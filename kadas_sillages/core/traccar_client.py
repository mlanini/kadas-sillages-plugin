# -*- coding: utf-8 -*-
"""
Synchronous HTTP client for the Traccar v6 REST API.
Uses QgsNetworkAccessManager to inherit KADAS proxy/VPN settings.

Usage pattern:
    client = TraccarClient("https://host", "user@mail.com", "pass")
    client.login()                          # raises TraccarAuthError on failure
    devices = client.get_devices()          # → List[Device]
    positions = client.get_positions()      # → List[Position]
    client.logout()
"""
from __future__ import annotations

import json
from email.utils import parsedate_to_datetime
from typing import List, Optional
from datetime import datetime, timezone

from qgis.PyQt.QtCore import QByteArray, QEventLoop, QUrl, QUrlQuery
from qgis.PyQt.QtNetwork import (
    QNetworkAccessManager,
    QNetworkCookieJar,
    QNetworkReply,
    QNetworkRequest,
)
from qgis.core import QgsNetworkAccessManager

from .models import Device, Position
from ..logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TraccarError(Exception):
    """Generic Traccar client error."""


class TraccarAuthError(TraccarError):
    """Invalid credentials or expired session."""


class TraccarNetworkError(TraccarError):
    """Network error (timeout, SSL, proxy, …)."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class TraccarClient:
    """
    Handles authentication and REST API calls for Traccar.

    All requests are synchronous (blocks on QEventLoop) for simplicity of
    integration with PyQGIS code. Slow operations (e.g. long historic
    tracks) should be run in a worker thread by the caller.
    """

    DEFAULT_TIMEOUT_MS = 15_000   # 15 secondi

    def __init__(self, server_url: str, username: str, password: str):
        self.server_url = server_url.rstrip("/")
        self.username = username
        self.password = password

        # Private NAM: NEVER touch the global KADAS/QGIS NAM.
        # Copy both the static proxy and the proxy factory from the global NAM
        # to inherit KADAS VPN/PAC configuration.
        self._cookie_jar = QNetworkCookieJar()
        self._nam = QNetworkAccessManager()
        self._nam.setCookieJar(self._cookie_jar)
        self._apply_kadas_proxy(self._nam)

        self._logged_in = False

    @staticmethod
    def _apply_kadas_proxy(nam: "QNetworkAccessManager") -> None:
        """
        Copy both the static proxy and the proxy factory from the global
        QgsNetworkAccessManager onto the provided NAM.
        """
        try:
            from qgis.core import QgsNetworkAccessManager
            qgis_nam = QgsNetworkAccessManager.instance()
            # Proxy factory (VPN, PAC, per-host proxy)
            factory = qgis_nam.proxyFactory()
            if factory is not None:
                nam.setProxyFactory(factory)
            else:
                # Static fallback proxy
                nam.setProxy(qgis_nam.proxy())
        except Exception as exc:
            log.debug("Unable to copy proxy configuration from KADAS: %s", exc)

    def get_proxy(self):
        """
        Return the QNetworkProxy to use for the WebSocket.
        Queries the proxy factory (when available) for the server URL,
        otherwise returns the static proxy from the private NAM.
        """
        from qgis.PyQt.QtNetwork import QNetworkProxy, QNetworkProxyQuery
        factory = self._nam.proxyFactory()
        if factory is not None:
            try:
                from qgis.PyQt.QtCore import QUrl as _QUrl
                query = QNetworkProxyQuery(_QUrl(self.server_url))
                proxies = factory.queryProxy(query)
                if proxies:
                    return proxies[0]
            except Exception:
                pass
        return self._nam.proxy()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def login(self) -> dict:
        """
        POST /api/session with form-urlencoded body.
        Traccar sets a session cookie that is kept in the cookie jar for
        subsequent calls.

        Returns:
            dict with the logged-in user data.

        Raises:
            TraccarAuthError: wrong credentials (HTTP 401/403).
            TraccarNetworkError: network issues.
        """
        url = f"{self.server_url}/api/session"
        body = QUrlQuery()
        body.addQueryItem("email", self.username)
        body.addQueryItem("password", self.password)
        encoded = body.toString(QUrl.FullyEncoded).encode("utf-8")

        request = self._build_request(url)
        request.setHeader(
            QNetworkRequest.ContentTypeHeader,
            "application/x-www-form-urlencoded",
        )

        reply = self._exec_sync(self._nam.post(request, QByteArray(encoded)))
        data = self._parse_reply(reply, expect_auth=True)

        self._logged_in = True
        log.info("Login successful: user=%s id=%s", data.get("name"), data.get("id"))
        return data

    def logout(self) -> None:
        """Issue DELETE /api/session and invalidate the local cookie."""
        if not self._logged_in:
            return
        url = f"{self.server_url}/api/session"
        request = self._build_request(url)
        reply = self._exec_sync(self._nam.deleteResource(request))
        try:
            self._parse_reply(reply)
        except TraccarError:
            pass  # ignora errori in logout
        finally:
            self._logged_in = False
            self._cookie_jar.setAllCookies([])
            log.info("Logout successful")

    def verify_session(self) -> dict:
        """GET /api/session — verify that the session is still active."""
        return self._get_json("/api/session")

    @property
    def session_cookie_header(self) -> str:
        """
        Return the ``Cookie`` header value for the current session.

        Required to authenticate the WebSocket, which in Qt5 does not
        automatically share cookies with QNetworkAccessManager.
        Format: "JSESSIONID=xxxx; ..."
        """
        from qgis.PyQt.QtCore import QUrl as _QUrl
        cookies = self._cookie_jar.cookiesForUrl(
            _QUrl(self.server_url)
        )
        if not cookies:
            return ""
        return "; ".join(
            f"{c.name().data().decode()if isinstance(c.name(), (bytes, bytearray)) else c.name()}="
            f"{c.value().data().decode() if isinstance(c.value(), (bytes, bytearray)) else c.value()}"
            for c in cookies
        )

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------

    def get_devices(self, all_devices: bool = True) -> List[Device]:
        """
        GET /api/devices

        Args:
            all_devices: if True appends ?all=true (requires admin permissions).

        Returns:
            List of Device.
        """
        params = {"all": "true"} if all_devices else {}
        data = self._get_json("/api/devices", params=params)
        devices = [Device.from_dict(d) for d in data]
        log.debug("Received %d devices", len(devices))
        return devices

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def get_positions(
        self,
        device_id: Optional[int] = None,
        from_dt: Optional[datetime] = None,
        to_dt: Optional[datetime] = None,
    ) -> List[Position]:
        """
        GET /api/positions

        Without parameters: last known positions for all devices.
        With device_id + from_dt + to_dt: historic positions for a device.

        Returns:
            List of Position.
        """
        params: dict = {}
        if device_id is not None:
            params["deviceId"] = str(device_id)
        if from_dt is not None:
            params["from"] = from_dt.isoformat()
        if to_dt is not None:
            params["to"] = to_dt.isoformat()

        data = self._get_json("/api/positions", params=params)
        positions = [Position.from_dict(p) for p in data]
        log.debug("Received %d positions", len(positions))
        return positions

    def get_route(
        self,
        device_id: int,
        from_dt: datetime,
        to_dt: datetime,
    ) -> List[Position]:
        """
        GET /api/reports/route — full track for reports.
        Includes interpolated points compared to get_positions.
        """
        params = {
            "deviceId": str(device_id),
            "from": from_dt.isoformat(),
            "to": to_dt.isoformat(),
        }
        data = self._get_json("/api/reports/route", params=params)
        return [Position.from_dict(p) for p in data]

    # ------------------------------------------------------------------
    # Server info
    # ------------------------------------------------------------------

    def get_server_info(self) -> dict:
        """GET /api/server — does not require authentication."""
        return self._get_json("/api/server")

    def get_server_time_offset(self) -> float:
        """
        Measure the clock difference between client and server.

        Issues GET /api/server and reads the ``Date`` HTTP response header
        (RFC 7231 standard, always present in Traccar).
        The returned value is:

            offset = t_server - t_client  (seconds, float)

        • offset > 0  → server clock is *ahead* of client
        • offset < 0  → server clock is *behind* client
        • |offset| < 2  → negligible difference

        Accounts for half the Round-Trip-Time (RTT) to improve accuracy
        (simplified NTP algorithm).

        Raises:
            TraccarNetworkError: network error.
            TraccarError: missing or unparseable Date header.
        """
        url = f"{self.server_url}/api/server"
        request = self._build_request(url)

        t_send = datetime.now(timezone.utc)
        reply = self._exec_sync(self._nam.get(request))
        t_recv = datetime.now(timezone.utc)

        # Read the Date header from the HTTP response
        date_header = bytes(reply.rawHeader(b"Date")).decode(errors="replace").strip()
        # Release the reply (parse before deleteLater)
        reply.deleteLater()

        if not date_header:
            raise TraccarError(
                "'Date' header missing from server response. "
                "Unable to determine server time."
            )

        try:
            t_server = parsedate_to_datetime(date_header)
        except Exception as exc:
            raise TraccarError(
                f"Unparseable 'Date' header: '{date_header}': {exc}"
            ) from exc

        # Estimate the moment the server processed the request:
        # midpoint of the round trip
        rtt = (t_recv - t_send).total_seconds()
        t_client_mid = t_send + (t_recv - t_send) / 2

        offset = (t_server - t_client_mid).total_seconds()
        log.debug(
            "Time sync: server=%s  client_mid=%s  RTT=%.3fs  offset=%.3fs",
            t_server.isoformat(), t_client_mid.isoformat(), rtt, offset,
        )
        return offset

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_json(self, path: str, params: Optional[dict] = None):
        url = f"{self.server_url}{path}"
        if params:
            q = QUrlQuery()
            for k, v in params.items():
                q.addQueryItem(k, v)
            url = f"{url}?{q.toString(QUrl.FullyEncoded)}"

        request = self._build_request(url)
        reply = self._exec_sync(self._nam.get(request))
        return self._parse_reply(reply)

    def _build_request(self, url: str) -> QNetworkRequest:
        req = QNetworkRequest(QUrl(url))
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        req.setRawHeader(b"Accept", b"application/json")
        # Timeout (Qt 5.15+)
        try:
            req.setTransferTimeout(self.DEFAULT_TIMEOUT_MS)
        except AttributeError:
            pass
        return req

    @staticmethod
    def _exec_sync(reply: QNetworkReply) -> QNetworkReply:
        """Block until the reply is complete using a QEventLoop."""
        if not reply.isFinished():
            loop = QEventLoop()
            reply.finished.connect(loop.quit)
            loop.exec_()
        return reply

    def _parse_reply(
        self,
        reply: QNetworkReply,
        expect_auth: bool = False,
    ):
        """
        Read and decode the response.

        Raises:
            TraccarAuthError: HTTP 401/403.
            TraccarNetworkError: Qt network error.
            TraccarError: other HTTP errors.
        """
        net_err = reply.error()
        if net_err not in (
            QNetworkReply.NoError,
            QNetworkReply.AuthenticationRequiredError,
        ):
            msg = reply.errorString()
            reply.deleteLater()
            raise TraccarNetworkError(f"Network error: {msg}")

        http_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        raw = bytes(reply.readAll())
        req_url = reply.url().toString()[:80]   # salva prima di deleteLater
        reply.deleteLater()

        log.debug(
            "HTTP %s → %s  (%d byte)",
            req_url,
            http_code,
            len(raw),
        )

        if http_code in (401, 403):
            raise TraccarAuthError(
                f"Invalid credentials or access denied (HTTP {http_code})"
            )

        if http_code and http_code >= 400:
            try:
                detail = json.loads(raw).get("message", raw.decode(errors="replace"))
            except Exception:
                detail = raw.decode(errors="replace")
            raise TraccarError(f"Server error HTTP {http_code}: {detail}")

        if not raw:
            return {}

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TraccarError(f"Non-JSON response: {exc}") from exc

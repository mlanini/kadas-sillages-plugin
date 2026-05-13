# -*- coding: utf-8 -*-
"""
Client HTTP sincrono per le REST API di Traccar v6.
Usa QgsNetworkAccessManager per ereditare proxy/VPN di KADAS.

Pattern utilizzo:
    client = TraccarClient("https://host", "user@mail.com", "pass")
    client.login()                          # → lancia TraccarAuthError se fallisce
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
# Eccezioni
# ---------------------------------------------------------------------------

class TraccarError(Exception):
    """Errore generico del client Traccar."""


class TraccarAuthError(TraccarError):
    """Credenziali non valide o sessione scaduta."""


class TraccarNetworkError(TraccarError):
    """Errore di rete (timeout, SSL, proxy, …)."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class TraccarClient:
    """
    Gestisce autenticazione e chiamate REST all'API Traccar.

    Tutte le richieste sono sincrone (blocca su QEventLoop) per semplicità
    d'integrazione con il codice PyQGIS. Le operazioni lente (es. storico
    tracce lungo) vengono eseguite in thread separato lato chiamante.
    """

    DEFAULT_TIMEOUT_MS = 15_000   # 15 secondi

    def __init__(self, server_url: str, username: str, password: str):
        self.server_url = server_url.rstrip("/")
        self.username = username
        self.password = password

        # NAM privato: NON toccare mai il NAM globale di KADAS/QGIS.
        # Copiamo proxy statico E proxy factory dal NAM globale per
        # ereditare la configurazione VPN/PAC di KADAS.
        self._cookie_jar = QNetworkCookieJar()
        self._nam = QNetworkAccessManager()
        self._nam.setCookieJar(self._cookie_jar)
        self._apply_kadas_proxy(self._nam)

        self._logged_in = False

    @staticmethod
    def _apply_kadas_proxy(nam: "QNetworkAccessManager") -> None:
        """
        Copia sul NAM fornito sia il proxy statico sia il proxy factory
        del QgsNetworkAccessManager globale di KADAS.
        """
        try:
            from qgis.core import QgsNetworkAccessManager
            qgis_nam = QgsNetworkAccessManager.instance()
            # Proxy factory (VPN, PAC, proxy per-host)
            factory = qgis_nam.proxyFactory()
            if factory is not None:
                nam.setProxyFactory(factory)
            else:
                # Proxy statico di fallback
                nam.setProxy(qgis_nam.proxy())
        except Exception as exc:
            log.debug("Impossibile copiare configurazione proxy da KADAS: %s", exc)

    def get_proxy(self):
        """
        Restituisce il QNetworkProxy da usare per il WebSocket.
        Interroga il proxy factory (se disponibile) per l'URL del server,
        altrimenti restituisce il proxy statico del NAM privato.
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
    # Autenticazione
    # ------------------------------------------------------------------

    def login(self) -> dict:
        """
        Esegue POST /api/session con form-urlencoded.
        Traccar imposta un cookie di sessione che viene conservato nel
        cookie jar per le chiamate successive.

        Returns:
            dict con i dati dell'utente loggato.

        Raises:
            TraccarAuthError: credenziali errate (HTTP 401/403).
            TraccarNetworkError: problemi di rete.
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
        log.info("Login riuscito: utente=%s id=%s", data.get("name"), data.get("id"))
        return data

    def logout(self) -> None:
        """Esegue DELETE /api/session e invalida il cookie locale."""
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
            log.info("Logout effettuato")

    def verify_session(self) -> dict:
        """GET /api/session — verifica che la sessione sia ancora attiva."""
        return self._get_json("/api/session")

    @property
    def session_cookie_header(self) -> str:
        """
        Restituisce il valore dell'header ``Cookie`` per la sessione corrente.

        Necessario per autenticare il WebSocket, che in Qt5 non condivide
        automaticamente i cookie con QNetworkAccessManager.
        Formato: "JSESSIONID=xxxx; ..."
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
    # Dispositivi
    # ------------------------------------------------------------------

    def get_devices(self, all_devices: bool = True) -> List[Device]:
        """
        GET /api/devices

        Args:
            all_devices: se True aggiunge ?all=true (richiede permessi admin).

        Returns:
            Lista di Device.
        """
        params = {"all": "true"} if all_devices else {}
        data = self._get_json("/api/devices", params=params)
        devices = [Device.from_dict(d) for d in data]
        log.debug("Ricevuti %d dispositivi", len(devices))
        return devices

    # ------------------------------------------------------------------
    # Posizioni
    # ------------------------------------------------------------------

    def get_positions(
        self,
        device_id: Optional[int] = None,
        from_dt: Optional[datetime] = None,
        to_dt: Optional[datetime] = None,
    ) -> List[Position]:
        """
        GET /api/positions

        Senza parametri: ultime posizioni note di tutti i dispositivi.
        Con device_id + from_dt + to_dt: storico posizioni del dispositivo.

        Returns:
            Lista di Position.
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
        log.debug("Ricevute %d posizioni", len(positions))
        return positions

    def get_route(
        self,
        device_id: int,
        from_dt: datetime,
        to_dt: datetime,
    ) -> List[Position]:
        """
        GET /api/reports/route — traccia completa per report.
        Include punti interpolati rispetto a get_positions.
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
        """GET /api/server — non richiede autenticazione."""
        return self._get_json("/api/server")

    def get_server_time_offset(self) -> float:
        """
        Misura la differenza di orologio tra client e server.

        Esegue GET /api/server e legge l'header HTTP ``Date`` della risposta
        (standard RFC 7231, sempre presente in Traccar).
        Il valore restituito è:

            offset = t_server - t_client  (secondi, float)

        • offset > 0  → il server è *avanti* rispetto al client
        • offset < 0  → il server è *indietro* rispetto al client
        • |offset| < 2  → differenza trascurabile

        Il metodo contabilizza la metà del Round-Trip-Time (RTT) per
        aumentare la precisione della stima (algoritmo NTP semplificato).

        Raises:
            TraccarNetworkError: errore di rete.
            TraccarError: header Date mancante o non parsabile.
        """
        url = f"{self.server_url}/api/server"
        request = self._build_request(url)

        t_send = datetime.now(timezone.utc)
        reply = self._exec_sync(self._nam.get(request))
        t_recv = datetime.now(timezone.utc)

        # Leggi l'header Date dalla risposta HTTP
        date_header = bytes(reply.rawHeader(b"Date")).decode(errors="replace").strip()
        # Rilascia la reply (parsare prima del deleteLater)
        reply.deleteLater()

        if not date_header:
            raise TraccarError(
                "Header 'Date' assente nella risposta del server. "
                "Impossible determinare l'orario del server."
            )

        try:
            t_server = parsedate_to_datetime(date_header)
        except Exception as exc:
            raise TraccarError(
                f"Header 'Date' non parsabile: '{date_header}': {exc}"
            ) from exc

        # Stima del momento in cui il server ha lavorato la richiesta:
        # punto medio del viaggio andata-ritorno
        rtt = (t_recv - t_send).total_seconds()
        t_client_mid = t_send + (t_recv - t_send) / 2

        offset = (t_server - t_client_mid).total_seconds()
        log.debug(
            "Time sync: server=%s  client_mid=%s  RTT=%.3fs  offset=%.3fs",
            t_server.isoformat(), t_client_mid.isoformat(), rtt, offset,
        )
        return offset

    # ------------------------------------------------------------------
    # Helpers interni
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
        """Blocca finché la risposta non è completa usando un QEventLoop."""
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
        Legge e decodifica la risposta.

        Raises:
            TraccarAuthError: HTTP 401/403.
            TraccarNetworkError: errore di rete Qt.
            TraccarError: altri errori HTTP.
        """
        net_err = reply.error()
        if net_err not in (
            QNetworkReply.NoError,
            QNetworkReply.AuthenticationRequiredError,
        ):
            msg = reply.errorString()
            reply.deleteLater()
            raise TraccarNetworkError(f"Errore di rete: {msg}")

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
                f"Credenziali non valide o accesso negato (HTTP {http_code})"
            )

        if http_code and http_code >= 400:
            try:
                detail = json.loads(raw).get("message", raw.decode(errors="replace"))
            except Exception:
                detail = raw.decode(errors="replace")
            raise TraccarError(f"Errore server HTTP {http_code}: {detail}")

        if not raw:
            return {}

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TraccarError(f"Risposta non JSON: {exc}") from exc

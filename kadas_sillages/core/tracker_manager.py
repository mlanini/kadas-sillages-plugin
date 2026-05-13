# -*- coding: utf-8 -*-
"""
TrackerManager: manages live tracking toward Traccar.

Dual-mode automatic strategy
-----------------------------
1. Attempts WebSocket connection first (ideal mode, server-push).
2. If the WebSocket does not connect within _WS_CONNECT_TIMEOUT_MS, or
   receives HTTP 200 instead of 101 (typical corporate proxy blocking the
   upgrade), automatically switches to **HTTP polling** mode (GET /api/positions
   every _POLL_INTERVAL_MS milliseconds).
3. The active mode is exposed via `transport_mode` ("websocket" / "polling").

The Traccar WebSocket sends JSON messages:
    {"devices": [...], "positions": [...], "events": [...]}
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from qgis.PyQt.QtCore import QObject, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtNetwork import QAbstractSocket
try:
    from qgis.PyQt.QtWebSockets import QWebSocket
except ModuleNotFoundError:
    from PyQt5.QtWebSockets import QWebSocket  # KADAS/standalone PyQt5

from .connection_manager import ConnectionManager
from .map_layer_manager import MapLayerManager
from .models import Device, Position
from ..logger import get_logger

# Lazy import of LayerStyler to avoid circular dependencies
_LayerStyler = None


def _get_styler_class():
    global _LayerStyler
    if _LayerStyler is None:
        from .layer_styler import LayerStyler
        _LayerStyler = LayerStyler
    return _LayerStyler

log = get_logger(__name__)

# --- Timing constants ---
_WS_CONNECT_TIMEOUT_MS  = 8_000   # max wait for WS handshake before switching to polling
_RECONNECT_INTERVAL_MS  = 10_000  # pause between WS reconnect attempts after disconnect
_PING_INTERVAL_MS       = 25_000  # WS keepalive (Traccar closes idle after ~30s)
_POLL_INTERVAL_MS       = 5_000   # HTTP polling interval in fallback mode


class TrackerManager(QObject):
    """
    Manages live tracking toward Traccar with automatic fallback.

    WebSocket mode (preferred):
        Server-push connection, real-time updates.

    HTTP Polling mode (automatic fallback):
        Activated when the WebSocket fails within _WS_CONNECT_TIMEOUT_MS
        or receives HTTP 200 (corporate proxy blocking WebSocket).
        Calls GET /api/positions every _POLL_INTERVAL_MS ms.

    The active mode is readable via `transport_mode`.
    """

    # Signals
    position_updated      = pyqtSignal(int, float, float)  # device_id, lat, lon
    device_status_changed = pyqtSignal(int, str)            # device_id, status
    tracking_started      = pyqtSignal()
    tracking_stopped      = pyqtSignal()
    ws_error              = pyqtSignal(str)
    # Emitted when the transport mode changes
    transport_mode_changed = pyqtSignal(str)               # "websocket" | "polling"

    def __init__(self, connection_manager: ConnectionManager, parent=None):
        super().__init__(parent)
        self._conn    = connection_manager
        self._map     = MapLayerManager()
        self._styler  = None
        self._ws: Optional[QWebSocket] = None
        self._running = False

        # Modalità di trasporto attiva
        self._transport: str = "websocket"  # "websocket" | "polling"
        # Last position id per-device (avoids re-plotting already-seen positions in polling)
        self._last_pos_id: dict = {}

        # WS connection timeout timer → switch to polling
        self._ws_timeout = QTimer(self)
        self._ws_timeout.setSingleShot(True)
        self._ws_timeout.setInterval(_WS_CONNECT_TIMEOUT_MS)
        self._ws_timeout.timeout.connect(self._on_ws_connect_timeout)

        # WS reconnect timer (after disconnect)
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._open_websocket)

        # WS keepalive ping timer
        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(_PING_INTERVAL_MS)
        self._ping_timer.timeout.connect(self._send_ping)

        # HTTP polling timer
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_positions)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start tracking: create layers, apply styles, attempt WS."""
        if self._running:
            return
        if not self._conn.is_connected:
            log.warning("TrackerManager.start(): not connected to server")
            return

        self._running = True
        self._transport = "websocket"
        self._last_pos_id.clear()
        self._map.create_layers()

        for device in self._conn.devices:
            self._map.initialize_device(device)

        LayerStyler = _get_styler_class()
        self._styler = LayerStyler(self._map._layer_pos, self._map._layer_trk)
        self._styler.apply(self._conn.devices)

        self._open_websocket()
        self.tracking_started.emit()
        log.info("Tracking started (attempting WebSocket)")

    def stop(self) -> None:
        """Stop tracking: close WS/polling and remove layers."""
        if not self._running:
            return
        self._running = False
        self._ws_timeout.stop()
        self._ping_timer.stop()
        self._reconnect_timer.stop()
        self._poll_timer.stop()
        self._close_websocket()
        self._map.remove_layers()
        self._styler = None
        self.tracking_stopped.emit()
        log.info("Tracking stopped (mode: %s)", self._transport)

    @property
    def is_tracking(self) -> bool:
        return self._running

    @property
    def transport_mode(self) -> str:
        """'websocket' or 'polling'."""
        return self._transport

    @property
    def connection_manager(self) -> ConnectionManager:
        return self._conn

    @property
    def map_layer_manager(self) -> MapLayerManager:
        return self._map

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    def _open_websocket(self) -> None:
        """Open (or reopen) the WebSocket connection to Traccar."""
        if not self._running:
            return

        server_url = self._conn.client.server_url if self._conn.client else ""
        if not server_url:
            log.error("Server URL not available for WebSocket")
            self._switch_to_polling("missing server URL")
            return

        ws_url = server_url.replace("https://", "wss://").replace("http://", "ws://")
        ws_url = f"{ws_url}/api/socket"

        if self._ws is not None:
            self._close_websocket()

        self._ws = QWebSocket()

        # Proxy: QWebSocket Qt5 non eredita dal NAM
        try:
            proxy = self._conn.client.get_proxy()
            self._ws.setProxy(proxy)
            log.debug("WS proxy: %s", proxy.hostName() or "none")
        except Exception as exc:
            log.debug("WS proxy not set: %s", exc)

        self._ws.connected.connect(self._on_ws_connected)
        self._ws.disconnected.connect(self._on_ws_disconnected)
        self._ws.textMessageReceived.connect(self._on_ws_message)
        if hasattr(self._ws, "errorOccurred"):
            self._ws.errorOccurred.connect(self._on_ws_error)
        else:
            self._ws.error.connect(self._on_ws_error)

        # Explicit session cookie (Qt5: WS does not share cookies with NAM)
        from qgis.PyQt.QtNetwork import QNetworkRequest as _QNR
        ws_req = _QNR(QUrl(ws_url))
        try:
            cookie_hdr = self._conn.client.session_cookie_header
            if cookie_hdr:
                ws_req.setRawHeader(b"Cookie", cookie_hdr.encode())
                log.debug("WS cookie: %s", cookie_hdr[:80])
            else:
                log.warning("No session cookie for WebSocket")
        except Exception as exc:
            log.debug("Unable to read session cookie: %s", exc)

        log.debug("Opening WebSocket: %s", ws_url)
        self._ws_timeout.start()   # start countdown → fallback to polling
        self._ws.open(ws_req)

    def _close_websocket(self) -> None:
        if self._ws is None:
            return
        try:
            self._ws.connected.disconnect()
            self._ws.disconnected.disconnect()
            self._ws.textMessageReceived.disconnect()
            if hasattr(self._ws, "errorOccurred"):
                self._ws.errorOccurred.disconnect()
            else:
                self._ws.error.disconnect()
        except Exception:
            pass
        self._ws.close()
        self._ws.deleteLater()
        self._ws = None

    def _schedule_reconnect(self) -> None:
        if self._running and not self._reconnect_timer.isActive():
            log.info("WS reconnect in %d ms…", _RECONNECT_INTERVAL_MS)
            self._reconnect_timer.start(_RECONNECT_INTERVAL_MS)

    def _send_ping(self) -> None:
        if self._ws and self._ws.state() == QAbstractSocket.ConnectedState:
            self._ws.ping()

    # ------------------------------------------------------------------
    # WebSocket slots
    # ------------------------------------------------------------------

    def _on_ws_connected(self) -> None:
        self._ws_timeout.stop()   # handshake succeeded, cancel fallback timer
        log.info("WebSocket connected (mode: websocket)")
        self._ping_timer.start()
        self._transport = "websocket"
        self._poll_timer.stop()
        self.transport_mode_changed.emit("websocket")

    def _on_ws_disconnected(self) -> None:
        log.warning("WebSocket disconnected")
        self._ping_timer.stop()
        # If we were in WS mode, schedule reconnect
        if self._transport == "websocket":
            self._schedule_reconnect()

    def _on_ws_error(self, error_code) -> None:
        msg = self._ws.errorString() if self._ws else str(error_code)
        log.error("WebSocket error: %s", msg)
        self._ping_timer.stop()
        self._ws_timeout.stop()
        # HTTP 200/Unhandled status → proxy blocks WS → switch to polling immediately
        if "200" in msg or "Unhandled http" in msg or "handshake" in msg.lower():
            self._switch_to_polling(f"proxy blocks WebSocket ({msg})")
        else:
            self.ws_error.emit(msg)
            self._schedule_reconnect()

    def _on_ws_connect_timeout(self) -> None:
        """The WebSocket did not connect within the timeout: switch to polling."""
        log.warning("WebSocket connection timeout (%d ms)", _WS_CONNECT_TIMEOUT_MS)
        self._switch_to_polling("WebSocket connection timeout")

    # ------------------------------------------------------------------
    # HTTP polling fallback
    # ------------------------------------------------------------------

    def _switch_to_polling(self, reason: str) -> None:
        """Abandon the WebSocket and activate HTTP polling."""
        if not self._running:
            return
        self._close_websocket()
        self._reconnect_timer.stop()
        self._ws_timeout.stop()
        self._transport = "polling"
        msg = f"Falling back to HTTP polling ({reason}). Refresh every {_POLL_INTERVAL_MS // 1000}s."
        log.warning(msg)
        self.ws_error.emit(msg)
        self.transport_mode_changed.emit("polling")
        # Prima poll immediata, poi timer regolare
        self._poll_positions()
        self._poll_timer.start()

    def _poll_positions(self) -> None:
        """Call GET /api/positions and update layers with the results."""
        if not self._running or not self._conn.is_connected:
            return
        try:
            positions = self._conn.client.get_positions()
        except Exception as exc:
            log.warning("Position polling failed: %s", exc)
            return

        for pos in positions:
            # Skip if unchanged since last seen
            if self._last_pos_id.get(pos.device_id) == pos.id:
                continue
            self._last_pos_id[pos.device_id] = pos.id

            device = self._conn.get_device_by_id(pos.device_id)
            if device is None or not device.visible:
                continue
            self._map.update_position(device, pos)
            self.position_updated.emit(pos.device_id, pos.latitude, pos.longitude)
            log.debug(
                "Poll pos: %s → (%.5f, %.5f)",
                device.name, pos.latitude, pos.longitude,
            )

    # ------------------------------------------------------------------
    # WebSocket message processing
    # ------------------------------------------------------------------

    def _on_ws_message(self, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError as exc:
            log.warning("Invalid WS message: %s", exc)
            return

        for dev_data in data.get("devices", []):
            self._handle_device_update(dev_data)
        for pos_data in data.get("positions", []):
            self._handle_position_update(pos_data)
        for evt in data.get("events", []):
            log.debug("Traccar event: deviceId=%s type=%s",
                      evt.get("deviceId"), evt.get("type"))

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    def _handle_device_update(self, dev_data: dict) -> None:
        device_id = dev_data.get("id")
        if device_id is None:
            return
        device = self._conn.get_device_by_id(device_id)
        if device is None:
            try:
                device = Device.from_dict(dev_data)
                self._conn._devices.append(device)
            except Exception as exc:
                log.warning("Unable to parse device from WS: %s", exc)
                return
        old_status = device.status
        device.status = dev_data.get("status", device.status)
        if device.status != old_status:
            self.device_status_changed.emit(device_id, device.status)
            log.debug("Device %s: %s → %s", device.name, old_status, device.status)
        self._map.initialize_device(device)

    def _handle_position_update(self, pos_data: dict) -> None:
        device_id = pos_data.get("deviceId")
        if device_id is None:
            return
        device = self._conn.get_device_by_id(device_id)
        if device is None or not device.visible:
            return
        try:
            pos = Position.from_dict(pos_data)
        except Exception as exc:
            log.warning("Unable to parse position from WS: %s", exc)
            return

        # Filter stale positions (server/client clock offset)
        offset = self._conn.server_time_offset
        now_utc = datetime.now(timezone.utc)
        if pos.server_time is not None:
            local_equiv = pos.server_time - timedelta(seconds=offset)
            age_s = (now_utc - local_equiv).total_seconds()
            if age_s > 300:
                log.debug("Stale position ignored: %s age=%.0fs", device.name, age_s)
                return

        self._map.update_position(device, pos)
        self.position_updated.emit(device_id, pos.latitude, pos.longitude)
        log.debug("WS pos: %s → (%.5f, %.5f) %.1f kn",
                  device.name, pos.latitude, pos.longitude, pos.speed)

    def refresh_style(self) -> None:
        """Recalculate and apply renderers after a style change."""
        if self._styler is not None:
            self._styler.apply(self._conn.devices)

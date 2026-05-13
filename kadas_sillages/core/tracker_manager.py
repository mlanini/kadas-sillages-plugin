# -*- coding: utf-8 -*-
"""
TrackerManager: gestisce il live tracking verso Traccar.

Strategia duale automatica
--------------------------
1. Tenta prima la connessione WebSocket (modalità ideale, push dal server).
2. Se il WebSocket non riesce entro _WS_CONNECT_TIMEOUT_MS oppure riceve
   HTTP 200 invece di 101 (tipico proxy aziendale che blocca l'upgrade),
   passa automaticamente in modalità **polling HTTP** (GET /api/positions
   ogni _POLL_INTERVAL_MS millisecondi).
3. La modalità attiva è esposta da `transport_mode` ("websocket" / "polling").

Il WebSocket Traccar invia messaggi JSON:
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

# Import lazy di LayerStyler per evitare dipendenze circolari
_LayerStyler = None


def _get_styler_class():
    global _LayerStyler
    if _LayerStyler is None:
        from .layer_styler import LayerStyler
        _LayerStyler = LayerStyler
    return _LayerStyler

log = get_logger(__name__)

# --- Costanti timing ---
_WS_CONNECT_TIMEOUT_MS  = 8_000   # max attesa handshake WS prima di passare a polling
_RECONNECT_INTERVAL_MS  = 10_000  # pausa tra tentativi WS dopo disconnessione
_PING_INTERVAL_MS       = 25_000  # keepalive WS (Traccar chiude idle dopo ~30s)
_POLL_INTERVAL_MS       = 5_000   # intervallo polling HTTP in modalità fallback


class TrackerManager(QObject):
    """
    Gestisce il live tracking verso Traccar con fallback automatico.

    Modalità WebSocket (preferita):
        Connessione push, aggiornamenti in tempo reale.

    Modalità Polling HTTP (fallback automatico):
        Attivata se il WebSocket non riesce entro _WS_CONNECT_TIMEOUT_MS
        oppure riceve HTTP 200 (proxy aziendale che blocca il WebSocket).
        Chiama GET /api/positions ogni _POLL_INTERVAL_MS ms.

    La modalità attiva si legge con `transport_mode`.
    """

    # Segnali
    position_updated      = pyqtSignal(int, float, float)  # device_id, lat, lon
    device_status_changed = pyqtSignal(int, str)            # device_id, status
    tracking_started      = pyqtSignal()
    tracking_stopped      = pyqtSignal()
    ws_error              = pyqtSignal(str)
    # Emesso quando cambia la modalità di trasporto
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
        # ID ultima posizione per-device (evita ri-plot di posizioni già viste in polling)
        self._last_pos_id: dict = {}

        # Timer timeout connessione WS → switch a polling
        self._ws_timeout = QTimer(self)
        self._ws_timeout.setSingleShot(True)
        self._ws_timeout.setInterval(_WS_CONNECT_TIMEOUT_MS)
        self._ws_timeout.timeout.connect(self._on_ws_connect_timeout)

        # Timer riconnessione WS (dopo disconnessione)
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._open_websocket)

        # Timer ping keepalive WS
        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(_PING_INTERVAL_MS)
        self._ping_timer.timeout.connect(self._send_ping)

        # Timer polling HTTP
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_positions)

    # ------------------------------------------------------------------
    # API pubblica
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Avvia il tracking: crea layer, applica stili, tenta WS."""
        if self._running:
            return
        if not self._conn.is_connected:
            log.warning("TrackerManager.start(): non connesso al server")
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
        log.info("Tracking avviato (tentativo WebSocket)")

    def stop(self) -> None:
        """Ferma il tracking: chiude WS/polling e rimuove i layer."""
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
        log.info("Tracking fermato (modalità: %s)", self._transport)

    @property
    def is_tracking(self) -> bool:
        return self._running

    @property
    def transport_mode(self) -> str:
        """'websocket' oppure 'polling'."""
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
        """Apre (o riapre) la connessione WebSocket a Traccar."""
        if not self._running:
            return

        server_url = self._conn.client.server_url if self._conn.client else ""
        if not server_url:
            log.error("URL server non disponibile per il WebSocket")
            self._switch_to_polling("URL server mancante")
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
            log.debug("WS proxy: %s", proxy.hostName() or "nessuno")
        except Exception as exc:
            log.debug("Proxy WS non impostato: %s", exc)

        self._ws.connected.connect(self._on_ws_connected)
        self._ws.disconnected.connect(self._on_ws_disconnected)
        self._ws.textMessageReceived.connect(self._on_ws_message)
        if hasattr(self._ws, "errorOccurred"):
            self._ws.errorOccurred.connect(self._on_ws_error)
        else:
            self._ws.error.connect(self._on_ws_error)

        # Cookie di sessione esplicito (Qt5: WS non condivide cookie con NAM)
        from qgis.PyQt.QtNetwork import QNetworkRequest as _QNR
        ws_req = _QNR(QUrl(ws_url))
        try:
            cookie_hdr = self._conn.client.session_cookie_header
            if cookie_hdr:
                ws_req.setRawHeader(b"Cookie", cookie_hdr.encode())
                log.debug("WS cookie: %s", cookie_hdr[:80])
            else:
                log.warning("Nessun cookie di sessione per WebSocket")
        except Exception as exc:
            log.debug("Impossibile leggere cookie sessione: %s", exc)

        log.debug("Apertura WebSocket: %s", ws_url)
        self._ws_timeout.start()   # avvia conto alla rovescia → fallback polling
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
            log.info("Riconnessione WS tra %d ms…", _RECONNECT_INTERVAL_MS)
            self._reconnect_timer.start(_RECONNECT_INTERVAL_MS)

    def _send_ping(self) -> None:
        if self._ws and self._ws.state() == QAbstractSocket.ConnectedState:
            self._ws.ping()

    # ------------------------------------------------------------------
    # Slot WebSocket
    # ------------------------------------------------------------------

    def _on_ws_connected(self) -> None:
        self._ws_timeout.stop()   # handshake riuscito, annulla timer fallback
        log.info("WebSocket connesso (modalità: websocket)")
        self._ping_timer.start()
        self._transport = "websocket"
        self._poll_timer.stop()
        self.transport_mode_changed.emit("websocket")

    def _on_ws_disconnected(self) -> None:
        log.warning("WebSocket disconnesso")
        self._ping_timer.stop()
        # Se eravamo in modalità WS, pianifica riconnessione
        if self._transport == "websocket":
            self._schedule_reconnect()

    def _on_ws_error(self, error_code) -> None:
        msg = self._ws.errorString() if self._ws else str(error_code)
        log.error("Errore WebSocket: %s", msg)
        self._ping_timer.stop()
        self._ws_timeout.stop()
        # HTTP 200/Unhandled status → proxy blocca WS → passa subito a polling
        if "200" in msg or "Unhandled http" in msg or "handshake" in msg.lower():
            self._switch_to_polling(f"proxy blocca WebSocket ({msg})")
        else:
            self.ws_error.emit(msg)
            self._schedule_reconnect()

    def _on_ws_connect_timeout(self) -> None:
        """Il WebSocket non si è connesso entro il timeout: passa a polling."""
        log.warning("Timeout connessione WebSocket (%d ms)", _WS_CONNECT_TIMEOUT_MS)
        self._switch_to_polling("timeout connessione WebSocket")

    # ------------------------------------------------------------------
    # Polling HTTP fallback
    # ------------------------------------------------------------------

    def _switch_to_polling(self, reason: str) -> None:
        """Abbandona il WebSocket e attiva il polling HTTP."""
        if not self._running:
            return
        self._close_websocket()
        self._reconnect_timer.stop()
        self._ws_timeout.stop()
        self._transport = "polling"
        msg = f"Fallback a polling HTTP ({reason}). Aggiornamento ogni {_POLL_INTERVAL_MS // 1000}s."
        log.warning(msg)
        self.ws_error.emit(msg)
        self.transport_mode_changed.emit("polling")
        # Prima poll immediata, poi timer regolare
        self._poll_positions()
        self._poll_timer.start()

    def _poll_positions(self) -> None:
        """Chiama GET /api/positions e aggiorna i layer con i risultati."""
        if not self._running or not self._conn.is_connected:
            return
        try:
            positions = self._conn.client.get_positions()
        except Exception as exc:
            log.warning("Polling posizioni fallito: %s", exc)
            return

        for pos in positions:
            # Salta se non è cambiata rispetto all'ultima vista
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
    # Elaborazione messaggi WebSocket
    # ------------------------------------------------------------------

    def _on_ws_message(self, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError as exc:
            log.warning("Messaggio WS non valido: %s", exc)
            return

        for dev_data in data.get("devices", []):
            self._handle_device_update(dev_data)
        for pos_data in data.get("positions", []):
            self._handle_position_update(pos_data)
        for evt in data.get("events", []):
            log.debug("Evento Traccar: deviceId=%s type=%s",
                      evt.get("deviceId"), evt.get("type"))

    # ------------------------------------------------------------------
    # Handlers messaggi
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
                log.warning("Impossibile parsare device dal WS: %s", exc)
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
            log.warning("Impossibile parsare posizione dal WS: %s", exc)
            return

        # Filtra posizioni stale (offset orologio server/client)
        offset = self._conn.server_time_offset
        now_utc = datetime.now(timezone.utc)
        if pos.server_time is not None:
            local_equiv = pos.server_time - timedelta(seconds=offset)
            age_s = (now_utc - local_equiv).total_seconds()
            if age_s > 300:
                log.debug("Posizione stale ignorata: %s age=%.0fs", device.name, age_s)
                return

        self._map.update_position(device, pos)
        self.position_updated.emit(device_id, pos.latitude, pos.longitude)
        log.debug("WS pos: %s → (%.5f, %.5f) %.1f kn",
                  device.name, pos.latitude, pos.longitude, pos.speed)

    def refresh_style(self) -> None:
        """Ricalcola e applica i renderer dopo un cambio di stile."""
        if self._styler is not None:
            self._styler.apply(self._conn.devices)

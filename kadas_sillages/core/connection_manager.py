# -*- coding: utf-8 -*-
"""
ConnectionManager: coordina autenticazione, stato sessione e ciclo di vita
del client Traccar. È il punto di contatto tra la GUI e il core.

Segnali Qt emessi:
    connected(user_info: dict)   — login riuscito
    disconnected()               — logout o perdita sessione
    error(message: str)          — errore di connessione/rete
    devices_updated(devices)     — lista device aggiornata
"""
from __future__ import annotations

from typing import List, Optional

from qgis.PyQt.QtCore import QObject, pyqtSignal

from .traccar_client import TraccarClient, TraccarAuthError, TraccarNetworkError, TraccarError
from .settings import PluginSettings
from .models import Device
from ..logger import get_logger

log = get_logger(__name__)

# Soglia oltre cui l'offset è segnalato come problema (secondi)
_TIME_WARN_THRESHOLD_S  = 30.0
_TIME_ERROR_THRESHOLD_S = 120.0


class ConnectionManager(QObject):
    """Gestisce il ciclo di vita della connessione a Traccar."""

    connected = pyqtSignal(dict)          # user info dict
    disconnected = pyqtSignal()
    error = pyqtSignal(str)
    devices_updated = pyqtSignal(list)    # List[Device]
    # Emesso dopo il login: (offset_secondi, messaggio_leggibile)
    time_offset_detected = pyqtSignal(float, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client: Optional[TraccarClient] = None
        self._user_info: dict = {}
        self._devices: List[Device] = []
        self._server_time_offset: float = 0.0  # secondi: server - client

    # ------------------------------------------------------------------
    # Proprietà
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client._logged_in

    @property
    def client(self) -> Optional[TraccarClient]:
        return self._client

    @property
    def devices(self) -> List[Device]:
        return list(self._devices)

    @property
    def user_info(self) -> dict:
        return dict(self._user_info)

    @property
    def server_time_offset(self) -> float:
        """Offset in secondi tra orologio server e orologio locale (server - client)."""
        return self._server_time_offset

    # ------------------------------------------------------------------
    # Connessione / disconnessione
    # ------------------------------------------------------------------

    def connect_to_server(
        self,
        server_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> bool:
        """
        Tenta il login a Traccar.

        Se url/user/pass non vengono passati li legge da PluginSettings.
        Emette `connected` in caso di successo, `error` in caso di fallimento.

        Returns:
            True se il login è riuscito.
        """
        url = server_url or PluginSettings.server_url()
        user = username or PluginSettings.username()
        pwd = password or PluginSettings.password()

        if not all([url, user, pwd]):
            msg = "Configurazione incompleta: URL, utente e password sono obbligatori."
            log.warning(msg)
            self.error.emit(msg)
            return False

        # Disconnetti eventuale sessione precedente
        if self.is_connected:
            self.disconnect_from_server()

        try:
            self._client = TraccarClient(url, user, pwd)
            self._user_info = self._client.login()
            log.info(
                "Connesso a %s come %s",
                url,
                self._user_info.get("name", user),
            )
            self.connected.emit(self._user_info)
            # Verifica sincronia orologi client/server
            self.check_time_sync()
            # Carica subito la lista device
            self.refresh_devices()
            return True

        except TraccarAuthError as exc:
            self._client = None
            msg = f"Autenticazione fallita: {exc}"
            log.error(msg)
            self.error.emit(msg)
            return False

        except TraccarNetworkError as exc:
            self._client = None
            msg = f"Errore di rete: {exc}"
            log.error(msg)
            self.error.emit(msg)
            return False

        except TraccarError as exc:
            self._client = None
            msg = f"Errore server: {exc}"
            log.error(msg)
            self.error.emit(msg)
            return False

    def disconnect_from_server(self) -> None:
        """Esegue il logout e libera le risorse."""
        if self._client is not None:
            try:
                self._client.logout()
            except Exception as exc:
                log.warning("Errore durante il logout: %s", exc)
            finally:
                self._client = None
                self._user_info = {}
                self._devices = []
                self._server_time_offset = 0.0
                self.disconnected.emit()
                log.info("Disconnesso dal server Traccar")

    # ------------------------------------------------------------------
    # Device
    # ------------------------------------------------------------------

    def refresh_devices(self) -> List[Device]:
        """
        Aggiorna la lista dispositivi da server.
        Emette `devices_updated` con la lista aggiornata.
        """
        if not self.is_connected:
            return []
        try:
            # Salva le impostazioni visive correnti (personalizzazioni utente)
            saved_visuals: dict = {
                d.id: {
                    "track_color":      d.track_color,
                    "track_width":      d.track_width,
                    "track_max_points": d.track_max_points,
                    "show_label":       d.show_label,
                    "icon_path":        d.icon_path,
                    "visible":          d.visible,
                }
                for d in self._devices
            }

            self._devices = self._client.get_devices()
            # Applica valori visivi predefiniti ai device nuovi
            self._apply_default_visuals()
            # Ripristina le personalizzazioni utente per i device già noti
            for d in self._devices:
                if d.id in saved_visuals:
                    for attr, value in saved_visuals[d.id].items():
                        setattr(d, attr, value)

            self.devices_updated.emit(self._devices)
            return self._devices
        except TraccarError as exc:
            msg = f"Errore aggiornamento dispositivi: {exc}"
            log.error(msg)
            self.error.emit(msg)
            return []

    def get_device_by_id(self, device_id: int) -> Optional[Device]:
        for d in self._devices:
            if d.id == device_id:
                return d
        return None

    def update_device_visuals(self, device_id: int, **kwargs) -> None:
        """
        Aggiorna le proprietà visive di un device (track_color, track_width,
        track_max_points, show_label, icon_path, visible).
        """
        device = self.get_device_by_id(device_id)
        if device is None:
            return
        allowed = {
            "track_color", "track_width", "track_max_points",
            "show_label", "icon_path", "visible",
        }
        for k, v in kwargs.items():
            if k in allowed:
                setattr(device, k, v)
            else:
                log.warning("Campo visivo non riconosciuto: %s", k)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def check_time_sync(self) -> float:
        """
        Misura l'offset tra l'orologio locale e quello del server Traccar.

        Emette ``time_offset_detected(offset, msg)`` se la differenza supera
        la soglia di attenzione.

        Returns:
            L'offset misurato in secondi (server - client).
            0.0 se la misura non riesce.
        """
        if self._client is None:
            return 0.0
        try:
            offset = self._client.get_server_time_offset()
        except Exception as exc:
            log.warning("Impossibile misurare la sincronizzazione oraria: %s", exc)
            return 0.0

        self._server_time_offset = offset
        abs_off = abs(offset)
        direction = "avanti" if offset > 0 else "indietro"

        if abs_off >= _TIME_ERROR_THRESHOLD_S:
            msg = (
                f"⚠ Orologio del server è {direction} di {abs_off:.0f} s rispetto al "
                f"client. Il rendering live potrebbe essere fortemente compromesso. "
                f"Sincronizzare NTP su client e/o server."
            )
            log.error(msg)
            self.time_offset_detected.emit(offset, msg)

        elif abs_off >= _TIME_WARN_THRESHOLD_S:
            msg = (
                f"Attenzione: orologio server {direction} di {abs_off:.0f} s. "
                f"Il rendering live potrebbe avere ritardi visibili. "
                f"Verificare NTP su client e server."
            )
            log.warning(msg)
            self.time_offset_detected.emit(offset, msg)

        else:
            log.info(
                "Sincronizzazione oraria OK: offset=%.2f s (soglia >%ds)",
                offset, int(_TIME_WARN_THRESHOLD_S),
            )

        return offset

    def _apply_default_visuals(self) -> None:
        """Applica i valori predefiniti dai settings ai device che non li hanno ancora."""
        color = PluginSettings.default_track_color()
        width = PluginSettings.default_track_width()
        max_pts = PluginSettings.default_track_max_points()
        for d in self._devices:
            d.track_color = color
            d.track_width = width
            d.track_max_points = max_pts

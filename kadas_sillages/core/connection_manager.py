# -*- coding: utf-8 -*-
"""
ConnectionManager: coordinates authentication, session state and the lifecycle
of the Traccar client. Acts as the bridge between the GUI and the core.

Qt signals emitted:
    connected(user_info: dict)   — login succeeded
    disconnected()               — logout or session lost
    error(message: str)          — connection/network error
    devices_updated(devices)     — device list refreshed
"""
from __future__ import annotations

from typing import List, Optional

from qgis.PyQt.QtCore import QObject, pyqtSignal

from .traccar_client import TraccarClient, TraccarAuthError, TraccarNetworkError, TraccarError
from .settings import PluginSettings
from .models import Device
from ..logger import get_logger

log = get_logger(__name__)

# Threshold above which the offset is flagged as a problem (seconds)
_TIME_WARN_THRESHOLD_S  = 30.0
_TIME_ERROR_THRESHOLD_S = 120.0


class ConnectionManager(QObject):
    """Manages the connection lifecycle to Traccar."""

    connected = pyqtSignal(dict)          # user info dict
    disconnected = pyqtSignal()
    error = pyqtSignal(str)
    devices_updated = pyqtSignal(list)    # List[Device]
    # Emitted after login: (offset_seconds, human_readable_message)
    time_offset_detected = pyqtSignal(float, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client: Optional[TraccarClient] = None
        self._user_info: dict = {}
        self._devices: List[Device] = []
        self._server_time_offset: float = 0.0  # seconds: server - client

    # ------------------------------------------------------------------
    # Properties
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
        """Offset in seconds between server and local clock (server - client)."""
        return self._server_time_offset

    # ------------------------------------------------------------------
    # Connect / disconnect
    # ------------------------------------------------------------------

    def connect_to_server(
        self,
        server_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> bool:
        """
        Attempt login to Traccar.

        If url/user/pass are not provided they are read from PluginSettings.
        Emits `connected` on success, `error` on failure.

        Returns:
            True if login succeeded.
        """
        url = server_url or PluginSettings.server_url()
        user = username or PluginSettings.username()
        pwd = password or PluginSettings.password()

        if not all([url, user, pwd]):
            msg = "Incomplete configuration: URL, username and password are required."
            log.warning(msg)
            self.error.emit(msg)
            return False

        # Disconnect any existing session
        if self.is_connected:
            self.disconnect_from_server()

        try:
            self._client = TraccarClient(url, user, pwd)
            self._user_info = self._client.login()
            log.info(
                "Connected to %s as %s",
                url,
                self._user_info.get("name", user),
            )
            self.connected.emit(self._user_info)
            # Check client/server clock sync
            self.check_time_sync()
            # Immediately load device list
            self.refresh_devices()
            return True

        except TraccarAuthError as exc:
            self._client = None
            msg = f"Authentication failed: {exc}"
            log.error(msg)
            self.error.emit(msg)
            return False

        except TraccarNetworkError as exc:
            self._client = None
            msg = f"Network error: {exc}"
            log.error(msg)
            self.error.emit(msg)
            return False

        except TraccarError as exc:
            self._client = None
            msg = f"Server error: {exc}"
            log.error(msg)
            self.error.emit(msg)
            return False

    def disconnect_from_server(self) -> None:
        """Perform logout and release resources."""
        if self._client is not None:
            try:
                self._client.logout()
            except Exception as exc:
                log.warning("Error during logout: %s", exc)
            finally:
                self._client = None
                self._user_info = {}
                self._devices = []
                self._server_time_offset = 0.0
                self.disconnected.emit()
                log.info("Disconnected from Traccar server")

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------

    def refresh_devices(self) -> List[Device]:
        """
        Refresh the device list from the server.
        Emits `devices_updated` with the updated list.
        """
        if not self.is_connected:
            return []
        try:
            # Save current visual settings (user customisations)
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
            # Apply default visuals to new devices
            self._apply_default_visuals()
            # Restore user customisations for already-known devices
            for d in self._devices:
                if d.id in saved_visuals:
                    for attr, value in saved_visuals[d.id].items():
                        setattr(d, attr, value)

            self.devices_updated.emit(self._devices)
            return self._devices
        except TraccarError as exc:
            msg = f"Device list update error: {exc}"
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
        Update the visual properties of a device (track_color, track_width,
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
                log.warning("Unrecognised visual field: %s", k)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def check_time_sync(self) -> float:
        """
        Measure the offset between the local clock and the Traccar server clock.

        Emits ``time_offset_detected(offset, msg)`` when the difference exceeds
        the warning threshold.

        Returns:
            Measured offset in seconds (server - client).
            0.0 if the measurement fails.
        """
        if self._client is None:
            return 0.0
        try:
            offset = self._client.get_server_time_offset()
        except Exception as exc:
            log.warning("Unable to measure time synchronisation: %s", exc)
            return 0.0

        self._server_time_offset = offset
        abs_off = abs(offset)
        direction = "ahead" if offset > 0 else "behind"

        if abs_off >= _TIME_ERROR_THRESHOLD_S:
            msg = (
                f"⚠ Server clock is {direction} by {abs_off:.0f} s compared to "
                f"client. Live rendering may be severely affected. "
                f"Sync NTP on both client and server."
            )
            log.error(msg)
            self.time_offset_detected.emit(offset, msg)

        elif abs_off >= _TIME_WARN_THRESHOLD_S:
            msg = (
                f"Warning: server clock is {direction} by {abs_off:.0f} s. "
                f"Live rendering may show visible delays. "
                f"Check NTP on client and server."
            )
            log.warning(msg)
            self.time_offset_detected.emit(offset, msg)

        else:
            log.info(
                "Time sync OK: offset=%.2f s (threshold >%ds)",
                offset, int(_TIME_WARN_THRESHOLD_S),
            )

        return offset

    def _apply_default_visuals(self) -> None:
        """Apply default visual settings to devices that do not have them yet."""
        color = PluginSettings.default_track_color()
        width = PluginSettings.default_track_width()
        max_pts = PluginSettings.default_track_max_points()
        for d in self._devices:
            d.track_color = color
            d.track_width = width
            d.track_max_points = max_pts

# -*- coding: utf-8 -*-
"""
Main DockWidget for the KadasSillages plugin.
Contains: connection toolbar, device list, visual controls.
"""
from __future__ import annotations

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.connection_manager import ConnectionManager
from ..core.tracker_manager import TrackerManager
from ..core.settings import PluginSettings
from ..logger import get_logger

log = get_logger(__name__)


class MainDock(QDockWidget):
    """Main side panel for the KadasSillages plugin."""

    # Emitted when the dock is closed via the X button
    closed = pyqtSignal()

    def __init__(self, iface, parent=None):
        super().__init__("Sillages – Live Tracking", parent)
        self.iface = iface
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        # ConnectionManager e TrackerManager
        self._conn = ConnectionManager(self)
        self._conn.connected.connect(self._on_connected)
        self._conn.disconnected.connect(self._on_disconnected)
        self._conn.error.connect(self._on_error)
        self._conn.devices_updated.connect(self._on_devices_updated)
        self._conn.time_offset_detected.connect(self._on_time_offset_detected)

        self._tracker = TrackerManager(self._conn, self)
        self._tracker.tracking_started.connect(self._on_tracking_started)
        self._tracker.tracking_stopped.connect(self._on_tracking_stopped)
        self._tracker.ws_error.connect(self._on_ws_error)
        self._tracker.device_status_changed.connect(self._on_device_status_changed)
        self._tracker.transport_mode_changed.connect(self._on_transport_mode_changed)

        self._build_ui()

        # Auto-connect if configured
        if PluginSettings.auto_connect() and PluginSettings.is_configured():
            self._do_connect()

    # ------------------------------------------------------------------
    # Public properties (used by TrackerManager in Step 3)
    # ------------------------------------------------------------------

    @property
    def connection_manager(self) -> ConnectionManager:
        return self._conn

    @property
    def tracker_manager(self) -> TrackerManager:
        return self._tracker

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # --- Connection toolbar ---
        toolbar_row = QWidget()
        h = QHBoxLayout(toolbar_row)
        h.setContentsMargins(0, 0, 0, 0)

        self._btn_connect = QPushButton("Connect")
        self._btn_connect.setCheckable(True)
        self._btn_connect.clicked.connect(self._on_connect_btn_clicked)

        self._btn_refresh = QPushButton("↻")
        self._btn_refresh.setFixedWidth(28)
        self._btn_refresh.setToolTip("Refresh device list")
        self._btn_refresh.setEnabled(False)
        self._btn_refresh.clicked.connect(self._on_refresh_clicked)

        self._btn_track = QPushButton("▶ Live")
        self._btn_track.setCheckable(True)
        self._btn_track.setEnabled(False)
        self._btn_track.setToolTip("Start/stop live tracking on the map")
        self._btn_track.clicked.connect(self._on_track_btn_clicked)

        self._btn_export = QPushButton("⬇ History")
        self._btn_export.setEnabled(False)
        self._btn_export.setToolTip("Export historic track from server")
        self._btn_export.clicked.connect(self._on_export_clicked)

        self._btn_settings = QPushButton("⚙")
        self._btn_settings.setFixedWidth(28)
        self._btn_settings.setToolTip("Connection settings")
        self._btn_settings.clicked.connect(self._on_settings_clicked)

        self._btn_about = QPushButton("ℹ")
        self._btn_about.setFixedWidth(28)
        self._btn_about.setToolTip("About Sillages")
        self._btn_about.clicked.connect(self._on_about_clicked)

        h.addWidget(self._btn_connect)
        h.addWidget(self._btn_refresh)
        h.addWidget(self._btn_track)
        h.addWidget(self._btn_export)
        h.addWidget(self._btn_settings)
        h.addWidget(self._btn_about)
        layout.addWidget(toolbar_row)

        # --- Connected user info ---
        self._lbl_user = QLabel("")
        self._lbl_user.setStyleSheet("font-size: 10px; color: #555;")
        self._lbl_user.setVisible(False)
        layout.addWidget(self._lbl_user)

        # --- Content area: QStackedWidget with placeholder and DeviceListWidget ---
        self._stack = QStackedWidget()

        # Page 0: placeholder (not connected)
        self._placeholder = QLabel(
            "<i>No devices.<br>"
            "Configure the connection and press <b>Connect</b>.</i>"
        )
        self._placeholder.setWordWrap(True)
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._stack.addWidget(self._placeholder)   # index 0

        # Page 1: DeviceListWidget (lazy, created on first connect)
        self._device_list = None
        self._stack.setCurrentIndex(0)
        layout.addWidget(self._stack, 1)

        # --- Status bar ---
        self._status = QLabel("Not connected")
        self._status.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(self._status)

        # --- Log box ---
        self._log_box = QTextEdit()
        self._log_box.setReadOnly(True)
        self._log_box.setFixedHeight(90)
        self._log_box.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #d4d4d4; "
            "font-family: Consolas, monospace; font-size: 10px; }"
        )
        self._log_box.setToolTip("Connection event log")
        layout.addWidget(self._log_box)

        self.setWidget(root)

    # ------------------------------------------------------------------
    # Slots – buttons
    # ------------------------------------------------------------------

    def _on_connect_btn_clicked(self, checked: bool):
        if checked:
            if not PluginSettings.is_configured():
                self._on_settings_clicked()
                if not PluginSettings.is_configured():
                    self._btn_connect.setChecked(False)
                    return
            self._do_connect()
        else:
            self._do_disconnect()

    def _on_refresh_clicked(self):
        self._conn.refresh_devices()

    def _on_track_btn_clicked(self, checked: bool):
        if checked:
            self._tracker.start()
        else:
            self._tracker.stop()

    def _on_export_clicked(self):
        from .export_dialog import ExportDialog
        dlg = ExportDialog(self._conn, self)
        dlg.exec_()

    def _on_settings_clicked(self):
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.exec_()

    def _on_about_clicked(self):
        from .about_dialog import AboutDialog
        dlg = AboutDialog(self)
        dlg.exec_()

    # ------------------------------------------------------------------
    # Slots – ConnectionManager
    # ------------------------------------------------------------------

    def _on_connected(self, user_info: dict):
        name = user_info.get("name") or user_info.get("email", "")
        server = PluginSettings.server_url()
        self._btn_connect.setText("Disconnect")
        self._btn_connect.setChecked(True)
        self._btn_refresh.setEnabled(True)
        self._btn_track.setEnabled(True)
        self._btn_export.setEnabled(True)
        self._lbl_user.setText(f"👤 {name}  |  {server}")
        self._lbl_user.setVisible(True)
        self.set_status("Connected", "#2E7D32")
        self._log(f"✔ Connected as {name} → {server}", "ok")

    def _on_disconnected(self):
        # Stop tracking if active
        if self._tracker.is_tracking:
            self._tracker.stop()
        self._btn_connect.setText("Connect")
        self._btn_connect.setChecked(False)
        self._btn_refresh.setEnabled(False)
        self._btn_track.setEnabled(False)
        self._btn_track.setChecked(False)
        self._btn_export.setEnabled(False)
        self._lbl_user.setVisible(False)
        self._stack.setCurrentIndex(0)
        self._placeholder.setText(
            "<i>No devices.<br>"
            "Configure the connection and press <b>Connect</b>.</i>"
        )
        self.set_status("Not connected", "gray")
        self._log("Disconnected from server.", "warning")

    def _on_error(self, message: str):
        self._btn_connect.setChecked(self._conn.is_connected)
        self._btn_connect.setText("Disconnect" if self._conn.is_connected else "Connect")
        self.set_status(f"⚠ {message}", "#B71C1C")
        self._log(f"⚠ Error: {message}", "error")

    def _on_devices_updated(self, devices: list):
        count = len(devices)
        self._log(f"↻ Device list updated: {count} found.", "info")
        if count == 0:
            self._stack.setCurrentIndex(0)
            self._placeholder.setText("<i>No devices found on server.</i>")
            return

        # Create DeviceListWidget on first connect
        if self._device_list is None:
            from .device_list_widget import DeviceListWidget
            self._device_list = DeviceListWidget(self._tracker, self)
            self._device_list.style_changed.connect(self._on_device_style_changed)
            self._device_list.visibility_changed.connect(self._on_device_visibility)
            self._device_list.track_cleared.connect(
                lambda did: log.debug("Track cleared: device_id=%d", did)
            )
            self._device_list.center_on_device.connect(self._on_center_on_device)
            self._stack.addWidget(self._device_list)   # index 1

        self._device_list.populate(devices)
        self._stack.setCurrentIndex(1)
        log.debug("Device list updated: %d devices", count)

    def _on_tracking_started(self):
        self._btn_track.setText("⏹ Stop")
        self._btn_track.setChecked(True)
        self.set_status("Tracking started (connecting…)", "#1565C0")
        self._log("▶ Tracking started — attempting WebSocket…", "info")

    def _on_tracking_stopped(self):
        self._btn_track.setText("▶ Live")
        self._btn_track.setChecked(False)
        status = "Connected" if self._conn.is_connected else "Not connected"
        color  = "#2E7D32" if self._conn.is_connected else "gray"
        self.set_status(status, color)
        self._log("⏹ Live tracking stopped.", "warning")

    def _on_ws_error(self, message: str):
        self.set_status(f"⚠ WebSocket: {message}", "#E65100")
        self._log(f"⚠ WebSocket: {message}", "error")

    def _on_transport_mode_changed(self, mode: str):
        if mode == "polling":
            self.set_status("⏱ HTTP polling active (WebSocket blocked by proxy)", "#E65100")
            self._log("⏱ HTTP polling mode active: WebSocket unavailable (corporate proxy). Refresh every 5s.", "warning")
        else:
            self.set_status("Live tracking active (WebSocket)", "#1565C0")
            self._log("✔ WebSocket restored — real-time updates active.", "ok")

    def _on_time_offset_detected(self, offset: float, message: str):
        """Show a clock-skew warning in the log box."""
        abs_off = abs(offset)
        level = "error" if abs_off >= 120 else "warning"
        self._log(f"🕐 {message}", level)

    def _on_center_on_device(self, lat: float, lon: float):
        """Centre the map on the device (EPSG:4326) at scale 1:50,000."""
        try:
            from qgis.core import (
                QgsCoordinateReferenceSystem,
                QgsCoordinateTransform,
                QgsPointXY,
                QgsProject,
            )
            canvas = self.iface.mapCanvas()
            map_crs = canvas.mapSettings().destinationCrs()
            src_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            tr = QgsCoordinateTransform(src_crs, map_crs, QgsProject.instance())
            pt = tr.transform(QgsPointXY(lon, lat))
            canvas.setCenter(pt)
            canvas.zoomScale(50000)
            canvas.refresh()
            log.debug("Map centred on lat=%.6f lon=%.6f scale 1:50000", lat, lon)
        except Exception as exc:  # pragma: no cover
            log.warning("Unable to centre map: %s", exc)

    def _on_device_status_changed(self, device_id: int, status: str):
        if self._device_list is not None:
            self._device_list.update_device_status(device_id, status)

    def _on_device_style_changed(self, device_id: int):
        """Called when the user saves the DeviceStyleDialog."""
        # Aggiorna swatch nella lista
        device = self._conn.get_device_by_id(device_id)
        if device and self._device_list:
            self._device_list.update_device_style(device)
        # Ricalcola renderer QGIS
        self._tracker.refresh_style()

    def _on_device_visibility(self, device_id: int, visible: bool):
        """Update `visible` on the device model and re-render."""
        self._conn.update_device_visuals(device_id, visible=visible)
        # If tracking is active, triggerRepaint is already handled by the renderer
        if self._tracker.is_tracking:
            self._tracker.refresh_style()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _do_connect(self):
        self.set_status("Connecting…", "orange")
        self._log(f"→ Connecting to {PluginSettings.server_url()} …", "info")
        self._btn_connect.setEnabled(False)
        try:
            self._conn.connect_to_server()
        finally:
            self._btn_connect.setEnabled(True)

    def _do_disconnect(self):
        if self._tracker.is_tracking:
            self._tracker.stop()
        self._conn.disconnect_from_server()

    def set_status(self, message: str, color: str = "gray"):
        self._status.setText(message)
        self._status.setStyleSheet(f"color: {color}; font-size: 10px;")

    # HTML colours per log level
    _LOG_COLORS = {
        "info":    "#d4d4d4",
        "ok":      "#4ec9b0",
        "warning": "#ce9178",
        "error":   "#f44747",
        "debug":   "#858585",
    }

    def _log(self, message: str, level: str = "info") -> None:
        """Append a coloured line to the log box and to the Python logger."""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        color = self._LOG_COLORS.get(level, "#d4d4d4")
        self._log_box.append(
            f"<span style='color:#858585;'>[{ts}]</span> "
            f"<span style='color:{color};'>{message}</span>"
        )
        getattr(log, level if level in ("info", "warning", "error", "debug") else "info")(message)

    # ------------------------------------------------------------------
    # Close override
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        # Stop tracker and disconnect before closing
        if self._tracker.is_tracking:
            self._tracker.stop()
        if self._conn.is_connected:
            self._conn.disconnect_from_server()
        self.closed.emit()
        super().closeEvent(event)

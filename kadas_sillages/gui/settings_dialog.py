# -*- coding: utf-8 -*-
"""
Traccar connection settings dialog.
Reads/writes via PluginSettings (QgsSettings).
"""
from __future__ import annotations

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from ..core.settings import PluginSettings
from ..logger import get_logger

log = get_logger(__name__)


class SettingsDialog(QDialog):
    """Modal dialog for configuring the Traccar connection and default options."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sillages – Settings")
        self.setMinimumWidth(380)
        self._build_ui()
        self._load()

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ----- Connection group -----
        grp_conn = QGroupBox("Traccar Server")
        form_conn = QFormLayout(grp_conn)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://traccar.intelligeo.net")
        form_conn.addRow("Server URL:", self._url_edit)

        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("admin@example.com")
        form_conn.addRow("Username (email):", self._user_edit)

        self._pass_edit = QLineEdit()
        self._pass_edit.setEchoMode(QLineEdit.Password)
        form_conn.addRow("Password:", self._pass_edit)

        self._auto_connect_cb = QCheckBox("Auto-connect on startup")
        form_conn.addRow("", self._auto_connect_cb)

        layout.addWidget(grp_conn)

        # ----- Default track values group -----
        grp_track = QGroupBox("Default Track Settings")
        form_track = QFormLayout(grp_track)

        self._color_edit = QLineEdit()
        self._color_edit.setPlaceholderText("#0000FF")
        form_track.addRow("Colour (hex):", self._color_edit)

        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 20)
        self._width_spin.setSuffix(" px")
        form_track.addRow("Track width:", self._width_spin)

        self._max_points_spin = QSpinBox()
        self._max_points_spin.setRange(10, 10000)
        self._max_points_spin.setSingleStep(50)
        self._max_points_spin.setSuffix(" pts")
        form_track.addRow("Max track length:", self._max_points_spin)

        layout.addWidget(grp_track)

        # ----- Proxy note -----
        note = QLabel(
            "<small>Network proxy settings are managed automatically by "
            "KADAS/QGIS. No additional configuration is required for "
            "environments with a corporate proxy or VPN.</small>"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        # ----- Buttons -----
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def _load(self):
        s = PluginSettings
        self._url_edit.setText(s.server_url())
        self._user_edit.setText(s.username())
        self._pass_edit.setText(s.password())
        self._auto_connect_cb.setChecked(s.auto_connect())
        self._color_edit.setText(s.default_track_color())
        self._width_spin.setValue(s.default_track_width())
        self._max_points_spin.setValue(s.default_track_max_points())

    def _save(self):
        s = PluginSettings
        s.set_server_url(self._url_edit.text().strip())
        s.set_username(self._user_edit.text().strip())
        s.set_password(self._pass_edit.text())
        s.set_auto_connect(self._auto_connect_cb.isChecked())

        color = self._color_edit.text().strip() or "#0000FF"
        s.set_default_track_color(color)
        s.set_default_track_width(self._width_spin.value())
        s.set_default_track_max_points(self._max_points_spin.value())

        log.debug(
            "Settings saved: url=%s user=%s auto_connect=%s",
            s.server_url(),
            s.username(),
            s.auto_connect(),
        )
        self.accept()

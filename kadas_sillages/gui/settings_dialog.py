# -*- coding: utf-8 -*-
"""
Dialog impostazioni di connessione a Traccar.
Legge/scrive tramite PluginSettings (QgsSettings).
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
    """Dialog modale per configurare la connessione a Traccar e le opzioni predefinite."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sillages – Impostazioni")
        self.setMinimumWidth(380)
        self._build_ui()
        self._load()

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ----- Gruppo connessione -----
        grp_conn = QGroupBox("Server Traccar")
        form_conn = QFormLayout(grp_conn)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://traccar.intelligeo.net")
        form_conn.addRow("URL server:", self._url_edit)

        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("admin@example.com")
        form_conn.addRow("Utente (email):", self._user_edit)

        self._pass_edit = QLineEdit()
        self._pass_edit.setEchoMode(QLineEdit.Password)
        form_conn.addRow("Password:", self._pass_edit)

        self._auto_connect_cb = QCheckBox("Connetti automaticamente all'avvio")
        form_conn.addRow("", self._auto_connect_cb)

        layout.addWidget(grp_conn)

        # ----- Gruppo valori predefiniti traccia -----
        grp_track = QGroupBox("Impostazioni traccia predefinite")
        form_track = QFormLayout(grp_track)

        self._color_edit = QLineEdit()
        self._color_edit.setPlaceholderText("#0000FF")
        form_track.addRow("Colore (hex):", self._color_edit)

        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 20)
        self._width_spin.setSuffix(" px")
        form_track.addRow("Spessore traccia:", self._width_spin)

        self._max_points_spin = QSpinBox()
        self._max_points_spin.setRange(10, 10000)
        self._max_points_spin.setSingleStep(50)
        self._max_points_spin.setSuffix(" punti")
        form_track.addRow("Lunghezza max traccia:", self._max_points_spin)

        layout.addWidget(grp_track)

        # ----- Note proxy -----
        note = QLabel(
            "<small>Il proxy di rete viene gestito automaticamente dalle "
            "impostazioni KADAS/QGIS. Non è necessaria alcuna configurazione "
            "aggiuntiva per ambienti con proxy aziendale o VPN.</small>"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        # ----- Pulsanti -----
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
            "Impostazioni salvate: url=%s user=%s auto_connect=%s",
            s.server_url(),
            s.username(),
            s.auto_connect(),
        )
        self.accept()

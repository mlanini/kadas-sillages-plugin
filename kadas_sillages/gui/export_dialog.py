# -*- coding: utf-8 -*-
"""
ExportDialog: dialog per esportare la traccia storica di un dispositivo Traccar.

Permette di selezionare:
  • Dispositivo (da lista)
  • Intervallo date (da / a)
  • Formato output: layer QGIS (traccia), layer QGIS (punti), GeoJSON, GPX, CSV
  • Percorso file (per output su disco)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import List

from qgis.PyQt.QtCore import QDateTime, Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QProgressDialog,
    QApplication,
)

from ..core.models import Device
from ..logger import get_logger

log = get_logger(__name__)


class ExportDialog(QDialog):
    """Dialog modale per l'esportazione dello storico tracce."""

    def __init__(self, connection_manager, parent=None):
        super().__init__(parent)
        self._conn = connection_manager
        self.setWindowTitle("Sillages – Esporta traccia storica")
        self.setMinimumWidth(420)
        self._build_ui()
        self._populate_devices()

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ----- Dispositivo -----
        grp_dev = QGroupBox("Dispositivo")
        form_dev = QFormLayout(grp_dev)
        self._device_combo = QComboBox()
        form_dev.addRow("Dispositivo:", self._device_combo)
        layout.addWidget(grp_dev)

        # ----- Intervallo temporale -----
        grp_time = QGroupBox("Intervallo temporale (UTC)")
        form_time = QFormLayout(grp_time)

        now = QDateTime.currentDateTimeUtc()
        yesterday = now.addDays(-1)

        self._from_dt = QDateTimeEdit(yesterday)
        self._from_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._from_dt.setCalendarPopup(True)

        self._to_dt = QDateTimeEdit(now)
        self._to_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._to_dt.setCalendarPopup(True)

        form_time.addRow("Da:", self._from_dt)
        form_time.addRow("A:",  self._to_dt)

        # Shortcuts
        shortcuts = QWidget()
        h_sc = QHBoxLayout(shortcuts)
        h_sc.setContentsMargins(0, 0, 0, 0)
        for label, delta_hours in [("Ultima ora", 1), ("Ultime 6h", 6),
                                    ("Ultime 24h", 24), ("Ultima settimana", 168)]:
            btn = QPushButton(label)
            btn.setFixedHeight(22)
            btn.clicked.connect(lambda _, dh=delta_hours: self._set_range(dh))
            h_sc.addWidget(btn)
        form_time.addRow("Rapido:", shortcuts)
        layout.addWidget(grp_time)

        # ----- Formato output -----
        grp_fmt = QGroupBox("Formato output")
        v_fmt = QVBoxLayout(grp_fmt)

        self._rb_layer_track  = QRadioButton("Layer QGIS – Traccia (LineString nel progetto)")
        self._rb_layer_points = QRadioButton("Layer QGIS – Punti (MultiPoint nel progetto)")
        self._rb_geojson      = QRadioButton("File GeoJSON")
        self._rb_gpx          = QRadioButton("File GPX")
        self._rb_csv          = QRadioButton("File CSV")
        self._rb_layer_track.setChecked(True)

        for rb in (self._rb_layer_track, self._rb_layer_points,
                   self._rb_geojson, self._rb_gpx, self._rb_csv):
            v_fmt.addWidget(rb)
            rb.toggled.connect(self._on_format_changed)

        # Riga percorso file (abilitata solo per formati file)
        file_row = QWidget()
        h_file = QHBoxLayout(file_row)
        h_file.setContentsMargins(0, 0, 0, 0)
        self._file_edit = QLineEdit()
        self._file_edit.setPlaceholderText("Seleziona percorso file…")
        self._btn_browse_file = QPushButton("…")
        self._btn_browse_file.setFixedWidth(28)
        self._btn_browse_file.clicked.connect(self._browse_file)
        h_file.addWidget(self._file_edit, 1)
        h_file.addWidget(self._btn_browse_file)
        v_fmt.addWidget(file_row)
        self._file_row = file_row
        self._file_row.setEnabled(False)

        layout.addWidget(grp_fmt)

        # ----- Pulsanti -----
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        self._buttons.button(QDialogButtonBox.Ok).setText("Esporta")
        self._buttons.accepted.connect(self._do_export)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    # ------------------------------------------------------------------
    # Populate
    # ------------------------------------------------------------------

    def _populate_devices(self):
        self._device_combo.clear()
        devices = self._conn.devices if self._conn else []
        for d in sorted(devices, key=lambda x: x.name.lower()):
            self._device_combo.addItem(
                f"[{d.status}] {d.name}", userData=d.id
            )
        if not devices:
            self._device_combo.addItem("(nessun dispositivo disponibile)", userData=None)
            self._buttons.button(QDialogButtonBox.Ok).setEnabled(False)

    # ------------------------------------------------------------------
    # Slot
    # ------------------------------------------------------------------

    def _set_range(self, hours: int):
        now = QDateTime.currentDateTimeUtc()
        self._from_dt.setDateTime(now.addSecs(-hours * 3600))
        self._to_dt.setDateTime(now)

    def _on_format_changed(self):
        file_fmt = self._rb_geojson.isChecked() or self._rb_gpx.isChecked() or self._rb_csv.isChecked()
        self._file_row.setEnabled(file_fmt)

    def _browse_file(self):
        if self._rb_geojson.isChecked():
            filt = "GeoJSON (*.geojson *.json)"
            ext = ".geojson"
        elif self._rb_gpx.isChecked():
            filt = "GPX (*.gpx)"
            ext = ".gpx"
        else:
            filt = "CSV (*.csv)"
            ext = ".csv"

        path, _ = QFileDialog.getSaveFileName(self, "Salva file", "", filt)
        if path:
            if not path.lower().endswith(ext):
                path += ext
            self._file_edit.setText(path)

    def _do_export(self):
        device_id = self._device_combo.currentData()
        if device_id is None:
            return

        device = self._conn.get_device_by_id(device_id)
        if device is None:
            QMessageBox.warning(self, "Errore", "Dispositivo non trovato.")
            return

        from_dt = self._from_dt.dateTime().toPyDateTime().replace(tzinfo=timezone.utc)
        to_dt   = self._to_dt.dateTime().toPyDateTime().replace(tzinfo=timezone.utc)

        if from_dt >= to_dt:
            QMessageBox.warning(self, "Errore", "La data 'Da' deve essere precedente a 'A'.")
            return

        is_file_fmt = self._rb_geojson.isChecked() or self._rb_gpx.isChecked() or self._rb_csv.isChecked()
        if is_file_fmt and not self._file_edit.text().strip():
            QMessageBox.warning(self, "Errore", "Seleziona un percorso file di destinazione.")
            return

        # Progress dialog
        prog = QProgressDialog(
            f"Download posizioni per {device.name}…", "Annulla", 0, 0, self
        )
        prog.setWindowModality(Qt.WindowModal)
        prog.show()
        QApplication.processEvents()

        try:
            from ..core.exporter import Exporter
            exp = Exporter(self._conn.client)

            if self._rb_layer_track.isChecked():
                lyr = exp.export_to_layer(device, from_dt, to_dt, as_track=True)
                msg = f"Traccia aggiunta al progetto come layer '{lyr.name()}'" if lyr else "Nessuna posizione trovata."
            elif self._rb_layer_points.isChecked():
                lyr = exp.export_to_layer(device, from_dt, to_dt, as_track=False)
                msg = f"Punti aggiunti al progetto come layer '{lyr.name()}'" if lyr else "Nessuna posizione trovata."
            else:
                fpath = self._file_edit.text().strip()
                fmt = "geojson" if self._rb_geojson.isChecked() else ("gpx" if self._rb_gpx.isChecked() else "csv")
                ok = exp.export_to_file(device, from_dt, to_dt, fpath, fmt)
                msg = f"File salvato: {fpath}" if ok else "Esportazione fallita. Controlla i log."

            prog.close()
            QMessageBox.information(self, "Esportazione completata", msg)
            self.accept()

        except Exception as exc:
            prog.close()
            log.error("Errore esportazione: %s", exc)
            QMessageBox.critical(self, "Errore", f"Esportazione fallita:\n{exc}")

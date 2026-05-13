# -*- coding: utf-8 -*-
"""
ExportDialog: dialog for exporting the historic track of a Traccar device.

Allows selecting:
  • Device (from list)
  • Date range (from / to)
  • Output format: QGIS layer (track), QGIS layer (points), GeoJSON, GPX, CSV
  • File path (for disk output)
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
    """Modal dialog for exporting historic tracks."""

    def __init__(self, connection_manager, parent=None):
        super().__init__(parent)
        self._conn = connection_manager
        self.setWindowTitle("Sillages – Export Historic Track")
        self.setMinimumWidth(420)
        self._build_ui()
        self._populate_devices()

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ----- Device -----
        grp_dev = QGroupBox("Device")
        form_dev = QFormLayout(grp_dev)
        self._device_combo = QComboBox()
        form_dev.addRow("Device:", self._device_combo)
        layout.addWidget(grp_dev)

        # ----- Time range -----
        grp_time = QGroupBox("Time Range (UTC)")
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
        for label, delta_hours in [("Last hour", 1), ("Last 6h", 6),
                                    ("Last 24h", 24), ("Last week", 168)]:
            btn = QPushButton(label)
            btn.setFixedHeight(22)
            btn.clicked.connect(lambda _, dh=delta_hours: self._set_range(dh))
            h_sc.addWidget(btn)
        form_time.addRow("Quick:", shortcuts)
        layout.addWidget(grp_time)

        # ----- Output format -----
        grp_fmt = QGroupBox("Output Format")
        v_fmt = QVBoxLayout(grp_fmt)

        self._rb_layer_track  = QRadioButton("QGIS Layer – Track (LineString in project)")
        self._rb_layer_points = QRadioButton("QGIS Layer – Points (MultiPoint in project)")
        self._rb_geojson      = QRadioButton("GeoJSON file")
        self._rb_gpx          = QRadioButton("GPX file")
        self._rb_csv          = QRadioButton("CSV file")
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
        self._file_edit.setPlaceholderText("Select output file path…")
        self._btn_browse_file = QPushButton("…")
        self._btn_browse_file.setFixedWidth(28)
        self._btn_browse_file.clicked.connect(self._browse_file)
        h_file.addWidget(self._file_edit, 1)
        h_file.addWidget(self._btn_browse_file)
        v_fmt.addWidget(file_row)
        self._file_row = file_row
        self._file_row.setEnabled(False)

        layout.addWidget(grp_fmt)

        # ----- Buttons -----
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        self._buttons.button(QDialogButtonBox.Ok).setText("Export")
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
            self._device_combo.addItem("(no devices available)", userData=None)
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

        path, _ = QFileDialog.getSaveFileName(self, "Save file", "", filt)
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
            QMessageBox.warning(self, "Error", "Device not found.")
            return

        from_dt = self._from_dt.dateTime().toPyDateTime().replace(tzinfo=timezone.utc)
        to_dt   = self._to_dt.dateTime().toPyDateTime().replace(tzinfo=timezone.utc)

        if from_dt >= to_dt:
            QMessageBox.warning(self, "Error", "The 'From' date must be earlier than 'To'.")
            return

        is_file_fmt = self._rb_geojson.isChecked() or self._rb_gpx.isChecked() or self._rb_csv.isChecked()
        if is_file_fmt and not self._file_edit.text().strip():
            QMessageBox.warning(self, "Error", "Please select a destination file path.")
            return

        # Progress dialog
        prog = QProgressDialog(
            f"Downloading positions for {device.name}…", "Cancel", 0, 0, self
        )
        prog.setWindowModality(Qt.WindowModal)
        prog.show()
        QApplication.processEvents()

        try:
            from ..core.exporter import Exporter
            exp = Exporter(self._conn.client)

            if self._rb_layer_track.isChecked():
                lyr = exp.export_to_layer(device, from_dt, to_dt, as_track=True)
                msg = f"Track added to project as layer '{lyr.name()}'" if lyr else "No positions found."
            elif self._rb_layer_points.isChecked():
                lyr = exp.export_to_layer(device, from_dt, to_dt, as_track=False)
                msg = f"Points added to project as layer '{lyr.name()}'" if lyr else "No positions found."
            else:
                fpath = self._file_edit.text().strip()
                fmt = "geojson" if self._rb_geojson.isChecked() else ("gpx" if self._rb_gpx.isChecked() else "csv")
                ok = exp.export_to_file(device, from_dt, to_dt, fpath, fmt)
                msg = f"File saved: {fpath}" if ok else "Export failed. Check the logs."

            prog.close()
            QMessageBox.information(self, "Export complete", msg)
            self.accept()

        except Exception as exc:
            prog.close()
            log.error("Export error: %s", exc)
            QMessageBox.critical(self, "Error", f"Export failed:\n{exc}")

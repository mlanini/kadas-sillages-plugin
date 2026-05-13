# -*- coding: utf-8 -*-
"""
DeviceListWidget: widget che mostra la lista dei dispositivi Traccar
con indicatore di stato, controllo visibilità e accesso rapido alle opzioni
di stile.

Ogni riga mostra:
  [●] [vis] NomeDevice   [stato]   [⚙ Stile] [✕ Traccia]

Colori stato:
  ● verde  → online
  ● grigio → offline / unknown
"""
from __future__ import annotations

from typing import Dict, List

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QIcon, QPixmap
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.models import Device
from ..logger import get_logger

log = get_logger(__name__)

# Colori LED stato
_STATUS_COLOR = {
    "online":  "#43A047",   # verde
    "offline": "#9E9E9E",   # grigio
    "unknown": "#9E9E9E",
}


def _status_dot(status: str) -> str:
    color = _STATUS_COLOR.get(status, "#9E9E9E")
    return f'<span style="color:{color};font-size:16px;">●</span>'


class DeviceRowWidget(QWidget):
    """Singola riga dispositivo nella lista."""

    # Segnali emessi verso il DeviceListWidget
    visibility_changed = pyqtSignal(int, bool)    # device_id, visible
    style_requested    = pyqtSignal(int)          # device_id
    clear_track        = pyqtSignal(int)          # device_id
    center_requested   = pyqtSignal(int)          # device_id

    def __init__(self, device: Device, parent=None):
        super().__init__(parent)
        self._device = device
        self._build_ui()

    @property
    def device(self) -> Device:
        return self._device

    def _build_ui(self):
        h = QHBoxLayout(self)
        h.setContentsMargins(2, 2, 2, 2)
        h.setSpacing(4)

        # LED stato
        self._lbl_status = QLabel(_status_dot(self._device.status))
        self._lbl_status.setFixedWidth(18)
        self._lbl_status.setAlignment(Qt.AlignCenter)
        h.addWidget(self._lbl_status)

        # Checkbox visibilità
        self._cb_vis = QCheckBox()
        self._cb_vis.setChecked(self._device.visible)
        self._cb_vis.setToolTip("Mostra/nascondi sulla mappa")
        self._cb_vis.toggled.connect(
            lambda checked: self.visibility_changed.emit(self._device.id, checked)
        )
        h.addWidget(self._cb_vis)

        # Swatch colore traccia
        self._swatch = QLabel()
        self._swatch.setFixedSize(10, 10)
        self._update_swatch()
        h.addWidget(self._swatch)

        # Nome device
        self._lbl_name = QLabel(self._device.name)
        self._lbl_name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        font = self._lbl_name.font()
        font.setBold(self._device.status == "online")
        self._lbl_name.setFont(font)
        h.addWidget(self._lbl_name, 1)

        # Stato testuale
        self._lbl_status_text = QLabel(self._device.status)
        self._lbl_status_text.setStyleSheet("color: gray; font-size: 10px;")
        self._lbl_status_text.setFixedWidth(52)
        h.addWidget(self._lbl_status_text)

        # Pulsante stile
        self._btn_style = QToolButton()
        self._btn_style.setText("⚙")
        self._btn_style.setFixedSize(22, 22)
        self._btn_style.setToolTip("Personalizza stile")
        self._btn_style.clicked.connect(lambda: self.style_requested.emit(self._device.id))
        h.addWidget(self._btn_style)

        # Pulsante cancella traccia
        self._btn_clear = QToolButton()
        self._btn_clear.setText("⌫")
        self._btn_clear.setFixedSize(22, 22)
        self._btn_clear.setToolTip("Cancella traccia")
        self._btn_clear.clicked.connect(lambda: self.clear_track.emit(self._device.id))
        h.addWidget(self._btn_clear)

        # Pulsante centra mappa
        self._btn_center = QToolButton()
        self._btn_center.setText("📍")
        self._btn_center.setFixedSize(22, 22)
        self._btn_center.setToolTip("Centra la mappa su questo dispositivo (1:50 000)")
        self._btn_center.clicked.connect(lambda: self.center_requested.emit(self._device.id))
        h.addWidget(self._btn_center)

    def refresh(self, device: Device):
        """Aggiorna la riga con lo stato/stile del device."""
        self._device = device
        self._lbl_status.setText(_status_dot(device.status))
        self._lbl_status_text.setText(device.status)
        font = self._lbl_name.font()
        font.setBold(device.status == "online")
        self._lbl_name.setFont(font)
        self._cb_vis.blockSignals(True)
        self._cb_vis.setChecked(device.visible)
        self._cb_vis.blockSignals(False)
        self._update_swatch()

    def _update_swatch(self):
        c = QColor(self._device.track_color)
        if c.isValid():
            self._swatch.setStyleSheet(
                f"background-color:{c.name()}; border:1px solid #888; border-radius:2px;"
            )


class DeviceListWidget(QWidget):
    """
    Lista scorrevole di DeviceRowWidget.

    Espone segnali che il MainDock può connettere al TrackerManager / MapLayerManager.
    """

    visibility_changed = pyqtSignal(int, bool)
    style_changed      = pyqtSignal(int)       # emesso dopo che l'utente ha salvato il dialog
    track_cleared      = pyqtSignal(int)
    # lat, lon WGS-84 del device su cui centrare la mappa
    center_on_device   = pyqtSignal(float, float)

    def __init__(self, tracker_manager, parent=None):
        super().__init__(parent)
        self._tracker = tracker_manager
        self._rows: Dict[int, DeviceRowWidget] = {}
        self._build_ui()

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        header = QWidget()
        h_hdr = QHBoxLayout(header)
        h_hdr.setContentsMargins(4, 2, 4, 2)
        lbl = QLabel("<b>Dispositivi</b>")
        self._lbl_count = QLabel("(0)")
        self._lbl_count.setStyleSheet("color: gray; font-size: 10px;")
        btn_all = QPushButton("Tutti ✓")
        btn_all.setFixedHeight(20)
        btn_all.setToolTip("Mostra tutti i dispositivi")
        btn_all.clicked.connect(self._show_all)
        btn_none = QPushButton("Nessuno")
        btn_none.setFixedHeight(20)
        btn_none.setToolTip("Nascondi tutti i dispositivi")
        btn_none.clicked.connect(self._hide_all)
        h_hdr.addWidget(lbl)
        h_hdr.addWidget(self._lbl_count)
        h_hdr.addStretch()
        h_hdr.addWidget(btn_all)
        h_hdr.addWidget(btn_none)
        outer.addWidget(header)

        # Separatore
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #ccc;")
        outer.addWidget(sep)

        # Area scorrevole con le righe
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(1)
        self._list_layout.addStretch()

        scroll.setWidget(self._list_container)
        outer.addWidget(scroll, 1)

    # ------------------------------------------------------------------
    # API pubblica
    # ------------------------------------------------------------------

    def populate(self, devices: List[Device]) -> None:
        """Rimpiazza l'intera lista con i device forniti."""
        # Rimuovi righe obsolete
        old_ids = set(self._rows.keys())
        new_ids = {d.id for d in devices}
        for did in old_ids - new_ids:
            self._remove_row(did)

        for device in devices:
            if device.id in self._rows:
                self._rows[device.id].refresh(device)
            else:
                self._add_row(device)

        # Ordina: prima online, poi per nome
        self._sort_rows(devices)
        self._lbl_count.setText(f"({len(devices)})")

    def update_device_status(self, device_id: int, status: str) -> None:
        """Aggiorna solo il LED di stato di un device."""
        row = self._rows.get(device_id)
        if row:
            device = row.device
            device.status = status
            row.refresh(device)

    def update_device_style(self, device: Device) -> None:
        """Aggiorna il swatch colore dopo un cambio di stile."""
        row = self._rows.get(device.id)
        if row:
            row.refresh(device)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add_row(self, device: Device) -> None:
        row = DeviceRowWidget(device, self._list_container)
        row.visibility_changed.connect(self._on_visibility_changed)
        row.style_requested.connect(self._on_style_requested)
        row.clear_track.connect(self._on_clear_track)
        row.center_requested.connect(self._on_center_requested)
        # Inserisci prima dello stretch finale
        idx = self._list_layout.count() - 1
        self._list_layout.insertWidget(idx, row)
        self._rows[device.id] = row

    def _remove_row(self, device_id: int) -> None:
        row = self._rows.pop(device_id, None)
        if row:
            self._list_layout.removeWidget(row)
            row.deleteLater()

    def _sort_rows(self, devices: List[Device]) -> None:
        """Riordina le righe: online in cima, poi ordine alfabetico."""
        sorted_devices = sorted(
            devices,
            key=lambda d: (0 if d.status == "online" else 1, d.name.lower()),
        )
        for i, device in enumerate(sorted_devices):
            row = self._rows.get(device.id)
            if row:
                self._list_layout.removeWidget(row)
                self._list_layout.insertWidget(i, row)

    def _show_all(self):
        for row in self._rows.values():
            row._cb_vis.setChecked(True)

    def _hide_all(self):
        for row in self._rows.values():
            row._cb_vis.setChecked(False)

    # ------------------------------------------------------------------
    # Slot
    # ------------------------------------------------------------------

    def _on_visibility_changed(self, device_id: int, visible: bool):
        # Emette il segnale verso MainDock, che si occupa di aggiornare il model.
        # Non aggiornare qui per evitare la doppia chiamata a update_device_visuals.
        self.visibility_changed.emit(device_id, visible)

    def _on_style_requested(self, device_id: int):
        conn = self._tracker.connection_manager if hasattr(self._tracker, 'connection_manager') else None
        if conn is None:
            return
        device = conn.get_device_by_id(device_id)
        if device is None:
            return

        from .device_style_dialog import DeviceStyleDialog
        dlg = DeviceStyleDialog(device, self)
        if dlg.exec_():
            # Aggiusta swatch e layer stile
            row = self._rows.get(device_id)
            if row:
                row.refresh(device)
            # Forza aggiornamento renderer layer traccia
            self._tracker.map_layer_manager  # type: ignore
            self.style_changed.emit(device_id)
            log.debug("Stile aggiornato per device_id=%d", device_id)

    def _on_clear_track(self, device_id: int):
        mlm = self._tracker.map_layer_manager
        if mlm:
            mlm.clear_device_track(device_id)
        self.track_cleared.emit(device_id)
        log.debug("Traccia cancellata per device_id=%d", device_id)

    def _on_center_requested(self, device_id: int):
        """Recupera le coordinate attuali del device dal layer e le emette."""
        mlm = self._tracker.map_layer_manager
        if mlm is None or mlm._layer_pos is None:
            log.warning("Layer posizioni non disponibile per centrare la mappa")
            return
        fid = mlm._pos_fid.get(device_id)
        if fid is None:
            log.warning("Nessuna posizione nota per device_id=%d", device_id)
            return
        feat = mlm._layer_pos.getFeature(fid)
        geom = feat.geometry() if feat.isValid() else None
        if geom is None or geom.isEmpty():
            log.warning("Geometria assente per device_id=%d", device_id)
            return
        pt = geom.asPoint()
        self.center_on_device.emit(pt.y(), pt.x())   # lat, lon

# -*- coding: utf-8 -*-
"""
DeviceStyleDialog: dialog for customising the appearance of a single device.

Allows configuring:
  • Icon (SVG/PNG from file)
  • Track colour (Qt colour picker)
  • Track width
  • Maximum track length (number of points)
  • Device name label visibility
"""
from __future__ import annotations

import os

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QColor, QIcon, QPixmap
from qgis.PyQt.QtSvg import QSvgRenderer
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.models import Device
from ..logger import get_logger

log = get_logger(__name__)

# Default icon for the preview (same as used by LayerStyler)
_DEFAULT_ICON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "resources", "kadas_star.png",
)

# Directory of preset SVG markers
_MARKERS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "resources", "markers",
)


def _load_svg_icon(path: str, size: int = 32) -> QIcon:
    """Rasterise an SVG into a QIcon of the requested size."""
    from qgis.PyQt.QtGui import QImage, QPainter
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(0)
    renderer = QSvgRenderer(path)
    painter = QPainter(img)
    renderer.render(painter)
    painter.end()
    return QIcon(QPixmap.fromImage(img))


class DeviceStyleDialog(QDialog):
    """Modal dialog for customising the visual appearance of a Device."""

    def __init__(self, device: Device, parent=None):
        super().__init__(parent)
        self._device = device
        self.setWindowTitle(f"Style – {device.name}")
        self.setMinimumWidth(480)
        self._build_ui()
        self._load()

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ----- Icon group -----
        grp_icon = QGroupBox("Device icon")
        v_icon = QVBoxLayout(grp_icon)

        # Preset SVG marker grid
        lbl_preset = QLabel("Preset markers:")
        lbl_preset.setStyleSheet("font-size: 10px; color: gray;")
        v_icon.addWidget(lbl_preset)

        scroll = QScrollArea()
        scroll.setFixedHeight(72)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        marker_container = QWidget()
        h_markers = QHBoxLayout(marker_container)
        h_markers.setContentsMargins(2, 2, 2, 2)
        h_markers.setSpacing(4)

        self._marker_btn_group = QButtonGroup(self)
        self._marker_btn_group.setExclusive(True)

        self._marker_svgs: list[str] = []  # path ordinati
        if os.path.isdir(_MARKERS_DIR):
            svgs = sorted(
                f for f in os.listdir(_MARKERS_DIR) if f.lower().endswith(".svg")
            )
            for fname in svgs:
                fpath = os.path.join(_MARKERS_DIR, fname)
                btn = QToolButton()
                btn.setCheckable(True)
                btn.setFixedSize(52, 52)
                btn.setIconSize(QSize(36, 36))
                btn.setToolTip(os.path.splitext(fname)[0])
                btn.setIcon(_load_svg_icon(fpath, 36))
                btn.setStyleSheet(
                    "QToolButton { border: 2px solid transparent; border-radius: 4px; }"
                    "QToolButton:checked { border: 2px solid #1565C0; background: #E3F2FD; }"
                )
                self._marker_btn_group.addButton(btn, len(self._marker_svgs))
                h_markers.addWidget(btn)
                self._marker_svgs.append(fpath)
                btn.clicked.connect(lambda _checked, p=fpath: self._on_marker_selected(p))

        h_markers.addStretch()
        scroll.setWidget(marker_container)
        v_icon.addWidget(scroll)

        # Riga file custom + preview
        icon_row = QWidget()
        h_icon = QHBoxLayout(icon_row)
        h_icon.setContentsMargins(0, 4, 0, 0)

        self._icon_preview = QLabel()
        self._icon_preview.setFixedSize(32, 32)
        self._icon_preview.setStyleSheet(
            "border: 1px solid #ccc; border-radius: 4px;"
        )
        self._icon_edit = QLineEdit()
        self._icon_edit.setPlaceholderText("(default icon)")
        self._icon_edit.setReadOnly(True)
        self._btn_icon_browse = QPushButton("…")
        self._btn_icon_browse.setFixedWidth(28)
        self._btn_icon_browse.setToolTip("Browse file…")
        self._btn_icon_browse.clicked.connect(self._browse_icon)
        self._btn_icon_clear = QPushButton("✕")
        self._btn_icon_clear.setFixedWidth(28)
        self._btn_icon_clear.setToolTip("Use default icon")
        self._btn_icon_clear.clicked.connect(self._clear_icon)

        h_icon.addWidget(self._icon_preview)
        h_icon.addWidget(self._icon_edit, 1)
        h_icon.addWidget(self._btn_icon_browse)
        h_icon.addWidget(self._btn_icon_clear)
        v_icon.addWidget(icon_row)
        layout.addWidget(grp_icon)

        # ----- Track group -----
        grp_track = QGroupBox("Track")
        form_track = QFormLayout(grp_track)

        # Colour
        color_row = QWidget()
        h_color = QHBoxLayout(color_row)
        h_color.setContentsMargins(0, 0, 0, 0)
        self._color_swatch = QLabel()
        self._color_swatch.setFixedSize(24, 24)
        self._color_swatch.setStyleSheet("border: 1px solid #999; border-radius: 3px;")
        self._color_edit = QLineEdit()
        self._color_edit.setPlaceholderText("#0000FF")
        self._color_edit.textChanged.connect(self._update_swatch)
        self._btn_color = QPushButton("Pick…")
        self._btn_color.clicked.connect(self._pick_color)
        h_color.addWidget(self._color_swatch)
        h_color.addWidget(self._color_edit, 1)
        h_color.addWidget(self._btn_color)
        form_track.addRow("Colour:", color_row)

        # Width
        width_row = QWidget()
        h_width = QHBoxLayout(width_row)
        h_width.setContentsMargins(0, 0, 0, 0)
        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 20)
        self._width_spin.setSuffix(" px")
        self._width_slider = QSlider(Qt.Horizontal)
        self._width_slider.setRange(1, 20)
        self._width_spin.valueChanged.connect(self._width_slider.setValue)
        self._width_slider.valueChanged.connect(self._width_spin.setValue)
        h_width.addWidget(self._width_spin)
        h_width.addWidget(self._width_slider, 1)
        form_track.addRow("Width:", width_row)

        # Maximum length
        self._max_pts_spin = QSpinBox()
        self._max_pts_spin.setRange(2, 10000)
        self._max_pts_spin.setSingleStep(50)
        self._max_pts_spin.setSuffix(" pts")
        form_track.addRow("Max length:", self._max_pts_spin)

        layout.addWidget(grp_track)

        # ----- Label group -----
        grp_label = QGroupBox("Label")
        form_lbl = QFormLayout(grp_label)
        self._show_label_cb = QCheckBox("Show device name on the map")
        form_lbl.addRow("", self._show_label_cb)
        layout.addWidget(grp_label)

        # ----- Pulsanti -----
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def _load(self):
        d = self._device
        self._icon_edit.setText(d.icon_path or "")
        self._update_icon_preview(d.icon_path)
        self._color_edit.setText(d.track_color)
        self._update_swatch(d.track_color)
        self._width_spin.setValue(d.track_width)
        self._max_pts_spin.setValue(d.track_max_points)
        self._show_label_cb.setChecked(d.show_label)
        # Select the corresponding button in the marker grid
        self._sync_marker_selection(d.icon_path)

    def _save(self):
        d = self._device
        icon = self._icon_edit.text().strip() or None
        d.icon_path = icon
        d.track_color = self._color_edit.text().strip() or "#0000FF"
        d.track_width = self._width_spin.value()
        d.track_max_points = self._max_pts_spin.value()
        d.show_label = self._show_label_cb.isChecked()
        log.debug(
            "Style updated for device %s: color=%s width=%d maxpts=%d label=%s",
            d.name, d.track_color, d.track_width, d.track_max_points, d.show_label,
        )
        self.accept()

    # ------------------------------------------------------------------
    # Internal slots
    # ------------------------------------------------------------------

    def _browse_icon(self):
        start_dir = _MARKERS_DIR if os.path.isdir(_MARKERS_DIR) else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select icon",
            start_dir,
            "Images (*.svg *.png *.jpg *.jpeg *.bmp);;All files (*)",
        )
        if path:
            self._icon_edit.setText(path)
            self._update_icon_preview(path)
            self._sync_marker_selection(path)

    def _clear_icon(self):
        self._icon_edit.clear()
        self._update_icon_preview(None)
        self._sync_marker_selection(None)

    def _on_marker_selected(self, path: str):
        """Called when the user clicks a preset marker."""
        self._icon_edit.setText(path)
        self._update_icon_preview(path)

    def _sync_marker_selection(self, path: str | None):
        """Update the checked state of marker buttons based on the path."""
        norm = os.path.normcase(os.path.normpath(path)) if path else None
        for idx, fpath in enumerate(self._marker_svgs):
            btn = self._marker_btn_group.button(idx)
            if btn is not None:
                btn.setChecked(
                    norm == os.path.normcase(os.path.normpath(fpath))
                )

    def _update_icon_preview(self, path: str | None):
        target = path if (path and os.path.isfile(path)) else (
            _DEFAULT_ICON if os.path.isfile(_DEFAULT_ICON) else None
        )
        if target:
            pix = QPixmap(target).scaled(
                28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self._icon_preview.setPixmap(pix)
            self._icon_preview.setText("")
        else:
            self._icon_preview.setPixmap(QPixmap())
            self._icon_preview.setText("?")
            self._icon_preview.setAlignment(Qt.AlignCenter)

    def _pick_color(self):
        from qgis.PyQt.QtWidgets import QColorDialog
        initial = QColor(self._color_edit.text() or "#0000FF")
        color = QColorDialog.getColor(initial, self, "Pick track colour")
        if color.isValid():
            self._color_edit.setText(color.name())

    def _update_swatch(self, color_text: str):
        c = QColor(color_text)
        if c.isValid():
            self._color_swatch.setStyleSheet(
                f"background-color: {c.name()}; border: 1px solid #999; border-radius: 3px;"
            )
        else:
            self._color_swatch.setStyleSheet(
                "background-color: transparent; border: 1px solid #999; border-radius: 3px;"
            )

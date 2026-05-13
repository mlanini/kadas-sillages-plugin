# -*- coding: utf-8 -*-
"""
LayerStyler: applies QGIS styles to the Sillages in-memory layers.

Responsibilities:
  • Categorised renderer for the Tracks layer (per-device colour from the 'color' field)
  • Categorised renderer for the Positions layer (SVG or default icon per device)
  • Labels (QgsPalLayerSettings) for the Positions layer when show_label is active

The main challenge is that devices have individual styles: a
QgsCategorizedSymbolRenderer is used for both layers, with one category per device.
It must be reapplied every time a device's style changes.
"""
from __future__ import annotations

from typing import List, Optional
import os

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsRendererCategory,
    QgsSvgMarkerSymbolLayer,
    QgsSimpleLineSymbolLayer,
    QgsSimpleMarkerSymbolLayer,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)
try:
    from qgis.core import QgsRasterMarkerSymbolLayer as _QgsRasterMarkerSL
except ImportError:  # KADAS < 3.10 fallback
    _QgsRasterMarkerSL = None
from qgis.PyQt.QtGui import QColor, QFont

from .map_layer_manager import LAYER_NAME_POSITIONS, LAYER_NAME_TRACKS
from .models import Device
from ..logger import get_logger

log = get_logger(__name__)

# Default icon for devices
_DEFAULT_ICON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "resources", "kadas_star.png",
)


class LayerStyler:
    """
    Applies and updates categorised renderers on the Sillages layers.

    Call `apply(devices)` after every style change or when the device list changes.
    """

    def __init__(
        self,
        layer_pos: Optional[QgsVectorLayer],
        layer_trk: Optional[QgsVectorLayer],
    ):
        self._layer_pos = layer_pos
        self._layer_trk = layer_trk

    def update_layers(
        self,
        layer_pos: Optional[QgsVectorLayer],
        layer_trk: Optional[QgsVectorLayer],
    ) -> None:
        """Update layer references (call after create_layers)."""
        self._layer_pos = layer_pos
        self._layer_trk = layer_trk

    def apply(self, devices: List[Device]) -> None:
        """Recalculate and apply categorised renderers for all devices."""
        if not devices:
            return
        self._apply_track_renderer(devices)
        self._apply_position_renderer(devices)
        self._apply_labels(devices)
        # Forza ridisegno
        for lyr in (self._layer_pos, self._layer_trk):
            if lyr is not None:
                lyr.triggerRepaint()
        log.debug("Styles applied to %d devices", len(devices))

    # ------------------------------------------------------------------
    # Tracks layer
    # ------------------------------------------------------------------

    def _apply_track_renderer(self, devices: List[Device]) -> None:
        lyr = self._layer_trk
        if lyr is None:
            return

        categories = []
        for device in devices:
            sym = QgsLineSymbol()
            # Rimuove layer simbolo default e aggiunge linea semplice configurata
            sym.deleteSymbolLayer(0)
            line_sl = QgsSimpleLineSymbolLayer()
            line_sl.setColor(QColor(device.track_color))
            line_sl.setWidth(device.track_width * 0.1)   # QGIS usa unità mappa (~mm)
            line_sl.setWidthUnit(
                __import__(
                    "qgis.core", fromlist=["QgsUnitTypes"]
                ).QgsUnitTypes.RenderPixels
            )
            sym.appendSymbolLayer(line_sl)

            cat = QgsRendererCategory(device.id, sym, device.name)
            categories.append(cat)

        renderer = QgsCategorizedSymbolRenderer("device_id", categories)
        lyr.setRenderer(renderer)

    # ------------------------------------------------------------------
    # Positions layer
    # ------------------------------------------------------------------

    def _apply_position_renderer(self, devices: List[Device]) -> None:
        lyr = self._layer_pos
        if lyr is None:
            return

        categories = []
        for device in devices:
            if device.icon_path and os.path.isfile(device.icon_path):
                ext = os.path.splitext(device.icon_path)[1].lower()
                if ext == ".svg":
                    sym = self._svg_marker_symbol(device.icon_path, device.track_color)
                else:
                    sym = self._raster_marker_symbol(device.icon_path)
            else:
                sym = self._default_marker_symbol(device.track_color, device.status)

            cat = QgsRendererCategory(device.id, sym, device.name)
            categories.append(cat)

        renderer = QgsCategorizedSymbolRenderer("device_id", categories)
        lyr.setRenderer(renderer)

    @staticmethod
    def _svg_marker_symbol(svg_path: str, color: str) -> QgsMarkerSymbol:
        sym = QgsMarkerSymbol()
        sym.deleteSymbolLayer(0)
        svg_sl = QgsSvgMarkerSymbolLayer(svg_path)
        svg_sl.setSize(8)
        svg_sl.setFillColor(QColor(color))
        sym.appendSymbolLayer(svg_sl)
        return sym

    @staticmethod
    def _raster_marker_symbol(path: str, size: float = 10.0) -> QgsMarkerSymbol:
        """Create a raster marker (PNG/JPG) using QgsRasterMarkerSymbolLayer."""
        sym = QgsMarkerSymbol()
        sym.deleteSymbolLayer(0)
        if _QgsRasterMarkerSL is not None:
            sl = _QgsRasterMarkerSL(path)
            sl.setSize(size)
        else:
            # Fallback: simple circle when QgsRasterMarkerSymbolLayer is unavailable
            sl = QgsSimpleMarkerSymbolLayer()
            sl.setSize(size * 0.6)
            sl.setColor(QColor("#3388cc"))
            sl.setStrokeColor(QColor("#FFFFFF"))
        sym.appendSymbolLayer(sl)
        return sym

    @staticmethod
    def _default_marker_symbol(color: str, status: str) -> QgsMarkerSymbol:
        sym = QgsMarkerSymbol()
        sym.deleteSymbolLayer(0)
        if os.path.isfile(_DEFAULT_ICON):
            if _QgsRasterMarkerSL is not None:
                sl = _QgsRasterMarkerSL(_DEFAULT_ICON)
                sl.setSize(10)
            else:
                # Fallback SVG if available, otherwise circle
                sl = QgsSimpleMarkerSymbolLayer()
                sl.setSize(6)
                sl.setColor(QColor(color))
                sl.setStrokeColor(QColor("#FFFFFF"))
        else:
            sl = QgsSimpleMarkerSymbolLayer()
            sl.setSize(6)
            sl.setColor(QColor(color))
            sl.setStrokeColor(QColor("#FFFFFF"))
        sym.appendSymbolLayer(sl)
        return sym

    # ------------------------------------------------------------------
    # Labels
    # ------------------------------------------------------------------

    def _apply_labels(self, devices: List[Device]) -> None:
        lyr = self._layer_pos
        if lyr is None:
            return

        # Enable labelling if at least one device has labels active
        any_label = any(d.show_label for d in devices)
        if not any_label:
            lyr.setLabelsEnabled(False)
            return

        pal = QgsPalLayerSettings()
        pal.fieldName = "name"
        pal.enabled = True

        text_format = QgsTextFormat()
        font = QFont("Sans Serif", 8)
        font.setBold(False)
        text_format.setFont(font)
        text_format.setSize(8)

        # White buffer for readability on any background
        from qgis.core import QgsTextBufferSettings
        buf = QgsTextBufferSettings()
        buf.setEnabled(True)
        buf.setSize(1)
        buf.setColor(QColor("#FFFFFF"))
        text_format.setBuffer(buf)
        pal.setFormat(text_format)

        # Label placement: around the point (AroundPoint is the correct value
        # for LabelPlacement in KADAS Albireo 2 / QGIS 3.x).
        # OverPoint belongs to LabelPredefinedPointPosition, not to placement.
        try:
            pal.placement = QgsPalLayerSettings.AroundPoint
        except AttributeError:
            pal.placement = 0  # numeric fallback = AroundPoint
        try:
            pal.quadOffset = QgsPalLayerSettings.QuadrantBelow
        except (AttributeError, TypeError):
            pass  # quadOffset is optional, skip if unsupported

        labeling = QgsVectorLayerSimpleLabeling(pal)
        lyr.setLabeling(labeling)
        lyr.setLabelsEnabled(True)

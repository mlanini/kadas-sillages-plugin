# -*- coding: utf-8 -*-
"""
MapLayerManager: manages in-memory vector layers for positions and tracks.

Layer structure:
  • "Sillages – Positions"  → QgsVectorLayer Point   (one feature per device)
  • "Sillages – Tracks"     → QgsVectorLayer LineString (one feature per device)

Both layers are added to the current QGIS/KADAS project and removed
automatically when tracking stops or the plugin is unloaded.
"""
from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional

from qgis.PyQt.QtCore import QTimer
from qgis.core import (
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)

from .models import Device, Position
from ..logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Layer names
# ---------------------------------------------------------------------------
LAYER_NAME_POSITIONS = "Sillages – Positions"
LAYER_NAME_TRACKS    = "Sillages – Tracks"

# ---------------------------------------------------------------------------
# Attribute fields — defined as (name, uri_type) tuples.
# URI types accepted by the QGIS/KADAS "memory" provider:
#   integer, double, string, date, datetime
# ---------------------------------------------------------------------------
FIELDS_POS = [
    ("device_id", "integer"),
    ("name",      "string(200)"),
    ("status",    "string(20)"),
    ("speed",     "double"),
    ("course",    "double"),
    ("altitude",  "double"),
    ("fix_time",  "string(30)"),
    ("address",   "string(300)"),
]

# Track layer fields
FIELDS_TRK = [
    ("device_id", "integer"),
    ("name",      "string(200)"),
    ("color",     "string(20)"),
]


class MapLayerManager:
    """
    Creates, updates and removes in-memory layers for live tracking.

    Lifecycle:
        mgr = MapLayerManager()
        mgr.create_layers()          # adds layers to the project
        mgr.update_position(device, position)   # updates geometry/attributes
        mgr.remove_layers()          # removes from the project
    """

    def __init__(self):
        self._layer_pos: Optional[QgsVectorLayer] = None
        self._layer_trk: Optional[QgsVectorLayer] = None

        # device_id → QgsFeatureId nel layer posizioni
        self._pos_fid: Dict[int, int] = {}
        # device_id → QgsFeatureId nel layer tracce
        self._trk_fid: Dict[int, int] = {}
        # device_id → deque di QgsPointXY (buffer traccia)
        self._track_buffer: Dict[int, deque] = {}

        # Timer for repaint throttling (max once per second)
        self._repaint_timer = QTimer()
        self._repaint_timer.setSingleShot(True)
        self._repaint_timer.setInterval(800)   # ms
        self._repaint_timer.timeout.connect(self._do_repaint)
        self._repaint_pending_pos = False
        self._repaint_pending_trk = False

    # ------------------------------------------------------------------
    # Layer lifecycle
    # ------------------------------------------------------------------

    def create_layers(self) -> None:
        """Create in-memory layers and add them to the current project."""
        if self._layer_pos is not None:
            log.debug("Layers already exist, skipping create_layers")
            return

        self._layer_pos = self._make_layer(
            "Point", LAYER_NAME_POSITIONS, FIELDS_POS
        )
        self._layer_trk = self._make_layer(
            "LineString", LAYER_NAME_TRACKS, FIELDS_TRK
        )

        QgsProject.instance().addMapLayer(self._layer_trk)
        QgsProject.instance().addMapLayer(self._layer_pos)
        log.info("Sillages layers created and added to project")

    def remove_layers(self) -> None:
        """Remove layers from the project and free memory."""
        self._repaint_timer.stop()
        proj = QgsProject.instance()
        for lyr in (self._layer_pos, self._layer_trk):
            if lyr is not None:
                try:
                    proj.removeMapLayer(lyr.id())
                except Exception:
                    pass
        self._layer_pos = None
        self._layer_trk = None
        self._pos_fid.clear()
        self._trk_fid.clear()
        self._track_buffer.clear()
        log.info("Sillages layers removed from project")

    @property
    def layers_exist(self) -> bool:
        return self._layer_pos is not None and self._layer_trk is not None

    # ------------------------------------------------------------------
    # Position updates
    # ------------------------------------------------------------------

    def update_position(self, device: Device, position: Position) -> None:
        """
        Update (or create) the device feature in the position and track layers.
        Called on every WebSocket message with a new position.
        """
        if not self.layers_exist:
            return
        if not position.valid:
            return

        pt = QgsPointXY(position.longitude, position.latitude)
        self._update_position_layer(device, position, pt)
        self._update_track_layer(device, position, pt)

    def clear_device_track(self, device_id: int) -> None:
        """Svuota il buffer traccia di un singolo device."""
        self._track_buffer.pop(device_id, None)
        fid = self._trk_fid.get(device_id)
        if fid is not None and self._layer_trk is not None:
            pr = self._layer_trk.dataProvider()
            pr.changeGeometryValues({fid: QgsGeometry()})
            self._layer_trk.updateExtents()
            self._layer_trk.triggerRepaint()

    def initialize_device(self, device: Device) -> None:
        """
        Create empty features for a device that has no live position yet.
        Ensures the device appears in the list even before the first
        WebSocket update.
        """
        if not self.layers_exist:
            return
        if device.id not in self._pos_fid:
            self._create_pos_feature(device, None)
        if device.id not in self._trk_fid:
            self._create_trk_feature(device)

    # ------------------------------------------------------------------
    # Position layer helpers
    # ------------------------------------------------------------------

    def _update_position_layer(
        self, device: Device, pos: Position, pt: QgsPointXY
    ) -> None:
        lyr = self._layer_pos
        pr  = lyr.dataProvider()
        geom = QgsGeometry.fromPointXY(pt)

        flds = lyr.fields()
        def _idx(name): return flds.indexFromName(name)

        attrs = {
            _idx("device_id"): device.id,
            _idx("name"):      device.name,
            _idx("status"):    device.status,
            _idx("speed"):     pos.speed,
            _idx("course"):    pos.course,
            _idx("altitude"):  pos.altitude,
            _idx("fix_time"):  pos.fix_time.isoformat() if pos.fix_time else "",
            _idx("address"):   pos.address or "",
        }
        # Rimuovi indici non trovati (< 0)
        attrs = {k: v for k, v in attrs.items() if k >= 0}

        if device.id in self._pos_fid:
            fid = self._pos_fid[device.id]
            pr.changeGeometryValues({fid: geom})
            pr.changeAttributeValues({fid: attrs})
        else:
            self._create_pos_feature(device, pos, geom, attrs, lyr)

        self._repaint_pending_pos = True
        if not self._repaint_timer.isActive():
            self._repaint_timer.start()

    def _create_pos_feature(
        self,
        device: Device,
        pos: Optional[Position],
        geom: Optional[QgsGeometry] = None,
        attrs: Optional[dict] = None,
        lyr: Optional[QgsVectorLayer] = None,
    ) -> None:
        if lyr is None:
            lyr = self._layer_pos
        if geom is None:
            geom = QgsGeometry()

        f = QgsFeature(lyr.fields())
        f.setGeometry(geom)
        if attrs:
            # attrs può essere {idx: value} oppure {nome: value}
            for key, value in attrs.items():
                if isinstance(key, int):
                    if key >= 0:
                        f.setAttribute(key, value)
                else:
                    f[key] = value
        else:
            f["device_id"] = device.id
            f["name"] = device.name
            f["status"] = device.status

        pr = lyr.dataProvider()
        ok, added = pr.addFeatures([f])
        if ok and added:
            self._pos_fid[device.id] = added[0].id()

    # ------------------------------------------------------------------
    # Track layer helpers
    # ------------------------------------------------------------------

    def _update_track_layer(
        self, device: Device, pos: Position, pt: QgsPointXY
    ) -> None:
        lyr = self._layer_trk
        pr  = lyr.dataProvider()
        buf = self._track_buffer.setdefault(
            device.id, deque(maxlen=device.track_max_points)
        )
        # Aggiorna maxlen se cambiata nelle impostazioni
        if buf.maxlen != device.track_max_points:
            buf = deque(buf, maxlen=device.track_max_points)
            self._track_buffer[device.id] = buf
        buf.append(pt)

        if len(buf) < 2:
            if device.id not in self._trk_fid:
                self._create_trk_feature(device, lyr)
            return

        line = QgsGeometry.fromPolylineXY(list(buf))
        if device.id in self._trk_fid:
            fid = self._trk_fid[device.id]
            pr.changeGeometryValues({fid: line})
            idx_color = lyr.fields().indexFromName("color")
            if idx_color >= 0:
                pr.changeAttributeValues({fid: {idx_color: device.track_color}})
        else:
            self._create_trk_feature(device, lyr, line)

        self._repaint_pending_trk = True
        if not self._repaint_timer.isActive():
            self._repaint_timer.start()

    def _create_trk_feature(
        self,
        device: Device,
        lyr: Optional[QgsVectorLayer] = None,
        geom: Optional[QgsGeometry] = None,
    ) -> None:
        if lyr is None:
            lyr = self._layer_trk
        if geom is None:
            geom = QgsGeometry()

        f = QgsFeature(lyr.fields())
        f.setGeometry(geom)
        f["device_id"] = device.id
        f["name"]      = device.name
        f["color"]     = device.track_color

        pr = lyr.dataProvider()
        ok, added = pr.addFeatures([f])
        if ok and added:
            self._trk_fid[device.id] = added[0].id()

    # ------------------------------------------------------------------
    # Repaint throttle
    # ------------------------------------------------------------------

    def _do_repaint(self) -> None:
        """Trigger repaint on layers that have pending updates."""
        if self._repaint_pending_pos and self._layer_pos is not None:
            self._layer_pos.triggerRepaint()
            self._repaint_pending_pos = False
        if self._repaint_pending_trk and self._layer_trk is not None:
            self._layer_trk.triggerRepaint()
            self._repaint_pending_trk = False

    # ------------------------------------------------------------------
    # Layer factory
    # ------------------------------------------------------------------

    @staticmethod
    def _make_layer(
        geom_type: str,
        name: str,
        field_defs: list,
    ) -> QgsVectorLayer:
        """
        Create a memory layer by specifying fields directly in the URI.
        Avoids QgsField/QVariant (deprecated in KADAS Albireo 2).
        URI format: "Point?crs=EPSG:4326&field=name:type&..."
        """
        field_parts = "&".join(f"field={fname}:{ftype}" for fname, ftype in field_defs)
        uri = f"{geom_type}?crs=EPSG:4326&{field_parts}"
        lyr = QgsVectorLayer(uri, name, "memory")
        if not lyr.isValid():
            raise RuntimeError(f"Unable to create layer '{name}' (uri={uri})")
        return lyr

# -*- coding: utf-8 -*-
"""
Exporter: downloads historic positions from Traccar and adds them to the project
as a permanent vector layer or saves them to file (GeoJSON, GPX, CSV).

Flow:
    exp = Exporter(client)
    exp.export_to_layer(device, from_dt, to_dt)          # → QgsVectorLayer in the project
    exp.export_to_file(device, from_dt, to_dt, path, fmt) # → file on disk
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from typing import List, Optional

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from .traccar_client import TraccarClient, TraccarError
from .models import Device, Position
from ..logger import get_logger

log = get_logger(__name__)

# Fields of the exported layer
_EXPORT_FIELDS = [
    ("device_id",  QVariant.Int,    "Device ID"),
    ("device_name",QVariant.String, "Device name"),
    ("fix_time",   QVariant.String, "GPS fix time (UTC)"),
    ("latitude",   QVariant.Double, "Latitude"),
    ("longitude",  QVariant.Double, "Longitude"),
    ("altitude",   QVariant.Double, "Altitude (m)"),
    ("speed_kn",   QVariant.Double, "Speed (knots)"),
    ("speed_kmh",  QVariant.Double, "Speed (km/h)"),
    ("course",     QVariant.Double, "Heading (°)"),
    ("address",    QVariant.String, "Address"),
    ("valid",      QVariant.Int,    "Valid fix (0/1)"),
]


class Exporter:
    """Downloads and converts historic Traccar positions."""

    def __init__(self, client: TraccarClient):
        self._client = client

    # ------------------------------------------------------------------
    # Export as a layer in the KADAS project
    # ------------------------------------------------------------------

    def export_to_layer(
        self,
        device: Device,
        from_dt: datetime,
        to_dt: datetime,
        as_track: bool = True,
    ) -> Optional[QgsVectorLayer]:
        """
        Download historic positions and add them to the project as:
          • as_track=True  → LineString (track)
          • as_track=False → MultiPoint (individual points with all attributes)

        Returns:
            QgsVectorLayer added to the project, or None on error.
        """
        positions = self._fetch(device, from_dt, to_dt)
        if not positions:
            log.warning("No positions found for %s in the requested range", device.name)
            return None

        layer_name = (
            f"{device.name} – track "
            f"{from_dt.strftime('%Y%m%d')}–{to_dt.strftime('%Y%m%d')}"
        )

        if as_track:
            lyr = self._build_track_layer(layer_name, device, positions)
        else:
            lyr = self._build_points_layer(layer_name, device, positions)

        QgsProject.instance().addMapLayer(lyr)
        log.info(
            "Exported %d points for device '%s' → layer '%s'",
            len(positions), device.name, layer_name,
        )
        return lyr

    # ------------------------------------------------------------------
    # Export to file
    # ------------------------------------------------------------------

    def export_to_file(
        self,
        device: Device,
        from_dt: datetime,
        to_dt: datetime,
        file_path: str,
        file_format: str = "geojson",
    ) -> bool:
        """
        Save historic positions to file.

        Args:
            file_format: "geojson" | "gpx" | "csv"

        Returns:
            True if export succeeded.
        """
        positions = self._fetch(device, from_dt, to_dt)
        if not positions:
            log.warning("No positions to export for %s", device.name)
            return False

        fmt = file_format.lower()
        try:
            if fmt == "geojson":
                return self._write_geojson(file_path, device, positions)
            elif fmt == "gpx":
                return self._write_gpx(file_path, device, positions)
            elif fmt == "csv":
                return self._write_csv(file_path, device, positions)
            else:
                log.error("Unsupported format: %s", file_format)
                return False
        except Exception as exc:
            log.error("Error during file export: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Fetch positions
    # ------------------------------------------------------------------

    def _fetch(
        self, device: Device, from_dt: datetime, to_dt: datetime
    ) -> List[Position]:
        try:
            positions = self._client.get_route(device.id, from_dt, to_dt)
            if not positions:
                # Fallback to get_positions if route returns nothing
                positions = self._client.get_positions(device.id, from_dt, to_dt)
            return positions
        except TraccarError as exc:
            log.error("Error fetching historic positions: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Build QGIS layers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_base_layer(geom_type: str, name: str) -> QgsVectorLayer:
        uri = f"{geom_type}?crs=EPSG:4326"
        lyr = QgsVectorLayer(uri, name, "memory")
        if not lyr.isValid():
            raise RuntimeError(f"Unable to create layer '{name}'")
        pr = lyr.dataProvider()
        pr.addAttributes([QgsField(fn, ft) for fn, ft, _ in _EXPORT_FIELDS])
        lyr.updateFields()
        return lyr

    def _build_track_layer(
        self, name: str, device: Device, positions: List[Position]
    ) -> QgsVectorLayer:
        lyr = self._make_base_layer("LineString", name)
        valid = [p for p in positions if p.valid]
        if len(valid) < 2:
            valid = positions  # use all if not enough valid

        pts = [QgsPointXY(p.longitude, p.latitude) for p in valid]
        geom = QgsGeometry.fromPolylineXY(pts)

        f = QgsFeature(lyr.fields())
        f.setGeometry(geom)
        f["device_id"]   = device.id
        f["device_name"] = device.name
        f["fix_time"]    = valid[0].fix_time.isoformat() if valid[0].fix_time else ""
        lyr.dataProvider().addFeature(f)
        lyr.updateExtents()

        # Stile linea colorata
        from qgis.core import QgsLineSymbol
        sym = QgsLineSymbol.createSimple({
            "color": device.track_color,
            "width": str(device.track_width),
            "width_unit": "Pixel",
        })
        lyr.renderer().setSymbol(sym)
        return lyr

    def _build_points_layer(
        self, name: str, device: Device, positions: List[Position]
    ) -> QgsVectorLayer:
        lyr = self._make_base_layer("Point", name)
        features = []
        for pos in positions:
            f = QgsFeature(lyr.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(pos.longitude, pos.latitude)))
            f["device_id"]   = device.id
            f["device_name"] = device.name
            f["fix_time"]    = pos.fix_time.isoformat() if pos.fix_time else ""
            f["latitude"]    = pos.latitude
            f["longitude"]   = pos.longitude
            f["altitude"]    = pos.altitude
            f["speed_kn"]    = pos.speed
            f["speed_kmh"]   = round(pos.speed * 1.852, 2)
            f["course"]      = pos.course
            f["address"]     = pos.address or ""
            f["valid"]       = 1 if pos.valid else 0
            features.append(f)
        lyr.dataProvider().addFeatures(features)
        lyr.updateExtents()
        return lyr

    # ------------------------------------------------------------------
    # File writers
    # ------------------------------------------------------------------

    def _write_geojson(
        self, path: str, device: Device, positions: List[Position]
    ) -> bool:
        fc = {
            "type": "FeatureCollection",
            "name": device.name,
            "features": [],
        }
        for pos in positions:
            fc["features"].append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [pos.longitude, pos.latitude, pos.altitude],
                },
                "properties": {
                    "device_id":   device.id,
                    "device_name": device.name,
                    "fix_time":    pos.fix_time.isoformat() if pos.fix_time else None,
                    "speed_kn":    pos.speed,
                    "speed_kmh":   round(pos.speed * 1.852, 2),
                    "course":      pos.course,
                    "address":     pos.address,
                    "valid":       pos.valid,
                },
            })
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(fc, fh, ensure_ascii=False, indent=2)
        log.info("GeoJSON written: %s (%d features)", path, len(fc["features"]))
        return True

    def _write_gpx(
        self, path: str, device: Device, positions: List[Position]
    ) -> bool:
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<gpx version="1.1" creator="KadasSillages"',
            '  xmlns="http://www.topografix.com/GPX/1/1">',
            f'  <trk><name>{_xml_escape(device.name)}</name><trkseg>',
        ]
        for pos in positions:
            ts = pos.fix_time.isoformat() if pos.fix_time else ""
            lines.append(
                f'    <trkpt lat="{pos.latitude}" lon="{pos.longitude}">'
                f"<ele>{pos.altitude}</ele>"
                f"<time>{ts}</time>"
                f"<speed>{round(pos.speed * 0.514444, 2)}</speed>"
                f"</trkpt>"
            )
        lines += ["  </trkseg></trk>", "</gpx>"]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        log.info("GPX written: %s (%d trackpoints)", path, len(positions))
        return True

    def _write_csv(
        self, path: str, device: Device, positions: List[Position]
    ) -> bool:
        headers = [
            "device_id", "device_name", "fix_time",
            "latitude", "longitude", "altitude",
            "speed_kn", "speed_kmh", "course", "address", "valid",
        ]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=headers)
            writer.writeheader()
            for pos in positions:
                writer.writerow({
                    "device_id":   device.id,
                    "device_name": device.name,
                    "fix_time":    pos.fix_time.isoformat() if pos.fix_time else "",
                    "latitude":    pos.latitude,
                    "longitude":   pos.longitude,
                    "altitude":    pos.altitude,
                    "speed_kn":    pos.speed,
                    "speed_kmh":   round(pos.speed * 1.852, 2),
                    "course":      pos.course,
                    "address":     pos.address or "",
                    "valid":       1 if pos.valid else 0,
                })
        log.info("CSV written: %s (%d rows)", path, len(positions))
        return True


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )

# -*- coding: utf-8 -*-
"""
Exporter: scarica le posizioni storiche da Traccar e le aggiunge al progetto
come layer vettoriale permanente oppure le salva su file (GeoJSON, GPX, CSV).

Flusso:
    exp = Exporter(client)
    exp.export_to_layer(device, from_dt, to_dt)          # → QgsVectorLayer nel progetto
    exp.export_to_file(device, from_dt, to_dt, path, fmt) # → file su disco
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

# Campi del layer esportato
_EXPORT_FIELDS = [
    ("device_id",  QVariant.Int,    "ID dispositivo"),
    ("device_name",QVariant.String, "Nome dispositivo"),
    ("fix_time",   QVariant.String, "Ora fix GPS (UTC)"),
    ("latitude",   QVariant.Double, "Latitudine"),
    ("longitude",  QVariant.Double, "Longitudine"),
    ("altitude",   QVariant.Double, "Quota (m)"),
    ("speed_kn",   QVariant.Double, "Velocità (nodi)"),
    ("speed_kmh",  QVariant.Double, "Velocità (km/h)"),
    ("course",     QVariant.Double, "Direzione (°)"),
    ("address",    QVariant.String, "Indirizzo"),
    ("valid",      QVariant.Int,    "Fix valido (0/1)"),
]


class Exporter:
    """Scarica e converte posizioni storiche Traccar."""

    def __init__(self, client: TraccarClient):
        self._client = client

    # ------------------------------------------------------------------
    # Export come layer nel progetto KADAS
    # ------------------------------------------------------------------

    def export_to_layer(
        self,
        device: Device,
        from_dt: datetime,
        to_dt: datetime,
        as_track: bool = True,
    ) -> Optional[QgsVectorLayer]:
        """
        Scarica le posizioni storiche e le aggiunge al progetto come:
          • as_track=True  → LineString (traccia)
          • as_track=False → MultiPoint (punti separati con tutti gli attributi)

        Returns:
            QgsVectorLayer aggiunto al progetto, o None in caso di errore.
        """
        positions = self._fetch(device, from_dt, to_dt)
        if not positions:
            log.warning("Nessuna posizione trovata per %s nel range richiesto", device.name)
            return None

        layer_name = (
            f"{device.name} – traccia "
            f"{from_dt.strftime('%Y%m%d')}–{to_dt.strftime('%Y%m%d')}"
        )

        if as_track:
            lyr = self._build_track_layer(layer_name, device, positions)
        else:
            lyr = self._build_points_layer(layer_name, device, positions)

        QgsProject.instance().addMapLayer(lyr)
        log.info(
            "Esportati %d punti per device '%s' → layer '%s'",
            len(positions), device.name, layer_name,
        )
        return lyr

    # ------------------------------------------------------------------
    # Export su file
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
        Salva su file le posizioni storiche.

        Args:
            file_format: "geojson" | "gpx" | "csv"

        Returns:
            True se l'esportazione è riuscita.
        """
        positions = self._fetch(device, from_dt, to_dt)
        if not positions:
            log.warning("Nessuna posizione da esportare per %s", device.name)
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
                log.error("Formato non supportato: %s", file_format)
                return False
        except Exception as exc:
            log.error("Errore durante l'esportazione su file: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Fetch posizioni
    # ------------------------------------------------------------------

    def _fetch(
        self, device: Device, from_dt: datetime, to_dt: datetime
    ) -> List[Position]:
        try:
            positions = self._client.get_route(device.id, from_dt, to_dt)
            if not positions:
                # Fallback a get_positions se route non restituisce nulla
                positions = self._client.get_positions(device.id, from_dt, to_dt)
            return positions
        except TraccarError as exc:
            log.error("Errore fetch posizioni storiche: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Build layer QGIS
    # ------------------------------------------------------------------

    @staticmethod
    def _make_base_layer(geom_type: str, name: str) -> QgsVectorLayer:
        uri = f"{geom_type}?crs=EPSG:4326"
        lyr = QgsVectorLayer(uri, name, "memory")
        if not lyr.isValid():
            raise RuntimeError(f"Impossibile creare layer '{name}'")
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
            valid = positions  # usa tutti se non ci sono abbastanza valid

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
    # Scrittura file
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
        log.info("GeoJSON scritto: %s (%d features)", path, len(fc["features"]))
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
        log.info("GPX scritto: %s (%d trackpoints)", path, len(positions))
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
        log.info("CSV scritto: %s (%d righe)", path, len(positions))
        return True


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )

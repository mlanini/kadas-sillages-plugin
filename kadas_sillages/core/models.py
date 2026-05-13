# -*- coding: utf-8 -*-
"""
Data models for Traccar devices and positions.
Simple dataclasses mirroring the Traccar v6 OpenAPI schema.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class Device:
    """Representation of a Traccar device (GET /api/devices)."""
    id: int
    name: str
    unique_id: str
    status: str = "unknown"          # "online" | "offline" | "unknown"
    disabled: bool = False
    last_update: Optional[datetime] = None
    position_id: Optional[int] = None
    group_id: Optional[int] = None
    category: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)

    # Visual options (managed plugin-side, not by Traccar)
    visible: bool = True
    icon_path: Optional[str] = None      # absolute path to an SVG/PNG icon
    track_color: str = "#0000FF"         # hex colour
    track_width: int = 2                 # pixels
    track_max_points: int = 100          # maximum number of points in the track
    show_label: bool = True

    @staticmethod
    def from_dict(data: dict) -> "Device":
        return Device(
            id=data["id"],
            name=data.get("name", ""),
            unique_id=data.get("uniqueId", ""),
            status=data.get("status", "unknown"),
            disabled=data.get("disabled", False),
            last_update=_parse_dt(data.get("lastUpdate")),
            position_id=data.get("positionId"),
            group_id=data.get("groupId"),
            category=data.get("category"),
            attributes=data.get("attributes", {}),
        )


@dataclass
class Position:
    """Representation of a Traccar position (GET /api/positions or WebSocket)."""
    id: int
    device_id: int
    device_time: Optional[datetime]
    fix_time: Optional[datetime]
    server_time: Optional[datetime]
    valid: bool
    latitude: float
    longitude: float
    altitude: float = 0.0
    speed: float = 0.0          # knots
    course: float = 0.0         # degrees 0-360
    address: Optional[str] = None
    accuracy: float = 0.0
    attributes: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(data: dict) -> "Position":
        return Position(
            id=data["id"],
            device_id=data["deviceId"],
            device_time=_parse_dt(data.get("deviceTime")),
            fix_time=_parse_dt(data.get("fixTime")),
            server_time=_parse_dt(data.get("serverTime")),
            valid=data.get("valid", False),
            latitude=data["latitude"],
            longitude=data["longitude"],
            altitude=data.get("altitude", 0.0),
            speed=data.get("speed", 0.0),
            course=data.get("course", 0.0),
            address=data.get("address"),
            accuracy=data.get("accuracy", 0.0),
            attributes=data.get("attributes", {}),
        )


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # ISO 8601 con eventuale trailing Z
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None

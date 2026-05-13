# -*- coding: utf-8 -*-
"""
Persistent plugin settings backed by QgsSettings.
All keys are grouped under the 'kadas_sillages/' prefix.
"""
from __future__ import annotations
from typing import Optional

from qgis.core import QgsSettings

_PREFIX = "kadas_sillages"


class PluginSettings:
    """Typed wrapper around QgsSettings for the KadasSillages plugin."""

    # ------------------------------------------------------------------
    # Server / authentication
    # ------------------------------------------------------------------

    @staticmethod
    def server_url() -> str:
        return QgsSettings().value(f"{_PREFIX}/server_url", "", type=str)

    @staticmethod
    def set_server_url(url: str) -> None:
        QgsSettings().setValue(f"{_PREFIX}/server_url", url.rstrip("/"))

    @staticmethod
    def username() -> str:
        return QgsSettings().value(f"{_PREFIX}/username", "", type=str)

    @staticmethod
    def set_username(value: str) -> None:
        QgsSettings().setValue(f"{_PREFIX}/username", value)

    @staticmethod
    def password() -> str:
        """
        Password stored in plain text in QgsSettings (encrypted by the Qt
        keystore when available). Consider QgsAuthManager for production.
        """
        return QgsSettings().value(f"{_PREFIX}/password", "", type=str)

    @staticmethod
    def set_password(value: str) -> None:
        QgsSettings().setValue(f"{_PREFIX}/password", value)

    # ------------------------------------------------------------------
    # Behaviour
    # ------------------------------------------------------------------

    @staticmethod
    def auto_connect() -> bool:
        """Automatically reconnect on plugin load when True."""
        return QgsSettings().value(f"{_PREFIX}/auto_connect", False, type=bool)

    @staticmethod
    def set_auto_connect(value: bool) -> None:
        QgsSettings().setValue(f"{_PREFIX}/auto_connect", value)

    @staticmethod
    def default_track_color() -> str:
        return QgsSettings().value(f"{_PREFIX}/default_track_color", "#0000FF", type=str)

    @staticmethod
    def set_default_track_color(value: str) -> None:
        QgsSettings().setValue(f"{_PREFIX}/default_track_color", value)

    @staticmethod
    def default_track_width() -> int:
        return QgsSettings().value(f"{_PREFIX}/default_track_width", 2, type=int)

    @staticmethod
    def set_default_track_width(value: int) -> None:
        QgsSettings().setValue(f"{_PREFIX}/default_track_width", value)

    @staticmethod
    def default_track_max_points() -> int:
        return QgsSettings().value(f"{_PREFIX}/default_track_max_points", 100, type=int)

    @staticmethod
    def set_default_track_max_points(value: int) -> None:
        QgsSettings().setValue(f"{_PREFIX}/default_track_max_points", value)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def is_configured() -> bool:
        """Return True if URL and credentials have been set."""
        s = PluginSettings
        return bool(s.server_url() and s.username() and s.password())

    @staticmethod
    def clear() -> None:
        """Remove all plugin settings."""
        qs = QgsSettings()
        qs.beginGroup(_PREFIX)
        qs.remove("")
        qs.endGroup()

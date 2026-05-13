# -*- coding: utf-8 -*-
"""
Gestione persistente delle impostazioni del plugin tramite QgsSettings.
Tutte le chiavi sono raggruppate sotto il prefisso 'kadas_sillages/'.
"""
from __future__ import annotations
from typing import Optional

from qgis.core import QgsSettings

_PREFIX = "kadas_sillages"


class PluginSettings:
    """Wrapper tipizzato attorno a QgsSettings per il plugin KadasSillages."""

    # ------------------------------------------------------------------
    # Server / autenticazione
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
        La password è salvata in chiaro in QgsSettings (cifrata dal keystore Qt
        se disponibile). Per produzione considerare QgsAuthManager.
        """
        return QgsSettings().value(f"{_PREFIX}/password", "", type=str)

    @staticmethod
    def set_password(value: str) -> None:
        QgsSettings().setValue(f"{_PREFIX}/password", value)

    # ------------------------------------------------------------------
    # Comportamento
    # ------------------------------------------------------------------

    @staticmethod
    def auto_connect() -> bool:
        """Riconnette automaticamente all'avvio del plugin se True."""
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
    # Utilità
    # ------------------------------------------------------------------

    @staticmethod
    def is_configured() -> bool:
        """Ritorna True se URL e credenziali sono stati impostati."""
        s = PluginSettings
        return bool(s.server_url() and s.username() and s.password())

    @staticmethod
    def clear() -> None:
        """Rimuove tutte le impostazioni del plugin."""
        qs = QgsSettings()
        qs.beginGroup(_PREFIX)
        qs.remove("")
        qs.endGroup()

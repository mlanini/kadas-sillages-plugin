# -*- coding: utf-8 -*-
"""Utility generali del plugin."""
import os


def plugin_path(*parts: str) -> str:
    """Ritorna il path assoluto relativo alla root del pacchetto plugin."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def resource_path(filename: str) -> str:
    """Ritorna il path assoluto di un file nella cartella resources/."""
    return plugin_path("resources", filename)

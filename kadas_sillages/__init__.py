# -*- coding: utf-8 -*-
"""
Entry point del plugin KADAS Sillages.
Chiamato da KADAS/QGIS al momento del caricamento del plugin.
"""


def classFactory(iface):  # noqa: N802
    from .plugin import KadasSillagesPlugin
    return KadasSillagesPlugin(iface)

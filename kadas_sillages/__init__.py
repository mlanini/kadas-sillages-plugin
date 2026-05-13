# -*- coding: utf-8 -*-
"""
Entry point for the KADAS Sillages plugin.
Called by KADAS/QGIS when the plugin is loaded.
"""


def classFactory(iface):  # noqa: N802
    from .plugin import KadasSillagesPlugin
    return KadasSillagesPlugin(iface)

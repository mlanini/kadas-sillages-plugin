# -*- coding: utf-8 -*-
"""
Classe principale del plugin KadasSillages.
"""
import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .logger import get_logger

log = get_logger(__name__)


class KadasSillagesPlugin:
    """Plugin KADAS per il live tracking via server Traccar."""

    PLUGIN_NAME = "Sillages"
    RIBBON_TAB = "GPS"          # Tab del ribbon KADAS dove aggiungere il pulsante

    def __init__(self, iface):
        try:
            from kadas.kadasgui import KadasPluginInterface
            self.iface = KadasPluginInterface.cast(iface)
        except Exception:
            # Fallback per testing fuori da KADAS (QGIS puro)
            self.iface = iface

        self._main_dock = None
        self._toggle_action = None

    # ------------------------------------------------------------------
    # Ciclo di vita
    # ------------------------------------------------------------------

    def initGui(self):
        """Chiamato da KADAS quando il plugin viene abilitato."""
        icon = QIcon(self._icon_path("icon.svg"))

        self._toggle_action = QAction(icon, self.PLUGIN_NAME, self.iface.mainWindow())
        self._toggle_action.setCheckable(True)
        self._toggle_action.setToolTip(self.tr("Live tracking Traccar"))
        self._toggle_action.toggled.connect(self._on_toggle)

        # Aggiunge il pulsante al ribbon KADAS:
        #   • tab GPS_TAB  (posizione principale)
        #   • tab PLUGIN_MENU (tab "Plugins" — sempre visibile)
        try:
            from kadas.kadasgui import KadasPluginInterface
            self.iface.addAction(
                self._toggle_action,
                self.iface.PLUGIN_MENU,
                self.iface.GPS_TAB,
            )
            self.iface.addAction(
                self._toggle_action,
                self.iface.PLUGIN_MENU,
                self.iface.PLUGIN_MENU,
            )
        except Exception:
            self.iface.addPluginToMenu(self.PLUGIN_NAME, self._toggle_action)

        log.info("KadasSillages: initGui completato")

    def unload(self):
        """Chiamato da KADAS quando il plugin viene disabilitato o l'app si chiude."""
        if self._main_dock is not None:
            self._main_dock.close()
            self.iface.mainWindow().removeDockWidget(self._main_dock)
            self._main_dock = None

        try:
            from kadas.kadasgui import KadasPluginInterface
            self.iface.removeAction(
                self._toggle_action,
                self.iface.PLUGIN_MENU,
                self.iface.GPS_TAB,
            )
            self.iface.removeAction(
                self._toggle_action,
                self.iface.PLUGIN_MENU,
                self.iface.PLUGIN_MENU,
            )
        except Exception:
            self.iface.removePluginMenu(self.PLUGIN_NAME, self._toggle_action)

        if self._toggle_action:
            self._toggle_action.deleteLater()
            self._toggle_action = None

        log.info("KadasSillages: unload completato")

    # ------------------------------------------------------------------
    # Slot
    # ------------------------------------------------------------------

    def _on_toggle(self, checked: bool):
        """Mostra/nasconde il pannello principale."""
        if checked:
            self._ensure_main_dock()
            self._main_dock.show()
        else:
            if self._main_dock is not None:
                self._main_dock.hide()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_main_dock(self):
        """Crea il DockWidget principale la prima volta che viene richiesto (lazy init)."""
        if self._main_dock is not None:
            return

        from qgis.PyQt.QtCore import Qt
        from .gui.main_dock import MainDock

        self._main_dock = MainDock(self.iface, self.iface.mainWindow())
        self._main_dock.closed.connect(lambda: self._toggle_action.setChecked(False))
        self.iface.mainWindow().addDockWidget(Qt.RightDockWidgetArea, self._main_dock)

    @staticmethod
    def _icon_path(filename: str) -> str:
        return os.path.join(os.path.dirname(__file__), "resources", filename)

    @staticmethod
    def tr(message: str) -> str:  # noqa: N802 – QObject.tr convention
        return message

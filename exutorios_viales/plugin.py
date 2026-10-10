# -*- coding: utf-8 -*-
# Complemento QGIS «Exutorios Viales»
# Copyright (C) 2026 Jose Ospina
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version. See the LICENSE file for details.
import os

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
try:
    from qgis.PyQt.QtWidgets import QAction
except ImportError:  # Qt6
    from qgis.PyQt.QtGui import QAction
from qgis.core import QgsApplication

from .provider import ExutoriosVialesProvider

ID_ALGORITMO_RAPIDO = "exutoriosviales:cuencas_alcantarillas_rapido"
ID_ALGORITMO_COMPLETO = "exutoriosviales:cuencas_alcantarillas"
MENU = "&Exutorios Viales"
URL_MANUAL = "https://github.com/Andy-rba30/Exutorios/blob/main/docs/MANUAL_PARAMETROS.md"


class ExutoriosVialesPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.acciones = []

    def initProcessing(self):
        if self.provider is None:
            self.provider = ExutoriosVialesProvider()
            QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()
        carpeta = os.path.dirname(__file__)
        icono = QIcon(os.path.join(carpeta, "icon.png"))

        rapido = QAction(icono, "Cuencas de alcantarillas (análisis rápido)", self.iface.mainWindow())
        rapido.setToolTip("Elige el DEM y el eje de la vía y ejecuta")
        rapido.triggered.connect(lambda: self.ejecutar(ID_ALGORITMO_RAPIDO))
        self.iface.addToolBarIcon(rapido)
        self.iface.addPluginToMenu(MENU, rapido)
        self.acciones.append(rapido)

        completo = QAction(icono, "Análisis completo…", self.iface.mainWindow())
        completo.setToolTip("Todos los parámetros a la vista")
        completo.triggered.connect(lambda: self.ejecutar(ID_ALGORITMO_COMPLETO))
        self.iface.addPluginToMenu(MENU, completo)
        self.acciones.append(completo)

        manual = QAction("Manual de parámetros (criterios)", self.iface.mainWindow())
        manual.triggered.connect(self.abrir_manual)
        self.iface.addPluginToMenu(MENU, manual)
        self.acciones.append(manual)

    def ejecutar(self, id_algoritmo):
        import processing
        processing.execAlgorithmDialog(id_algoritmo)

    def abrir_manual(self):
        local = os.path.join(os.path.dirname(__file__), "MANUAL_PARAMETROS.md")
        if os.path.exists(local):
            QDesktopServices.openUrl(QUrl.fromLocalFile(local))
        else:
            QDesktopServices.openUrl(QUrl(URL_MANUAL))

    def unload(self):
        for accion in self.acciones:
            self.iface.removeToolBarIcon(accion)
            self.iface.removePluginMenu(MENU, accion)
        self.acciones = []
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

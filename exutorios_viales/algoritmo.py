# -*- coding: utf-8 -*-
# Complemento QGIS «Exutorios Viales»
# Copyright (C) 2026 Jose Ospina
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version. See the LICENSE file for details.
"""
Algoritmos de Procesos de QGIS del complemento «Exutorios Viales».

- CuencasAlcantarillasAlgorithm: análisis completo (todos los parámetros a la vista).
- CuencasAlcantarillasRapidoAlgorithm: análisis con DEM + eje; el resto en
  «Parámetros avanzados» con valores por defecto.

El DEM se prepara automáticamente igual que en «Cota de Anegamiento»:
reproyección a UTM si viene en grados, remuestreo si tiene demasiadas
celdas y relleno de huecos pequeños sin datos.
"""

import math
import os

import numpy as np

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingLayerPostProcessorInterface,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsWkbTypes,
)

from . import acondicionar as ac
from . import red, hidrologia as hd, herramientas as h

# Límite de celdas a partir del cual el DEM se remuestrea automáticamente
MAX_CELDAS_AUTO = 6_000_000

# ---------------------------------------------------------------------------
# Compatibilidad entre versiones de QGIS 3.x (y QGIS 4)
# ---------------------------------------------------------------------------

try:
    _CAMPO_CUALQUIERA = Qgis.ProcessingFieldParameterDataType.Any
except AttributeError:
    _CAMPO_CUALQUIERA = QgsProcessingParameterField.Any

try:
    _NUM_DOUBLE = Qgis.ProcessingNumberParameterType.Double
    _NUM_INT = Qgis.ProcessingNumberParameterType.Integer
except AttributeError:
    _NUM_DOUBLE = QgsProcessingParameterNumber.Double
    _NUM_INT = QgsProcessingParameterNumber.Integer

try:
    _TIPO_LINEA = Qgis.ProcessingSourceType.VectorLine
    _TIPO_PUNTO = Qgis.ProcessingSourceType.VectorPoint
    _TIPO_CUALQUIERA = Qgis.ProcessingSourceType.VectorAnyGeometry
except AttributeError:
    _TIPO_LINEA = QgsProcessing.TypeVectorLine
    _TIPO_PUNTO = QgsProcessing.TypeVectorPoint
    _TIPO_CUALQUIERA = QgsProcessing.TypeVectorAnyGeometry

try:
    _WKB_POLIGONO = Qgis.WkbType.MultiPolygon
    _WKB_PUNTO = Qgis.WkbType.Point
    _WKB_LINEA = Qgis.WkbType.LineString
except AttributeError:
    _WKB_POLIGONO = QgsWkbTypes.MultiPolygon
    _WKB_PUNTO = QgsWkbTypes.Point
    _WKB_LINEA = QgsWkbTypes.LineString

if Qgis.QGIS_VERSION_INT >= 33800:
    from qgis.PyQt.QtCore import QMetaType
    _T_DOUBLE, _T_INT, _T_STR = QMetaType.Type.Double, QMetaType.Type.Int, QMetaType.Type.QString
else:
    _T_DOUBLE, _T_INT, _T_STR = QVariant.Double, QVariant.Int, QVariant.String


def _avanzado(param):
    try:
        param.setFlags(param.flags() | Qgis.ProcessingParameterFlag.Advanced)
    except AttributeError:
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
    return param


def _num(v):
    """NaN -> None (NULL en la tabla de atributos)."""
    if v is None:
        return None
    try:
        return None if not math.isfinite(v) else float(v)
    except TypeError:
        return None


def _tr(texto):
    return QCoreApplication.translate("ExutoriosViales", texto)


def _si_no(v):
    return "SI" if v else "NO"


def _tr_txt(tr):
    """Nombre corto de un periodo de retorno para campos: 25 -> «25», 2.5 -> «2_5»."""
    return ("%g" % tr).replace(".", "_")


# ---------------------------------------------------------------------------
# Estilos automáticos de las capas de salida
# ---------------------------------------------------------------------------

_POST_PROCESADORES = []


def _estilo_pseudocolor(capa, puntos):
    """Pseudocolor monobanda con cortes (fracción del máximo, color)."""
    from qgis.core import (QgsColorRampShader, QgsRasterShader, QgsSingleBandPseudoColorRenderer)
    prov = capa.dataProvider()
    try:
        est = prov.bandStatistics(1, Qgis.RasterBandStatistic.All)
    except AttributeError:
        from qgis.core import QgsRasterBandStats
        est = prov.bandStatistics(1, QgsRasterBandStats.All)
    mn, mx = float(est.minimumValue), float(est.maximumValue)
    if not (math.isfinite(mn) and math.isfinite(mx)):
        return
    if mx - mn < 1e-6:
        mx = mn + 1e-6
    fn = QgsColorRampShader()
    try:
        fn.setColorRampType(Qgis.ShaderInterpolationMethod.Linear)
    except AttributeError:
        fn.setColorRampType(QgsColorRampShader.Interpolated)
    items = []
    for frac, c in puntos:
        v = mn + (mx - mn) * frac
        items.append(QgsColorRampShader.ColorRampItem(v, QColor(c), "%.1f" % v))
    fn.setColorRampItemList(items)
    sombreado = QgsRasterShader()
    sombreado.setRasterShaderFunction(fn)
    capa.setRenderer(QgsSingleBandPseudoColorRenderer(prov, 1, sombreado))
    capa.triggerRepaint()


def _estilo_acumulacion(capa):
    _estilo_pseudocolor(capa, [(0.0, "#ffffff"), (0.001, "#deebf7"), (0.01, "#9ecae1"), (0.1, "#3182bd"),
                               (1.0, "#08306b")])


def _estilo_paleta(capa):
    from qgis.core import QgsPalettedRasterRenderer
    prov = capa.dataProvider()
    try:
        clases = QgsPalettedRasterRenderer.classDataFromRaster(prov, 1)
        capa.setRenderer(QgsPalettedRasterRenderer(prov, 1, clases))
        capa.triggerRepaint()
    except Exception:
        pass


def _estilo_cauces(capa):
    """Grosor y azul según el orden de Strahler."""
    from qgis.core import QgsGraduatedSymbolRenderer, QgsLineSymbol, QgsRendererRange
    rangos = [(0.5, 1.5, "#9ecae1", "0.35", _tr("Orden 1")), (1.5, 2.5, "#4292c6", "0.6", _tr("Orden 2")),
              (2.5, 3.5, "#2171b5", "0.9", _tr("Orden 3")), (3.5, 99, "#08306b", "1.3", _tr("Orden 4 o más"))]
    lista = []
    for a, b, color, ancho, etiqueta in rangos:
        s = QgsLineSymbol.createSimple({"color": color, "width": ancho})
        lista.append(QgsRendererRange(a, b, s, etiqueta))
    capa.setRenderer(QgsGraduatedSymbolRenderer("orden", lista))
    capa.triggerRepaint()


def _estilo_salidas(capa):
    from qgis.core import QgsRuleBasedRenderer, QgsMarkerSymbol
    raiz = QgsRuleBasedRenderer.Rule(None)
    reglas = [("\"origen\" = 'punto'", "#d7301f", _tr("Punto dado (alcantarilla del diseño)")),
              ("\"origen\" = 'punto+cruce'", "#7a0177", _tr("Punto dado que coincide con un cruce")),
              ("ELSE", "#fd8d3c", _tr("Cruce automático cauce–eje"))]
    for filtro, color, etiqueta in reglas:
        s = QgsMarkerSymbol.createSimple({"name": "circle", "color": color, "outline_color": "#333333",
                                          "outline_width": "0.3", "size": "3.2"})
        raiz.appendChild(QgsRuleBasedRenderer.Rule(s, 0, 0, filtro, etiqueta))
    capa.setRenderer(QgsRuleBasedRenderer(raiz))
    capa.triggerRepaint()


def _estilo_cuencas(capa):
    from qgis.core import QgsRuleBasedRenderer, QgsFillSymbol
    raiz = QgsRuleBasedRenderer.Rule(None)
    reglas = [("\"escenario\" = 'con_via'", "0,109,44,40", "0,109,44,255", "0.7", _tr("Cuenca con la vía como barrera")),
              ("\"borde\" = 'SI'", "222,45,38,50", "165,15,21,255", "0.6", _tr("Cuenca natural que toca el borde del DEM")),
              ("ELSE", "49,130,189,50", "8,81,156,255", "0.6", _tr("Cuenca natural"))]
    for filtro, relleno, borde, ancho, etiqueta in reglas:
        s = QgsFillSymbol.createSimple({"color": relleno, "outline_color": borde, "outline_width": ancho})
        raiz.appendChild(QgsRuleBasedRenderer.Rule(s, 0, 0, filtro, etiqueta))
    capa.setRenderer(QgsRuleBasedRenderer(raiz))
    capa.triggerRepaint()


def _estilo_recorridos(capa):
    from qgis.core import QgsSingleSymbolRenderer, QgsLineSymbol
    s = QgsLineSymbol.createSimple({"color": "#b30000", "width": "0.6", "line_style": "dash"})
    capa.setRenderer(QgsSingleSymbolRenderer(s))
    capa.triggerRepaint()


class _PostProcesador(QgsProcessingLayerPostProcessorInterface):
    def __init__(self, funcion, nombre=None):
        super().__init__()
        self.funcion = funcion
        self.nombre = nombre

    def postProcessLayer(self, capa, context, feedback):
        try:
            if self.nombre:
                capa.setName(self.nombre)
            self.funcion(capa)
        except Exception as err:  # el estilo nunca debe hacer fallar el algoritmo
            feedback.pushWarning(_tr("No se pudo aplicar el estilo automático: %s") % err)


def _programar_estilo(context, ruta_o_id, funcion, nombre=None):
    if not ruta_o_id:
        return
    try:
        if context.willLoadLayerOnCompletion(ruta_o_id):
            pp = _PostProcesador(funcion, nombre)
            _POST_PROCESADORES.append(pp)
            detalles = context.layerToLoadOnCompletionDetails(ruta_o_id)
            if nombre:
                detalles.name = nombre
            detalles.setPostProcessor(pp)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# E/S de rásters con GDAL (viene con QGIS)
# ---------------------------------------------------------------------------

def _preparar_dem(ruta, celda_objetivo=0.0, max_huecos=10, max_celdas=MAX_CELDAS_AUTO, feedback=None):
    """Abre el DEM con GDAL y lo deja listo para el análisis (misma lógica
    que «Cota de Anegamiento»). Devuelve (arr, validos, gt, wkt, notas)."""
    from osgeo import gdal, osr

    def info(msg):
        if feedback is not None:
            feedback.pushInfo(msg)

    notas = []
    ds = gdal.Open(ruta)
    if ds is None:
        raise QgsProcessingException(_tr("No se pudo abrir el DEM con GDAL: %s") % ruta)
    banda = ds.GetRasterBand(1)
    nodata = banda.GetNoDataValue()

    wkt = ds.GetProjection() or ""
    srs = osr.SpatialReference()
    geografico = False
    if wkt:
        srs.ImportFromWkt(wkt)
        geografico = bool(srs.IsGeographic())
    gt = ds.GetGeoTransform()
    rotado = abs(gt[2]) > 1e-12 or abs(gt[4]) > 1e-12
    nd_warp = nodata if nodata is not None else -9999.0

    if geografico:
        cx = gt[0] + gt[1] * ds.RasterXSize / 2.0 + gt[2] * ds.RasterYSize / 2.0
        cy = gt[3] + gt[4] * ds.RasterXSize / 2.0 + gt[5] * ds.RasterYSize / 2.0
        epsg = epsg_utm(cx, cy)
        celda = celda_objetivo if celda_objetivo > 0 else celda_redondeada(abs(gt[5]) * 111320.0)
        info(_tr("El DEM está en grados: se reproyecta a EPSG:%d (UTM) con celda de %g m.") % (epsg, celda))
        ds = gdal.Warp("", ds, format="MEM", dstSRS="EPSG:%d" % epsg, xRes=celda, yRes=celda,
                       resampleAlg="bilinear", srcNodata=nodata, dstNodata=nd_warp)
        if ds is None:
            raise QgsProcessingException(_tr("No se pudo reproyectar el DEM a UTM."))
        notas.append(_tr("reproyección automática de grados a EPSG:%d, celda %g m") % (epsg, celda))
        wkt = ds.GetProjection()
        gt = ds.GetGeoTransform()
    elif rotado or (celda_objetivo > 0 and abs(abs(gt[1]) - celda_objetivo) > 1e-9):
        celda = celda_objetivo if celda_objetivo > 0 else celda_redondeada(math.hypot(gt[1], gt[2]))
        alg = "average" if celda > abs(gt[1]) * 1.5 else "bilinear"
        info(_tr("Remuestreando el DEM a celda de %g m…") % celda)
        ds = gdal.Warp("", ds, format="MEM", xRes=celda, yRes=celda, resampleAlg=alg,
                       srcNodata=nodata, dstNodata=nd_warp)
        if ds is None:
            raise QgsProcessingException(_tr("No se pudo remuestrear el DEM."))
        notas.append(_tr("remuestreo a celda de %g m") % celda)
        gt = ds.GetGeoTransform()

    n = ds.RasterXSize * ds.RasterYSize
    if celda_objetivo <= 0 and n > max_celdas:
        f = math.sqrt(n / float(max_celdas))
        celda = celda_redondeada(abs(gt[1]) * f)
        if celda > abs(gt[1]):
            info(_tr("El DEM tiene %.1f millones de celdas: se remuestrea a %g m para que el cálculo sea "
                     "manejable. Fija el «tamaño de celda de trabajo» si prefieres otro valor.") % (n / 1e6, celda))
            ds = gdal.Warp("", ds, format="MEM", xRes=celda, yRes=celda, resampleAlg="average",
                           srcNodata=nodata, dstNodata=nd_warp)
            if ds is None:
                raise QgsProcessingException(_tr("No se pudo remuestrear el DEM."))
            notas.append(_tr("remuestreo automático a celda de %g m por tamaño (%.1f millones de celdas)")
                         % (celda, n / 1e6))
            gt = ds.GetGeoTransform()

    banda = ds.GetRasterBand(1)
    nodata = banda.GetNoDataValue()
    if max_huecos and max_huecos > 0 and nodata is not None:
        arr0 = banda.ReadAsArray()
        huecos = np.isclose(arr0, nodata) | ~np.isfinite(arr0)
        interior = huecos_interiores(huecos)
        if interior.any():
            if ds.GetDriver().ShortName != "MEM":
                ds = gdal.GetDriverByName("MEM").CreateCopy("", ds)
                banda = ds.GetRasterBand(1)
            mds = gdal.GetDriverByName("MEM").Create("", ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Byte)
            mb = mds.GetRasterBand(1)
            mb.WriteArray(np.where(interior, 0, 255).astype(np.uint8))
            gdal.FillNodata(targetBand=banda, maskBand=mb, maxSearchDist=int(max_huecos), smoothingIterations=0)
            banda.FlushCache()
            n_huecos = int(interior.sum())
            notas.append(_tr("relleno de %d celdas sin dato en huecos interiores (búsqueda máxima %d celdas)")
                         % (n_huecos, int(max_huecos)))
            info(_tr("Se rellenaron %d celdas sin dato en huecos interiores del DEM.") % n_huecos)

    gt = ds.GetGeoTransform()
    if abs(gt[2]) > 1e-12 or abs(gt[4]) > 1e-12:
        raise QgsProcessingException(_tr("El DEM sigue rotado tras el remuestreo; reproyéctalo manualmente."))
    banda = ds.GetRasterBand(1)
    arr = banda.ReadAsArray().astype(np.float64)
    nodata = banda.GetNoDataValue()
    validos = np.isfinite(arr)
    if nodata is not None:
        validos &= ~np.isclose(arr, nodata)
    validos &= arr > -1000
    arr = np.where(validos, arr, np.nan)
    return arr, validos, gt, ds.GetProjection() or wkt, notas


def epsg_utm(lon, lat):
    """Código EPSG de la zona UTM (WGS 84) que contiene el punto (lon, lat)."""
    zona = int(math.floor((lon + 180.0) / 6.0)) + 1
    zona = min(max(zona, 1), 60)
    return (32600 if lat >= 0 else 32700) + zona


def celda_redondeada(celda_m):
    """Redondea un tamaño de celda a 2 cifras significativas."""
    if celda_m <= 0 or not math.isfinite(celda_m):
        return 1.0
    exp = math.floor(math.log10(celda_m))
    base = 10.0 ** (exp - 1)
    return max(round(celda_m / base) * base, base)


def huecos_interiores(mascara_nodata):
    """Celdas sin dato que NO están conectadas (8 vecinos) con el borde del DEM."""
    m = np.asarray(mascara_nodata, dtype=bool)
    if not m.any():
        return np.zeros_like(m)
    lab, n = ac.etiquetar(m)
    if n == 0:
        return np.zeros_like(m)
    borde = np.concatenate((lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]))
    toca = np.zeros(n + 1, dtype=bool)
    toca[np.unique(borde)] = True
    toca[0] = False
    return (lab > 0) & ~toca[lab]


def _escribir_raster(ruta, arr, gt, wkt, nodata=-9999.0, entero=False):
    from osgeo import gdal
    from qgis.core import QgsRasterFileWriter
    ext = os.path.splitext(ruta)[1].lower().lstrip(".")
    driver_nombre = QgsRasterFileWriter.driverForExtension(ext) if ext else "GTiff"
    drv = gdal.GetDriverByName(driver_nombre or "GTiff") or gdal.GetDriverByName("GTiff")
    filas, cols = arr.shape
    opciones = ["COMPRESS=DEFLATE", "TILED=YES"] if drv.ShortName == "GTiff" else []
    tipo = gdal.GDT_Int32 if entero else gdal.GDT_Float32
    ds = drv.Create(ruta, cols, filas, 1, tipo, options=opciones)
    if ds is None:
        raise QgsProcessingException(_tr("No se pudo crear el ráster de salida: %s") % ruta)
    ds.SetGeoTransform(gt)
    ds.SetProjection(wkt)
    b = ds.GetRasterBand(1)
    if entero:
        b.SetNoDataValue(0)
        b.WriteArray(arr.astype(np.int32))
    else:
        b.SetNoDataValue(nodata)
        b.WriteArray(np.where(np.isfinite(arr), arr, nodata).astype(np.float32))
    b.FlushCache()
    ds = None


def _poligono_mascara(mascara2d, gt, wkt, x_sal, y_sal):
    """Polígono (QgsGeometry multipolígono) de una máscara ráster, sin islas:
    se conserva solo la parte que contiene el punto de salida (o la mayor).
    Devuelve (geometria, n_partes_descartadas)."""
    from osgeo import gdal, ogr
    filas, cols = mascara2d.shape
    ds = gdal.GetDriverByName("MEM").Create("", cols, filas, 1, gdal.GDT_Byte)
    ds.SetGeoTransform(gt)
    ds.SetProjection(wkt)
    b = ds.GetRasterBand(1)
    b.WriteArray(mascara2d.astype(np.uint8))
    b.SetNoDataValue(0)
    drv = ogr.GetDriverByName("Memory") or ogr.GetDriverByName("MEM")
    vds = drv.CreateDataSource("poligonos")
    capa = vds.CreateLayer("p", geom_type=ogr.wkbPolygon)
    capa.CreateField(ogr.FieldDefn("id", ogr.OFTInteger))
    gdal.Polygonize(b, b.GetMaskBand(), capa, 0, ["8CONNECTED=8"], callback=None)
    geoms = []
    for f in capa:
        if f.GetField(0):
            geoms.append(QgsGeometry.fromWkt(f.GetGeometryRef().ExportToWkt()))
    if not geoms:
        return None, 0
    if len(geoms) == 1:
        g = geoms[0]
    else:
        pt = QgsGeometry.fromPointXY(QgsPointXY(x_sal, y_sal))
        contiene = [g for g in geoms if g.intersects(pt)]
        g = contiene[0] if contiene else max(geoms, key=lambda q: q.area())
    g.convertToMultiType()
    return g, len(geoms) - 1


def _rasterizar_poligonos(elementos, gt, forma, wkt):
    """Rasteriza polígonos (lista de (codigo_int, wkt)) -> array int32 (0 = ninguno)."""
    from osgeo import gdal, ogr, osr
    filas, cols = forma
    ds = gdal.GetDriverByName("MEM").Create("", cols, filas, 1, gdal.GDT_Int32)
    ds.SetGeoTransform(gt)
    ds.SetProjection(wkt)
    ds.GetRasterBand(1).Fill(0)
    drv = ogr.GetDriverByName("Memory") or ogr.GetDriverByName("MEM")
    vds = drv.CreateDataSource("suelos")
    srs = osr.SpatialReference()
    if wkt:
        srs.ImportFromWkt(wkt)
    capa = vds.CreateLayer("s", srs=srs, geom_type=ogr.wkbUnknown)
    capa.CreateField(ogr.FieldDefn("codigo", ogr.OFTInteger))
    defn = capa.GetLayerDefn()
    for codigo, w in elementos:
        f = ogr.Feature(defn)
        f.SetField("codigo", int(codigo))
        f.SetGeometry(ogr.CreateGeometryFromWkt(w))
        capa.CreateFeature(f)
    gdal.RasterizeLayer(ds, [1], capa, options=["ATTRIBUTE=codigo", "ALL_TOUCHED=FALSE"])
    return ds.GetRasterBand(1).ReadAsArray().astype(np.int32)


# ---------------------------------------------------------------------------
# Lectura de capas vectoriales
# ---------------------------------------------------------------------------

def _polilineas_de_fuente(fuente, crs, context):
    """Lista de polilíneas [(x, y), ...] en el CRS del DEM. Las geometrías con
    curvas (CompoundCurve de DXF) se segmentan; la Z se descarta."""
    polilineas = []
    transf = QgsCoordinateTransform(fuente.sourceCrs(), crs, context.transformContext())
    for f in fuente.getFeatures():
        g = QgsGeometry(f.geometry())
        if g.isNull() or g.isEmpty():
            continue
        try:
            if g.constGet() is not None and g.constGet().hasCurvedSegments():
                g = QgsGeometry(g.constGet().segmentize())
        except Exception:
            pass
        if transf.isValid() and fuente.sourceCrs().isValid() and crs.isValid():
            g.transform(transf)
        partes = g.asGeometryCollection() if g.isMultipart() else [g]
        for parte in partes:
            try:
                pl = parte.asPolyline()
            except Exception:
                pl = []
            if len(pl) >= 2:
                polilineas.append([(pt.x(), pt.y()) for pt in pl])
    return polilineas


def _puntos_de_fuente(fuente, crs, context, campo_nombre=None):
    """Lista de dicts {x, y, fid, nombre} en el CRS del DEM."""
    puntos = []
    transf = QgsCoordinateTransform(fuente.sourceCrs(), crs, context.transformContext())
    campos = fuente.fields()
    for f in fuente.getFeatures():
        g = QgsGeometry(f.geometry())
        if g.isNull() or g.isEmpty():
            continue
        if transf.isValid() and fuente.sourceCrs().isValid() and crs.isValid():
            g.transform(transf)
        partes = g.asGeometryCollection() if g.isMultipart() else [g]
        for parte in partes:
            try:
                p = parte.asPoint()
            except Exception:
                p = parte.centroid().asPoint()
            nombre = ""
            if campo_nombre and campos.indexOf(campo_nombre) >= 0:
                nombre = str(f[campo_nombre]) if f[campo_nombre] is not None else ""
            puntos.append({"x": p.x(), "y": p.y(), "fid": f.id(), "nombre": nombre})
    return puntos


def _interpretar_suelo(valor):
    """Devuelve ("grupo", "A".."D") o ("cn", float) o None."""
    if valor is None:
        return None
    s = str(valor).strip()
    if not s:
        return None
    try:
        v = float(s.replace(",", "."))
        if 1.0 <= v <= 100.0:
            return ("cn", v)
    except ValueError:
        pass
    letras = [ch for ch in s.upper() if ch in "ABCD"]
    if letras:
        # «grupo C», «C», «HSG-C»: se toma la última letra A-D del texto
        return ("grupo", letras[-1])
    return None


# ---------------------------------------------------------------------------
# Algoritmo completo
# ---------------------------------------------------------------------------

class CuencasAlcantarillasAlgorithm(QgsProcessingAlgorithm):
    DEM = "DEM"
    EJE = "EJE"
    PUNTOS = "PUNTOS"
    CAMPO_NOMBRE = "CAMPO_NOMBRE"
    UMBRAL_HA = "UMBRAL_HA"
    MODO_SALIDAS = "MODO_SALIDAS"
    LLUVIA = "LLUVIA"
    USO = "USO"
    AMC = "AMC"
    GRUPO_DEFECTO = "GRUPO_DEFECTO"
    CN_DIRECTO = "CN_DIRECTO"
    SUELOS = "SUELOS"
    CAMPO_SUELO = "CAMPO_SUELO"
    VIA_BARRERA = "VIA_BARRERA"
    ALTURA_VIA = "ALTURA_VIA"
    RADIO_AJUSTE = "RADIO_AJUSTE"
    FUSION = "FUSION"
    TOLERANCIA_CRUCE = "TOLERANCIA_CRUCE"
    DEPRESIONES = "DEPRESIONES"
    LONG_BREACH = "LONG_BREACH"
    SUAVIZAR = "SUAVIZAR"
    FACTOR_24H = "FACTOR_24H"
    IDF_TIPO = "IDF_TIPO"
    IDF_LAMBDA = "IDF_LAMBDA"
    IDF_KAPPA = "IDF_KAPPA"
    IDF_PSI = "IDF_PSI"
    IDF_THETA = "IDF_THETA"
    IDF_ETA = "IDF_ETA"
    TC_MIN = "TC_MIN"
    TC_CRITERIO = "TC_CRITERIO"
    C_RACIONAL = "C_RACIONAL"
    Q_ADOPTADO = "Q_ADOPTADO"
    DEP_AVISO = "DEP_AVISO"
    CELDA = "CELDA"
    HUECOS = "HUECOS"
    OUT_CAUCES = "OUT_CAUCES"
    OUT_SALIDAS = "OUT_SALIDAS"
    OUT_CUENCAS = "OUT_CUENCAS"
    OUT_RECORRIDOS = "OUT_RECORRIDOS"
    OUT_ACUM = "OUT_ACUMULACION"
    OUT_DIR = "OUT_DIRECCION"
    OUT_CUENCAS_R = "OUT_CUENCAS_RASTER"
    OUT_MFD = "OUT_MFD"
    OUT_CSV = "OUT_CSV"
    OUT_INFORME = "OUT_INFORME"
    RES_N = "N_SALIDAS"
    RES_QMAX = "Q_MAX"
    RES_RESUMEN = "RESUMEN"

    MODOS = ["Cruces automáticos cauce–eje", "Solo los puntos dados",
             "Ambos sin duplicar (recomendado)"]
    AMCS = ["II (condición normal)", "III (condición húmeda, más conservadora)"]
    DEPRESIONES_OPC = ["Rellenar (Priority-Flood, recomendado en terreno plano)",
                       "Abrir/romper (breaching de Lindsay) y rellenar el resto"]
    IDF_TIPOS = ["Dyck-Peschke a partir de la lluvia de 24 h (sin IDF)",
                 "IDF de Hydrognomon, Gumbel: i = λ(ψ − ln(−ln(1−1/T))) / (1+d/θ)^η, d en horas",
                 "IDF de Hydrognomon, GEV: i = λ'(T^κ' − ψ') / (1+d/θ)^η, d en horas",
                 "IDF tipo Sherman: I = K·T^m / (d+θ)^η, d en minutos"]
    TC_CRITERIOS = ["Media de las fórmulas en rango", "Mediana de las fórmulas en rango",
                    "Mínimo de las fórmulas en rango", "Máximo de las fórmulas en rango",
                    "Kirpich", "Témez", "California Culverts Practice", "Bransby-Williams", "Retardo SCS"]
    TC_CLAVES = ["media_validas", "mediana_validas", "minimo", "maximo",
                 "Kirpich", "Témez", "California Culverts Practice", "Bransby-Williams", "Retardo SCS"]
    Q_OPC = ["Racional modificado de Témez (con K)", "Racional clásico", "El mayor de los dos"]
    Q_CLAVES = ["temez", "racional", "mayor"]

    def tr(self, texto):
        return _tr(texto)

    def createInstance(self):
        return CuencasAlcantarillasAlgorithm()

    def name(self):
        return "cuencas_alcantarillas"

    def displayName(self):
        return self.tr("Cuencas de alcantarillas (completo)")

    def group(self):
        return self.tr("Hidrología vial")

    def groupId(self):
        return "hidrologia_vial"

    def shortHelpString(self):
        return self.tr(
            "<p>Delimita la <b>cuenca de aporte de cada alcantarilla</b> o cruce cauce–vía y calcula sus "
            "parámetros geomorfológicos, el tiempo de concentración y el caudal de diseño.</p>"
            "<ol><li>Prepara el DEM (reproyección a UTM, remuestreo, relleno de huecos) y lo acondiciona: "
            "relleno de depresiones con Priority-Flood (o breaching) y planicies resueltas con el método de "
            "Barnes (2014).</li>"
            "<li>Direcciones y acumulación D8; red de cauces por umbral de área (en hectáreas) con orden de "
            "Strahler.</li>"
            "<li>Salidas: cruces exactos de los cauces con el eje, puntos dados ajustados a la celda de mayor "
            "acumulación, o ambos sin duplicar.</li>"
            "<li>Cuenca de cada salida (sin islas, con anidamiento), recorrido más largo exacto, A, P, L, "
            "cotas, pendientes, Kc, Kf, depresiones cerradas y contacto con el borde del DEM.</li>"
            "<li>Tc por Kirpich, Témez, California Culverts Practice, Bransby-Williams y retardo SCS, con "
            "aviso de fuera de rango; caudal racional y racional modificado de Témez por periodo de retorno "
            "(Dyck-Peschke o IDF de Hydrognomon).</li>"
            "<li>Opcional: la vía como barrera (terraplén elevado salvo en las alcantarillas) para obtener la "
            "cuenca real con la vía construida.</li></ol>"
            "<p>Obligatorios: DEM y eje de la vía. Las capas de salida se cargan con simbología; además se "
            "escriben un CSV y un informe HTML. Solo usa numpy y GDAL.</p>")

    # ------------------------------------------------------------------
    def initAlgorithm(self, config=None):
        P = self.addParameter
        P(QgsProcessingParameterRasterLayer(self.DEM, self.tr("DEM (modelo digital de elevación)")))
        P(QgsProcessingParameterFeatureSource(
            self.EJE, self.tr("Eje de la vía (líneas; las partes se concatenan en orden)"), [_TIPO_LINEA]))
        P(QgsProcessingParameterFeatureSource(
            self.PUNTOS, self.tr("Alcantarillas del diseño (puntos, opcional)"), [_TIPO_PUNTO], optional=True))
        P(QgsProcessingParameterField(
            self.CAMPO_NOMBRE, self.tr("Puntos: campo con el nombre o progresiva (opcional)"),
            parentLayerParameterName=self.PUNTOS, type=_CAMPO_CUALQUIERA, optional=True))
        P(QgsProcessingParameterEnum(self.MODO_SALIDAS, self.tr("Modo de salidas"), options=self.MODOS,
                                     defaultValue=2))
        P(QgsProcessingParameterNumber(
            self.UMBRAL_HA, self.tr("Umbral de cauce (ha): área mínima drenada para que haya cauce"),
            type=_NUM_DOUBLE, defaultValue=2.0, minValue=0.001))
        P(QgsProcessingParameterString(
            self.LLUVIA, self.tr("Lluvia máxima diaria por periodo de retorno: Tr:Pd en mm, separados por «;»"),
            defaultValue="25:58.5; 35:70.6; 71:101.7"))
        P(QgsProcessingParameterEnum(self.USO, self.tr("Uso del suelo para el CN (tabla TR-55)"),
                                     options=hd.USOS_CN, defaultValue=0))
        P(QgsProcessingParameterEnum(self.AMC, self.tr("Condición de humedad antecedente"), options=self.AMCS,
                                     defaultValue=0))
        P(QgsProcessingParameterFeatureSource(
            self.SUELOS, self.tr("Suelos (opcional): calicatas (puntos) o polígonos con grupo hidrológico o CN"),
            [_TIPO_CUALQUIERA], optional=True))
        P(QgsProcessingParameterField(
            self.CAMPO_SUELO, self.tr("Suelos: campo con el grupo hidrológico (A–D) o el CN"),
            parentLayerParameterName=self.SUELOS, type=_CAMPO_CUALQUIERA, optional=True))
        P(QgsProcessingParameterEnum(
            self.GRUPO_DEFECTO, self.tr("Grupo hidrológico por defecto (si no hay capa de suelos)"),
            options=list(hd.GRUPOS), defaultValue=2))
        P(QgsProcessingParameterNumber(
            self.CN_DIRECTO, self.tr("CN directo para todas las cuencas (0 = calcular con uso y grupo)"),
            type=_NUM_DOUBLE, defaultValue=0.0, minValue=0.0, maxValue=100.0))
        P(QgsProcessingParameterBoolean(
            self.VIA_BARRERA, self.tr("La vía como barrera: terraplén elevado salvo en las alcantarillas "
                                      "(segundo escenario «con_via»)"), defaultValue=False))
        P(QgsProcessingParameterNumber(
            self.ALTURA_VIA, self.tr("Altura del terraplén para la barrera (m)"),
            type=_NUM_DOUBLE, defaultValue=3.0, minValue=0.1))

        A = lambda p: P(_avanzado(p))  # noqa: E731
        A(QgsProcessingParameterNumber(
            self.RADIO_AJUSTE, self.tr("Radio para ajustar cada punto a la celda de mayor acumulación (m)"),
            type=_NUM_DOUBLE, defaultValue=25.0, minValue=0.0))
        A(QgsProcessingParameterNumber(
            self.FUSION, self.tr("Fusionar salidas a menos de (m) en el modo «ambos»"),
            type=_NUM_DOUBLE, defaultValue=30.0, minValue=0.0))
        A(QgsProcessingParameterNumber(
            self.TOLERANCIA_CRUCE, self.tr("Agrupar puntos de corte cauce–eje a menos de (m de progresiva)"),
            type=_NUM_DOUBLE, defaultValue=40.0, minValue=0.0))
        A(QgsProcessingParameterEnum(self.DEPRESIONES, self.tr("Tratamiento de depresiones"),
                                     options=self.DEPRESIONES_OPC, defaultValue=0))
        A(QgsProcessingParameterNumber(
            self.LONG_BREACH, self.tr("Breaching: longitud máxima del canal (celdas)"),
            type=_NUM_INT, defaultValue=50, minValue=1))
        A(QgsProcessingParameterBoolean(
            self.SUAVIZAR, self.tr("Suavizar el DEM con media móvil 3×3 antes del análisis"), defaultValue=False))
        A(QgsProcessingParameterNumber(
            self.FACTOR_24H, self.tr("Factor lluvia de 24 h / lluvia diaria (Hershfield)"),
            type=_NUM_DOUBLE, defaultValue=1.13, minValue=1.0, maxValue=1.5))
        A(QgsProcessingParameterEnum(self.IDF_TIPO, self.tr("Intensidad de lluvia"), options=self.IDF_TIPOS,
                                     defaultValue=0))
        A(QgsProcessingParameterNumber(self.IDF_LAMBDA, self.tr("IDF: λ (o λ', o K)"), type=_NUM_DOUBLE,
                                       defaultValue=0.0))
        A(QgsProcessingParameterNumber(self.IDF_KAPPA, self.tr("IDF: κ' (o m)"), type=_NUM_DOUBLE,
                                       defaultValue=0.0))
        A(QgsProcessingParameterNumber(self.IDF_PSI, self.tr("IDF: ψ (o ψ')"), type=_NUM_DOUBLE,
                                       defaultValue=0.0))
        A(QgsProcessingParameterNumber(self.IDF_THETA, self.tr("IDF: θ"), type=_NUM_DOUBLE, defaultValue=0.0))
        A(QgsProcessingParameterNumber(self.IDF_ETA, self.tr("IDF: η"), type=_NUM_DOUBLE, defaultValue=0.0))
        A(QgsProcessingParameterNumber(
            self.TC_MIN, self.tr("Tiempo de concentración mínimo (min)"), type=_NUM_DOUBLE, defaultValue=10.0,
            minValue=0.0))
        A(QgsProcessingParameterEnum(self.TC_CRITERIO, self.tr("Tc adoptado"), options=self.TC_CRITERIOS,
                                     defaultValue=0))
        A(QgsProcessingParameterNumber(
            self.C_RACIONAL, self.tr("Coeficiente C del método racional clásico (0 = usar el C de Témez)"),
            type=_NUM_DOUBLE, defaultValue=0.0, minValue=0.0, maxValue=1.0))
        A(QgsProcessingParameterEnum(self.Q_ADOPTADO, self.tr("Caudal adoptado"), options=self.Q_OPC,
                                     defaultValue=0))
        A(QgsProcessingParameterNumber(
            self.DEP_AVISO, self.tr("Avisar si las depresiones cerradas superan este % del área de la cuenca"),
            type=_NUM_DOUBLE, defaultValue=5.0, minValue=0.0, maxValue=100.0))
        A(QgsProcessingParameterNumber(
            self.CELDA, self.tr("Tamaño de celda de trabajo (m; 0 = automático)"),
            type=_NUM_DOUBLE, defaultValue=0.0, minValue=0.0))
        A(QgsProcessingParameterNumber(
            self.HUECOS, self.tr("Rellenar huecos sin datos de hasta N celdas (0 = no rellenar)"),
            type=_NUM_INT, defaultValue=10, minValue=0))

        P(QgsProcessingParameterFeatureSink(self.OUT_CUENCAS, self.tr("Cuencas (polígonos con parámetros)")))
        P(QgsProcessingParameterFeatureSink(self.OUT_SALIDAS, self.tr("Salidas (puntos)")))
        P(QgsProcessingParameterFeatureSink(self.OUT_CAUCES, self.tr("Cauces (líneas con orden de Strahler)")))
        P(QgsProcessingParameterFeatureSink(self.OUT_RECORRIDOS, self.tr("Recorridos más largos (líneas)"),
                                            optional=True, createByDefault=True))
        P(QgsProcessingParameterRasterDestination(self.OUT_ACUM, self.tr("Acumulación de flujo D8 (ha)"),
                                                  optional=True, createByDefault=False))
        P(QgsProcessingParameterRasterDestination(self.OUT_DIR, self.tr("Dirección de flujo D8 (códigos ESRI)"),
                                                  optional=True, createByDefault=False))
        P(QgsProcessingParameterRasterDestination(self.OUT_CUENCAS_R, self.tr("Cuencas etiquetadas (ráster)"),
                                                  optional=True, createByDefault=False))
        P(QgsProcessingParameterRasterDestination(self.OUT_MFD, self.tr("Acumulación MFD (solo visualización, ha)"),
                                                  optional=True, createByDefault=False))
        P(QgsProcessingParameterFileDestination(self.OUT_CSV, self.tr("Tabla de cuencas (CSV)"),
                                                fileFilter="CSV (*.csv)", optional=True, createByDefault=True))
        P(QgsProcessingParameterFileDestination(self.OUT_INFORME, self.tr("Informe de cálculo"),
                                                fileFilter="HTML (*.html)"))
        self.addOutput(QgsProcessingOutputNumber(self.RES_N, self.tr("Salidas analizadas")))
        self.addOutput(QgsProcessingOutputNumber(self.RES_QMAX, self.tr("Caudal máximo (m³/s)")))
        self.addOutput(QgsProcessingOutputString(self.RES_RESUMEN, self.tr("Resumen")))

    # ------------------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):
        pa = parameters
        capa_dem = self.parameterAsRasterLayer(pa, self.DEM, context)
        if capa_dem is None:
            raise QgsProcessingException(self.tr("No se pudo cargar el DEM."))
        crs_capa = capa_dem.crs()

        def info(t):
            feedback.pushInfo(t)

        def aviso(t):
            feedback.pushWarning(t)

        def cancelado():
            return feedback.isCanceled()

        def progreso(a, b):
            return lambda f: feedback.setProgress(100.0 * (a + (b - a) * f))

        # --- DEM -------------------------------------------------------------
        info(self.tr("Leyendo y preparando el DEM…"))
        try:
            dem, validos, gt, wkt, notas = _preparar_dem(
                capa_dem.source(), self.parameterAsDouble(pa, self.CELDA, context),
                self.parameterAsInt(pa, self.HUECOS, context), feedback=feedback)
        except QgsProcessingException:
            raise
        except Exception as err:
            raise QgsProcessingException(self.tr("Error al preparar el DEM: %s") % err)
        crs = QgsCoordinateReferenceSystem()
        if wkt:
            crs.createFromWkt(wkt)
        if not crs.isValid():
            crs = crs_capa
        if crs.isValid() and crs.isGeographic():
            raise QgsProcessingException(self.tr(
                "El DEM sigue en coordenadas geográficas tras la preparación. Reproyéctalo a UTM."))
        if not crs.isValid():
            aviso(self.tr("El DEM no tiene sistema de coordenadas: se asume que las unidades son metros."))
        filas, cols = dem.shape
        celda = abs(gt[1])
        area_celda = abs(gt[1] * gt[5])
        n_celdas = filas * cols
        info(self.tr("DEM de trabajo: %d filas × %d columnas, celda de %.2f m (%s).")
             % (filas, cols, celda, crs.authid() or crs.description()))
        if n_celdas > 25_000_000:
            raise QgsProcessingException(self.tr(
                "El DEM tiene %.1f millones de celdas. Indica un tamaño de celda de trabajo mayor o recórtalo.")
                % (n_celdas / 1e6))
        if not validos.any():
            raise QgsProcessingException(self.tr("El DEM no tiene celdas con datos válidos."))
        if abs(abs(gt[1]) - abs(gt[5])) > 1e-6 * celda:
            aviso(self.tr("Las celdas no son cuadradas (%.3f × %.3f m); las distancias usan %.3f m.")
                  % (abs(gt[1]), abs(gt[5]), celda))
        entero = bool(np.all(np.abs(dem[validos] - np.round(dem[validos])) < 1e-9))
        if entero:
            info(self.tr("El DEM tiene cotas enteras (resolución vertical de 1 m): las planicies se resuelven "
                         "con el método de Barnes; las pendientes de celda son escalonadas."))
        if self.parameterAsBool(pa, self.SUAVIZAR, context):
            dem = ac.suavizar_3x3(dem, validos)
            notas.append(self.tr("suavizado 3×3"))
            info(self.tr("DEM suavizado con media móvil 3×3."))

        # --- Eje -------------------------------------------------------------
        fuente_eje = self.parameterAsSource(pa, self.EJE, context)
        if fuente_eje is None:
            raise QgsProcessingException(self.tr("Falta el eje de la vía."))
        polilineas = _polilineas_de_fuente(fuente_eje, crs, context)
        if not polilineas:
            raise QgsProcessingException(self.tr("La capa del eje no tiene líneas válidas."))
        bases, longs = h.longitudes_partes(polilineas)
        long_eje = sum(longs)
        info(self.tr("Eje: %d parte(s), %.1f m en total; la progresiva 0+000 es el primer vértice de la "
                     "primera parte.") % (len(polilineas), long_eje))
        mascara_eje = h.mascara_polilineas(polilineas, gt, dem.shape)
        if not mascara_eje.any():
            raise QgsProcessingException(self.tr("El eje de la vía cae fuera del DEM."))
        partes_eje = [np.asarray(p, dtype=float) for p in polilineas]

        # --- Parámetros ------------------------------------------------------
        umbral_ha = self.parameterAsDouble(pa, self.UMBRAL_HA, context)
        umbral_celdas = max(int(round(umbral_ha * 1e4 / area_celda)), 1)
        info(self.tr("Umbral de cauce: %.3f ha = %d celdas de %.2f m.") % (umbral_ha, umbral_celdas, celda))
        modo = self.parameterAsEnum(pa, self.MODO_SALIDAS, context)
        radio = self.parameterAsDouble(pa, self.RADIO_AJUSTE, context)
        fusion = self.parameterAsDouble(pa, self.FUSION, context)
        tol_cruce = self.parameterAsDouble(pa, self.TOLERANCIA_CRUCE, context)
        metodo_dep = "breaching" if self.parameterAsEnum(pa, self.DEPRESIONES, context) == 1 else "relleno"
        long_breach = self.parameterAsInt(pa, self.LONG_BREACH, context)
        barrera = self.parameterAsBool(pa, self.VIA_BARRERA, context)
        altura = self.parameterAsDouble(pa, self.ALTURA_VIA, context)
        tc_min = self.parameterAsDouble(pa, self.TC_MIN, context)
        tc_criterio = self.TC_CLAVES[self.parameterAsEnum(pa, self.TC_CRITERIO, context)]
        q_adoptar = self.Q_CLAVES[self.parameterAsEnum(pa, self.Q_ADOPTADO, context)]
        c_fijo = self.parameterAsDouble(pa, self.C_RACIONAL, context) or None
        dep_aviso = self.parameterAsDouble(pa, self.DEP_AVISO, context)
        factor_24 = self.parameterAsDouble(pa, self.FACTOR_24H, context)
        amc = "III" if self.parameterAsEnum(pa, self.AMC, context) == 1 else "II"
        uso = self.parameterAsEnum(pa, self.USO, context)
        grupo_def = hd.GRUPOS[self.parameterAsEnum(pa, self.GRUPO_DEFECTO, context)]
        cn_directo = self.parameterAsDouble(pa, self.CN_DIRECTO, context)
        try:
            lluvias = hd.leer_tabla_lluvia(self.parameterAsString(pa, self.LLUVIA, context) or "")
        except ValueError as err:
            raise QgsProcessingException(self.tr("Tabla de lluvia no válida: %s") % err)
        idf = None
        idf_tipo = self.parameterAsEnum(pa, self.IDF_TIPO, context)
        if idf_tipo > 0:
            idf = {"tipo": ("gumbel", "gev", "sherman")[idf_tipo - 1],
                   "lam": self.parameterAsDouble(pa, self.IDF_LAMBDA, context),
                   "kappa": self.parameterAsDouble(pa, self.IDF_KAPPA, context),
                   "psi": self.parameterAsDouble(pa, self.IDF_PSI, context),
                   "theta": self.parameterAsDouble(pa, self.IDF_THETA, context),
                   "eta": self.parameterAsDouble(pa, self.IDF_ETA, context)}
            if idf["lam"] <= 0 or idf["eta"] <= 0:
                raise QgsProcessingException(self.tr("Los parámetros de la IDF (λ y η) deben ser mayores que 0."))

        # --- Suelos ------------------------------------------------------------
        suelos = None
        fuente_suelos = self.parameterAsSource(pa, self.SUELOS, context)
        if fuente_suelos is not None:
            campo = self.parameterAsString(pa, self.CAMPO_SUELO, context) or ""
            if not campo:
                aviso(self.tr("Capa de suelos sin campo de grupo/CN: se ignora."))
            else:
                suelos = self._leer_suelos(fuente_suelos, campo, crs, context, gt, dem.shape, wkt, feedback)

        # --- Puntos dados ------------------------------------------------------
        puntos = []
        fuente_pts = self.parameterAsSource(pa, self.PUNTOS, context)
        if fuente_pts is not None:
            campo_nombre = self.parameterAsString(pa, self.CAMPO_NOMBRE, context) or None
            puntos = _puntos_de_fuente(fuente_pts, crs, context, campo_nombre)
            info(self.tr("Puntos de alcantarillas: %d.") % len(puntos))
        if modo == 1 and not puntos:
            raise QgsProcessingException(self.tr("El modo «solo los puntos dados» necesita la capa de puntos."))
        if modo == 2 and not puntos:
            info(self.tr("No hay puntos: se usan solo los cruces automáticos."))

        # --- Acondicionamiento natural ------------------------------------------
        info(self.tr("Acondicionando el DEM (%s)…") % ("breaching + relleno" if metodo_dep == "breaching"
                                                        else "relleno Priority-Flood"))
        try:
            cond = ac.acondicionar(dem, validos, metodo_dep, long_breach, progreso=progreso(0.0, 0.25),
                                   cancelado=cancelado)
        except RuntimeError as err:
            raise QgsProcessingException(str(err))
        self._informar_acondicionamiento(cond, area_celda, feedback)
        R, C = cond["forma"]
        valido_p = np.isfinite(cond["zp"]).ravel()
        try:
            cond["oleadas"] = red.oleadas(cond["recv"], valido_p)
        except RuntimeError as err:
            raise QgsProcessingException(str(err))
        acc = red.acumulacion(cond["recv"], cond["oleadas"], R * C)
        cond["acc"] = acc
        feedback.setProgress(30)

        # --- Salidas ---------------------------------------------------------------
        mascara_eje_p = np.zeros((R, C), dtype=bool)
        mascara_eje_p[1:-1, 1:-1] = mascara_eje
        dil = mascara_eje_p.copy()
        for dr, dc in ac.VECINOS:
            dil[1:-1, 1:-1] |= mascara_eje_p[1 + dr:R - 1 + dr, 1 + dc:C - 1 + dc]
        segmentos, _ = red.red_cauces(cond["recv"], acc, valido_p, umbral_celdas)
        info(self.tr("Red de cauces: %d segmentos.") % len(segmentos))
        salidas = []
        if modo in (0, 2):
            cruces = red.cruces_con_eje(segmentos, acc, C, gt, partes_eje, dil.ravel(), tol_cruce)
            for cr in cruces:
                salidas.append({"id": len(salidas) + 1, "celda": cr["celda"], "x": cr["x"], "y": cr["y"],
                                "x_orig": cr["x"], "y_orig": cr["y"], "progresiva": cr["progresiva"],
                                "origen": "cruce", "desplazamiento": 0.0, "acc": cr["acc"],
                                "n_puntos": cr["n_puntos"], "nombre": ""})
            info(self.tr("Cruces automáticos cauce–eje: %d.") % len(cruces))
        if modo in (1, 2):
            fuera = 0
            for p in puntos:
                aj = red.ajustar_punto(p["x"], p["y"], acc, valido_p, C, R, gt, radio)
                if aj is None:
                    fuera += 1
                    continue
                celda_s, xa, ya, despl = aj
                prog, dist_eje = h.progresiva_de_punto(xa, ya, polilineas)
                if dist_eje > max(100.0, 4 * celda):
                    aviso(self.tr("El punto %s está a %.0f m del eje; su progresiva es la del punto más cercano "
                                  "del eje.") % (p["nombre"] or p["fid"], dist_eje))
                salidas.append({"id": len(salidas) + 1, "celda": celda_s, "x": xa, "y": ya,
                                "x_orig": p["x"], "y_orig": p["y"], "progresiva": prog, "origen": "punto",
                                "desplazamiento": despl, "acc": float(acc[celda_s]), "n_puntos": 0,
                                "nombre": p["nombre"]})
            if fuera:
                aviso(self.tr("%d punto(s) caen fuera del DEM y se ignoran.") % fuera)
        descartadas = []
        if modo == 2 and puntos:
            salidas, descartadas = red.fusionar_salidas(salidas, fusion)
            for s in salidas:
                if s["origen"] == "punto" and s.get("fusiona"):
                    s["origen"] = "punto+cruce"
            if descartadas:
                info(self.tr("%d salida(s) fusionadas por estar a menos de %.0f m de otra.")
                     % (len(descartadas), fusion))
        salidas.sort(key=lambda s: (s["progresiva"] if s["progresiva"] is not None else 1e18))
        for k, s in enumerate(salidas, start=1):
            s["id"] = k
        if not salidas:
            raise QgsProcessingException(self.tr(
                "No se encontró ninguna salida: ningún cauce cruza el eje con el umbral de %.2f ha. Baja el umbral "
                "o indica las alcantarillas como puntos.") % umbral_ha)
        info(self.tr("Salidas a analizar: %d.") % len(salidas))
        # red de cauces definitiva, partida en las salidas
        segmentos, cauce_m = red.red_cauces(cond["recv"], acc, valido_p, umbral_celdas,
                                            cortar_en=[s["celda"] for s in salidas])
        feedback.setProgress(35)

        # --- Escenarios ----------------------------------------------------------
        escenarios = []
        info(self.tr("Delimitando cuencas naturales…"))
        try:
            res_nat = red.analizar_cuencas(cond, salidas, celda, gt, progreso=progreso(0.35, 0.55),
                                           cancelado=cancelado)
        except RuntimeError as err:
            raise QgsProcessingException(str(err))
        escenarios.append(("natural", cond, res_nat, salidas))
        cond_via = None
        if barrera:
            info(self.tr("Escenario con la vía como barrera: terraplén de %.1f m salvo en las salidas…") % altura)
            dem_via = dem.copy()
            m_via = mascara_eje & validos
            dem_via[m_via] = dem_via[m_via] + altura
            # abrir el terraplén en cada salida a lo largo del cauce natural
            via_flat = mascara_eje_p.ravel()
            abiertas = set()
            for s in salidas:
                abiertas |= red.celdas_abrir_via(cond["recv"], acc, via_flat, s["celda"], C)
            for cel in abiertas:
                f0, c0 = cel // C - 1, cel % C - 1
                dem_via[f0, c0] = dem[f0, c0]
            info(self.tr("Terraplén abierto en %d celdas (salidas y su cauce natural).") % len(abiertas))
            try:
                cond_via = ac.acondicionar(dem_via, validos, metodo_dep, long_breach,
                                           progreso=progreso(0.55, 0.7), cancelado=cancelado)
                cond_via["oleadas"] = red.oleadas(cond_via["recv"], valido_p)
                cond_via["acc"] = red.acumulacion(cond_via["recv"], cond_via["oleadas"], R * C)
            except RuntimeError as err:
                raise QgsProcessingException(str(err))
            # con la vía construida el flujo cambia de celda en las planicies: cada
            # salida se vuelve a ajustar a la celda de mayor acumulación en el radio
            salidas_via = []
            for s in salidas:
                sv = dict(s)
                aj = red.ajustar_punto(s["x"], s["y"], cond_via["acc"], valido_p, C, R, gt, max(radio, celda))
                if aj is not None:
                    sv["celda"], sv["x"], sv["y"], sv["desplazamiento"] = aj
                    sv["acc"] = float(cond_via["acc"][aj[0]])
                salidas_via.append(sv)
            try:
                res_via = red.analizar_cuencas(cond_via, salidas_via, celda, gt, progreso=progreso(0.7, 0.8),
                                               cancelado=cancelado)
            except RuntimeError as err:
                raise QgsProcessingException(str(err))
            escenarios.append(("con_via", cond_via, res_via, salidas_via))
        feedback.setProgress(80)

        # --- Hidrología por cuenca ------------------------------------------------
        avisos = []
        filas_csv = []
        cuencas_informe = []
        tabla_cuencas = []
        for esc_nombre, cnd, res, sals in escenarios:
            for cu in res["cuencas"]:
                s = sals[cu["id"] - 1]
                par = cu["parametros"]
                cn, cn_detalle = self._cn_cuenca(cu["mascara_total"], suelos, uso, amc, grupo_def, cn_directo,
                                                 C, gt)
                tcs = hd.tiempos_concentracion(par["l_m"], par["dh"], par["area_km2"],
                                               par["s_l"] if par["s_l"] > 0 else 1e-4,
                                               par["s_cuenca"] if par["s_cuenca"] > 0 else 1e-4, cn, tc_min)
                tc_ad, tc_crit = hd.tc_adoptado(tcs, tc_criterio, tc_min)
                qs = hd.caudales(par["area_km2"], tc_ad, cn, lluvias, factor_24, idf, c_fijo, q_adoptar)
                fila = dict(par)
                fila.update({"id": cu["id"], "escenario": esc_nombre, "progresiva": s["progresiva"],
                             "origen": s["origen"], "desplazamiento": s["desplazamiento"], "nombre": s["nombre"],
                             "cn": cn, "cn_detalle": cn_detalle, "tc": tcs, "tc_adoptado_min": tc_ad,
                             "tc_criterio": tc_crit, "q": qs})
                tabla_cuencas.append(fila)
                if esc_nombre == "natural":
                    cuencas_informe.append(fila)
                    if par["toca_borde"]:
                        avisos.append({"texto": self.tr(
                            "Salida %d (%s): la cuenca toca el borde del DEM; el área puede estar incompleta. "
                            "Usa un DEM con más margen.") % (cu["id"], h.progresiva_km(s["progresiva"])),
                            "grave": True})
                    if 100.0 * par["frac_depresiones"] > dep_aviso:
                        avisos.append({"texto": self.tr(
                            "Salida %d (%s): %.1f %% del área está en depresiones cerradas (%d, %.0f m³). El "
                            "método racional no considera ese almacenamiento: el caudal es un límite superior.")
                            % (cu["id"], h.progresiva_km(s["progresiva"]), 100.0 * par["frac_depresiones"],
                               par["n_depresiones"], par["vol_depresiones"])})
                    fuera = [n for n, r in tcs.items() if r["fuera_rango"]]
                    if len(fuera) == len(tcs):
                        avisos.append({"texto": self.tr(
                            "Salida %d (%s): ninguna fórmula de Tc está en su rango de calibración; el Tc "
                            "adoptado es %s.") % (cu["id"], h.progresiva_km(s["progresiva"]), tc_crit)})
        if barrera:
            lab_via = escenarios[1][2]["etiquetas"]
            for cu in res_nat["cuencas"]:
                k = cu["id"]
                a_nat = cu["parametros"]["area_ha"]
                a_via = next(c for c in escenarios[1][2]["cuencas"] if c["id"] == k)["parametros"]["area_ha"]
                if a_nat > 0 and a_via < 0.5 * a_nat:
                    cuenta = np.bincount(lab_via[cu["mascara_total"]], minlength=len(salidas) + 1)
                    cuenta[k] = 0
                    j = int(np.argmax(cuenta))
                    if j > 0 and cuenta[j] > 0:
                        destino = (" el agua represada vierte sobre todo por la salida %d (%s)."
                                   % (j, h.progresiva_km(salidas[j - 1]["progresiva"])))
                    else:
                        destino = " el agua represada rodea el extremo de la vía o sale del DEM sin pasar por una salida."
                    avisos.append({"texto": self.tr(
                        "Salida %d (%s): con la vía como barrera la cuenca baja de %.2f ha a %.2f ha;%s")
                        % (k, h.progresiva_km(salidas[k - 1]["progresiva"]), a_nat, a_via, destino)})
        for a in avisos:
            (aviso if a.get("grave") else info)(a["texto"])
        feedback.setProgress(85)

        resultados = {}
        # --- Capa de cuencas -----------------------------------------------------
        info(self.tr("Creando polígonos de cuencas…"))
        campos = QgsFields()
        base_campos = [("id", _T_INT), ("escenario", _T_STR), ("nombre", _T_STR), ("progresiva", _T_STR),
                       ("prog_m", _T_DOUBLE), ("origen", _T_STR), ("area_ha", _T_DOUBLE), ("area_km2", _T_DOUBLE),
                       ("perim_km", _T_DOUBLE), ("l_m", _T_DOUBLE), ("h_max", _T_DOUBLE), ("h_min", _T_DOUBLE),
                       ("h_min_z", _T_DOUBLE), ("dh", _T_DOUBLE), ("s_l", _T_DOUBLE), ("s_1085", _T_DOUBLE), ("s_cuenca", _T_DOUBLE),
                       ("h_media", _T_DOUBLE), ("kc", _T_DOUBLE), ("kf", _T_DOUBLE), ("n_dep", _T_INT),
                       ("vol_dep", _T_DOUBLE), ("frac_dep", _T_DOUBLE), ("borde", _T_STR), ("anidada", _T_INT),
                       ("contiene", _T_STR), ("a_propia", _T_DOUBLE), ("cn", _T_DOUBLE), ("cn_detalle", _T_STR),
                       ("tc_kirp", _T_DOUBLE), ("tc_temez", _T_DOUBLE), ("tc_calif", _T_DOUBLE),
                       ("tc_bw", _T_DOUBLE), ("tc_scs", _T_DOUBLE), ("tc_fuera", _T_STR), ("tc_adopt", _T_DOUBLE),
                       ("tc_crit", _T_STR), ("k_temez", _T_DOUBLE)]
        for tr, _ in lluvias:
            t = _tr_txt(tr)
            base_campos += [("pd_" + t, _T_DOUBLE), ("i_" + t, _T_DOUBLE), ("c_" + t, _T_DOUBLE),
                            ("qr_" + t, _T_DOUBLE), ("qt_" + t, _T_DOUBLE), ("q_" + t, _T_DOUBLE)]
        for nombre, tipo in base_campos:
            campos.append(QgsField(nombre, tipo))
        sink, dest = self.parameterAsSink(pa, self.OUT_CUENCAS, context, campos, _WKB_POLIGONO, crs)
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(pa, self.OUT_CUENCAS))
        n_descartadas = 0
        for esc_nombre, cnd, res, sals in escenarios:
            for cu in res["cuencas"]:
                if cancelado():
                    break
                fila = next(f for f in tabla_cuencas if f["id"] == cu["id"] and f["escenario"] == esc_nombre)
                s = sals[cu["id"] - 1]
                m2 = cu["mascara_total"].reshape(R, C)[1:-1, 1:-1]
                g, desc = _poligono_mascara(m2, gt, wkt, s["x"], s["y"])
                n_descartadas += desc
                if g is None:
                    continue
                f = QgsFeature(campos)
                f.setGeometry(g)
                tcs = fila["tc"]
                valores = [fila["id"], esc_nombre, fila["nombre"] or None, h.progresiva_km(fila["progresiva"]),
                           _num(fila["progresiva"]), fila["origen"], _num(fila["area_ha"]), _num(fila["area_km2"]),
                           _num(fila["perimetro_km"]), _num(fila["l_m"]), _num(fila["h_max"]), _num(fila["h_min"]),
                           _num(fila["h_min_zonal"]), _num(fila["dh"]), _num(fila["s_l"]), _num(fila["s_1085"]), _num(fila["s_cuenca"]),
                           _num(fila["h_media"]), _num(fila["kc"]), _num(fila["kf"]), fila["n_depresiones"],
                           _num(fila["vol_depresiones"]), _num(fila["frac_depresiones"]), _si_no(fila["toca_borde"]),
                           fila["anidada_en"] or None, ", ".join(str(i) for i in fila["contiene"]) or None,
                           _num(fila["area_propia_ha"]), _num(fila["cn"]), fila["cn_detalle"],
                           _num(tcs["Kirpich"]["tc_min"]), _num(tcs["Témez"]["tc_min"]),
                           _num(tcs["California Culverts Practice"]["tc_min"]),
                           _num(tcs["Bransby-Williams"]["tc_min"]), _num(tcs["Retardo SCS"]["tc_min"]),
                           "; ".join("%s: %s" % (n, r["fuera_rango"]) for n, r in tcs.items() if r["fuera_rango"])
                           or None, _num(fila["tc_adoptado_min"]), fila["tc_criterio"],
                           _num(hd.k_temez(fila["tc_adoptado_min"] / 60.0))]
                for tr, _ in lluvias:
                    q = fila["q"][tr]
                    valores += [_num(q["pd"]), _num(q["i"]), _num(q["c"]), _num(q["q_racional"]),
                                _num(q["q_temez"]), _num(q["q_adoptado"])]
                f.setAttributes(valores)
                sink.addFeature(f)
                fila_csv = {c.name(): v for c, v in zip(campos, valores)}
                fila_csv["x_salida"] = s["x"]
                fila_csv["y_salida"] = s["y"]
                filas_csv.append(fila_csv)
        if n_descartadas:
            aviso(self.tr("Se descartaron %d parte(s) de polígono no conectadas con su salida.") % n_descartadas)
        self._cerrar(sink)
        resultados[self.OUT_CUENCAS] = dest
        _programar_estilo(context, dest, _estilo_cuencas, self.tr("Cuencas de alcantarillas"))

        # --- Salidas ---------------------------------------------------------------
        campos_s = QgsFields()
        for nombre, tipo in [("id", _T_INT), ("nombre", _T_STR), ("progresiva", _T_STR), ("prog_m", _T_DOUBLE),
                             ("origen", _T_STR), ("despl_m", _T_DOUBLE), ("x_orig", _T_DOUBLE),
                             ("y_orig", _T_DOUBLE), ("acc_ha", _T_DOUBLE), ("cota", _T_DOUBLE),
                             ("n_cortes", _T_INT), ("fusiona", _T_STR), ("area_ha", _T_DOUBLE),
                             ("q_max", _T_DOUBLE)]:
            campos_s.append(QgsField(nombre, tipo))
        sink_s, dest_s = self.parameterAsSink(pa, self.OUT_SALIDAS, context, campos_s, _WKB_PUNTO, crs)
        if sink_s is not None:
            for s in salidas:
                fila = next(f for f in tabla_cuencas if f["id"] == s["id"] and f["escenario"] == "natural")
                f = QgsFeature(campos_s)
                f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(s["x"], s["y"])))
                tr_max = lluvias[-1][0]
                f.setAttributes([s["id"], s["nombre"] or None, h.progresiva_km(s["progresiva"]),
                                 _num(s["progresiva"]), s["origen"], _num(s["desplazamiento"]), _num(s["x_orig"]),
                                 _num(s["y_orig"]), _num(s["acc"] * area_celda / 1e4),
                                 _num(float(cond["original"].ravel()[s["celda"]])), int(s.get("n_puntos", 0)),
                                 ", ".join(str(i) for i in s.get("fusiona", [])) or None, _num(fila["area_ha"]),
                                 _num(fila["q"][tr_max]["q_adoptado"])])
                sink_s.addFeature(f)
            self._cerrar(sink_s)
            resultados[self.OUT_SALIDAS] = dest_s
            _programar_estilo(context, dest_s, _estilo_salidas, self.tr("Salidas (exutorios)"))

        # --- Cauces ----------------------------------------------------------------
        campos_c = QgsFields()
        for nombre, tipo in [("id", _T_INT), ("orden", _T_INT), ("acc_ha", _T_DOUBLE), ("long_m", _T_DOUBLE),
                             ("ag_abajo", _T_INT)]:
            campos_c.append(QgsField(nombre, tipo))
        sink_c, dest_c = self.parameterAsSink(pa, self.OUT_CAUCES, context, campos_c, _WKB_LINEA, crs)
        if sink_c is not None:
            paso = red.paso_celda(cond["recv"], C, celda)
            for seg in segmentos:
                cel = seg["celdas"]
                if cel.size < 2:
                    continue
                xs, ys = h.xy_de_indices(cel // C - 1, cel % C - 1, gt)
                f = QgsFeature(campos_c)
                f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(float(x), float(y)) for x, y in zip(xs, ys)]))
                f.setAttributes([seg["id"], seg["orden"], _num(seg["acc_fin"] * area_celda / 1e4),
                                 _num(float(paso[cel[:-1]].sum())), seg["aguas_abajo"] or None])
                sink_c.addFeature(f)
            self._cerrar(sink_c)
            resultados[self.OUT_CAUCES] = dest_c
            _programar_estilo(context, dest_c, _estilo_cauces, self.tr("Cauces (Strahler)"))

        # --- Recorridos ------------------------------------------------------------
        if pa.get(self.OUT_RECORRIDOS) is not None:
            campos_r = QgsFields()
            for nombre, tipo in [("id", _T_INT), ("escenario", _T_STR), ("l_m", _T_DOUBLE), ("h_ini", _T_DOUBLE),
                                 ("h_fin", _T_DOUBLE), ("s_l", _T_DOUBLE), ("s_1085", _T_DOUBLE)]:
                campos_r.append(QgsField(nombre, tipo))
            sink_r, dest_r = self.parameterAsSink(pa, self.OUT_RECORRIDOS, context, campos_r, _WKB_LINEA, crs)
            if sink_r is not None:
                for esc_nombre, cnd, res, sals in escenarios:
                    for cu in res["cuencas"]:
                        cel = cu["camino"]
                        if cel.size < 2:
                            continue
                        par = cu["parametros"]
                        xs, ys = h.xy_de_indices(cel // C - 1, cel % C - 1, gt)
                        f = QgsFeature(campos_r)
                        f.setGeometry(QgsGeometry.fromPolylineXY(
                            [QgsPointXY(float(x), float(y)) for x, y in zip(xs, ys)]))
                        f.setAttributes([cu["id"], esc_nombre, _num(par["l_m"]), _num(par["h_max"]),
                                         _num(par["h_min"]), _num(par["s_l"]), _num(par["s_1085"])])
                        sink_r.addFeature(f)
                self._cerrar(sink_r)
                resultados[self.OUT_RECORRIDOS] = dest_r
                _programar_estilo(context, dest_r, _estilo_recorridos, self.tr("Recorridos más largos"))
        feedback.setProgress(90)

        # --- Rásters opcionales --------------------------------------------------------
        def recortar(a):
            return a.reshape(R, C)[1:-1, 1:-1]

        if pa.get(self.OUT_ACUM) is not None:
            ruta = self.parameterAsOutputLayer(pa, self.OUT_ACUM, context)
            if ruta:
                arr = np.where(validos, recortar(acc) * area_celda / 1e4, np.nan)
                _escribir_raster(ruta, arr, gt, wkt)
                resultados[self.OUT_ACUM] = ruta
                _programar_estilo(context, ruta, _estilo_acumulacion, self.tr("Acumulación D8 (ha)"))
        if pa.get(self.OUT_DIR) is not None:
            ruta = self.parameterAsOutputLayer(pa, self.OUT_DIR, context)
            if ruta:
                _escribir_raster(ruta, recortar(self._codigos_d8(cond["recv"], C)), gt, wkt, entero=True)
                resultados[self.OUT_DIR] = ruta
                _programar_estilo(context, ruta, _estilo_paleta, self.tr("Dirección D8"))
        if pa.get(self.OUT_CUENCAS_R) is not None:
            ruta = self.parameterAsOutputLayer(pa, self.OUT_CUENCAS_R, context)
            if ruta:
                _escribir_raster(ruta, recortar(res_nat["etiquetas"]), gt, wkt, entero=True)
                resultados[self.OUT_CUENCAS_R] = ruta
                _programar_estilo(context, ruta, _estilo_paleta, self.tr("Cuencas (id de la salida más cercana)"))
        if pa.get(self.OUT_MFD) is not None:
            ruta = self.parameterAsOutputLayer(pa, self.OUT_MFD, context)
            if ruta:
                info(self.tr("Calculando acumulación MFD (Freeman 1991) para visualización…"))
                mfd = red.acumulacion_mfd(cond["zp"], cond["recv"], valido_p, cond["oleadas"])
                _escribir_raster(ruta, np.where(validos, recortar(mfd) * area_celda / 1e4, np.nan), gt, wkt)
                resultados[self.OUT_MFD] = ruta
                _programar_estilo(context, ruta, _estilo_acumulacion, self.tr("Acumulación MFD (ha)"))

        # --- CSV e informe -----------------------------------------------------------
        ruta_csv = self.parameterAsFileOutput(pa, self.OUT_CSV, context)
        if ruta_csv and filas_csv:
            columnas = [c.name() for c in campos] + ["x_salida", "y_salida"]
            h.escribir_csv(ruta_csv, columnas, filas_csv)
            resultados[self.OUT_CSV] = ruta_csv

        datos = self._datos_informe(capa_dem.name(), notas, filas, cols, celda, crs, fuente_eje.sourceName(),
                                    long_eje, len(polilineas), puntos, modo, umbral_ha, umbral_celdas, metodo_dep,
                                    barrera, altura, radio, fusion, tol_cruce, lluvias, factor_24, idf, uso, amc,
                                    grupo_def, cn_directo, suelos, tc_min, tc_criterio, q_adoptar, c_fijo,
                                    tabla_cuencas, cuencas_informe, avisos, cond, entero, segmentos, dep_aviso)
        ruta_html = self.parameterAsFileOutput(pa, self.OUT_INFORME, context)
        h.informe_html(ruta_html, datos)
        resultados[self.OUT_INFORME] = ruta_html

        # --- Resultados numéricos ------------------------------------------------------
        tr_max = lluvias[-1][0]
        qmax = max(f["q"][tr_max]["q_adoptado"] for f in cuencas_informe) if cuencas_informe else 0.0
        texto = self.tr("RESULTADO: %d salidas; cuenca mayor %.3f km²; caudal máximo %.2f m³/s (Tr %g años).") % (
            len(salidas), max(f["area_km2"] for f in cuencas_informe) if cuencas_informe else 0.0, qmax, tr_max)
        info(texto)
        resultados[self.RES_N] = len(salidas)
        resultados[self.RES_QMAX] = qmax
        resultados[self.RES_RESUMEN] = texto
        info(self.tr("Informe: %s") % ruta_html)
        feedback.setProgress(100)
        return resultados

    # ------------------------------------------------------------------
    @staticmethod
    def _cerrar(sink):
        try:
            sink.finalize()
        except AttributeError:
            pass

    @staticmethod
    def _codigos_d8(recv, C):
        """Códigos ESRI: E=1, SE=2, S=4, SW=8, W=16, NW=32, N=64, NE=128; 0 = salida."""
        idx = np.arange(recv.size, dtype=np.int64)
        d = recv - idx
        tabla = {1: 1, C + 1: 2, C: 4, C - 1: 8, -1: 16, -C - 1: 32, -C: 64, -C + 1: 128}
        out = np.zeros(recv.size, dtype=np.int32)
        for off, code in tabla.items():
            out[(d == off) & (recv >= 0)] = code
        out[recv < 0] = 0
        return out

    def _informar_acondicionamiento(self, cond, area_celda, feedback):
        n_dep = int(cond["depresion"].sum())
        vol = float(cond["relleno"].sum() * area_celda)
        feedback.pushInfo(self.tr("Depresiones rellenadas: %d celdas (%.1f ha), %.0f m³ de relleno.")
                          % (n_dep, n_dep * area_celda / 1e4, vol))
        if cond.get("breaching"):
            ab, nab = cond["breaching"]
            feedback.pushInfo(self.tr("Breaching: %d depresiones abiertas, %d rellenadas por no poder abrirse.")
                              % (ab, nab))
        if cond["n_sin_salida"]:
            feedback.pushWarning(self.tr("¡%d celdas quedaron sin salida tras el acondicionamiento! Revisa los "
                                         "huecos sin datos del DEM.") % cond["n_sin_salida"])
        else:
            feedback.pushInfo(self.tr("Verificación: ninguna celda válida quedó sin salida."))

    def _leer_suelos(self, fuente, campo, crs, context, gt, forma, wkt, feedback):
        """Devuelve dict: tipo «puntos» (lista de (x, y, valor)) o «raster»
        (array de códigos + lista de valores)."""
        tipo_geom = None
        try:
            tipo_geom = QgsWkbTypes.geometryType(fuente.wkbType())
        except Exception:
            pass
        campos = fuente.fields()
        if campos.indexOf(campo) < 0:
            feedback.pushWarning(self.tr("La capa de suelos no tiene el campo «%s»; se ignora.") % campo)
            return None
        transf = QgsCoordinateTransform(fuente.sourceCrs(), crs, context.transformContext())
        es_puntos = tipo_geom == QgsWkbTypes.PointGeometry if tipo_geom is not None else None
        puntos = []
        poligonos = []
        valores = []
        for f in fuente.getFeatures():
            g = QgsGeometry(f.geometry())
            if g.isNull() or g.isEmpty():
                continue
            if transf.isValid() and fuente.sourceCrs().isValid() and crs.isValid():
                g.transform(transf)
            v = _interpretar_suelo(f[campo])
            if v is None:
                feedback.pushWarning(self.tr("Suelos: valor «%s» no reconocido (se espera A–D o un CN); se omite.")
                                     % f[campo])
                continue
            if es_puntos or (es_puntos is None and g.type() == 0):
                p = g.asPoint() if not g.isMultipart() else g.asGeometryCollection()[0].asPoint()
                puntos.append((p.x(), p.y(), v))
            else:
                valores.append(v)
                poligonos.append((len(valores), g.asWkt()))
        if puntos:
            feedback.pushInfo(self.tr("Suelos: %d calicatas; se asignan por Thiessen (vecino más cercano) y se "
                                      "ponderan por área.") % len(puntos))
            return {"tipo": "puntos", "puntos": puntos}
        if poligonos:
            codigos = _rasterizar_poligonos(poligonos, gt, forma, wkt)
            feedback.pushInfo(self.tr("Suelos: %d polígonos rasterizados.") % len(poligonos))
            return {"tipo": "raster", "codigos": codigos, "valores": valores}
        feedback.pushWarning(self.tr("La capa de suelos no tiene elementos válidos; se ignora."))
        return None

    def _cn_cuenca(self, mascara_total, suelos, uso, amc, grupo_def, cn_directo, C, gt):
        """CN compuesto de la cuenca y texto con el detalle."""
        if cn_directo and cn_directo > 0:
            return float(cn_directo), "CN directo"
        if suelos is None:
            cn = hd.cn_compuesto({grupo_def: 1.0}, uso, amc)
            return cn, "grupo %s por defecto, AMC %s" % (grupo_def, amc)
        cel = np.flatnonzero(mascara_total)
        if suelos["tipo"] == "puntos":
            xs, ys = h.xy_de_indices(cel // C - 1, cel % C - 1, gt)
            px = np.asarray([p[0] for p in suelos["puntos"]])
            py = np.asarray([p[1] for p in suelos["puntos"]])
            # vecino más cercano por bloques para no agotar memoria
            mas_cercano = np.empty(cel.size, dtype=np.int64)
            for i in range(0, cel.size, 200000):
                d2 = (xs[i:i + 200000, None] - px[None, :]) ** 2 + (ys[i:i + 200000, None] - py[None, :]) ** 2
                mas_cercano[i:i + 200000] = np.argmin(d2, axis=1)
            cuenta = np.bincount(mas_cercano, minlength=px.size)
            valores = [p[2] for p in suelos["puntos"]]
        else:
            cod = suelos["codigos"].ravel()
            # los códigos están sin acolchar: convertir índices
            filas = cel // C - 1
            cols = cel % C - 1
            ncols = suelos["codigos"].shape[1]
            c = cod[filas * ncols + cols]
            cuenta = np.bincount(c, minlength=len(suelos["valores"]) + 1)[1:]
            valores = suelos["valores"]
            if cuenta.sum() == 0:
                cn = hd.cn_compuesto({grupo_def: 1.0}, uso, amc)
                return cn, "sin suelos en la cuenca: grupo %s por defecto" % grupo_def
        fracciones = {}
        detalle = {}
        total = float(cuenta.sum())
        for k, n in enumerate(cuenta.tolist()):
            if n == 0:
                continue
            tipo, v = valores[k]
            clave = v if tipo == "grupo" else float(v)
            fracciones[clave] = fracciones.get(clave, 0.0) + n / total
            detalle[clave] = detalle.get(clave, 0.0) + n / total
        cn = hd.cn_compuesto(fracciones, uso, amc)
        txt = ", ".join("%s %.0f%%" % (k if isinstance(k, str) else "CN %g" % k, 100 * v)
                        for k, v in sorted(detalle.items(), key=lambda t: -t[1]))
        return cn, "%s; AMC %s" % (txt, amc)

    def _datos_informe(self, nombre_dem, notas, filas, cols, celda, crs, nombre_eje, long_eje, n_partes, puntos,
                       modo, umbral_ha, umbral_celdas, metodo_dep, barrera, altura, radio, fusion, tol_cruce,
                       lluvias, factor_24, idf, uso, amc, grupo_def, cn_directo, suelos, tc_min, tc_criterio,
                       q_adoptar, c_fijo, tabla_cuencas, cuencas_informe, avisos, cond, entero, segmentos,
                       dep_aviso):
        trs = [tr for tr, _ in lluvias]
        tabla = [
            ("DEM", nombre_dem),
            ("Preparación automática del DEM", "; ".join(notas) if notas else "ninguna (se usó tal cual)"),
            ("Celda / filas × columnas", "%.2f m / %d × %d" % (celda, filas, cols)),
            ("Sistema de coordenadas", crs.authid() or crs.description()),
            ("Cotas", "enteras (resolución vertical 1 m)" if entero else "decimales"),
            ("Eje de la vía", "%s (%d parte(s), %.0f m)" % (nombre_eje, n_partes, long_eje)),
            ("Alcantarillas dadas", "%d puntos" % len(puntos) if puntos else "ninguna"),
            ("Modo de salidas", self.MODOS[modo]),
            ("Umbral de cauce", "%.2f ha = %d celdas" % (umbral_ha, umbral_celdas)),
            ("Tratamiento de depresiones", self.DEPRESIONES_OPC[0 if metodo_dep == "relleno" else 1]),
            ("Vía como barrera", ("sí, terraplén de %.1f m" % altura) if barrera else "no"),
            ("Ajuste de puntos / fusión / agrupación de cortes", "%.0f m / %.0f m / %.0f m" % (radio, fusion, tol_cruce)),
            ("Lluvia máxima diaria", "; ".join("Tr %g: %g mm" % (tr, p) for tr, p in lluvias)),
            ("Lluvia de 24 h", "diaria × %.2f" % factor_24),
            ("Intensidad", self.IDF_TIPOS[0] if idf is None else "%s (λ=%g, κ=%g, ψ=%g, θ=%g, η=%g)" % (
                idf["tipo"], idf["lam"], idf["kappa"], idf["psi"], idf["theta"], idf["eta"])),
            ("Uso del suelo (CN)", hd.USOS_CN[uso]),
            ("Suelos", ("CN directo %g" % cn_directo) if cn_directo else (
                "capa de suelos (%s)" % suelos["tipo"] if suelos else "grupo %s por defecto" % grupo_def)),
            ("Condición de humedad", "AMC " + amc),
            ("Tc mínimo / criterio", "%.0f min / %s" % (tc_min, tc_criterio)),
            ("Caudal adoptado", {"temez": "racional modificado de Témez", "racional": "racional clásico",
                                 "mayor": "mayor de los dos"}[q_adoptar] +
             (" (C fijo = %g)" % c_fijo if c_fijo else "")),
        ]
        metodo = [
            "Acondicionamiento del DEM: %s; zonas planas resueltas con el gradiente superpuesto de Barnes, Lehman y "
            "Mulla (2014). Verificación: %d celdas sin salida." % (
                "relleno de depresiones con Priority-Flood (Barnes et al., 2014)" if metodo_dep == "relleno" else
                "apertura de depresiones (breaching híbrido, Lindsay 2016) y relleno Priority-Flood del resto",
                cond["n_sin_salida"]),
            "Direcciones D8 de máxima pendiente (O'Callaghan y Mark, 1984) y acumulación de flujo; red de cauces "
            "con umbral de %.2f ha (%d celdas), segmentos de confluencia a confluencia con orden de Strahler "
            "(%d segmentos)." % (umbral_ha, umbral_celdas, len(segmentos)),
            "Salidas: %s. Los cruces se obtienen por intersección geométrica exacta de cada segmento de cauce con "
            "el eje; los puntos dados se ajustan a la celda de mayor acumulación en %.0f m. Progresivas medidas "
            "sobre el eje concatenando sus partes." % (self.MODOS[modo], radio),
            "Cuenca de cada salida: todas las celdas cuyo camino D8 pasa por ella (incluye las cuencas anidadas "
            "aguas arriba). Polígono sin islas. L = máxima distancia de flujo hasta la salida (pasos diagonales "
            "√2·celda).",
            "Parámetros: A, P (del polígono ráster), L, Hmáx, Hmín en la salida, ΔH, S = ΔH/L, pendiente 10–85 "
            "del recorrido, pendiente media de la cuenca (Horn), cota media, Kc = 0.28·P/√A, Kf = A/L², "
            "depresiones cerradas (relleno − terreno) y contacto con el borde del DEM.",
            "Tc: Kirpich (1940), Témez (1978), California Culverts Practice (1942), Bransby-Williams (1922) y "
            "retardo SCS (NRCS NEH-630 cap. 15), con sus rangos de calibración; Tc mínimo %.0f min; adoptado: %s."
            % (tc_min, tc_criterio),
            "CN de la tabla TR-55 (USDA-NRCS, 1986) por uso y grupo hidrológico, compuesto por área; condición "
            "AMC %s (Chow et al., 1988)." % amc,
            "Lluvia de 24 h = diaria × %.2f (Hershfield, 1961). Intensidad: %s." % (
                factor_24, "Dyck-Peschke, P_d = P24·(d/1440)^0.25" if idf is None else
                "curva IDF %s (Koutsoyiannis et al., 1998 / Hydrognomon)" % idf["tipo"]),
            "Caudal: racional Q = C·I·A/3.6 y racional modificado de Témez Q = C·I·A·K/3.6 con "
            "C = (Pd−Po)(Pd+23Po)/(Pd+11Po)², Po = 5080/CN − 50.8 y K = 1 + Tc^1.25/(Tc^1.25+14) (Témez, 1991).",
        ]
        if barrera:
            metodo.append("Escenario «con_via»: el eje se eleva %.1f m en el DEM salvo en las celdas de salida y "
                          "se repite todo el análisis; el agua que llega al terraplén corre por su pie hasta la "
                          "alcantarilla más cercana." % altura)
        limitaciones = [
            "El DEM manda: con celda de %.1f m%s las divisorias en terreno plano son inciertas en varias celdas y "
            "las pendientes de celda son escalonadas. Valida las cuencas críticas con topografía." % (
                celda, " y cotas enteras" if entero else ""),
            "Las depresiones cerradas se rellenan para que todo drene: el caudal racional no descuenta ese "
            "almacenamiento, por lo que en cuencas con muchas depresiones es un límite superior.",
            "Una cuenca que toca el borde del DEM puede estar incompleta.",
            "Las fórmulas de Tc son empíricas; fuera de su rango de calibración (marcado con *) son extrapolaciones. "
            "En pendientes menores de 1 % Kirpich y California tienden a subestimar Tc (y a sobrestimar Q).",
            "El método racional supone lluvia uniforme de duración igual a Tc y es apropiado para cuencas pequeñas "
            "(el Manual del MTC lo limita a unos 10 km²); para cuencas mayores conviene un hidrograma unitario.",
            "El escenario con la vía como barrera supone terraplén continuo e impermeable salvo en las "
            "alcantarillas indicadas; no modela cunetas ni la capacidad hidráulica de cada obra.",
        ]
        if cuencas_informe:
            tr_max = trs[-1]
            texto = (
                "Las cuencas de aporte de las %d obras de cruce se delimitaron sobre el modelo digital de elevación "
                "(celda de %.1f m) con el complemento QGIS «Exutorios Viales»: el DEM se acondicionó hidrológicamente "
                "(%s y resolución de planicies de Barnes et al., 2014), se obtuvieron las direcciones y la "
                "acumulación de flujo D8, la red de cauces con un umbral de %.2f ha y las cuencas de cada salida. "
                "Para cada cuenca se calcularon el área, el perímetro, la longitud del recorrido más largo, las "
                "cotas extremas, las pendientes, los índices de compacidad y de forma, y el tiempo de "
                "concentración con las fórmulas de Kirpich, Témez, California Culverts Practice, Bransby-Williams y "
                "del retardo del SCS (adoptando %s, con un mínimo de %.0f min). El caudal de diseño se estimó con "
                "el método racional modificado de Témez a partir de la lluvia máxima diaria de %s (Log-Pearson III), "
                "convertida a 24 h con el factor %.2f e intensidad por %s, con número de curva de la tabla "
                "TR-55 (%s, AMC %s). Las áreas resultan entre %.3f y %.3f km² y los caudales para Tr = %g años "
                "entre %.2f y %.2f m³/s. Los resultados son referenciales y deben validarse con topografía de "
                "detalle en el expediente técnico." % (
                    len(cuencas_informe), celda,
                    "relleno de depresiones por Priority-Flood" if metodo_dep == "relleno" else "breaching y relleno",
                    umbral_ha, tc_criterio, tc_min,
                    "; ".join("%g mm para Tr %g años" % (p, tr) for tr, p in lluvias), factor_24,
                    "Dyck-Peschke" if idf is None else "la curva IDF de Hydrognomon",
                    hd.USOS_CN[uso], amc,
                    min(f["area_km2"] for f in cuencas_informe), max(f["area_km2"] for f in cuencas_informe),
                    tr_max, min(f["q"][tr_max]["q_adoptado"] for f in cuencas_informe),
                    max(f["q"][tr_max]["q_adoptado"] for f in cuencas_informe)))
        else:
            texto = ""
        return {
            "parametros": {"tabla": tabla, "tc_min": tc_min},
            "metodo": metodo,
            "cuencas": [f for f in tabla_cuencas if f["escenario"] == "natural"] +
                       [f for f in tabla_cuencas if f["escenario"] != "natural"],
            "hidrologia": {"tr": trs, "formulas_tc": list(hd.FORMULAS_TC), "texto": [
                "Lluvia máxima diaria por periodo de retorno (Log-Pearson III): %s. Lluvia de 24 h = diaria × %.2f."
                % ("; ".join("Tr %g años: %g mm" % (tr, p) for tr, p in lluvias), factor_24),
                "Intensidad para una duración igual al Tc adoptado: %s." % (
                    "Dyck-Peschke, I = P24·(Tc/1440)^0.25 / (Tc/60)" if idf is None else "curva IDF %s" % idf["tipo"]),
                "C de Témez con Po = 5080/CN − 50.8 (equivalente a Ia = 0.2·S); K = 1 + Tc^1.25/(Tc^1.25+14). "
                "Caudal adoptado: %s." % {"temez": "racional modificado de Témez", "racional": "racional clásico",
                                          "mayor": "el mayor de los dos"}[q_adoptar],
                ("Las filas «con_via» corresponden al escenario con la vía como barrera." if barrera else "")]},
            "avisos": avisos,
            "limitaciones": limitaciones,
            "texto_tesis": texto,
        }


# ---------------------------------------------------------------------------
# Algoritmo rápido
# ---------------------------------------------------------------------------

class CuencasAlcantarillasRapidoAlgorithm(CuencasAlcantarillasAlgorithm):
    """Misma lógica; a la vista solo DEM, eje, puntos, umbral, lluvia, uso del
    suelo, suelos y vía como barrera. El resto va en «Parámetros avanzados»."""

    VISIBLES = (
        CuencasAlcantarillasAlgorithm.DEM,
        CuencasAlcantarillasAlgorithm.EJE,
        CuencasAlcantarillasAlgorithm.PUNTOS,
        CuencasAlcantarillasAlgorithm.CAMPO_NOMBRE,
        CuencasAlcantarillasAlgorithm.UMBRAL_HA,
        CuencasAlcantarillasAlgorithm.LLUVIA,
        CuencasAlcantarillasAlgorithm.USO,
        CuencasAlcantarillasAlgorithm.SUELOS,
        CuencasAlcantarillasAlgorithm.CAMPO_SUELO,
        CuencasAlcantarillasAlgorithm.VIA_BARRERA,
    )

    def createInstance(self):
        return CuencasAlcantarillasRapidoAlgorithm()

    def name(self):
        return "cuencas_alcantarillas_rapido"

    def displayName(self):
        return self.tr("Cuencas de alcantarillas (análisis rápido: DEM + eje)")

    def shortHelpString(self):
        return self.tr(
            "<p><b>Elige el DEM y el eje de la vía y pulsa Ejecutar.</b> Si tienes las alcantarillas del diseño "
            "como puntos, añádelas: cada punto se ajusta a la celda de mayor acumulación en 25 m y se combina con "
            "los cruces automáticos sin duplicar.</p>"
            "<p>Valores por defecto: umbral de cauce 2 ha, relleno de depresiones Priority-Flood con planicies de "
            "Barnes, lluvia diaria 58.5/70.6/101.7 mm (Tr 25/35/71), factor 1.13, Dyck-Peschke, CN de cultivos en "
            "hileras con grupo C, AMC II, Tc = media de las fórmulas en rango (mínimo 10 min), caudal racional "
            "modificado de Témez. Todo se puede cambiar en «Parámetros avanzados».</p>"
            "<p>Salidas: cuencas, salidas, cauces y recorridos con simbología; rásters opcionales; CSV e informe "
            "HTML con advertencias (borde del DEM, fórmulas fuera de rango, depresiones).</p>")

    def initAlgorithm(self, config=None):
        super().initAlgorithm(config)
        for p in self.parameterDefinitions():
            if p.name() in self.VISIBLES or p.isDestination():
                continue
            _avanzado(p)

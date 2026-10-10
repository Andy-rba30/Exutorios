# -*- coding: utf-8 -*-
"""Ejecución completa de processAlgorithm() con el sustituto de PyQGIS.

Necesita GDAL/OGR (python3-gdal); si no está, se omite. Construye un DEM
sintético (valle en V con una vía que lo cruza) y verifica cada salida."""
import os

import numpy as np
import pytest

osgeo = pytest.importorskip("osgeo")
from osgeo import gdal  # noqa: E402

from qgis.core import FuenteFalsa, CapaRasterFalsa, ContextoFalso, FeedbackFalso, SINKS  # noqa: E402
from exutorios_viales import algoritmo  # noqa: E402

WKT = ('PROJCS["WGS 84 / UTM zone 17S",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
       'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],'
       'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",-81],PARAMETER["scale_factor",0.9996],'
       'PARAMETER["false_easting",500000],PARAMETER["false_northing",10000000],UNIT["metre",1],'
       'AUTHORITY["EPSG","32717"]]')
X0, Y0, CELDA = 500000.0, 9400000.0, 10.0


def escribir_dem(ruta, dem):
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(ruta, dem.shape[1], dem.shape[0], 1, gdal.GDT_Float32)
    ds.SetGeoTransform((X0, CELDA, 0, Y0, 0, -CELDA))
    ds.SetProjection(WKT)
    ds.GetRasterBand(1).WriteArray(dem.astype(np.float32))
    ds.GetRasterBand(1).SetNoDataValue(-9999)
    ds = None


@pytest.fixture
def dem_valle(tmp_path):
    n = 120
    yy, xx = np.mgrid[0:n, 0:n]
    dem = 100 + (n - 1 - yy) * 0.1 + 1.0 * np.abs(xx - 60)
    ruta = str(tmp_path / "dem.tif")
    escribir_dem(ruta, dem)
    return ruta, dem


def correr(ruta_dem, tmp_path, extra=None, clase=algoritmo.CuencasAlcantarillasRapidoAlgorithm):
    SINKS.clear()
    dem = CapaRasterFalsa(ruta_dem, "dem")
    crs = dem.crs()
    # eje horizontal en la fila 80 (y = Y0 - 805), de x = 0 a 1200 m, en dos partes
    y = Y0 - 80.5 * CELDA
    eje = FuenteFalsa([("LINESTRING (%r %r, %r %r)" % (X0, y, X0 + 400, y), {}),
                       ("LINESTRING (%r %r, %r %r)" % (X0 + 400, y, X0 + 1200, y), {})], "LineString", crs, "eje")
    params = {"DEM": dem, "EJE": eje, "OUT_CUENCAS": "cuencas", "OUT_SALIDAS": "salidas", "OUT_CAUCES": "cauces",
              "OUT_RECORRIDOS": "recorridos", "OUT_CSV": str(tmp_path / "c.csv"),
              "OUT_INFORME": str(tmp_path / "informe.html"), "UMBRAL_HA": 1.0}
    if extra:
        params.update(extra)
    a = clase()
    a.initAlgorithm()
    fb = FeedbackFalso()
    res = a.processAlgorithm(params, ContextoFalso(), fb)
    return res, fb


def test_valle_v_cruce_automatico(dem_valle, tmp_path):
    ruta, dem = dem_valle
    res, fb = correr(ruta, tmp_path)
    assert res["N_SALIDAS"] == 1
    cu = [f.como_dict() for f in SINKS["cuencas"].features]
    assert len(cu) == 1
    c = cu[0]
    # 81 filas × 120 columnas drenan al fondo del valle en la fila 80
    assert c["area_ha"] == pytest.approx(81 * 120 * CELDA ** 2 / 1e4)
    assert c["progresiva"] == "0+605"          # x del fondo = 60.5 celdas
    assert c["l_m"] == pytest.approx((60 + 80) * CELDA)
    assert c["borde"] == "SI"
    assert c["origen"] == "cruce"
    assert c["q_71"] > c["q_25"] > 0
    assert c["tc_adopt"] >= 10.0
    assert c["cn"] == 85.0                      # cultivos en hileras, grupo C por defecto
    assert len(SINKS["salidas"].features) == 1
    assert len(SINKS["cauces"].features) >= 1
    assert len(SINKS["recorridos"].features) == 1
    assert os.path.exists(str(tmp_path / "c.csv")) and os.path.exists(str(tmp_path / "informe.html"))
    html = open(str(tmp_path / "informe.html"), encoding="utf-8").read()
    assert "0+605" in html and "toca el borde" in html
    assert any("ninguna celda válida quedó sin salida" in m for m in fb.mensajes)


def test_puntos_suelos_barrera_y_rasters(dem_valle, tmp_path):
    ruta, dem = dem_valle
    crs = CapaRasterFalsa(ruta).crs()
    # punto a 18 m del fondo del valle sobre el eje; otro lejos (se ajusta a su propia celda)
    puntos = FuenteFalsa([("POINT (%r %r)" % (X0 + 605 + 18, Y0 - 805), {"nombre": "ALC-1"}),
                          ("POINT (%r %r)" % (X0 + 200, Y0 - 300), {"nombre": "ALC-2"})], "Point", crs, "pts")
    suelos = FuenteFalsa([("POINT (%r %r)" % (X0 + 300, Y0 - 300), {"grupo": "A"}),
                          ("POINT (%r %r)" % (X0 + 900, Y0 - 300), {"grupo": "D"})], "Point", crs, "calicatas")
    extra = {"PUNTOS": puntos, "CAMPO_NOMBRE": "nombre", "SUELOS": suelos, "CAMPO_SUELO": "grupo",
             "VIA_BARRERA": True, "ALTURA_VIA": 3.0, "OUT_ACUMULACION": str(tmp_path / "acc.tif"),
             "OUT_DIRECCION": str(tmp_path / "dir.tif"), "OUT_CUENCAS_RASTER": str(tmp_path / "cu.tif"),
             "OUT_MFD": str(tmp_path / "mfd.tif"), "AMC": 1, "MODO_SALIDAS": 2}
    res, fb = correr(ruta, tmp_path, extra, algoritmo.CuencasAlcantarillasAlgorithm)
    cu = [f.como_dict() for f in SINKS["cuencas"].features]
    nat = [c for c in cu if c["escenario"] == "natural"]
    via = [c for c in cu if c["escenario"] == "con_via"]
    assert len(nat) == len(via) == res["N_SALIDAS"]
    # el punto ALC-1 se fusiona con el cruce (a menos de 30 m) y conserva su nombre
    s = [f.como_dict() for f in SINKS["salidas"].features]
    alc1 = next(x for x in s if x["nombre"] == "ALC-1")
    assert alc1["origen"] == "punto+cruce"
    assert alc1["despl_m"] <= 25.0 + 1e-6
    # CN compuesto por Thiessen: entre A (67) y D (89) con AMC III (> 67)
    c1 = next(c for c in nat if c["nombre"] == "ALC-1")
    assert 67 < c1["cn"] < 100 and "AMC III" in c1["cn_detalle"]
    # con la vía como barrera el cruce del valle conserva su cuenca
    v1 = next(c for c in via if c["nombre"] == "ALC-1")
    assert v1["area_ha"] == pytest.approx(c1["area_ha"], rel=0.05)
    for n in ("acc.tif", "dir.tif", "cu.tif", "mfd.tif"):
        ds = gdal.Open(str(tmp_path / n))
        assert ds is not None and ds.RasterXSize == 120
    acc = gdal.Open(str(tmp_path / "acc.tif")).ReadAsArray()
    assert acc.max() == pytest.approx(120 * 120 * CELDA ** 2 / 1e4, rel=0.01)   # fila inferior del valle
    cuencas_r = gdal.Open(str(tmp_path / "cu.tif")).ReadAsArray()
    assert cuencas_r.max() == res["N_SALIDAS"]


def test_solo_puntos_e_idf(dem_valle, tmp_path):
    ruta, dem = dem_valle
    crs = CapaRasterFalsa(ruta).crs()
    puntos = FuenteFalsa([("POINT (%r %r)" % (X0 + 605, Y0 - 805), {})], "Point", crs, "pts")
    extra = {"PUNTOS": puntos, "MODO_SALIDAS": 1, "IDF_TIPO": 1, "IDF_LAMBDA": 20.0, "IDF_PSI": 0.5,
             "IDF_THETA": 0.2, "IDF_ETA": 0.7, "CN_DIRECTO": 80.0, "Q_ADOPTADO": 1, "TC_CRITERIO": 4,
             "DEPRESIONES": 1}
    res, fb = correr(ruta, tmp_path, extra, algoritmo.CuencasAlcantarillasAlgorithm)
    c = SINKS["cuencas"].features[0].como_dict()
    assert c["origen"] == "punto" and c["cn"] == 80.0
    assert c["tc_crit"] == "Kirpich" and c["tc_adopt"] == pytest.approx(max(c["tc_kirp"], 10.0))
    assert c["q_25"] == pytest.approx(c["qr_25"])
    assert any("Breaching" in m for m in fb.mensajes)


def test_sin_cruces_lanza_error(dem_valle, tmp_path):
    ruta, dem = dem_valle
    from qgis.core import QgsProcessingException
    with pytest.raises(QgsProcessingException):
        correr(ruta, tmp_path, {"UMBRAL_HA": 500.0})

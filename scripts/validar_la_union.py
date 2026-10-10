#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validación con el caso real de La Unión (Piura): corre el algoritmo completo
sobre el DEM de GRASS con el eje y las 17 alcantarillas, y compara las dos
cuencas de referencia de GRASS (r.watershed + r.water.outlet + r.lfp).

Necesita python3-gdal. Usa el sustituto de PyQGIS de tests/qgis_stub, así que
no requiere QGIS. Uso:  python3 scripts/validar_la_union.py [umbral_ha]
"""
import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tests", "qgis_stub"))

from osgeo import ogr, gdal  # noqa: E402
gdal.UseExceptions()
from qgis.core import FuenteFalsa, CapaRasterFalsa, ContextoFalso, FeedbackFalso, SINKS  # noqa: E402
from exutorios_viales import algoritmo  # noqa: E402

DATOS = os.path.join(RAIZ, "datos_prueba", "la_union")
SALIDA = os.path.join(RAIZ, "dist", "validacion_la_union")


def fuente_de_gpkg(ruta, wkb, crs):
    ds = ogr.Open(ruta)
    capa = ds.GetLayer(0)
    defn = capa.GetLayerDefn()
    nombres = [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]
    elems = []
    for f in capa:
        elems.append((f.GetGeometryRef().ExportToWkt(), {n: f.GetField(n) for n in nombres}))
    return FuenteFalsa(elems, wkb, crs, os.path.basename(ruta)), elems


def correr(umbral_ha, puntos, modo, etiqueta, barrera=False):
    SINKS.clear()
    os.makedirs(SALIDA, exist_ok=True)
    dem = CapaRasterFalsa(os.path.join(DATOS, "dem_grass_area_estudio.tif"), "dem_grass_area_estudio")
    crs = dem.crs()
    eje, _ = fuente_de_gpkg(os.path.join(DATOS, "eje_via.gpkg"), "LineString", crs)
    params = {"DEM": dem, "EJE": eje, "PUNTOS": puntos, "CAMPO_NOMBRE": "progresiva", "MODO_SALIDAS": modo,
              "UMBRAL_HA": umbral_ha,
              "VIA_BARRERA": barrera, "OUT_CUENCAS": "cuencas", "OUT_SALIDAS": "salidas", "OUT_CAUCES": "cauces",
              "OUT_RECORRIDOS": "recorridos", "OUT_CSV": os.path.join(SALIDA, "cuencas_%s.csv" % etiqueta),
              "OUT_INFORME": os.path.join(SALIDA, "informe_%s.html" % etiqueta)}
    a = algoritmo.CuencasAlcantarillasAlgorithm()
    a.initAlgorithm()
    fb = FeedbackFalso()
    t = time.time()
    res = a.processAlgorithm(params, ContextoFalso(), fb)
    print("[%s] %.1f s; %s" % (etiqueta, time.time() - t, res["RESUMEN"]))
    for m in fb.avisos:
        print("   AVISO:", m)
    return [f.como_dict() for f in SINKS["cuencas"].features], \
        [(f.como_dict(), f.geometry()) for f in SINKS["cuencas"].features], \
        [f.como_dict() for f in SINKS["salidas"].features], fb


def main():
    umbral = float(sys.argv[1]) if len(sys.argv) > 1 else 10.94
    crs = CapaRasterFalsa(os.path.join(DATOS, "dem_grass_area_estudio.tif")).crs()
    alc, alc_elems = fuente_de_gpkg(os.path.join(DATOS, "alcantarillas_17.gpkg"), "Point", crs)
    gr, gr_elems = fuente_de_gpkg(os.path.join(DATOS, "exutorios_grass.gpkg"), "Point", crs)
    ds = ogr.Open(os.path.join(DATOS, "cuencas_grass.gpkg"))
    grass = {}
    for f in ds.GetLayer(0):
        d = {k: f.GetField(k) for k in ("Cuenca", "cota_min_m", "cota_max_m", "long_cauce_m", "pendiente", "area_ha",
                                        "progresiva_cruce")}
        d["geom"] = f.GetGeometryRef().Clone()
        grass[d["Cuenca"]] = d

    def comparar(titulo, geoms, sal):
        print("\n=== %s ===" % titulo)
        print("%-7s %-10s %9s %8s %8s %6s %6s %6s %8s %5s  %s" % ("Cuenca", "Fuente", "A (ha)", "P (km)", "L (m)", "Hmin",
                                                               "HminZ", "Hmax", "S=dH/L", "IoU", "salida"))
        for k in sorted(grass):
            ref = grass[k]
            # la cuenca del complemento que mejor coincide (mayor IoU) entre las naturales
            mejor = None
            for fila, g in geoms:
                if fila["escenario"] != "natural":
                    continue
                inter = ref["geom"].Intersection(g._g).GetArea()
                union = ref["geom"].Union(g._g).GetArea()
                iou = inter / union if union > 0 else 0.0
                if mejor is None or iou > mejor[0]:
                    mejor = (iou, fila)
            iou, fila = mejor
            despl = next((s_["despl_m"] for s_ in sal if s_["id"] == fila["id"]), 0.0) or 0.0
            print("%-7s %-10s %9.2f %8.3f %8.1f %6.1f %6s %6.1f %8.5f %5s  %s" % (
                k, "GRASS", ref["area_ha"], ref["geom"].Boundary().Length() / 1000.0, ref["long_cauce_m"],
                ref["cota_min_m"], "", ref["cota_max_m"], ref["pendiente"], "", ref["progresiva_cruce"]))
            print("%-7s %-10s %9.2f %8.3f %8.1f %6.1f %6.1f %6.1f %8.5f %5.2f  %s (%s, desplazada %.0f m)" % (
                k, "Exutorios", fila["area_ha"], fila["perim_km"], fila["l_m"], fila["h_min"], fila["h_min_z"],
                fila["h_max"], fila["s_l"], iou, fila["progresiva"], fila["origen"], despl))
            print("        s_1085 %.5f; depresiones %d (%.1f %% del área); Tc adoptado %.1f min (%s); Q71 = %.2f m³/s"
                  % (fila["s_1085"], fila["n_dep"], 100 * fila["frac_dep"], fila["tc_adopt"], fila["tc_crit"],
                     fila["q_71"]))

    # 1. Corrida con las dos salidas de GRASS (modo solo puntos)
    cu, geoms, sal, fb = correr(umbral, gr, 1, "salidas_grass")
    comparar("Comparación con GRASS usando sus mismas salidas (ajustadas a 25 m), umbral %.2f ha" % umbral, geoms, sal)

    # 2. Corrida completa: 17 alcantarillas + cruces automáticos
    cu, geoms, sal, fb = correr(umbral, alc, 2, "completa")
    comparar("Mejor coincidencia entre todas las cuencas de la corrida completa (17 puntos + cruces)", geoms, sal)
    print("\n=== 17 alcantarillas del diseño (umbral %.2f ha): cuenca natural y caudal ===" % umbral)
    print("%-3s %-7s %-12s %-12s %8s %8s %8s %8s %8s %8s %8s   %s" % ("n", "prog", "tipo", "origen", "A (ha)", "L (m)", "S",
                                                                     "Tc min", "Q25", "Q35", "Q71", "diseño (Tr, Q)"))
    diseno = {e[1]["progresiva"]: e[1] for e in alc_elems}
    for f in cu:
        if f["escenario"] != "natural":
            continue
        d = diseno.get(f["nombre"], {})
        print("%-3s %-7s %-12s %-12s %8.2f %8.0f %8.4f %8.1f %8.3f %8.3f %8.3f   %s" % (
            d.get("n", "-"), f["progresiva"], d.get("tipo", "cruce auto"), f["origen"], f["area_ha"], f["l_m"],
            f["s_l"] or 0, f["tc_adopt"], f["q_25"], f["q_35"], f["q_71"],
            ("Tr %s: %s m³/s" % (d["tr_anios"], d["q_m3s"])) if d else ""))


if __name__ == "__main__":
    main()

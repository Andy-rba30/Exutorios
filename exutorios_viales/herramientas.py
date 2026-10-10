# -*- coding: utf-8 -*-
# Complemento QGIS «Exutorios Viales»
# Copyright (C) 2026 Jose Ospina
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version. See the LICENSE file for details.
"""
Funciones auxiliares sin dependencia de QGIS: geometría del eje y
progresivas (mismo criterio que «Cota de Anegamiento»: las partes de la línea
se concatenan en el orden recibido), intersección exacta de polilíneas,
CSV e informe HTML.
"""

import datetime
import html
import math

import numpy as np


# ---------------------------------------------------------------------------
# Geometría ráster
# ---------------------------------------------------------------------------

def celda_de_xy(x, y, gt):
    """Fila y columna de la celda que contiene el punto (x, y)."""
    col = int(math.floor((x - gt[0]) / gt[1]))
    fila = int(math.floor((y - gt[3]) / gt[5]))
    return fila, col


def xy_de_celda(fila, col, gt):
    """Coordenadas del centro de una celda (admite valores fraccionarios)."""
    return gt[0] + (col + 0.5) * gt[1], gt[3] + (fila + 0.5) * gt[5]


def xy_de_indices(filas, cols, gt):
    """Versión vectorial de xy_de_celda."""
    filas = np.asarray(filas, dtype=float)
    cols = np.asarray(cols, dtype=float)
    return gt[0] + (cols + 0.5) * gt[1], gt[3] + (filas + 0.5) * gt[5]


def mascara_polilineas(polilineas, gt, forma):
    """Rasteriza polilíneas con conectividad de 4 vecinos.

    Con 4 vecinos el terraplén no deja «fugas» en diagonal para el flujo
    D8. polilineas: lista de listas de (x, y)."""
    filas, cols = forma
    m = np.zeros(forma, dtype=bool)
    paso = min(abs(gt[1]), abs(gt[5])) / 4.0

    def marcar(f, c):
        if 0 <= f < filas and 0 <= c < cols:
            m[f, c] = True

    for pts in polilineas:
        previa = None
        for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
            L = math.hypot(x1 - x0, y1 - y0)
            n = max(int(math.ceil(L / paso)), 1)
            for k in range(n + 1):
                t = k / n
                f, c = celda_de_xy(x0 + t * (x1 - x0), y0 + t * (y1 - y0), gt)
                if previa is not None and (f, c) != previa:
                    df, dc = f - previa[0], c - previa[1]
                    if abs(df) >= 1 and abs(dc) >= 1:
                        marcar(previa[0], c)  # cierra el paso diagonal
                marcar(f, c)
                previa = (f, c)
    return m


# ---------------------------------------------------------------------------
# Eje y progresivas
# ---------------------------------------------------------------------------

def longitudes_partes(polilineas):
    """Longitud de cada parte y progresiva base (acumulada) al inicio de cada una."""
    bases = []
    longs = []
    base = 0.0
    for pts in polilineas:
        seg = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts[:-1], pts[1:])]
        total = float(sum(seg))
        bases.append(base)
        longs.append(total)
        base += total
    return bases, longs


def muestrear_polilineas(polilineas, paso):
    """Puntos cada `paso` m a lo largo de las polilíneas: lista de (progresiva, x, y).

    La progresiva continúa de una polilínea a la siguiente en el orden recibido."""
    salida = []
    base = 0.0
    for pts in polilineas:
        if len(pts) < 2:
            continue
        seg = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts[:-1], pts[1:])]
        total = sum(seg)
        if total <= 0:
            continue
        d = 0.0
        distancias = []
        while d < total - 1e-9:
            distancias.append(d)
            d += paso
        distancias.append(total)
        acum = 0.0
        i = 0
        for dist in distancias:
            while i < len(seg) - 1 and acum + seg[i] < dist - 1e-9:
                acum += seg[i]
                i += 1
            t = 0.0 if seg[i] == 0 else (dist - acum) / seg[i]
            t = min(max(t, 0.0), 1.0)
            a, b = pts[i], pts[i + 1]
            salida.append((base + dist, a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
        base += total
    return salida


def progresiva_de_punto(x, y, polilineas):
    """Progresiva (m) del punto del eje más cercano a (x, y), y la distancia
    perpendicular. Las partes se concatenan en el orden recibido."""
    mejor = (float("nan"), float("inf"))
    base = 0.0
    for pts in polilineas:
        if len(pts) < 2:
            continue
        p = np.asarray(pts, dtype=float)
        a = p[:-1]
        b = p[1:]
        d = b - a
        L2 = (d ** 2).sum(axis=1)
        L = np.sqrt(L2)
        t = np.where(L2 > 0, ((x - a[:, 0]) * d[:, 0] + (y - a[:, 1]) * d[:, 1]) / np.maximum(L2, 1e-300), 0.0)
        t = np.clip(t, 0.0, 1.0)
        px = a[:, 0] + t * d[:, 0]
        py = a[:, 1] + t * d[:, 1]
        dist = np.hypot(px - x, py - y)
        k = int(np.argmin(dist))
        if dist[k] < mejor[1]:
            acum = float(np.concatenate(([0.0], np.cumsum(L)))[k])
            mejor = (base + acum + t[k] * L[k], float(dist[k]))
        base += float(L.sum())
    return mejor


def progresiva_km(m):
    """Formato de progresiva 0+000."""
    if m is None or not math.isfinite(m):
        return "-"
    total = int(round(m))
    return "%d+%03d" % (total // 1000, total % 1000)


def intersecciones(polilinea, partes_eje):
    """Intersecciones exactas entre una polilínea y las partes del eje.

    polilinea: array (n, 2). partes_eje: lista de arrays (m, 2).
    Devuelve lista de dicts: x, y, progresiva (sobre el eje concatenado),
    i (índice del tramo de la polilínea), t (posición 0-1 dentro del tramo)."""
    p = np.asarray(polilinea, dtype=float)
    if p.shape[0] < 2:
        return []
    a = p[:-1]
    d1 = p[1:] - a
    res = []
    base = 0.0
    for parte in partes_eje:
        q = np.asarray(parte, dtype=float)
        if q.shape[0] < 2:
            continue
        c = q[:-1]
        d2 = q[1:] - c
        Lq = np.hypot(d2[:, 0], d2[:, 1])
        acum = np.concatenate(([0.0], np.cumsum(Lq)))
        # filtro por cajas envolventes
        amin = np.minimum(a, a + d1)
        amax = np.maximum(a, a + d1)
        cmin = np.minimum(c, c + d2)
        cmax = np.maximum(c, c + d2)
        cand = ((amin[:, None, 0] <= cmax[None, :, 0]) & (amax[:, None, 0] >= cmin[None, :, 0]) &
                (amin[:, None, 1] <= cmax[None, :, 1]) & (amax[:, None, 1] >= cmin[None, :, 1]))
        ii, jj = np.nonzero(cand)
        if ii.size:
            A = a[ii]
            D1 = d1[ii]
            Cc = c[jj]
            D2 = d2[jj]
            den = D1[:, 0] * D2[:, 1] - D1[:, 1] * D2[:, 0]
            ok = np.abs(den) > 1e-12
            w = Cc - A
            t = np.where(ok, (w[:, 0] * D2[:, 1] - w[:, 1] * D2[:, 0]) / np.where(ok, den, 1.0), -1.0)
            u = np.where(ok, (w[:, 0] * D1[:, 1] - w[:, 1] * D1[:, 0]) / np.where(ok, den, 1.0), -1.0)
            # tramo cerrado por la izquierda y abierto por la derecha, para no
            # contar dos veces el cruce en un vértice
            ok &= (t >= 0.0) & (t < 1.0) & (u >= 0.0) & (u < 1.0)
            for k in np.flatnonzero(ok):
                x = A[k, 0] + t[k] * D1[k, 0]
                y = A[k, 1] + t[k] * D1[k, 1]
                res.append({"x": float(x), "y": float(y),
                            "progresiva": float(base + acum[jj[k]] + u[k] * Lq[jj[k]]),
                            "i": int(ii[k]), "t": float(t[k])})
        base += float(Lq.sum())
    return res


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def escribir_csv(ruta, columnas, filas):
    """CSV con separador «;» y BOM (abre bien en Excel en español)."""
    def fmt(v):
        if v is None:
            return ""
        if isinstance(v, float):
            if not math.isfinite(v):
                return ""
            return ("%.4f" % v).rstrip("0").rstrip(".")
        return str(v)
    with open(ruta, "w", encoding="utf-8-sig") as f:
        f.write(";".join(columnas) + "\n")
        for fila in filas:
            f.write(";".join(fmt(fila.get(c)) for c in columnas) + "\n")


# ---------------------------------------------------------------------------
# Informe HTML
# ---------------------------------------------------------------------------

def _n(v, dec=2):
    if v is None:
        return "-"
    try:
        if not math.isfinite(v):
            return "-"
    except TypeError:
        return html.escape(str(v))
    s = "{:,.{d}f}".format(v, d=dec)
    return s.replace(",", " ")


CSS = """
body{font-family:Segoe UI,Arial,sans-serif;margin:24px auto;max-width:1200px;color:#1f2933;line-height:1.45;padding:0 16px}
h1{font-size:24px;margin-bottom:4px}h2{font-size:18px;margin-top:28px;border-bottom:2px solid #d9e2ec;padding-bottom:4px}
h3{font-size:15px;margin-top:18px}
.sub{color:#52606d;margin-top:0}
table{border-collapse:collapse;width:100%;margin:8px 0 16px;font-size:12.5px}
th,td{border:1px solid #d9e2ec;padding:3px 5px;text-align:right}th{background:#f0f4f8;text-align:center}
td.t{text-align:left}
.kpis{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0}
.kpi{border:1px solid #d9e2ec;border-radius:6px;padding:10px 14px;min-width:160px;flex:1}
.kpi b{display:block;font-size:22px;color:#102a43}.kpi span{font-size:12px;color:#52606d}
.aviso{background:#fff8e1;border-left:4px solid #f0b429;padding:8px 12px;margin:10px 0}
.malo{background:#fdecea;border-left:4px solid #d64545;padding:8px 12px;margin:10px 0}
.ok{background:#e3f9e5;border-left:4px solid #3ebd93;padding:8px 12px;margin:10px 0}
.cita{background:#f0f4f8;padding:12px;border-radius:6px;font-size:14px}
.fuera{color:#b54708}
small{color:#52606d}
"""


def informe_html(ruta, datos):
    """Escribe el informe. `datos` es el dict armado por el algoritmo."""
    e = html.escape
    p = datos["parametros"]
    out = []
    w = out.append
    w("<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>")
    w("<title>Cuencas de alcantarillas</title><style>%s</style></head><body>" % CSS)
    w("<h1>Cuencas de aporte de alcantarillas – informe de cálculo</h1>")
    w("<p class='sub'>Generado el %s con el complemento QGIS «Exutorios Viales». Resultado referencial para "
      "estudios a nivel de perfil.</p>" % datetime.datetime.now().strftime("%d/%m/%Y %H:%M"))

    cuencas = datos["cuencas"]
    trs = datos["hidrologia"]["tr"]
    naturales = [c for c in cuencas if c["escenario"] == "natural"]
    hay_via = any(c["escenario"] != "natural" for c in cuencas)

    def esc(c):
        return ("<td class='t'>%s</td>" % e(c["escenario"])) if hay_via else ""

    col_esc = "<th>Escenario</th>" if hay_via else ""

    # 1. Resumen
    w("<h2>1. Resumen</h2>")
    w("<div class='kpis'>")
    w("<div class='kpi'><b>%d</b><span>Salidas analizadas (cruces + puntos)</span></div>" % len(naturales))
    if naturales:
        mayor = max(naturales, key=lambda c: c["area_km2"])
        w("<div class='kpi'><b>%s km²</b><span>Cuenca mayor (salida %d, %s)</span></div>"
          % (_n(mayor["area_km2"], 3), mayor["id"], e(progresiva_km(mayor.get("progresiva")))))
        if trs:
            tr0 = trs[-1]
            qmax = max(naturales, key=lambda c: c["q"].get(tr0, {}).get("q_adoptado", 0) or 0)
            w("<div class='kpi'><b>%s m³/s</b><span>Caudal máximo Tr %s años (salida %d, cuenca natural)</span></div>"
              % (_n(qmax["q"][tr0]["q_adoptado"]), _n(tr0, 0), qmax["id"]))
        n_borde = sum(1 for c in naturales if c["toca_borde"])
        w("<div class='kpi'><b>%d</b><span>Cuencas que tocan el borde del DEM</span></div>" % n_borde)
    w("</div>")
    avisos = datos.get("avisos") or []
    for a in avisos:
        w("<div class='%s'>%s</div>" % ("malo" if a.get("grave") else "aviso", e(a["texto"])))

    # 2. Datos de entrada
    w("<h2>2. Datos de entrada</h2><table>")
    for k, v in p["tabla"]:
        w("<tr><td class='t'><b>%s</b></td><td class='t'>%s</td></tr>" % (e(str(k)), e(str(v))))
    w("</table>")

    # 3. Método
    w("<h2>3. Método</h2><ol>")
    for t in datos["metodo"]:
        w("<li>%s</li>" % e(t))
    w("</ol>")

    # 4. Salidas
    w("<h2>4. Salidas (exutorios)</h2>")
    if hay_via:
        w("<p>Las filas «con_via» corresponden al escenario con la vía como barrera: el terraplén se eleva salvo "
          "en las salidas y cada salida se reubica en la celda de mayor acumulación dentro del radio de ajuste "
          "(columna «Desplazamiento»).</p>")
    w("<table><tr><th>Id</th>" + col_esc + "<th>Progresiva</th><th>Origen</th><th>Desplazamiento (m)</th>"
      "<th>Área drenada (ha)</th><th>Cota (msnm)</th><th>Anidada en</th><th>Contiene</th></tr>")
    for c in cuencas:
        w("<tr><td>%d</td>" % c["id"] + esc(c) +
          "<td>%s</td><td class='t'>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
          "<td class='t'>%s</td></tr>"
          % (e(progresiva_km(c.get("progresiva"))), e(c["origen"]), _n(c.get("desplazamiento"), 1),
             _n(c["area_ha"], 1), _n(c["h_min"]), c["anidada_en"] or "-",
             e(", ".join(str(i) for i in c["contiene"]) or "-")))
    w("</table>")

    # 5. Parámetros geomorfológicos
    w("<h2>5. Parámetros geomorfológicos</h2>")
    w("<table><tr><th>Id</th>" + col_esc + "<th>A (km²)</th><th>P (km)</th><th>L (m)</th><th>Hmáx</th><th>Hmín</th>"
      "<th>ΔH (m)</th><th>S = ΔH/L</th><th>S 10–85</th><th>S cuenca</th><th>H media</th><th>Kc</th><th>Kf</th>"
      "<th>Depresiones</th><th>Vol. dep. (m³)</th><th>% área dep.</th><th>Borde</th></tr>")
    for c in cuencas:
        w("<tr><td>%d</td>" % c["id"] + esc(c) +
          "<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
          "<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%d</td><td>%s</td><td>%s</td><td>%s</td></tr>"
          % (_n(c["area_km2"], 4), _n(c["perimetro_km"], 3), _n(c["l_m"], 0), _n(c["h_max"]),
             _n(c["h_min"]), _n(c["dh"]), _n(c["s_l"], 4), _n(c["s_1085"], 4), _n(c["s_cuenca"], 4),
             _n(c["h_media"]), _n(c["kc"]), _n(c["kf"], 3), c["n_depresiones"], _n(c["vol_depresiones"], 0),
             _n(100.0 * c["frac_depresiones"], 1), "Sí" if c["toca_borde"] else "No"))
    w("</table>")

    # 6. Tc
    w("<h2>6. Tiempo de concentración (min)</h2>")
    nombres = datos["hidrologia"]["formulas_tc"]
    w("<table><tr><th>Id</th>" + col_esc + "".join("<th>%s</th>" % e(n) for n in nombres) +
      "<th>Adoptado</th><th>Criterio</th></tr>")
    for c in cuencas:
        w("<tr><td>%d</td>" % c["id"] + esc(c))
        for n in nombres:
            r = c["tc"][n]
            txt = _n(r["tc_min"], 1)
            if r.get("fuera_rango"):
                txt = "<span class='fuera' title='%s'>%s*</span>" % (e(r["fuera_rango"]), txt)
            w("<td>%s</td>" % txt)
        w("<td><b>%s</b></td><td class='t'>%s</td></tr>" % (_n(c["tc_adoptado_min"], 1), e(c["tc_criterio"])))
    w("</table>")
    w("<p><small>* Fuera del rango de calibración de la fórmula (pasa el ratón para ver el motivo). "
      "Tc mínimo aplicado: %s min.</small></p>" % _n(p["tc_min"], 0))

    # 7. Caudales
    w("<h2>7. Lluvia, escorrentía y caudal de diseño</h2>")
    h = datos["hidrologia"]
    for t in h["texto"]:
        w("<p>%s</p>" % e(t))
    w("<table><tr><th>Id</th>" + col_esc + "<th>A (km²)</th><th>Tc (min)</th><th>CN</th><th>Tr (años)</th>"
      "<th>Pd (mm)</th><th>P24 (mm)</th><th>I (mm/h)</th><th>C Témez</th><th>Q racional (m³/s)</th><th>K</th>"
      "<th>Q Témez (m³/s)</th><th>Q adoptado</th></tr>")
    for c in cuencas:
        for tr in trs:
            q = c["q"][tr]
            w("<tr><td>%d</td>" % c["id"] + esc(c) +
              "<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
              "<td>%s</td><td>%s</td><td><b>%s</b></td></tr>"
              % (_n(c["area_km2"], 4), _n(c["tc_adoptado_min"], 1), _n(c["cn"], 1), _n(tr, 0), _n(q["pd"], 1), _n(q["p24"], 1), _n(q["i"], 1),
                 _n(q["c"], 3), _n(q["q_racional"], 3), _n(q["k"], 3), _n(q["q_temez"], 3), _n(q["q_adoptado"], 3)))
    w("</table>")

    # 8. Limitaciones
    w("<h2>8. Advertencias y limitaciones</h2><ul>")
    for t in datos["limitaciones"]:
        w("<li>%s</li>" % e(t))
    w("</ul>")
    w("<h2>9. Texto sugerido para la tesis</h2><div class='cita'>%s</div>" % e(datos["texto_tesis"]))
    w("</body></html>")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(out))

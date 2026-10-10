# -*- coding: utf-8 -*-
# Complemento QGIS «Exutorios Viales»
# Copyright (C) 2026 Jose Ospina
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version. See the LICENSE file for details.
"""
Red de drenaje sobre el grafo D8 (solo numpy).

Todo trabaja con índices planos del array acolchado que devuelve
acondicionar.acondicionar(): `recv[c]` es el receptor de la celda c,
SALIDA (-1) si drena fuera del DEM.

- Orden topológico por «oleadas» (algoritmo de Kahn vectorizado): todas las
  celdas sin aportes pendientes se procesan a la vez. Sirve para la
  acumulación, la distancia de flujo y la etiqueta de cuencas en O(N).
- Acumulación D8 y, opcional, MFD de Freeman (1991) para visualizar.
- Red de cauces por umbral de área, vectorizada de confluencia a
  confluencia con orden de Strahler (1957).
- Cruces exactos cauce–eje, ajuste de puntos a la celda de mayor
  acumulación, cuencas (anidadas), recorrido más largo y parámetros
  geomorfológicos.
"""

import math

import numpy as np

from .acondicionar import SALIDA, VECINOS, DIAGONAL, offsets, etiquetar, pendiente_horn
from . import herramientas as h


# ---------------------------------------------------------------------------
# Orden topológico y acumulación
# ---------------------------------------------------------------------------

def oleadas(recv, valido):
    """Lista de arrays de celdas; cada oleada solo depende de las anteriores.

    Lanza RuntimeError si el grafo tiene ciclos o celdas sin receptor."""
    N = recv.size
    tiene = valido & (recv >= 0)
    indeg = np.bincount(recv[tiene], minlength=N)
    frente = np.flatnonzero(valido & (indeg == 0))
    lista = []
    procesadas = 0
    while frente.size:
        lista.append(frente)
        procesadas += frente.size
        r = recv[frente]
        r = r[r >= 0]
        if r.size == 0:
            break
        u, cnt = np.unique(r, return_counts=True)
        indeg[u] -= cnt
        frente = u[indeg[u] == 0]
    if procesadas != int(valido.sum()):
        raise RuntimeError("El grafo de flujo tiene %d celdas que no drenan (ciclos o celdas sin salida)."
                           % (int(valido.sum()) - procesadas))
    return lista


def acumulacion(recv, oleadas_, N, pesos=None):
    """Número de celdas (o suma de pesos) que drenan por cada celda, incluida ella."""
    acc = np.zeros(N, dtype=float)
    if pesos is None:
        for w in oleadas_:
            acc[w] += 1.0
    else:
        for w in oleadas_:
            acc[w] += pesos[w]
    for w in oleadas_:
        r = recv[w]
        m = r >= 0
        np.add.at(acc, r[m], acc[w][m])
    return acc


def paso_celda(recv, C, celda):
    """Longitud del paso de cada celda hacia su receptor (celda o celda·√2)."""
    idx = np.arange(recv.size, dtype=np.int64)
    d = recv - idx
    diag = (np.abs(d) == C - 1) | (np.abs(d) == C + 1)
    return np.where(diag, celda * math.sqrt(2.0), celda)


def distancia_flujo(recv, oleadas_, C, celda):
    """Distancia de flujo aguas abajo hasta la salida del DEM (m)."""
    dist = np.zeros(recv.size, dtype=float)
    paso = paso_celda(recv, C, celda)
    for w in reversed(oleadas_):
        r = recv[w]
        m = r >= 0
        dist[w[m]] = dist[r[m]] + paso[w[m]]
        dist[w[~m]] = paso[w[~m]]
    return dist


def acumulacion_mfd(zp, recv, valido, oleadas_d8, p=1.1):
    """Acumulación con flujo múltiple de Freeman (1991): la fracción hacia
    cada vecino más bajo es proporcional a (pendiente)^p, p = 1.1. En celdas
    sin vecino más bajo (planicies) se usa el receptor D8. Solo para
    visualización."""
    R, C = zp.shape
    N = R * C
    z = np.where(np.isfinite(zp), zp, np.nan).ravel()
    idx = np.flatnonzero(valido)
    offs = np.asarray(offsets(C), dtype=np.int64)
    dist = np.asarray([math.sqrt(2.0) if d else 1.0 for d in DIAGONAL])
    vec = idx[:, None] + offs[None, :]
    pend = (z[idx][:, None] - z[vec]) / dist[None, :]
    pend = np.where(np.isfinite(pend) & (pend > 0), pend, 0.0)
    peso = pend ** p
    suma = peso.sum(axis=1)
    usa_d8 = suma <= 0
    # aristas MFD
    src = np.repeat(idx, 8)
    dst = vec.ravel()
    frac = (peso / np.where(suma > 0, suma, 1.0)[:, None]).ravel()
    keep = frac > 0
    src, dst, frac = src[keep], dst[keep], frac[keep]
    # aristas D8 para las celdas sin descenso
    s2 = idx[usa_d8]
    d2 = recv[s2]
    m2 = d2 >= 0
    src = np.concatenate((src, s2[m2]))
    dst = np.concatenate((dst, d2[m2]))
    frac = np.concatenate((frac, np.ones(int(m2.sum()))))
    # Kahn sobre el multigrafo
    orden = np.argsort(src, kind="stable")
    src, dst, frac = src[orden], dst[orden], frac[orden]
    ptr = np.searchsorted(src, np.arange(N + 1))
    indeg = np.bincount(dst, minlength=N)
    acc = np.zeros(N)
    acc[idx] = 1.0
    frente = idx[indeg[idx] == 0]
    while frente.size:
        ini = ptr[frente]
        fin = ptr[frente + 1]
        cnt = fin - ini
        tot = int(cnt.sum())
        if tot == 0:
            break
        rep = np.repeat(np.arange(frente.size), cnt)
        e = ini[rep] + (np.arange(tot) - np.repeat(np.cumsum(cnt) - cnt, cnt))
        np.add.at(acc, dst[e], acc[src[e]] * frac[e])
        u, c = np.unique(dst[e], return_counts=True)
        indeg[u] -= c
        frente = u[indeg[u] == 0]
    return acc


# ---------------------------------------------------------------------------
# Red de cauces
# ---------------------------------------------------------------------------

def red_cauces(recv, acc, valido, umbral_celdas, cortar_en=()):
    """Segmentos de cauce de confluencia a confluencia con orden de Strahler.

    Devuelve (segmentos, cauce) donde cauce es la máscara plana de celdas de
    cauce y segmentos una lista de dicts: id, celdas (array), orden, acc_fin
    (celdas drenadas en el extremo aguas abajo), aguas_abajo (id del
    segmento siguiente o 0), fin_en_salida (bool).
    cortar_en: celdas (exutorios) donde los segmentos se parten."""
    N = recv.size
    cauce = valido & (acc >= umbral_celdas)
    idx = np.flatnonzero(cauce)
    if idx.size == 0:
        return [], cauce
    r = recv[idx]
    rs = r[(r >= 0)]
    rs = rs[cauce[rs]]
    n_up = np.bincount(rs, minlength=N)
    corte = np.zeros(N, dtype=bool)
    corte[np.asarray(list(cortar_en), dtype=np.int64)] = True
    inicio_m = (n_up[idx] == 0) | (n_up[idx] >= 2) | corte[idx]
    inicios = idx[inicio_m]
    recv_l = recv.tolist()
    cauce_l = cauce.tolist()
    nup_l = n_up.tolist()
    corte_l = corte.tolist()
    segmentos = []
    por_inicio = {}
    for s in inicios.tolist():
        celdas = [s]
        c = s
        termina = "fin"
        while True:
            rr = recv_l[c]
            if rr < 0 or not cauce_l[rr]:
                break
            celdas.append(rr)
            if nup_l[rr] >= 2 or corte_l[rr]:
                termina = "union"
                break
            c = rr
        seg = {"id": len(segmentos) + 1, "celdas": np.asarray(celdas, dtype=np.int64),
               "orden": 0, "aguas_abajo": 0, "termina": termina}
        segmentos.append(seg)
        por_inicio[s] = seg["id"]
    # enlaces y Strahler (orden creciente de acumulación en el inicio)
    entradas = {}
    for seg in segmentos:
        cel = seg["celdas"]
        fin = int(cel[-1])
        # área drenada: en el extremo propio del segmento, antes de la confluencia
        propio = int(cel[-2]) if (seg["termina"] == "union" and cel.size > 1) else fin
        seg["acc_fin"] = float(acc[propio])
        sig = por_inicio.get(fin, 0) if seg["termina"] == "union" else 0
        if sig == seg["id"]:
            sig = 0
        seg["aguas_abajo"] = sig
        if sig:
            entradas.setdefault(sig, []).append(seg["id"])
    por_id = {s["id"]: s for s in segmentos}
    for seg in sorted(segmentos, key=lambda s: acc[int(s["celdas"][0])]):
        ordenes = [por_id[i]["orden"] for i in entradas.get(seg["id"], [])]
        if not ordenes:
            seg["orden"] = 1
        else:
            mx = max(ordenes)
            seg["orden"] = mx + 1 if ordenes.count(mx) >= 2 else mx
    return segmentos, cauce


# ---------------------------------------------------------------------------
# Salidas (exutorios)
# ---------------------------------------------------------------------------

def _xy_celdas(celdas, C, gt):
    filas = celdas // C - 1
    cols = celdas % C - 1
    return h.xy_de_indices(filas, cols, gt)


def cruces_con_eje(segmentos, acc, C, gt, partes_eje, mascara_eje_p, tolerancia_m):
    """Cruces de la red de cauces con el eje.

    mascara_eje_p: máscara plana (acolchada) de las celdas del eje dilatada
    una celda, para descartar rápido los segmentos lejanos.
    Devuelve lista de dicts: celda, x, y, progresiva, acc, n_puntos,
    segmento. Los puntos de corte a menos de `tolerancia_m` de progresiva
    se agrupan en un solo cruce (celda de mayor acumulación)."""
    puntos = []
    for seg in segmentos:
        cel = seg["celdas"]
        if cel.size < 2 or not mascara_eje_p[cel].any():
            continue
        x, y = _xy_celdas(cel, C, gt)
        pl = np.column_stack((x, y))
        for it in h.intersecciones(pl, partes_eje):
            a = int(cel[it["i"]])
            b = int(cel[it["i"] + 1])
            f, c = h.celda_de_xy(it["x"], it["y"], gt)
            cont = (f + 1) * C + (c + 1)
            if cont == a or cont == b:
                celda = cont
            else:
                celda = b if it["t"] >= 0.5 else a
            puntos.append({"celda": celda, "x": it["x"], "y": it["y"], "progresiva": it["progresiva"],
                           "acc": float(acc[celda]), "segmento": seg["id"]})
    puntos.sort(key=lambda p: p["progresiva"])
    cruces = []
    grupo = []
    for p in puntos:
        if grupo and p["progresiva"] - grupo[-1]["progresiva"] > tolerancia_m:
            cruces.append(_fusionar_grupo(grupo))
            grupo = []
        grupo.append(p)
    if grupo:
        cruces.append(_fusionar_grupo(grupo))
    return cruces


def _fusionar_grupo(grupo):
    mejor = max(grupo, key=lambda p: p["acc"])
    out = dict(mejor)
    out["n_puntos"] = len(grupo)
    return out


def ajustar_punto(x, y, acc, valido, C, R, gt, radio_m):
    """Ajusta el punto a la celda válida de mayor acumulación dentro del radio.

    Devuelve (celda_acolchada, x_ajustado, y_ajustado, desplazamiento_m) o
    None si el punto cae fuera del DEM."""
    f, c = h.celda_de_xy(x, y, gt)
    filas, cols = R - 2, C - 2
    if not (0 <= f < filas and 0 <= c < cols):
        return None
    celda = min(abs(gt[1]), abs(gt[5]))
    n = int(math.ceil(radio_m / celda)) if radio_m > 0 else 0
    f0, f1 = max(f - n, 0), min(f + n + 1, filas)
    c0, c1 = max(c - n, 0), min(c + n + 1, cols)
    ff, cc = np.mgrid[f0:f1, c0:c1]
    xs, ys = h.xy_de_indices(ff, cc, gt)
    dentro = np.hypot(xs - x, ys - y) <= max(radio_m, 0.0) + 1e-9
    dentro |= (ff == f) & (cc == c)
    cel = (ff + 1) * C + (cc + 1)
    ok = dentro & valido[cel]
    if not ok.any():
        return None
    a = np.where(ok, acc[cel], -1.0)
    k = np.argmax(a)
    cf, cc_ = int(ff.ravel()[k]), int(cc.ravel()[k])
    xa, ya = h.xy_de_celda(cf, cc_, gt)
    return int(cel.ravel()[k]), xa, ya, float(math.hypot(xa - x, ya - y))


def fusionar_salidas(salidas, distancia_m):
    """Elimina salidas repetidas: si dos están a menos de `distancia_m`, se
    conserva la de origen «punto» (diseño) y, a igual origen, la de mayor
    acumulación. Devuelve la lista depurada (con «fusionada_con» en las
    descartadas) y la lista de descartadas."""
    orden = sorted(salidas, key=lambda s: (0 if s["origen"] == "punto" else 1, -s["acc"]))
    conservadas = []
    descartadas = []
    for s in orden:
        dup = None
        for k in conservadas:
            if s["celda"] == k["celda"] or math.hypot(s["x"] - k["x"], s["y"] - k["y"]) <= distancia_m:
                dup = k
                break
        if dup is None:
            conservadas.append(s)
        else:
            s["fusionada_con"] = dup["id"]
            dup.setdefault("fusiona", []).append(s["id"])
            descartadas.append(s)
    conservadas.sort(key=lambda s: (s.get("progresiva") if s.get("progresiva") is not None else 1e18, s["id"]))
    return conservadas, descartadas


def celdas_abrir_via(recv, acc, mascara_via, celda_salida, C, max_pasos=30):
    """Celdas del terraplén que hay que dejar a cota natural para que el cauce
    natural atraviese la vía en una salida: la propia salida, las celdas de
    la vía que recorre el flujo aguas abajo de ella y las que recorre el
    cauce principal (mayor acumulación) aguas arriba, más la celda de la vía
    más cercana. Devuelve un conjunto de índices acolchados."""
    abrir = {int(celda_salida)}
    offs = offsets(C)
    # aguas abajo
    c = int(celda_salida)
    entro = bool(mascara_via[c])
    for _ in range(max_pasos):
        r = int(recv[c])
        if r < 0:
            break
        if mascara_via[r]:
            abrir.add(r)
            entro = True
        elif entro:
            break
        c = r
    # aguas arriba por el cauce principal
    c = int(celda_salida)
    entro = bool(mascara_via[c])
    for _ in range(max_pasos):
        donantes = [c + o for o in offs if recv[c + o] == c]
        if not donantes:
            break
        d = max(donantes, key=lambda i: acc[i])
        if mascara_via[d]:
            abrir.add(int(d))
            entro = True
        elif entro:
            break
        c = int(d)
    # celda de la vía más cercana (por si la salida no toca la vía)
    via = np.flatnonzero(mascara_via)
    if via.size:
        f0, c0 = celda_salida // C, celda_salida % C
        k = int(np.argmin((via // C - f0) ** 2 + (via % C - c0) ** 2))
        abrir.add(int(via[k]))
    return abrir


# ---------------------------------------------------------------------------
# Cuencas
# ---------------------------------------------------------------------------

def etiquetar_cuencas(recv, oleadas_, celdas_salida):
    """Etiqueta de la primera salida que encuentra cada celda aguas abajo
    (partición). Devuelve (etiquetas planas int32, aguas_abajo) donde
    aguas_abajo[k] es la etiqueta de la salida siguiente de la salida k (0 =
    ninguna)."""
    lab = np.zeros(recv.size, dtype=np.int32)
    sal = np.asarray(celdas_salida, dtype=np.int64)
    lab[sal] = np.arange(1, sal.size + 1, dtype=np.int32)
    for w in reversed(oleadas_):
        r = recv[w]
        m = (lab[w] == 0) & (r >= 0)
        lab[w[m]] = lab[r[m]]
    aguas_abajo = np.zeros(sal.size + 1, dtype=np.int32)
    for k, c in enumerate(sal.tolist(), start=1):
        r = recv[c]
        aguas_abajo[k] = lab[r] if r >= 0 else 0
    return lab, aguas_abajo


def miembros_cuenca_total(aguas_abajo):
    """Para cada salida k, las etiquetas cuya cadena aguas abajo pasa por k
    (incluida k): dict k -> lista."""
    n = aguas_abajo.size - 1
    miembros = {k: [k] for k in range(1, n + 1)}
    for j in range(1, n + 1):
        a = int(aguas_abajo[j])
        visitados = set()
        while a and a not in visitados:
            visitados.add(a)
            miembros[a].append(j)
            a = int(aguas_abajo[a])
    return miembros


def recorrido_mas_largo(recv, dist, mascara_total, salida):
    """Celda más lejana, L (m) y camino (celdas) hasta la salida."""
    cel = np.flatnonzero(mascara_total)
    d = dist[cel] - dist[salida]
    k = int(np.argmax(d))
    lejana = int(cel[k])
    L = float(d[k])
    camino = [lejana]
    c = lejana
    recv_l = recv
    n = 0
    while c != salida and recv_l[c] >= 0 and n < recv.size:
        c = int(recv_l[c])
        camino.append(c)
        n += 1
    return lejana, L, np.asarray(camino, dtype=np.int64)


def perimetro_raster(mascara2d, celda):
    """Perímetro (m) del polígono ráster: aristas entre celdas dentro/fuera."""
    m = np.zeros((mascara2d.shape[0] + 2, mascara2d.shape[1] + 2), dtype=bool)
    m[1:-1, 1:-1] = mascara2d
    n = int((m[1:, :] != m[:-1, :]).sum() + (m[:, 1:] != m[:, :-1]).sum())
    return n * celda


def pendiente_10_85(camino, zp_orig, paso):
    """Pendiente 10–85 (m/m) del recorrido: cotas al 10 % y 85 % de la
    longitud medida desde la salida (Gray, 1961; método usado por el USGS).

    camino: celdas desde la más lejana hasta la salida. paso: longitud del
    paso de cada celda hacia su receptor."""
    if camino.size < 2:
        return float("nan")
    z = zp_orig.ravel()[camino]
    seg = paso[camino[:-1]]
    s_desde_lejana = np.concatenate(([0.0], np.cumsum(seg)))
    L = s_desde_lejana[-1]
    if L <= 0:
        return float("nan")
    s_desde_salida = L - s_desde_lejana
    orden = np.argsort(s_desde_salida)
    s = s_desde_salida[orden]
    zz = z[orden]
    ok = np.isfinite(zz)
    if ok.sum() < 2:
        return float("nan")
    z10 = float(np.interp(0.10 * L, s[ok], zz[ok]))
    z85 = float(np.interp(0.85 * L, s[ok], zz[ok]))
    return (z85 - z10) / (0.75 * L)


def parametros_cuenca(mascara_total, salida, camino, L, zp_orig, relleno, lab_dep, borde, pend, celda,
                      C):
    """Parámetros geomorfológicos de una cuenca (dict)."""
    R = zp_orig.shape[0]
    m2 = mascara_total.reshape(R, C)[1:-1, 1:-1]
    cel = np.flatnonzero(mascara_total)
    z = zp_orig.ravel()[cel]
    z = z[np.isfinite(z)]
    n = cel.size
    area_m2 = n * celda * celda
    P = perimetro_raster(m2, celda)
    h_min = float(zp_orig.ravel()[salida])
    h_max = float(z.max()) if z.size else float("nan")
    dh = h_max - h_min
    area_km2 = area_m2 / 1e6
    deps = np.unique(lab_dep[cel])
    deps = deps[deps > 0]
    rel = relleno[cel]
    s_cuenca = float(np.nanmean(pend.ravel()[cel])) if n else float("nan")
    return {
        "n_celdas": int(n), "area_m2": float(area_m2), "area_ha": float(area_m2 / 1e4),
        "area_km2": float(area_km2), "perimetro_m": float(P), "perimetro_km": float(P / 1000.0),
        "l_m": float(L), "h_max": h_max, "h_min": h_min, "dh": float(dh),
        "h_media": float(z.mean()) if z.size else float("nan"),
        "s_l": float(dh / L) if L > 0 else float("nan"),
        "s_cuenca": s_cuenca,
        "kc": float(0.28 * P / math.sqrt(area_m2)) if area_m2 > 0 else float("nan"),
        "kf": float(area_m2 / (L * L)) if L > 0 else float("nan"),
        "n_depresiones": int(deps.size),
        "vol_depresiones": float(rel.sum() * celda * celda),
        "frac_depresiones": float((rel > 0).sum() / n) if n else 0.0,
        "toca_borde": bool(borde[cel].any()),
    }


def celdas_borde(zp):
    """Máscara plana: celdas válidas con algún vecino inválido (borde del DEM
    o sin datos)."""
    R, C = zp.shape
    valido = np.isfinite(zp)
    v = np.zeros((R, C), dtype=bool)
    for dr, dc in VECINOS:
        v[1:-1, 1:-1] |= ~valido[1 + dr:R - 1 + dr, 1 + dc:C - 1 + dc]
    return (v & valido).ravel()


def analizar_cuencas(cond, salidas, celda, gt, progreso=None, cancelado=None):
    """Delimita las cuencas de todas las salidas y calcula sus parámetros.

    cond: dict de acondicionar.acondicionar(); salidas: lista de dicts con
    «celda» (índice acolchado) e «id» consecutivo desde 1.
    Devuelve dict con etiquetas (partición), aguas_abajo, miembros, y por
    salida: mascara_total, parámetros, camino (celdas), lejana."""
    recv = cond["recv"]
    zp = cond["zp"]
    R, C = zp.shape
    valido = np.isfinite(zp).ravel()
    ol = cond.get("oleadas")
    if ol is None:
        ol = oleadas(recv, valido)
        cond["oleadas"] = ol
    dist = cond.get("dist")
    if dist is None:
        dist = distancia_flujo(recv, ol, C, celda)
        cond["dist"] = dist
    paso = paso_celda(recv, C, celda)
    cel_sal = [s["celda"] for s in salidas]
    lab, aguas_abajo = etiquetar_cuencas(recv, ol, cel_sal)
    miembros = miembros_cuenca_total(aguas_abajo)
    lab_dep2, _ = etiquetar(cond["depresion"][1:-1, 1:-1])
    lab_dep = np.zeros((R, C), dtype=np.int32)
    lab_dep[1:-1, 1:-1] = lab_dep2
    lab_dep = lab_dep.ravel()
    borde = celdas_borde(zp)
    pend = pendiente_horn(cond["original"], celda)
    resultados = []
    for k, s in enumerate(salidas, start=1):
        if cancelado is not None and cancelado():
            raise RuntimeError("Proceso cancelado por el usuario.")
        total = np.isin(lab, miembros[k])
        lejana, L, camino = recorrido_mas_largo(recv, dist, total, s["celda"])
        par = parametros_cuenca(total, s["celda"], camino, L, cond["original"], cond["relleno"].ravel(),
                                lab_dep, borde, pend, celda, C)
        par["s_1085"] = pendiente_10_85(camino, cond["original"], paso)
        par["anidada_en"] = int(aguas_abajo[k])
        par["contiene"] = sorted(i for i in miembros[k] if i != k)
        par["area_propia_ha"] = float((lab == k).sum() * celda * celda / 1e4)
        resultados.append({"id": k, "mascara_total": total, "parametros": par, "camino": camino,
                           "lejana": lejana})
        if progreso is not None:
            progreso((k) / max(len(salidas), 1))
    return {"etiquetas": lab, "aguas_abajo": aguas_abajo, "miembros": miembros, "cuencas": resultados,
            "dist": dist, "oleadas": ol}

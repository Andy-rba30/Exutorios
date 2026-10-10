# -*- coding: utf-8 -*-
# Complemento QGIS «Exutorios Viales»
# Copyright (C) 2026 Jose Ospina
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version. See the LICENSE file for details.
"""
Acondicionamiento hidrológico del DEM (solo numpy y biblioteca estándar).

1. Relleno de depresiones con Priority-Flood (Barnes, Lehman y Mulla, 2014a:
   «Priority-flood: An optimal depression-filling and watershed-labeling
   algorithm for digital elevation models», Computers & Geosciences 62,
   117-127).
2. Opcional: apertura de depresiones («breaching») híbrida, siguiendo la idea
   de Lindsay (2016, «Efficient hybrid breaching-filling sink removal methods
   for flow path enforcement in digital elevation models», Hydrological
   Processes 30, 846-857): desde cada fosa se busca el camino de menor costo
   hasta una celda más baja, con longitud y profundidad máximas; lo que no
   se puede abrir se rellena.
3. Direcciones D8 (O'Callaghan y Mark, 1984) sobre el DEM acondicionado.
4. Zonas planas resueltas con el gradiente superpuesto de Barnes, Lehman y
   Mulla (2014b, «An efficient assignment of drainage direction over flat
   surfaces in raster digital elevation models», Computers & Geosciences 62,
   128-135): un gradiente que se aleja del terreno alto más otro que se
   acerca a las salidas de la planicie.

Convenciones:
- Los arrays internos van «acolchados» con un borde de una celda inválida,
  de modo que todo vecino existe y no hay comprobaciones de límites.
- Receptor de una celda: índice plano de la celda hacia la que drena.
  SALIDA (-1) = drena fuera del DEM (borde o celda sin datos).
  SIN_FLUJO (-2) = no tiene salida (solo si el DEM no pudo acondicionarse).
"""

import heapq
import math
from collections import deque

import numpy as np

SALIDA = -1
SIN_FLUJO = -2
EPS = 1e-9

# Vecinos D8: primero los ortogonales (para que los empates prefieran
# el paso recto al diagonal), luego los diagonales.
VECINOS = ((-1, 0), (0, -1), (0, 1), (1, 0), (-1, -1), (-1, 1), (1, -1), (1, 1))
DIAGONAL = (False, False, False, False, True, True, True, True)


def acolchar(arr, valor=np.nan):
    """Añade un borde de una celda con `valor`."""
    filas, cols = arr.shape
    p = np.full((filas + 2, cols + 2), valor, dtype=arr.dtype if np.issubdtype(arr.dtype, np.floating)
                else float)
    p[1:-1, 1:-1] = arr
    return p


def desacolchar(arr):
    return arr[1:-1, 1:-1]


def offsets(C):
    """Desplazamientos planos de los 8 vecinos en un array de C columnas."""
    return [dr * C + dc for dr, dc in VECINOS]


# ---------------------------------------------------------------------------
# Priority-Flood
# ---------------------------------------------------------------------------

def priority_flood(zp, progreso=None, cancelado=None):
    """Relleno de depresiones Priority-Flood sobre el DEM acolchado.

    zp: array 2D float con NaN en celdas inválidas (incluido el borde).
    Devuelve el DEM rellenado (array 2D float, NaN donde no hay dato).
    Toda celda válida queda con un camino no ascendente hasta una celda
    vecina de una inválida (borde o sin datos)."""
    R, C = zp.shape
    N = R * C
    zf = zp.ravel()
    invalido = ~np.isfinite(zf)
    z = np.where(invalido, 0.0, zf).tolist()
    filled = list(z)
    closed = bytearray(invalido.astype(np.uint8).tobytes())

    inv2 = invalido.reshape(R, C)
    vecino_inv = np.zeros((R, C), dtype=bool)
    for dr, dc in VECINOS:
        vecino_inv[1:-1, 1:-1] |= inv2[1 + dr:R - 1 + dr, 1 + dc:C - 1 + dc]
    semillas = np.flatnonzero((vecino_inv & ~inv2).ravel()).tolist()

    heap = [(z[i], i) for i in semillas]
    heapq.heapify(heap)
    for i in semillas:
        closed[i] = 1

    offs = offsets(C)
    pit = deque()
    total = N - int(invalido.sum())
    paso = max(total // 50, 1)
    cuenta = 0
    heappop = heapq.heappop
    heappush = heapq.heappush
    pit_pop = pit.popleft
    pit_append = pit.append

    while heap or pit:
        if pit:
            c = pit_pop()
            cz = filled[c]
        else:
            cz, c = heappop(heap)
        for o in offs:
            n = c + o
            if closed[n]:
                continue
            closed[n] = 1
            zn = z[n]
            if zn <= cz:
                filled[n] = cz
                pit_append(n)
            else:
                heappush(heap, (zn, n))
        cuenta += 1
        if cuenta % paso == 0:
            if cancelado is not None and cancelado():
                raise RuntimeError("Proceso cancelado por el usuario.")
            if progreso is not None:
                progreso(cuenta / total)
    out = np.asarray(filled, dtype=float).reshape(R, C)
    out[inv2] = np.nan
    return out


# ---------------------------------------------------------------------------
# Etiquetado de componentes conexas (8 vecinos)
# ---------------------------------------------------------------------------

def etiquetar(mascara):
    """Etiqueta grupos conectados (8 vecinos). Usa scipy si está disponible.

    Devuelve (etiquetas int32, número de grupos)."""
    m = np.asarray(mascara, dtype=bool)
    if not m.any():
        return np.zeros(m.shape, dtype=np.int32), 0
    try:
        from scipy import ndimage
        lab, n = ndimage.label(m, structure=np.ones((3, 3), dtype=int))
        return lab.astype(np.int32), int(n)
    except Exception:
        pass
    # Sin scipy: BFS por frentes con numpy sobre el array acolchado
    R, C = m.shape[0] + 2, m.shape[1] + 2
    mp = np.zeros((R, C), dtype=bool)
    mp[1:-1, 1:-1] = m
    mf = mp.ravel()
    lab = np.zeros(R * C, dtype=np.int32)
    offs = np.asarray(offsets(C), dtype=np.int64)
    pendientes = np.flatnonzero(mf)
    n = 0
    pos = 0
    while pos < pendientes.size:
        semilla = pendientes[pos]
        pos += 1
        if lab[semilla]:
            continue
        n += 1
        frente = np.asarray([semilla], dtype=np.int64)
        lab[frente] = n
        while frente.size:
            v = (frente[:, None] + offs[None, :]).ravel()
            v = v[mf[v] & (lab[v] == 0)]
            if v.size == 0:
                break
            v = np.unique(v)
            lab[v] = n
            frente = v
    return lab.reshape(R, C)[1:-1, 1:-1].copy(), n


# ---------------------------------------------------------------------------
# Breaching híbrido (Lindsay, 2016)
# ---------------------------------------------------------------------------

def breaching(zp, max_longitud=50, max_profundidad=None, progreso=None, cancelado=None):
    """Abre un canal desde la fosa de cada depresión hasta terreno más bajo.

    zp: DEM acolchado (NaN = inválido). Devuelve (dem_modificado, n_abiertas,
    n_no_abiertas). Las depresiones que no se pueden abrir dentro de los
    límites quedan para el relleno posterior.

    Costo de un camino = suma de los rebajes necesarios (z_celda - z_fosa)
    a lo largo de él, es decir, el volumen de corte por celda; el camino se
    busca con Dijkstra limitado a `max_longitud` pasos (Lindsay, 2016,
    variante «constrained breaching»)."""
    R, C = zp.shape
    rell = priority_flood(zp, progreso=progreso, cancelado=cancelado)
    dep = np.isfinite(zp) & (rell > zp + EPS)
    if not dep.any():
        return zp.copy(), 0, 0
    lab, n = etiquetar(dep[1:-1, 1:-1])
    labp = np.zeros((R, C), dtype=np.int32)
    labp[1:-1, 1:-1] = lab
    z = zp.copy()
    zf = z.ravel()
    labf = labp.ravel()
    valido = np.isfinite(zf)
    offs = offsets(C)
    # fosa de cada depresión: celda más baja
    idx = np.flatnonzero(labf > 0)
    orden = np.lexsort((zf[idx], labf[idx]))
    idx_ord = idx[orden]
    primero = np.searchsorted(labf[idx_ord], np.arange(1, n + 1))
    fosas = idx_ord[primero]
    # las fosas más altas primero: al abrirlas pueden vaciar en otra más baja
    fosas = fosas[np.argsort(-zf[fosas])]
    abiertas = 0
    no_abiertas = 0
    z_l = zf.tolist()
    val_l = valido.tolist()
    for k, f in enumerate(fosas.tolist()):
        if cancelado is not None and k % 50 == 0 and cancelado():
            raise RuntimeError("Proceso cancelado por el usuario.")
        zf0 = z_l[f]
        # ¿sigue siendo una fosa? (una apertura anterior pudo vaciarla)
        if any(val_l[f + o] and z_l[f + o] < zf0 for o in offs) or \
                any(not val_l[f + o] for o in offs):
            continue
        costo = {f: 0.0}
        pasos = {f: 0}
        padre = {}
        heap = [(0.0, 0, f)]
        objetivo = None
        while heap:
            c, p, u = heapq.heappop(heap)
            if c > costo.get(u, math.inf):
                continue
            if u != f and (not val_l[u] or z_l[u] < zf0):
                objetivo = u
                break
            if p >= max_longitud:
                continue
            for o in offs:
                v = u + o
                if not val_l[v]:
                    # salir del DEM es una salida válida (costo del propio paso)
                    nc = c
                else:
                    corte = z_l[v] - zf0
                    if max_profundidad is not None and corte > max_profundidad:
                        continue
                    nc = c + max(corte, 0.0)
                if nc < costo.get(v, math.inf):
                    costo[v] = nc
                    pasos[v] = p + 1
                    padre[v] = u
                    heapq.heappush(heap, (nc, p + 1, v))
        if objetivo is None:
            no_abiertas += 1
            continue
        # camino desde la fosa hasta el objetivo
        camino = []
        u = objetivo
        while u != f:
            camino.append(u)
            u = padre[u]
        camino.reverse()           # fosa -> ... -> objetivo (excluye la fosa)
        interior = camino[:-1]     # celdas a rebajar
        z_obj = z_l[objetivo] if val_l[objetivo] else zf0 - 1.0
        m = len(interior) + 1
        for i, cel in enumerate(interior, start=1):
            nuevo = zf0 + (z_obj - zf0) * i / m
            if nuevo < z_l[cel]:
                z_l[cel] = nuevo
        abiertas += 1
        if progreso is not None and k % 20 == 0:
            progreso(k / max(len(fosas), 1))
    out = np.asarray(z_l, dtype=float).reshape(R, C)
    out[~valido.reshape(R, C)] = np.nan
    return out, abiertas, no_abiertas


# ---------------------------------------------------------------------------
# Direcciones D8 y zonas planas
# ---------------------------------------------------------------------------

def _d8_estricto(zp):
    """Receptor D8 de máxima pendiente (solo descensos estrictos).

    Una celda sin vecino válido más bajo pero con algún vecino inválido
    (borde del DEM o sin datos) drena fuera: SALIDA. Si tiene un vecino
    válido más bajo, drena hacia él aunque esté en el borde (el borde del
    DEM no es una divisoria).
    Devuelve array plano int64 con el índice del receptor, SALIDA o SIN_FLUJO."""
    R, C = zp.shape
    valido = np.isfinite(zp)
    z = np.where(valido, zp, 0.0)
    mejor = np.zeros((R, C), dtype=float)
    recv = np.full((R, C), SIN_FLUJO, dtype=np.int64)
    idx = np.arange(R * C, dtype=np.int64).reshape(R, C)
    zi = z[1:-1, 1:-1]
    vi = valido[1:-1, 1:-1]
    vecino_inv = np.zeros((R - 2, C - 2), dtype=bool)
    for (dr, dc), diag in zip(VECINOS, DIAGONAL):
        zn = z[1 + dr:R - 1 + dr, 1 + dc:C - 1 + dc]
        vn = valido[1 + dr:R - 1 + dr, 1 + dc:C - 1 + dc]
        vecino_inv |= ~vn
        pend = (zi - zn) / (math.sqrt(2.0) if diag else 1.0)
        pend = np.where(vn, pend, -np.inf)
        mejora = vi & (pend > mejor[1:-1, 1:-1])
        mejor[1:-1, 1:-1] = np.where(mejora, pend, mejor[1:-1, 1:-1])
        recv[1:-1, 1:-1] = np.where(mejora, idx[1 + dr:R - 1 + dr, 1 + dc:C - 1 + dc], recv[1:-1, 1:-1])
    sale = vi & (mejor[1:-1, 1:-1] <= 0) & vecino_inv
    recv[1:-1, 1:-1] = np.where(sale, SALIDA, recv[1:-1, 1:-1])
    recv[~valido] = SIN_FLUJO
    return recv.ravel()


def _distancia_octil(semillas, dentro, offs, costos, z, inicial=None):
    """Distancia mínima (pasos ortogonales = 1, diagonales = √2) desde las
    semillas a través de las celdas `dentro` (máscara plana) de la misma cota
    `z` que la celda de origen, por relajación vectorizada con frente
    (Bellman-Ford con frontera): cada ronda propaga solo desde las celdas
    que mejoraron. Devuelve array float (inf = no alcanzada). Las semillas
    valen `inicial` (0 por defecto)."""
    dist = np.full(dentro.size, np.inf)
    frente = np.unique(np.asarray(semillas, dtype=np.int64))
    if frente.size == 0:
        return dist
    dist[frente] = 0.0 if inicial is None else inicial
    while frente.size:
        nb = (frente[:, None] + offs[None, :]).ravel()
        cand = (dist[frente][:, None] + costos[None, :]).ravel()
        zsrc = np.repeat(z[frente], offs.size)
        ok = dentro[nb] & (z[nb] == zsrc) & (cand < dist[nb] - 1e-9)
        nb = nb[ok]
        cand = cand[ok]
        if nb.size == 0:
            break
        np.minimum.at(dist, nb, cand)
        # vuelven al frente las celdas cuyo valor quedó fijado por esta ronda
        mejorado = dist[nb] >= cand - 1e-12
        frente = np.unique(nb[mejorado])
    return dist


def media_movil(zp, radio):
    """Media móvil de (2·radio+1)² celdas ignorando NaN (sumas acumuladas)."""
    z = np.where(np.isfinite(zp), zp, 0.0)
    w = np.isfinite(zp).astype(float)
    k = 2 * radio + 1

    def caja(a):
        c = np.cumsum(np.cumsum(np.pad(a, ((1, 0), (1, 0))), axis=0), axis=1)
        R, C = a.shape
        out = np.zeros_like(a)
        # ventana recortada en los bordes
        r0 = np.clip(np.arange(R) - radio, 0, R)
        r1 = np.clip(np.arange(R) + radio + 1, 0, R)
        c0 = np.clip(np.arange(C) - radio, 0, C)
        c1 = np.clip(np.arange(C) + radio + 1, 0, C)
        out = (c[r1][:, c1] - c[r0][:, c1] - c[r1][:, c0] + c[r0][:, c0])
        return out

    s = caja(z)
    n = caja(w)
    out = np.where(n > 0, s / np.maximum(n, 1), np.nan)
    return np.where(np.isfinite(zp), out, np.nan)


def resolver_planos(zp, recv, z_desempate=None):
    """Asigna receptor a las celdas sin flujo de las planicies (Barnes 2014b).

    zp: DEM acolchado rellenado; recv: receptores del D8 estricto (se
    modifica una copia). z_desempate: superficie suavizada (acolchada) para
    desempatar entre vecinos con la misma máscara: se elige el de mayor
    descenso en esa superficie, lo que evita el sesgo a 45° de los empates
    en las terrazas de los DEM de cotas enteras. Devuelve (recv, n_sin_salida)."""
    R, C = zp.shape
    recv = recv.copy()
    z = np.where(np.isfinite(zp), zp, np.nan).ravel()
    valido = np.isfinite(z)
    sin_flujo = recv == SIN_FLUJO
    sin_flujo &= valido
    if not sin_flujo.any():
        return recv, 0
    offs = np.asarray(offsets(C), dtype=np.int64)
    con_flujo = valido & ~sin_flujo

    planas = np.flatnonzero(sin_flujo)
    vec = planas[:, None] + offs[None, :]
    zp_ = z[planas][:, None]
    # bordes altos: celdas planas con algún vecino válido más alto
    alto = (valido[vec] & (z[vec] > zp_)).any(axis=1)
    bordes_altos = planas[alto]
    # bordes bajos (semillas): celdas CON flujo adyacentes a una plana de igual cota
    bajo = (con_flujo[vec] & (z[vec] == zp_))
    semillas = np.unique(vec[bajo])

    costos = np.asarray([math.sqrt(2.0) if d else 1.0 for d in DIAGONAL])
    # gradiente que se aleja del terreno alto: distancia desde los bordes altos
    # (los bordes altos valen 1, como en Barnes)
    lejos = _distancia_octil(bordes_altos, sin_flujo, offs, costos, z, inicial=1.0)
    lejos = np.where(np.isfinite(lejos), lejos, 0.0)
    altura = float(lejos.max()) if lejos.size else 0.0
    # gradiente hacia las salidas: distancia desde las semillas (celdas con
    # flujo de igual cota), que valen 1; combinado como en Barnes:
    # máscara = (altura − lejos) + 2·hacia
    hacia = _distancia_octil(semillas, sin_flujo | np.isin(np.arange(z.size), semillas), offs, costos, z,
                             inicial=1.0)
    mascara = np.where(np.isfinite(hacia), (altura - lejos) + 2.0 * hacia, 0.0)
    mascara[semillas] = 2.0

    # D8 sobre la máscara. Cualquier vecino de igual cota con máscara menor
    # que la propia garantiza un camino acíclico hasta una semilla; entre
    # ellos se prefiere el de mayor descenso en la superficie suavizada (la
    # dirección real del terreno), porque la máscara de Barnes, construida
    # con distancias «de tablero» (8 vecinos), sesga el flujo hacia las
    # diagonales cuando el borde de la terraza está inclinado. Sin superficie
    # de desempate se toma el vecino de máscara mínima (ortogonales primero).
    cand = (valido[vec] & (z[vec] == zp_) & (mascara[vec] > 0))
    val = np.where(cand, mascara[vec], np.inf)
    minimo = val.min(axis=1)
    propio = mascara[planas]
    if z_desempate is not None:
        zs = np.where(np.isfinite(z_desempate), z_desempate, np.inf).ravel()
        dist = np.asarray([math.sqrt(2.0) if d else 1.0 for d in DIAGONAL])
        pend = (zs[planas][:, None] - zs[vec]) / dist[None, :]
        menor = cand & (val < propio[:, None])
        pend = np.where(menor, pend, -np.inf)
        k = np.argmax(pend, axis=1)
        # si la superficie suavizada no distingue (todo igual), máscara mínima
        indistinto = np.isfinite(pend).sum(axis=1) == 0
        k_min = np.argmax(cand & (val == minimo[:, None]), axis=1)
        k = np.where(indistinto, k_min, k)
    else:
        k = np.argmax(cand & (val == minimo[:, None]), axis=1)
    ok = (minimo < propio) & (propio > 0)
    recv[planas[ok]] = vec[np.arange(planas.size), k][ok]
    n_sin_salida = int((~ok).sum())
    return recv, n_sin_salida


def acondicionar(dem, validos, metodo="relleno", max_longitud=50, max_profundidad=None,
                 progreso=None, cancelado=None, radio_desempate=4):
    """Acondiciona el DEM y calcula los receptores D8.

    dem: array 2D float (sin acolchar); validos: array 2D bool.
    metodo: «relleno» (Priority-Flood) o «breaching» (apertura + relleno).
    Devuelve dict con:
      zp        DEM acondicionado acolchado (NaN fuera)
      recv      receptor por celda (índice plano acolchado), SALIDA o SIN_FLUJO
      forma     (R, C) acolchada
      n_sin_salida  celdas válidas sin receptor (debe ser 0)
      depresion (R, C) bool: celdas que el relleno elevó sobre el terreno original
      relleno   (R, C) float: altura de relleno (acondicionado - original), 0 si no
      breaching (abiertas, no_abiertas) si se usó
    radio_desempate: radio (celdas) de la media móvil usada para desempatar
    direcciones en las planicies (0 = sin desempate, orden fijo de vecinos).
    """
    zp = acolchar(np.where(validos, dem, np.nan).astype(float))

    def prog(f, a, b):
        if progreso is not None:
            progreso(a + (b - a) * f)

    info = {}
    base = zp
    if metodo == "breaching":
        base, ab, nab = breaching(zp, max_longitud, max_profundidad,
                                  progreso=lambda f: prog(f, 0.0, 0.45), cancelado=cancelado)
        info["breaching"] = (ab, nab)
        rell = priority_flood(base, progreso=lambda f: prog(f, 0.45, 0.8), cancelado=cancelado)
    else:
        rell = priority_flood(zp, progreso=lambda f: prog(f, 0.0, 0.8), cancelado=cancelado)
    recv = _d8_estricto(rell)
    prog(1.0, 0.8, 0.9)
    z_des = media_movil(rell, radio_desempate) if radio_desempate and radio_desempate > 0 else None
    recv, n_sin = resolver_planos(rell, recv, z_des)
    prog(1.0, 0.9, 1.0)
    relleno = np.where(np.isfinite(zp), rell - zp, 0.0)
    relleno = np.where(np.isfinite(relleno), relleno, 0.0)
    info.update({
        "zp": rell, "recv": recv, "forma": rell.shape, "n_sin_salida": n_sin,
        "depresion": relleno > EPS, "relleno": relleno, "original": zp,
    })
    return info


# ---------------------------------------------------------------------------
# Utilidades sobre el DEM
# ---------------------------------------------------------------------------

def pendiente_horn(zp, celda):
    """Pendiente (m/m) por celda con el operador de Horn (1981), como en
    GDAL/ArcGIS. zp acolchado; vecinos NaN se sustituyen por la celda central."""
    R, C = zp.shape
    z = zp.copy()
    centro = z[1:-1, 1:-1]
    def v(dr, dc):
        n = z[1 + dr:R - 1 + dr, 1 + dc:C - 1 + dc]
        return np.where(np.isfinite(n), n, centro)
    a, b, c = v(-1, -1), v(-1, 0), v(-1, 1)
    d, f = v(0, -1), v(0, 1)
    g, h, i = v(1, -1), v(1, 0), v(1, 1)
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8.0 * celda)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8.0 * celda)
    s = np.sqrt(dzdx ** 2 + dzdy ** 2)
    out = np.full((R, C), np.nan)
    out[1:-1, 1:-1] = np.where(np.isfinite(centro), s, np.nan)
    return out


def suavizar_3x3(dem, validos):
    """Media móvil 3×3 ignorando celdas sin dato (opción avanzada)."""
    zp = acolchar(np.where(validos, dem, np.nan).astype(float))
    R, C = zp.shape
    suma = np.zeros((R - 2, C - 2))
    cuenta = np.zeros((R - 2, C - 2))
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            n = zp[1 + dr:R - 1 + dr, 1 + dc:C - 1 + dc]
            ok = np.isfinite(n)
            suma += np.where(ok, n, 0.0)
            cuenta += ok
    out = np.where(cuenta > 0, suma / np.maximum(cuenta, 1), np.nan)
    return np.where(validos, out, np.nan)

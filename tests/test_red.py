# -*- coding: utf-8 -*-
"""Pruebas de la red de drenaje y las cuencas con DEM sintéticos."""
import math

import numpy as np
import pytest

from exutorios_viales import acondicionar as ac, red, herramientas as h

CELDA = 10.0
GT = (0.0, CELDA, 0.0, 1000.0, 0.0, -CELDA)


def valle_v(n=100, long_=0.1, lat=1.0):
    """Valle en V que baja hacia el sur: pendiente longitudinal `long_` m/celda y
    lateral `lat` m/celda (con lat >> long_ el agua baja recto al fondo)."""
    yy, xx = np.mgrid[0:n, 0:n]
    return 100 + (n - 1 - yy) * long_ + lat * np.abs(xx - n // 2)


def preparar(dem, **kw):
    cond = ac.acondicionar(dem, np.ones_like(dem, bool), **kw)
    R, C = cond["forma"]
    valido = np.isfinite(cond["zp"]).ravel()
    cond["oleadas"] = red.oleadas(cond["recv"], valido)
    cond["acc"] = red.acumulacion(cond["recv"], cond["oleadas"], R * C)
    return cond, valido


def celda(f, c, C):
    return (f + 1) * C + (c + 1)


def test_acumulacion_y_cuenca_en_valle_v():
    dem = valle_v()
    cond, valido = preparar(dem)
    R, C = cond["forma"]
    sal = celda(70, 50, C)
    # todo lo que está en las filas 0..70 drena al fondo del valle en la fila 70
    assert cond["acc"][sal] == 71 * 100
    res = red.analizar_cuencas(cond, [{"id": 1, "celda": sal}], CELDA, GT)
    p = res["cuencas"][0]["parametros"]
    assert p["n_celdas"] == 7100
    assert p["area_ha"] == pytest.approx(71.0)
    # L: desde la esquina (0,0): 50 celdas rectas al fondo + 70 por el valle
    assert p["l_m"] == pytest.approx(120 * CELDA)
    assert p["h_min"] == pytest.approx(dem[70, 50])
    assert p["h_max"] == pytest.approx(dem[0, 0])
    assert p["perimetro_m"] == pytest.approx(2 * (71 + 100) * CELDA)
    assert p["kc"] == pytest.approx(0.28 * p["perimetro_m"] / math.sqrt(p["area_m2"]))
    assert p["kf"] == pytest.approx(p["area_m2"] / p["l_m"] ** 2)
    assert p["toca_borde"]
    assert p["n_depresiones"] == 0
    # recorrido: empieza en una esquina superior y termina en la salida
    camino = res["cuencas"][0]["camino"]
    assert camino[-1] == sal
    assert camino[0] // C - 1 == 0 and (camino[0] % C - 1) in (0, 99)


def test_cruce_con_eje_y_progresiva_con_partes():
    dem = valle_v()
    cond, valido = preparar(dem)
    R, C = cond["forma"]
    segs, _ = red.red_cauces(cond["recv"], cond["acc"], valido, 500)
    assert all(s["orden"] >= 1 for s in segs)
    # eje en dos partes: la primera (200 m) lejos del valle, la segunda cruza
    # el fondo del valle (x = 505) en y = 295 (fila 70)
    eje = [[(0.0, 50.0), (200.0, 50.0)], [(0.0, 295.0), (1000.0, 295.0)]]
    meje = h.mascara_polilineas(eje, GT, dem.shape)
    mp = np.zeros((R, C), bool)
    mp[1:-1, 1:-1] = meje
    dil = mp.copy()
    for dr, dc in ac.VECINOS:
        dil[1:-1, 1:-1] |= mp[1 + dr:R - 1 + dr, 1 + dc:C - 1 + dc]
    cruces = red.cruces_con_eje(segs, cond["acc"], C, GT, [np.asarray(p) for p in eje], dil.ravel(), 30.0)
    assert len(cruces) == 1
    cr = cruces[0]
    assert cr["celda"] // C - 1 == 70 and cr["celda"] % C - 1 == 50
    assert cr["progresiva"] == pytest.approx(200.0 + 505.0)
    assert cr["acc"] == 7100


def test_cuencas_anidadas_y_recorrido():
    dem = valle_v()
    cond, valido = preparar(dem)
    R, C = cond["forma"]
    arriba = celda(40, 50, C)
    abajo = celda(70, 50, C)
    res = red.analizar_cuencas(cond, [{"id": 1, "celda": arriba}, {"id": 2, "celda": abajo}], CELDA, GT)
    p1 = res["cuencas"][0]["parametros"]
    p2 = res["cuencas"][1]["parametros"]
    assert p1["anidada_en"] == 2 and p1["contiene"] == []
    assert p2["anidada_en"] == 0 and p2["contiene"] == [1]
    assert p1["n_celdas"] == 41 * 100
    assert p2["n_celdas"] == 71 * 100          # la total incluye la anidada
    assert p2["area_propia_ha"] == pytest.approx(30.0)
    assert int(res["aguas_abajo"][1]) == 2
    # pendiente 10-85 en el valle: el recorrido va por el fondo salvo el tramo lateral
    assert 0 < p2["s_1085"] < 0.2


def test_strahler_en_arbol_sintetico():
    """Grafo explícito en Y: dos cabeceras de orden 1 confluyen en un tronco de orden 2."""
    C = 7
    N = 7 * C

    def cel(f, c):
        return f * C + c

    recv = np.full(N, ac.SIN_FLUJO, dtype=np.int64)
    valido = np.zeros(N, bool)
    cadena = [[(1, 1), (2, 2), (3, 3)], [(1, 5), (2, 4), (3, 3)], [(3, 3), (4, 3), (5, 3)]]
    for rama in cadena:
        for a, b in zip(rama[:-1], rama[1:]):
            recv[cel(*a)] = cel(*b)
            valido[cel(*a)] = valido[cel(*b)] = True
    recv[cel(5, 3)] = ac.SALIDA
    ol = red.oleadas(recv, valido)
    acc = red.acumulacion(recv, ol, N)
    assert acc[cel(3, 3)] == 5 and acc[cel(5, 3)] == 7
    segs, cauce = red.red_cauces(recv, acc, valido, 1)
    assert len(segs) == 3
    por_inicio = {int(s["celdas"][0]): s for s in segs}
    s1, s2, tronco = por_inicio[cel(1, 1)], por_inicio[cel(1, 5)], por_inicio[cel(3, 3)]
    assert s1["orden"] == s2["orden"] == 1 and tronco["orden"] == 2
    assert s1["aguas_abajo"] == tronco["id"] and s2["aguas_abajo"] == tronco["id"] and tronco["aguas_abajo"] == 0
    assert s1["acc_fin"] == 2 and tronco["acc_fin"] == 7     # antes de la confluencia / en la salida
    assert list(s1["celdas"]) == [cel(1, 1), cel(2, 2), cel(3, 3)]
    assert tronco["termina"] == "fin"
    # partir en una celda intermedia (salida): el tronco se divide en dos
    segs2, _ = red.red_cauces(recv, acc, valido, 1, cortar_en=[cel(4, 3)])
    assert len(segs2) == 4
    cortado = next(s for s in segs2 if int(s["celdas"][0]) == cel(3, 3))
    assert list(cortado["celdas"]) == [cel(3, 3), cel(4, 3)] and cortado["termina"] == "union"


def test_ajustar_punto_y_fusion():
    dem = valle_v()
    cond, valido = preparar(dem)
    R, C = cond["forma"]
    # punto a 15 m del fondo del valle en la fila 70 (x = 505 + 15, y = 295): con
    # radio 20 m la celda de mayor acumulación alcanzable es la del fondo una fila
    # más abajo (fila 71, a 18 m), no la de la misma fila
    aj = red.ajustar_punto(520.0, 295.0, cond["acc"], valido, C, R, GT, 20.0)
    cel, xa, ya, despl = aj
    assert cel // C - 1 == 71 and cel % C - 1 == 50
    assert xa == pytest.approx(505.0) and despl == pytest.approx(math.hypot(15.0, 10.0))
    # sin radio se queda en su celda
    cel0, _, _, d0 = red.ajustar_punto(520.0, 295.0, cond["acc"], valido, C, R, GT, 0.0)
    assert cel0 % C - 1 == 52 and d0 == pytest.approx(math.hypot(525 - 520, 0))
    assert red.ajustar_punto(-50.0, 295.0, cond["acc"], valido, C, R, GT, 25.0) is None
    salidas = [{"id": 1, "celda": cel, "x": xa, "y": ya, "origen": "cruce", "acc": 7100.0, "progresiva": 505.0},
               {"id": 2, "celda": cel, "x": xa, "y": ya, "origen": "punto", "acc": 7100.0, "progresiva": 505.0},
               {"id": 3, "celda": cel + 5 * C, "x": xa, "y": ya - 50, "origen": "cruce", "acc": 7600.0,
                "progresiva": 560.0}]
    cons, desc = red.fusionar_salidas(salidas, 30.0)
    assert [s["id"] for s in cons] == [2, 3]
    assert desc[0]["id"] == 1 and desc[0]["fusionada_con"] == 2
    assert cons[0]["fusiona"] == [1]


def test_distancia_flujo_y_paso_diagonal():
    n = 30
    yy, xx = np.mgrid[0:n, 0:n]
    dem = (xx + yy) * 1.0         # baja en diagonal hacia (0, 0)
    cond, valido = preparar(dem)
    R, C = cond["forma"]
    dist = red.distancia_flujo(cond["recv"], cond["oleadas"], C, CELDA)
    # desde (k, k) la distancia al vértice (0, 0) es k pasos diagonales
    assert dist[celda(10, 10, C)] - dist[celda(0, 0, C)] == pytest.approx(10 * CELDA * math.sqrt(2))


def test_acumulacion_mfd_conserva_el_total():
    dem = valle_v()
    cond, valido = preparar(dem)
    R, C = cond["forma"]
    mfd = red.acumulacion_mfd(cond["zp"], cond["recv"], valido, cond["oleadas"])
    # en el fondo del valle (una sola salida posible) el MFD acumula lo mismo que D8
    sal = celda(99, 50, C)
    assert mfd[sal] == pytest.approx(cond["acc"][sal], rel=0.02)
    assert mfd[valido].min() >= 1.0


def test_oleadas_detecta_ciclos():
    recv = np.array([1, 0, -1])
    with pytest.raises(RuntimeError):
        red.oleadas(recv, np.ones(3, bool))


def test_perimetro_raster():
    m = np.zeros((5, 5), bool)
    m[1:4, 1:4] = True
    assert red.perimetro_raster(m, 10.0) == 120.0
    m[2, 2] = False     # un hueco añade perímetro interior
    assert red.perimetro_raster(m, 10.0) == 160.0


def test_celdas_abrir_via():
    dem = valle_v()
    cond, valido = preparar(dem)
    R, C = cond["forma"]
    via = np.zeros(R * C, bool)
    via[celda(70, 0, C):celda(70, 99, C) + 1] = True      # fila 70 completa
    sal = celda(70, 50, C)
    abrir = red.celdas_abrir_via(cond["recv"], cond["acc"], via, sal, C)
    assert sal in abrir
    assert all(via[c] or c == sal for c in abrir)
    # salida fuera de la vía (dos filas más abajo): se abre la vía por donde pasa el cauce
    sal2 = celda(72, 50, C)
    abrir2 = red.celdas_abrir_via(cond["recv"], cond["acc"], via, sal2, C)
    assert sal in abrir2

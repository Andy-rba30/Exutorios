# -*- coding: utf-8 -*-
"""Pruebas del acondicionamiento del DEM con superficies analíticas."""
import numpy as np
import pytest

from exutorios_viales import acondicionar as ac


def plano(n=60, paso=0.02, base=100.0):
    """Plano que baja hacia el sur (filas grandes = más bajo)."""
    yy, xx = np.mgrid[0:n, 0:n]
    return base + (n - 1 - yy) * paso


def cubeta(dem, centro, radio, prof):
    yy, xx = np.mgrid[0:dem.shape[0], 0:dem.shape[1]]
    r = np.hypot(xx - centro[1], yy - centro[0])
    m = r < radio
    d = dem.copy()
    d[m] -= prof * (1 - (r[m] / radio) ** 2)
    return d


def receptores(cond):
    R, C = cond["forma"]
    return cond["recv"].reshape(R, C), C


def test_plano_inclinado_todo_drena_recto():
    dem = plano()
    cond = ac.acondicionar(dem, np.ones_like(dem, bool))
    assert cond["n_sin_salida"] == 0
    assert not cond["depresion"].any()
    recv, C = receptores(cond)
    # una celda interior drena a la de abajo (misma columna)
    i = 10 * C + 20
    assert recv.ravel()[i] == i + C
    # la última fila válida drena fuera del DEM
    assert recv[-2, 20] == ac.SALIDA


def test_planicie_perfecta_drena_al_lado_bajo():
    """Meseta perfectamente plana cerrada por terreno alto en tres lados y con
    el lado sur más bajo: todas las celdas deben salir por el sur."""
    n = 40
    dem = np.full((n, n), 50.0)
    dem[0, :] = 51.0
    dem[:, 0] = 51.0
    dem[:, -1] = 51.0
    dem[-1, :] = 49.0
    cond = ac.acondicionar(dem, np.ones_like(dem, bool))
    assert cond["n_sin_salida"] == 0
    recv, C = receptores(cond)
    for c0 in (2 * C + 2, 5 * C + 20, 20 * C + 38, 30 * C + 3):
        c = c0
        pasos = 0
        while recv.ravel()[c] >= 0:
            c = recv.ravel()[c]
            pasos += 1
            assert pasos < n * n
        assert c // C == n  # fila 39 del DEM = fila 40 acolchada
        assert pasos <= 2 * n  # sin rodeos largos (se aleja de las paredes altas y baja)


def test_cuenca_cerrada_se_rellena_y_tiene_salida():
    dem = cubeta(np.full((60, 60), 100.0), (30, 30), 10, 2.0)
    cond = ac.acondicionar(dem, np.ones_like(dem, bool))
    assert cond["n_sin_salida"] == 0
    assert cond["depresion"].any()
    # volumen de relleno ≈ volumen del paraboloide π r² h / 2 (r = 10 celdas, h = 2 m)
    vol = cond["relleno"].sum()  # en m·celda²
    assert vol == pytest.approx(np.pi * 10 ** 2 * 2 / 2, rel=0.08)
    # el relleno es plano a la cota de rebose y ya no hay celdas sin descenso aisladas
    zf = cond["zp"][1:-1, 1:-1]
    assert np.nanmax(zf - dem) == pytest.approx(2.0, abs=0.05)


def test_breaching_abre_la_cubeta():
    dem = cubeta(plano(), (30, 30), 10, 2.0)
    cond = ac.acondicionar(dem, np.ones_like(dem, bool), metodo="breaching", max_longitud=50)
    assert cond["breaching"] == (1, 0)
    assert cond["n_sin_salida"] == 0
    # el canal abierto deja la cubeta sin relleno (o casi)
    assert cond["depresion"].sum() < 5
    # con longitud máxima insuficiente, se rellena
    cond2 = ac.acondicionar(dem, np.ones_like(dem, bool), metodo="breaching", max_longitud=2)
    assert cond2["breaching"][1] == 1
    assert cond2["depresion"].sum() > 100


def test_dem_de_cotas_enteras():
    """Plano suave cuantizado a metros: terrazas de varias celdas de ancho."""
    n = 80
    yy, xx = np.mgrid[0:n, 0:n]
    dem = np.floor(100 + (n - 1 - yy) * 0.2 + 0.05 * xx)
    cond = ac.acondicionar(dem, np.ones_like(dem, bool))
    assert cond["n_sin_salida"] == 0
    assert not cond["depresion"].any()
    recv, C = receptores(cond)
    z = cond["zp"].ravel()
    # desde el centro del DEM se desciende sin subir nunca y se llega abajo
    for c0 in range(3 * C + 30, 3 * C + 70, 7):
        c = c0
        pasos = 0
        while recv.ravel()[c] >= 0:
            r = recv.ravel()[c]
            assert z[r] <= z[c]
            c = r
            pasos += 1
            assert pasos < n * n
        assert c // C >= n - 3
    # la mayor parte del agua sale por la fila inferior
    from exutorios_viales import red
    valido = np.isfinite(cond["zp"]).ravel()
    acc = red.acumulacion(cond["recv"], red.oleadas(cond["recv"], valido), recv.size)
    assert acc.reshape(recv.shape)[n, 1:-1].sum() > 0.9 * n * n


def test_cono_invertido_drena_al_centro():
    n = 61
    yy, xx = np.mgrid[0:n, 0:n]
    dem = np.hypot(xx - 30, yy - 30) * 0.5
    validos = np.ones_like(dem, bool)
    # el centro es una fosa: se rellena hasta el borde y luego todo sale por el borde;
    # con una celda sin datos en el centro, el centro actúa como salida
    validos[30, 30] = False
    cond = ac.acondicionar(dem, validos)
    assert cond["n_sin_salida"] == 0
    assert not cond["depresion"].any()
    recv, C = receptores(cond)
    centro = 31 * C + 31
    # el vecino del centro drena fuera (al hueco)
    assert recv.ravel()[centro + 1] == ac.SALIDA
    # una celda alejada llega al hueco siguiendo receptores
    c = 5 * C + 50
    while recv.ravel()[c] >= 0:
        c = recv.ravel()[c]
    assert abs(c // C - 31) <= 1 and abs(c % C - 31) <= 1


def test_nodata_interior_y_borde():
    dem = plano()
    validos = np.ones_like(dem, bool)
    validos[:, 0] = False
    validos[20:25, 20:25] = False
    cond = ac.acondicionar(dem, validos)
    assert cond["n_sin_salida"] == 0
    recv, C = receptores(cond)
    # celdas inválidas sin receptor
    assert (recv[1:-1, 1:-1][~validos] == ac.SIN_FLUJO).all()
    assert (recv[1:-1, 1:-1][validos] != ac.SIN_FLUJO).all()


def test_cancelacion():
    dem = plano(100)
    with pytest.raises(RuntimeError):
        ac.acondicionar(dem, np.ones_like(dem, bool), cancelado=lambda: True)


def test_etiquetar_con_y_sin_scipy(monkeypatch):
    m = np.zeros((10, 10), dtype=bool)
    m[1:3, 1:3] = True
    m[5, 5] = True
    m[6, 6] = True  # diagonal: misma componente (8 vecinos)
    lab, n = ac.etiquetar(m)
    assert n == 2
    assert lab[1, 1] == lab[2, 2] and lab[5, 5] == lab[6, 6] and lab[1, 1] != lab[5, 5]
    # forzar la versión sin scipy
    import builtins
    real_import = builtins.__import__

    def sin_scipy(name, *a, **k):
        if name.startswith("scipy"):
            raise ImportError("sin scipy")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", sin_scipy)
    lab2, n2 = ac.etiquetar(m)
    assert n2 == 2
    assert (lab2 > 0).sum() == 6


def test_media_movil():
    zp = ac.acolchar(np.arange(25, dtype=float).reshape(5, 5))
    m = ac.media_movil(zp, 1)
    assert m[3, 3] == pytest.approx(12.0)         # centro: media del 3×3 = valor central
    assert m[1, 1] == pytest.approx((0 + 1 + 5 + 6) / 4.0)   # esquina: ventana recortada
    assert np.isnan(m[0, 0])


def test_pendiente_horn_en_plano():
    dem = plano(paso=0.05)
    zp = ac.acolchar(dem)
    s = ac.pendiente_horn(zp, 10.0)[1:-1, 1:-1]
    assert s[5:-5, 5:-5] == pytest.approx(0.005)


def test_suavizar_conserva_plano():
    dem = plano()
    validos = np.ones_like(dem, bool)
    validos[0, 0] = False
    s = ac.suavizar_3x3(dem, validos)
    assert np.isnan(s[0, 0])
    assert s[10, 10] == pytest.approx(dem[10, 10])

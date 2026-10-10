# -*- coding: utf-8 -*-
import numpy as np
import pytest

from exutorios_viales import herramientas as h

GT = (500000.0, 5.0, 0.0, 9400000.0, 0.0, -5.0)


def test_celda_xy_ida_y_vuelta():
    assert h.celda_de_xy(500012.0, 9399988.0, GT) == (2, 2)
    assert h.xy_de_celda(2, 2, GT) == (500012.5, 9399987.5)
    xs, ys = h.xy_de_indices([2, 3], [2, 0], GT)
    assert list(xs) == [500012.5, 500002.5] and list(ys) == [9399987.5, 9399982.5]


def test_mascara_polilineas_sin_fugas_diagonales():
    m = h.mascara_polilineas([[(500000.0, 9400000.0), (500050.0, 9399950.0)]], GT, (12, 12))
    assert m.any()
    filas, cols = np.nonzero(m)
    for f, c in zip(filas, cols):
        vecinos = [(f + 1, c), (f - 1, c), (f, c + 1), (f, c - 1)]
        assert any(0 <= a < 12 and 0 <= b < 12 and m[a, b] for a, b in vecinos)


def test_progresivas_con_partes_concatenadas():
    partes = [[(0.0, 0.0), (100.0, 0.0)], [(0.0, 50.0), (0.0, 80.0)]]
    bases, longs = h.longitudes_partes(partes)
    assert bases == [0.0, 100.0] and longs == [100.0, 30.0]
    pts = h.muestrear_polilineas(partes, 25.0)
    assert [p[0] for p in pts] == [0, 25, 50, 75, 100, 100, 125, 130]
    # punto cerca de la segunda parte: progresiva 100 + 20
    prog, dist = h.progresiva_de_punto(3.0, 70.0, partes)
    assert prog == pytest.approx(120.0) and dist == pytest.approx(3.0)
    # punto antes del inicio: se ancla al primer vértice
    prog0, _ = h.progresiva_de_punto(-10.0, 0.0, partes)
    assert prog0 == 0.0


def test_progresiva_km():
    assert h.progresiva_km(0) == "0+000"
    assert h.progresiva_km(1234.6) == "1+235"
    assert h.progresiva_km(None) == "-"


def test_intersecciones_exactas():
    cauce = np.array([(0.0, 0.0), (10.0, 10.0), (20.0, 0.0)])
    eje = [np.array([(0.0, 5.0), (20.0, 5.0)])]
    its = h.intersecciones(cauce, eje)
    assert len(its) == 2
    assert its[0]["x"] == pytest.approx(5.0) and its[0]["progresiva"] == pytest.approx(5.0) and its[0]["i"] == 0
    assert its[1]["x"] == pytest.approx(15.0) and its[1]["progresiva"] == pytest.approx(15.0) and its[1]["i"] == 1
    # cruce exactamente en un vértice del cauce: una sola intersección
    its2 = h.intersecciones(cauce, [np.array([(0.0, 10.0), (20.0, 10.0)])])
    assert len(its2) == 1 and its2[0]["x"] == pytest.approx(10.0)
    # segunda parte del eje: la progresiva acumula la longitud de la primera
    its3 = h.intersecciones(cauce, [np.array([(100.0, 100.0), (130.0, 100.0)]), np.array([(0.0, 5.0), (20.0, 5.0)])])
    assert its3[0]["progresiva"] == pytest.approx(35.0)
    # paralelas: nada
    assert h.intersecciones(np.array([(0.0, 0.0), (10.0, 0.0)]), [np.array([(0.0, 1.0), (10.0, 1.0)])]) == []


def test_csv(tmp_path):
    ruta = tmp_path / "t.csv"
    h.escribir_csv(str(ruta), ["a", "b", "c"], [{"a": 1, "b": 2.5, "c": "x"}, {"a": None, "b": float("nan")}])
    lineas = ruta.read_text(encoding="utf-8-sig").splitlines()
    assert lineas == ["a;b;c", "1;2.5;x", ";;"]


def _cuenca(i):
    tc = {n: {"tc_min": 20.0 + i, "tc_aplicado": 20.0 + i, "fuera_rango": "área fuera de rango" if n == "Kirpich" else None}
          for n in ("Kirpich", "Témez", "California Culverts Practice", "Bransby-Williams", "Retardo SCS")}
    q = {25: {"pd": 58.5, "p24": 66.1, "po": 9.0, "p_tc": 30.0, "c": 0.5, "c_racional": 0.5, "i": 40.0,
              "q_racional": 1.0, "k": 1.05, "q_temez": 1.05, "q_adoptado": 1.05}}
    return {"id": i, "escenario": "natural", "progresiva": 100.0 * i, "origen": "cruce", "desplazamiento": 0.0,
            "area_ha": 10.0 * i, "area_km2": 0.1 * i, "perimetro_km": 1.5, "l_m": 500.0, "h_max": 30.0, "h_min": 20.0,
            "dh": 10.0, "s_l": 0.02, "s_1085": 0.015, "s_cuenca": 0.03, "h_media": 25.0, "kc": 1.3, "kf": 0.4,
            "n_depresiones": 2, "vol_depresiones": 1000.0, "frac_depresiones": 0.1, "toca_borde": i == 2,
            "anidada_en": 0, "contiene": [], "cn": 85.0, "tc": tc, "tc_adoptado_min": 22.0,
            "tc_criterio": "media de ...", "q": q}


def test_informe_html(tmp_path):
    datos = {
        "parametros": {"tabla": [("DEM", "dem.tif"), ("Celda", "12.5 m")], "tc_min": 10.0},
        "metodo": ["paso uno", "paso dos"],
        "cuencas": [_cuenca(1), _cuenca(2)],
        "hidrologia": {"tr": [25], "formulas_tc": ["Kirpich", "Témez", "California Culverts Practice",
                                                   "Bransby-Williams", "Retardo SCS"], "texto": ["lluvia"]},
        "avisos": [{"texto": "toca el borde", "grave": True}, {"texto": "depresiones"}],
        "limitaciones": ["limitación"],
        "texto_tesis": "texto para la tesis",
    }
    ruta = tmp_path / "informe.html"
    h.informe_html(str(ruta), datos)
    html = ruta.read_text(encoding="utf-8")
    assert "Cuencas de aporte" in html and "toca el borde" in html and "texto para la tesis" in html
    assert "class='fuera'" in html          # Kirpich fuera de rango marcado
    assert "0+100" in html and "0+200" in html

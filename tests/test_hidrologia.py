# -*- coding: utf-8 -*-
"""Pruebas de las fórmulas hidrológicas contra valores de referencia."""
import math

import pytest

from exutorios_viales import hidrologia as hd


def test_kirpich_y_california_son_la_misma_ecuacion():
    L, S = 1230.0, 0.0126
    tk = hd.tc_kirpich(L, S)
    assert tk == pytest.approx(0.0195 * L ** 0.77 * S ** -0.385)
    assert hd.tc_california(L, S * L) == pytest.approx(tk, rel=1e-9)
    # ejemplo clásico: L = 1 000 m, S = 1 % -> 23.6 min
    assert hd.tc_kirpich(1000.0, 0.01) == pytest.approx(23.4, abs=0.1)
    assert math.isnan(hd.tc_kirpich(0, 0.01))


def test_temez_horas():
    # L = 1.23 km, S = 0.0126 -> 0.3·(1.23/0.0126^0.25)^0.76 h
    t = hd.tc_temez(1.23, 0.0126)
    assert t / 60.0 == pytest.approx(0.3 * (1.23 / 0.0126 ** 0.25) ** 0.76)


def test_bransby_williams_y_scs():
    t = hd.tc_bransby_williams(1.23, 0.554, 0.0126)
    assert t == pytest.approx(14.6 * 1.23 * 0.554 ** -0.1 * 0.0126 ** -0.2)
    # retardo SCS: L = 1 000 pies, CN = 80, Y = 2 % -> lag = 1000^0.8·(2.5+1)^0.7/(1900·√2)
    L_m = 1000.0 / 3.280839895
    lag_h = 1000 ** 0.8 * (1000 / 80 - 10 + 1) ** 0.7 / (1900 * math.sqrt(2))
    assert hd.tc_scs_lag(L_m, 80.0, 2.0) == pytest.approx(60 * lag_h / 0.6, rel=1e-6)


def test_rangos_y_adoptado():
    tcs = hd.tiempos_concentracion(1230.0, 15.5, 0.554, 0.0126, 0.02, 85.0, tc_min=10.0)
    assert set(tcs) == set(hd.FORMULAS_TC)
    assert "pendiente" in tcs["Kirpich"]["fuera_rango"]
    assert "área" in tcs["Kirpich"]["fuera_rango"]
    assert tcs["Témez"]["fuera_rango"] and "1 km²" in tcs["Témez"]["fuera_rango"]
    assert tcs["Bransby-Williams"]["fuera_rango"] is None
    assert tcs["Retardo SCS"]["fuera_rango"] is None
    tc, crit = hd.tc_adoptado(tcs, "media_validas")
    validas = [tcs["Bransby-Williams"]["tc_aplicado"], tcs["Retardo SCS"]["tc_aplicado"]]
    assert tc == pytest.approx(sum(validas) / 2)
    assert "Bransby-Williams" in crit and "Kirpich" not in crit
    assert hd.tc_adoptado(tcs, "Kirpich")[0] == tcs["Kirpich"]["tc_aplicado"]
    assert hd.tc_adoptado(tcs, "minimo")[0] == min(validas)
    # Tc mínimo
    tcs2 = hd.tiempos_concentracion(50.0, 5.0, 0.001, 0.1, 0.1, 85.0, tc_min=10.0)
    assert tcs2["Kirpich"]["tc_min"] < 10.0 and tcs2["Kirpich"]["tc_aplicado"] == 10.0


def test_cn_tabla_amc_y_compuesto():
    assert hd.cn_tabla(0, "C") == 85.0
    assert hd.cn_tabla("Barbecho / suelo desnudo", "d") == 94.0
    # Chow et al. 1988: CN(II) = 85 -> CN(III) ≈ 92.9, CN(I) ≈ 70.3
    assert hd.cn_amc(85, "III") == pytest.approx(92.87, abs=0.01)
    assert hd.cn_amc(85, "I") == pytest.approx(70.4, abs=0.1)
    assert hd.cn_amc(85, "II") == 85.0
    # compuesto por área: 50 % A (67) + 50 % D (89) = 78
    assert hd.cn_compuesto({"A": 0.5, "D": 0.5}, 0) == pytest.approx(78.0)
    # claves numéricas = CN directos
    assert hd.cn_compuesto({70.0: 1.0, 90.0: 1.0}, 0) == pytest.approx(80.0)


def test_lluvia_e_intensidad():
    assert hd.lluvia_24h(58.5) == pytest.approx(66.105)
    pd_, i = hd.intensidad_dyck_peschke(100.0, 60.0)
    assert pd_ == pytest.approx(100 * (60 / 1440) ** 0.25)
    assert i == pytest.approx(pd_)                       # 60 min -> mm/h = mm
    pd24, i24 = hd.intensidad_dyck_peschke(100.0, 1440.0)
    assert pd24 == pytest.approx(100.0) and i24 == pytest.approx(100 / 24)
    # IDF Gumbel de Hydrognomon: i = λ(ψ − ln(−ln(1−1/T)))/(1+d/θ)^η
    i_g = hd.intensidad_idf("gumbel", 50, 60.0, 20.0, 0.0, 0.5, 0.2, 0.7)
    assert i_g == pytest.approx(20.0 * (0.5 - math.log(-math.log(1 - 1 / 50))) / (1 + 1.0 / 0.2) ** 0.7)
    i_gev = hd.intensidad_idf("gev", 50, 60.0, 20.0, 0.15, 0.6, 0.2, 0.7)
    assert i_gev == pytest.approx(20.0 * (50 ** 0.15 - 0.6) / (1 + 1.0 / 0.2) ** 0.7)
    i_sh = hd.intensidad_idf("sherman", 50, 60.0, 500.0, 0.2, 0.0, 10.0, 0.8)
    assert i_sh == pytest.approx(500 * 50 ** 0.2 / 70 ** 0.8)


def test_temez_c_k_y_caudales():
    # hoja de cálculo de referencia (Alzira): Pd = 139, Po = 48.3 -> C ≈ 0.25; Tc = 1.19 h -> K ≈ 1.08
    assert hd.c_temez(139.0, 48.3) == pytest.approx(0.25, abs=0.005)
    assert hd.k_temez(1.19) == pytest.approx(1.08, abs=0.005)
    assert hd.k_temez(0.77) == pytest.approx(1.05, abs=0.005)
    assert hd.c_temez(10.0, 20.0) == 0.0
    assert hd.umbral_po(85.0) == pytest.approx(5080 / 85 - 50.8)
    assert hd.q_racional(0.5, 40.0, 2.0) == pytest.approx(0.5 * 40 * 2 / 3.6)
    q, k = hd.q_temez(0.5, 40.0, 2.0, 1.0)
    assert q == pytest.approx(0.5 * 40 * 2 * k / 3.6)
    res = hd.caudales(0.554, 45.0, 85.0, [(25, 58.5), (71, 101.7)])
    assert set(res) == {25, 71}
    r = res[71]
    assert r["p24"] == pytest.approx(101.7 * 1.13)
    assert r["q_temez"] == pytest.approx(r["q_racional"] * r["k"])
    assert r["q_adoptado"] == r["q_temez"]
    assert hd.caudales(0.554, 45.0, 85.0, [(25, 58.5)], adoptar="racional")[25]["q_adoptado"] == pytest.approx(
        res[25]["q_racional"])
    # C fijo para el racional clásico
    r2 = hd.caudales(0.554, 45.0, 85.0, [(25, 58.5)], c_fijo=0.6)[25]
    assert r2["c_racional"] == 0.6 and r2["q_racional"] == pytest.approx(0.6 * r2["i"] * 0.554 / 3.6)


def test_leer_tabla_lluvia():
    assert hd.leer_tabla_lluvia("25:58.5; 35:70.6; 71:101.7") == [(25.0, 58.5), (35.0, 70.6), (71.0, 101.7)]
    assert hd.leer_tabla_lluvia("71=101.7\n25 58.5") == [(25.0, 58.5), (71.0, 101.7)]
    with pytest.raises(ValueError):
        hd.leer_tabla_lluvia("")
    with pytest.raises(ValueError):
        hd.leer_tabla_lluvia("25")

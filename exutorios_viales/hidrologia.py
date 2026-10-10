# -*- coding: utf-8 -*-
# Complemento QGIS «Exutorios Viales»
# Copyright (C) 2026 Jose Ospina
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version. See the LICENSE file for details.
"""
Hidrología de las cuencas: tiempo de concentración, número de curva,
lluvia de diseño, intensidad y caudal de diseño. Solo biblioteca estándar.

Todas las fórmulas llevan su fuente y sus unidades. Se verificaron contra
las fuentes citadas antes de implementarlas; las notas de validez indican
el rango con el que cada fórmula fue calibrada.
"""

import math

# ---------------------------------------------------------------------------
# Tiempo de concentración
# ---------------------------------------------------------------------------

FORMULAS_TC = ("Kirpich", "Témez", "California Culverts Practice", "Bransby-Williams", "Retardo SCS")


def tc_kirpich(L_m, S):
    """Kirpich (1940), «Time of concentration of small agricultural
    watersheds», Civil Engineering (ASCE) 10(6):362.

    Tc [min] = 0.0195 · L^0.77 · S^-0.385, con L [m] longitud del cauce y
    S [m/m] pendiente media del cauce (coeficiente SI 0.0195; en unidades
    inglesas 0.0078 con L en pies). Calibrada en 7 cuencas rurales de
    Tennessee de 0.5 a 45 ha (1.25 a 112 acres) con pendientes de 3 a 10 %."""
    if L_m <= 0 or S <= 0:
        return float("nan")
    return 0.0195 * L_m ** 0.77 * S ** (-0.385)


def tc_temez(L_km, S):
    """Témez (1978), «Cálculo hidrometeorológico de caudales máximos en
    pequeñas cuencas naturales», MOPU, Madrid; adoptada por la Instrucción
    5.2-IC «Drenaje superficial» (España, 1990).

    Tc [h] = 0.3 · (L / S^0.25)^0.76, con L [km] longitud del cauce principal
    y S [m/m] su pendiente media. Devuelve minutos. Témez (1991) la aplica
    en cuencas naturales de hasta 3 000 km²; por debajo de ~1 km² es una
    extrapolación (fue ajustada con cuencas de 1 a 3 000 km²)."""
    if L_km <= 0 or S <= 0:
        return float("nan")
    return 60.0 * 0.3 * (L_km / S ** 0.25) ** 0.76


def tc_california(L_m, H_m):
    """California Culverts Practice (California Highways and Public Works,
    1942), como la recoge el Manual de Hidrología, Hidráulica y Drenaje del
    MTC (Perú, 2011, tabla de fórmulas de Tc).

    Tc [min] = 0.0195 · (L³ / H)^0.385 con L [m] longitud del cauce más largo
    y H [m] desnivel entre la divisoria y la salida. Es la misma ecuación de
    Kirpich escrita con el desnivel (S = H/L); con L en km se escribe
    Tc = 60 · (0.87 · L³ / H)^0.385. Desarrollada para cuencas pequeñas de
    montaña en California; comparte el rango de Kirpich."""
    if L_m <= 0 or H_m <= 0:
        return float("nan")
    return 0.0195 * (L_m ** 3 / H_m) ** 0.385


def tc_bransby_williams(L_km, A_km2, S):
    """Bransby Williams (1922), «Flood discharge and the dimensions of
    spillways in India», The Engineer 134:321-322; forma métrica de Pilgrim
    y Cordery (1993, «Flood runoff», Handbook of Hydrology, cap. 9) y del
    Manual del MTC (2011).

    Tc [min] = 14.6 · L · A^-0.1 · S^-0.2 (equivale a Tc [h] = 0.2433 · L ·
    A^-0.1 · S^-0.2), con L [km] longitud del cauce principal, A [km²] área
    y S [m/m] pendiente del cauce. Sin rango de calibración publicado; se
    emplea en cuencas rurales medianas (Australian Rainfall and Runoff la
    recomienda para áreas menores de ~50 km²)."""
    if L_km <= 0 or A_km2 <= 0 or S <= 0:
        return float("nan")
    return 14.6 * L_km * A_km2 ** (-0.1) * S ** (-0.2)


def tc_scs_lag(L_m, CN, Y_pct):
    """Retardo (lag) del SCS: USDA-NRCS, National Engineering Handbook
    Part 630 Hydrology, cap. 15 «Time of concentration» (2010), ec. 15-4a, y
    Tc = lag / 0.6 (ec. 15-5).

    lag [h] = l^0.8 · (S + 1)^0.7 / (1900 · Y^0.5), con l [pies] longitud
    hidráulica, S [pulg] = 1000/CN − 10 y Y [%] pendiente media de la cuenca.
    Devuelve Tc en minutos. El NEH-630 la limita a cuencas menores de
    2 000 acres (8.1 km²) y a CN entre 50 y 95."""
    if L_m <= 0 or CN <= 0 or Y_pct <= 0:
        return float("nan")
    l_ft = L_m * 3.280839895
    S_in = 1000.0 / CN - 10.0
    lag_h = l_ft ** 0.8 * (S_in + 1.0) ** 0.7 / (1900.0 * math.sqrt(Y_pct))
    return 60.0 * lag_h / 0.6


def tiempos_concentracion(L_m, dh_m, A_km2, S_cauce, S_cuenca, CN, tc_min=10.0):
    """Calcula las cinco fórmulas y marca las que salen de su rango.

    S_cauce: pendiente del recorrido (m/m) usada por Kirpich, Témez y
    Bransby-Williams; dh_m: desnivel para California; S_cuenca: pendiente
    media de la cuenca (m/m) para el retardo SCS.
    Devuelve dict nombre -> {tc_min, tc_min_aplicado, fuera_rango (texto o None)}."""
    A_ha = A_km2 * 100.0
    L_km = L_m / 1000.0
    res = {}

    def agrega(nombre, tc, motivos):
        aplicado = tc
        if tc is not None and math.isfinite(tc):
            aplicado = max(tc, tc_min)
        res[nombre] = {"tc_min": tc, "tc_aplicado": aplicado, "fuera_rango": "; ".join(motivos) or None}

    m = []
    if not (0.5 <= A_ha <= 45.0):
        m.append("área fuera de 0.5–45 ha")
    if not (0.03 <= S_cauce <= 0.10):
        m.append("pendiente fuera de 3–10 %")
    agrega("Kirpich", tc_kirpich(L_m, S_cauce), m)

    m = []
    if A_km2 < 1.0:
        m.append("área menor de 1 km² (extrapolación)")
    if A_km2 > 3000.0:
        m.append("área mayor de 3 000 km²")
    agrega("Témez", tc_temez(L_km, S_cauce), m)

    m = []
    if not (0.5 <= A_ha <= 45.0):
        m.append("área fuera de 0.5–45 ha (igual que Kirpich)")
    if not (0.03 <= S_cauce <= 0.10):
        m.append("pendiente fuera de 3–10 % (igual que Kirpich)")
    agrega("California Culverts Practice", tc_california(L_m, dh_m), m)

    m = []
    if A_km2 > 50.0:
        m.append("área mayor de 50 km²")
    agrega("Bransby-Williams", tc_bransby_williams(L_km, A_km2, S_cauce), m)

    m = []
    if A_km2 > 8.1:
        m.append("área mayor de 2 000 acres (8.1 km²)")
    if not (50.0 <= CN <= 95.0):
        m.append("CN fuera de 50–95")
    agrega("Retardo SCS", tc_scs_lag(L_m, CN, 100.0 * S_cuenca), m)
    return res


def tc_adoptado(tcs, criterio="media_validas", tc_min=10.0):
    """Tc adoptado según el criterio: media_validas, mediana_validas, minimo,
    maximo o el nombre de una fórmula. Si ninguna fórmula está en rango se
    usan todas. Devuelve (tc_min, texto_del_criterio)."""
    valores = {k: v["tc_aplicado"] for k, v in tcs.items()
               if v["tc_aplicado"] is not None and math.isfinite(v["tc_aplicado"])}
    if not valores:
        return tc_min, "sin fórmulas válidas: Tc mínimo"
    if criterio in valores:
        return valores[criterio], criterio
    validas = {k: v for k, v in valores.items() if not tcs[k]["fuera_rango"]}
    usadas = validas if validas else valores
    nota = "" if validas else " (ninguna en rango: se usan todas)"
    vs = sorted(usadas.values())
    if criterio == "minimo":
        return vs[0], "mínimo de " + ", ".join(sorted(usadas)) + nota
    if criterio == "maximo":
        return vs[-1], "máximo de " + ", ".join(sorted(usadas)) + nota
    if criterio == "mediana_validas":
        n = len(vs)
        med = vs[n // 2] if n % 2 else 0.5 * (vs[n // 2 - 1] + vs[n // 2])
        return med, "mediana de " + ", ".join(sorted(usadas)) + nota
    return sum(vs) / len(vs), "media de " + ", ".join(sorted(usadas)) + nota


# ---------------------------------------------------------------------------
# Número de curva
# ---------------------------------------------------------------------------

# CN para condición de humedad II (AMC II), grupos hidrológicos A, B, C, D.
# Fuente: USDA-NRCS (1986) Urban Hydrology for Small Watersheds, TR-55,
# tablas 2-2a (urbano), 2-2b (agrícola cultivado) y 2-2c (otras tierras
# agrícolas) y 2-2d (zonas áridas y semiáridas).
TABLA_CN = [
    ("Cultivos en hileras, surcos rectos, condición buena", (67, 78, 85, 89)),
    ("Cultivos en hileras, surcos rectos, condición pobre", (72, 81, 88, 91)),
    ("Cereales (grano pequeño), surcos rectos, condición buena", (63, 75, 83, 87)),
    ("Barbecho / suelo desnudo", (77, 86, 91, 94)),
    ("Pastizal, condición regular", (49, 69, 79, 84)),
    ("Pastizal, condición pobre", (68, 79, 86, 89)),
    ("Matorral, condición regular", (35, 56, 70, 77)),
    ("Bosque, condición regular", (36, 60, 73, 79)),
    ("Matorral desértico (zona árida), condición regular", (55, 72, 81, 86)),
    ("Residencial, lotes de 1 000 m² (38 % impermeable)", (61, 75, 83, 87)),
    ("Pavimentos y techos (impermeable)", (98, 98, 98, 98)),
]
USOS_CN = [t[0] for t in TABLA_CN]
GRUPOS = ("A", "B", "C", "D")


def cn_tabla(uso, grupo):
    """CN (AMC II) para un uso de la tabla y un grupo hidrológico A-D."""
    if isinstance(uso, int):
        fila = TABLA_CN[uso]
    else:
        fila = next(t for t in TABLA_CN if t[0] == uso)
    g = GRUPOS.index(str(grupo).strip().upper())
    return float(fila[1][g])


def cn_amc(cn2, amc="II"):
    """Conversión entre condiciones de humedad antecedente (Chow, Maidment y
    Mays, 1988, Applied Hydrology, ecs. 5.5.5 y 5.5.6):
    CN(I) = 4.2·CN(II)/(10 − 0.058·CN(II));  CN(III) = 23·CN(II)/(10 + 0.13·CN(II))."""
    amc = str(amc).upper()
    if amc == "III":
        return 23.0 * cn2 / (10.0 + 0.13 * cn2)
    if amc == "I":
        return 4.2 * cn2 / (10.0 - 0.058 * cn2)
    return float(cn2)


def cn_compuesto(fracciones, uso, amc="II"):
    """CN compuesto por área (SCS): Σ CN_i · A_i / Σ A_i.

    fracciones: dict grupo -> fracción de área (o dict CN -> fracción si las
    claves son numéricas)."""
    total = sum(fracciones.values())
    if total <= 0:
        return float("nan")
    s = 0.0
    for k, f in fracciones.items():
        if isinstance(k, (int, float)):
            cn = float(k)
        else:
            try:
                cn = cn_tabla(uso, k)
            except (ValueError, StopIteration):
                cn = float(k)
        s += cn * f
    return cn_amc(s / total, amc)


# ---------------------------------------------------------------------------
# Lluvia e intensidad
# ---------------------------------------------------------------------------

def lluvia_24h(p_diaria, factor=1.13):
    """Lluvia máxima de 24 h a partir de la máxima diaria (observación a
    hora fija): factor de Hershfield (1961, Weather Bureau TP-40), 1.13,
    también recomendado por la OMM (Guía de prácticas hidrológicas, 2009)."""
    return p_diaria * factor


def intensidad_dyck_peschke(p24, d_min):
    """Dyck y Peschke (1995, Grundlagen der Hydrologie), como la aplica el
    Manual de Hidrología, Hidráulica y Drenaje del MTC (2011):
    P_d = P_24h · (d / 1440)^0.25 con d en minutos; I = P_d / (d/60) [mm/h].
    Devuelve (P_d [mm], I [mm/h])."""
    if d_min <= 0:
        return float("nan"), float("nan")
    pd_ = p24 * (d_min / 1440.0) ** 0.25
    return pd_, pd_ * 60.0 / d_min


def intensidad_idf(tipo, tr, d_min, lam, kappa, psi, theta, eta):
    """Curva IDF paramétrica.

    tipo «gumbel» o «gev»: forma de Koutsoyiannis, Kozonis y Manetas (1998,
    J. Hydrol. 206:118-135), la que entrega Hydrognomon (módulo «Ombrian
    curves»): i(d, T) = a(T) / b(d), con b(d) = (1 + d/θ)^η, d en HORAS,
    i en mm/h, y
      gumbel: a(T) = λ · (ψ − ln(−ln(1 − 1/T)))
      gev:    a(T) = λ' · (T^κ' − ψ')
    tipo «sherman»: I = K · T^m / (d + θ)^η con d en MINUTOS (forma de
    Bernard/Sherman usada en estudios peruanos: K = lam, m = kappa).
    Devuelve I [mm/h]."""
    if d_min <= 0 or tr <= 1:
        return float("nan")
    tipo = (tipo or "").lower()
    if tipo == "sherman":
        return lam * tr ** kappa / (d_min + theta) ** eta
    d_h = d_min / 60.0
    b = (1.0 + d_h / theta) ** eta if theta > 0 else 1.0
    if tipo == "gumbel":
        a = lam * (psi - math.log(-math.log(1.0 - 1.0 / tr)))
    elif tipo == "gev":
        a = lam * (tr ** kappa - psi)
    else:
        return float("nan")
    return a / b


# ---------------------------------------------------------------------------
# Escorrentía y caudal
# ---------------------------------------------------------------------------

def umbral_po(cn):
    """Umbral de escorrentía Po [mm] equivalente al CN: Po = Ia = 0.2·S con
    S = 25400/CN − 254 → Po = 5080/CN − 50.8 (la forma 5000/CN − 50 es su
    redondeo)."""
    return 5080.0 / cn - 50.8


def c_temez(pd_mm, po_mm):
    """Coeficiente de escorrentía de Témez (1991; Instrucción 5.2-IC):
    C = (Pd − Po)(Pd + 23·Po) / (Pd + 11·Po)², 0 si Pd ≤ Po."""
    if pd_mm <= po_mm or po_mm < 0:
        return 0.0
    return (pd_mm - po_mm) * (pd_mm + 23.0 * po_mm) / (pd_mm + 11.0 * po_mm) ** 2


def k_temez(tc_h):
    """Coeficiente de uniformidad de Témez (1991, «Extended and improved
    rational method», XXIV IAHR Congress, Madrid): K = 1 + Tc^1.25 / (Tc^1.25 + 14),
    Tc en horas."""
    if tc_h <= 0:
        return 1.0
    t = tc_h ** 1.25
    return 1.0 + t / (t + 14.0)


def q_racional(c, i_mmh, a_km2):
    """Método racional: Q [m³/s] = C · I [mm/h] · A [km²] / 3.6."""
    return c * i_mmh * a_km2 / 3.6


def q_temez(c, i_mmh, a_km2, tc_h):
    """Método racional modificado de Témez: Q = C · I · A · K / 3.6.
    Devuelve (Q [m³/s], K)."""
    k = k_temez(tc_h)
    return c * i_mmh * a_km2 * k / 3.6, k


def caudales(a_km2, tc_min, cn, lluvias, factor_24h=1.13, idf=None, c_fijo=None,
             adoptar="temez"):
    """Caudal de diseño para cada periodo de retorno.

    lluvias: lista de (Tr, P_diaria_mm). idf: None (Dyck-Peschke) o dict con
    tipo, lam, kappa, psi, theta, eta. c_fijo: coeficiente C para el método
    racional clásico (None = usar el C de Témez). adoptar: «temez», «racional»
    o «mayor».
    Devuelve dict Tr -> {pd, p24, po, c, c_racional, i, q_racional, k, q_temez, q_adoptado}."""
    out = {}
    po = umbral_po(cn)
    tc_h = tc_min / 60.0
    for tr, pd_ in lluvias:
        p24 = lluvia_24h(pd_, factor_24h)
        if idf:
            i = intensidad_idf(idf["tipo"], tr, tc_min, idf["lam"], idf["kappa"], idf["psi"], idf["theta"],
                               idf["eta"])
            p_tc = i * tc_h
        else:
            p_tc, i = intensidad_dyck_peschke(p24, tc_min)
        c = c_temez(pd_, po)
        c_r = c if c_fijo is None else c_fijo
        qr = q_racional(c_r, i, a_km2)
        qt, k = q_temez(c, i, a_km2, tc_h)
        if adoptar == "racional":
            qa = qr
        elif adoptar == "mayor":
            qa = max(qr, qt)
        else:
            qa = qt
        out[tr] = {"pd": pd_, "p24": p24, "po": po, "p_tc": p_tc, "c": c, "c_racional": c_r, "i": i,
                   "q_racional": qr, "k": k, "q_temez": qt, "q_adoptado": qa}
    return out


def leer_tabla_lluvia(texto):
    """«25:58.5; 35:70.6; 71:101.7» -> [(25.0, 58.5), ...]. Acepta «,» «;»
    y saltos de línea como separadores de pares y «:» «=» o espacio dentro."""
    pares = []
    for trozo in texto.replace(";", "\n").replace(",", "\n").splitlines():
        t = trozo.strip()
        if not t:
            continue
        for sep in (":", "=", "\t", " "):
            if sep in t:
                a, b = t.split(sep, 1)
                break
        else:
            raise ValueError("par Tr:lluvia no válido: «%s»" % t)
        pares.append((float(a.strip()), float(b.strip())))
    if not pares:
        raise ValueError("la tabla de lluvia está vacía")
    return sorted(pares)

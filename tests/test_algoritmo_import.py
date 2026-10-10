# -*- coding: utf-8 -*-
"""Importa el complemento con el sustituto de PyQGIS y revisa la definición
de parámetros (nombres únicos, avanzados, salidas)."""
from exutorios_viales import algoritmo, provider


def test_algoritmo_completo_define_parametros():
    a = algoritmo.CuencasAlcantarillasAlgorithm()
    a.initAlgorithm()
    nombres = [p.name() for p in a.parameterDefinitions()]
    assert nombres[0] == "DEM" and nombres[1] == "EJE"
    for n in ("PUNTOS", "UMBRAL_HA", "MODO_SALIDAS", "LLUVIA", "USO", "AMC", "SUELOS", "CAMPO_SUELO",
              "VIA_BARRERA", "DEPRESIONES", "IDF_TIPO", "TC_MIN", "TC_CRITERIO", "Q_ADOPTADO",
              "OUT_CUENCAS", "OUT_SALIDAS", "OUT_CAUCES", "OUT_RECORRIDOS", "OUT_ACUMULACION", "OUT_CSV",
              "OUT_INFORME"):
        assert n in nombres
    assert len(nombres) == len(set(nombres))
    salidas = [o.name() for o in a.outputDefinitions()]
    assert "N_SALIDAS" in salidas and "Q_MAX" in salidas
    assert a.parameterDefinition("IDF_ETA").flags() & 2
    assert not a.parameterDefinition("DEM").flags() & 2
    assert a.parameterDefinition("UMBRAL_HA").defaultValue() == 2.0
    assert a.parameterDefinition("RADIO_AJUSTE").defaultValue() == 25.0
    assert len(a.TC_CRITERIOS) == len(a.TC_CLAVES) and len(a.Q_OPC) == len(a.Q_CLAVES)


def test_algoritmo_rapido_visibles():
    a = algoritmo.CuencasAlcantarillasRapidoAlgorithm()
    a.initAlgorithm()
    visibles = [p.name() for p in a.parameterDefinitions() if not p.isDestination() and not (p.flags() & 2)]
    assert visibles == ["DEM", "EJE", "PUNTOS", "CAMPO_NOMBRE", "UMBRAL_HA", "LLUVIA", "USO", "SUELOS",
                        "CAMPO_SUELO", "VIA_BARRERA"]
    for n in ("MODO_SALIDAS", "AMC", "DEPRESIONES", "CELDA", "HUECOS", "TC_MIN"):
        assert a.parameterDefinition(n).flags() & 2
    assert a.name() == "cuencas_alcantarillas_rapido"
    assert a.createInstance().name() == "cuencas_alcantarillas_rapido"
    assert "DEM" in a.shortHelpString()


def test_proveedor_y_plugin():
    p = provider.ExutoriosVialesProvider()
    p.loadAlgorithms()
    assert sorted(a.name() for a in p.algorithms()) == ["cuencas_alcantarillas", "cuencas_alcantarillas_rapido"]
    assert p.id() == "exutoriosviales"
    from exutorios_viales import plugin
    assert plugin.ID_ALGORITMO_RAPIDO == "exutoriosviales:cuencas_alcantarillas_rapido"


def test_codigos_d8():
    import numpy as np
    C = 5
    recv = np.array([-1, 0, 1 + C, 1 + C, 1 + C, 1 + C, -2])
    cod = algoritmo.CuencasAlcantarillasAlgorithm._codigos_d8(recv, C)
    assert cod[0] == 0 and cod[1] == 16   # oeste
    assert cod[6] == 0
    assert cod[2] == 8                 # celda 2 -> celda 6 = fila +1, col -1: suroeste


def test_interpretar_suelo():
    assert algoritmo._interpretar_suelo("C") == ("grupo", "C")
    assert algoritmo._interpretar_suelo("grupo b") == ("grupo", "B")
    assert algoritmo._interpretar_suelo("78") == ("cn", 78.0)
    assert algoritmo._interpretar_suelo("") is None
    assert algoritmo._interpretar_suelo("xyz") is None

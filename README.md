# Exutorios Viales – complemento para QGIS

Delimita la **cuenca de aporte de cada alcantarilla** (o de cada cruce cauce–vía) y calcula sus
parámetros geomorfológicos, el tiempo de concentración y el caudal de diseño, en un solo algoritmo
de Procesos. Reemplaza el flujo manual con GRASS (`r.watershed` → `r.thin` → `r.to.vect` →
intersección → `r.water.outlet` → `r.lfp` → calculadora de campos) y sus pasos frágiles.

Solo usa `numpy` y GDAL/OGR, que ya vienen con QGIS. Funciona en QGIS 3.16 o superior (Qt5 y Qt6).
Es el complemento hermano de [Cota de Anegamiento](https://github.com/Andy-rba30/Plugin-cota-de-anegamiento)
y comparte con él la preparación del DEM, el cálculo de progresivas y la estructura.

## Instalación

1. Descarga `exutorios_viales.zip` (carpeta `dist`, pestaña *Releases* o artefacto de CI), o
   genéralo con `python scripts/empaquetar.py`.
2. En QGIS: **Complementos › Administrar e instalar complementos › Instalar a partir de ZIP**.
3. Aparecen un ícono en la barra de herramientas, el menú **Complementos › Exutorios Viales** y el
   grupo **Exutorios Viales › Hidrología vial** en la caja de herramientas de Procesos.

## Uso rápido

1. Carga el DEM y el eje de la vía (líneas; puede venir de un DXF con curvas y varias partes).
2. Pulsa el ícono **Cuencas de alcantarillas (análisis rápido)**.
3. Elige el DEM y el eje. Si tienes las alcantarillas del diseño como puntos, añádelas (se ajustan
   a la celda de mayor acumulación en 25 m y se combinan con los cruces automáticos sin duplicar).
   Revisa la lluvia, el uso del suelo y, si la tienes, la capa de suelos. Pulsa **Ejecutar**.

El complemento:

- prepara el DEM (reproyección a UTM si está en grados, remuestreo si es muy grande, relleno de
  huecos pequeños) y lo **acondiciona**: relleno de depresiones con Priority-Flood (o breaching) y
  planicies resueltas con el gradiente superpuesto de Barnes (2014), con desempate por la pendiente
  del terreno suavizado para que los DEM de cotas enteras no desvíen el flujo en las terrazas;
- calcula direcciones y acumulación **D8**, la **red de cauces** por umbral de área (en hectáreas)
  con orden de Strahler, vectorizada de confluencia a confluencia sin limpieza manual;
- obtiene las **salidas**: intersección exacta cauce–eje, puntos dados ajustados, o ambos;
- delimita la **cuenca** de cada salida (sin islas, con anidamiento), mide el **recorrido más largo**
  exacto y entrega A, P, L, Hmáx, Hmín, ΔH, S = ΔH/L, S 10–85, pendiente media, cota media, Kc, Kf,
  depresiones cerradas y contacto con el borde del DEM;
- calcula **Tc** por Kirpich, Témez, California Culverts Practice, Bransby-Williams y retardo SCS,
  marcando las que salen de su rango de calibración, y el **caudal** racional y racional modificado
  de Témez por periodo de retorno (Dyck-Peschke o IDF de Hydrognomon), con CN de la tabla TR-55 y
  suelos por calicatas (Thiessen ponderado por área) o polígonos;
- opcionalmente repite todo con la **vía como barrera** (terraplén elevado salvo en las alcantarillas);
- carga las capas **con simbología** y escribe un **CSV** y un **informe HTML** con advertencias.

## Salidas

| Salida | Contenido |
|---|---|
| Cuencas (polígonos) | Una fila por salida y escenario con todos los parámetros, CN, Tc por fórmula y adoptado, y por cada Tr: Pd, I, C, Q racional, Q Témez y Q adoptado. |
| Salidas (puntos) | Progresiva, origen (cruce / punto / punto+cruce), desplazamiento del ajuste, área drenada, cota, caudal máximo. |
| Cauces (líneas) | Segmentos con orden de Strahler, área drenada y segmento aguas abajo. |
| Recorridos más largos (líneas) | Línea de flujo desde la celda más lejana hasta cada salida. |
| Rásters opcionales | Acumulación D8 (ha), dirección D8 (códigos ESRI), cuencas etiquetadas, acumulación MFD (Freeman 1991, solo visualización). |
| CSV | Una fila por salida y escenario, lista para pegar en la tesis. |
| Informe HTML | Datos de entrada, método, salidas, parámetros, comparación de Tc, caudales, advertencias (borde del DEM, fuera de rango, depresiones, represamiento) y limitaciones, con texto de sustento. |

Rendimiento: el DEM de prueba de 1 millón de celdas (12.5 m) se procesa completo, con ambos
escenarios y todos los rásters, en unos 16 s en Python puro.

## Documentación

- [Manual de parámetros](docs/MANUAL_PARAMETROS.md): qué es cada dato, su valor por defecto, por qué
  y cómo elegirlo; texto de sustento para la tesis.
- [Plan de diseño y decisiones de algoritmo](docs/PLAN.md).
- [Validación](docs/VALIDACION.md): pruebas analíticas, corrida sobre el DEM real y comparación con
  el procedimiento de GRASS.
- [Historial de cambios](CHANGELOG.md).

## Desarrollo

```bash
pip install numpy pytest
python -m pytest              # pruebas del núcleo con DEM analíticos (no necesitan QGIS)
python -m pytest              # con python3-gdal también corre la prueba de integración completa
python scripts/empaquetar.py  # genera dist/exutorios_viales.zip
```

Estructura:

```
exutorios_viales/
  acondicionar.py  Priority-Flood, breaching, D8, planicies (Barnes 2014 con distancias octiles)
  red.py           oleadas topológicas, acumulación D8/MFD, cauces + Strahler, cruces, cuencas, L
  hidrologia.py    Tc (5 fórmulas), CN (TR-55, AMC), lluvia (Dyck-Peschke / IDF), C y K de Témez, Q
  herramientas.py  eje y progresivas, intersección exacta, CSV, informe HTML
  algoritmo.py     algoritmos de Procesos (rápido y completo), preparación del DEM, estilos
  provider.py / plugin.py
tests/             pytest: superficies analíticas, fórmulas, integración con un sustituto de PyQGIS
scripts/           empaquetado del ZIP
docs/              manual, plan, validación
```

El resultado es referencial, apropiado para estudios a nivel de perfil. En el expediente técnico
debe validarse con topografía de detalle.

## Licencia

GPL-2.0 o posterior. Ver [LICENSE](LICENSE).

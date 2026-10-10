# Validación

Tres niveles: (1) pruebas automáticas con superficies analíticas, (2) corrida sobre el DEM real de
La Unión y (3) comparación con el procedimiento de GRASS. El nivel 3 queda abierto hasta contar
con el eje y las alcantarillas del proyecto (ver §3).

## 1. Pruebas automáticas (`python -m pytest`)

42 pruebas con numpy solo (46 con GDAL, que añade la ejecución completa del algoritmo con un
sustituto de PyQGIS). Casos con resultado conocido:

| Caso | Qué se comprueba | Resultado |
|---|---|---|
| Plano inclinado | Toda celda drena recto a la de abajo; sin depresiones; la cuenca de una celda del fondo es exactamente la columna/rectángulo aguas arriba. | A = 71.0 ha (7 100 celdas), exacto. |
| Valle en V (pendiente lateral 10 %, longitudinal 1 %) | Acumulación en el fondo = 71 filas × 100 columnas; L = 50 celdas al fondo + 70 por el valle; perímetro del rectángulo; Kc y Kf coherentes; el recorrido empieza en una esquina y termina en la salida. | L = 1 200 m, P = 3 420 m, exactos. |
| Cruce cauce–eje con eje en dos partes | Progresiva del cruce = longitud de la primera parte + distancia en la segunda. | 200 + 505 = 705 m, exacto. |
| Cuencas anidadas | Dos salidas sobre el mismo cauce: `anidada_en`, `contiene`, área total y área propia. | 41 y 71 filas; área propia 30 ha. |
| Cono invertido con sumidero central | Todo drena al centro; ninguna celda sin salida. | Correcto. |
| Cuenca cerrada (cubeta parabólica) | El relleno recupera el volumen del paraboloide (π r² h / 2) y vierte por el rebose; breaching la abre con 1 canal y la rellena si la longitud máxima no alcanza. | Volumen dentro del 8 %; 1 abierta / 0 rellenadas. |
| Planicie perfecta cerrada por tres lados | Todas las celdas salen por el lado bajo sin ciclos. | Correcto. |
| DEM de cotas enteras (plano suave cuantizado, gradiente a 14° del sur) | Ninguna celda sin salida; descenso monótono; más del 90 % del agua sale por el sur. | 97 % por el sur (con desempate suavizado; 47 % sin él, ver §2.2). |
| Árbol en Y explícito | Strahler 1 + 1 → 2, enlaces aguas abajo, área drenada antes de la confluencia, corte en salidas. | Exacto. |
| Fórmulas hidrológicas | Kirpich ≡ California; K de Témez (1.08 para Tc = 1.19 h) y C (0.25 para Pd = 139, Po = 48.3) de una hoja de cálculo de referencia; CN(III) de Chow; Dyck-Peschke; tres formas de IDF; tabla de lluvia. | Exacto. |
| Integración (GDAL) | Valle en V con vía: 1 cruce en 0+605, A = 97.2 ha, L = 1 400 m, puntos fusionados con el cruce, CN compuesto por Thiessen con AMC III, escenario con vía, rásters, CSV e informe. | Correcto. |

## 2. DEM real (La Unión, 12.5 m, 1 006 × 1 028 celdas, cotas enteras 12–53 m)

Archivo `datos_prueba/dem_la_union_12_5m.tif` (conversión a GeoTIFF del `Superficie_12.5x12.5.dem`
exportado desde CAD). Tiempos en Python puro, un núcleo (contenedor Linux):

| Paso | Tiempo |
|---|---|
| Relleno Priority-Flood + D8 + planicies | 5.2 s |
| Oleadas topológicas y acumulación (2 077 oleadas) | 0.2 s |
| Red de cauces (2 ha): 60 522 celdas, 3 595 segmentos | 0.2 s |
| 30 cuencas con parámetros | 1.6 s |
| Corrida completa (dos escenarios, 4 rásters, CSV, HTML) | 16–18 s |

Lo que dice el DEM: 25.4 % de las celdas están en depresiones cerradas (2 834 depresiones,
relleno medio 1.57 m, máximo 10 m). Con 2 ha la densidad de drenaje es 5.3 km/km² (Strahler hasta 5);
con el umbral de GRASS (10.94 ha) baja a 2.7 km/km² (764 segmentos). La celda de mayor
acumulación drena 49.3 km² hacia el sur.

### 2.1 Sensibilidad al acondicionamiento

Se tomaron 25 salidas al azar sobre cauces por clase de tamaño, se delimitó su cuenca con el método
por defecto (relleno + Barnes con desempate suavizado) y se repitió con los otros métodos
reubicando la salida en la celda de mayor acumulación a menos de 25 m:

| Clase de cuenca | Barnes puro (sin desempate): dif. de área mediana / p75 | Breaching: dif. de área mediana |
|---|---|---|
| 2–10 ha | 38 % / 93 % | 73 % |
| 10–50 ha | 11 % / 50 % | 91 % |
| 50–200 ha | 5 % / 87 % | 95 % |
| 200–1 000 ha | 4 % / 68 % | 95 % |

Conclusiones:

- **Las cuencas pequeñas (menos de 10 ha) no son delimitables con confianza en este DEM.** En
  terrazas de 1 m de resolución vertical y 33–100 m de ancho, la divisoria se mueve varias celdas
  con cualquier cambio del método; el área puede variar a la mitad o al doble. Trátalas como
  órdenes de magnitud y verifica en campo o con topografía.
- **Breaching no es comparable con relleno en este DEM:** abre zanjas de hasta 10 m a través de los
  escalones y reubica la red entera. Se mantiene como opción para DEM LiDAR con obstáculos reales,
  pero aquí el valor por defecto (relleno) es el correcto, como se anticipó en el plan.
- **El desempate por la pendiente suavizada importa:** sin él, la máscara de Barnes (distancias
  de tablero) empuja el flujo 45° en las terrazas inclinadas (en la prueba sintética solo el 47 %
  del agua salía por el lado bajo, frente al 97 % con desempate). Las cuencas medianas y grandes
  cambian poco (4–11 % en mediana), pero el p75 muestra que algunas sí.

### 2.2 Qué hacer con el DEM

Si existe, usar el DEM ALOS PALSAR RT1 original en decimales (no el exportado desde CAD, que está
redondeado al metro) reduce las terrazas y la incertidumbre. La preparación automática lo
reproyecta y rellena huecos igual.

## 3. Comparación con el procedimiento de GRASS (caso real)

Datos en `datos_prueba/la_union/` (DEM de GRASS de 1 637 × 1 569 celdas, cotas enteras de −2 a
61 m; eje de 4 275.63 m; 17 alcantarillas; polígonos y salidas de GRASS). Script reproducible:
`python3 scripts/validar_la_union.py [umbral_ha]` (necesita python3-gdal; usa el sustituto de
PyQGIS). Cada corrida completa (2.6 millones de celdas, 18 salidas, CSV e informe) tarda 20 s.

Nota: los valores de referencia del encargo (0.554 km², 4.435 km, 1 230 m, cotas 10.29–25.81) no
salen de estas capas; los valores de GRASS correctos, según el LEEME de los datos, son los de la
tabla. GRASS corrió con MFD, umbral de 700 celdas (10.94 ha), `r.water.outlet` y `r.lfp`.

### 3.1 Resultados (umbral 10.94 ha; con 2 ha las dos cuencas son idénticas)

| Cuenca | Fuente | Salida | A (ha) | P (km) | L (m) | Hmín salida | Hmín cuenca | Hmáx | S = ΔH/L | IoU |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | GRASS | 2+070 | 63.66 | 5.175 | 1 565.9 | – | 22 | 37 | 0.00958 | – |
| 1 | Exutorios | 2+140 (cruce) | 56.27 | 5.075 | 1 914.4 | 25 | 22 | 37 | 0.00627 | 0.81 |
| 2 | GRASS | 1+100 | 34.67 | 4.150 | 1 261.0 | – | 20 | 36 | 0.01269 | – |
| 2 | Exutorios | 1+109 (punto+cruce) | 33.09 | 3.575 | 1 219.1 | 22 | 20 | 35 | 0.01066 | 0.88 |

IoU = intersección / unión de los polígonos. Con la salida de GRASS de la cuenca 1 ajustada a
25 m (2+085) el complemento delimita solo 2.5 ha: ese punto cae sobre un afluente, no sobre el
cauce principal, que en el flujo D8 del complemento cruza el eje 70 m más adelante (2+140).

### 3.2 Lectura

- **Cuenca 2 (1+100):** coincidencia muy buena. Área −5 %, L −3 %, mismas cotas mínima de cuenca
  (20) y máxima (36 → 35 por el píxel de la divisoria). IoU 0.88. Las diferencias son del orden de
  una o dos celdas en la divisoria, lo esperable entre MFD + búsqueda de menor costo (GRASS) y
  relleno + Barnes (complemento).
- **Cuenca 1 (2+070):** coincidencia buena en el cuerpo de la cuenca (IoU 0.81, Hmáx y Hmín de
  cuenca iguales) pero el área es 12 % menor y L 22 % mayor. Dos causas: (a) el cauce principal
  corre casi paralelo al eje cerca del cruce y cada programa lo corta en un punto distinto (GRASS
  en 2+070, el complemento en 2+140), con lo que una franja de la cuenca cambia de lado; (b) el
  recorrido más largo del complemento entra por una cola de la cuenca con pendiente casi nula
  (S 10–85 = 0.0009) que GRASS no incluye. El Tc resultante (68 min) es mayor que el que daría la L
  de GRASS, es decir, el caudal del complemento (5.65 m³/s para Tr 71) es algo menor que el que se
  obtendría con los datos de GRASS y casi igual al del diseño actual en 2+070 (5.12 m³/s).
- **Hmín.** El complemento da dos valores: en la salida (`h_min`, para ΔH/L) y mínimo de la cuenca
  (`h_min_z`, el de la estadística de zona de GRASS, que cae en una depresión). GRASS usó el
  segundo para la pendiente; por eso su S es mayor. Para Tc lo correcto es el desnivel del recorrido.
- **Perímetro.** Ambos miden el polígono ráster; difieren con el área y la forma, no por método.

### 3.3 Cuál resultado es más confiable y por qué

Para la cuenca 2 ambos son equivalentes; para la cuenca 1 la discrepancia no es de programa sino
de dato: en un DEM de cotas enteras con pendientes de 0.6 a 1 %, la posición exacta donde un
cauce casi paralelo al eje lo cruza es incierta en decenas de metros, y con ella el reparto de
una franja de la cuenca. El complemento tiene a su favor que (1) el procedimiento es único,
reproducible y verificado (celdas sin salida = 0, polígono sin islas, L medida con la misma
definición que `r.lfp`), (2) reporta las señales de alerta (28 % y 18 % del área en depresiones
cerradas: el caudal racional es un límite superior) y (3) permite comprobar el punto de cruce con
la capa de cauces y de recorridos. La recomendación para la tesis: adoptar el complemento como
procedimiento, reportar la cuenca de GRASS como contraste, y para la obra de 2+070 verificar en
campo o con la topografía del proyecto si el cauce cruza en 2+070 o en 2+140 (70 m), porque de
ello depende un 12 % del área.

### 3.4 Las 17 alcantarillas (umbral 10.94 ha, cuenca natural, suelos grupo C por defecto)

| n | Progresiva | Tipo | A (ha) | L (m) | Tc (min) | Q Tr 35 | Q Tr 71 | Q del diseño |
|---|---|---|---|---|---|---|---|---|
| 1 | 0+080 | Alivio | 1.73 | 259 | 13.0 | 0.33 | 0.57 | 0.08 (Tr 35) |
| 2 | 0+320 | Igualación | 2.02 | 422 | 18.9 | 0.29 | 0.50 | 1.92 (Tr 71) |
| 3 | 0+690 | Alivio | 1.05 | 176 | 10.0 | 0.24 | 0.42 | 0.11 (Tr 35) |
| 4 | 0+840 | Alivio | 0.12 | 68 | 10.0 | 0.03 | 0.05 | 0.08 (Tr 35) |
| 5 | 1+100 | Igualación | 33.09 | 1 219 | 41.5 | 2.72 | 4.67 | 2.15 (Tr 71) |
| 6 | 1+490 | Alivio | 4.97 | 314 | 12.7 | 0.96 | 1.65 | 0.16 (Tr 35) |
| 7 | 1+680 | Obligatoria | 2.11 | 281 | 10.4 | 0.47 | 0.81 | 1.17 (Tr 71) |
| 8 | 2+070 | Igualación | 2.48 | 377 | 12.7 | 0.48 | 0.83 | 5.12 (Tr 71) |
| – | 2+140 | cruce automático | 56.27 | 1 914 | 68.2 | 3.28 | 5.65 | – |
| 9 | 2+320 | Alivio | 0.09 | 53 | 10.0 | 0.02 | 0.04 | 0.16 (Tr 35) |
| 10 | 2+500 | Obligatoria | 1.52 | 266 | 12.3 | 0.30 | 0.52 | 0.60 (Tr 71) |
| 11 | 2+940 | Alivio | 13.62 | 782 | 35.1 | 1.26 | 2.16 | 0.21 (Tr 35) |
| 12 | 3+150 | Igualación | 3.19 | 377 | 16.5 | 0.51 | 0.87 | 2.21 (Tr 71) |
| 13 | 3+480 | Alivio | 0.80 | 153 | 10.0 | 0.18 | 0.32 | 0.17 (Tr 35) |
| 14 | 3+660 | Obligatoria | 5.03 | 467 | 19.4 | 0.71 | 1.23 | 1.35 (Tr 71) |
| 15 | 3+760 | Obligatoria | 10.39 | 645 | 24.0 | 1.26 | 2.17 | 1.33 (Tr 71) |
| 16 | 3+920 | Obligatoria | 5.03 | 364 | 11.7 | 1.03 | 1.77 | 0.47 (Tr 71) |
| 17 | 4+080 | Obligatoria | 1.95 | 181 | 10.0 | 0.45 | 0.77 | 0.47 (Tr 71) |

Observaciones para el diseño (no son conclusiones del complemento, sino lo que el DEM muestra):

- La obra de **2+070** recibe en el DEM solo 2.5 ha; el cauce de 56 ha cruza en **2+140**. O la
  obra se desplaza, o se confirma en campo que es el mismo cauce.
- **2+940 (alivio)** drena 13.6 ha y **1+490 (alivio)** 5 ha en el DEM: más que una faja de
  bordillo. Conviene revisarlas como obras de cruce.
- Las de alivio restantes drenan menos de 2 ha, coherente con su función.
- Las cuencas de **0+320** y **3+150** (igualación) son pequeñas en el DEM (2 y 3 ha) frente a los
  caudales del diseño (1.9 y 2.2 m³/s): el diseño considera el volumen represado en la depresión,
  que el método racional no ve. Para ellas vale el análisis de «Cota de Anegamiento».
- Los caudales del complemento usan grupo hidrológico C por defecto; con las calicatas (A/B/D/C/A)
  cambiarán. Las progresivas de los puntos difieren ±10 m de las nominales por el ajuste a la
  celda de mayor acumulación.

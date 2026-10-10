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

## 3. Comparación con el procedimiento de GRASS

Las dos cuencas de referencia de la tesis:

| | A (km²) | P (km) | L (m) | Hmín–Hmáx | S |
|---|---|---|---|---|---|
| Cuenca 1 (GRASS) | 0.554 | 4.435 | 1 230 | 10.29–25.81 | 0.0126 |
| Cuenca 2 (GRASS) | 0.341 | 3.288 | 1 014 | 9.83–24.32 | 0.0143 |

Para reproducirlas hacen falta tres cosas que no están en el repositorio: el **eje** (DXF o GPKG),
los **17 puntos** de alcantarillas y los **polígonos de GRASS** (o al menos las coordenadas de las
dos salidas). Además, las cotas mínimas de GRASS (10.29 y 9.83 m) están por debajo del mínimo del
DEM entregado (12 m): el procedimiento de GRASS se corrió sobre otro DEM (probablemente el ALOS
PALSAR original en decimales), así que la comparación debe hacerse con ese mismo DEM.

Cómo hacerla cuando estén los archivos (10 min en QGIS):

1. Ejecutar «Cuencas de alcantarillas (análisis rápido)» con el DEM de GRASS, el eje y los 17
   puntos; en avanzados, umbral 10.94 ha (para igualar `r.watershed`).
2. En la capa de salidas, localizar las dos salidas por progresiva y leer en la capa de cuencas
   `area_km2`, `perim_km`, `l_m`, `h_min`, `h_max`, `s_l`.
3. Pegar los valores en esta tabla y en el informe.

Diferencias esperables y cuál resultado es más confiable:

- **Área.** GRASS `r.watershed` usa MFD (flujo múltiple) para la acumulación y `r.water.outlet`
  D8 para la cuenca; las divisorias en planicies dependen de cómo cada programa resuelve las zonas
  planas (GRASS usa una búsqueda de menor costo sin rellenar). Con relleno + Barnes la divisoria
  sigue la cota de rebose real de cada depresión, que es donde físicamente se reparte el agua
  cuando las depresiones se llenan. Diferencias del 5–15 % en cuencas de 0.3–0.6 km² son normales;
  mayores indican una depresión grande cerca de la divisoria (ver `n_dep`, `vol_dep`). En ese caso
  el valor del complemento es el conservador (cuenca con todo lo que vierte al llenarse) y además
  el informe lo señala.
- **Perímetro y Kc.** Ambos miden el polígono ráster escalonado; deben coincidir si la cuenca
  coincide. Los píxeles sueltos e islas de GRASS (eliminados a mano) aquí no existen: el polígono
  es la parte conectada que contiene la salida.
- **L.** `r.lfp` y el complemento miden la misma magnitud (distancia de flujo D8 máxima con pasos
  diagonales de √2); la diferencia solo puede venir de la cuenca o del acondicionamiento.
- **Cotas.** Hmín aquí es la cota del DEM en la celda de salida; en GRASS la estadística de zona
  toma el mínimo de la cuenca, que puede estar en una depresión y no en la salida. El complemento
  usa la salida porque ΔH/L se refiere al recorrido.
- **Pendiente.** `s_l` = ΔH/L coincide en definición con la de GRASS; se añade `s_1085`, más
  representativa en terreno plano.
- **Confiabilidad.** Dado el mismo DEM, el resultado del complemento es más trazable: una sola
  corrida reproducible, sin pasos manuales, con verificación de celdas sin salida, cuencas sin islas
  y avisos de borde y depresiones. Pero la fuente dominante de incertidumbre no es el programa sino
  el DEM: con cotas enteras, las cuencas menores de 10 ha son inciertas en un factor 2 (§2.1), y
  ningún procedimiento ráster puede mejorarlas sin topografía.

# Manual de parámetros: criterios para llenar cada dato de entrada

Complemento QGIS «Exutorios Viales» v1.0. Explica, parámetro por parámetro, qué es cada dato,
el valor por defecto, por qué ese valor y cómo elegirlo. Al final hay un texto de sustento
metodológico para la tesis y la lista de fuentes.

Obligatorios: el **DEM** y el **eje de la vía**. Los valores por defecto están pensados para el caso
de La Unión (Bajo Piura): DEM de 12.5 m con cotas enteras, terreno casi plano, lluvias de
Log-Pearson III y cultivos en hileras; en otra zona revisa al menos la lluvia, el uso del suelo y
el umbral de cauce.

## 1. Datos de entrada principales

### DEM (modelo digital de elevación)
- **Qué es:** ráster de cotas (msnm). Puede estar en grados (se reproyecta solo a la zona UTM que
  corresponde a su centro) o en metros. Si supera 6 millones de celdas se remuestrea.
- **Criterios:** debe cubrir **toda** la cuenca de cada alcantarilla; con 2 a 3 km de margen fuera
  del eje en terreno plano. El informe avisa de cada cuenca que toca el borde del DEM (campo
  `borde`): esa área puede estar incompleta.
- **Cotas enteras:** el complemento lo detecta y lo anota. Con resolución vertical de 1 m y
  pendientes de 1 a 3 % el terreno queda en terrazas de 33 a 100 m; las divisorias dentro de una
  terraza son inciertas en varias celdas. Si tienes el DEM original en decimales (ALOS PALSAR RT1
  en float), úsalo en lugar del exportado desde CAD.

### Eje de la vía (líneas)
- **Qué es:** el trazo de la vía. Acepta DXF con `CompoundCurveZ` (se segmenta y se descarta la Z)
  y varias partes: las partes se **concatenan en el orden en que vienen** y la progresiva 0+000 es
  el primer vértice de la primera parte, igual que en «Cota de Anegamiento».
- **Criterio:** si el DXF trae las partes desordenadas, únelas antes (Vectorial › Geoprocesamiento ›
  Disolver, o «Unir líneas») y comprueba en la capa de salidas que las progresivas crecen en el
  sentido del kilometraje del proyecto.

### Alcantarillas del diseño (puntos, opcional) y campo de nombre
- **Qué es:** las obras ya ubicadas (las 17 progresivas del diseño). Cada punto se **ajusta a la
  celda de mayor acumulación** dentro del radio de ajuste (25 m) y se reporta cuánto se movió
  (`despl_m`). El campo de nombre (progresiva, código) se copia a las salidas y cuencas.
- **Criterio:** dibuja los puntos sobre el eje. Si un punto queda a más de 100 m del eje se avisa;
  su progresiva es la del punto más cercano del eje.

### Modo de salidas
- **Cruces automáticos cauce–eje:** las salidas son las intersecciones exactas de la red de
  cauces (por umbral) con el eje. Sirve para descubrir dónde hacen falta obras.
- **Solo los puntos dados:** solo las alcantarillas del diseño.
- **Ambos sin duplicar (por defecto):** los puntos dados más los cruces automáticos que no estén
  a menos de la distancia de fusión (30 m) de un punto. En una fusión se conserva el punto del
  diseño (origen `punto+cruce`). Si no das puntos, equivale al primer modo.

### Umbral de cauce (ha)
- **Qué es:** área drenada mínima para que una celda sea cauce. Se pide en hectáreas y el registro
  muestra la equivalencia en celdas (2 ha = 128 celdas de 12.5 m).
- **Por defecto 2 ha.** Detecta las cuencas de 1 a 5 ha de las obras de alivio, que con el umbral
  de GRASS (700 celdas = 10.94 ha) no aparecían. Para reproducir el procedimiento anterior usa
  10.94. Valores menores de 0.5 ha generan miles de cauces de ruido en DEM de cotas enteras.
- **Efecto:** solo cambia qué cruces automáticos aparecen; las cuencas de los puntos dados no
  dependen del umbral.

### Lluvia máxima diaria por periodo de retorno
- **Formato:** `Tr:Pd; Tr:Pd; …` en mm. Por defecto `25:58.5; 35:70.6; 71:101.7` (Log-Pearson III
  de Hydrognomon para La Unión).
- **Criterio:** los periodos de retorno que exige el Manual de Hidrología, Hidráulica y Drenaje del
  MTC según el tipo de obra (alcantarillas: Tr de 25 a 50 años; vida útil y riesgo admisible).
  Se calcula el caudal para cada Tr de la tabla.

### Uso del suelo para el CN
- Tabla TR-55 (USDA-NRCS, 1986). Por defecto **cultivos en hileras, surcos rectos, condición
  buena** (CN 67/78/85/89 para A/B/C/D). Otras filas: cereales, barbecho, pastizal, matorral,
  bosque, matorral desértico, residencial, pavimentos.
- **Criterio:** el uso dominante de las cuencas. Para una cuenca con usos mixtos, usa polígonos de
  suelos con un campo de CN ya compuesto.

### Condición de humedad antecedente (AMC)
- **II (por defecto):** condición media, la de las tablas. **III:** suelo húmedo antes del evento;
  conversión de Chow, Maidment y Mays (1988): CN(III) = 23·CN(II)/(10 + 0.13·CN(II)).
- **Criterio:** AMC III para quedar del lado seguro en eventos El Niño (lluvias de varios días).

### Suelos (opcional) y campo de grupo / CN
- **Calicatas (puntos):** campo con el grupo hidrológico (A, B, C o D; también «grupo C») o un CN
  numérico. Cada celda de la cuenca toma el valor de la **calicata más cercana (Thiessen)** y el CN
  de la cuenca es el promedio ponderado por área (campo `cn_detalle`: «A 60%, B 40%; AMC II»).
- **Polígonos:** mapa de suelos o de CN; se rasteriza y se pondera por área.
- **Sin capa:** se usa el grupo hidrológico por defecto (C) con el uso elegido, o el CN directo.

### Grupo hidrológico por defecto y CN directo
- **Grupo por defecto C:** conservador para suelos francos a arcillosos del valle. En La Unión las
  calicatas dan A, B, C y D: conviene dar la capa de calicatas.
- **CN directo (0 = no usar):** fuerza un mismo CN en todas las cuencas (por ejemplo para una
  corrida de sensibilidad).

### La vía como barrera y altura del terraplén
- **Qué hace:** eleva el eje en el DEM (3 m por defecto) salvo en las celdas de cada salida y en
  las celdas de la vía por donde pasa su cauce natural, y repite todo el análisis (escenario
  `con_via`). El agua que llega al terraplén se represa y corre por su pie hasta la alcantarilla
  **más baja que alcance el embalse**; cada salida se reubica en la celda de mayor acumulación
  dentro del radio de ajuste.
- **Interpretación:** si una alcantarilla pierde su cuenca en `con_via`, el informe dice por cuál
  salida vierte el agua represada. En terreno plano con cotas enteras eso significa que el DEM no
  distingue entre dos alcantarillas cercanas: la decisión final se toma con la topografía del
  proyecto y las cunetas de pie de talud, que el complemento no modela.
- **Criterio:** usa la altura tentativa del terraplén del proyecto (1 a 3 m). El escenario natural
  sigue siendo la base del diseño; `con_via` es una verificación del represamiento.

## 2. Parámetros avanzados

| Parámetro | Criterio | Por defecto |
|---|---|---|
| Radio para ajustar cada punto (m) | Debe cubrir el error de ubicación del punto y 1 a 2 celdas; 2 celdas (25 m con 12.5 m) es suficiente. 0 = no ajustar. | 25 |
| Fusionar salidas a menos de (m) | Un cruce automático a menos de esta distancia de un punto dado se considera la misma obra. Usa 1 a 3 celdas. | 30 |
| Agrupar cortes cauce–eje a menos de (m de progresiva) | Un cauce que serpentea puede cortar el eje varias veces en pocos metros: los cortes a menos de esta distancia son un solo cruce (se toma la celda de mayor acumulación). 3 celdas. | 40 |
| Tratamiento de depresiones | **Rellenar** (Priority-Flood): vierte cada depresión por su punto de rebose real; recomendado en terreno plano y en DEM de cotas enteras, donde las «depresiones» son escalones de 1 m. **Abrir/romper** (breaching de Lindsay): abre un canal de menor costo desde cada fosa hasta terreno más bajo, con longitud máxima; lo que no se abre se rellena. Útil con LiDAR donde las depresiones son terraplenes o puentes. En el DEM de La Unión las áreas difieren poco entre ambos (ver docs/VALIDACION.md). | Rellenar |
| Breaching: longitud máxima (celdas) | Canales más largos no se abren y la depresión se rellena. 50 celdas = 625 m. | 50 |
| Suavizar el DEM 3×3 | Media móvil antes del análisis; reduce el ruido pero rebaja las cotas de los cauces. Solo para comparar. | No |
| Factor lluvia 24 h / diaria | Hershfield (1961): 1.13 convierte la máxima diaria de observación a hora fija en máxima de 24 h móviles; la OMM lo recomienda. Si la serie ya es de 24 h móviles, 1.0. | 1.13 |
| Intensidad de lluvia | **Dyck-Peschke**: P_d = P24·(d/1440)^0.25 (d en min), la relación que usa el Manual del MTC; **IDF de Hydrognomon** (Koutsoyiannis et al., 1998): i(d,T) = a(T)/(1+d/θ)^η con d en horas, a(T) Gumbel = λ(ψ − ln(−ln(1−1/T))) o GEV = λ'(T^κ' − ψ'); **Sherman**: I = K·T^m/(d+θ)^η con d en minutos. Copia los parámetros tal como los entrega Hydrognomon (módulo «Ombrian curves»). | Dyck-Peschke |
| IDF: λ, κ, ψ, θ, η | Parámetros de la curva elegida (λ o λ' o K; κ' o m; ψ o ψ'; θ; η). | 0 |
| Tiempo de concentración mínimo (min) | Las fórmulas dan valores irreales en cuencas de pocas hectáreas; el MTC y la práctica usan 10 min como mínimo. | 10 |
| Tc adoptado | Media (por defecto), mediana, mínimo o máximo de las fórmulas que están dentro de su rango de calibración, o una fórmula fija. Si ninguna está en rango se usan todas. | Media de las válidas |
| Coeficiente C del racional clásico | 0 = usar el C de Témez (función de Pd y CN); si el estudio fijó un C tabulado, ponlo aquí (solo afecta al Q racional clásico). | 0 |
| Caudal adoptado | Racional modificado de Témez (K ≥ 1, más conservador), racional clásico o el mayor. | Témez |
| Avisar si las depresiones superan este % del área | Umbral del aviso «el caudal es un límite superior». | 5 |
| Tamaño de celda de trabajo (m) | 0 = conservar la celda del DEM (o agrandarla si supera 6 M de celdas). | 0 |
| Rellenar huecos sin datos de hasta N celdas | Interpola huecos interiores pequeños; los que tocan el borde no se rellenan. | 10 |

## 3. Cómo leer los resultados

### Parámetros geomorfológicos (capa de cuencas y CSV)
- `area_ha`, `area_km2`: celdas de la cuenca total (incluye las cuencas anidadas aguas arriba);
  `a_propia`: solo el área entre esta salida y las salidas aguas arriba.
- `perim_km`: perímetro del polígono ráster (escalonado). Es el mismo que mide GRASS sobre el
  polígono de `r.water.outlet`; sobrestima el perímetro real y por tanto Kc.
- `l_m`: recorrido más largo exacto: máxima distancia de flujo D8 (pasos ortogonales = celda,
  diagonales = celda·√2) desde cualquier celda hasta la salida. Equivale a `r.lfp`.
- `h_max`, `h_min` (cota en la salida), `h_min_z` (cota mínima de toda la cuenca, como la estadística
  de zona de GRASS; suele caer en una depresión), `dh` = Hmáx − Hmín en la salida, `s_l` = ΔH/L, `s_1085`: pendiente entre el 10 % y el
  85 % del recorrido (Gray, 1961; USGS), `s_cuenca`: pendiente media de la cuenca con el operador
  de Horn sobre el DEM original, `h_media`, `kc` = 0.28·P/√A (Gravelius), `kf` = A/L² (Horton).
- `n_dep`, `vol_dep`, `frac_dep`: depresiones cerradas del DEM original dentro de la cuenca
  (número, volumen de relleno en m³ y fracción del área). `borde`: la cuenca toca el borde del DEM.
- `anidada`: id de la salida aguas abajo que la contiene; `contiene`: salidas aguas arriba.

### Tc y caudales
- `tc_kirp`, `tc_temez`, `tc_calif`, `tc_bw`, `tc_scs`: minutos sin el mínimo aplicado;
  `tc_fuera`: por qué una fórmula sale de rango; `tc_adopt` y `tc_crit`.
- Por cada Tr (sufijo `_25`, `_35`, `_71`…): `pd` (lluvia diaria), `i` (mm/h para d = Tc), `c`
  (C de Témez), `qr` (racional), `qt` (Témez), `q` (adoptado), y `k_temez`.

### Advertencias del informe
- **Toca el borde del DEM:** consigue un DEM más amplio o acepta el área como mínima.
- **Depresiones cerradas:** el método racional supone que toda la cuenca aporta; con muchas
  depresiones el caudal es un límite superior (parte del agua se almacena). Para evaluar el
  almacenamiento usa «Cota de Anegamiento».
- **Fuera de rango:** Kirpich y California se calibraron en cuencas de 0.5 a 45 ha con pendientes
  de 3 a 10 %; en el Bajo Piura (1 a 3 %) tienden a subestimar Tc y sobrestimar Q. Témez se ajustó
  con cuencas mayores de 1 km². El retardo SCS vale hasta 8 km² y CN 50–95. Bransby-Williams no
  tiene rango publicado. Por eso el criterio por defecto promedia solo las fórmulas en rango.
- **Con la vía como barrera la cuenca baja:** ver «La vía como barrera».

## 4. Corridas recomendadas para la tesis

1. Análisis rápido con DEM, eje y los 17 puntos, suelos por calicatas, AMC II (base).
2. Igual con AMC III (sensibilidad a la humedad).
3. Igual con «vía como barrera» (verificación del represamiento y de alcantarillas redundantes).
4. Umbral 10.94 ha para reproducir y comparar con el procedimiento de GRASS.

Adopta para cada obra el mayor caudal entre 1 y 2, y revisa en 3 las obras cuya cuenca cambia.

## 5. Texto de sustento metodológico (para la tesis)

> La delimitación de las cuencas de aporte de las obras de cruce se realizó sobre el modelo
> digital de elevación con el complemento QGIS «Exutorios Viales», que implementa el procedimiento
> estándar de hidrología de terreno: acondicionamiento hidrológico del DEM mediante relleno de
> depresiones con el algoritmo Priority-Flood (Barnes, Lehman y Mulla, 2014a) y asignación de
> direcciones en las zonas planas con el gradiente superpuesto de Barnes, Lehman y Mulla (2014b);
> direcciones de flujo por máxima pendiente D8 (O'Callaghan y Mark, 1984) y acumulación de flujo;
> extracción de la red de drenaje por umbral de área con orden de Strahler (1957); identificación de
> las salidas por intersección de la red con el eje de la vía y por la ubicación de las alcantarillas
> proyectadas; delimitación de la cuenca de cada salida como el conjunto de celdas cuyo camino de
> flujo pasa por ella; y cálculo de los parámetros morfométricos (área, perímetro, longitud del
> recorrido más largo, cotas, pendientes, índice de compacidad de Gravelius y factor de forma de
> Horton). El tiempo de concentración se estimó con las fórmulas de Kirpich (1940), Témez (1978),
> California Culverts Practice (1942), Bransby-Williams (1922) y del retardo del SCS (NRCS, 2010),
> adoptando el promedio de las que se encuentran dentro de su rango de calibración y un mínimo de
> 10 min. El caudal de diseño se obtuvo con el método racional modificado de Témez (1991), con el
> coeficiente de escorrentía en función de la precipitación diaria y del umbral de escorrentía
> equivalente al número de curva (TR-55, USDA-NRCS, 1986) y la intensidad de lluvia para una
> duración igual al tiempo de concentración, derivada de la lluvia máxima de 24 h (lluvia diaria de
> Log-Pearson III por el factor 1.13 de Hershfield) con la relación de Dyck-Peschke que adopta el
> Manual de Hidrología, Hidráulica y Drenaje del MTC. Los resultados son referenciales y se
> validarán con topografía de detalle en el expediente técnico.

## 6. Fuentes

- Barnes, R., Lehman, C., Mulla, D. (2014a). Priority-flood: an optimal depression-filling and
  watershed-labeling algorithm for digital elevation models. *Computers & Geosciences* 62, 117–127.
- Barnes, R., Lehman, C., Mulla, D. (2014b). An efficient assignment of drainage direction over flat
  surfaces in raster digital elevation models. *Computers & Geosciences* 62, 128–135.
- Lindsay, J. B. (2016). Efficient hybrid breaching-filling sink removal methods for flow path
  enforcement in digital elevation models. *Hydrological Processes* 30, 846–857.
- O'Callaghan, J. F., Mark, D. M. (1984). The extraction of drainage networks from digital elevation
  data. *Computer Vision, Graphics, and Image Processing* 28, 323–344.
- Freeman, T. G. (1991). Calculating catchment area with divergent flow based on a regular grid.
  *Computers & Geosciences* 17, 413–422.
- Strahler, A. N. (1957). Quantitative analysis of watershed geomorphology. *Trans. AGU* 38, 913–920.
- Kirpich, Z. P. (1940). Time of concentration of small agricultural watersheds. *Civil Engineering*
  10(6), 362.
- Témez, J. R. (1978). Cálculo hidrometeorológico de caudales máximos en pequeñas cuencas
  naturales. MOPU, Madrid. — Témez, J. R. (1991). Extended and improved rational method. *XXIV IAHR
  Congress*, Madrid. — Instrucción 5.2-IC Drenaje superficial (1990).
- California Highways and Public Works (1942). California Culverts Practice.
- Bransby Williams, G. (1922). Flood discharge and the dimensions of spillways in India. *The
  Engineer* 134, 321–322. — Pilgrim, D. H., Cordery, I. (1993). Flood runoff. En *Handbook of
  Hydrology*, cap. 9.
- USDA-NRCS (2010). National Engineering Handbook, Part 630 Hydrology, cap. 15 Time of
  concentration. — USDA-NRCS (1986). Urban hydrology for small watersheds, TR-55.
- Chow, V. T., Maidment, D. R., Mays, L. W. (1988). *Applied Hydrology*. McGraw-Hill.
- Hershfield, D. M. (1961). Rainfall frequency atlas of the United States. Weather Bureau TP-40.
- Koutsoyiannis, D., Kozonis, D., Manetas, A. (1998). A mathematical framework for studying rainfall
  intensity-duration-frequency relationships. *Journal of Hydrology* 206, 118–135.
- MTC (2011). Manual de Hidrología, Hidráulica y Drenaje. Ministerio de Transportes y
  Comunicaciones, Perú.
- Gray, D. M. (1961). Interrelationships of watershed characteristics. *J. Geophys. Res.* 66, 1215–1223.

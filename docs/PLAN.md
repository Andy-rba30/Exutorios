# Plan de diseño: complemento QGIS «Exutorios Viales» (cuencas de alcantarillas)

Documento corto de decisiones, previo a la programación (aprobado; implementado en la versión 1.0.0).
Cambio respecto al plan: la máscara de planicies de Barnes se calcula con distancias octiles y se
desempata por la pendiente del terreno suavizado, porque las distancias «de tablero» del método
original sesgaban el flujo 45° en las terrazas de los DEM de cotas enteras (ver docs/VALIDACION.md).

## 1. Estructura (calcada de «Cota de Anegamiento»)

```
exutorios_viales/
  __init__.py, plugin.py, provider.py, metadata.txt, icon.png, LEEME.txt
  acondicionar.py   relleno Priority-Flood, zonas planas (Barnes 2014), breaching (Lindsay 2016), D8
  red.py            acumulación D8 (y MFD opcional), cauces + Strahler, cruces, cuencas, recorrido más largo
  hidrologia.py     Tc (5 fórmulas), CN compuesto, lluvia (Dyck-Peschke / IDF), C de Témez, Q racional
  herramientas.py   eje y progresivas (mismo cálculo que «Cota»), CSV, informe HTML
  algoritmo.py      «Cuencas de alcantarillas» (rápido) y «… (completo)», preparación del DEM, estilos
tests/              pytest con el stub de PyQGIS reutilizado; DEM sintéticos analíticos
scripts/empaquetar.py, docs/MANUAL_PARAMETROS.md, CHANGELOG.md, LICENSE (GPL-2.0-or-later), CI
```

Solo numpy + GDAL/OGR (los que trae QGIS). Nada de GRASS, SAGA ni scipy obligatorio.
Compatibilidad 3.16 → 3.40+, Qt5/Qt6, con los mismos «try/except» de la API que usa «Cota».

## 2. Decisiones de algoritmo

### 2.1 Depresiones: RELLENO por defecto (Priority-Flood), breaching como opción
- **Relleno** = Priority-Flood (Barnes, Lehman y Mulla, 2014a), igual que «Cota de Anegamiento», lo
  que mantiene coherencia entre los dos complementos: la cota de rebose de cada depresión es la misma.
- **Por qué relleno en el Bajo Piura:** el DEM tiene cotas enteras, así que casi todas las «depresiones»
  son escalones de 1 m de la cuantización, no cubetas reales. El breaching abre zanjas de 1 celda de
  ancho y hasta 1 m de hondo a través de esos escalones e impone cauces que el dato no sustenta; el
  relleno vierte cada depresión por su punto de rebose real (el más bajo del borde), que es por donde
  saldría el agua cuando la depresión se llena. Las áreas de cuenca resultan casi iguales con ambos; la
  diferencia está en el trazo del cauce dentro de la depresión, y las depresiones se reportan aparte.
- **Breaching** (opción «abrir/romper»): híbrido de Lindsay (2016): desde cada fosa, búsqueda de
  menor costo hasta una celda más baja, con longitud máxima configurable (por defecto 100 celdas);
  se rebajan las celdas del camino; lo que no se pudo abrir se rellena. Útil con DEM LiDAR donde las
  depresiones son terraplenes o puentes.
- **Verificación obligatoria:** tras acondicionar, ninguna celda válida queda sin receptor salvo las
  que salen por el borde o por un hueco sin datos; se cuenta y se informa en el registro.

### 2.2 Zonas planas: asignación de Barnes, Lehman y Mulla (2014b)
- Sobre el DEM rellenado se detectan las celdas planas (sin vecino más bajo) y se les asigna un
  gradiente artificial con las dos pasadas en anchura del artículo: alejándose del terreno más alto
  y acercándose a las celdas de salida de la planicie; se suman y se obtiene D8 sobre ese gradiente.
- Motivo: con cotas enteras y pendientes de 1 a 3 %, cada «terraza» mide de 33 a 100 m (3 a 8
  celdas); casi todo el DEM es terraza. El puntero del Priority-Flood sesga el flujo hacia un lado
  (ya se corrigió ese defecto en «Cota» 1.1.0); el método de Barnes da direcciones que convergen al
  rebose real y respetan el terreno alto, y es determinista (no depende del orden de visita).
- Opción avanzada, desactivada por defecto: suavizado 3×3 del DEM antes del análisis, para comparar.

### 2.3 Direcciones y acumulación
- **D8** para todo lo que se mide (cuencas, L, cauces): determinista y trazable.
- Acumulación por «oleadas» topológicas vectorizadas en numpy (orden de Kahn): O(N) total, sin
  bucle Python por celda. El mismo orden sirve para cuencas, distancia de flujo y L.
- **MFD** (Freeman 1991, exponente 1.1) solo como ráster de visualización, opcional.

### 2.4 Umbral de cauce: 2 ha por defecto
- Se pide en hectáreas y se convierte a celdas (12.5 m → 128 celdas; se escribe la equivalencia en
  el registro). 2 ha detecta las obras de alivio de 1 a 5 ha; el valor de GRASS (10.94 ha) se
  conserva como ejemplo en el manual para reproducir el procedimiento anterior.
- Cauces vectorizados directamente desde el ráster de flujo: segmentos de confluencia a
  confluencia (cabecera → unión), con orden de Strahler, área drenada y longitud. Sin r.thin ni
  limpieza manual: la topología sale limpia porque cada celda tiene un solo receptor.

### 2.5 Salidas (exutorios)
- **Cruces automáticos:** intersección geométrica exacta de cada segmento de cauce (polilínea por
  centros de celda) con el eje; los puntos de corte a menos de 3 celdas se funden en un cruce y se
  toma como salida la celda de cauce de mayor acumulación en el cruce. Progresiva = distancia a lo
  largo del eje concatenando partes (misma función que «Cota de Anegamiento»).
- **Puntos dados:** se ajustan a la celda de mayor acumulación en un radio (25 m por defecto); se
  guarda el desplazamiento.
- **Modo por defecto:** «ambos sin duplicar» (fusión a menos de 30 m, configurable); si no hay capa
  de puntos equivale a «cruces automáticos».
- **La vía como barrera (opcional):** 1) se acondiciona el DEM natural y se fijan las salidas;
  2) se eleva el eje (rasterizado con 4 vecinos, sin fugas diagonales) 3 m salvo en las celdas de
  salida; 3) se vuelve a acondicionar y calcular. El agua que llega al terraplén corre por el pie
  hasta la alcantarilla más cercana. Se entregan ambas cuencas (natural y con vía).

### 2.6 Cuencas y parámetros
- Cuenca = todas las celdas cuyo camino D8 llega a la salida (una pasada aguas abajo → etiqueta
  de la primera salida que encuentra; la cuenca total de una salida incluye las anidadas).
- Polígono: poligonizar con GDAL, disolver, quedarse con la parte conectada que contiene la salida
  (sin islas ni píxeles sueltos). Campo `contiene` y `dentro_de` para las cuencas anidadas.
- L exacto: distancia de flujo aguas abajo (1 o √2 celdas por paso) acumulada por oleadas; L = máximo
  en la cuenca; se guarda la línea del recorrido.
- Parámetros: A (ha, km²), P (km, del polígono), L (m), Hmáx, Hmín (salida), ΔH, S = ΔH/L, S 10–85
  sobre el recorrido, pendiente media de la cuenca (gradiente de Horn), cota media, Kc, Kf, número /
  volumen / fracción de área de depresiones cerradas (relleno − DEM), `toca_borde` del DEM.

### 2.7 Hidrología (todas las fórmulas se verificarán en fuente primaria y se citarán)
- **Tc:** Kirpich (1940), Témez (1978), California Culverts Practice (1942, algebraicamente igual
  a Kirpich: se mostrará esa nota), Bransby-Williams (1922), retardo SCS (NRCS NEH-630 cap. 15,
  Tc = lag/0.6). Cada una con su rango de validez (pendiente, área, L, CN) y marca «fuera de rango»;
  Tc mínimo 10 min (configurable). Tc adoptado configurable (por defecto: media de las válidas).
- **CN:** tabla SCS por grupo hidrológico (A/B/C/D) y uso (cultivos en hileras por defecto); AMC II
  o III (conversión de Chow). Calicatas: Thiessen por celda → fracción de área por grupo → CN
  compuesto por cuenca. Polígonos: rasterizados por campo de grupo o de CN.
- **Lluvia:** tabla Tr → Pd; P24 = Pd × 1.13 (configurable). Intensidad por Dyck-Peschke
  (P(d) = P24·(d/1440)^0.25) o IDF de Hydrognomon i(d,T) = a(T)/b(d), b(d) = (1+d/θ)^η, con
  a(T) de Gumbel [λ(ψ − ln(−ln(1−1/T)))] o GEV [λ'(T^κ' − ψ')] (Koutsoyiannis et al., 1998).
- **Q:** racional Q = 0.278·C·I·A; racional modificado de Témez con C = (Pd−Po)(Pd+23Po)/(Pd+11Po)²,
  Po = 5080/CN − 50.8 (exacto; 5000/CN − 50 es su redondeo) y K = 1 + Tc^1.25/(Tc^1.25 + 14).
  Aviso cuando las depresiones cerradas superan una fracción (5 %) del área: Q es límite superior.

## 3. Salidas
Cauces, salidas, cuencas (natural y con vía), recorridos, rásters opcionales (acumulación,
dirección, cuencas, MFD), CSV y HTML, todo con simbología como en «Cota de Anegamiento».

## 4. Pruebas analíticas (sin QGIS)
Plano inclinado (cuenca = columna, L = n·celda), valle en V (L = media anchura + tramo), cono
invertido (L exacto en D8 = celda·(máx − mín + mín·√2)), cuenca cerrada (ninguna celda sin salida,
volumen de la depresión), planicie perfecta (todas las celdas drenan al lado bajo), DEM de cotas
enteras, cruce cauce–eje y progresiva en un valle sintético, ajuste de puntos, Tc y Q con valores
de referencia publicados.

## 5. Rendimiento
Objetivo: 1 M de celdas ≈ 15 s, 6 M ≈ 2 min (Priority-Flood en Python puro como «Cota»; el resto
vectorizado). Progreso y cancelación en todas las fases.

## 6. Validación con el caso real
Necesito en el repositorio o en la sesión: el DEM (GeoTIFF), el eje (DXF/GPKG), los 17 puntos y las
dos cuencas de GRASS. Sin esos archivos, el informe comparativo lo redacto con los valores que diste
y con una corrida tuya en QGIS; aquí no puedo descargar el DEM ALOS PALSAR.

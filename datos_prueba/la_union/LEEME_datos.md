# Datos para cerrar la validación del complemento de exutorios

Vía de evitamiento, La Unión, Piura. Todas las capas están en **EPSG:32717 (WGS 84 / UTM 17S)**.

## 1. Eje de la vía

- `eje_via.gpkg`: una sola línea de 4 275.63 m. Viene de `EJE_VIA_DE_EVITAMIENTO_UNIDO.dxf`, una LWPOLYLINE de la capa «EJE DE VÍA» con 277 vértices y 4 arcos. Los arcos se densificaron con una tolerancia de 1 cm.
- Sentido: el primer vértice (528 469.58, 9 401 639.37) es la progresiva **0+000**.
  - Para verificarlo se muestreó el DEM a lo largo del eje y se comparó con el perfil del complemento Cota de Anegamiento.
  - En este sentido, el error medio es de 0.19 m en 215 progresivas; en el sentido inverso sería de 1.56 m.
  - El perfil del complemento termina en 4+276, igual que la longitud del eje.
- `EJE_VIA_DE_EVITAMIENTO_UNIDO.dxf`: el archivo original, por si se necesita.

## 2. Las 17 alcantarillas

`alcantarillas_17.gpkg` (y `alcantarillas_17.csv`): puntos interpolados sobre el eje en cada progresiva.

Campos: `n`, `progresiva`, `dist_m`, `tipo` (Obligatoria / Igualacion / Alivio), `tr_anios`, `q_m3s` (caudal de diseño actual), `x`, `y`.

- **Obligatorias:** el terraplén embalsa agua.
- **Igualación:** el eje corta una depresión.
- **Alivio:** bajante del bordillo. Su área es una faja geométrica dentro del derecho de vía (25 m a cada lado del eje), así que no se espera que coincida con una cuenca del DEM.

## 3. Cuencas de GRASS

`cuencas_grass.gpkg`: los polígonos de las dos cuencas delimitadas con r.watershed (MFD, umbral de 700 celdas = 10.94 ha), r.water.outlet y r.lfp. Se unieron `Cota_cuenca_1.gpkg` y `Cota_cuenca_2.gpkg` del proyecto original.

| Cuenca | Cruce | Área (ha) | Cota mín. (m) | Cota máx. (m) | L cauce (m) | Pendiente |
|---|---|---|---|---|---|---|
| 1 | 2+070 | 63.66 | 22 | 37 | 1 565.9 | 0.00958 |
| 2 | 1+100 | 34.67 | 20 | 36 | 1 261.0 | 0.01269 |

La pendiente es (cota máx. − cota mín.) / L.

**Corrección:** las cotas mínimas de GRASS son 22 m y 20 m, no 10.29 m y 9.83 m. Esos dos valores no salen de estas capas.

`exutorios_grass.gpkg`: los 2 puntos de salida que se usaron en GRASS (`Puntos_interseccion.gpkg` del proyecto original).

- El de la cuenca 1 cae sobre el eje, en la distancia 2 082.1 m.
- El de la cuenca 2 está a 79.1 m del eje. Su proyección sobre el eje cae en la distancia 1 110.9 m.
- La alcantarilla del cuadro se ubicó en 1+100.

## 4. DEM

- `Area de estudio.dem`: el DEM exacto que se usó en GRASS. Es un USGS DEM ASCII de 12.5 m, con nodata −32767.
- `dem_grass_area_estudio.tif`: el mismo DEM convertido a GeoTIFF.

**No existe un DEM con decimales.** El ALOS PALSAR RTC de 12.5 m (ASF) se distribuye en metros enteros (Int16), y este DEM también es entero: va de −2 a 61 m. La comparación con GRASS debe hacerse sobre este mismo archivo.

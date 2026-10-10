# Historial de cambios

## 1.0.0
- Versión inicial del complemento «Exutorios Viales».
- Algoritmos de Procesos «Cuencas de alcantarillas» (análisis rápido y completo).
- Acondicionamiento del DEM: Priority-Flood (Barnes et al., 2014) o breaching híbrido (Lindsay,
  2016); planicies resueltas con el gradiente superpuesto de Barnes et al. (2014) calculado con
  distancias octiles y desempate por la pendiente del terreno suavizado (evita el sesgo a 45° en los
  DEM de cotas enteras); verificación de celdas sin salida.
- Direcciones y acumulación D8 por oleadas topológicas; MFD de Freeman (1991) opcional.
- Red de cauces por umbral en hectáreas, de confluencia a confluencia, con orden de Strahler.
- Salidas por intersección exacta cauce–eje (agrupando cortes cercanos), por puntos ajustados a la
  celda de mayor acumulación, o ambos sin duplicar; progresivas sobre el eje concatenado.
- Cuencas sin islas con anidamiento; recorrido más largo exacto; A, P, L, cotas, ΔH/L, S 10–85,
  pendiente media (Horn), cota media, Kc, Kf, depresiones cerradas, contacto con el borde.
- Tc: Kirpich, Témez, California Culverts Practice, Bransby-Williams, retardo SCS, con rangos de
  validez y Tc mínimo; criterio de adopción configurable.
- CN de la tabla TR-55 por uso y grupo, AMC II/III, compuesto por área con calicatas (Thiessen) o
  polígonos; caudal racional y racional modificado de Témez con Dyck-Peschke o IDF de Hydrognomon.
- Escenario con la vía como barrera.
- Capas con simbología, rásters opcionales, CSV, informe HTML, salidas numéricas para el modelador.
- Pruebas automáticas con DEM analíticos y prueba de integración con un sustituto de PyQGIS; CI.

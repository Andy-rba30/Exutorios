"""Sustituto mínimo de qgis.core para probar el complemento sin QGIS.

Cubre dos usos:
1. Importar el complemento y revisar initAlgorithm() (solo numpy).
2. Ejecutar processAlgorithm() de punta a punta cuando GDAL/OGR está
   disponible (python3-gdal): las geometrías se apoyan en OGR y los «sinks»
   guardan los elementos en memoria. Es un doble de pruebas, no PyQGIS."""
import os

try:
    from osgeo import ogr, osr
except Exception:  # pragma: no cover - sin GDAL solo funciona el uso 1
    ogr = osr = None


class _Enum:
    def __getattr__(self, nombre):
        return nombre


class Qgis:
    QGIS_VERSION_INT = 34000
    ProcessingNumberParameterType = _Enum()
    ProcessingSourceType = _Enum()
    WkbType = type("W", (), {"MultiPolygon": "MultiPolygon", "Point": "Point", "LineString": "LineString"})
    ProcessingParameterFlag = type("F", (), {"Advanced": 2})
    ProcessingFieldParameterDataType = _Enum()
    RasterBandStatistic = _Enum()
    ShaderInterpolationMethod = _Enum()


class QgsProcessing:
    TypeVectorLine = "line"
    TypeVectorPoint = "point"
    TypeVectorAnyGeometry = "any"


class QgsWkbTypes:
    MultiPolygon = "MultiPolygon"
    Point = "Point"
    LineString = "LineString"
    PointGeometry = 0
    LineGeometry = 1
    PolygonGeometry = 2

    @staticmethod
    def geometryType(wkb):
        w = str(wkb).lower()
        if "point" in w:
            return 0
        if "line" in w:
            return 1
        return 2


# ---------------------------------------------------------------------------
# Parámetros
# ---------------------------------------------------------------------------

class QgsProcessingParameterDefinition:
    FlagAdvanced = 2

    def __init__(self, name, description="", *a, **k):
        self._name = name
        self._description = description
        self._flags = 0
        self.kwargs = k
        self.args = a

    def name(self):
        return self._name

    def description(self):
        return self._description

    def flags(self):
        return self._flags

    def setFlags(self, f):
        self._flags = f

    def isDestination(self):
        return False

    def defaultValue(self):
        return self.kwargs.get("defaultValue")


class QgsProcessingParameterRasterLayer(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterExtent(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterFeatureSource(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterNumber(QgsProcessingParameterDefinition):
    Double = "double"
    Integer = "int"


class QgsProcessingParameterString(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterEnum(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterField(QgsProcessingParameterDefinition):
    Numeric = "numeric"
    Any = "any"


class QgsProcessingParameterBoolean(QgsProcessingParameterDefinition):
    pass


class _Destino(QgsProcessingParameterDefinition):
    def isDestination(self):
        return True


class QgsProcessingParameterFeatureSink(_Destino):
    pass


class QgsProcessingParameterRasterDestination(_Destino):
    pass


class QgsProcessingParameterFileDestination(_Destino):
    pass


class QgsProcessingOutputNumber:
    def __init__(self, name, description=""):
        self._name = name

    def name(self):
        return self._name


class QgsProcessingOutputString(QgsProcessingOutputNumber):
    pass


class QgsProcessingException(Exception):
    pass


class QgsProcessingLayerPostProcessorInterface:
    def __init__(self):
        pass


class QgsProcessingProvider:
    def __init__(self):
        self._algs = []

    def addAlgorithm(self, a):
        self._algs.append(a)
        return True

    def algorithms(self):
        return list(self._algs)


# ---------------------------------------------------------------------------
# Geometría (sobre OGR)
# ---------------------------------------------------------------------------

class QgsPointXY:
    def __init__(self, x, y=None):
        if y is None:
            x, y = x
        self._x, self._y = float(x), float(y)

    def x(self):
        return self._x

    def y(self):
        return self._y


class _Abstracta:
    def __init__(self, g):
        self._g = g

    def hasCurvedSegments(self):
        return False

    def segmentize(self):
        return QgsGeometry(self._g)


class QgsGeometry:
    def __init__(self, g=None):
        if isinstance(g, QgsGeometry):
            g = g._g
        self._g = g

    @staticmethod
    def fromWkt(wkt):
        return QgsGeometry(ogr.CreateGeometryFromWkt(wkt))

    @staticmethod
    def fromPointXY(p):
        return QgsGeometry.fromWkt("POINT (%r %r)" % (p.x(), p.y()))

    @staticmethod
    def fromPolylineXY(pts):
        return QgsGeometry.fromWkt("LINESTRING (%s)" % ", ".join("%r %r" % (p.x(), p.y()) for p in pts))

    def isNull(self):
        return self._g is None

    def isEmpty(self):
        return self._g is None or self._g.IsEmpty()

    def isMultipart(self):
        return self._g.GetGeometryCount() > 0 and self._g.GetGeometryName().startswith("MULTI")

    def asGeometryCollection(self):
        return [QgsGeometry(self._g.GetGeometryRef(i).Clone()) for i in range(self._g.GetGeometryCount())]

    def asPolyline(self):
        if self._g.GetGeometryName() != "LINESTRING":
            raise TypeError("no es una línea")
        return [QgsPointXY(x, y) for x, y, *_ in self._g.GetPoints()]

    def asPoint(self):
        return QgsPointXY(self._g.GetX(), self._g.GetY())

    def centroid(self):
        return QgsGeometry(self._g.Centroid())

    def constGet(self):
        return _Abstracta(self._g)

    def transform(self, t):
        return 0

    def asWkt(self):
        return self._g.ExportToWkt()

    def convertToMultiType(self):
        n = self._g.GetGeometryName()
        if n == "POLYGON":
            self._g = ogr.ForceToMultiPolygon(self._g.Clone())
        return True

    def intersects(self, otra):
        return bool(self._g.Intersects(otra._g))

    def area(self):
        return self._g.GetArea()

    def length(self):
        return self._g.Length()

    def type(self):
        return QgsWkbTypes.geometryType(self._g.GetGeometryName())


# ---------------------------------------------------------------------------
# Campos, elementos, fuentes y sinks
# ---------------------------------------------------------------------------

class QgsField:
    def __init__(self, name, tipo=None):
        self._name = name
        self._type = tipo

    def name(self):
        return self._name


class QgsFields:
    def __init__(self):
        self._f = []

    def append(self, f):
        self._f.append(f)

    def __iter__(self):
        return iter(self._f)

    def __len__(self):
        return len(self._f)

    def indexOf(self, nombre):
        for i, f in enumerate(self._f):
            if f.name() == nombre:
                return i
        return -1

    def names(self):
        return [f.name() for f in self._f]


class QgsFeature:
    def __init__(self, campos=None, fid=0):
        self._campos = campos if campos is not None else QgsFields()
        self._attr = [None] * len(self._campos)
        self._geom = QgsGeometry()
        self._id = fid

    def setGeometry(self, g):
        self._geom = g

    def geometry(self):
        return self._geom

    def setAttributes(self, a):
        self._attr = list(a)

    def attributes(self):
        return list(self._attr)

    def id(self):
        return self._id

    def __getitem__(self, k):
        if isinstance(k, int):
            return self._attr[k]
        i = self._campos.indexOf(k)
        return self._attr[i] if i >= 0 else None

    def como_dict(self):
        return dict(zip(self._campos.names(), self._attr))


class FuenteFalsa:
    """Capa vectorial en memoria: lista de (wkt, dict_atributos)."""

    def __init__(self, elementos, wkb="LineString", crs=None, nombre="capa"):
        self._crs = crs or QgsCoordinateReferenceSystem()
        self._wkb = wkb
        self._nombre = nombre
        self._campos = QgsFields()
        nombres = []
        for _, attrs in elementos:
            for k in attrs:
                if k not in nombres:
                    nombres.append(k)
        for n in nombres:
            self._campos.append(QgsField(n))
        self._feats = []
        for i, (wkt, attrs) in enumerate(elementos, start=1):
            f = QgsFeature(self._campos, i)
            f.setGeometry(QgsGeometry.fromWkt(wkt))
            f.setAttributes([attrs.get(n) for n in nombres])
            self._feats.append(f)

    def getFeatures(self, *a, **k):
        return iter(self._feats)

    def sourceCrs(self):
        return self._crs

    def sourceName(self):
        return self._nombre

    def fields(self):
        return self._campos

    def wkbType(self):
        return self._wkb


class SinkFalso:
    def __init__(self, campos):
        self.campos = campos
        self.features = []

    def addFeature(self, f, *a):
        self.features.append(f)
        return True

    def finalize(self):
        pass


SINKS = {}


class CapaRasterFalsa:
    def __init__(self, ruta, nombre=None):
        self._ruta = ruta
        self._nombre = nombre or os.path.basename(ruta)

    def source(self):
        return self._ruta

    def name(self):
        return self._nombre

    def crs(self):
        from osgeo import gdal
        ds = gdal.Open(self._ruta)
        c = QgsCoordinateReferenceSystem()
        c.createFromWkt(ds.GetProjection())
        return c


# ---------------------------------------------------------------------------
# CRS y transformaciones
# ---------------------------------------------------------------------------

class QgsCoordinateReferenceSystem:
    def __init__(self, *a, **k):
        self._wkt = ""

    def createFromWkt(self, wkt):
        self._wkt = wkt or ""
        return bool(wkt)

    def isValid(self):
        return bool(self._wkt)

    def isGeographic(self):
        if not self._wkt or osr is None:
            return False
        s = osr.SpatialReference()
        s.ImportFromWkt(self._wkt)
        return bool(s.IsGeographic())

    def authid(self):
        if not self._wkt or osr is None:
            return ""
        s = osr.SpatialReference()
        s.ImportFromWkt(self._wkt)
        try:
            s.AutoIdentifyEPSG()
        except Exception:
            pass
        code = s.GetAuthorityCode(None)
        return "EPSG:%s" % code if code else ""

    def description(self):
        return "CRS"


class QgsCoordinateTransform:
    def __init__(self, *a, **k):
        pass

    def isValid(self):
        return False


class ContextoFalso:
    def transformContext(self):
        return None

    def willLoadLayerOnCompletion(self, *a):
        return False


class FeedbackFalso:
    def __init__(self):
        self.mensajes = []
        self.avisos = []
        self.progreso = 0.0

    def pushInfo(self, t):
        self.mensajes.append(t)

    def pushWarning(self, t):
        self.avisos.append(t)

    def pushDebugInfo(self, t):
        self.mensajes.append(t)

    def setProgress(self, p):
        self.progreso = p

    def isCanceled(self):
        return False


class QgsRasterFileWriter:
    @staticmethod
    def driverForExtension(ext):
        return "GTiff"


# ---------------------------------------------------------------------------
# Algoritmo base con parameterAs* funcionales
# ---------------------------------------------------------------------------

class QgsProcessingAlgorithm:
    def __init__(self):
        self._params = []
        self._outputs = []

    def addParameter(self, p):
        assert p.name() not in [q.name() for q in self._params], "parámetro duplicado: %s" % p.name()
        self._params.append(p)
        return True

    def addOutput(self, o):
        self._outputs.append(o)
        return True

    def parameterDefinitions(self):
        return list(self._params)

    def parameterDefinition(self, nombre):
        for p in self._params:
            if p.name() == nombre:
                return p
        return None

    def outputDefinitions(self):
        return list(self._outputs)

    # --- en ejecución ---------------------------------------------------
    def _valor(self, params, nombre):
        if nombre in params:
            return params[nombre]
        d = self.parameterDefinition(nombre)
        return d.defaultValue() if d is not None else None

    def parameterAsRasterLayer(self, params, nombre, ctx):
        return self._valor(params, nombre)

    def parameterAsDouble(self, params, nombre, ctx):
        v = self._valor(params, nombre)
        return float(v) if v is not None else 0.0

    def parameterAsInt(self, params, nombre, ctx):
        v = self._valor(params, nombre)
        return int(v) if v is not None else 0

    def parameterAsEnum(self, params, nombre, ctx):
        v = self._valor(params, nombre)
        return int(v) if v is not None else 0

    def parameterAsBool(self, params, nombre, ctx):
        return bool(self._valor(params, nombre))

    def parameterAsString(self, params, nombre, ctx):
        v = self._valor(params, nombre)
        return "" if v is None else str(v)

    def parameterAsSource(self, params, nombre, ctx):
        return params.get(nombre)

    def parameterAsSink(self, params, nombre, ctx, campos, wkb, crs):
        dest = params.get(nombre) or ("memory:" + nombre)
        s = SinkFalso(campos)
        SINKS[dest] = s
        return s, dest

    def parameterAsOutputLayer(self, params, nombre, ctx):
        return params.get(nombre)

    def parameterAsFileOutput(self, params, nombre, ctx):
        return params.get(nombre)

    def invalidSinkError(self, params, nombre):
        return "sink inválido: %s" % nombre


class _Cualquiera:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, nombre):
        return _Cualquiera()

    def __call__(self, *a, **k):
        return _Cualquiera()


class QgsApplication(_Cualquiera):
    pass

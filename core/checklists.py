"""Catálogo fijo de puntos de checklist y mediciones por tipo de equipo.

No es una referencia normativa: define qué se revisa en cada visita. Al iniciar una orden se copia a filas
propias de la orden, de modo que cambiar este catálogo no altera órdenes ya iniciadas.
"""
from dataclasses import dataclass
from decimal import Decimal

INSPECCION = 'INSPECCION'
FUNCIONAMIENTO = 'FUNCIONAMIENTO'
REFRIGERANTE = 'REFRIGERANTE'
MEDICIONES_BLOQUE = 'MEDICIONES'
FOTOS = 'FOTOS'
FIRMA = 'FIRMA'

ETIQUETAS_BLOQUE = {
    INSPECCION: 'Inspección',
    FUNCIONAMIENTO: 'Funcionamiento',
    REFRIGERANTE: 'Refrigerante',
    MEDICIONES_BLOQUE: 'Mediciones',
    FOTOS: 'Fotografías',
    FIRMA: 'Firma del cliente',
}
BLOQUES_DE_PUNTOS = [INSPECCION, FUNCIONAMIENTO, REFRIGERANTE]
ORDEN_BLOQUES = BLOQUES_DE_PUNTOS + [MEDICIONES_BLOQUE, FOTOS, FIRMA]


@dataclass(frozen=True)
class PuntoDef:
    codigo: str
    bloque: str
    texto: str


@dataclass(frozen=True)
class MedicionDef:
    codigo: str
    etiqueta: str
    unidad: str
    minimo: Decimal
    maximo: Decimal


CODIGOS_ARRANQUE = ('ARR_SENAL', 'ARR_VENTILACION', 'ARR_CONDENSADOS', 'ARR_ESTABILIDAD', 'ARR_FUGAS')

_ARRANQUE = [
    PuntoDef('ARR_SENAL', FUNCIONAMIENTO, 'Señal de arranque y contactor-compresor correctos'),
    PuntoDef('ARR_VENTILACION', FUNCIONAMIENTO, 'Ventilación correcta'),
    PuntoDef('ARR_CONDENSADOS', FUNCIONAMIENTO, 'Drenaje de condensación correcto'),
    PuntoDef('ARR_ESTABILIDAD', FUNCIONAMIENTO, 'Funcionamiento estable, sin vibraciones anómalas'),
    PuntoDef('ARR_FUGAS', FUNCIONAMIENTO, 'Sin fugas visibles de refrigerante, agua helada o aceite'),
]

_INSPECCION_COMUN = [
    PuntoDef('INS_FILTROS', INSPECCION, 'Estado de los filtros'),
    PuntoDef('INS_BATERIA', INSPECCION, 'Estado del serpentín'),
    PuntoDef('INS_FIJACIONES', INSPECCION, 'Fijaciones y soportes en buen estado'),
    PuntoDef('INS_AISLAMIENTO', INSPECCION, 'Aislamiento de las tuberías en buen estado'),
    PuntoDef('INS_LIMPIEZA', INSPECCION, 'Limpieza general del equipo'),
]

_EXTRAS = {
    'SPLIT': [PuntoDef('INS_UNIDAD_INTERIOR', INSPECCION, 'Limpieza de la unidad interior')],
    'MINI_SPLIT': [PuntoDef('INS_UNIDAD_INTERIOR', INSPECCION, 'Limpieza de la unidad interior')],
    'CHILLER': [PuntoDef('INS_AGUA_GLICOL', INSPECCION, 'Nivel y estado del agua o glicol'),
                PuntoDef('FUN_BOMBA', FUNCIONAMIENTO, 'Bomba de circulación sin ruidos ni fugas')],
    'VRF': [PuntoDef('FUN_COMUNICACION', FUNCIONAMIENTO, 'Comunicación correcta entre unidades')],
    'UMA': [PuntoDef('INS_CORREAS', INSPECCION, 'Correas y ruido de rodamientos del motor o ventilador')],
    'ROOFTOP': [PuntoDef('INS_COMPUERTAS', INSPECCION, 'Compuertas de aire exterior en buen estado')],
    'OTRO': [],
}

_REFRIGERANTE = [
    PuntoDef('REF_ESTANQUEIDAD', REFRIGERANTE, 'Prueba de estanqueidad superada'),
    PuntoDef('REF_FUGAS', REFRIGERANTE, 'Detección de fugas realizada'),
]

MEDICIONES = {m.codigo: m for m in [
    # Los topes (mínimo y máximo) rechazan valores imposibles o erróneos de teclado; no son rangos de funcionamiento normal.
    MedicionDef('TEMP_IMPULSION', 'Temperatura de inyección', '°C', Decimal('-10'), Decimal('60')),
    MedicionDef('TEMP_RETORNO', 'Temperatura de retorno', '°C', Decimal('-10'), Decimal('60')),
    MedicionDef('TENSION', 'Tensión', 'V', Decimal('0'), Decimal('480')),
    MedicionDef('CORRIENTE', 'Corriente', 'A', Decimal('0'), Decimal('300')),
    MedicionDef('PRESION_ALTA', 'Presión alta', 'bar', Decimal('0'), Decimal('45')),
    MedicionDef('PRESION_BAJA', 'Presión baja', 'bar', Decimal('0'), Decimal('20')),
    MedicionDef('VELOCIDAD_AIRE', 'Velocidad del flujo de aire', 'm/s', Decimal('0'), Decimal('20')),
]}
_BASE = ['TEMP_IMPULSION', 'TEMP_RETORNO', 'TENSION', 'CORRIENTE']


def _tipo(tipo):
    return tipo if tipo in _EXTRAS else 'OTRO'


def puntos_para(tipo, requiere_refrigerante):
    """Puntos del checklist para un tipo de equipo, en el orden en que se muestran."""
    puntos = _INSPECCION_COMUN + _EXTRAS[_tipo(tipo)] + _ARRANQUE
    if requiere_refrigerante:
        puntos = puntos + _REFRIGERANTE
    return sorted(puntos, key=lambda p: ORDEN_BLOQUES.index(p.bloque))


def mediciones_para(tipo):
    """Mediciones aplicables a un tipo de equipo (las presiones no aplican a una UMA)."""
    codigos = _BASE + ([] if _tipo(tipo) == 'UMA' else ['PRESION_ALTA', 'PRESION_BAJA'])
    return [MEDICIONES[c] for c in codigos]

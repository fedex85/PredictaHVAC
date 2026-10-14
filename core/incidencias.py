"""Incidencias de gravedad Alta: la gestión decide entre una orden correctiva enlazada o una justificación."""
from django.db import transaction

from core.models import DecisionIncidenciaOT, OrdenTrabajo, PuntoChecklistOT
from core import ordenes
from core.ordenes import ReglaError, _bloquear, _evento, _exigir_estado, _exigir_gestion
from core.permisos import ROLES_GESTION, rol_de

JUSTIFICACION_MINIMA = 10
MSG_YA_DECIDIDA = 'Esta incidencia ya tiene decisión.'
MSG_NO_ENCONTRADA = 'Incidencia no encontrada.'
MSG_JUSTIFICACION = f'La justificación es obligatoria (mínimo {JUSTIFICACION_MINIMA} caracteres).'
MSG_BLOQUEADA = 'La orden está bloqueada por una correctiva.'
MSG_SIN_DECISION = 'Esa decisión no existe.'


def _decision(punto):
    """Consulta directa: evita la caché de la relación inversa."""
    return DecisionIncidenciaOT.objects.filter(punto=punto).first()


def decision_activa(decision):
    return (decision.tipo == DecisionIncidenciaOT.CORRECTIVA
            and decision.orden_correctiva.estado != OrdenTrabajo.CANCELADA)


def incidencias_alta(orden):
    """Puntos con incidencia Alta, cada uno con `decision_actual` (None si aún no se ha decidido)."""
    puntos = list(orden.puntos.filter(resultado=PuntoChecklistOT.INCIDENCIA, gravedad='ALTA'))
    for punto in puntos:
        punto.decision_actual = _decision(punto)
    return puntos


def pendientes_alta(orden):
    return [p for p in incidencias_alta(orden) if p.decision_actual is None]


def bloqueada_por_correctiva(orden):
    return (DecisionIncidenciaOT.objects.filter(punto__orden=orden, tipo=DecisionIncidenciaOT.CORRECTIVA)
            .exclude(orden_correctiva__estado=OrdenTrabajo.CANCELADA).exists())


def resumen_decisiones(orden):
    decisiones = list(DecisionIncidenciaOT.objects.filter(punto__orden=orden).select_related('orden_correctiva'))
    if not decisiones:
        return ''
    partes = [f'correctiva {d.orden_correctiva.codigo}' if d.tipo == DecisionIncidenciaOT.CORRECTIVA else 'justificada'
              for d in decisiones]
    return f"Incidencias Alta: {len(decisiones)} {'resuelta' if len(decisiones) == 1 else 'resueltas'} ({', '.join(partes)})"


def motivo_no_decidible(orden, punto_id, usuario):
    """Comprobación de solo lectura para las pantallas: (mensaje, punto). Mensaje vacío si se puede decidir."""
    if rol_de(usuario) not in ROLES_GESTION:
        return 'Solo un administrador o gerente puede hacer esto.', None
    if orden.estado != OrdenTrabajo.PENDIENTE_APROBACION:
        return f'La OT ya no está en un estado que lo permita (estado actual: {orden.get_estado_display()}).', None
    punto = orden.puntos.filter(pk=punto_id, resultado=PuntoChecklistOT.INCIDENCIA, gravedad='ALTA').first()
    if punto is None:
        return MSG_NO_ENCONTRADA, None
    if _decision(punto):
        return MSG_YA_DECIDIDA, punto
    return '', punto


def _preparar(orden, punto_id, request):
    """Comprobaciones comunes: bloquea la orden, exige gestión y estado, y localiza la incidencia Alta."""
    _bloquear(orden)
    _exigir_gestion(request)
    _exigir_estado(orden, OrdenTrabajo.PENDIENTE_APROBACION)
    try:
        pk = int(punto_id)
    except (TypeError, ValueError):
        raise ReglaError(MSG_NO_ENCONTRADA)
    punto = orden.puntos.filter(pk=pk, resultado=PuntoChecklistOT.INCIDENCIA, gravedad='ALTA').first()
    if punto is None:
        raise ReglaError(MSG_NO_ENCONTRADA)
    return punto


@transaction.atomic
def justificar(orden, punto_id, texto, request):
    punto = _preparar(orden, punto_id, request)
    if _decision(punto):
        raise ReglaError(MSG_YA_DECIDIDA)
    texto = (texto or '').strip()
    if len(texto) < JUSTIFICACION_MINIMA:
        raise ReglaError(MSG_JUSTIFICACION)
    decision = DecisionIncidenciaOT.objects.create(punto=punto, tipo=DecisionIncidenciaOT.JUSTIFICADA,
                                                   justificacion=texto, decidida_por=request.user)
    _evento(orden, request, f'Incidencia Alta justificada: {punto.texto}')
    return decision


@transaction.atomic
def crear_correctiva(orden, punto_id, correctiva, request):
    """Guarda la correctiva (equipo y tipo forzados) y registra la decisión, en una sola transacción."""
    punto = _preparar(orden, punto_id, request)
    if _decision(punto):
        raise ReglaError(MSG_YA_DECIDIDA)
    correctiva.orden_origen, correctiva.equipo, correctiva.tipo = orden, orden.equipo, 'CORRECTIVO'
    ordenes.crear(correctiva, request)
    DecisionIncidenciaOT.objects.create(punto=punto, tipo=DecisionIncidenciaOT.CORRECTIVA,
                                        orden_correctiva=correctiva, decidida_por=request.user)
    _evento(orden, request, f'Incidencia Alta: correctiva {correctiva.codigo} creada ({punto.texto})')
    _evento(correctiva, request, f'Origen: incidencia Alta de {orden.codigo} ({punto.texto})')
    return correctiva


@transaction.atomic
def deshacer(orden, punto_id, request):
    punto = _preparar(orden, punto_id, request)
    decision = _decision(punto)
    if decision is None:
        raise ReglaError(MSG_SIN_DECISION)
    if decision_activa(decision):
        raise ReglaError(MSG_BLOQUEADA)
    decision.delete()
    _evento(orden, request, f'Decisión sobre incidencia Alta deshecha: {punto.texto}')


def liberar_por_cancelacion(correctiva, request):
    """Al cancelar una correctiva, su incidencia vuelve a Sin resolver y la orden de origen se desbloquea."""
    for decision in DecisionIncidenciaOT.objects.filter(orden_correctiva=correctiva).select_related('punto__orden'):
        origen, texto = decision.punto.orden, decision.punto.texto
        if origen.estado != OrdenTrabajo.PENDIENTE_APROBACION:
            # Original ya cerrada: la decisión se conserva como registro de lo que se resolvió en su día.
            _evento(origen, request, f'Correctiva {correctiva.codigo} cancelada (la orden ya estaba cerrada: la decisión se conserva) ({texto})')
            _evento(correctiva, request, f'Cancelada: su orden de origen {origen.codigo} ya estaba cerrada ({texto})')
            continue
        decision.delete()
        _evento(origen, request, f'Correctiva {correctiva.codigo} cancelada: la incidencia Alta vuelve a Sin resolver ({texto})')
        _evento(correctiva, request, f'Cancelada: libera la incidencia Alta de {origen.codigo} ({texto})')


def anular_si_cambia(punto, request):
    """Si el punto deja de ser incidencia Alta, su decisión ya no tiene objeto: se borra y se anota."""
    decision = _decision(punto)
    if decision is None or decision_activa(decision):
        return  # una correctiva activa bloquea la orden: su decisión no se toca
    if punto.resultado == PuntoChecklistOT.INCIDENCIA and punto.gravedad == 'ALTA':
        return
    decision.delete()
    _evento(punto.orden, request, f'Decisión anulada: el punto cambió ({punto.texto})')

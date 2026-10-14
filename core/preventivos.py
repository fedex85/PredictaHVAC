"""Plan de mantenimiento preventivo: cuándo toca cada equipo y generación de las órdenes correspondientes."""
import calendar
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Max

from core import auditoria
from core.models import EquipoHVAC, EventoOT, HistorialMantenimiento, OrdenTrabajo, RegistroActividad

# Estados del plan de un equipo
SIN_PLAN, FUERA_SERVICIO, ABIERTA, CANCELADA, VENCIDO, PROXIMO, AL_DIA = (
    'SIN_PLAN', 'FUERA_SERVICIO', 'ABIERTA', 'CANCELADA', 'VENCIDO', 'PROXIMO', 'AL_DIA')
ETIQUETAS = {SIN_PLAN: 'Sin plan', FUERA_SERVICIO: 'Fuera de servicio', ABIERTA: 'Orden abierta',
             CANCELADA: 'Orden cancelada', VENCIDO: 'Vencido', PROXIMO: 'Próximo', AL_DIA: 'Al día'}
CERRADAS = (OrdenTrabajo.FINALIZADA, OrdenTrabajo.CANCELADA)


def anticipacion_dias():
    return int(getattr(settings, 'PREVENTIVOS_ANTICIPACION_DIAS', 15))


def sumar_meses(fecha, meses):
    """Suma meses de calendario; si el día no existe en el mes destino se usa el último (31 ene + 1 mes = 28/29 feb)."""
    indice = fecha.year * 12 + (fecha.month - 1) + meses
    anio, mes = indice // 12, indice % 12 + 1
    return fecha.replace(year=anio, month=mes, day=min(fecha.day, calendar.monthrange(anio, mes)[1]))


def ultimo_preventivo(equipo):
    return equipo.mantenimientos.filter(tipo_mantenimiento='PREVENTIVO') \
        .aggregate(f=Max('fecha_mantenimiento'))['f']


def proximo(equipo, hoy, ultimo=None):
    """Fecha en que toca el siguiente preventivo, o None si el equipo no tiene plan.
    Se cuenta desde el último preventivo; si no hay, desde la instalación; si tampoco, toca hoy."""
    if not equipo.periodicidad_meses:
        return None
    base = ultimo or equipo.fecha_instalacion
    return sumar_meses(base, equipo.periodicidad_meses) if base else hoy


def _preventivas(equipo):
    return equipo.ordenes.filter(tipo='PREVENTIVO')


def situacion(equipo, hoy):
    """Estado del plan de un equipo: dict con ultimo, proximo, estado, etiqueta y si 'toca' generar su orden."""
    ultimo = ultimo_preventivo(equipo)
    fecha = proximo(equipo, hoy, ultimo)
    abierta = _preventivas(equipo).exclude(estado__in=CERRADAS).first()
    if fecha is None:
        estado = SIN_PLAN
    elif equipo.estado == 'FUERA_SERVICIO':
        estado = FUERA_SERVICIO
    elif abierta:
        estado = ABIERTA
    elif _preventivas(equipo).filter(estado=OrdenTrabajo.CANCELADA, fecha_programada=fecha).exists():
        estado = CANCELADA   # se respeta la cancelación hasta que cambie la fecha que toca
    elif fecha < hoy:
        estado = VENCIDO
    elif fecha <= hoy + timedelta(days=anticipacion_dias()):
        estado = PROXIMO
    else:
        estado = AL_DIA
    return {'equipo': equipo, 'ultimo': ultimo, 'proximo': fecha, 'abierta': abierta, 'estado': estado,
            'etiqueta': ETIQUETAS[estado], 'toca': estado in (VENCIDO, PROXIMO)}


def plan(hoy):
    """Situación de todos los equipos con plan, los que más urgen primero."""
    filas = [situacion(e, hoy) for e in EquipoHVAC.objects.filter(periodicidad_meses__isnull=False)]
    orden = {VENCIDO: 0, PROXIMO: 1, ABIERTA: 2, CANCELADA: 3, AL_DIA: 4, FUERA_SERVICIO: 5}
    return sorted(filas, key=lambda f: (orden[f['estado']], f['proximo'], f['equipo'].codigo_identificador))


def generar(hoy, usuario=None, simular=False):
    """Crea una orden Pendiente por cada equipo al que le toca. Devuelve la lista de (equipo, fecha) creadas
    (o que se crearían, con simular=True). Idempotente: una segunda llamada no duplica nada."""
    creadas = []
    for equipo_id in EquipoHVAC.objects.filter(periodicidad_meses__isnull=False).values_list('pk', flat=True):
        with transaction.atomic():
            equipo = EquipoHVAC.objects.select_for_update().get(pk=equipo_id)   # evita duplicados por doble clic
            s = situacion(equipo, hoy)
            if not s['toca']:
                continue
            if not simular:
                _crear_orden(equipo, s['proximo'], usuario)
            creadas.append((equipo, s['proximo']))
    return creadas


def _crear_orden(equipo, fecha, usuario):
    orden = OrdenTrabajo.objects.create(
        equipo=equipo, tipo='PREVENTIVO', criticidad='MEDIA', estado=OrdenTrabajo.PENDIENTE, fecha_programada=fecha,
        descripcion=f'Mantenimiento preventivo programado (cada {equipo.periodicidad_meses} '
                    f'{"mes" if equipo.periodicidad_meses == 1 else "meses"}).',
        creado_por=usuario)
    nombre = (usuario.get_full_name() or usuario.get_username()) if usuario else 'Sistema'
    EventoOT.objects.create(orden=orden, usuario_nombre=nombre, texto='Generada por el plan preventivo del equipo')
    auditoria.registrar(RegistroActividad.ORDEN_CREADA, usuario=usuario, nombre=nombre,
                        detalle=f'{orden.codigo} · {equipo.codigo_identificador} · plan preventivo')
    return orden

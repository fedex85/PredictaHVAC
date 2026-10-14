"""Agrupación de órdenes para las pantallas móviles del técnico (parte 4b). Funciones puras, sin consultas."""
from datetime import date

TITULOS_AGENDA = ['Atrasadas', 'Hoy', 'Mañana', 'Esta semana', 'Más adelante', 'Sin fecha']


def _grupo_de_fecha(fecha, hoy):
    if fecha is None:
        return 'Sin fecha'
    dias = (fecha - hoy).days
    if dias < 0:
        return 'Atrasadas'
    if dias == 0:
        return 'Hoy'
    if dias == 1:
        return 'Mañana'
    return 'Esta semana' if dias <= 6 else 'Más adelante'


def agrupar_por_fecha(ordenes, hoy):
    """[(título, [órdenes])] por fecha programada, en el orden de TITULOS_AGENDA y sin grupos vacíos."""
    grupos = {titulo: [] for titulo in TITULOS_AGENDA}
    for orden in sorted(ordenes, key=lambda o: (o.fecha_programada or date.max, o.pk or 0)):
        grupos[_grupo_de_fecha(orden.fecha_programada, hoy)].append(orden)
    return [(titulo, grupos[titulo]) for titulo in TITULOS_AGENDA if grupos[titulo]]


TITULOS_MIS_ORDENES = ['Requieren tu atención', 'En ejecución', 'Asignadas', 'Enviadas a aprobación', 'Finalizadas']
MAX_FINALIZADAS = 10


def agrupar_mis_ordenes(ordenes):
    """[(título, [órdenes])] para «Mis órdenes». Recibe las órdenes ya ordenadas por actividad reciente
    (más nuevas primero). Atención = en ejecución devuelta con motivo de subsanación. Finalizadas: solo las
    MAX_FINALIZADAS primeras. Estados que no pertenecen a ningún grupo (pendiente, cancelada) se omiten."""
    grupos = {titulo: [] for titulo in TITULOS_MIS_ORDENES}
    for orden in ordenes:
        if orden.estado == 'EN_EJECUCION':
            grupos['Requieren tu atención' if orden.subsanacion_motivo else 'En ejecución'].append(orden)
        elif orden.estado == 'ASIGNADA':
            grupos['Asignadas'].append(orden)
        elif orden.estado == 'PENDIENTE_APROBACION':
            grupos['Enviadas a aprobación'].append(orden)
        elif orden.estado == 'FINALIZADA':
            grupos['Finalizadas'].append(orden)
    grupos['Finalizadas'] = grupos['Finalizadas'][:MAX_FINALIZADAS]
    return [(titulo, grupos[titulo]) for titulo in TITULOS_MIS_ORDENES if grupos[titulo]]

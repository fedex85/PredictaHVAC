"""Calendario mensual de órdenes para gestión. Funciones puras, sin consultas."""
import calendar
from datetime import date

MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre',
         'octubre', 'noviembre', 'diciembre']
DIAS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
ANIO_MIN, ANIO_MAX = 2000, 2100


def parsear_mes(texto, hoy):
    """'2026-09' -> (2026, 9); cualquier valor inválido o fuera de rango devuelve el mes de `hoy`."""
    try:
        anio, mes = (int(p) for p in str(texto).split('-'))
        if ANIO_MIN <= anio <= ANIO_MAX and 1 <= mes <= 12:
            return anio, mes
    except (ValueError, TypeError):
        pass
    return hoy.year, hoy.month


def mes_vecino(anio, mes, delta):
    """Mes anterior (-1) o siguiente (+1) como (anio, mes); None si sale del rango admitido."""
    indice = anio * 12 + (mes - 1) + delta
    nuevo = (indice // 12, indice % 12 + 1)
    return nuevo if ANIO_MIN <= nuevo[0] <= ANIO_MAX else None


def clave(anio, mes):
    return f'{anio:04d}-{mes:02d}'


def semanas_del_mes(anio, mes, ordenes, hoy):
    """Semanas (lunes a domingo) con [{'fecha','del_mes','es_hoy','ordenes':[...]}] por día; órdenes por código."""
    por_dia = {}
    for orden in sorted(ordenes, key=lambda o: o.pk or 0):
        if orden.fecha_programada:
            por_dia.setdefault(orden.fecha_programada, []).append(orden)
    semanas = []
    for semana in calendar.Calendar(firstweekday=0).monthdatescalendar(anio, mes):
        semanas.append([{'fecha': d, 'del_mes': d.month == mes, 'es_hoy': d == hoy,
                         'ordenes': por_dia.get(d, [])} for d in semana])
    return semanas


def dias_con_ordenes(semanas):
    """Lista plana de los días del mes que tienen órdenes (para la vista móvil)."""
    return [dia for semana in semanas for dia in semana if dia['del_mes'] and dia['ordenes']]

"""Informe en PDF de una orden de trabajo (fase 2, parte 4).

Dos pasos: `datos_informe` reúne todo en un diccionario (sin escribir nada) y
`generar_informe_ot` lo entrega a `core.informe_pdf`, que lo dibuja con reportlab.
"""
import logging

from django.utils import timezone

from core import checklists, evidencias, informe_pdf
from core.models import DecisionIncidenciaOT, OrdenTrabajo

logger = logging.getLogger(__name__)

VERSIONES = {
    OrdenTrabajo.PENDIENTE_APROBACION: 'PROVISIONAL',
    OrdenTrabajo.FINALIZADA: 'DEFINITIVO',
}


def _nombre(usuario):
    return (usuario.get_full_name() or usuario.get_username()) if usuario else '—'


def _resultado(punto):
    if punto.resultado == 'OK':
        return 'OK'
    if punto.resultado == 'INCIDENCIA':
        return f'Incidencia {punto.gravedad.capitalize()}'.strip()
    return 'Sin marcar'


def _decision(decision):
    if decision is None:
        return None
    correctiva = decision.tipo == DecisionIncidenciaOT.CORRECTIVA
    return {
        'tipo': decision.tipo,
        'correctiva': decision.orden_correctiva.codigo if correctiva else '',
        'justificacion': decision.justificacion,
        'por': _nombre(decision.decidida_por),
        'en': decision.decidida_en,
    }


def _medicion(medicion):
    definicion = checklists.MEDICIONES.get(medicion.codigo)
    return {
        'etiqueta': medicion.etiqueta,
        'valor': f'{medicion.valor.normalize():f}' if medicion.valor is not None else 'Sin medir',
        'unidad': medicion.unidad,
        'rango': f'{definicion.minimo:f} a {definicion.maximo:f}' if definicion else '',
    }


def _plural(n, singular, plural):
    return f'{n} {singular if n == 1 else plural}'


def _resumen(puntos, mediciones):
    """Cifras y frase de resultado que abren el informe."""
    incidencias = [p for p in puntos if p['resultado'].startswith('Incidencia')]
    cuantas = {g: sum(1 for p in incidencias if p['resultado'] == f'Incidencia {g}') for g in ('Alta', 'Media', 'Leve')}
    altas = [p for p in incidencias if p['resultado'] == 'Incidencia Alta']
    correctivas = [p['decision']['correctiva'] for p in altas if p['decision'] and p['decision']['tipo'] == 'CORRECTIVA']
    justificadas = sum(1 for p in altas if p['decision'] and p['decision']['tipo'] == 'JUSTIFICADA')
    pendientes = sum(1 for p in altas if p['alta_pendiente'])
    resumen = {
        'puntos': len(puntos), 'ok': sum(1 for p in puntos if p['resultado'] == 'OK'),
        'incidencias': len(incidencias), 'alta': cuantas['Alta'], 'media': cuantas['Media'], 'leve': cuantas['Leve'],
        'alta_pendientes': pendientes, 'correctivas': correctivas,
        'mediciones': len(mediciones), 'mediciones_tomadas': sum(1 for m in mediciones if m['valor'] != 'Sin medir'),
    }
    if not puntos:
        resumen['frase'] = 'Sin checklist en esta orden.'
    elif not incidencias:
        resumen['frase'] = f"Sin incidencias: los {len(puntos)} puntos revisados están OK."
    else:
        partes = []
        if cuantas['Alta']:
            detalle = []
            if correctivas:
                detalle.append('correctiva ' + ', '.join(correctivas))
            if justificadas:
                detalle.append(_plural(justificadas, 'justificada', 'justificadas'))
            if pendientes:
                detalle.append(_plural(pendientes, 'pendiente de resolver', 'pendientes de resolver'))
            partes.append(f"{cuantas['Alta']} Alta" + (f" ({', '.join(detalle)})" if detalle else ''))
        for gravedad in ('Media', 'Leve'):
            if cuantas[gravedad]:
                partes.append(f'{cuantas[gravedad]} {gravedad}')
        resumen['frase'] = f"{_plural(len(incidencias), 'incidencia', 'incidencias')}: {', '.join(partes)}."
    return resumen


def datos_informe(orden):
    """Todo lo que lleva el informe, listo para dibujar. ValueError si el estado no admite informe."""
    version = VERSIONES.get(orden.estado)
    if version is None:
        raise ValueError(f'La orden {orden.codigo} no admite informe en el estado {orden.estado}.')
    decisiones = {d.punto_id: d for d in DecisionIncidenciaOT.objects.filter(punto__orden=orden)
                  .select_related('orden_correctiva', 'decidida_por')}
    puntos = []
    for p in orden.puntos.all():
        decision = _decision(decisiones.get(p.pk))
        puntos.append({
            'bloque': checklists.ETIQUETAS_BLOQUE.get(p.bloque, p.bloque),
            'texto': p.texto,
            'resultado': _resultado(p),
            'nota': p.nota,
            'decision': decision,
            'alta_pendiente': p.resultado == 'INCIDENCIA' and p.gravedad == 'ALTA' and decision is None,
        })
    firma = evidencias._firma(orden)
    firma_tec = evidencias._firma_tecnico(orden)
    mediciones = [_medicion(m) for m in orden.mediciones.all()]
    return {
        'codigo': orden.codigo,
        'version': version,
        'estado': orden.get_estado_display(),
        'equipo': f'{orden.equipo.codigo_identificador} · {orden.equipo.nombre}',
        'tipo': orden.get_tipo_display(),
        'tecnico': _nombre(orden.tecnico),
        'inicio': orden.inicio,
        'fin': orden.fin,
        'tiempo_efectivo': orden.tiempo_efectivo_texto,
        'pausas': [{'motivo': p.motivo, 'desde': p.desde, 'hasta': p.hasta} for p in orden.pausas.all()],
        'puntos': puntos,
        'mediciones': mediciones,
        'resumen': _resumen(puntos, mediciones),
        'materiales': 'Sin materiales' if orden.sin_materiales else orden.materiales,
        'observaciones': orden.observaciones,
        'firma': {
            'estado': evidencias.estado_firma(orden),
            'firmante': firma.firmante if firma else '',
            'fecha': firma.firmada_en if firma else None,
            'sello': evidencias.sello_anotado(orden) if firma else '',
            'integridad': evidencias.integridad_firma(orden),
        },
        'firma_tecnico': {
            'estado': evidencias.estado_firma_tecnico(orden),
            'firmante': firma_tec.firmante if firma_tec else '',
            'fecha': firma_tec.firmada_en if firma_tec else None,
            'sello': evidencias.sello_anotado(orden, True) if firma_tec else '',
            'integridad': evidencias.integridad_firma(orden, True),
        },
    }



def _bytes_firma(orden, tecnico=False):
    """Bytes de la firma desde el almacenamiento privado; None si el archivo no está disponible."""
    firma = evidencias._firma_tecnico(orden) if tecnico else evidencias._firma(orden)
    if firma is None:
        return None
    try:
        with firma.imagen.open('rb') as archivo:
            return archivo.read()
    except Exception:  # archivo ausente o ilegible: el informe sigue sin la imagen
        logger.warning('Firma de %s no disponible para el informe', orden.codigo, exc_info=True)
        return None


def generar_informe_ot(orden, generado_por):
    """PDF del informe de la orden (bytes). ValueError si el estado no admite informe."""
    datos = datos_informe(orden)
    firma_png = _bytes_firma(orden) if datos['firma']['estado'] != 'sin' else None
    generado = f"Generado el {timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M')} por {_nombre(generado_por)}"
    firma_tec_png = _bytes_firma(orden, True) if datos['firma_tecnico']['estado'] != 'sin' else None
    return informe_pdf.dibujar(datos, firma_png, generado, firma_tec_png)

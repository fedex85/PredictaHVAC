"""Modo sin conexión: descarga de una orden y sincronización del trabajo hecho en el teléfono."""
import json
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core import checklists, evidencias, ordenes
from core.models import OrdenTrabajo, PuntoChecklistOT, SincronizacionOT
from core.ordenes import ReglaError, _bloquear, _evento, certificado_problema


class Rechazo(ReglaError):
    """Una petición del modo sin conexión que se rechaza. `estado_http`: 400 datos, 403 permiso, 409 conflicto."""
    def __init__(self, *mensajes, estado_http=400):
        super().__init__(*mensajes)
        self.estado_http = estado_http


ESTADOS_DESCARGABLES = (OrdenTrabajo.ASIGNADA, OrdenTrabajo.EN_EJECUCION)
TOLERANCIA_RELOJ = timedelta(minutes=5)
MAX_PUNTOS = 100
MAX_MEDICIONES = 50
MSG_PAQUETE = 'El paquete de sincronización no es válido.'


def _punto(p):
    return {'codigo': p.codigo, 'bloque': p.bloque, 'texto': p.texto}


def _medicion(codigo, etiqueta, unidad, minimo=None, maximo=None):
    return {'codigo': codigo, 'etiqueta': etiqueta, 'unidad': unidad,
            'minimo': None if minimo is None else format(minimo, 'f'),
            'maximo': None if maximo is None else format(maximo, 'f')}


def _catalogo(orden):
    """Puntos y mediciones que verá el técnico: los de la orden si ya existen; si va a iniciarla, los del catálogo."""
    tipo = orden.equipo.tipo
    nueva_con_checklist = orden.estado == OrdenTrabajo.ASIGNADA and orden.con_checklist
    if orden.puntos.exists():
        puntos = [_punto(p) for p in orden.puntos.all()]
    elif nueva_con_checklist:
        puntos = [_punto(p) for p in checklists.puntos_para(tipo, orden.requiere_refrigerante)]
    else:
        puntos = []
    if orden.mediciones.exists():
        mediciones = []
        for m in orden.mediciones.all():
            d = checklists.MEDICIONES.get(m.codigo)
            mediciones.append(_medicion(m.codigo, m.etiqueta, m.unidad, d and d.minimo, d and d.maximo))
    elif nueva_con_checklist:
        mediciones = [_medicion(d.codigo, d.etiqueta, d.unidad, d.minimo, d.maximo)
                      for d in checklists.mediciones_para(tipo)]
    else:
        mediciones = []
    con_checklist = orden.con_checklist if orden.estado == OrdenTrabajo.ASIGNADA else orden.tiene_checklist
    elegibles = [] if con_checklist else [
        _medicion(d.codigo, d.etiqueta, d.unidad, d.minimo, d.maximo) for d in checklists.MEDICIONES.values()]
    return {'puntos': puntos, 'mediciones': mediciones, 'mediciones_elegibles': elegibles}


def _firma_resumen(orden):
    """Resumen firmado si la firma del servidor está vigente; None si no hay firma o quedó obsoleta."""
    if orden.con_evidencias and evidencias.estado_firma(orden) == 'vigente':
        return evidencias.resumen_para_firma(orden)
    return None


def _firma_tecnico_resumen(orden):
    """Resumen firmado por el técnico si su firma es vigente; None si no hay o quedó obsoleta."""
    if orden.con_evidencias and evidencias.estado_firma_tecnico(orden) == 'vigente':
        return evidencias.resumen_para_firma(orden)
    return None


def _estado_actual(orden):
    return {
        'puntos': [{'codigo': p.codigo, 'resultado': p.resultado, 'gravedad': p.gravedad, 'nota': p.nota}
                   for p in orden.puntos.all()],
        'mediciones': [{'codigo': m.codigo, 'valor': None if m.valor is None else format(m.valor, 'f')}
                       for m in orden.mediciones.all()],
        'observaciones': orden.observaciones, 'materiales': orden.materiales, 'sin_materiales': orden.sin_materiales,
        'fotos': orden.fotos.count(),
        'firma': evidencias.estado_firma(orden) != 'sin' if orden.con_evidencias else False,
        'firma_resumen': _firma_resumen(orden),
        'firma_tecnico': evidencias.estado_firma_tecnico(orden) != 'sin' if orden.con_evidencias else False,
        'firma_tecnico_resumen': _firma_tecnico_resumen(orden),
    }


@transaction.atomic
def descargar(orden, request):
    """Marca la orden como descargada (bloquea su reasignación) y devuelve el paquete para el teléfono."""
    _bloquear(orden)
    if orden.tecnico_id != request.user.id:
        raise Rechazo('Solo el técnico asignado puede descargar esta orden.', estado_http=403)
    if orden.estado not in ESTADOS_DESCARGABLES:
        raise Rechazo(f'No se puede descargar: la orden está {orden.get_estado_display().lower()}.')
    problema = certificado_problema(request.user, orden.requiere_refrigerante)
    if problema:
        raise Rechazo(f'No se puede descargar. {problema} Esta intervención requiere manipular refrigerante.')
    if orden.descargada_en is None:
        orden.descargada_en = timezone.now()
        orden.save()
        _evento(orden, request, 'Descargada para trabajo sin conexión')
    equipo = orden.equipo
    return {
        'orden': {
            'id': orden.id, 'codigo': orden.codigo, 'tipo': orden.tipo, 'tipo_texto': orden.get_tipo_display(),
            'descripcion': orden.descripcion, 'criticidad': orden.criticidad,
            'requiere_refrigerante': orden.requiere_refrigerante, 'con_checklist': orden.con_checklist,
            'con_evidencias': orden.con_evidencias if orden.estado == OrdenTrabajo.EN_EJECUCION else orden.con_checklist,
            'estado': orden.estado,
            'inicio': orden.inicio.isoformat() if orden.inicio else None,
            'fecha_programada': orden.fecha_programada.isoformat() if orden.fecha_programada else None,
            'subsanacion_motivo': orden.subsanacion_motivo, 'subsanacion_bloque': orden.subsanacion_bloque,
        },
        'equipo': {'codigo': equipo.codigo_identificador, 'nombre': equipo.nombre,
                   'ubicacion': equipo.ubicacion, 'tipo': equipo.tipo},
        'catalogo': _catalogo(orden),
        'estado_actual': _estado_actual(orden),
        'limites': {'fotos_min': evidencias.FOTOS_MINIMAS, 'fotos_max': evidencias.FOTOS_MAXIMAS,
                    'foto_bytes': evidencias.TAMANO_MAXIMO},
        'descargada_en': orden.descargada_en.isoformat(),
    }


# ---------------------------------------------------------------- lectura del paquete
def _cadena(valor, nombre):
    if valor is None:
        return ''
    if not isinstance(valor, str) or '\x00' in valor:
        raise Rechazo(f'{MSG_PAQUETE} («{nombre}» debe ser texto).')
    return valor


def _lista(valor, nombre, maximo):
    if not isinstance(valor, list) or len(valor) > maximo:
        raise Rechazo(f'{MSG_PAQUETE} («{nombre}» debe ser una lista de hasta {maximo} elementos).')
    return valor


def _numero_como_texto(valor):
    if valor is None or isinstance(valor, str):
        if valor and '\x00' in valor:
            raise Rechazo(f'{MSG_PAQUETE} (valor de medición incorrecto).')
        return valor or ''
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return str(valor)
    raise Rechazo(f'{MSG_PAQUETE} (valor de medición incorrecto).')


def leer_paquete(texto):
    """Valida la estructura del paquete JSON y lo devuelve normalizado. Cualquier defecto es un Rechazo 400."""
    try:
        datos = json.loads(texto or '')
    except (ValueError, TypeError):
        raise Rechazo(MSG_PAQUETE)
    if not isinstance(datos, dict):
        raise Rechazo(MSG_PAQUETE)
    try:
        paquete = {'paquete_id': uuid.UUID(str(datos.get('paquete_id', '')))}
    except ValueError:
        raise Rechazo('Falta el identificador del paquete o no es válido.')
    if datos.get('inicio') is not None:
        inicio = None
        if isinstance(datos['inicio'], str):
            try:
                inicio = parse_datetime(datos['inicio'])
            except ValueError:
                inicio = None
        if inicio is None or timezone.is_naive(inicio):
            raise Rechazo('La hora de inicio no es válida o no indica la zona horaria.')
        paquete['inicio'] = inicio
    if 'puntos' in datos:
        paquete['puntos'] = []
        for x in _lista(datos['puntos'], 'puntos', MAX_PUNTOS):
            if not isinstance(x, dict):
                raise Rechazo(f'{MSG_PAQUETE} (punto incorrecto).')
            paquete['puntos'].append({k: _cadena(x.get(k), k) for k in ('codigo', 'resultado', 'gravedad', 'nota')})
    if 'mediciones' in datos:
        paquete['mediciones'] = []
        for x in _lista(datos['mediciones'], 'mediciones', MAX_MEDICIONES):
            if not isinstance(x, dict):
                raise Rechazo(f'{MSG_PAQUETE} (medición incorrecta).')
            paquete['mediciones'].append({'codigo': _cadena(x.get('codigo'), 'codigo'),
                                          'valor': _numero_como_texto(x.get('valor'))})
    if 'elegidas' in datos:
        paquete['elegidas'] = [_cadena(c, 'elegidas') for c in _lista(datos['elegidas'], 'elegidas', MAX_MEDICIONES)]
    for campo in ('observaciones', 'materiales'):
        if campo in datos:
            paquete[campo] = _cadena(datos[campo], campo)
    if 'sin_materiales' in datos:
        if not isinstance(datos['sin_materiales'], bool):
            raise Rechazo(f'{MSG_PAQUETE} («sin_materiales» debe ser verdadero o falso).')
        paquete['sin_materiales'] = datos['sin_materiales']
    if 'fotos_ids' in datos:
        ids = []
        for x in _lista(datos['fotos_ids'], 'fotos_ids', evidencias.FOTOS_MAXIMAS):
            try:
                ids.append(uuid.UUID(str(x)))
            except ValueError:
                raise Rechazo(f'{MSG_PAQUETE} (identificador de fotografía incorrecto).')
        paquete['fotos_ids'] = ids
    if datos.get('firma') is not None:
        f = datos['firma']
        if not isinstance(f, dict):
            raise Rechazo(f'{MSG_PAQUETE} (firma incorrecta).')
        resumen = _lista(f.get('resumen', []), 'resumen', 500)
        paquete['firma'] = {'firmante': _cadena(f.get('firmante'), 'firmante'),
                            'imagen': _cadena(f.get('imagen'), 'imagen'),
                            'resumen': [_cadena(r, 'resumen') for r in resumen]}
    if datos.get('firma_tecnico') is not None:
        f = datos['firma_tecnico']
        if not isinstance(f, dict):
            raise Rechazo(f'{MSG_PAQUETE} (firma del técnico incorrecta).')
        resumen = _lista(f.get('resumen', []), 'resumen', 500)
        paquete['firma_tecnico'] = {'imagen': _cadena(f.get('imagen'), 'imagen'),
                                    'resumen': [_cadena(r, 'resumen') for r in resumen]}
    return paquete


# ---------------------------------------------------------------- sincronización
def _respuesta(orden, repetido, firma, avisos=(), firma_tecnico='ninguna'):
    orden.refresh_from_db()
    faltan = ordenes.validar_envio(orden) if orden.estado == OrdenTrabajo.EN_EJECUCION else []
    return {'ok': True, 'repetido': repetido, 'estado': orden.estado, 'firma': firma,
            'firma_estado': evidencias.estado_firma(orden) if orden.con_evidencias else 'sin',
            'firma_resumen': _firma_resumen(orden),
            'firma_tecnico': firma_tecnico,
            'firma_tecnico_estado': evidencias.estado_firma_tecnico(orden) if orden.con_evidencias else 'sin',
            'firma_tecnico_resumen': _firma_tecnico_resumen(orden),
            'avisos': list(avisos), 'faltan': faltan}


def _recordar(creados, campo):
    if campo and campo.name:
        creados.append((campo.storage, campo.name))


def _guardar_firma(orden, firma, request, creados):
    """('guardada' | 'descartada', aviso). Un problema con la firma nunca invalida el resto del trabajo."""
    if not orden.con_evidencias:
        return 'descartada', 'Esta orden no lleva firma del cliente; se ignoró la firma enviada.'
    if firma['resumen'] != evidencias.resumen_para_firma(orden):
        return 'descartada', ('La firma no corresponde al resumen actual de la orden: '
                              'el cliente debe firmar de nuevo.')
    try:
        guardada = evidencias.guardar_firma(orden, firma['firmante'], firma['imagen'], request)
    except ReglaError as e:
        return 'descartada', 'La firma no se guardó: ' + ' '.join(e.mensajes)
    _recordar(creados, guardada.imagen)
    return 'guardada', ''


def _mismo_valor(actual, texto):
    """¿El texto enviado equivale al valor ya guardado? (si no se puede interpretar, que decida el servicio)"""
    if actual is None:
        return False
    try:
        return Decimal(texto.strip().replace(',', '.')).quantize(Decimal('0.01')) == actual
    except (InvalidOperation, ValueError):
        return False


def _aplicar(orden, paquete, archivos, request, creados):
    _bloquear(orden)
    if orden.tecnico_id != request.user.id:
        raise Rechazo('Solo el técnico asignado puede sincronizar esta orden.', estado_http=403)
    previa = SincronizacionOT.objects.filter(paquete_id=paquete['paquete_id']).first()
    if previa:
        if previa.orden_id != orden.id:
            raise Rechazo(MSG_PAQUETE)
        return _respuesta(orden, True, previa.firma)
    if orden.estado == OrdenTrabajo.CANCELADA:
        motivo = orden.motivo_cancelacion or 'sin motivo indicado'
        raise Rechazo(f'La orden fue cancelada ({motivo}). Tu trabajo sigue guardado en el teléfono; avisa a gestión.',
                      estado_http=409)
    if orden.estado not in ESTADOS_DESCARGABLES:
        raise Rechazo(f'La orden ya no admite cambios (estado: {orden.get_estado_display().lower()}).',
                      estado_http=409)
    if orden.descargada_en is None:
        raise Rechazo('La descarga de esta orden fue liberada por gestión: vuelve a prepararla con señal.')

    if orden.estado == OrdenTrabajo.ASIGNADA:
        inicio = paquete.get('inicio')
        if inicio is None:
            raise Rechazo('Falta la hora de inicio de la intervención.')
        if inicio < orden.descargada_en:
            raise Rechazo('La hora de inicio es anterior a la descarga de la orden. '
                          'Revisa la fecha y la hora del teléfono.')
        if inicio > timezone.now() + TOLERANCIA_RELOJ:
            raise Rechazo('La hora de inicio está en el futuro. Revisa la fecha y la hora del teléfono.')
        ordenes.iniciar(orden, request, inicio=inicio)

    if 'elegidas' in paquete and set(paquete['elegidas']) != set(orden.mediciones.values_list('codigo', flat=True)):
        ordenes.elegir_mediciones(orden, paquete['elegidas'], request)
    n_puntos = n_mediciones = 0
    # Solo se aplican los cambios reales: en una subsanación el teléfono reenvía también lo que ya estaba guardado
    # y los bloques bloqueados no deben rechazar un valor que no cambia.
    puntos = {p.codigo: p for p in orden.puntos.all()}
    for x in paquete.get('puntos', []):
        punto = puntos.get(x['codigo'])
        if punto is None:
            raise Rechazo(f"Punto de checklist desconocido: {x['codigo'][:40]}.")
        if not x['resultado']:
            continue  # sin marcar: no hay nada que guardar
        incidencia = x['resultado'] == PuntoChecklistOT.INCIDENCIA
        nuevo = (x['resultado'], x['gravedad'] if incidencia else '', x['nota'].strip()[:255] if incidencia else '')
        if nuevo == (punto.resultado, punto.gravedad, punto.nota):
            continue
        ordenes.marcar_punto(orden, x['codigo'], x['resultado'], x['gravedad'], x['nota'], request)
        n_puntos += 1
    medidas = {m.codigo: m for m in orden.mediciones.all()}
    for x in paquete.get('mediciones', []):
        medicion = medidas.get(x['codigo'])
        if medicion is None:
            raise Rechazo(f"Medición desconocida: {x['codigo'][:40]}.")
        if x['valor'] == '' or _mismo_valor(medicion.valor, x['valor']):
            continue
        ordenes.registrar_medicion(orden, x['codigo'], x['valor'], request)
        n_mediciones += 1
    actual = (orden.observaciones, orden.materiales, orden.sin_materiales)
    nuevo = (paquete.get('observaciones', orden.observaciones), paquete.get('materiales', orden.materiales),
             paquete.get('sin_materiales', orden.sin_materiales))
    if nuevo != actual:
        ordenes.guardar_ejecucion(orden, *nuevo, request)
    ids = paquete.get('fotos_ids')
    if ids is not None and len(ids) != len(archivos):
        raise Rechazo(f'{MSG_PAQUETE} (las fotografías no coinciden con sus identificadores).')
    n_fotos = 0
    for i, archivo in enumerate(archivos):
        cliente_id = ids[i] if ids else None
        if cliente_id and orden.fotos.filter(cliente_id=cliente_id).exists():
            continue  # ya llegó en un envío anterior cuya respuesta se perdió
        foto = evidencias.subir_foto(orden, archivo, request)
        _recordar(creados, foto.imagen)
        if cliente_id:
            foto.cliente_id = cliente_id
            foto.save(update_fields=['cliente_id'])
        n_fotos += 1

    firma, avisos = 'ninguna', []
    if paquete.get('firma') is not None:
        firma, aviso = _guardar_firma(orden, paquete['firma'], request, creados)
        if aviso:
            avisos.append(aviso)

    firma_tecnico = 'ninguna'
    if paquete.get('firma_tecnico') is not None:
        firma_tecnico, aviso = _guardar_firma_tecnico(orden, paquete['firma_tecnico'], request, creados)
        if aviso:
            avisos.append(aviso)

    SincronizacionOT.objects.create(paquete_id=paquete['paquete_id'], orden=orden, usuario=request.user, firma=firma)
    _evento(orden, request, f'Sincronizado desde modo sin conexión ({n_puntos} puntos, '
                            f'{n_mediciones} mediciones, {n_fotos} fotos)')
    return _respuesta(orden, False, firma, avisos, firma_tecnico)


def _guardar_firma_tecnico(orden, firma, request, creados):
    """('guardada' | 'descartada', aviso). Igual que la del cliente: un problema aquí no invalida el resto."""
    if not orden.con_evidencias:
        return 'descartada', 'Esta orden no lleva firma del técnico; se ignoró la firma enviada.'
    if firma['resumen'] != evidencias.resumen_para_firma(orden):
        return 'descartada', 'La firma del técnico no corresponde al resumen actual de la orden: firma de nuevo.'
    try:
        guardada = evidencias.guardar_firma_tecnico(orden, firma['imagen'], request)
    except ReglaError as e:
        return 'descartada', 'La firma del técnico no se guardó: ' + ' '.join(e.mensajes)
    _recordar(creados, guardada.imagen)
    return 'guardada', ''


@transaction.atomic
def sincronizar(orden, paquete, archivos, request):
    """Aplica el paquete completo o nada. Si se revierte, también se borran los archivos escritos en esta llamada."""
    if len(archivos) > evidencias.FOTOS_MAXIMAS:
        raise Rechazo(f'Un paquete no puede llevar más de {evidencias.FOTOS_MAXIMAS} fotografías.')
    creados = []
    try:
        return _aplicar(orden, paquete, archivos, request, creados)
    except Exception:
        for almacen, nombre in creados:
            almacen.delete(nombre)
        raise

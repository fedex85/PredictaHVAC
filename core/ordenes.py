"""Reglas del ciclo de vida de las órdenes de trabajo (Pendiente -> ... -> Finalizada / Cancelada)."""
import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core import auditoria, checklists
from core.models import (EquipoHVAC, EventoOT, HistorialMantenimiento, MedicionOT, NotaAdministrativa, OrdenTrabajo, PausaOT, PuntoChecklistOT,
                         RegistroActividad)
from core.permisos import ADMIN, ROLES_GESTION, TECNICO, rol_de


class ReglaError(Exception):
    """Una regla de negocio impide la acción. `mensajes` es la lista de motivos mostrados al usuario."""
    def __init__(self, *mensajes):
        super().__init__(' '.join(mensajes))
        self.mensajes = list(mensajes)


def nombre_de(usuario):
    return (usuario.get_full_name() or usuario.get_username()) if usuario else '—'


# ---------------------------------------------------------------- certificación
def certificado_problema(tecnico, requiere_refrigerante, fecha=None):
    """Texto del problema si el técnico no puede manipular refrigerante; None si todo está en regla.
    Con `fecha` evalúa el certificado en ese día (trabajo hecho sin conexión); sin ella, hoy."""
    if not requiere_refrigerante or tecnico is None or rol_de(tecnico) == ADMIN:
        return None
    perfil = getattr(tecnico, 'perfil', None)
    if perfil is None:
        estado = 'sin'
    elif fecha is None:
        estado = perfil.cert_estado
    elif not perfil.cert_numero or not perfil.cert_caducidad:
        estado = 'sin'
    else:
        estado = 'caducado' if perfil.cert_caducidad < fecha else 'vigente'
    if estado == 'caducado':
        return (f"{nombre_de(tecnico)} tiene el certificado de manipulador de gases fluorados "
                f"caducado desde el {perfil.cert_caducidad:%d/%m/%Y}.")
    if estado == 'sin':
        return f"{nombre_de(tecnico)} no tiene certificado de manipulador de gases fluorados registrado."
    return None


# ---------------------------------------------------------------- permisos de cancelación
def puede_cancelar(orden, usuario):
    rol = rol_de(usuario)
    gestion = rol in ROLES_GESTION
    creador = orden.creado_por_id == usuario.id
    asignado = orden.tecnico_id == usuario.id
    if orden.estado == OrdenTrabajo.PENDIENTE:
        return gestion or creador
    if orden.estado in (OrdenTrabajo.ASIGNADA, OrdenTrabajo.EN_EJECUCION):
        return gestion or creador or asignado
    return False


def motivo_no_cancelable(orden):
    if orden.estado == OrdenTrabajo.PENDIENTE_APROBACION:
        return 'Una OT pendiente de aprobación no se puede cancelar. Aprueba la OT o solicita una subsanación.'
    if orden.estado == OrdenTrabajo.FINALIZADA:
        return 'Una OT finalizada no se puede cancelar.'
    if orden.estado == OrdenTrabajo.CANCELADA:
        return 'Una OT cancelada no se reabre.'
    return 'Tu rol no puede cancelar esta OT en su estado actual.'


# ---------------------------------------------------------------- utilidades
def _evento(orden, request, texto):
    EventoOT.objects.create(orden=orden, usuario_nombre=nombre_de(request.user), texto=texto[:255])
    auditoria.registrar(RegistroActividad.ORDEN_ACTUALIZADA, request, detalle=f"{orden.codigo}: {texto}")


def _bloquear(orden):
    """Bloquea la fila de la orden hasta el final de la transacción (evita acciones simultáneas) y la recarga."""
    OrdenTrabajo.objects.select_for_update().get(pk=orden.pk)
    orden.refresh_from_db()


def _exigir_gestion(request):
    if rol_de(request.user) not in ROLES_GESTION:
        raise ReglaError('Solo un administrador o gerente puede hacer esto.')


def _exigir_tecnico(orden, request):
    if orden.tecnico_id != request.user.id:
        raise ReglaError('Solo el técnico asignado puede hacer esto.')


def _exigir_estado(orden, *estados):
    if orden.estado not in estados:
        actual = orden.get_estado_display()
        raise ReglaError(f'La OT ya no está en un estado que lo permita (estado actual: {actual}).')


# ---------------------------------------------------------------- creación
@transaction.atomic
def crear(orden, request):
    """Guarda una orden nueva: Asignada si trae técnico, Pendiente si no."""
    orden.creado_por = request.user
    orden.estado = OrdenTrabajo.ASIGNADA if orden.tecnico_id else OrdenTrabajo.PENDIENTE
    orden.save()
    texto = f"Creada y asignada a {nombre_de(orden.tecnico)}" if orden.tecnico_id else 'Creada sin técnico (Pendiente)'
    if orden.continuacion_de_id:
        texto += f'. Continuación de {orden.continuacion_de.codigo}'
    EventoOT.objects.create(orden=orden, usuario_nombre=nombre_de(request.user), texto=texto)
    auditoria.registrar(RegistroActividad.ORDEN_CREADA, request,
                        detalle=f"{orden.codigo} · {orden.equipo.codigo_identificador} · {orden.get_estado_display()}")
    return orden


def antecedente_de(original):
    """Incidente de la orden original que se copia como antecedente histórico bloqueado de la continuación."""
    texto = (original.observaciones or '').strip() or (original.descripcion or '').strip()
    return f'{original.codigo} · {original.equipo.codigo_identificador}: {texto}'


@transaction.atomic
def añadir_nota(orden, texto, request):
    """Nota administrativa/histórica de gestión sobre una orden cerrada; no modifica datos técnicos."""
    _exigir_gestion(request)
    _exigir_estado(orden, OrdenTrabajo.FINALIZADA, OrdenTrabajo.CANCELADA)
    texto = (texto or '').strip()
    if not texto:
        raise ReglaError('Escribe la nota.')
    NotaAdministrativa.objects.create(orden=orden, usuario_nombre=nombre_de(request.user), texto=texto[:2000])
    _evento(orden, request, 'Nota administrativa añadida')


@transaction.atomic
def crear_emergencia(orden, request):
    """OT correctiva/emergencia creada por el propio técnico: nace Asignada a él y se avisa a gestión."""
    if rol_de(request.user) != TECNICO:
        raise ReglaError('Solo un técnico crea órdenes de emergencia desde el móvil.')
    orden.tecnico = request.user
    orden.tipo = 'CORRECTIVO'
    crear(orden, request)
    _evento(orden, request, 'Creada por el técnico como correctiva/emergencia sobre un equipo del inventario')
    from core import avisos
    avisos.notificar_gestion(f'{nombre_de(request.user)} creó la OT de emergencia {orden.codigo} sobre '
                             f'{orden.equipo.codigo_identificador} (criticidad {orden.get_criticidad_display().lower()}).', orden)
    return orden


# ---------------------------------------------------------------- transiciones
@transaction.atomic
def asignar(orden, tecnico, request):
    orden.refresh_from_db()
    _exigir_gestion(request)
    _exigir_estado(orden, OrdenTrabajo.PENDIENTE, OrdenTrabajo.ASIGNADA)
    if orden.descargada_en:
        raise ReglaError('El técnico ya descargó esta orden para trabajar sin conexión. '
                         'Usa «Liberar descarga» antes de reasignarla.')
    if rol_de(tecnico) != TECNICO or not tecnico.is_active:
        raise ReglaError('Elige un técnico activo.')
    problema = certificado_problema(tecnico, orden.requiere_refrigerante)
    if problema:
        raise ReglaError(f'No se puede asignar. {problema} Esta intervención requiere manipular refrigerante.')
    orden.tecnico, orden.estado = tecnico, OrdenTrabajo.ASIGNADA
    orden.save()
    _evento(orden, request, f'Asignada a {nombre_de(tecnico)}')


def validar_llegada(estado, texto=''):
    """Estado de llegada obligatorio; «Otro» exige texto. Devuelve (estado, texto) limpios."""
    estado, texto = (estado or '').strip(), (texto or '').strip()
    if estado not in dict(OrdenTrabajo.LLEGADA_CHOICES):
        raise ReglaError('Indica el estado en el que encuentras el equipo al llegar.')
    if estado == 'OTRO' and not texto:
        raise ReglaError('Describe el estado de llegada («Otro»).')
    return estado, (texto[:255] if estado == 'OTRO' else '')


def identificar_equipo(texto):
    """Equipo que corresponde a lo leído del QR (URL de su ficha) o escrito a mano (su código). None si no existe."""
    texto = (texto or '').strip()
    if not texto:
        return None
    m = re.search(r'/equipos/(\d+)/?(?:[?#].*)?$', texto)
    if m:
        return EquipoHVAC.objects.filter(pk=int(m.group(1))).first()
    return EquipoHVAC.objects.filter(codigo_identificador__iexact=texto).first()


def _verificar_equipo(orden, verificacion):
    """Devuelve (modo, detalle). `verificacion` = {'codigo', 'continuar', 'nota', 'estricto'}.

    Estricto (web): una discrepancia bloquea salvo «continuar y reportar incidencia» con observación.
    No estricto (paquete sin conexión): el teléfono ya bloqueó; el servidor registra lo que declaró sin rechazar el trabajo."""
    codigo = (verificacion.get('codigo') or '').strip()
    nota = (verificacion.get('nota') or '').strip()
    continuar, estricto = bool(verificacion.get('continuar')), verificacion.get('estricto', True)
    identificado = identificar_equipo(codigo)
    if identificado is not None and identificado.pk == orden.equipo_id:
        return ('QR' if '/' in codigo else 'MANUAL'), identificado.codigo_identificador
    if estricto:
        if not codigo and not continuar:
            raise ReglaError('Identifica el equipo (escanea su QR o escribe su código) antes de iniciar.')
        if not continuar:
            raise ReglaError(
                f'El equipo identificado ({identificado.codigo_identificador if identificado else codigo}) no coincide con el de la '
                f'orden ({orden.equipo.codigo_identificador}). Vuelve a escanear, busca manualmente o continúa y reporta una incidencia.')
        if not nota:
            raise ReglaError('Para continuar con un equipo distinto describe la incidencia en la observación.')
    quien = identificado.codigo_identificador if identificado else (codigo or 'sin identificar')
    return 'DISCREPANCIA', f'OT: {orden.equipo.codigo_identificador}; identificado: {quien}. {nota or "Sin observación."}'[:255]


@transaction.atomic
def iniciar(orden, request, inicio=None, llegada=None, verificacion=None):
    """Inicia la intervención. `inicio` (con zona horaria) es la hora real cuando se empezó sin conexión.
    `llegada` = (estado, texto); solo falta en paquetes sin conexión de versiones anteriores de la app."""
    orden.refresh_from_db()
    _exigir_estado(orden, OrdenTrabajo.ASIGNADA)
    if orden.tecnico_id != request.user.id:
        raise ReglaError('Esta OT está asignada a otro técnico: solo el técnico asignado puede iniciarla.')
    fecha = timezone.localtime(inicio).date() if inicio else None
    problema = certificado_problema(request.user, orden.requiere_refrigerante, fecha)
    if problema:
        raise ReglaError(f'No se puede iniciar la intervención. {problema} '
                         'Esta intervención requiere manipular refrigerante.')
    if llegada is not None:
        llegada = validar_llegada(*llegada)
    verificado = _verificar_equipo(orden, verificacion) if verificacion is not None else None
    orden.estado, orden.inicio = OrdenTrabajo.EN_EJECUCION, inicio or timezone.now()
    orden.con_evidencias = True  # toda OT lleva 3 fotos y las dos firmas, también sin checklist
    if llegada:
        orden.llegada, orden.llegada_texto = llegada
    if verificado:
        orden.verificacion, orden.verificacion_detalle = verificado
    orden.save()
    texto = 'Intervención iniciada'
    if inicio:
        # Trabajo sin conexión: queda constancia de lo que declaró el teléfono y de cuándo lo recibió el servidor
        recibido = timezone.now()
        segundos = max(0, int((recibido - inicio).total_seconds()))
        texto += (f' sin conexión (inicio declarado {timezone.localtime(inicio):%d/%m %H:%M}, '
                  f'recibido {timezone.localtime(recibido):%d/%m %H:%M}, diferencia {segundos // 3600} h {segundos % 3600 // 60} min)')
    if llegada:
        texto += f'. Estado de llegada: {orden.llegada_texto_completo}'
    if verificado:
        texto += ('. Equipo verificado por ' + ('QR' if verificado[0] == 'QR' else 'código')) if verificado[0] != 'DISCREPANCIA' \
            else '. DISCREPANCIA de equipo'
    if orden.con_checklist:
        puntos, mediciones = generar_checklist(orden)
        if puntos or mediciones:
            texto += f'. Checklist generado: {puntos} puntos y {mediciones} mediciones'
    _evento(orden, request, texto)
    if verificado and verificado[0] == 'DISCREPANCIA':
        EventoOT.objects.create(orden=orden, usuario_nombre=nombre_de(request.user),
                                texto=f'Discrepancia de equipo: {verificado[1]}'[:255])
        from core import avisos
        avisos.notificar_gestion(f'{orden.codigo}: el técnico {nombre_de(request.user)} inició la orden con un equipo '
                                 f'distinto al previsto ({orden.equipo.codigo_identificador}). Revisa el historial.', orden)


@transaction.atomic
def liberar_descarga(orden, request):
    """Gestión anula la descarga sin conexión para poder reasignar la orden."""
    orden.refresh_from_db()
    _exigir_gestion(request)
    _exigir_estado(orden, OrdenTrabajo.ASIGNADA, OrdenTrabajo.EN_EJECUCION)
    if not orden.descargada_en:
        raise ReglaError('Esta orden no está descargada para trabajar sin conexión.')
    orden.descargada_en = None
    orden.save()
    _evento(orden, request, f'Descarga liberada por {nombre_de(request.user)}')


@transaction.atomic
def pausar(orden, motivo, request):
    orden.refresh_from_db()
    _exigir_tecnico(orden, request)
    _exigir_estado(orden, OrdenTrabajo.EN_EJECUCION)
    motivo = (motivo or '').strip()
    if not motivo:
        raise ReglaError('El motivo de la pausa es obligatorio.')
    if orden.pausa_activa:
        raise ReglaError('La intervención ya está en pausa.')
    PausaOT.objects.create(orden=orden, motivo=motivo[:255], desde=timezone.now())
    _evento(orden, request, f'Pausa: {motivo}')


@transaction.atomic
def reanudar(orden, request):
    orden.refresh_from_db()
    _exigir_tecnico(orden, request)
    _exigir_estado(orden, OrdenTrabajo.EN_EJECUCION)
    pausa = orden.pausa_activa
    if not pausa:
        raise ReglaError('La intervención no está en pausa.')
    pausa.hasta = timezone.now()
    pausa.save()
    _evento(orden, request, 'Intervención reanudada')


# ---------------------------------------------------------------- checklist y mediciones
def generar_checklist(orden):
    """Copia a la orden los puntos y mediciones del catálogo. Idempotente: devuelve (puntos, mediciones) creados."""
    if orden.puntos.exists() or orden.mediciones.exists():
        return 0, 0
    tipo = orden.equipo.tipo
    puntos = [PuntoChecklistOT(orden=orden, codigo=p.codigo, bloque=p.bloque, texto=p.texto, orden_visual=i)
              for i, p in enumerate(checklists.puntos_para(tipo, orden.requiere_refrigerante))]
    mediciones = [MedicionOT(orden=orden, codigo=m.codigo, etiqueta=m.etiqueta, unidad=m.unidad, obligatoria=True)
                  for m in checklists.mediciones_para(tipo)]
    PuntoChecklistOT.objects.bulk_create(puntos, ignore_conflicts=True)  # un doble clic simultáneo no debe dar error 500
    MedicionOT.objects.bulk_create(mediciones, ignore_conflicts=True)
    return len(puntos), len(mediciones)


def _etiqueta_bloque(codigo):
    return dict(OrdenTrabajo.BLOQUES).get(codigo, codigo)


def puede_editar(orden, bloque):
    """¿Puede el técnico escribir en este bloque? Solo En ejecución y, en una subsanación, solo el bloque indicado."""
    if orden.estado != OrdenTrabajo.EN_EJECUCION:
        return False
    if not orden.subsanacion_motivo:
        return True
    if bloque == 'FIRMA_TECNICO':
        return True  # el técnico renueva su firma cuando corrige algo
    if bloque == 'FIRMA':
        # Cualquier cambio posterior invalida la firma; sin poder firmar de nuevo la orden quedaría bloqueada.
        from core import evidencias
        if orden.con_evidencias and evidencias.estado_firma(orden) != 'vigente':
            return True
    return orden.subsanacion_bloque in ('', bloque)


def _exigir_edicion(orden, request, bloque):
    _exigir_tecnico(orden, request)
    _exigir_estado(orden, OrdenTrabajo.EN_EJECUCION)
    if not puede_editar(orden, bloque):
        raise ReglaError(f'Esta subsanación solo permite editar: {_etiqueta_bloque(orden.subsanacion_bloque)}.')


@transaction.atomic
def marcar_punto(orden, codigo, resultado, gravedad, nota, request):
    orden.refresh_from_db()
    _exigir_edicion(orden, request, 'CHECKLIST')
    punto = orden.puntos.filter(codigo=codigo).first()
    if punto is None:
        raise ReglaError('Punto de checklist desconocido.')
    if resultado == PuntoChecklistOT.OK:
        punto.resultado, punto.gravedad, punto.nota = PuntoChecklistOT.OK, '', ''
    elif resultado == PuntoChecklistOT.INCIDENCIA:
        if gravedad not in dict(PuntoChecklistOT.GRAVEDADES):
            raise ReglaError('Indica la gravedad de la incidencia.')
        punto.resultado, punto.gravedad, punto.nota = PuntoChecklistOT.INCIDENCIA, gravedad, (nota or '').strip()[:255]
    else:
        raise ReglaError('Marca el punto como OK o como Incidencia.')
    punto.save()
    from core import incidencias
    incidencias.anular_si_cambia(punto, request)
    return punto


@transaction.atomic
def registrar_medicion(orden, codigo, valor, request):
    orden.refresh_from_db()
    _exigir_edicion(orden, request, 'MEDICIONES')
    medicion = orden.mediciones.filter(codigo=codigo).first()
    if medicion is None:
        raise ReglaError('Medición desconocida.')
    texto = (valor or '').strip().replace(',', '.')
    if texto == '':
        medicion.valor = None
    else:
        try:
            numero = Decimal(texto)
            if not numero.is_finite():
                raise InvalidOperation
            numero = numero.quantize(Decimal('0.01'))
        except InvalidOperation:
            raise ReglaError('Introduce un número válido (por ejemplo 12,5).')
        definicion = checklists.MEDICIONES.get(codigo)
        if definicion and not (definicion.minimo <= numero <= definicion.maximo):
            raise ReglaError(f'{medicion.etiqueta} debe estar entre {definicion.minimo:f} y '
                             f'{definicion.maximo:f} {medicion.unidad}.')
        medicion.valor = numero
    medicion.save()
    return medicion


@transaction.atomic
def elegir_mediciones(orden, codigos, request):
    orden.refresh_from_db()
    _exigir_edicion(orden, request, 'MEDICIONES')
    if orden.tiene_checklist:
        raise ReglaError('Las mediciones se eligen solo en OT sin checklist.')
    codigos = set(codigos)
    if not codigos <= set(checklists.MEDICIONES):
        raise ReglaError('Medición desconocida.')
    orden.mediciones.exclude(codigo__in=codigos).delete()
    existentes = set(orden.mediciones.values_list('codigo', flat=True))
    for c in sorted(codigos - existentes):
        d = checklists.MEDICIONES[c]
        MedicionOT.objects.create(orden=orden, codigo=c, etiqueta=d.etiqueta, unidad=d.unidad, obligatoria=True)


def avance_por_bloque(orden):
    """{'FUNCIONAMIENTO': {'hechos': 2, 'total': 5}, …, 'MEDICIONES': {...}}: solo los bloques con elementos."""
    avance = {}
    for p in orden.puntos.all():
        b = avance.setdefault(p.bloque, {'hechos': 0, 'total': 0})
        b['total'] += 1
        b['hechos'] += 1 if p.completo else 0
    medibles = [m for m in orden.mediciones.all() if m.obligatoria]
    if medibles:
        avance[checklists.MEDICIONES_BLOQUE] = {'hechos': sum(1 for m in medibles if m.valor is not None),
                                                'total': len(medibles)}
    if orden.con_evidencias:
        from core import evidencias
        avance[checklists.FOTOS] = {'hechos': min(orden.fotos.count(), evidencias.FOTOS_MINIMAS),
                                    'total': evidencias.FOTOS_MINIMAS}
        avance[checklists.FIRMA] = {'hechos': int(evidencias.firma_vigente(orden)) + int(evidencias.firma_tecnico_vigente(orden)),
                                    'total': 2}
    return {b: avance[b] for b in checklists.ORDEN_BLOQUES if b in avance}


@transaction.atomic
def guardar_ejecucion(orden, observaciones, materiales, sin_materiales, request):
    orden.refresh_from_db()
    _exigir_tecnico(orden, request)
    _exigir_estado(orden, OrdenTrabajo.EN_EJECUCION)
    edita_obs, edita_mat = puede_editar(orden, 'OBSERVACIONES'), puede_editar(orden, 'MATERIALES')
    if not (edita_obs or edita_mat):
        raise ReglaError(f'Esta subsanación solo permite editar: {_etiqueta_bloque(orden.subsanacion_bloque)}.')
    if edita_obs:
        orden.observaciones = observaciones or ''
    if edita_mat:
        orden.sin_materiales = bool(sin_materiales)
        orden.materiales = '' if sin_materiales else (materiales or '')
    orden.save()
    auditoria.registrar(RegistroActividad.ORDEN_ACTUALIZADA, request, detalle=f'{orden.codigo}: datos de la intervención guardados')


def incidencias_abiertas(orden):
    """Puntos del checklist con incidencia (de cualquier gravedad): impiden «cerrar sin acción»."""
    return [p for p in orden.puntos.all() if p.resultado == PuntoChecklistOT.INCIDENCIA]


def problema_proxima_accion(orden):
    """Motivo por el que la próxima acción elegida no es válida (o falta); None si está bien."""
    accion = orden.proxima_accion
    if accion not in dict(OrdenTrabajo.PROXIMA_CHOICES):
        return 'Elige la próxima acción: programar revisión, crear OT correctiva o cerrar sin acción'
    if accion == 'REVISION' and not orden.proxima_fecha:
        return 'Indica la fecha propuesta para la próxima revisión'
    if accion == 'CORRECTIVA' and not (orden.proxima_texto.strip() or orden.proxima_orden_id):
        return 'Describe la OT correctiva que hay que crear'
    if accion == 'NINGUNA' and incidencias_abiertas(orden):
        return 'No se puede cerrar sin acción: hay incidencias abiertas en el checklist'
    return None


@transaction.atomic
def elegir_proxima_accion(orden, accion, fecha, texto, request):
    """Tras la firma, el técnico decide qué pasa después. La OT correctiva se crea al enviar a aprobación."""
    orden.refresh_from_db()
    _exigir_tecnico(orden, request)
    _exigir_estado(orden, OrdenTrabajo.EN_EJECUCION)
    if orden.subsanacion_motivo:
        raise ReglaError('En una subsanación no se cambia la próxima acción.')
    if orden.proxima_orden_id:
        raise ReglaError('Ya se creó la OT correctiva: la próxima acción no se puede cambiar.')
    if accion not in dict(OrdenTrabajo.PROXIMA_CHOICES):
        raise ReglaError('Elige una de las tres opciones.')
    hoy = timezone.localdate()
    if accion == 'REVISION':
        if fecha is None:
            raise ReglaError('Indica la fecha propuesta para la próxima revisión.')
        if fecha < hoy or fecha > hoy.replace(year=hoy.year + 3):
            raise ReglaError('La fecha de la próxima revisión debe estar entre hoy y dentro de tres años.')
    texto = (texto or '').strip()
    if accion == 'CORRECTIVA' and not texto:
        raise ReglaError('Describe la OT correctiva que hay que crear.')
    orden.proxima_accion = accion
    orden.proxima_fecha = fecha if accion == 'REVISION' else None
    orden.proxima_texto = texto[:255] if accion == 'CORRECTIVA' else ''
    problema = problema_proxima_accion(orden)
    if problema:
        raise ReglaError(problema)
    orden.save()
    _evento(orden, request, f'Próxima acción: {dict(OrdenTrabajo.PROXIMA_CHOICES)[accion]}'
            + (f' ({fecha:%d/%m/%Y})' if accion == 'REVISION' else ''))


def _crear_derivada(orden, request, tipo, descripcion, fecha=None, origen=False):
    nueva = OrdenTrabajo(equipo=orden.equipo, tipo=tipo, descripcion=descripcion, criticidad=orden.criticidad,
                         requiere_refrigerante=orden.requiere_refrigerante, fecha_programada=fecha,
                         orden_origen=orden if origen else None)
    return crear(nueva, request)


def validar_envio(orden):
    """Lista de motivos que impiden enviar la OT a aprobación (vacía si puede enviarse)."""
    problemas = []
    if orden.pausa_activa:
        problemas.append('Hay una pausa activa. Pulsa CONTINUAR antes de enviar.')
    puntos = list(orden.puntos.all()) if orden.con_checklist else []
    for p in puntos:
        if not p.resultado:
            problemas.append(f'Falta marcar: {p.texto}')
        elif p.resultado == PuntoChecklistOT.INCIDENCIA and not p.gravedad:
            problemas.append(f'Falta indicar la gravedad de: {p.texto}')
    for m in orden.mediciones.filter(obligatoria=True, valor__isnull=True):
        problemas.append(f'Falta medir: {m.etiqueta}')
    if orden.con_evidencias:
        from core import evidencias
        faltan = evidencias.fotos_faltantes(orden)
        if faltan:
            problemas.append('Falta 1 fotografía' if faltan == 1 else f'Faltan {faltan} fotografías')
        firma = evidencias.estado_firma(orden)
        if firma == 'sin':
            problemas.append('Falta la firma del cliente')
        elif firma == 'obsoleta':
            problemas.append('El resumen cambió después de la firma: recoge la firma de nuevo')
        firma_tec = evidencias.estado_firma_tecnico(orden)
        if firma_tec == 'sin':
            problemas.append('Falta la firma del técnico')
        elif firma_tec == 'obsoleta':
            problemas.append('El resumen cambió después de tu firma: firma de nuevo como técnico')
    if orden.con_evidencias:
        problema = problema_proxima_accion(orden)
        if problema:
            problemas.append(problema)
    if not orden.observaciones.strip():
        if not puntos:
            problemas.append('Las observaciones técnicas son obligatorias: OT sin checklist.')
        elif any(p.resultado == PuntoChecklistOT.INCIDENCIA for p in puntos):
            problemas.append('Las observaciones técnicas son obligatorias: hay incidencias en el checklist.')
    if not orden.sin_materiales and not orden.materiales.strip():
        problemas.append('Materiales: marca SIN MATERIALES o registra al menos un material.')
    return problemas


@transaction.atomic
def enviar(orden, request):
    orden.refresh_from_db()
    _exigir_tecnico(orden, request)
    _exigir_estado(orden, OrdenTrabajo.EN_EJECUCION)
    problemas = validar_envio(orden)
    if problemas:
        raise ReglaError(*problemas)
    firma_conservada = False
    if orden.con_evidencias:
        from core import evidencias
        firma_conservada = evidencias.fijar_firma_conservada(orden)
    if orden.con_evidencias and orden.proxima_accion == 'CORRECTIVA' and not orden.proxima_orden_id:
        correctiva = _crear_derivada(orden, request, 'CORRECTIVO', orden.proxima_texto, origen=True)
        orden.proxima_orden = correctiva
        _evento(orden, request, f'Próxima acción: creada la OT correctiva {correctiva.codigo} (Pendiente de asignación)')
    orden.estado = OrdenTrabajo.PENDIENTE_APROBACION
    orden.subsanacion_motivo, orden.subsanacion_bloque = '', ''
    orden.save()
    _evento(orden, request, 'Enviada a aprobación' + ('. Firma del cliente conservada tras la subsanación' if firma_conservada else ''))
    if getattr(settings, 'APROBACION_AUTOMATICA', False):
        from core import incidencias
        if not incidencias.pendientes_alta(orden):
            _finalizar(orden, request, 'Aprobada automáticamente (aprobación automática activada en la empresa)')
            return
    from core import avisos
    avisos.notificar_gestion(f'{orden.codigo} ({orden.equipo.codigo_identificador}) espera tu aprobación.', orden)


@transaction.atomic
def aprobar(orden, request, fecha_revision=None):
    _bloquear(orden)
    _exigir_gestion(request)
    _exigir_estado(orden, OrdenTrabajo.PENDIENTE_APROBACION)
    from core import incidencias
    pendientes = len(incidencias.pendientes_alta(orden))
    if pendientes:
        raise ReglaError('Falta 1 incidencia Alta por resolver' if pendientes == 1
                         else f'Faltan {pendientes} incidencias Alta por resolver')
    if orden.proxima_accion == 'REVISION':
        fecha_revision = fecha_revision or orden.proxima_fecha
        if fecha_revision is None or fecha_revision < timezone.localdate():
            raise ReglaError('Confirma una fecha válida (hoy o posterior) para la próxima revisión.')
    _finalizar(orden, request, 'Aprobada y finalizada', fecha_revision)


def _finalizar(orden, request, texto_evento, fecha_revision=None):
    from core import incidencias
    descripcion = f"[{orden.codigo}] {orden.descripcion}\n\nObservaciones: {orden.observaciones.strip()}"
    if orden.materiales.strip():
        descripcion += f"\nMateriales: {orden.materiales.strip()}"
    if orden.llegada:
        descripcion += f"\nEstado de llegada: {orden.llegada_texto_completo}"
    puntos = list(orden.puntos.all())
    if puntos:
        graves = {g: sum(1 for p in puntos if p.gravedad == g) for g, _ in PuntoChecklistOT.GRAVEDADES}
        n_incidencias = sum(graves.values())
        descripcion += (f"\nChecklist: {len(puntos)} puntos revisados, {n_incidencias} incidencias "
                        f"(Leve {graves['LEVE']}, Media {graves['MEDIA']}, Alta {graves['ALTA']}).")
    resumen = incidencias.resumen_decisiones(orden)
    if resumen:
        descripcion += "\n" + resumen
    medidas = [f"{m.etiqueta} {m.valor.normalize():f} {m.unidad}" for m in orden.mediciones.all() if m.valor is not None]
    if medidas:
        descripcion += "\nMediciones: " + "; ".join(medidas)
    orden.mantenimiento = HistorialMantenimiento.objects.create(
        equipo=orden.equipo, tipo_mantenimiento=orden.tipo, descripcion=descripcion,
        fecha_mantenimiento=timezone.localdate(), tecnico_responsable=nombre_de(orden.tecnico))
    orden.estado, orden.fin = OrdenTrabajo.FINALIZADA, timezone.now()
    orden.save()
    _evento(orden, request, f'{texto_evento}. Registrada en el historial del equipo')
    if orden.proxima_accion == 'REVISION':
        fecha = fecha_revision or orden.proxima_fecha
        if fecha and fecha >= timezone.localdate():
            revision = _crear_derivada(orden, request, 'PREVENTIVO', f'Próxima revisión programada tras {orden.codigo}.', fecha)
            orden.proxima_orden = revision
            orden.proxima_fecha = fecha
            orden.save(update_fields=['proxima_orden', 'proxima_fecha'])
            _evento(orden, request, f'Próxima revisión confirmada para el {fecha:%d/%m/%Y}: {revision.codigo}')
    from core import correo_informe
    correo_informe.preparar(orden)


@transaction.atomic
def solicitar_subsanacion(orden, motivo, bloque, request):
    _bloquear(orden)
    _exigir_gestion(request)
    _exigir_estado(orden, OrdenTrabajo.PENDIENTE_APROBACION)
    motivo = (motivo or '').strip()
    if not motivo:
        raise ReglaError('El motivo es obligatorio.')
    from core import incidencias
    if incidencias.bloqueada_por_correctiva(orden):
        raise ReglaError(incidencias.MSG_BLOQUEADA)
    if bloque and bloque not in dict(OrdenTrabajo.BLOQUES):
        raise ReglaError('El bloque a subsanar no es válido.')
    orden.estado, orden.subsanacion_motivo, orden.subsanacion_bloque = OrdenTrabajo.EN_EJECUCION, motivo, bloque or ''
    orden.save()
    donde = f' (bloque: {_etiqueta_bloque(bloque)})' if bloque else ''
    _evento(orden, request, f'Subsanación solicitada{donde}: {motivo}')


@transaction.atomic
def cancelar(orden, motivo, request):
    _bloquear(orden)
    if not puede_cancelar(orden, request.user):
        raise ReglaError(motivo_no_cancelable(orden))
    motivo = (motivo or '').strip()
    if not motivo:
        raise ReglaError('El motivo de la cancelación es obligatorio.')
    pausa = orden.pausa_activa
    if pausa:
        pausa.hasta = timezone.now()
        pausa.save()
    previo = orden.get_estado_display()
    orden.estado_previo_cancelacion = orden.estado
    orden.estado = OrdenTrabajo.CANCELADA
    orden.cancelada_por, orden.cancelada_en, orden.motivo_cancelacion = request.user, timezone.now(), motivo
    orden.save()
    _evento(orden, request, f'Cancelada (estado previo: {previo}). Motivo: {motivo}')
    from core import incidencias
    incidencias.liberar_por_cancelacion(orden, request)

"""Vistas de órdenes de trabajo. Gerente/Administrador gestionan; el técnico ejecuta las que tiene asignadas."""
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles import finders
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from core import agenda, auditoria, checklists, evidencias, incidencias, informe_ot, ordenes, preventivos, sincronizacion
from core.forms import (AsignarOrdenForm, EjecucionForm, EmergenciaForm, LlegadaForm, MotivoForm, NotaAdministrativaForm,
                        OrdenTrabajoForm, ProximaAccionForm, SubsanacionForm, VerificacionForm)
from core.models import DecisionIncidenciaOT, EquipoHVAC, NotaAdministrativa, OrdenTrabajo, RegistroActividad
from core.ordenes import ReglaError
from core.permisos import ROLES_GESTION, TECNICO, es_tecnico, rol_de, rol_requerido
from core.utiles import entero_o_none

logger = logging.getLogger(__name__)

HISTORIAL_VISIBLE = 6  # eventos recientes visibles; los anteriores quedan plegados

PASOS = [OrdenTrabajo.PENDIENTE, OrdenTrabajo.ASIGNADA, OrdenTrabajo.EN_EJECUCION,
         OrdenTrabajo.PENDIENTE_APROBACION, OrdenTrabajo.FINALIZADA]


def _visibles(usuario):
    """Gerente y administrador ven todas; el técnico solo las que tiene asignadas."""
    qs = OrdenTrabajo.objects.select_related('equipo', 'tecnico', 'creado_por')
    return qs if rol_de(usuario) in ROLES_GESTION else qs.filter(tecnico=usuario)


def _hacer(request, orden, accion, *args, ok=None):
    """Ejecuta una transición y muestra el resultado; devuelve True si se hizo."""
    try:
        accion(orden, *args, request)
    except ReglaError as e:
        for m in e.mensajes:
            messages.error(request, m)
        return False
    if ok:
        messages.success(request, ok)
    return True


@login_required
def ordenes_view(request):
    base = _visibles(request.user)
    if es_tecnico(request.user):
        mias = base.order_by('-actualizada_en', '-id')
        return render(request, 'ordenes.html', {'grupos': agenda.agrupar_mis_ordenes(mias), 'seccion': 'ordenes'})
    estado, q = request.GET.get('estado', ''), request.GET.get('q', '').strip()
    cuentas = {f['estado']: f['n'] for f in base.order_by().values('estado').annotate(n=Count('id'))}
    lista = base
    if estado in dict(OrdenTrabajo.ESTADO_CHOICES):
        lista = lista.filter(estado=estado)
    if q:
        filtro = (Q(equipo__codigo_identificador__icontains=q) | Q(equipo__nombre__icontains=q)
                  | Q(descripcion__icontains=q) | Q(tecnico__first_name__icontains=q) | Q(tecnico__username__icontains=q))
        numero = entero_o_none(q[3:]) if q.upper().startswith('OT-') else entero_o_none(q)
        if numero is not None:
            filtro |= Q(pk=numero)
        lista = lista.filter(filtro)
    lista = lista.annotate(
        n_incidencias=Count('puntos', filter=Q(puntos__resultado='INCIDENCIA')),
        n_alta_sin_resolver=Count('puntos', filter=Q(puntos__resultado='INCIDENCIA', puntos__gravedad='ALTA',
                                                     puntos__decision__isnull=True)),
        n_correctivas_activas=Count('puntos', filter=Q(puntos__decision__tipo='CORRECTIVA')
                                    & ~Q(puntos__decision__orden_correctiva__estado=OrdenTrabajo.CANCELADA)),
    ).order_by('-creada_en', '-id')
    pagina = Paginator(lista, 25).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'ordenes.html', {
        'pagina': pagina, 'estado': estado, 'q': q, 'querystring': params.urlencode(),
        'pestanas': [('', 'Todas', sum(cuentas.values()))] + [(v, e, cuentas.get(v, 0)) for v, e in OrdenTrabajo.ESTADO_CHOICES],
        'seccion': 'ordenes'})


@rol_requerido(*ROLES_GESTION)
def orden_crear_view(request):
    inicial = {}
    # «Continuación de OT»: nace de una orden anterior; el vínculo y el antecedente los fija el servidor, no el formulario.
    original = None
    cont_id = entero_o_none(request.GET.get('continuacion', '') or request.POST.get('continuacion', ''))
    if cont_id is not None:
        original = OrdenTrabajo.objects.select_related('equipo').filter(pk=cont_id).first()
    if original is not None:
        inicial.update(equipo=original.equipo_id, tipo='CORRECTIVO', criticidad=original.criticidad,
                       requiere_refrigerante=original.requiere_refrigerante,
                       descripcion=f'Continuación de {original.codigo}: ')
    equipo_id = entero_o_none(request.GET.get('equipo', ''))
    if original is None and equipo_id is not None and EquipoHVAC.objects.filter(pk=equipo_id).exists():
        inicial['equipo'] = equipo_id
    form = OrdenTrabajoForm(request.POST or None, initial=inicial)
    if request.method == 'POST' and form.is_valid():
        nueva = form.save(commit=False)
        if original is not None:
            nueva.continuacion_de = original
            nueva.antecedente = ordenes.antecedente_de(original)
        orden = ordenes.crear(nueva, request)
        messages.success(request, f'{orden.codigo} creada ({orden.get_estado_display()}).')
        return redirect('orden_detalle', orden_id=orden.id)
    return render(request, 'orden_form.html', {'form': form, 'seccion': 'ordenes', 'continuacion': original})


@login_required
def orden_detalle_view(request, orden_id):
    orden = get_object_or_404(_visibles(request.user), pk=orden_id)
    usuario, rol = request.user, rol_de(request.user)
    gestion, es_tecnico = rol in ROLES_GESTION, orden.tecnico_id == usuario.id
    estado = orden.estado
    previo = orden.estado_previo_cancelacion if estado == OrdenTrabajo.CANCELADA else estado
    idx = PASOS.index(previo) if previo in PASOS else 0
    etiquetas = dict(OrdenTrabajo.ESTADO_CHOICES)
    pasos = [{'etiqueta': etiquetas[p], 'situacion': 'hecho' if i < idx or (i == idx and estado == OrdenTrabajo.FINALIZADA)
              else 'actual' if i == idx and estado != OrdenTrabajo.CANCELADA else 'pendiente'}
             for i, p in enumerate(PASOS)]
    en_ejecucion = es_tecnico and estado == OrdenTrabajo.EN_EJECUCION
    # Un técnico solo puede abrir las órdenes que tiene asignadas: las demás se muestran como texto, no como enlace.
    correctivas = list(orden.correctivas.all())
    decision_origen = DecisionIncidenciaOT.objects.filter(orden_correctiva=orden).select_related('punto__orden').first()
    relacionadas = [c.id for c in correctivas] + ([decision_origen.punto.orden_id] if decision_origen else [])
    ids_visibles = set(_visibles(usuario).filter(pk__in=relacionadas).values_list('pk', flat=True))
    for c in correctivas:
        c.visible = c.id in ids_visibles
    cancelable = ordenes.puede_cancelar(orden, usuario)
    puntos, mediciones = list(orden.puntos.all()), list(orden.mediciones.all())
    avance = ordenes.avance_por_bloque(orden)
    bloques = [{'codigo': c, 'etiqueta': checklists.ETIQUETAS_BLOQUE[c], 'puntos': [p for p in puntos if p.bloque == c],
                'hechos': avance[c]['hechos'], 'total': avance[c]['total'],
                'completo': avance[c]['hechos'] == avance[c]['total']}
               for c in checklists.BLOQUES_DE_PUNTOS if c in avance]
    sin_checklist = not orden.tiene_checklist
    ed_mediciones = en_ejecucion and ordenes.puede_editar(orden, 'MEDICIONES')
    elegidas = {m.codigo for m in mediciones}
    con_incidencias = estado in (OrdenTrabajo.PENDIENTE_APROBACION, OrdenTrabajo.FINALIZADA) or bool(
        estado == OrdenTrabajo.EN_EJECUCION and orden.subsanacion_motivo)
    alta = incidencias.incidencias_alta(orden) if con_incidencias else []
    for p in alta:
        p.deshacible = bool(p.decision_actual) and not incidencias.decision_activa(p.decision_actual)
    pendientes_alta = sum(1 for p in alta if p.decision_actual is None)
    ids_corr = [p.decision_actual.orden_correctiva_id for p in alta if p.decision_actual and p.decision_actual.orden_correctiva_id]
    corr_visibles = set(_visibles(usuario).filter(pk__in=ids_corr).values_list('pk', flat=True))
    for p in alta:
        p.correctiva_visible = bool(p.decision_actual) and p.decision_actual.orden_correctiva_id in corr_visibles
    descarga_activa = bool(orden.descargada_en) and estado in sincronizacion.ESTADOS_DESCARGABLES
    con_evidencias = orden.con_evidencias
    eventos = list(orden.eventos.all())
    firma = evidencias._firma(orden) if con_evidencias else None
    firma_tecnico = evidencias._firma_tecnico(orden) if con_evidencias else None
    ctx = {
        'bloques': bloques, 'mediciones': mediciones, 'avance_mediciones': avance.get(checklists.MEDICIONES_BLOQUE),
        'sin_checklist': sin_checklist, 'revisar': request.GET.get('revisar') == '1',
        'ed_checklist': en_ejecucion and ordenes.puede_editar(orden, 'CHECKLIST'), 'ed_mediciones': ed_mediciones,
        'ed_observaciones': en_ejecucion and ordenes.puede_editar(orden, 'OBSERVACIONES'),
        'ed_materiales': en_ejecucion and ordenes.puede_editar(orden, 'MATERIALES'),
        'catalogo_mediciones': [{'med': d, 'elegida': d.codigo in elegidas} for d in checklists.MEDICIONES.values()]
        if sin_checklist and ed_mediciones else [],
        'form_subsanacion': SubsanacionForm(),
        'incidencias_alta': alta, 'n_pendientes_alta': pendientes_alta,
        'puede_decidir': gestion and estado == OrdenTrabajo.PENDIENTE_APROBACION,
        'bloqueada': estado == OrdenTrabajo.PENDIENTE_APROBACION and incidencias.bloqueada_por_correctiva(orden),
        'correctivas': correctivas,
        'decision_origen': decision_origen, 'origen_visible': decision_origen is not None and decision_origen.punto.orden_id in ids_visibles,
        'informe_version': informe_ot.VERSIONES.get(estado, '').lower() or None,
        'con_evidencias': con_evidencias,
        'fotos': list(orden.fotos.all()) if con_evidencias else [],
        'avance_fotos': avance.get(checklists.FOTOS), 'avance_firma': avance.get(checklists.FIRMA),
        'huella_firma': evidencias.huella_resumen(orden) if con_evidencias else '',
        'firma': firma, 'firma_vigente': bool(firma) and evidencias.firma_vigente(orden),
        'firma_tecnico': firma_tecnico, 'firma_tecnico_vigente': bool(firma_tecnico) and evidencias.firma_tecnico_vigente(orden),
        'resumen_firma': evidencias.resumen_para_firma(orden) if con_evidencias else [],
        'filas_resumen': evidencias.filas_resumen(orden) if con_evidencias else [],
        'ed_fotos': con_evidencias and en_ejecucion and ordenes.puede_editar(orden, 'FOTOS'),
        'ed_firma': con_evidencias and en_ejecucion and ordenes.puede_editar(orden, 'FIRMA'),
        'ed_firma_tecnico': (con_evidencias and en_ejecucion and es_tecnico and ordenes.puede_editar(orden, 'FIRMA_TECNICO')
                             and bool(firma) and evidencias.firma_vigente(orden)),
        'orden': orden, 'pasos': pasos, 'seccion': 'ordenes',
        'puede_asignar': gestion and estado in (OrdenTrabajo.PENDIENTE, OrdenTrabajo.ASIGNADA),
        'descarga_activa': descarga_activa, 'puede_liberar': gestion and descarga_activa,
        'puede_iniciar': es_tecnico and estado == OrdenTrabajo.ASIGNADA,
        'form_llegada': LlegadaForm(),
        'form_verificacion': VerificacionForm(),
        'form_proxima': ProximaAccionForm(initial={'accion': orden.proxima_accion or None, 'fecha': orden.proxima_fecha,
                                                   'texto': orden.proxima_texto}),
        'proxima_editable': en_ejecucion and con_evidencias and not orden.subsanacion_motivo and not orden.proxima_orden_id
        and bool(firma),
        'proxima_texto': dict(OrdenTrabajo.PROXIMA_CHOICES).get(orden.proxima_accion, ''),
        'proxima_orden': orden.proxima_orden,
        'original': orden.continuacion_de,
        'original_visible': bool(orden.continuacion_de_id) and _visibles(usuario).filter(pk=orden.continuacion_de_id).exists(),
        'puede_continuar': gestion and estado in (OrdenTrabajo.FINALIZADA, OrdenTrabajo.CANCELADA),
        'puede_nota': gestion and estado in (OrdenTrabajo.FINALIZADA, OrdenTrabajo.CANCELADA),
        'notas_admin': list(orden.notas_admin.all()) if gestion else [],
        'envio_informe': getattr(orden, 'envio_informe', None) if gestion and estado == OrdenTrabajo.FINALIZADA else None,
        'destinatarios_informe': orden.destinatarios_informe.split() if gestion and estado == OrdenTrabajo.FINALIZADA else [],
        'form_nota': NotaAdministrativaForm(),
        'puede_descargar': es_tecnico and estado in sincronizacion.ESTADOS_DESCARGABLES,
        'en_ejecucion': en_ejecucion,
        'puede_aprobar': gestion and estado == OrdenTrabajo.PENDIENTE_APROBACION,
        'puede_cancelar': cancelable,
        'motivo_no_cancelable': '' if cancelable or not (gestion or es_tecnico) else ordenes.motivo_no_cancelable(orden),
        'problema_cert': ordenes.certificado_problema(orden.tecnico, orden.requiere_refrigerante)
        if estado == OrdenTrabajo.ASIGNADA else None,
        'problemas_envio': ordenes.validar_envio(orden) if en_ejecucion else [],
        'pausa_activa': orden.pausa_activa,
        'pausas': orden.pausas.all(), 'eventos': eventos[-HISTORIAL_VISIBLE:], 'eventos_antiguos': eventos[:-HISTORIAL_VISIBLE],
        'form_asignar': AsignarOrdenForm(initial={'tecnico': orden.tecnico_id}),
        'form_motivo': MotivoForm(),
        'form_ejecucion': EjecucionForm(initial={'observaciones': orden.observaciones, 'materiales': orden.materiales,
                                                 'sin_materiales': orden.sin_materiales}),
    }
    if descarga_activa:
        ctx['form_asignar'].fields['tecnico'].disabled = True
    if en_ejecucion:
        if not ctx['ed_observaciones']:
            ctx['form_ejecucion'].fields['observaciones'].disabled = True
        if not ctx['ed_materiales']:
            ctx['form_ejecucion'].fields['materiales'].disabled = True
            ctx['form_ejecucion'].fields['sin_materiales'].disabled = True
    return render(request, 'orden_detalle.html', ctx)


@rol_requerido(TECNICO)
def agenda_view(request):
    """Órdenes abiertas del técnico (Asignada y En ejecución) agrupadas por fecha programada."""
    abiertas = (OrdenTrabajo.objects.filter(tecnico=request.user, estado__in=[OrdenTrabajo.ASIGNADA, OrdenTrabajo.EN_EJECUCION])
                .select_related('equipo'))
    return render(request, 'agenda.html', {'grupos': agenda.agrupar_por_fecha(abiertas, timezone.localdate()),
                                           'seccion': 'agenda'})


@login_required
def orden_informe_pdf_view(request, orden_id):
    """Informe en PDF: provisional con la orden Pendiente de aprobación, definitivo con la orden Finalizada."""
    orden = get_object_or_404(_visibles(request.user), pk=orden_id)
    if orden.estado not in informe_ot.VERSIONES:
        raise Http404('El informe solo está disponible cuando la orden está pendiente de aprobación o finalizada.')
    try:
        pdf = informe_ot.generar_informe_ot(orden, request.user)
    except Exception:
        logger.exception('No se pudo generar el informe de %s', orden.codigo)
        messages.error(request, 'No se pudo generar el informe. Inténtalo de nuevo.')
        return redirect('orden_detalle', orden.id)
    version = informe_ot.VERSIONES[orden.estado].lower()
    auditoria.registrar(RegistroActividad.REPORTE_DESCARGADO, request, detalle=f'Informe {version} de {orden.codigo}')
    respuesta = HttpResponse(pdf, content_type='application/pdf')
    respuesta['Content-Disposition'] = f'attachment; filename="Informe_{orden.codigo}_{version}.pdf"'
    respuesta['Cache-Control'] = 'private, no-store'
    return respuesta


def _orden_de(request, orden_id):
    return get_object_or_404(_visibles(request.user), pk=orden_id)


def _volver(orden):
    return redirect('orden_detalle', orden_id=orden.id)


def _es_ajax(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


def _json_ok(orden):
    datos = {'ok': True, 'avance': ordenes.avance_por_bloque(orden), 'faltan': ordenes.validar_envio(orden)}
    if orden.con_evidencias:
        # La pantalla firma sobre la huella que tenía al cargar; si el técnico siguió editando sin recargar,
        # esa huella queda vieja y la firma se rechazaba. Se devuelve siempre la actual.
        datos.update(huella=evidencias.huella_resumen(orden), resumen_firma=evidencias.resumen_para_firma(orden),
                     firma_estado=evidencias.estado_firma(orden), firma_tecnico_estado=evidencias.estado_firma_tecnico(orden))
    return JsonResponse(datos)


def _json_error(mensajes):
    return JsonResponse({'ok': False, 'errores': list(mensajes)}, status=400)


def _json_error_firma(orden, error):
    """Error al firmar: devuelve además el resumen actual para que la pantalla pueda volver a firmar sin recargar."""
    datos = {'ok': False, 'errores': list(error.mensajes)}
    if orden.con_evidencias:
        orden.refresh_from_db()
        datos.update(huella=evidencias.huella_resumen(orden), resumen_firma=evidencias.resumen_para_firma(orden),
                     firma_estado=evidencias.estado_firma(orden), firma_tecnico_estado=evidencias.estado_firma_tecnico(orden))
    return JsonResponse(datos, status=400)


def _json_rechazo(error):
    return JsonResponse({'ok': False, 'errores': list(error.mensajes)}, status=getattr(error, 'estado_http', 400))


@login_required
@require_POST
def orden_punto_view(request, orden_id, codigo):
    orden = _orden_de(request, orden_id)
    try:
        ordenes.marcar_punto(orden, codigo, request.POST.get('resultado', ''), request.POST.get('gravedad', ''),
                             request.POST.get('nota', ''), request)
    except ReglaError as e:
        return _json_error(e.mensajes)
    return _json_ok(orden)


@login_required
@require_POST
def orden_medicion_view(request, orden_id, codigo):
    orden = _orden_de(request, orden_id)
    try:
        ordenes.registrar_medicion(orden, codigo, request.POST.get('valor', ''), request)
    except ReglaError as e:
        return _json_error(e.mensajes)
    return _json_ok(orden)


@login_required
@require_POST
def orden_mediciones_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    _hacer(request, orden, ordenes.elegir_mediciones, request.POST.getlist('codigos'), ok='Mediciones actualizadas.')
    return _volver(orden)


@login_required
@require_POST
def orden_incidencia_justificar_view(request, orden_id, punto_id):
    orden = _orden_de(request, orden_id)
    _hacer(request, orden, incidencias.justificar, punto_id, request.POST.get('justificacion', ''),
           ok='Incidencia justificada.')
    return _volver(orden)


@login_required
@require_POST
def orden_incidencia_deshacer_view(request, orden_id, punto_id):
    orden = _orden_de(request, orden_id)
    _hacer(request, orden, incidencias.deshacer, punto_id, ok='Decisión deshecha: la incidencia vuelve a estar sin resolver.')
    return _volver(orden)


@login_required
def orden_incidencia_correctiva_view(request, orden_id, punto_id):
    orden = _orden_de(request, orden_id)
    motivo, punto = incidencias.motivo_no_decidible(orden, punto_id, request.user)
    if motivo:
        messages.error(request, motivo)
        return _volver(orden)
    form = OrdenTrabajoForm(request.POST or None, initial={'equipo': orden.equipo_id, 'tipo': 'CORRECTIVO'})
    for campo in ('equipo', 'tipo'):
        form.fields[campo].disabled = True
    if request.method == 'POST' and form.is_valid():
        try:
            correctiva = incidencias.crear_correctiva(orden, punto.id, form.save(commit=False), request)
        except ReglaError as e:
            for m in e.mensajes:
                messages.error(request, m)
            return _volver(orden)
        messages.success(request, f'{correctiva.codigo} creada y enlazada a la incidencia.')
        return _volver(orden)
    return render(request, 'orden_form.html', {'form': form, 'seccion': 'ordenes', 'origen': {'orden': orden, 'punto': punto}})


def _archivo_privado(campo, tipo):
    """Sirve un archivo solo a quien ya pasó el filtro de visibilidad de la orden (nunca por URL pública)."""
    try:
        respuesta = FileResponse(campo.open('rb'), content_type=tipo)
    except (FileNotFoundError, ValueError, OSError):
        raise Http404('Archivo no disponible.')
    respuesta['Cache-Control'] = 'private, max-age=0, no-store'
    respuesta['X-Content-Type-Options'] = 'nosniff'
    return respuesta


@login_required
@require_POST
def orden_foto_subir_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    archivo = request.FILES.get('archivo')
    if archivo is None:
        return _json_error(['No se ha recibido ninguna fotografía.'])
    try:
        foto = evidencias.subir_foto(orden, archivo, request)
    except ReglaError as e:
        return _json_error(e.mensajes)
    respuesta = _json_ok(orden)
    datos = json.loads(respuesta.content)
    datos['foto'] = {'id': foto.id, 'url': reverse('orden_foto_ver', args=[orden.id, foto.id])}
    return JsonResponse(datos)


@login_required
def orden_foto_ver_view(request, orden_id, foto_id):
    orden = _orden_de(request, orden_id)
    foto = get_object_or_404(orden.fotos, pk=foto_id)
    return _archivo_privado(foto.imagen, 'image/jpeg')


@login_required
@require_POST
def orden_foto_borrar_view(request, orden_id, foto_id):
    orden = _orden_de(request, orden_id)
    try:
        evidencias.borrar_foto(orden, foto_id, request)
    except ReglaError as e:
        return _json_error(e.mensajes)
    return _json_ok(orden)


@login_required
@require_POST
def orden_firma_guardar_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    try:
        evidencias.guardar_firma(orden, request.POST.get('firmante', ''), request.POST.get('imagen', ''), request,
                                 huella=request.POST.get('huella', ''))
    except ReglaError as e:
        return _json_error_firma(orden, e)
    return _json_ok(orden)


@login_required
@require_POST
def orden_firma_tecnico_guardar_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    try:
        evidencias.guardar_firma_tecnico(orden, request.POST.get('imagen', ''), request,
                                         huella=request.POST.get('huella', ''))
    except ReglaError as e:
        return _json_error_firma(orden, e)
    return _json_ok(orden)


@login_required
def orden_firma_tecnico_ver_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    firma = evidencias._firma_tecnico(orden)
    if firma is None:
        raise Http404('Sin firma.')
    return _archivo_privado(firma.imagen, 'image/png')


@login_required
def orden_firma_ver_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    firma = evidencias._firma(orden)
    if firma is None:
        raise Http404('Sin firma.')
    return _archivo_privado(firma.imagen, 'image/png')


@login_required
@require_POST
def orden_asignar_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    form = AsignarOrdenForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Elige un técnico activo.')
    else:
        _hacer(request, orden, ordenes.asignar, form.cleaned_data['tecnico'], ok='Orden asignada.')
    return _volver(orden)


@rol_requerido(*ROLES_GESTION)
@require_POST
def orden_liberar_descarga_view(request, orden_id):
    orden = get_object_or_404(OrdenTrabajo, pk=orden_id)
    _hacer(request, orden, ordenes.liberar_descarga, ok='Descarga liberada. Ya puedes reasignar la orden.')
    return _volver(orden)


@login_required
@require_POST
def orden_iniciar_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    form = LlegadaForm(request.POST)
    llegada = (form.data.get('llegada', ''), form.data.get('llegada_texto', ''))
    verificacion = {'codigo': request.POST.get('equipo_codigo', ''), 'nota': request.POST.get('verificacion_nota', ''),
                    'continuar': bool(request.POST.get('continuar_discrepancia')), 'estricto': True}
    _hacer(request, orden, lambda o, r: ordenes.iniciar(o, r, llegada=llegada, verificacion=verificacion),
           ok='Intervención iniciada.')
    return _volver(orden)


@login_required
@require_POST
def orden_proxima_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    form = ProximaAccionForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Elige una de las tres opciones y revisa la fecha.')
    else:
        d = form.cleaned_data
        _hacer(request, orden, lambda o, r: ordenes.elegir_proxima_accion(o, d['accion'], d['fecha'], d['texto'], r),
               ok='Próxima acción guardada.')
    return _volver(orden)


@rol_requerido(TECNICO)
def orden_emergencia_view(request):
    form = EmergenciaForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        problema = ordenes.certificado_problema(request.user, d['requiere_refrigerante'])
        if problema:
            form.add_error('requiere_refrigerante', f'No puedes crearla. {problema}')
        else:
            orden = OrdenTrabajo(equipo=d['equipo'], tipo='CORRECTIVO', criticidad=d['criticidad'],
                                 descripcion=f"{d['motivo']}: {d['descripcion']}", requiere_refrigerante=d['requiere_refrigerante'],
                                 con_checklist=not d['sin_checklist'], tecnico=request.user)
            orden = ordenes.crear_emergencia(orden, request)
            messages.success(request, f'{orden.codigo} creada y asignada a ti. Ábrela para iniciarla.')
            return redirect('orden_detalle', orden_id=orden.id)
    return render(request, 'orden_emergencia.html', {'form': form, 'seccion': 'ordenes'})


@login_required
@require_POST
def orden_reenviar_informe_view(request, orden_id):
    from core import correo_informe
    orden = _orden_de(request, orden_id)
    _hacer(request, orden, lambda o, r: ordenes._exigir_gestion(r) or correo_informe.reenviar_manual(o, r.user),
           ok='Informe reenviado a los destinatarios guardados en la orden.')
    return _volver(orden)


@login_required
@require_POST
def orden_nota_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    form = NotaAdministrativaForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Escribe la nota (máximo 2000 caracteres).')
    else:
        _hacer(request, orden, lambda o, r: ordenes.añadir_nota(o, form.cleaned_data['texto'], r), ok='Nota añadida.')
    return _volver(orden)


@login_required
@require_POST
def orden_pausar_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    form = MotivoForm(request.POST)
    _hacer(request, orden, ordenes.pausar, form.cleaned_data['motivo'] if form.is_valid() else '',
           ok='Intervención en pausa.')
    return _volver(orden)


@login_required
@require_POST
def orden_reanudar_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    _hacer(request, orden, ordenes.reanudar, ok='Intervención reanudada.')
    return _volver(orden)


@login_required
@require_POST
def orden_guardar_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    ajax = _es_ajax(request)
    form = EjecucionForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        try:
            ordenes.guardar_ejecucion(orden, d['observaciones'], d['materiales'], d['sin_materiales'], request)
            if ajax:
                return _json_ok(orden)
            messages.success(request, 'Datos guardados.')
        except ReglaError as e:
            if ajax:
                return _json_error(e.mensajes)
            for m in e.mensajes:
                messages.error(request, m)
    elif ajax:
        return _json_error(['Los datos no son válidos.'])
    return _volver(orden)


@login_required
@require_POST
def orden_enviar_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    form = EjecucionForm(request.POST)
    if (form.is_valid() and orden.estado == OrdenTrabajo.EN_EJECUCION and orden.tecnico_id == request.user.id
            and (ordenes.puede_editar(orden, 'OBSERVACIONES') or ordenes.puede_editar(orden, 'MATERIALES'))):
        d = form.cleaned_data  # guarda lo escrito y a continuación valida
        ordenes.guardar_ejecucion(orden, d['observaciones'], d['materiales'], d['sin_materiales'], request)
    _hacer(request, orden, ordenes.enviar, ok='Orden enviada a aprobación.')
    return _volver(orden)


@login_required
@require_POST
def orden_aprobar_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    fecha = parse_date(request.POST.get('proxima_fecha', '') or '') if request.POST.get('proxima_fecha') else None
    _hacer(request, orden, lambda o, r: ordenes.aprobar(o, r, fecha_revision=fecha),
           ok='Orden aprobada y finalizada. Ya figura en el historial del equipo.')
    return _volver(orden)


@login_required
@require_POST
def orden_subsanacion_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    form = SubsanacionForm(request.POST)
    valido = form.is_valid()
    _hacer(request, orden, ordenes.solicitar_subsanacion, form.cleaned_data['motivo'] if valido else '',
           form.cleaned_data['bloque'] if valido else '',
           ok='Subsanación solicitada: la orden vuelve a En ejecución.')
    return _volver(orden)


@login_required
@require_POST
def orden_cancelar_view(request, orden_id):
    orden = _orden_de(request, orden_id)
    form = MotivoForm(request.POST)
    _hacer(request, orden, ordenes.cancelar, form.cleaned_data['motivo'] if form.is_valid() else '',
           ok='Orden cancelada.')
    return _volver(orden)


@login_required
@require_POST
def orden_descargar_view(request, orden_id):
    """El técnico prepara la orden para trabajarla sin conexión: queda marcada y recibe el paquete."""
    orden = OrdenTrabajo.objects.filter(pk=orden_id).first()
    try:
        if orden is None:
            raise sincronizacion.orden_no_disponible()  # misma respuesta que «no es tuya»: no revela si existe
        paquete = sincronizacion.descargar(orden, request)
    except ReglaError as e:
        return _json_rechazo(e)
    respuesta = JsonResponse({'ok': True, 'paquete': paquete})
    respuesta['Cache-Control'] = 'private, no-store'
    return respuesta


@login_required
@require_POST
def orden_sincronizar_view(request, orden_id):
    """Recibe el trabajo hecho sin conexión (paquete JSON + fotos). Todo o nada; reenviar el mismo paquete es seguro."""
    orden = OrdenTrabajo.objects.filter(pk=orden_id).first()
    try:
        if orden is None:
            raise sincronizacion.orden_no_disponible()
        paquete = sincronizacion.leer_paquete(request.POST.get('paquete', ''))
        resultado = sincronizacion.sincronizar(orden, paquete, request.FILES.getlist('fotos'), request)
    except ReglaError as e:
        return _json_rechazo(e)
    respuesta = JsonResponse(resultado)
    respuesta['Cache-Control'] = 'private, no-store'
    return respuesta


# ---------------------------------------------------------------- aplicación sin conexión (PWA)
@rol_requerido(TECNICO)
@ensure_csrf_cookie
def sin_conexion_view(request):
    """Pantalla que funciona sin señal: lista las órdenes descargadas en este teléfono."""
    return render(request, 'sin_conexion.html')


@require_GET
def service_worker_view(request):
    """El Service Worker se sirve desde la raíz para poder controlar toda la aplicación."""
    ruta = finders.find('sinconexion/sw.js')
    if not ruta:
        raise Http404('Service Worker no disponible')
    with open(ruta, encoding='utf-8') as f:
        respuesta = HttpResponse(f.read(), content_type='application/javascript')
    respuesta['Service-Worker-Allowed'] = '/'
    respuesta['Cache-Control'] = 'no-cache'
    return respuesta


@require_GET
def manifest_view(request):
    datos = {
        'name': 'PredictaHVAC', 'short_name': 'Predicta', 'lang': 'es',
        'start_url': '/ordenes/', 'scope': '/', 'display': 'standalone',
        'background_color': '#0b1e47', 'theme_color': '#0b1e47',
        'icons': [
            {'src': static('sinconexion/iconos/icono-192.png'), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': static('sinconexion/iconos/icono-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': static('sinconexion/iconos/icono-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png',
             'purpose': 'maskable'},
        ],
    }
    return HttpResponse(json.dumps(datos), content_type='application/manifest+json')


@rol_requerido(*ROLES_GESTION)
def preventivos_view(request):
    """Plan de mantenimiento preventivo: cuándo toca cada equipo y botón para generar las órdenes que tocan."""
    filas = preventivos.plan(timezone.localdate())
    return render(request, 'preventivos.html', {
        'filas': filas, 'n_tocan': sum(1 for f in filas if f['toca']), 'dias': preventivos.anticipacion_dias(),
        'n_sin_plan': EquipoHVAC.objects.filter(periodicidad_meses__isnull=True).count(), 'seccion': 'ordenes'})


@rol_requerido(*ROLES_GESTION)
@require_POST
def preventivos_generar_view(request):
    creadas = preventivos.generar(timezone.localdate(), usuario=request.user)
    if creadas:
        messages.success(request, f'Se crearon {len(creadas)} orden(es) preventiva(s) pendientes de asignar.')
    else:
        messages.info(request, 'No hay preventivos por generar: todos los equipos con plan están al día o ya tienen su orden.')
    return redirect('ordenes')

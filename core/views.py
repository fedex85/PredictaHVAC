import logging

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils.dateparse import parse_date
from django.db.models import Max
from django.http import Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from config.groq_service import consultar_groq
from core.forms import (EquipoHVACForm, EquipoHVACEditForm, HistorialMantenimientoForm,
                        CrearUsuarioForm, EditarUsuarioForm)
from core import asistente_ia, auditoria, calendario, qr_equipo
from core.models import (DispositivoTOTP, EquipoHVAC, HistorialMantenimiento, OrdenTrabajo, PerfilUsuario,
                         RegistroActividad)
from core.permisos import ADMIN, ROLES_GESTION, es_tecnico, rol_de, rol_requerido
from core.pdf_service import generar_pdf_mantenimiento

logger = logging.getLogger(__name__)

@login_required
def dashboard_view(request):
    """
    Consulta las métricas de equipos HVAC e historial de mantenimientos
    desde PostgreSQL para alimentarlos en el Dashboard.
    """
    if es_tecnico(request.user):
        return redirect('ordenes')
    total_equipos = EquipoHVAC.objects.count()
    equipos_operativos = EquipoHVAC.objects.filter(estado='OPERATIVO').count()
    equipos_mantenimiento = EquipoHVAC.objects.filter(estado='MANTENIMIENTO').count()
    equipos_fuera_servicio = EquipoHVAC.objects.filter(estado='FUERA_SERVICIO').count()
    
    servicios_recientes = HistorialMantenimiento.objects.select_related('equipo').order_by('-fecha_mantenimiento')[:5]

    contexto = {
        'total_equipos': total_equipos,
        'equipos_operativos': equipos_operativos,
        'equipos_mantenimiento': equipos_mantenimiento,
        'equipos_fuera_servicio': equipos_fuera_servicio,
        'alertas_activas': equipos_fuera_servicio,
        'servicios_totales': HistorialMantenimiento.objects.count(),
        'servicios_recientes': servicios_recientes,
    }
    
    return render(request, 'dashboard.html', contexto)

@login_required
def equipos_view(request):
    equipos = EquipoHVAC.objects.annotate(
        ultimo_mantenimiento=Max('mantenimientos__fecha_mantenimiento')
    )
    return render(request, 'equipos.html', {'equipos': equipos})

@login_required
def detalle_equipo(request, equipo_id):
    equipo = get_object_or_404(EquipoHVAC, id=equipo_id)
    mantenimientos = equipo.mantenimientos.all().order_by('-fecha_mantenimiento')
    if es_tecnico(request.user):
        # Misma regla que el historial y el PDF: el técnico solo ve los mantenimientos de sus propias órdenes.
        mantenimientos = mantenimientos.filter(orden__tecnico=request.user)
    mantenimientos = list(mantenimientos)
    for m in mantenimientos:
        m.puede_pdf = True  # lo que se lista ya es visible para quien lo ve (ver mantenimiento_visible)
    return render(request, 'detalle_equipo.html', {
        'equipo': equipo, 'mantenimientos': mantenimientos, 'seccion': 'equipos',
        'qr_svg': qr_equipo.svg_qr(qr_equipo.url_ficha(request, equipo)),
        'ordenes_activas': _ordenes_activas_del_equipo(request.user, equipo)})

ESTADOS_OT_ACTIVAS = (OrdenTrabajo.PENDIENTE, OrdenTrabajo.ASIGNADA, OrdenTrabajo.EN_EJECUCION,
                      OrdenTrabajo.PENDIENTE_APROBACION)

def _ordenes_activas_del_equipo(usuario, equipo):
    """OT abiertas del equipo que el usuario puede ver (un técnico, solo las suyas): acceso directo tras escanear el QR."""
    from core.views_ordenes import _visibles
    return list(_visibles(usuario).filter(equipo=equipo, estado__in=ESTADOS_OT_ACTIVAS).order_by('fecha_programada', 'id'))

@login_required
def etiqueta_equipo_view(request, equipo_id):
    """Etiqueta imprimible (6x6 cm) con el QR de la ficha y el nombre del equipo debajo."""
    equipo = get_object_or_404(EquipoHVAC, id=equipo_id)
    return render(request, 'etiqueta_equipo.html', {
        'equipo': equipo, 'qr_svg': qr_equipo.svg_qr(qr_equipo.url_ficha(request, equipo))})

@rol_requerido(*ROLES_GESTION)
def editar_equipo_view(request, equipo_id):
    """Permite corregir los datos de la ficha técnica de un equipo existente."""
    equipo = get_object_or_404(EquipoHVAC, id=equipo_id)
    if request.method == 'POST':
        form = EquipoHVACEditForm(request.POST, instance=equipo)
        if form.is_valid():
            form.save()
            auditoria.registrar(RegistroActividad.EQUIPO_EDITADO, request,
                                detalle=f"{equipo.codigo_identificador}: " + (', '.join(form.changed_data) or 'sin cambios'))
            return redirect('detalle_equipo', equipo_id=equipo.id)
    else:
        form = EquipoHVACEditForm(instance=equipo)
    return render(request, 'editar_equipo.html', {'form': form, 'equipo': equipo, 'seccion': 'equipos'})

@login_required
def historial_view(request):
    servicios = HistorialMantenimiento.objects.select_related('equipo').order_by('-fecha_mantenimiento')
    if es_tecnico(request.user):
        servicios = servicios.filter(orden__tecnico=request.user)
    return render(request, 'historial.html', {'servicios': servicios})

@login_required
def ia_assistant_view(request):
    return render(request, 'ia_assistant.html', {
        'seccion': 'ia_assistant', 'max_mensaje': asistente_ia.MAX_MENSAJE, 'max_turnos': asistente_ia.MAX_TURNOS})

@require_POST
def consultar_ia(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Debes iniciar sesión para usar el asistente.'}, status=401)
    try:
        mensaje = asistente_ia.validar_mensaje(request.POST.get('mensaje'))
        historial = asistente_ia.validar_historial(request.POST.get('historial'))
    except asistente_ia.ConsultaInvalida as e:
        return JsonResponse({'error': str(e)}, status=400)
    if asistente_ia.limite_superado(request.user):
        return JsonResponse({'error': f'Has alcanzado el límite de {asistente_ia.limite_por_hora()} consultas por hora. '
                                      'Inténtalo de nuevo más tarde.'}, status=429)

    auditoria.registrar(RegistroActividad.CONSULTA_IA, request)  # no se guarda el contenido de la consulta
    respuesta, error = consultar_groq(mensaje, historial=historial)
    if error:
        logger.error('Fallo del asistente IA: %s', error)  # el detalle técnico no se muestra al usuario
        return JsonResponse({'error': 'El asistente no está disponible en este momento. Inténtalo de nuevo en unos minutos.'}, status=502)
    return JsonResponse({'respuesta': respuesta})

@rol_requerido(*ROLES_GESTION)
def crear_equipo_view(request):
    """
    Gestiona la creación de nuevos equipos HVAC:
    - GET: renderiza el formulario 'crear_equipo.html' con el generador QR.
    - POST: valida los datos y registra la unidad en la base de datos.
    """
    if request.method == 'POST':
        form = EquipoHVACForm(request.POST)
        if form.is_valid():
            equipo = form.save()
            auditoria.registrar(RegistroActividad.EQUIPO_CREADO, request,
                                detalle=f"{equipo.codigo_identificador} · {equipo.nombre}")
            return redirect('equipos')
    else:
        form = EquipoHVACForm()

    return render(request, 'crear_equipo.html', {'form': form})

@rol_requerido(*ROLES_GESTION)
def calendario_view(request):
    """Calendario mensual de órdenes por fecha programada (las canceladas no se muestran)."""
    hoy = timezone.localdate()
    anio, mes = calendario.parsear_mes(request.GET.get('mes', ''), hoy)
    tecnicos = get_user_model().objects.filter(ordenes_asignadas__isnull=False).distinct().order_by('username')
    try:
        tecnico_id = int(request.GET.get('tecnico', ''))
    except ValueError:
        tecnico_id = None
    base = OrdenTrabajo.objects.select_related('equipo', 'tecnico').exclude(estado=OrdenTrabajo.CANCELADA)
    if tecnico_id:
        base = base.filter(tecnico_id=tecnico_id)
    del_mes = base.filter(fecha_programada__year=anio, fecha_programada__month=mes)
    sin_fecha = base.filter(fecha_programada__isnull=True,
                            estado__in=[OrdenTrabajo.PENDIENTE, OrdenTrabajo.ASIGNADA]).order_by('id')
    semanas = calendario.semanas_del_mes(anio, mes, list(del_mes), hoy)
    anterior, siguiente = calendario.mes_vecino(anio, mes, -1), calendario.mes_vecino(anio, mes, 1)
    return render(request, 'calendario.html', {
        'seccion': 'calendario', 'semanas': semanas, 'dias_lista': calendario.dias_con_ordenes(semanas),
        'sin_fecha': list(sin_fecha), 'titulo_mes': f'{calendario.MESES[mes - 1].capitalize()} {anio}',
        'dias_semana': calendario.DIAS, 'tecnicos': tecnicos, 'tecnico_id': tecnico_id,
        'mes_anterior': calendario.clave(*anterior) if anterior else None,
        'mes_siguiente': calendario.clave(*siguiente) if siguiente else None,
        'mes_actual': calendario.clave(hoy.year, hoy.month), 'mes_mostrado': calendario.clave(anio, mes),
        'total_mes': sum(len(d['ordenes']) for sem in semanas for d in sem if d['del_mes']),
    })

def mantenimiento_visible(usuario, mantenimiento):
    """Gestión ve todos los mantenimientos; el técnico solo los que salieron de una orden suya."""
    if not es_tecnico(usuario):
        return True
    return OrdenTrabajo.objects.filter(tecnico=usuario, mantenimiento=mantenimiento).exists()


@login_required
def descargar_reporte_pdf(request, mantenimiento_id):
    """
    Recupera un registro de mantenimiento por ID y retorna el archivo PDF generado.
    """
    mantenimiento = get_object_or_404(HistorialMantenimiento, id=mantenimiento_id)
    if not mantenimiento_visible(request.user, mantenimiento):
        raise Http404('Reporte no disponible.')
    pdf_buffer = generar_pdf_mantenimiento(mantenimiento)
    auditoria.registrar(RegistroActividad.REPORTE_DESCARGADO, request,
                        detalle=f"Mantenimiento #{mantenimiento.id} · {mantenimiento.equipo.codigo_identificador}")
    
    response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
    filename = f"reporte_servicio_{mantenimiento.equipo.codigo_identificador}_{mantenimiento.id}.pdf"
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    
    return response

@rol_requerido(*ROLES_GESTION)
def registrar_mantenimiento(request):
    """
    Vista para renderizar y procesar el formulario de registro de mantenimientos.
    Al guardar exitosamente, redirige a la descarga/visualización del PDF.
    """
    if request.method == 'POST':
        form = HistorialMantenimientoForm(request.POST)
        if form.is_valid():
            mantenimiento = form.save()
            auditoria.registrar(RegistroActividad.MANTENIMIENTO_REGISTRADO, request,
                                detalle=f"{mantenimiento.equipo.codigo_identificador} · {mantenimiento.get_tipo_mantenimiento_display()}")
            return redirect('descargar_reporte_pdf', mantenimiento_id=mantenimiento.id)
    else:
        form = HistorialMantenimientoForm()
    
    return render(request, 'core/registrar_mantenimiento.html', {'form': form})


# ---------------------------------------------------------------------------
# Gestión de usuarios (solo Administrador)
# ---------------------------------------------------------------------------
def _admins_activos_excluyendo(usuario):
    """Cuántos administradores activos hay aparte de este usuario."""
    User = get_user_model()
    return (User.objects.filter(is_active=True).exclude(pk=usuario.pk)
            .filter(Q(is_superuser=True) | Q(perfil__rol=PerfilUsuario.ADMIN)).count())


@rol_requerido(ADMIN)
def usuarios_view(request):
    User = get_user_model()
    usuarios = User.objects.select_related('perfil').order_by('first_name', 'username')
    return render(request, 'usuarios.html', {'usuarios': usuarios, 'seccion': 'usuarios'})


@rol_requerido(ADMIN)
def crear_usuario_view(request):
    if request.method == 'POST':
        form = CrearUsuarioForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            User = get_user_model()
            with transaction.atomic():
                usuario = User.objects.create_user(username=d['email'], email=d['email'],
                                                   password=d['password1'], first_name=d['nombre'])
                perfil = usuario.perfil
                perfil.rol = d['rol']
                perfil.cert_numero, perfil.cert_categoria, perfil.cert_caducidad = (
                    d['cert_numero'], d['cert_categoria'], d['cert_caducidad'])
                perfil.debe_cambiar_clave = True  # la contraseña inicial la conoce quien crea la cuenta
                perfil.save()
            auditoria.registrar(RegistroActividad.USUARIO_CREADO, request,
                                detalle=f"{usuario.username} · {perfil.get_rol_display()}")
            messages.success(request, f'Usuario {usuario.username} creado. Entrégale su contraseña por un canal seguro: '
                                      'tendrá que cambiarla en su primer acceso.')
            return redirect('usuarios')
    else:
        form = CrearUsuarioForm()
    return render(request, 'usuario_form.html', {'form': form, 'modo': 'crear', 'seccion': 'usuarios'})


@rol_requerido(ADMIN)
def editar_usuario_view(request, usuario_id):
    User = get_user_model()
    usuario = get_object_or_404(User.objects.select_related('perfil'), id=usuario_id)
    perfil = usuario.perfil
    rol_anterior = rol_de(usuario)
    bloqueado = usuario == request.user or usuario.is_superuser  # no se cambia su propio rol ni se desactiva
    inicial = {'nombre': usuario.get_full_name() or usuario.username, 'rol': rol_anterior,
               'cert_numero': perfil.cert_numero, 'cert_categoria': perfil.cert_categoria,
               'cert_caducidad': perfil.cert_caducidad, 'activo': usuario.is_active}
    form = EditarUsuarioForm(request.POST or None, initial=inicial)
    form.usuario_obj = usuario
    if bloqueado:
        form.fields['rol'].disabled = True
        form.fields['activo'].disabled = True
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        deja_de_ser_admin = rol_anterior == ADMIN and (d['rol'] != ADMIN or not d['activo'])
        if deja_de_ser_admin and not _admins_activos_excluyendo(usuario):
            form.add_error('rol', 'Debe quedar al menos un administrador activo.')
        else:
            cambios = []
            if d['rol'] != rol_anterior:
                cambios.append(f"rol {rol_anterior} -> {d['rol']}")
            if d['activo'] != usuario.is_active:
                cambios.append('cuenta activada' if d['activo'] else 'cuenta desactivada')
            if (d['cert_numero'], d['cert_categoria'], d['cert_caducidad']) != (
                    perfil.cert_numero, perfil.cert_categoria, perfil.cert_caducidad):
                cambios.append('certificado')
            if d['nombre'] != inicial['nombre']:
                cambios.append('nombre')
            with transaction.atomic():
                usuario.first_name, usuario.last_name = d['nombre'], ''
                usuario.is_active = d['activo']
                if d['password1']:
                    usuario.set_password(d['password1'])
                    cambios.append('contraseña restablecida')
                usuario.save()
                perfil.rol = d['rol']
                perfil.cert_numero, perfil.cert_categoria, perfil.cert_caducidad = (
                    d['cert_numero'], d['cert_categoria'], d['cert_caducidad'])
                if d['password1'] and usuario != request.user:
                    perfil.debe_cambiar_clave = True  # el administrador conoce la clave que fijó: debe cambiarla
                perfil.save()
            if d['password1'] and usuario == request.user:
                update_session_auth_hash(request, usuario)  # no cerrar la sesión de quien cambia su propia clave
            auditoria.registrar(RegistroActividad.USUARIO_EDITADO, request,
                                detalle=f"{usuario.username}: " + ('; '.join(cambios) or 'sin cambios'))
            messages.success(request, f'Cambios guardados para {usuario.get_full_name() or usuario.username}.')
            return redirect('usuarios')
    return render(request, 'usuario_form.html', {'form': form, 'modo': 'editar', 'usuario_obj': usuario,
                                                 'bloqueado': bloqueado, 'seccion': 'usuarios',
                                                 'mfa_activo': DispositivoTOTP.objects.filter(usuario=usuario, confirmado=True).exists()})


@rol_requerido(ADMIN)
def actividad_view(request):
    """Bitácora de seguridad (solo lectura) con filtros por usuario, acción y fechas."""
    User = get_user_model()
    registros = RegistroActividad.objects.select_related('usuario')
    uid, accion = request.GET.get('usuario', ''), request.GET.get('accion', '')
    desde, hasta = parse_date(request.GET.get('desde', '')), parse_date(request.GET.get('hasta', ''))
    if uid.isdigit():
        registros = registros.filter(usuario_id=int(uid))
    if accion in dict(RegistroActividad.ACCION_CHOICES):
        registros = registros.filter(accion=accion)
    if desde:
        registros = registros.filter(fecha__date__gte=desde)
    if hasta:
        registros = registros.filter(fecha__date__lte=hasta)
    pagina = Paginator(registros, 50).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'actividad.html', {
        'pagina': pagina, 'usuarios': User.objects.order_by('first_name', 'username'),
        'acciones': RegistroActividad.ACCION_CHOICES, 'f': {'usuario': uid, 'accion': accion,
                                                            'desde': request.GET.get('desde', ''),
                                                            'hasta': request.GET.get('hasta', '')},
        'querystring': params.urlencode(), 'seccion': 'actividad'})

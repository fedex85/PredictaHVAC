from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.db.models import Max
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from config.groq_service import consultar_groq
from core.forms import (EquipoHVACForm, EquipoHVACEditForm, HistorialMantenimientoForm,
                        InvitarUsuarioForm, EditarUsuarioForm)
from core.models import EquipoHVAC, HistorialMantenimiento, PerfilUsuario
from core.permisos import ADMIN, ROLES_GESTION, rol_de, rol_requerido
from core.pdf_service import generar_pdf_mantenimiento

@login_required
def dashboard_view(request):
    """
    Consulta las métricas de equipos HVAC e historial de mantenimientos
    desde PostgreSQL para alimentarlos en el Dashboard.
    """
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
    return render(request, 'detalle_equipo.html', {'equipo': equipo, 'mantenimientos': mantenimientos, 'seccion': 'equipos'})

@rol_requerido(*ROLES_GESTION)
def editar_equipo_view(request, equipo_id):
    """Permite corregir los datos de la ficha técnica de un equipo existente."""
    equipo = get_object_or_404(EquipoHVAC, id=equipo_id)
    if request.method == 'POST':
        form = EquipoHVACEditForm(request.POST, instance=equipo)
        if form.is_valid():
            form.save()
            return redirect('detalle_equipo', equipo_id=equipo.id)
    else:
        form = EquipoHVACEditForm(instance=equipo)
    return render(request, 'editar_equipo.html', {'form': form, 'equipo': equipo, 'seccion': 'equipos'})

@login_required
def historial_view(request):
    servicios = HistorialMantenimiento.objects.select_related('equipo').order_by('-fecha_mantenimiento')
    return render(request, 'historial.html', {'servicios': servicios})

@login_required
def ia_assistant_view(request):
    return render(request, 'ia_assistant.html')

@require_POST
def consultar_ia(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Debes iniciar sesión para usar el asistente.'}, status=401)
    mensaje = request.POST.get('mensaje', '').strip()
    if not mensaje:
        return JsonResponse({'error': 'El mensaje no puede estar vacío.'}, status=400)
        
    respuesta, error = consultar_groq(mensaje)
    if error:
        return JsonResponse({'error': error}, status=500)
        
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
            form.save()
            return redirect('equipos')
    else:
        form = EquipoHVACForm()

    return render(request, 'crear_equipo.html', {'form': form})

@login_required
def calendario_view(request):
    return render(request, 'calendario.html')

@login_required
def descargar_reporte_pdf(request, mantenimiento_id):
    """
    Recupera un registro de mantenimiento por ID y retorna el archivo PDF generado.
    """
    mantenimiento = get_object_or_404(HistorialMantenimiento, id=mantenimiento_id)
    pdf_buffer = generar_pdf_mantenimiento(mantenimiento)
    
    response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
    filename = f"reporte_servicio_{mantenimiento.equipo.codigo_identificador}_{mantenimiento.id}.pdf"
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    
    return response

@login_required
def registrar_mantenimiento(request):
    """
    Vista para renderizar y procesar el formulario de registro de mantenimientos.
    Al guardar exitosamente, redirige a la descarga/visualización del PDF.
    """
    if request.method == 'POST':
        form = HistorialMantenimientoForm(request.POST)
        if form.is_valid():
            mantenimiento = form.save()
            return redirect('descargar_reporte_pdf', mantenimiento_id=mantenimiento.id)
    else:
        form = HistorialMantenimientoForm()
    
    return render(request, 'core/registrar_mantenimiento.html', {'form': form})


# ---------------------------------------------------------------------------
# Gestión de usuarios (solo Administrador)
# ---------------------------------------------------------------------------
def _enviar_invitacion(request, usuario):
    """Envía el enlace para que el usuario fije su contraseña. Devuelve el enlace."""
    uid = urlsafe_base64_encode(force_bytes(usuario.pk))
    token = default_token_generator.make_token(usuario)
    enlace = request.build_absolute_uri(reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token}))
    send_mail(
        'Tu acceso a PredictaHVAC',
        f"Hola {usuario.get_full_name() or usuario.username},\n\n"
        f"Se ha creado tu cuenta en PredictaHVAC. Crea tu contraseña desde este enlace:\n{enlace}\n\n"
        "El enlace caduca en 7 días.",
        settings.DEFAULT_FROM_EMAIL,
        [usuario.email],
    )
    return enlace


def _aviso_invitacion(request, usuario):
    try:
        enlace = _enviar_invitacion(request, usuario)
    except Exception:
        messages.warning(request, f'Se creó el usuario {usuario.email}, pero no se pudo enviar el correo. '
                                  'Usa «Reenviar enlace de acceso» cuando el correo esté configurado.')
        return
    texto = f'Usuario creado. Hemos enviado a {usuario.email} un correo para que cree su contraseña.'
    if settings.DEBUG:
        texto += f' (Modo desarrollo: el enlace también aparece en la consola del servidor: {enlace})'
    messages.success(request, texto)


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
def invitar_usuario_view(request):
    if request.method == 'POST':
        form = InvitarUsuarioForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            User = get_user_model()
            with transaction.atomic():
                usuario = User.objects.create_user(username=d['email'], email=d['email'], password=None,
                                                   first_name=d['nombre'])
                perfil = usuario.perfil
                perfil.rol = d['rol']
                perfil.cert_numero, perfil.cert_categoria, perfil.cert_caducidad = (
                    d['cert_numero'], d['cert_categoria'], d['cert_caducidad'])
                perfil.save()
            _aviso_invitacion(request, usuario)
            return redirect('usuarios')
    else:
        form = InvitarUsuarioForm()
    return render(request, 'usuario_form.html', {'form': form, 'modo': 'invitar', 'seccion': 'usuarios'})


@rol_requerido(ADMIN)
def editar_usuario_view(request, usuario_id):
    User = get_user_model()
    usuario = get_object_or_404(User.objects.select_related('perfil'), id=usuario_id)
    perfil = usuario.perfil
    bloqueado = usuario == request.user or usuario.is_superuser  # no se cambia su propio rol ni se desactiva
    inicial = {'nombre': usuario.get_full_name() or usuario.username, 'rol': rol_de(usuario),
               'cert_numero': perfil.cert_numero, 'cert_categoria': perfil.cert_categoria,
               'cert_caducidad': perfil.cert_caducidad, 'activo': usuario.is_active}
    form = EditarUsuarioForm(request.POST or None, initial=inicial)
    if bloqueado:
        form.fields['rol'].disabled = True
        form.fields['activo'].disabled = True
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        deja_de_ser_admin = rol_de(usuario) == ADMIN and (d['rol'] != ADMIN or not d['activo'])
        if deja_de_ser_admin and not _admins_activos_excluyendo(usuario):
            form.add_error('rol', 'Debe quedar al menos un administrador activo.')
        else:
            with transaction.atomic():
                usuario.first_name, usuario.last_name = d['nombre'], ''
                usuario.is_active = d['activo']
                usuario.save()
                perfil.rol = d['rol']
                perfil.cert_numero, perfil.cert_categoria, perfil.cert_caducidad = (
                    d['cert_numero'], d['cert_categoria'], d['cert_caducidad'])
                perfil.save()
            messages.success(request, f'Cambios guardados para {usuario.get_full_name() or usuario.username}.')
            return redirect('usuarios')
    return render(request, 'usuario_form.html', {'form': form, 'modo': 'editar', 'usuario_obj': usuario,
                                                 'bloqueado': bloqueado, 'seccion': 'usuarios'})


@rol_requerido(ADMIN)
@require_POST
def reenviar_invitacion_view(request, usuario_id):
    usuario = get_object_or_404(get_user_model(), id=usuario_id)
    if not usuario.email:
        messages.error(request, 'Este usuario no tiene correo registrado.')
    else:
        _aviso_invitacion(request, usuario)
    return redirect('usuarios')

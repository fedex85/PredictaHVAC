"""Control de acceso reforzado: bloqueo por intentos, verificación en dos pasos (TOTP),
cambio obligatorio de contraseña y enlaces de restablecimiento generados por un administrador."""
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import PasswordChangeView, PasswordResetConfirmView
from django.core.exceptions import ValidationError
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.encoding import force_bytes
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_encode
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from core import auditoria, bloqueo, totp
from core.models import DispositivoTOTP, PerfilUsuario, RegistroActividad
from core.permisos import ADMIN, GERENTE, rol_de, rol_requerido

# Roles que deben usar verificación en dos pasos (la gestión aprueba órdenes y administra usuarios)
ROLES_MFA = (ADMIN, GERENTE)


# --- Inicio de sesión con bloqueo ------------------------------------------------------------------
class FormularioAcceso(AuthenticationForm):
    """Formulario de login: tras demasiados fallos de un usuario desde una IP se bloquea aunque se acierte."""
    bloqueado_minutos = 0

    def _mensaje_bloqueo(self, minutos):
        self.bloqueado_minutos = minutos
        return ValidationError(f'Demasiados intentos fallidos. Inténtalo de nuevo en unos {minutos} minutos.',
                               code='bloqueado')

    def clean(self):
        usuario = self.cleaned_data.get('username')
        if not usuario or not self.cleaned_data.get('password'):
            return super().clean()
        clave = bloqueo.clave_de(usuario, auditoria.ip_de(self.request))
        restantes = bloqueo.minutos_restantes(clave)
        if restantes:
            raise self._mensaje_bloqueo(restantes)
        try:
            datos = super().clean()
        except ValidationError:
            if bloqueo.registrar_fallo(clave):
                auditoria.registrar(RegistroActividad.BLOQUEO_ACCESO, self.request, nombre=str(usuario)[:150],
                                    detalle=f'Bloqueado {settings.ACCESO_BLOQUEO_MINUTOS} min')
                raise self._mensaje_bloqueo(settings.ACCESO_BLOQUEO_MINUTOS)
            raise
        bloqueo.limpiar(clave)
        return datos


# --- Middleware: segundo factor y cambio obligatorio de contraseña ----------------------------------
def _tiene_mfa_activo(usuario):
    return DispositivoTOTP.objects.filter(usuario=usuario, confirmado=True).exists()


def mfa_requerido(usuario):
    """MFA exigido por el rol, o porque la persona ya lo activó (aunque no sea obligatorio para su rol)."""
    if not settings.MFA_OBLIGATORIO:
        return False
    return rol_de(usuario) in ROLES_MFA or _tiene_mfa_activo(usuario)


def mfa_superado(request):
    return request.session.get('mfa_uid') == request.user.pk


class AccesoSeguroMiddleware:
    """Tras el login, obliga a cambiar la contraseña inicial y a pasar el segundo factor antes de usar la app."""

    def __init__(self, get_response):
        self.get_response = get_response

    def _exentas(self):
        nombres = ('logout', 'service_worker', 'manifest', 'mfa_configurar', 'mfa_verificar', 'cambiar_clave')
        return {reverse(n) for n in nombres}

    def __call__(self, request):
        respuesta = self._comprobar(request)
        return respuesta if respuesta is not None else self.get_response(request)

    def _comprobar(self, request):
        usuario = getattr(request, 'user', None)
        if usuario is None or not usuario.is_authenticated:
            return None
        ruta = request.path
        if ruta.startswith('/' + settings.STATIC_URL.lstrip('/')) or ruta.startswith('/cuenta/restablecer/') \
                or ruta in self._exentas():
            return None
        perfil = getattr(usuario, 'perfil', None)
        if perfil is not None and perfil.debe_cambiar_clave:
            return self._desviar(request, 'cambiar_clave')
        if mfa_requerido(usuario) and not mfa_superado(request):
            return self._desviar(request, 'mfa_verificar' if _tiene_mfa_activo(usuario) else 'mfa_configurar')
        return None

    def _desviar(self, request, nombre):
        navegacion = request.method in ('GET', 'HEAD') and 'application/json' not in request.headers.get('Accept', '')
        if not navegacion:
            return HttpResponseForbidden('Acción pendiente en tu cuenta: abre la aplicación para continuar.')
        return redirect(f"{reverse(nombre)}?next={quote(request.get_full_path())}")


def _destino(request, por_defecto='dashboard'):
    siguiente = request.POST.get('next') or request.GET.get('next') or ''
    if siguiente and url_has_allowed_host_and_scheme(siguiente, allowed_hosts={request.get_host()},
                                                     require_https=request.is_secure()):
        return siguiente
    return reverse(por_defecto)


# --- Verificación en dos pasos -----------------------------------------------------------------------
def _comprobar_codigo(request, dispositivo):
    """Valida el código enviado. Devuelve (ok, mensaje_de_error). Con bloqueo por intentos."""
    clave = bloqueo.clave_de(f'mfa:{request.user.pk}', auditoria.ip_de(request))
    restantes = bloqueo.minutos_restantes(clave)
    if restantes:
        return False, f'Demasiados intentos fallidos. Inténtalo de nuevo en unos {restantes} minutos.'
    paso = totp.verificar(dispositivo.secreto, request.POST.get('codigo', ''), ultimo_paso=dispositivo.ultimo_paso)
    # El UPDATE condicionado garantiza que un mismo código no se acepte dos veces, ni en peticiones simultáneas
    if paso is not None and DispositivoTOTP.objects.filter(pk=dispositivo.pk, ultimo_paso__lt=paso).update(ultimo_paso=paso):
        bloqueo.limpiar(clave)
        return True, ''
    auditoria.registrar(RegistroActividad.MFA_FALLIDO, request)
    if bloqueo.registrar_fallo(clave):
        auditoria.registrar(RegistroActividad.BLOQUEO_ACCESO, request, detalle='Verificación en dos pasos')
        return False, f'Demasiados intentos fallidos. Inténtalo de nuevo en unos {settings.ACCESO_BLOQUEO_MINUTOS} minutos.'
    return False, 'Código incorrecto. Comprueba que la hora de tu teléfono sea automática e inténtalo de nuevo.'


def _marcar_superado(request):
    request.session.cycle_key()
    request.session['mfa_uid'] = request.user.pk


@login_required
def mfa_verificar_view(request):
    dispositivo = DispositivoTOTP.objects.filter(usuario=request.user, confirmado=True).first()
    if dispositivo is None:
        return redirect(f"{reverse('mfa_configurar')}?next={quote(_destino(request))}")
    if mfa_superado(request):
        return redirect(_destino(request))
    error = ''
    if request.method == 'POST':
        ok, error = _comprobar_codigo(request, dispositivo)
        if ok:
            _marcar_superado(request)
            return redirect(_destino(request))
    return render(request, 'registration/mfa_verificar.html', {'error': error, 'next': _destino(request)})


@login_required
def mfa_configurar_view(request):
    if _tiene_mfa_activo(request.user):
        return redirect('mfa_verificar')
    dispositivo, _ = DispositivoTOTP.objects.get_or_create(usuario=request.user, defaults={'secreto': totp.nuevo_secreto()})
    error = ''
    if request.method == 'POST':
        ok, error = _comprobar_codigo(request, dispositivo)
        if ok:
            DispositivoTOTP.objects.filter(pk=dispositivo.pk).update(confirmado=True)
            auditoria.registrar(RegistroActividad.MFA_ACTIVADO, request)
            _marcar_superado(request)
            messages.success(request, 'Verificación en dos pasos activada.')
            return redirect(_destino(request))
    import segno  # solo se necesita aquí
    uri = totp.uri_aprovisionamiento(dispositivo.secreto, request.user.get_username())
    qr = mark_safe(segno.make(uri, error='m').svg_inline(scale=5, border=2, dark='#000000', light='#ffffff'))
    secreto = ' '.join(dispositivo.secreto[i:i + 4] for i in range(0, len(dispositivo.secreto), 4))
    return render(request, 'registration/mfa_configurar.html',
                  {'error': error, 'qr': qr, 'secreto': secreto, 'next': _destino(request)})


@rol_requerido(ADMIN)
@require_POST
def mfa_restablecer_view(request, usuario_id):
    """Quita el segundo factor de un usuario (móvil perdido): en su próximo acceso deberá configurarlo de nuevo."""
    usuario = get_object_or_404(get_user_model(), pk=usuario_id)
    DispositivoTOTP.objects.filter(usuario=usuario).delete()
    auditoria.registrar(RegistroActividad.MFA_RESTABLECIDO, request, detalle=usuario.get_username())
    messages.success(request, f'Verificación en dos pasos restablecida para {usuario.get_username()}.')
    return redirect('editar_usuario', usuario_id=usuario.pk)


# --- Contraseñas ---------------------------------------------------------------------------------------
class FormularioCambioClave(PasswordChangeForm):
    def clean(self):
        datos = super().clean()
        nueva = datos.get('new_password1')
        if nueva and datos.get('old_password') == nueva:
            self.add_error('new_password1', ValidationError('La nueva contraseña debe ser distinta de la actual.', code='igual'))
        return datos


class CambiarClaveView(PasswordChangeView):
    template_name = 'registration/cambiar_clave.html'
    form_class = FormularioCambioClave
    success_url = reverse_lazy('dashboard')

    def get_success_url(self):
        return _destino(self.request)

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto['next'] = _destino(self.request)
        return contexto

    def form_valid(self, form):
        respuesta = super().form_valid(form)  # guarda y mantiene la sesión abierta
        PerfilUsuario.objects.filter(usuario=self.request.user).update(debe_cambiar_clave=False)
        auditoria.registrar(RegistroActividad.CLAVE_CAMBIADA, self.request)
        messages.success(self.request, 'Contraseña actualizada.')
        return respuesta


class FormularioRestablecer(SetPasswordForm):
    def save(self, commit=True):
        usuario = super().save(commit)
        if commit:
            PerfilUsuario.objects.filter(usuario=usuario).update(debe_cambiar_clave=False)
        return usuario


class RestablecerClaveView(PasswordResetConfirmView):
    """Destino del enlace que genera el administrador: contraseña nueva elegida por la propia persona."""
    template_name = 'registration/restablecer_clave.html'
    form_class = FormularioRestablecer
    success_url = reverse_lazy('login')
    post_reset_login = False

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        auditoria.registrar(RegistroActividad.CLAVE_CAMBIADA, self.request, usuario=form.user,
                            detalle='Restablecida con enlace')
        return respuesta


@rol_requerido(ADMIN)
@require_POST
def enlace_clave_view(request, usuario_id):
    """Genera un enlace de un solo uso (caduca en unas horas y deja de valer al cambiar la contraseña)."""
    usuario = get_object_or_404(get_user_model(), pk=usuario_id)
    uid = urlsafe_base64_encode(force_bytes(usuario.pk))
    token = default_token_generator.make_token(usuario)
    enlace = request.build_absolute_uri(reverse('restablecer_clave', args=[uid, token]))
    auditoria.registrar(RegistroActividad.CLAVE_ENLACE, request, detalle=usuario.get_username())
    horas = settings.PASSWORD_RESET_TIMEOUT // 3600
    return render(request, 'registration/enlace_clave.html',
                  {'usuario_obj': usuario, 'enlace': enlace, 'horas': horas, 'seccion': 'usuarios'})

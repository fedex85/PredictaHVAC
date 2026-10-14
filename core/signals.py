from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_save
from django.dispatch import receiver

from core import auditoria
from core.models import PerfilUsuario, RegistroActividad


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def crear_perfil(sender, instance, created, **kwargs):
    """Todo usuario nuevo tiene perfil: los superusuarios son Administradores; el resto, Técnicos."""
    if created:
        PerfilUsuario.objects.get_or_create(
            usuario=instance,
            defaults={'rol': PerfilUsuario.ADMIN if instance.is_superuser else PerfilUsuario.TECNICO},
        )


@receiver(user_logged_in)
def registrar_entrada(sender, request, user, **kwargs):
    auditoria.registrar(RegistroActividad.LOGIN, request, usuario=user)


@receiver(user_logged_out)
def registrar_salida(sender, request, user, **kwargs):
    if user is not None:
        auditoria.registrar(RegistroActividad.LOGOUT, request, usuario=user)


@receiver(user_login_failed)
def registrar_intento_fallido(sender, credentials, request=None, **kwargs):
    nombre = str(credentials.get('username', ''))[:150]
    auditoria.registrar(RegistroActividad.LOGIN_FALLIDO, request, nombre=nombre, detalle=f'Usuario: {nombre}')

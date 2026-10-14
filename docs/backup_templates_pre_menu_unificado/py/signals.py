from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import PerfilUsuario


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def crear_perfil(sender, instance, created, **kwargs):
    """Todo usuario nuevo tiene perfil: los superusuarios son Administradores; el resto, Técnicos."""
    if created:
        PerfilUsuario.objects.get_or_create(
            usuario=instance,
            defaults={'rol': PerfilUsuario.ADMIN if instance.is_superuser else PerfilUsuario.TECNICO},
        )

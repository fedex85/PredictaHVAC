"""Quita la verificación en dos pasos de un usuario (recuperación si se pierde el teléfono y no queda otro administrador)."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.models import DispositivoTOTP


class Command(BaseCommand):
    help = 'Restablece la verificación en dos pasos de un usuario: la configurará de nuevo en su próximo acceso.'

    def add_arguments(self, parser):
        parser.add_argument('usuario', help='Nombre de usuario (normalmente su correo)')

    def handle(self, *args, **opciones):
        try:
            usuario = get_user_model().objects.get(username=opciones['usuario'])
        except get_user_model().DoesNotExist:
            raise CommandError(f"No existe el usuario «{opciones['usuario']}».")
        borrados, _ = DispositivoTOTP.objects.filter(usuario=usuario).delete()
        self.stdout.write(self.style.SUCCESS(
            f'Verificación restablecida para {usuario.get_username()}.' if borrados else
            f'{usuario.get_username()} no tenía verificación en dos pasos configurada.'))

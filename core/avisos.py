"""Avisos a gestión: se guardan para verlos en la aplicación y se envían también por correo."""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.db import transaction

from core.models import Aviso, PerfilUsuario
from core.permisos import ROLES_GESTION

logger = logging.getLogger(__name__)


def destinatarios_gestion():
    return list(get_user_model().objects.filter(is_active=True, perfil__rol__in=ROLES_GESTION))


def notificar_gestion(texto, orden=None):
    """Un aviso por cada gerente/administrador activo y, al confirmarse la transacción, un correo a quien tenga email."""
    texto = texto[:255]
    usuarios = destinatarios_gestion()
    for u in usuarios:
        Aviso.objects.create(usuario=u, texto=texto, orden=orden)
    correos = [u.email for u in usuarios if u.email]
    if correos:
        transaction.on_commit(lambda: _enviar_correos(correos, texto))
    return len(usuarios)


def _enviar_correos(correos, texto):
    for correo in correos:
        try:
            EmailMessage(subject=f'[PredictaHVAC] {texto}'[:200], body=f'{texto}\n\nRevisa los avisos en PredictaHVAC.',
                         from_email=settings.DEFAULT_FROM_EMAIL, to=[correo]).send(fail_silently=False)
        except Exception:  # un correo caído no debe romper el flujo; el aviso ya está dentro de la aplicación
            logger.warning('No se pudo enviar el aviso por correo', exc_info=True)


def sin_leer(usuario):
    return Aviso.objects.filter(usuario=usuario, leido=False).count() if usuario.is_authenticated else 0

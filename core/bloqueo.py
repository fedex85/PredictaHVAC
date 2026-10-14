"""Bloqueo temporal por intentos fallidos (usuario + IP) contra la adivinación de contraseñas y códigos.

Tras `ACCESO_MAX_FALLOS` fallos seguidos la combinación queda bloqueada `ACCESO_BLOQUEO_MINUTOS` minutos,
aunque se acierte la contraseña. Un acierto antes del límite borra el contador.
"""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import BloqueoAcceso


def clave_de(identificador, ip):
    return f"{str(identificador).strip().lower()[:150]}|{ip or '-'}"


def minutos_restantes(clave):
    """Minutos que faltan para que termine el bloqueo (0 si no está bloqueado)."""
    b = BloqueoAcceso.objects.filter(clave=clave).first()
    if b and b.bloqueado_hasta and b.bloqueado_hasta > timezone.now():
        return max(1, int((b.bloqueado_hasta - timezone.now()).total_seconds() // 60) + 1)
    return 0


def registrar_fallo(clave):
    """Suma un fallo. Devuelve True si con este fallo la combinación queda bloqueada."""
    ahora = timezone.now()
    ventana = timedelta(minutes=settings.ACCESO_BLOQUEO_MINUTOS)
    with transaction.atomic():
        b, _ = BloqueoAcceso.objects.select_for_update().get_or_create(
            clave=clave, defaults={'fallos': 0, 'ultimo_fallo': ahora})
        if b.fallos and ahora - b.ultimo_fallo > ventana:
            b.fallos, b.bloqueado_hasta = 0, None  # fallos antiguos: se empieza de cero
        b.fallos += 1
        b.ultimo_fallo = ahora
        recien_bloqueado = b.fallos >= settings.ACCESO_MAX_FALLOS
        if recien_bloqueado:
            b.bloqueado_hasta = ahora + ventana
            b.fallos = 0
        b.save()
    # Limpieza ocasional de contadores viejos para que la tabla no crezca
    BloqueoAcceso.objects.filter(ultimo_fallo__lt=ahora - timedelta(days=1)).delete()
    return recien_bloqueado


def limpiar(clave):
    BloqueoAcceso.objects.filter(clave=clave).delete()

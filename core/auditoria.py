"""Registro de actividad: quién entra, sale y qué hace en la aplicación."""
import logging

from core.models import RegistroActividad

logger = logging.getLogger(__name__)


def ip_de(request):
    if request is None:
        return None
    return request.META.get('REMOTE_ADDR') or None


def registrar(accion, request=None, usuario=None, detalle='', nombre=''):
    """Anota una acción. Un fallo al anotar nunca debe romper la petición, pero queda en el log del servidor."""
    try:
        u = usuario if usuario is not None else getattr(request, 'user', None)
        if u is not None and not getattr(u, 'is_authenticated', False):
            u = None
        RegistroActividad.objects.create(
            usuario=u,
            usuario_nombre=(nombre or (u.get_username() if u else ''))[:150],
            accion=accion,
            detalle=str(detalle)[:255],
            ip=ip_de(request),
        )
    except Exception:
        logger.exception('No se pudo registrar la actividad %s', accion)

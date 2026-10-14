"""Registro de actividad: quién entra, sale y qué hace en la aplicación."""
import ipaddress
import logging

from django.conf import settings

from core.models import RegistroActividad

logger = logging.getLogger(__name__)


def ip_de(request):
    """IP del cliente. Detrás de Nginx (Gunicorn en socket Unix) REMOTE_ADDR no sirve: se lee X-Real-IP,
    que Nginx fija con $remote_addr. Solo se confía en esa cabecera si PROXY_CONFIABLE está activo (producción);
    nunca se usa X-Forwarded-For, cuyo primer valor puede falsear el cliente."""
    if request is None:
        return None
    if getattr(settings, 'PROXY_CONFIABLE', False):
        valor = (request.META.get('HTTP_X_REAL_IP') or '').strip()
        try:
            return str(ipaddress.ip_address(valor))
        except ValueError:
            pass  # cabecera ausente o inválida: se usa la dirección de la conexión
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

"""Cabeceras de seguridad de las respuestas: Content-Security-Policy con nonce por petición y Permissions-Policy.

La política impide ejecutar cualquier script que no sea de este mismo origen o no lleve el nonce de la petición,
de modo que un fallo de escape que inyecte `<script>` en una plantilla no llegue a ejecutarse.
"""
import secrets

from django.conf import settings

PERMISOS = 'camera=(self), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()'


def politica(nonce):
    return '; '.join([
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
        # Las hojas de estilo propias son del mismo origen; los atributos style="" de las plantillas exigen 'unsafe-inline'
        # (un riesgo mucho menor que en scripts).
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",        # QR y firmas en data:, fotos reducidas en blob:
        "media-src 'self' blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "worker-src 'self'",
        "manifest-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


class CabecerasSeguridadMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = secrets.token_urlsafe(16)
        respuesta = self.get_response(request)
        modo = getattr(settings, 'CSP_MODO', 'enforce')
        if modo != 'off':
            nombre = 'Content-Security-Policy-Report-Only' if modo == 'report-only' else 'Content-Security-Policy'
            respuesta.headers.setdefault(nombre, politica(request.csp_nonce))
        respuesta.headers.setdefault('Permissions-Policy', PERMISOS)
        return respuesta


def csp_nonce(request):
    """Disponible en las plantillas como {{ csp_nonce }} para los <script> en línea."""
    return {'csp_nonce': getattr(request, 'csp_nonce', '')}

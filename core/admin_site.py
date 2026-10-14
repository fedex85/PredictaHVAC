"""Panel de administración de Django con rastro en la bitácora de seguridad.

Todo alta, cambio o baja hecho desde el panel (usuarios, perfiles y roles incluidos) se anota en RegistroActividad
con el usuario y la IP, además del LogEntry genérico de Django, que no guarda la IP y puede borrarse.
"""
from django.contrib import admin

from core import auditoria
from core.models import RegistroActividad


def _campos_cambiados(mensaje):
    """Nombres de campos de un mensaje de cambio de Django (lista de dicts o JSON); [] si no se pueden leer."""
    campos = []
    if isinstance(mensaje, (list, tuple)):
        for parte in mensaje:
            if isinstance(parte, dict):
                for clave in ('changed', 'added'):
                    campos += list(parte.get(clave, {}).get('fields', []) or [parte.get(clave, {}).get('name', '')])
    return [c for c in campos if c]


class AuditoriaAdminMixin:
    def _anotar(self, request, verbo, obj, extra=''):
        detalle = f"{verbo} {obj._meta.verbose_name}: {obj}"
        if extra:
            detalle += f" ({extra})"
        auditoria.registrar(RegistroActividad.ADMIN_DJANGO, request, detalle=detalle[:255])

    def log_addition(self, request, obj, message):
        resultado = super().log_addition(request, obj, message)
        self._anotar(request, 'Alta', obj)
        return resultado

    def log_change(self, request, obj, message):
        resultado = super().log_change(request, obj, message)
        campos = _campos_cambiados(message)
        self._anotar(request, 'Cambio', obj, ', '.join(campos) if campos else (message if isinstance(message, str) else ''))
        return resultado

    def log_deletions(self, request, queryset):
        for obj in queryset:
            self._anotar(request, 'Baja', obj)
        return super().log_deletions(request, queryset)

    def log_deletion(self, request, obj, object_repr):  # versiones que aún usan la llamada individual
        resultado = super().log_deletion(request, obj, object_repr)
        self._anotar(request, 'Baja', obj)
        return resultado


class SitioAdmin(admin.AdminSite):
    """Cada modelo que se registra recibe el registro en la bitácora sin tener que acordarse de añadirlo."""

    def register(self, model_or_iterable, admin_class=None, **options):
        base = admin_class or admin.ModelAdmin
        if not issubclass(base, AuditoriaAdminMixin):
            admin_class = type(f'Auditado{base.__name__}', (AuditoriaAdminMixin, base), {})
        return super().register(model_or_iterable, admin_class, **options)

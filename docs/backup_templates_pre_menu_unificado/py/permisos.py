"""Control de acceso por rol: Administrador, Gerente y Técnico."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from core.models import PerfilUsuario

ADMIN, GERENTE, TECNICO = PerfilUsuario.ADMIN, PerfilUsuario.GERENTE, PerfilUsuario.TECNICO
ROLES_GESTION = (ADMIN, GERENTE)


def rol_de(user):
    """Rol efectivo del usuario (los superusuarios siempre son Administradores)."""
    if not getattr(user, 'is_authenticated', False):
        return None
    if user.is_superuser:
        return ADMIN
    perfil = getattr(user, 'perfil', None)
    return perfil.rol if perfil else TECNICO


def rol_requerido(*roles):
    """Exige sesión iniciada y que el rol del usuario esté entre los indicados (si no, 403)."""
    def decorador(vista):
        @wraps(vista)
        @login_required
        def envoltura(request, *args, **kwargs):
            if rol_de(request.user) not in roles:
                raise PermissionDenied
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador

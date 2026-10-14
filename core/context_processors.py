from core.models import PerfilUsuario
from core.permisos import ADMIN, ROLES_GESTION, es_tecnico, rol_de


def rol(request):
    """Variables de rol disponibles en todas las plantillas (menú, botones)."""
    r = rol_de(request.user)
    return {
        'rol_usuario': r,
        'rol_etiqueta': dict(PerfilUsuario.ROL_CHOICES).get(r, ''),
        'es_admin': r == ADMIN,
        'puede_gestionar': r in ROLES_GESTION,
        'es_tecnico': es_tecnico(request.user),
    }

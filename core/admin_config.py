from django.contrib.admin.apps import AdminConfig


class SitioAdminConfig(AdminConfig):
    """Sustituye a 'django.contrib.admin' en INSTALLED_APPS para usar el sitio con rastro en la bitácora."""
    default_site = 'core.admin_site.SitioAdmin'

from django.contrib import admin
from .models import EquipoHVAC, HistorialMantenimiento, PerfilUsuario, RegistroActividad

@admin.register(EquipoHVAC)
class EquipoHVACAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'codigo_identificador', 'tipo', 'ubicacion', 'estado', 'fecha_instalacion')
    list_filter = ('tipo', 'estado')
    search_fields = ('nombre', 'codigo_identificador', 'ubicacion')

@admin.register(HistorialMantenimiento)
class HistorialMantenimientoAdmin(admin.ModelAdmin):
    list_display = ('equipo', 'tipo_mantenimiento', 'fecha_mantenimiento', 'tecnico_responsable')
    list_filter = ('tipo_mantenimiento', 'fecha_mantenimiento')
    search_fields = ('equipo__nombre', 'equipo__codigo_identificador', 'tecnico_responsable', 'descripcion')

@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'rol', 'cert_numero', 'cert_caducidad')
    list_filter = ('rol',)


@admin.register(RegistroActividad)
class RegistroActividadAdmin(admin.ModelAdmin):
    """Bitácora de solo lectura: ni siquiera un superusuario puede añadir, editar o borrar registros."""
    list_display = ('fecha', 'usuario_nombre', 'accion', 'detalle', 'ip')
    list_filter = ('accion',)
    search_fields = ('usuario_nombre', 'detalle', 'ip')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

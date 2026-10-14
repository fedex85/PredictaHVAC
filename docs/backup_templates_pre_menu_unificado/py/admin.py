from django.contrib import admin
from .models import EquipoHVAC, HistorialMantenimiento

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
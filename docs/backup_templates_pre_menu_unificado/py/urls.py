from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('equipos/', views.equipos_view, name='equipos'),
    path('equipos/crear/', views.crear_equipo_view, name='crear_equipo'),
    path('equipos/<int:equipo_id>/', views.detalle_equipo, name='detalle_equipo'),
    path('equipos/<int:equipo_id>/editar/', views.editar_equipo_view, name='editar_equipo'),
    path('usuarios/', views.usuarios_view, name='usuarios'),
    path('usuarios/crear/', views.crear_usuario_view, name='crear_usuario'),
    path('usuarios/<int:usuario_id>/editar/', views.editar_usuario_view, name='editar_usuario'),
    path('actividad/', views.actividad_view, name='actividad'),
    path('historial/', views.historial_view, name='historial'),
    path('ia-assistant/', views.ia_assistant_view, name='ia_assistant'),
    path('api/consultar-ia/', views.consultar_ia, name='api_consultar_ia'),
    path('calendario/', views.calendario_view, name='calendario'),
    path('mantenimiento/<int:mantenimiento_id>/pdf/', views.descargar_reporte_pdf, name='descargar_reporte_pdf'),
    path('mantenimiento/nuevo/', views.registrar_mantenimiento, name='registrar_mantenimiento'),
]
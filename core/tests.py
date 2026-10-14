from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from datetime import timedelta

from django.core import mail
from django.utils import timezone

from core.models import EquipoHVAC, HistorialMantenimiento, PerfilUsuario, RegistroActividad
from core.pdf_service import generar_pdf_mantenimiento


class BaseDatosMixin:
    def setUp(self):
        self.usuario = get_user_model().objects.create_user('tecnico', password='clave-segura-123')
        self.usuario.perfil.rol = PerfilUsuario.GERENTE  # puede crear y editar equipos
        self.usuario.perfil.save()
        self.client.force_login(self.usuario)
        self.equipo = EquipoHVAC.objects.create(
            nombre='Chiller 1', codigo_identificador='CH-001', ubicacion='Azotea'
        )
        self.mantenimiento = HistorialMantenimiento.objects.create(
            equipo=self.equipo,
            tipo_mantenimiento='PREVENTIVO',
            descripcion='Limpieza <b>de filtros</b>\nRevisión de presiones',
            fecha_mantenimiento=date(2026, 9, 1),
            tecnico_responsable='Ana',
        )


class VistasTests(BaseDatosMixin, TestCase):
    def test_dashboard_muestra_metricas_y_servicios(self):
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['total_equipos'], 1)
        self.assertEqual(r.context['servicios_totales'], 1)
        self.assertContains(r, 'Chiller 1')

    def test_equipos_incluye_ultimo_mantenimiento(self):
        r = self.client.get(reverse('equipos'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['equipos'][0].ultimo_mantenimiento, date(2026, 9, 1))

    def test_historial_lista_servicios(self):
        r = self.client.get(reverse('historial'))
        self.assertContains(r, 'Ana')

    def test_registrar_mantenimiento_redirige_al_pdf(self):
        r = self.client.post(reverse('registrar_mantenimiento'), {
            'equipo': self.equipo.id,
            'tipo_mantenimiento': 'CORRECTIVO',
            'descripcion': 'Cambio de compresor',
            'fecha_mantenimiento': '2026-09-10',
            'tecnico_responsable': 'Luis',
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(HistorialMantenimiento.objects.count(), 2)


class AutenticacionTests(BaseDatosMixin, TestCase):
    def test_vistas_exigen_login(self):
        self.client.logout()
        for nombre in ['dashboard', 'equipos', 'historial', 'calendario', 'ia_assistant', 'crear_equipo', 'registrar_mantenimiento']:
            r = self.client.get(reverse(nombre))
            self.assertEqual(r.status_code, 302, nombre)
            self.assertIn(reverse('login'), r['Location'])

    def test_api_ia_sin_login_devuelve_401(self):
        self.client.logout()
        r = self.client.post(reverse('api_consultar_ia'), {'mensaje': 'hola'})
        self.assertEqual(r.status_code, 401)

    def test_logout_cierra_sesion(self):
        self.client.post(reverse('logout'))
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 302)


class EquiposTests(BaseDatosMixin, TestCase):
    def test_formulario_crear_equipo_se_muestra(self):
        r = self.client.get(reverse('crear_equipo'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'codigo_identificador')

    def test_crear_equipo_guarda_todos_los_campos(self):
        r = self.client.post(reverse('crear_equipo'), {
            'nombre': 'Split Sala', 'codigo_identificador': 'SP-010', 'tipo': 'SPLIT',
            'ubicacion': 'Sala 2', 'modelo': 'Daikin FTXM', 'capacidad': '18000 BTU', 'refrigerante': 'R-32',
        })
        self.assertRedirects(r, reverse('equipos'))
        equipo = EquipoHVAC.objects.get(codigo_identificador='SP-010')
        self.assertEqual(equipo.refrigerante, 'R-32')

    def test_crear_equipo_codigo_duplicado_muestra_error(self):
        r = self.client.post(reverse('crear_equipo'), {
            'nombre': 'Otro', 'codigo_identificador': 'CH-001', 'tipo': 'CHILLER', 'ubicacion': 'X',
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(EquipoHVAC.objects.count(), 1)

    def test_detalle_equipo(self):
        r = self.client.get(reverse('detalle_equipo', args=[self.equipo.id]))
        self.assertContains(r, 'Chiller 1')
        self.assertContains(r, 'Ana')


class IATests(BaseDatosMixin, TestCase):
    def test_mensaje_vacio_devuelve_400(self):
        r = self.client.post(reverse('api_consultar_ia'), {'mensaje': '  '})
        self.assertEqual(r.status_code, 400)

    def test_solo_post(self):
        self.assertEqual(self.client.get(reverse('api_consultar_ia')).status_code, 405)

    @patch('core.views.consultar_groq', return_value=('Respuesta', None))
    def test_respuesta_correcta(self, _):
        r = self.client.post(reverse('api_consultar_ia'), {'mensaje': 'error E1 Daikin'})
        self.assertEqual(r.json(), {'respuesta': 'Respuesta'})

    @patch('core.views.consultar_groq', return_value=(None, 'fallo'))
    def test_error_devuelve_502(self, _):
        r = self.client.post(reverse('api_consultar_ia'), {'mensaje': 'hola'})
        self.assertEqual(r.status_code, 502)


class PdfTests(BaseDatosMixin, TestCase):
    def test_pdf_con_marcado_en_descripcion(self):
        buffer = generar_pdf_mantenimiento(self.mantenimiento)
        self.assertTrue(buffer.getvalue().startswith(b'%PDF'))

    def test_descarga_pdf(self):
        r = self.client.get(reverse('descargar_reporte_pdf', args=[self.mantenimiento.id]))
        self.assertEqual(r['Content-Type'], 'application/pdf')


def _usuario(nombre, rol, **extra):
    u = get_user_model().objects.create_user(nombre, email=f'{nombre}@ejemplo.com', password='clave-segura-123', **extra)
    u.perfil.rol = rol
    u.perfil.save()
    return u


class RolesTests(TestCase):
    def setUp(self):
        self.admin = _usuario('admin', PerfilUsuario.ADMIN)
        self.gerente = _usuario('gerente', PerfilUsuario.GERENTE)
        self.tecnico = _usuario('tecnico', PerfilUsuario.TECNICO)
        self.equipo = EquipoHVAC.objects.create(nombre='Chiller 1', codigo_identificador='CH-001', ubicacion='Azotea')

    def test_usuario_nuevo_es_tecnico_y_superusuario_es_admin(self):
        u = get_user_model().objects.create_user('nuevo', password='x')
        self.assertEqual(u.perfil.rol, PerfilUsuario.TECNICO)
        s = get_user_model().objects.create_superuser('root', 'r@e.com', 'x')
        self.assertEqual(s.perfil.rol, PerfilUsuario.ADMIN)

    def test_tecnico_no_crea_ni_edita_equipos(self):
        self.client.force_login(self.tecnico)
        self.assertEqual(self.client.get(reverse('crear_equipo')).status_code, 403)
        self.assertEqual(self.client.get(reverse('editar_equipo', args=[self.equipo.id])).status_code, 403)
        self.assertNotContains(self.client.get(reverse('equipos')), 'Nuevo Equipo')

    def test_gerente_crea_y_edita_equipos_pero_no_gestiona_usuarios(self):
        self.client.force_login(self.gerente)
        self.assertEqual(self.client.get(reverse('crear_equipo')).status_code, 200)
        self.assertEqual(self.client.get(reverse('editar_equipo', args=[self.equipo.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse('usuarios')).status_code, 403)
        self.assertNotContains(self.client.get(reverse('dashboard')), 'Usuarios')

    def test_solo_admin_ve_usuarios(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse('usuarios'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Crear usuario')

    def _datos_usuario(self, **extra):
        datos = {'nombre': 'Marta Ruiz', 'email': 'Marta@Ejemplo.com', 'rol': 'TECNICO',
                 'password1': 'Clave-muy-segura-9', 'password2': 'Clave-muy-segura-9',
                 'cert_numero': 'ES-GF-1', 'cert_categoria': 'I',
                 'cert_caducidad': (timezone.now().date() + timedelta(days=365)).isoformat()}
        datos.update(extra)
        return datos

    def test_crear_usuario_con_contrasena_puesta_por_el_admin(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse('crear_usuario'), self._datos_usuario())
        self.assertRedirects(r, reverse('usuarios'))
        u = get_user_model().objects.get(username='marta@ejemplo.com')
        self.assertEqual(u.perfil.rol, PerfilUsuario.TECNICO)
        self.assertEqual(u.perfil.cert_estado, 'vigente')
        self.assertEqual(len(mail.outbox), 0)
        self.client.logout()
        self.assertTrue(self.client.login(username='marta@ejemplo.com', password='Clave-muy-segura-9'))

    def test_crear_usuario_contrasenas_distintas_o_debiles(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse('crear_usuario'), self._datos_usuario(password2='otra'))
        self.assertContains(r, 'no coinciden')
        r = self.client.post(reverse('crear_usuario'), self._datos_usuario(password1='12345678', password2='12345678'))
        self.assertEqual(get_user_model().objects.filter(username='marta@ejemplo.com').count(), 0)
        self.assertEqual(r.status_code, 200)

    def test_admin_restablece_contrasena_de_otro_usuario(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('editar_usuario', args=[self.tecnico.id]), {
            'nombre': 'Tec', 'rol': 'TECNICO', 'activo': 'on',
            'password1': 'Otra-clave-segura-7', 'password2': 'Otra-clave-segura-7'})
        self.client.logout()
        self.assertTrue(self.client.login(username='tecnico', password='Otra-clave-segura-7'))

    def test_certificado_incompleto_da_error(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse('crear_usuario'), {'nombre': 'X', 'email': 'x@e.com', 'rol': 'TECNICO', 'cert_numero': 'ES-1', 'password1': 'Clave-muy-segura-9', 'password2': 'Clave-muy-segura-9'})
        self.assertContains(r, 'fecha de caducidad')

    def test_admin_no_guarda_certificado(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('crear_usuario'), {'nombre': 'Ana', 'email': 'ana@e.com', 'rol': 'ADMIN', 'cert_numero': 'ES-1',
                                                      'cert_caducidad': '2030-01-01', 'password1': 'Clave-muy-segura-9', 'password2': 'Clave-muy-segura-9'})
        self.assertEqual(get_user_model().objects.get(username='ana@e.com').perfil.cert_numero, '')

    def test_cert_caducado(self):
        self.tecnico.perfil.cert_numero = 'ES-1'
        self.tecnico.perfil.cert_caducidad = timezone.now().date() - timedelta(days=1)
        self.assertEqual(self.tecnico.perfil.cert_estado, 'caducado')

    def test_editar_rol_de_otro_usuario(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse('editar_usuario', args=[self.tecnico.id]),
                             {'nombre': 'Tec', 'rol': 'GERENTE', 'activo': 'on'})
        self.assertRedirects(r, reverse('usuarios'))
        self.tecnico.perfil.refresh_from_db()
        self.assertEqual(self.tecnico.perfil.rol, PerfilUsuario.GERENTE)

    def test_admin_no_puede_quitarse_su_propio_rol(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('editar_usuario', args=[self.admin.id]), {'nombre': 'Admin', 'rol': 'TECNICO'})
        self.admin.perfil.refresh_from_db()
        self.assertEqual(self.admin.perfil.rol, PerfilUsuario.ADMIN)


class ActividadTests(TestCase):
    def setUp(self):
        self.admin = _usuario('admin', PerfilUsuario.ADMIN)
        self.tecnico = _usuario('tecnico', PerfilUsuario.TECNICO)

    def _acciones(self, accion):
        return RegistroActividad.objects.filter(accion=accion)

    def test_registra_entrada_y_salida(self):
        self.assertTrue(self.client.login(username='tecnico', password='clave-segura-123'))
        self.assertEqual(self._acciones(RegistroActividad.LOGIN).filter(usuario=self.tecnico).count(), 1)
        self.client.logout()
        self.assertEqual(self._acciones(RegistroActividad.LOGOUT).filter(usuario=self.tecnico).count(), 1)

    def test_registra_intento_fallido_con_ip(self):
        self.client.post(reverse('login'), {'username': 'tecnico', 'password': 'mala'})
        r = self._acciones(RegistroActividad.LOGIN_FALLIDO).get()
        self.assertEqual(r.usuario_nombre, 'tecnico')
        self.assertEqual(r.ip, '127.0.0.1')

    def test_registra_acceso_denegado_y_acciones_sobre_equipos(self):
        self.client.force_login(self.tecnico)
        self.client.get(reverse('crear_equipo'))
        self.assertEqual(self._acciones(RegistroActividad.ACCESO_DENEGADO).get().detalle, reverse('crear_equipo'))
        self.client.force_login(self.admin)
        self.client.post(reverse('crear_equipo'), {'nombre': 'Split', 'codigo_identificador': 'SP-1', 'tipo': 'SPLIT',
                                                   'ubicacion': 'Sala', 'modelo': 'M', 'capacidad': '1', 'refrigerante': 'R-32'})
        self.assertIn('SP-1', self._acciones(RegistroActividad.EQUIPO_CREADO).get().detalle)

    def test_solo_admin_ve_la_actividad(self):
        self.client.force_login(self.tecnico)
        self.assertEqual(self.client.get(reverse('actividad')).status_code, 403)
        self.client.force_login(self.admin)
        r = self.client.get(reverse('actividad'), {'accion': RegistroActividad.LOGIN})
        self.assertContains(r, 'Registro de actividad')
        self.assertContains(r, 'Inicio de sesión')

    def test_crear_usuario_queda_registrado(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('crear_usuario'), {'nombre': 'N', 'email': 'n@e.com', 'rol': 'GERENTE',
                                                    'password1': 'Clave-muy-segura-9', 'password2': 'Clave-muy-segura-9'})
        self.assertIn('n@e.com', self._acciones(RegistroActividad.USUARIO_CREADO).get().detalle)

    def test_registro_se_conserva_al_borrar_el_usuario(self):
        self.client.login(username='tecnico', password='clave-segura-123')
        self.tecnico.delete()
        r = self._acciones(RegistroActividad.LOGIN).get()
        self.assertIsNone(r.usuario)
        self.assertEqual(r.usuario_nombre, 'tecnico')

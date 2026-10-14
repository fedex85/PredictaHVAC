"""M-05: ruta del panel de administración y rastro de sus cambios en la bitácora de seguridad."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import PerfilUsuario, RegistroActividad
from core.test_ordenes import _usuario


class RutaAdminTests(TestCase):
    def test_el_panel_ya_no_esta_en_admin(self):
        self.assertNotEqual(settings.ADMIN_URL, 'admin/')
        self.assertEqual(reverse('admin:index'), '/' + settings.ADMIN_URL)
        self.assertEqual(self.client.get('/admin/').status_code, 404)
        self.assertEqual(self.client.get('/admin/login/').status_code, 404)

    def test_formato_de_la_ruta(self):
        self.assertTrue(settings.ADMIN_URL.endswith('/'))
        self.assertFalse(settings.ADMIN_URL.startswith('/'))

    def test_el_panel_sigue_exigiendo_ser_staff(self):
        r = self.client.get(reverse('admin:index'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])
        self.client.force_login(_usuario('tec', PerfilUsuario.TECNICO))
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 302)


class BitacoraDelAdminTests(TestCase):
    def setUp(self):
        self.su = get_user_model().objects.create_superuser('root', 'root@ejemplo.com', 'clave-segura-123')
        self.tec = _usuario('tec', PerfilUsuario.TECNICO)
        self.client.force_login(self.su)

    def entradas(self):
        return list(RegistroActividad.objects.filter(accion=RegistroActividad.ADMIN_DJANGO))

    def test_cambiar_el_rol_de_un_perfil_deja_rastro_con_usuario_ip_y_campo(self):
        perfil = self.tec.perfil
        r = self.client.post(reverse('admin:core_perfilusuario_change', args=[perfil.pk]),
                             {'usuario': self.tec.pk, 'rol': PerfilUsuario.ADMIN, 'cert_numero': '', 'cert_categoria': '',
                              'cert_caducidad': ''}, REMOTE_ADDR='10.1.2.3')
        self.assertEqual(r.status_code, 302, r.content[:500])
        perfil.refresh_from_db()
        self.assertEqual(perfil.rol, PerfilUsuario.ADMIN)
        e = self.entradas()
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0].usuario, self.su)
        self.assertEqual(e[0].ip, '10.1.2.3')
        self.assertIn('Cambio', e[0].detalle)
        self.assertIn('rol', e[0].detalle.lower())

    def test_cambios_en_usuarios_tambien_se_registran(self):
        r = self.client.post(reverse('admin:auth_user_password_change', args=[self.tec.pk]),
                             {'usable_password': 'true', 'password1': 'otra-clave-muy-larga-1', 'password2': 'otra-clave-muy-larga-1'})
        self.assertEqual(r.status_code, 302, r.content[:500])
        self.assertTrue(any('tec' in x.detalle for x in self.entradas()))

    def test_altas_y_bajas_se_registran(self):
        r = self.client.post(reverse('admin:core_equipohvac_add'),
                             {'nombre': 'Split', 'codigo_identificador': 'SP-1', 'tipo': 'SPLIT', 'ubicacion': 'Sala',
                              'modelo': '', 'capacidad': '', 'refrigerante': '', 'estado': 'OPERATIVO',
                              'fecha_instalacion': '', 'periodicidad_meses': ''})
        self.assertEqual(r.status_code, 302, r.content[:500])
        self.assertTrue(any(x.detalle.startswith('Alta') for x in self.entradas()))
        from core.models import EquipoHVAC
        equipo = EquipoHVAC.objects.get(codigo_identificador='SP-1')
        r = self.client.post(reverse('admin:core_equipohvac_delete', args=[equipo.pk]), {'post': 'yes'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(any(x.detalle.startswith('Baja') for x in self.entradas()))

    def test_la_bitacora_sigue_siendo_de_solo_lectura_en_el_panel(self):
        self.assertEqual(self.client.get(reverse('admin:core_registroactividad_add')).status_code, 403)
        RegistroActividad.objects.create(accion=RegistroActividad.LOGIN, usuario_nombre='x')
        reg = RegistroActividad.objects.first()
        self.assertEqual(self.client.get(reverse('admin:core_registroactividad_change', args=[reg.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse('admin:core_registroactividad_delete', args=[reg.pk]), {'post': 'yes'}).status_code, 403)

    def test_los_modelos_del_panel_pasan_por_el_registro(self):
        from django.contrib import admin
        for modelo, adm in admin.site._registry.items():
            self.assertTrue(hasattr(adm, '_anotar'), modelo.__name__)

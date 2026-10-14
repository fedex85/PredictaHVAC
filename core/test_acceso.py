"""A-02 / M-03 / M-06: bloqueo por intentos, segundo factor (TOTP), IP real y gestión de contraseñas."""
import re
import time
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import auditoria, totp
from core.models import BloqueoAcceso, DispositivoTOTP, PerfilUsuario, RegistroActividad
from core.test_ordenes import _usuario

CLAVE = 'clave-segura-123'


class TotpTests(SimpleTestCase):
    # Secreto y valores de prueba del RFC 6238 (SHA-1, "12345678901234567890"), con 8 dígitos
    SECRETO_RFC = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'

    def test_vectores_rfc_6238(self):
        for segundos, esperado in ((59, '94287082'), (1111111109, '07081804'), (1234567890, '89005924'),
                                   (2000000000, '69279037')):
            self.assertEqual(totp.codigo_para(self.SECRETO_RFC, segundos // 30, digitos=8), esperado)

    def test_secreto_nuevo_es_base32_de_160_bits_y_distinto_cada_vez(self):
        a, b = totp.nuevo_secreto(), totp.nuevo_secreto()
        self.assertNotEqual(a, b)
        self.assertEqual(len(a), 32)
        self.assertRegex(a, r'^[A-Z2-7]+$')

    def test_acepta_codigo_actual_y_vecinos_pero_no_lejanos(self):
        ahora = 1_700_000_000
        paso = ahora // 30
        for desfase in (-1, 0, 1):
            codigo = totp.codigo_para(self.SECRETO_RFC, paso + desfase)
            self.assertEqual(totp.verificar(self.SECRETO_RFC, codigo, ahora=ahora), paso + desfase)
        for desfase in (-2, 2):
            self.assertIsNone(totp.verificar(self.SECRETO_RFC, totp.codigo_para(self.SECRETO_RFC, paso + desfase), ahora=ahora))

    def test_un_codigo_no_se_puede_reutilizar(self):
        ahora = 1_700_000_000
        paso = ahora // 30
        codigo = totp.codigo_para(self.SECRETO_RFC, paso)
        self.assertEqual(totp.verificar(self.SECRETO_RFC, codigo, ahora=ahora), paso)
        self.assertIsNone(totp.verificar(self.SECRETO_RFC, codigo, ultimo_paso=paso, ahora=ahora))
        # ni tampoco uno anterior al último aceptado
        self.assertIsNone(totp.verificar(self.SECRETO_RFC, totp.codigo_para(self.SECRETO_RFC, paso - 1),
                                         ultimo_paso=paso, ahora=ahora))

    def test_entradas_invalidas(self):
        ahora = 1_700_000_000
        valido = totp.codigo_para(self.SECRETO_RFC, ahora // 30)
        for malo in ('', None, '12345', '1234567', 'abcdef', '１２３４５６', valido[:-1] + 'x', "'; --"):
            self.assertIsNone(totp.verificar(self.SECRETO_RFC, malo, ahora=ahora), repr(malo))
        # los espacios entre dígitos (cómo las apps muestran el código) se toleran
        self.assertEqual(totp.verificar(self.SECRETO_RFC, valido[:3] + ' ' + valido[3:], ahora=ahora), ahora // 30)

    def test_uri_para_apps_de_autenticacion(self):
        uri = totp.uri_aprovisionamiento('ABC234', 'ana@ejemplo.com')
        self.assertTrue(uri.startswith('otpauth://totp/PredictaHVAC:ana%40ejemplo.com?secret=ABC234'))
        self.assertIn('issuer=PredictaHVAC', uri)


class IpRealTests(SimpleTestCase):
    def peticion(self, **meta):
        return RequestFactory().get('/', **meta)

    @override_settings(PROXY_CONFIABLE=True)
    def test_con_proxy_de_confianza_usa_x_real_ip(self):
        r = self.peticion(REMOTE_ADDR='', HTTP_X_REAL_IP='203.0.113.7')
        self.assertEqual(auditoria.ip_de(r), '203.0.113.7')

    @override_settings(PROXY_CONFIABLE=True)
    def test_nunca_se_fia_de_x_forwarded_for(self):
        r = self.peticion(REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='6.6.6.6, 203.0.113.7')
        self.assertEqual(auditoria.ip_de(r), '10.0.0.1')

    @override_settings(PROXY_CONFIABLE=True)
    def test_cabecera_invalida_se_ignora(self):
        for malo in ('no-es-una-ip', '1.2.3', '<script>', '999.1.1.1'):
            r = self.peticion(REMOTE_ADDR='10.0.0.1', HTTP_X_REAL_IP=malo)
            self.assertEqual(auditoria.ip_de(r), '10.0.0.1', malo)

    @override_settings(PROXY_CONFIABLE=False)
    def test_sin_proxy_de_confianza_se_ignora_la_cabecera(self):
        r = self.peticion(REMOTE_ADDR='10.0.0.1', HTTP_X_REAL_IP='6.6.6.6')
        self.assertEqual(auditoria.ip_de(r), '10.0.0.1')

    @override_settings(PROXY_CONFIABLE=True)
    def test_ipv6_y_sin_datos(self):
        self.assertEqual(auditoria.ip_de(self.peticion(REMOTE_ADDR='', HTTP_X_REAL_IP='2001:db8::1')), '2001:db8::1')
        self.assertIsNone(auditoria.ip_de(self.peticion(REMOTE_ADDR='')))
        self.assertIsNone(auditoria.ip_de(None))


@override_settings(ACCESO_MAX_FALLOS=5, ACCESO_BLOQUEO_MINUTOS=30)
class BloqueoLoginTests(TestCase):
    def setUp(self):
        self.tec = _usuario('tec', PerfilUsuario.TECNICO)
        self.url = reverse('login')

    def intento(self, password='mala', usuario='tec', ip='10.0.0.5'):
        return self.client.post(self.url, {'username': usuario, 'password': password}, REMOTE_ADDR=ip)

    def test_cinco_fallos_bloquean_aunque_luego_se_acierte(self):
        for _ in range(5):
            self.intento()
        r = self.intento(CLAVE)  # contraseña correcta, pero bloqueado
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Demasiados intentos fallidos')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_el_quinto_fallo_ya_avisa_del_bloqueo_y_queda_en_la_bitacora(self):
        for _ in range(4):
            self.assertNotContains(self.intento(), 'Demasiados intentos')
        self.assertContains(self.intento(), 'Demasiados intentos fallidos')
        self.assertTrue(RegistroActividad.objects.filter(accion=RegistroActividad.BLOQUEO_ACCESO, usuario_nombre='tec').exists())
        self.assertEqual(RegistroActividad.objects.filter(accion=RegistroActividad.LOGIN_FALLIDO).count(), 5)

    def test_cuatro_fallos_y_un_acierto_reinician_el_contador(self):
        for _ in range(4):
            self.intento()
        self.assertEqual(self.intento(CLAVE).status_code, 302)
        self.client.logout()
        for _ in range(4):
            self.intento()
        self.assertEqual(self.intento(CLAVE).status_code, 302)  # sigue sin estar bloqueado

    def test_el_bloqueo_es_por_usuario_e_ip(self):
        otro = _usuario('otro', PerfilUsuario.TECNICO)
        for _ in range(5):
            self.intento()
        self.assertEqual(self.intento(CLAVE, usuario='otro').status_code, 302)  # otro usuario, misma IP
        self.client.logout()
        self.assertEqual(self.intento(CLAVE, ip='10.0.0.99').status_code, 302)  # mismo usuario, otra IP

    def test_el_usuario_no_distingue_mayusculas_ni_espacios(self):
        for _ in range(5):
            self.intento(usuario=' TEC ')
        self.assertContains(self.intento(CLAVE, usuario='tec'), 'Demasiados intentos')

    def test_usuario_inexistente_tambien_se_bloquea_sin_delatar_que_no_existe(self):
        for _ in range(5):
            self.intento(usuario='fantasma')
        self.assertContains(self.intento(usuario='fantasma'), 'Demasiados intentos')

    def test_el_bloqueo_termina_a_los_30_minutos(self):
        for _ in range(5):
            self.intento()
        futuro = timezone.now() + timedelta(minutes=31)
        with mock.patch('django.utils.timezone.now', return_value=futuro):
            self.assertEqual(self.intento(CLAVE).status_code, 302)

    def test_los_fallos_viejos_no_se_acumulan(self):
        for _ in range(4):
            self.intento()
        futuro = timezone.now() + timedelta(minutes=45)
        with mock.patch('django.utils.timezone.now', return_value=futuro):
            self.intento()  # cuenta como el primero de una racha nueva
            self.assertNotContains(self.intento(), 'Demasiados intentos')

    @override_settings(PROXY_CONFIABLE=True)
    def test_con_proxy_el_bloqueo_usa_la_ip_real_del_cliente(self):
        for _ in range(5):
            self.client.post(self.url, {'username': 'tec', 'password': 'mala'}, REMOTE_ADDR='', HTTP_X_REAL_IP='203.0.113.7')
        self.assertTrue(BloqueoAcceso.objects.filter(clave='tec|203.0.113.7').exists())
        r = self.client.post(self.url, {'username': 'tec', 'password': CLAVE}, REMOTE_ADDR='', HTTP_X_REAL_IP='198.51.100.9')
        self.assertEqual(r.status_code, 302)  # otro cliente no queda afectado

    def test_login_correcto_normal_sigue_funcionando(self):
        r = self.intento(CLAVE)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(BloqueoAcceso.objects.count(), 0)


@override_settings(MFA_OBLIGATORIO=True, ACCESO_MAX_FALLOS=5, ACCESO_BLOQUEO_MINUTOS=30)
class SegundoFactorTests(TestCase):
    def setUp(self):
        self.admin = _usuario('admin', PerfilUsuario.ADMIN)
        self.gerente = _usuario('gerente', PerfilUsuario.GERENTE)
        self.tec = _usuario('tec', PerfilUsuario.TECNICO)

    def codigo(self, usuario, desfase=0):
        d = DispositivoTOTP.objects.get(usuario=usuario)
        return totp.codigo_para(d.secreto, int(time.time() // 30) + desfase)

    def activar(self, usuario):
        """Pasa por el flujo real de configuración y deja la sesión verificada."""
        self.client.force_login(usuario)
        self.client.get(reverse('mfa_configurar'))
        r = self.client.post(reverse('mfa_configurar'), {'codigo': self.codigo(usuario)})
        self.assertEqual(r.status_code, 302)

    def test_gestion_sin_segundo_factor_va_a_configurarlo(self):
        for usuario in (self.admin, self.gerente):
            self.client.force_login(usuario)
            r = self.client.get(reverse('dashboard'))
            self.assertEqual(r.status_code, 302)
            self.assertTrue(r['Location'].startswith(reverse('mfa_configurar')), r['Location'])

    def test_tecnico_no_necesita_segundo_factor(self):
        self.client.force_login(self.tec)
        self.assertEqual(self.client.get(reverse('ordenes')).status_code, 200)

    def test_superusuario_tambien_lo_necesita_y_el_admin_de_django_queda_protegido(self):
        su = get_user_model().objects.create_superuser('root', 'root@ejemplo.com', CLAVE)
        self.client.force_login(su)
        self.assertTrue(self.client.get(reverse('admin:index'))['Location'].startswith(reverse('mfa_configurar')))

    def test_configurar_muestra_qr_y_clave_y_no_activa_hasta_confirmar(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse('mfa_configurar'))
        self.assertContains(r, '<svg')
        d = DispositivoTOTP.objects.get(usuario=self.admin)
        self.assertFalse(d.confirmado)
        self.assertContains(r, ' '.join(d.secreto[i:i + 4] for i in range(0, 32, 4)))
        # recargar la página no cambia el secreto (el QR ya escaneado seguiría valiendo)
        self.client.get(reverse('mfa_configurar'))
        self.assertEqual(DispositivoTOTP.objects.get(usuario=self.admin).secreto, d.secreto)

    def test_activar_con_codigo_correcto_da_acceso_y_queda_en_la_bitacora(self):
        self.activar(self.admin)
        self.assertTrue(DispositivoTOTP.objects.get(usuario=self.admin).confirmado)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        self.assertTrue(RegistroActividad.objects.filter(accion=RegistroActividad.MFA_ACTIVADO, usuario=self.admin).exists())

    def test_activar_con_codigo_incorrecto_no_activa(self):
        self.client.force_login(self.admin)
        self.client.get(reverse('mfa_configurar'))
        r = self.client.post(reverse('mfa_configurar'), {'codigo': '000000'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Código incorrecto')
        self.assertFalse(DispositivoTOTP.objects.get(usuario=self.admin).confirmado)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 302)

    def test_nuevo_inicio_de_sesion_pide_el_codigo_y_lo_acepta(self):
        self.activar(self.admin)
        self.client.logout()
        self.client.post(reverse('login'), {'username': 'admin', 'password': CLAVE})
        r = self.client.get(reverse('dashboard'))
        self.assertTrue(r['Location'].startswith(reverse('mfa_verificar')))
        # el código del intervalo siguiente es válido (ventana ±1) y mayor que el último usado
        r = self.client.post(reverse('mfa_verificar'), {'codigo': self.codigo(self.admin, desfase=1)})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    def test_un_codigo_ya_usado_no_vale_otra_vez(self):
        self.activar(self.admin)  # consumió el código del intervalo actual
        self.client.logout()
        self.client.post(reverse('login'), {'username': 'admin', 'password': CLAVE})
        r = self.client.post(reverse('mfa_verificar'), {'codigo': self.codigo(self.admin)})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Código incorrecto')

    def test_cinco_codigos_malos_bloquean_tambien_el_codigo_bueno(self):
        self.activar(self.admin)
        self.client.logout()
        self.client.post(reverse('login'), {'username': 'admin', 'password': CLAVE})
        for _ in range(5):
            self.client.post(reverse('mfa_verificar'), {'codigo': '000000'})
        r = self.client.post(reverse('mfa_verificar'), {'codigo': self.codigo(self.admin, desfase=1)})
        self.assertContains(r, 'Demasiados intentos')
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 302)
        self.assertTrue(RegistroActividad.objects.filter(accion=RegistroActividad.MFA_FALLIDO).count() >= 5)

    def test_sesion_verificada_de_un_usuario_no_vale_para_otro(self):
        self.activar(self.admin)
        sesion = self.client.session
        sesion['_auth_user_id'] = str(self.gerente.pk)  # simula reutilizar la sesión con otra cuenta
        sesion.save()
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 302)

    def test_peticiones_que_no_son_de_navegacion_reciben_403_en_vez_de_redireccion(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('api_consultar_ia'), {}).status_code, 403)
        self.assertEqual(self.client.get(reverse('api_consultar_ia'), HTTP_ACCEPT='application/json').status_code, 403)

    def test_recursos_estaticos_y_service_worker_siguen_accesibles(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('service_worker')).status_code, 200)
        self.assertEqual(self.client.get(reverse('manifest')).status_code, 200)

    def test_cerrar_sesion_funciona_sin_haber_pasado_el_segundo_factor(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('logout')).status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_next_externo_no_se_sigue(self):
        self.activar(self.admin)
        self.client.logout()
        self.client.post(reverse('login'), {'username': 'admin', 'password': CLAVE})
        r = self.client.post(reverse('mfa_verificar'), {'codigo': self.codigo(self.admin, desfase=1), 'next': 'https://malo.example/'})
        self.assertEqual(r['Location'], reverse('dashboard'))

    def test_tecnico_que_activa_voluntariamente_el_segundo_factor_pasa_a_necesitarlo(self):
        self.activar(self.tec)
        self.client.logout()
        self.client.post(reverse('login'), {'username': 'tec', 'password': CLAVE})
        self.assertTrue(self.client.get(reverse('ordenes'))['Location'].startswith(reverse('mfa_verificar')))

    @override_settings(MFA_OBLIGATORIO=False)
    def test_se_puede_desactivar_para_desarrollo(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    # --- restablecer el segundo factor ---
    def test_el_admin_restablece_el_segundo_factor_de_otro_y_queda_registrado(self):
        self.activar(self.gerente)
        self.client.logout()
        _ = DispositivoTOTP.objects.get(usuario=self.gerente)
        self.activar(self.admin)
        r = self.client.post(reverse('mfa_restablecer', args=[self.gerente.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(DispositivoTOTP.objects.filter(usuario=self.gerente).exists())
        self.assertTrue(RegistroActividad.objects.filter(accion=RegistroActividad.MFA_RESTABLECIDO).exists())

    def test_solo_el_admin_puede_restablecer_y_solo_por_post(self):
        self.activar(self.gerente)
        self.assertEqual(self.client.post(reverse('mfa_restablecer', args=[self.admin.pk])).status_code, 403)
        self.client.logout()
        self.activar(self.admin)
        self.assertEqual(self.client.get(reverse('mfa_restablecer', args=[self.gerente.pk])).status_code, 405)

    def test_comando_reset_mfa(self):
        DispositivoTOTP.objects.create(usuario=self.admin, secreto=totp.nuevo_secreto(), confirmado=True)
        salida = StringIO()
        call_command('reset_mfa', 'admin', stdout=salida)
        self.assertFalse(DispositivoTOTP.objects.filter(usuario=self.admin).exists())
        self.assertIn('restablecida', salida.getvalue())
        with self.assertRaises(CommandError):
            call_command('reset_mfa', 'no-existe')


class ContrasenasTests(TestCase):
    def setUp(self):
        self.admin = _usuario('admin', PerfilUsuario.ADMIN)
        self.tec = _usuario('tec', PerfilUsuario.TECNICO)
        self.datos_usuario = {'nombre': 'Nuevo Técnico', 'email': 'nuevo@ejemplo.com', 'rol': PerfilUsuario.TECNICO,
                              'password1': 'otra-clave-larga-1', 'password2': 'otra-clave-larga-1'}

    def crear_usuario(self, **cambios):
        self.client.force_login(self.admin)
        return self.client.post(reverse('crear_usuario'), {**self.datos_usuario, **cambios})

    def test_longitud_minima_12(self):
        r = self.crear_usuario(password1='Corta-1234', password2='Corta-1234')  # 10 caracteres
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '12 caracteres')
        self.assertFalse(get_user_model().objects.filter(username='nuevo@ejemplo.com').exists())
        self.assertEqual(self.crear_usuario().status_code, 302)  # 18 caracteres: válida

    def test_usuario_nuevo_debe_cambiar_la_contrasena_en_su_primer_acceso(self):
        self.crear_usuario()
        nuevo = get_user_model().objects.get(username='nuevo@ejemplo.com')
        self.assertTrue(nuevo.perfil.debe_cambiar_clave)
        self.client.logout()
        self.client.post(reverse('login'), {'username': 'nuevo@ejemplo.com', 'password': 'otra-clave-larga-1'})
        r = self.client.get(reverse('ordenes'))
        self.assertTrue(r['Location'].startswith(reverse('cambiar_clave')), r['Location'])

    def test_cambio_obligatorio_completo(self):
        self.crear_usuario()
        self.client.logout()
        self.client.post(reverse('login'), {'username': 'nuevo@ejemplo.com', 'password': 'otra-clave-larga-1'})
        url = reverse('cambiar_clave')
        # no vale repetir la misma
        r = self.client.post(url, {'old_password': 'otra-clave-larga-1', 'new_password1': 'otra-clave-larga-1',
                                   'new_password2': 'otra-clave-larga-1'})
        self.assertContains(r, 'distinta de la actual')
        # no vale una corta
        r = self.client.post(url, {'old_password': 'otra-clave-larga-1', 'new_password1': 'corta', 'new_password2': 'corta'})
        self.assertEqual(r.status_code, 200)
        # sí vale una buena; la sesión sigue abierta y la app queda libre
        r = self.client.post(url, {'old_password': 'otra-clave-larga-1', 'new_password1': 'mi-clave-propia-2026',
                                   'new_password2': 'mi-clave-propia-2026'})
        self.assertEqual(r.status_code, 302)
        nuevo = get_user_model().objects.get(username='nuevo@ejemplo.com')
        self.assertFalse(nuevo.perfil.debe_cambiar_clave)
        self.assertEqual(self.client.get(reverse('ordenes')).status_code, 200)
        self.assertTrue(RegistroActividad.objects.filter(accion=RegistroActividad.CLAVE_CAMBIADA, usuario=nuevo).exists())

    def test_cambiar_clave_exige_la_actual(self):
        self.tec.perfil.debe_cambiar_clave = True
        self.tec.perfil.save()
        self.client.force_login(self.tec)
        r = self.client.post(reverse('cambiar_clave'), {'old_password': 'mal', 'new_password1': 'mi-clave-propia-2026',
                                                        'new_password2': 'mi-clave-propia-2026'})
        self.assertEqual(r.status_code, 200)
        self.tec.perfil.refresh_from_db()
        self.assertTrue(self.tec.perfil.debe_cambiar_clave)

    def test_cambio_obligatorio_no_bloquea_cerrar_sesion_ni_los_estaticos(self):
        self.tec.perfil.debe_cambiar_clave = True
        self.tec.perfil.save()
        self.client.force_login(self.tec)
        self.assertEqual(self.client.post(reverse('logout')).status_code, 302)

    def test_si_el_admin_fija_la_clave_de_otro_este_debe_cambiarla_pero_no_si_es_la_suya(self):
        self.client.force_login(self.admin)
        base = {'nombre': 'Técnico', 'rol': PerfilUsuario.TECNICO, 'activo': 'on', 'password1': 'clave-nueva-larga-9',
                'password2': 'clave-nueva-larga-9'}
        self.client.post(reverse('editar_usuario', args=[self.tec.pk]), base)
        self.tec.perfil.refresh_from_db()
        self.assertTrue(self.tec.perfil.debe_cambiar_clave)
        self.client.post(reverse('editar_usuario', args=[self.admin.pk]),
                         {'nombre': 'Admin', 'rol': PerfilUsuario.ADMIN, 'activo': 'on', 'password1': 'mi-propia-clave-77',
                          'password2': 'mi-propia-clave-77'})
        self.admin.perfil.refresh_from_db()
        self.assertFalse(self.admin.perfil.debe_cambiar_clave)

    # --- enlace de restablecimiento generado por el administrador ---
    def generar_enlace(self, usuario):
        self.client.force_login(self.admin)
        r = self.client.post(reverse('enlace_clave', args=[usuario.pk]))
        self.assertEqual(r.status_code, 200)
        enlace = re.search(r'value="(http[^"]+)"', r.content.decode()).group(1)
        self.client.logout()
        return re.sub(r'^https?://[^/]+', '', enlace)

    def test_enlace_permite_elegir_contrasena_nueva_y_solo_sirve_una_vez(self):
        self.tec.perfil.debe_cambiar_clave = True
        self.tec.perfil.save()
        ruta = self.generar_enlace(self.tec)
        r = self.client.get(ruta, follow=True)
        self.assertContains(r, 'Elige tu nueva contraseña')
        destino = r.redirect_chain[-1][0]
        r = self.client.post(destino, {'new_password1': 'elegida-por-mi-123', 'new_password2': 'elegida-por-mi-123'})
        self.assertRedirects(r, reverse('login'), fetch_redirect_response=False)
        self.tec.refresh_from_db()
        self.assertTrue(self.tec.check_password('elegida-por-mi-123'))
        self.assertFalse(self.tec.perfil.debe_cambiar_clave)
        self.assertTrue(RegistroActividad.objects.filter(accion=RegistroActividad.CLAVE_ENLACE).exists())
        # el mismo enlace ya no vale
        r = self.client.get(ruta, follow=True)
        self.assertContains(r, 'no es válido o ya caducó')

    def test_enlace_caduca(self):
        ruta = self.generar_enlace(self.tec)
        with mock.patch('django.contrib.auth.tokens.PasswordResetTokenGenerator._now',
                        return_value=__import__('datetime').datetime.now() + timedelta(hours=5)):
            r = self.client.get(ruta, follow=True)
        self.assertContains(r, 'no es válido o ya caducó')

    def test_el_tiempo_de_caducidad_es_de_horas_no_de_dias(self):
        from django.conf import settings
        self.assertLessEqual(settings.PASSWORD_RESET_TIMEOUT, 24 * 3600)

    def test_enlace_manipulado_no_sirve(self):
        ruta = self.generar_enlace(self.tec)
        mal = ruta[:-3] + 'xx/'
        self.assertContains(self.client.get(mal, follow=True), 'no es válido o ya caducó')

    def test_solo_el_admin_genera_enlaces_y_solo_por_post(self):
        self.client.force_login(self.tec)
        self.assertEqual(self.client.post(reverse('enlace_clave', args=[self.admin.pk])).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('enlace_clave', args=[self.tec.pk])).status_code, 405)

    def test_el_enlace_no_se_guarda_en_la_bitacora(self):
        ruta = self.generar_enlace(self.tec)
        token = ruta.strip('/').split('/')[-1]
        self.assertFalse(RegistroActividad.objects.filter(detalle__contains=token).exists())


class LoginPantallaTests(TestCase):
    def test_pantalla_de_login_sin_enlaces_muertos(self):
        html = self.client.get(reverse('login')).content.decode()
        self.assertNotIn('Recordarme', html)  # la casilla no hacía nada
        self.assertNotIn('href="#"', html)
        self.assertIn('administrador', html)  # explica cómo recuperar la contraseña


class SesionTests(SimpleTestCase):
    def test_la_sesion_caduca_por_inactividad(self):
        from django.conf import settings
        self.assertLessEqual(settings.SESSION_COOKIE_AGE, 12 * 3600)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)  # se renueva con cada petición
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)

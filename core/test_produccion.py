"""Ajustes de producción: la app no debe arrancar con una configuración insegura."""
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

RAIZ = Path(__file__).resolve().parent.parent


def _cargar_ajustes(**entorno):
    env = {k: v for k, v in os.environ.items() if not k.startswith('DJANGO_')}
    # Valores explícitos (aunque vacíos) para que un .env local no interfiera: load_dotenv no pisa variables ya definidas
    env.update(USE_SQLITE='1', DJANGO_SECRET_KEY='', DJANGO_HSTS_SECONDS='3600', DJANGO_DEBUG='', DJANGO_ALLOWED_HOSTS='')
    env.update(entorno)
    codigo = ("import config.settings as s; "
              "print(*(getattr(s, n, False) for n in ('SECURE_SSL_REDIRECT', 'SESSION_COOKIE_SECURE', "
              "'CSRF_COOKIE_SECURE', 'SECURE_HSTS_SECONDS')), s.DEBUG, len(s.ALLOWED_HOSTS))")
    return subprocess.run([sys.executable, '-c', codigo], cwd=RAIZ, env=env, capture_output=True, text=True)


class AjustesProduccionTests(SimpleTestCase):
    def test_sin_clave_segura_no_arranca(self):
        r = _cargar_ajustes(DJANGO_DEBUG='0')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('DJANGO_SECRET_KEY', r.stderr)

    def test_clave_corta_no_arranca(self):
        self.assertNotEqual(_cargar_ajustes(DJANGO_DEBUG='0', DJANGO_SECRET_KEY='corta').returncode, 0)

    def test_con_clave_segura_activa_https_y_cookies_seguras(self):
        r = _cargar_ajustes(DJANGO_DEBUG='0', DJANGO_SECRET_KEY='x' * 50, DJANGO_ALLOWED_HOSTS='app.ejemplo.com')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split()[:4], ['True', 'True', 'True', '3600'])

    def test_desarrollo_no_fuerza_https(self):
        r = _cargar_ajustes(DJANGO_DEBUG='1', DJANGO_SECRET_KEY='clave-solo-para-desarrollo')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split()[:3], ['False', 'False', 'False'])

    # --- A-01: el modo seguro es el predeterminado --------------------------------------------
    def test_sin_clave_no_arranca_ni_en_desarrollo(self):
        r = _cargar_ajustes(DJANGO_DEBUG='1')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('DJANGO_SECRET_KEY', r.stderr)

    def test_sin_variable_debug_se_arranca_en_modo_produccion(self):
        # DJANGO_DEBUG vacío equivale a no definirlo: debe ser modo seguro (DEBUG apagado, HTTPS activo)
        r = _cargar_ajustes(DJANGO_SECRET_KEY='x' * 50, DJANGO_ALLOWED_HOSTS='app.ejemplo.com')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split()[:3], ['True', 'True', 'True'])
        self.assertEqual(r.stdout.split()[4], 'False')  # DEBUG apagado
        self.assertEqual(r.stdout.split()[5], '1')

    def test_clave_de_desarrollo_conocida_no_se_acepta_en_produccion(self):
        r = _cargar_ajustes(DJANGO_SECRET_KEY='django-insecure-solo-desarrollo' + 'x' * 30, DJANGO_ALLOWED_HOSTS='app.ejemplo.com')
        self.assertNotEqual(r.returncode, 0)

    def test_produccion_exige_allowed_hosts(self):
        r = _cargar_ajustes(DJANGO_DEBUG='0', DJANGO_SECRET_KEY='x' * 50)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('DJANGO_ALLOWED_HOSTS', r.stderr)

    def test_allowed_hosts_vacio_por_defecto_en_desarrollo(self):
        r = _cargar_ajustes(DJANGO_DEBUG='1', DJANGO_SECRET_KEY='clave-solo-para-desarrollo')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split()[5], '0')

"""Ajustes de producción: la app no debe arrancar con una configuración insegura."""
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

RAIZ = Path(__file__).resolve().parent.parent


def _cargar_ajustes(**entorno):
    env = {k: v for k, v in os.environ.items() if not k.startswith('DJANGO_')}
    env.update(USE_SQLITE='1', DJANGO_SECRET_KEY='', DJANGO_HSTS_SECONDS='3600')  # evita que un .env local interfiera
    env.update(entorno)
    codigo = ("import config.settings as s; "
              "print(*(getattr(s, n, False) for n in ('SECURE_SSL_REDIRECT', 'SESSION_COOKIE_SECURE', "
              "'CSRF_COOKIE_SECURE', 'SECURE_HSTS_SECONDS')))")
    return subprocess.run([sys.executable, '-c', codigo], cwd=RAIZ, env=env, capture_output=True, text=True)


class AjustesProduccionTests(SimpleTestCase):
    def test_sin_clave_segura_no_arranca(self):
        r = _cargar_ajustes(DJANGO_DEBUG='0')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('DJANGO_SECRET_KEY', r.stderr)

    def test_clave_corta_no_arranca(self):
        self.assertNotEqual(_cargar_ajustes(DJANGO_DEBUG='0', DJANGO_SECRET_KEY='corta').returncode, 0)

    def test_con_clave_segura_activa_https_y_cookies_seguras(self):
        r = _cargar_ajustes(DJANGO_DEBUG='0', DJANGO_SECRET_KEY='x' * 50)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), ['True', 'True', 'True', '3600'])

    def test_desarrollo_no_fuerza_https(self):
        r = _cargar_ajustes(DJANGO_DEBUG='1')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split()[:3], ['False', 'False', 'False'])

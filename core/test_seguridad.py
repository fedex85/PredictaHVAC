"""M-04: Content-Security-Policy con nonce y Permissions-Policy."""
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import PerfilUsuario
from core.test_ordenes import OrdenesBase, _usuario


class CabecerasTests(TestCase):
    def test_la_csp_esta_en_todas_las_respuestas_incluida_la_de_login(self):
        r = self.client.get('/')
        csp = r['Content-Security-Policy']
        self.assertIn("object-src 'none'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("base-uri 'self'", csp)
        self.assertNotIn('unsafe-inline', csp.split('style-src')[0])   # los scripts nunca admiten 'unsafe-inline'
        self.assertNotIn("script-src 'self' 'unsafe", csp)
        self.assertIn('camera=(self)', r['Permissions-Policy'])
        self.assertEqual(r['Referrer-Policy'], 'same-origin')

    def test_el_nonce_cambia_en_cada_peticion_y_coincide_con_la_cabecera(self):
        n1 = re.search(r"'nonce-([^']+)'", self.client.get('/')['Content-Security-Policy']).group(1)
        n2 = re.search(r"'nonce-([^']+)'", self.client.get('/')['Content-Security-Policy']).group(1)
        self.assertNotEqual(n1, n2)
        self.assertGreaterEqual(len(n1), 16)

    @override_settings(CSP_MODO='report-only')
    def test_modo_solo_aviso(self):
        r = self.client.get('/')
        self.assertIn('Content-Security-Policy-Report-Only', r)
        self.assertNotIn('Content-Security-Policy', r.headers.keys() - {'Content-Security-Policy-Report-Only'})

    @override_settings(CSP_MODO='off')
    def test_modo_apagado(self):
        r = self.client.get('/')
        self.assertNotIn('Content-Security-Policy', r)
        self.assertIn('Permissions-Policy', r)

    def test_por_defecto_la_csp_se_aplica(self):
        self.assertEqual(settings.CSP_MODO, 'enforce')


class ScriptsEnLineaTests(OrdenesBase):
    """Todo <script> en línea renderizado lleva el nonce de su petición; ninguna plantilla usa manejadores on*=."""

    RUTAS = ('dashboard', 'equipos', 'ordenes', 'calendario', 'ia_assistant', 'historial', 'registrar_mantenimiento')

    def comprobar(self, r):
        nonce = re.search(r"'nonce-([^']+)'", r['Content-Security-Policy']).group(1)
        html = r.content.decode()
        for etiqueta in re.findall(r'<script\b[^>]*>', html):
            if 'src=' in etiqueta:
                continue
            self.assertIn(f'nonce="{nonce}"', etiqueta, etiqueta)
        self.assertIsNone(re.search(r'\son(?:click|change|submit|load|error|input)\s*=', html, re.I))
        self.assertNotIn('javascript:', html.lower())

    def test_pantallas_del_gerente(self):
        self.client.force_login(self.gerente)
        for nombre in self.RUTAS:
            self.comprobar(self.client.get(reverse(nombre)))
        self.comprobar(self.client.get(reverse('detalle_equipo', args=[self.equipo.id])))
        self.comprobar(self.client.get(reverse('etiqueta_equipo', args=[self.equipo.id])))

    def test_pantallas_del_tecnico(self):
        self.client.force_login(self.tec)
        for nombre in ('agenda', 'ordenes', 'sin_conexion', 'ia_assistant'):
            self.comprobar(self.client.get(reverse(nombre)))

    def test_login(self):
        self.comprobar(self.client.get('/'))

    def test_ninguna_plantilla_fuente_tiene_manejadores_en_linea(self):
        raiz = Path(settings.BASE_DIR) / 'templates'
        patron = re.compile(r'\son(?:click|change|submit|load|error|input|keyup|keydown)\s*=', re.I)
        culpables = [str(p.relative_to(raiz)) for p in raiz.rglob('*.html') if patron.search(p.read_text(encoding='utf-8'))]
        self.assertEqual(culpables, [])

    def test_ninguna_plantilla_tiene_script_en_linea_sin_nonce(self):
        raiz = Path(settings.BASE_DIR) / 'templates'
        culpables = []
        for p in raiz.rglob('*.html'):
            for etiqueta in re.findall(r'<script\b[^>]*>', p.read_text(encoding='utf-8')):
                if 'src=' not in etiqueta and 'application/json' not in etiqueta and 'csp_nonce' not in etiqueta:
                    culpables.append((str(p.relative_to(raiz)), etiqueta))
        self.assertEqual(culpables, [])

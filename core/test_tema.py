"""Logo y tema visual (paleta del logo): archivos, enlaces en las plantillas y manifiesto de la app instalada."""
import json
from pathlib import Path
from unittest import mock

from django.contrib.staticfiles import finders
from django.test import SimpleTestCase
from django.urls import reverse
from PIL import Image

from core import informe_pdf
from core.test_ordenes import OrdenesBase

RAIZ = Path(__file__).resolve().parent.parent


def _estatico(ruta):
    return Path(finders.find(ruta))


class ArchivosDelLogoTests(SimpleTestCase):
    def test_los_iconos_son_cuadrados_y_del_tamano_esperado(self):
        esperados = {'sinconexion/iconos/icono-192.png': 192, 'sinconexion/iconos/icono-512.png': 512,
                     'sinconexion/iconos/icono-maskable-512.png': 512, 'img/apple-touch-icon.png': 180,
                     'img/favicon-32.png': 32, 'img/icono-app.png': 128}
        for ruta, lado in esperados.items():
            with Image.open(_estatico(ruta)) as im:
                self.assertEqual(im.size, (lado, lado), ruta)

    def test_el_icono_de_la_app_no_tiene_transparencia_en_las_esquinas(self):
        # Android e iOS ponen su propia máscara: un PNG con esquinas transparentes se vería con bordes negros o blancos.
        for ruta in ('sinconexion/iconos/icono-192.png', 'sinconexion/iconos/icono-512.png', 'img/apple-touch-icon.png'):
            with Image.open(_estatico(ruta)).convert('RGBA') as im:
                self.assertEqual(im.getpixel((0, 0))[3], 255, ruta)
                self.assertEqual(im.getpixel((im.width - 1, im.height - 1))[3], 255, ruta)

    def test_la_hoja_del_tema_existe_y_define_el_menu_marino(self):
        css = _estatico('css/tema.css').read_text(encoding='utf-8')
        self.assertIn('.menu-marino', css)
        self.assertIn('#0b1e47', css.lower())

    def test_el_service_worker_precarga_el_tema_y_sube_la_version_de_cache(self):
        sw = _estatico('sinconexion/sw.js').read_text(encoding='utf-8')
        self.assertIn('/static/css/tema.css', sw)
        self.assertIn('icono-maskable-512.png', sw)
        self.assertNotIn("'sinconexion-v6'", sw)


class LogoEnElPdfTests(SimpleTestCase):
    def test_el_logo_se_dibuja_y_desplaza_el_texto(self):
        lienzo = mock.MagicMock()
        self.assertGreater(informe_pdf._dibujar_logo(lienzo, 40, 700, 44), 0)
        lienzo.drawImage.assert_called_once()

    def test_si_falta_el_logo_el_informe_no_falla(self):
        lienzo = mock.MagicMock()
        with mock.patch.object(informe_pdf, 'LOGO', RAIZ / 'no_existe.png'):
            self.assertEqual(informe_pdf._dibujar_logo(lienzo, 40, 700, 44), 0)
        lienzo.drawImage.assert_not_called()


class PantallasConElTemaTests(OrdenesBase):
    def test_el_acceso_usa_el_logo_y_ya_no_muestra_el_subtitulo(self):
        r = self.client.get(reverse('login'))
        self.assertContains(r, 'img/logo-login.png')
        self.assertContains(r, 'css/tema.css')
        self.assertNotContains(r, 'Gestor de Mantenimiento de Aire Acondicionado')

    def test_las_paginas_cargan_el_tema_y_el_menu_es_marino(self):
        for usuario in (self.gerente, self.tec):
            self.client.force_login(usuario)
            r = self.client.get(reverse('ordenes'))
            self.assertContains(r, 'css/tema.css')
            self.assertContains(r, 'menu-marino')
            self.assertContains(r, 'img/icono-app.png')
            self.assertContains(r, 'img/favicon-32.png')

    def test_el_manifiesto_usa_el_azul_marino_y_declara_el_icono_maskable(self):
        datos = json.loads(self.client.get('/manifest.webmanifest').content)
        self.assertEqual(datos['theme_color'].lower(), '#0b1e47')
        self.assertIn('maskable', {i.get('purpose') for i in datos['icons']})

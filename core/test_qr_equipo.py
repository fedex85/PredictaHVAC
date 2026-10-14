"""QR de la ficha del equipo: etiqueta imprimible con el nombre debajo y acceso rápido a las OT abiertas."""
from django.test import RequestFactory, override_settings
from django.urls import reverse

from core import qr_equipo
from core.models import OrdenTrabajo
from core.test_ordenes import OrdenesBase


class QrEquipoTests(OrdenesBase):
    @override_settings(ALLOWED_HOSTS=['app.ejemplo.com'])
    def test_el_qr_es_un_svg_con_la_url_absoluta_de_la_ficha(self):
        peticion = RequestFactory().get('/', HTTP_HOST='app.ejemplo.com')
        url = qr_equipo.url_ficha(peticion, self.equipo)
        self.assertEqual(url, f'http://app.ejemplo.com/equipos/{self.equipo.id}/')
        svg = qr_equipo.svg_qr(url)
        self.assertTrue(svg.startswith('<svg'))
        self.assertNotIn('<?xml', svg)

    def test_la_ficha_muestra_el_qr_y_el_boton_de_imprimir_etiqueta(self):
        self.client.force_login(self.tec)
        r = self.client.get(reverse('detalle_equipo', args=[self.equipo.id]))
        self.assertContains(r, '<svg')
        self.assertContains(r, reverse('etiqueta_equipo', args=[self.equipo.id]))
        self.assertContains(r, 'Imprimir etiqueta')

    def test_la_etiqueta_lleva_el_nombre_del_equipo_debajo_del_qr(self):
        self.client.force_login(self.tec)
        r = self.client.get(reverse('etiqueta_equipo', args=[self.equipo.id]))
        html = r.content.decode()
        self.assertEqual(r.status_code, 200)
        self.assertIn('<svg', html)
        self.assertLess(html.index('<svg'), html.index('class="nombre"'))
        self.assertContains(r, 'Chiller 1')
        self.assertContains(r, 'CH-001')
        self.assertContains(r, 'size: 60mm 60mm')

    def test_la_etiqueta_exige_sesion_y_equipo_existente(self):
        url = reverse('etiqueta_equipo', args=[self.equipo.id])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.gerente)
        self.assertEqual(self.client.get(reverse('etiqueta_equipo', args=[9999])).status_code, 404)

    def test_crear_equipo_ya_no_usa_el_generador_externo(self):
        self.client.force_login(self.gerente)
        r = self.client.get(reverse('crear_equipo'))
        self.assertNotContains(r, 'qrcode.min.js')
        self.assertContains(r, 'se genera al guardar')


class OrdenesAbiertasTrasEscanearTests(OrdenesBase):
    def ficha(self, usuario):
        self.client.force_login(usuario)
        return self.client.get(reverse('detalle_equipo', args=[self.equipo.id]))

    def test_el_tecnico_ve_solo_sus_ordenes_abiertas_del_equipo(self):
        propia = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        ajena = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec2)
        cerrada = self.orden(OrdenTrabajo.FINALIZADA, tecnico=self.tec)
        r = self.ficha(self.tec)
        self.assertContains(r, reverse('orden_detalle', args=[propia.id]))
        self.assertNotContains(r, reverse('orden_detalle', args=[ajena.id]))
        self.assertNotContains(r, reverse('orden_detalle', args=[cerrada.id]))

    def test_gestion_ve_todas_las_abiertas_pero_no_las_canceladas(self):
        a = self.orden(OrdenTrabajo.PENDIENTE)
        b = self.orden(OrdenTrabajo.EN_EJECUCION, tecnico=self.tec)
        c = self.orden(OrdenTrabajo.CANCELADA, tecnico=self.tec)
        r = self.ficha(self.gerente)
        self.assertContains(r, reverse('orden_detalle', args=[a.id]))
        self.assertContains(r, reverse('orden_detalle', args=[b.id]))
        self.assertNotContains(r, reverse('orden_detalle', args=[c.id]))

    def test_sin_ordenes_abiertas_no_aparece_el_bloque(self):
        self.assertNotContains(self.ficha(self.tec), 'Órdenes de trabajo abiertas')

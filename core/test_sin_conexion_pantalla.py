"""Parte 5b · tarea 1: Service Worker, manifiesto, pantalla sin conexión y botón de descarga."""
import json
import re

from django.contrib.staticfiles import finders
from django.urls import reverse

from core.models import OrdenTrabajo
from core.test_ordenes import OrdenesBase


def _precarga():
    ruta = finders.find('sinconexion/sw.js')
    with open(ruta, encoding='utf-8') as f:
        texto = f.read()
    bloque = re.search(r'ARCHIVOS_PRECARGA\s*=\s*\[(.*?)\]', texto, re.S).group(1)
    return re.findall(r"'([^']+)'", bloque)


class SinConexionPantallaTests(OrdenesBase):
    def test_service_worker_publico_con_cabeceras(self):
        r = self.client.get('/sw.js')
        self.assertEqual(r.status_code, 200)
        self.assertIn('javascript', r['Content-Type'])
        self.assertEqual(r['Service-Worker-Allowed'], '/')
        self.assertEqual(r['Cache-Control'], 'no-cache')

    def test_archivos_de_precarga_existen(self):
        rutas = _precarga()
        self.assertIn('/sin-conexion/', rutas)
        for ruta in rutas:
            if ruta.startswith('/static/'):
                self.assertIsNotNone(finders.find(ruta[len('/static/'):]), ruta)

    def test_manifiesto_valido(self):
        r = self.client.get('/manifest.webmanifest')
        self.assertEqual(r.status_code, 200)
        datos = json.loads(r.content)
        self.assertEqual(datos['start_url'], '/ordenes/')
        self.assertEqual(datos['display'], 'standalone')
        for icono in datos['icons']:
            self.assertIsNotNone(finders.find(icono['src'].replace('/static/', '', 1)), icono['src'])

    def test_pantalla_para_tecnico(self):
        self.client.force_login(self.tec)
        r = self.client.get('/sin-conexion/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f'data-usuario="{self.tec.id}"')
        self.assertContains(r, '<script type="module" src="/static/sinconexion/app.js">', html=False)

    def test_pantalla_prohibida_para_gestion(self):
        for u in (self.gerente, self.admin):
            self.client.force_login(u)
            self.assertEqual(self.client.get('/sin-conexion/').status_code, 403)

    def test_pantalla_sin_sesion_redirige_al_acceso(self):
        r = self.client.get('/sin-conexion/')
        self.assertRedirects(r, f"{reverse('login')}?next=/sin-conexion/", fetch_redirect_response=False)

    def test_bloque_de_descarga_solo_al_tecnico_asignado(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        url = reverse('orden_detalle', args=[o.id])
        self.client.force_login(self.tec)
        r = self.client.get(url)
        self.assertContains(r, 'id="bloque-sin-conexion"')
        self.assertContains(r, f'data-orden="{o.id}"')
        for u in (self.gerente, self.admin):
            self.client.force_login(u)
            self.assertNotContains(self.client.get(url), 'id="bloque-sin-conexion"')
        self.client.force_login(self.tec2)
        self.assertEqual(self.client.get(url).status_code, 404)  # otro técnico ni siquiera ve la orden

    def test_bloque_visible_en_ejecucion_y_oculto_pendiente_de_aprobacion(self):
        self.client.force_login(self.tec)
        o = self.orden(OrdenTrabajo.EN_EJECUCION, tecnico=self.tec)
        self.assertContains(self.client.get(reverse('orden_detalle', args=[o.id])), 'id="bloque-sin-conexion"')
        p = self.orden(OrdenTrabajo.PENDIENTE_APROBACION, tecnico=self.tec)
        self.assertNotContains(self.client.get(reverse('orden_detalle', args=[p.id])), 'id="bloque-sin-conexion"')

    def test_arranque_solo_en_paginas_del_tecnico(self):
        self.client.force_login(self.tec)
        self.assertContains(self.client.get(reverse('ordenes')), 'sinconexion/arranque.js')
        self.client.force_login(self.gerente)
        self.assertNotContains(self.client.get(reverse('ordenes')), 'sinconexion/arranque.js')

    def test_indicador_sin_conexion_enlaza_a_la_pantalla(self):
        self.client.force_login(self.tec)
        self.assertContains(self.client.get(reverse('ordenes')), 'href="/sin-conexion/" data-sin-conexion')

    def test_contador_de_pendientes_solo_para_el_tecnico(self):
        self.client.force_login(self.tec)
        self.assertContains(self.client.get(reverse('ordenes')), 'id="contador-pendientes"')
        self.client.force_login(self.gerente)
        self.assertNotContains(self.client.get(reverse('ordenes')), 'id="contador-pendientes"')

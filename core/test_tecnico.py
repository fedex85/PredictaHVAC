"""Pruebas de la fase 2, parte 4b: experiencia y permisos del técnico en móvil."""
from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone

from core.models import HistorialMantenimiento, OrdenTrabajo
from core.test_ordenes import OrdenesBase


class PermisosTecnicoTests(OrdenesBase):
    def setUp(self):
        super().setUp()
        def mant(nombre):
            return HistorialMantenimiento.objects.create(equipo=self.equipo, tipo_mantenimiento='PREVENTIVO',
                                                         descripcion='Revisión', fecha_mantenimiento=date(2026, 9, 1),
                                                         tecnico_responsable=nombre)
        self.m_tec, self.m_tec2, self.m_manual = mant('Responsable Uno'), mant('Responsable Dos'), mant('Responsable Tres')
        for m, tecnico in ((self.m_tec, self.tec), (self.m_tec2, self.tec2)):
            OrdenTrabajo.objects.create(equipo=self.equipo, descripcion='Orden', estado=OrdenTrabajo.FINALIZADA,
                                        tecnico=tecnico, mantenimiento=m, creado_por=self.gerente)

    def pdf(self, m):
        return reverse('descargar_reporte_pdf', args=[m.id])

    def test_dashboard_redirige_al_tecnico_a_ordenes(self):
        self.client.force_login(self.tec)
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('ordenes'), fetch_redirect_response=False)
        for usuario in (self.gerente, self.admin):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    def test_login_lleva_al_tecnico_a_ordenes(self):
        r = self.client.post(reverse('login'), {'username': 'tec', 'password': 'clave-segura-123'}, follow=True)
        self.assertEqual(r.redirect_chain[-1][0], reverse('ordenes'))

    def test_registrar_mantenimiento_solo_gestion(self):
        self.client.force_login(self.tec)
        self.assertEqual(self.client.get(reverse('registrar_mantenimiento')).status_code, 403)
        for usuario in (self.gerente, self.admin):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(reverse('registrar_mantenimiento')).status_code, 200)

    def test_pdf_propio_ajeno_y_sin_orden(self):
        self.client.force_login(self.tec)
        r = self.client.get(self.pdf(self.m_tec))
        self.assertEqual((r.status_code, r['Content-Type']), (200, 'application/pdf'))
        self.assertEqual(self.client.get(self.pdf(self.m_tec2)).status_code, 404)
        self.assertEqual(self.client.get(self.pdf(self.m_manual)).status_code, 404)
        self.client.force_login(self.gerente)
        for m in (self.m_tec, self.m_tec2, self.m_manual):
            self.assertEqual(self.client.get(self.pdf(m)).status_code, 200)

    def test_pdf_deja_de_ser_visible_si_reasignan_la_orden(self):
        OrdenTrabajo.objects.filter(mantenimiento=self.m_tec).update(tecnico=self.tec2)
        self.client.force_login(self.tec)
        self.assertEqual(self.client.get(self.pdf(self.m_tec)).status_code, 404)

    def test_historial_del_tecnico_solo_lo_suyo(self):
        self.client.force_login(self.tec)
        r = self.client.get(reverse('historial'))
        self.assertContains(r, 'Responsable Uno')
        self.assertNotContains(r, 'Responsable Dos')
        self.assertNotContains(r, 'Responsable Tres')
        self.client.force_login(self.gerente)
        r = self.client.get(reverse('historial'))
        for nombre in ('Responsable Uno', 'Responsable Dos', 'Responsable Tres'):
            self.assertContains(r, nombre)

    def test_ficha_de_equipo_enlace_pdf_solo_si_es_suyo(self):
        url = reverse('detalle_equipo', args=[self.equipo.id])
        self.client.force_login(self.tec)
        r = self.client.get(url)
        self.assertContains(r, self.pdf(self.m_tec))
        self.assertNotContains(r, self.pdf(self.m_tec2))
        self.assertNotContains(r, self.pdf(self.m_manual))
        self.client.force_login(self.gerente)
        r = self.client.get(url)
        for m in (self.m_tec, self.m_tec2, self.m_manual):
            self.assertContains(r, self.pdf(m))

    def test_ficha_de_equipo_no_filtra_trabajo_ni_nombres_de_otros_tecnicos(self):
        """M-01: la ficha aplica la misma regla que el historial y el PDF."""
        self.m_tec2.descripcion = 'Cambio de compresor con fuga de R410A'
        self.m_tec2.save()
        self.m_manual.descripcion = 'Registro manual de gerencia'
        self.m_manual.save()
        url = reverse('detalle_equipo', args=[self.equipo.id])
        self.client.force_login(self.tec)
        r = self.client.get(url)
        self.assertContains(r, 'Responsable Uno')
        for ajeno in ('Responsable Dos', 'Responsable Tres', 'Cambio de compresor', 'Registro manual de gerencia'):
            self.assertNotContains(r, ajeno)
        self.assertEqual([m.id for m in r.context['mantenimientos']], [self.m_tec.id])

    def test_ficha_de_equipo_sin_trabajos_propios_muestra_el_mensaje_vacio(self):
        self.client.force_login(self.tec_caducado)
        r = self.client.get(reverse('detalle_equipo', args=[self.equipo.id]))
        self.assertContains(r, 'No hay registros de mantenimiento')
        self.assertNotContains(r, 'Responsable')

    def test_ficha_de_equipo_gestion_ve_todo(self):
        url = reverse('detalle_equipo', args=[self.equipo.id])
        for usuario in (self.gerente, self.admin):
            self.client.force_login(usuario)
            r = self.client.get(url)
            for nombre in ('Responsable Uno', 'Responsable Dos', 'Responsable Tres'):
                self.assertContains(r, nombre)

    def test_equipos_en_consulta_para_el_tecnico(self):
        self.client.force_login(self.tec)
        r = self.client.get(reverse('equipos'))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, reverse('crear_equipo'))
        r = self.client.get(reverse('detalle_equipo', args=[self.equipo.id]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, reverse('editar_equipo', args=[self.equipo.id]))
        self.assertNotContains(r, reverse('registrar_mantenimiento'))

    def test_rutas_de_gestion_cerradas_al_tecnico(self):
        self.client.force_login(self.tec)
        for nombre, args in (('usuarios', []), ('actividad', []), ('calendario', []), ('orden_crear', []),
                             ('crear_equipo', []), ('editar_equipo', [self.equipo.id])):
            self.assertEqual(self.client.get(reverse(nombre, args=args)).status_code, 403, nombre)

    def test_asistente_disponible_para_el_tecnico(self):
        self.client.force_login(self.tec)
        self.assertEqual(self.client.get(reverse('ia_assistant')).status_code, 200)


class AgendaTests(OrdenesBase):
    def _o(self, dias=None, **extra):
        hoy = timezone.localdate()
        datos = dict(equipo=self.equipo, descripcion='Orden', estado=OrdenTrabajo.ASIGNADA, tecnico=self.tec,
                     creado_por=self.gerente, fecha_programada=None if dias is None else hoy + timedelta(days=dias))
        datos.update(extra)
        return OrdenTrabajo.objects.create(**datos)

    def test_agrupa_por_fecha_en_orden(self):
        from core import agenda
        ordenes = [OrdenTrabajo(id=i, fecha_programada=None if d is None else timezone.localdate() + timedelta(days=d))
                   for i, d in enumerate([None, 7, 3, 1, 0, -1], start=1)]
        grupos = agenda.agrupar_por_fecha(ordenes, timezone.localdate())
        self.assertEqual([t for t, _ in grupos], ['Atrasadas', 'Hoy', 'Mañana', 'Esta semana', 'Más adelante', 'Sin fecha'])

    def test_omite_grupos_vacios_y_ordena_dentro_del_grupo(self):
        from core import agenda
        hoy = timezone.localdate()
        a = OrdenTrabajo(id=9, fecha_programada=hoy + timedelta(days=4))
        b = OrdenTrabajo(id=7, fecha_programada=hoy + timedelta(days=2))
        c = OrdenTrabajo(id=8, fecha_programada=hoy + timedelta(days=2))
        grupos = agenda.agrupar_por_fecha([a, c, b], hoy)
        self.assertEqual([(t, [o.id for o in os]) for t, os in grupos], [('Esta semana', [7, 8, 9])])

    def test_agenda_solo_ordenes_abiertas_propias(self):
        visibles = [self._o(0), self._o(2, estado=OrdenTrabajo.EN_EJECUCION)]
        ocultas = [self._o(0, estado=OrdenTrabajo.FINALIZADA), self._o(0, estado=OrdenTrabajo.PENDIENTE_APROBACION),
                   self._o(0, estado=OrdenTrabajo.CANCELADA), self._o(0, tecnico=self.tec2)]
        self.client.force_login(self.tec)
        r = self.client.get(reverse('agenda'))
        for o in visibles:
            self.assertContains(r, o.codigo)
        for o in ocultas:
            self.assertNotContains(r, o.codigo)

    def test_agenda_vacia_muestra_mensaje(self):
        self.client.force_login(self.tec)
        self.assertContains(self.client.get(reverse('agenda')), 'No tienes órdenes abiertas')

    def test_agenda_cerrada_a_gestion(self):
        for usuario in (self.gerente, self.admin):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(reverse('agenda')).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('agenda')).status_code, 302)

    def test_tarjeta_usa_contenedor_de_chips(self):
        self._o(0, tipo='CORRECTIVO', con_checklist=False)
        self.client.force_login(self.tec)
        r = self.client.get(reverse('agenda'))
        for texto in ('<div class="flex flex-wrap gap-1">', 'Correctivo', 'Sin checklist'):
            self.assertContains(r, texto)


class MarcoPorRolTests(OrdenesBase):
    def pagina(self, usuario, nombre):
        self.client.force_login(usuario)
        r = self.client.get(reverse(nombre))
        self.assertEqual(r.status_code, 200, nombre)
        return r.content.decode()

    def href(self, nombre):
        return f'href="{reverse(nombre)}"'

    def test_barra_del_tecnico_tiene_sus_cinco_enlaces(self):
        for pagina in ('ordenes', 'equipos', 'agenda', 'historial'):
            html = self.pagina(self.tec, pagina)
            self.assertEqual(html.count('data-bottomnav-item'), 5, pagina)
            for nombre in ('ordenes', 'equipos', 'agenda', 'historial', 'ia_assistant'):
                self.assertIn(self.href(nombre), html, (pagina, nombre))

    def test_el_tecnico_no_ve_enlaces_de_gestion_en_ningun_menu(self):
        for pagina in ('ordenes', 'equipos', 'agenda', 'historial'):
            html = self.pagina(self.tec, pagina)
            for nombre in ('dashboard', 'calendario', 'usuarios', 'actividad'):
                self.assertNotIn(self.href(nombre), html, (pagina, nombre))

    def test_rotulo_del_panel_segun_rol(self):
        self.assertIn('Panel del técnico', self.pagina(self.tec, 'ordenes'))
        self.assertNotIn('Panel de Gestión', self.pagina(self.tec, 'ordenes'))
        html = self.pagina(self.gerente, 'ordenes')
        self.assertIn('Panel de Gestión', html)
        self.assertNotIn('Panel del técnico', html)

    def test_indicador_de_conexion_solo_para_el_tecnico(self):
        self.assertIn('id="indicador-conexion"', self.pagina(self.tec, 'ordenes'))
        self.assertNotIn('id="indicador-conexion"', self.pagina(self.gerente, 'ordenes'))

    def test_gestion_conserva_su_menu(self):
        for usuario in (self.gerente, self.admin):
            html = self.pagina(usuario, 'ordenes')
            for nombre in ('dashboard', 'calendario', 'ordenes', 'equipos', 'historial', 'ia_assistant'):
                self.assertIn(self.href(nombre), html, nombre)
            self.assertNotIn(self.href('agenda'), html)
            self.assertNotIn('data-bottomnav-item', html)
        self.assertIn(self.href('usuarios'), self.pagina(self.admin, 'ordenes'))

    def test_logo_del_tecnico_lleva_a_mis_ordenes(self):
        self.assertIn(f'<a href="{reverse("ordenes")}" class="flex items-center space-x-3 min-w-0">',
                      self.pagina(self.tec, 'ordenes'))
        self.assertIn(f'<a href="{reverse("dashboard")}" class="flex items-center space-x-3"',
                      self.pagina(self.gerente, 'ordenes'))


class MisOrdenesTests(OrdenesBase):
    def test_agrupa_por_estado_y_atencion(self):
        atencion = self.orden(OrdenTrabajo.EN_EJECUCION, tecnico=self.tec)
        atencion.subsanacion_motivo = 'Falta foto'
        atencion.save()
        ejec = self.orden(OrdenTrabajo.EN_EJECUCION, tecnico=self.tec)
        asig = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        env = self.orden(OrdenTrabajo.PENDIENTE_APROBACION, tecnico=self.tec)
        fin = self.orden(OrdenTrabajo.FINALIZADA, tecnico=self.tec)
        self.client.force_login(self.tec)
        r = self.client.get(reverse('ordenes'))
        titulos = [t for t, _ in r.context['grupos']]
        self.assertEqual(titulos, ['Requieren tu atención', 'En ejecución', 'Asignadas',
                                   'Enviadas a aprobación', 'Finalizadas'])
        self.assertEqual([[o.pk for o in l] for _, l in r.context['grupos']],
                         [[atencion.pk], [ejec.pk], [asig.pk], [env.pk], [fin.pk]])

    def test_solo_las_propias_y_sin_tabla(self):
        self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec2)
        propia = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        self.client.force_login(self.tec)
        html = self.client.get(reverse('ordenes')).content.decode()
        self.assertIn(propia.codigo, html)
        self.assertEqual(html.count('Programada:'), 1)
        self.assertNotIn('<table', html)
        self.assertNotIn('Nueva orden', html)

    def test_finalizadas_limitadas_a_diez(self):
        for _ in range(12):
            self.orden(OrdenTrabajo.FINALIZADA, tecnico=self.tec)
        self.client.force_login(self.tec)
        grupos = dict(self.client.get(reverse('ordenes')).context['grupos'])
        self.assertEqual(len(grupos['Finalizadas']), 10)

    def test_sin_ordenes_muestra_mensaje(self):
        self.client.force_login(self.tec)
        self.assertContains(self.client.get(reverse('ordenes')), 'No tienes órdenes asignadas')

    def test_gestion_conserva_tabla_y_filtros(self):
        self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        self.client.force_login(self.gerente)
        html = self.client.get(reverse('ordenes')).content.decode()
        self.assertIn('<table', html)
        self.assertIn('Nueva orden', html)
        self.assertNotIn('No tienes órdenes asignadas', html)


class PantallasTecnicoTests(OrdenesBase):
    def mantenimiento(self, tecnico):
        orden = self.orden(OrdenTrabajo.FINALIZADA, tecnico=tecnico)
        m = HistorialMantenimiento.objects.create(
            equipo=self.equipo, tipo_mantenimiento='PREVENTIVO', fecha_mantenimiento=date.today(),
            tecnico_responsable=tecnico.username, descripcion='x')
        orden.mantenimiento = m
        orden.save()
        return orden, m

    def test_equipos_tiene_buscador_y_datos_para_filtrar(self):
        self.client.force_login(self.tec)
        html = self.client.get(reverse('equipos')).content.decode()
        self.assertIn('id="buscar-equipo"', html)
        self.assertIn('data-buscar="chiller 1 ch-001 azotea"', html)
        self.assertNotIn('Operativos</button>', html)
        self.client.force_login(self.gerente)
        html = self.client.get(reverse('equipos')).content.decode()
        self.assertNotIn('id="buscar-equipo"', html)
        self.assertIn('Operativos</button>', html)

    def test_historial_en_tarjetas_con_pdf_solo_de_lo_suyo(self):
        _, propio = self.mantenimiento(self.tec)
        _, ajeno = self.mantenimiento(self.tec2)
        self.client.force_login(self.tec)
        html = self.client.get(reverse('historial')).content.decode()
        self.assertIn('Mis intervenciones', html)
        self.assertNotIn('<table', html)
        self.assertIn(reverse('descargar_reporte_pdf', args=[propio.id]), html)
        self.assertNotIn(reverse('descargar_reporte_pdf', args=[ajeno.id]), html)

    def test_historial_vacio_del_tecnico(self):
        self.client.force_login(self.tec)
        self.assertContains(self.client.get(reverse('historial')), 'Aún no tienes intervenciones registradas')

    def test_historial_de_gestion_sigue_en_tabla(self):
        self.mantenimiento(self.tec)
        self.client.force_login(self.gerente)
        html = self.client.get(reverse('historial')).content.decode()
        self.assertIn('<table', html)
        self.assertNotIn('Mis intervenciones', html)

    def test_estilo_tactil_solo_para_el_tecnico(self):
        orden = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        url = reverse('orden_detalle', args=[orden.id])
        self.client.force_login(self.tec)
        self.assertContains(self.client.get(url), 'id="estilo-tactil"')
        self.client.force_login(self.gerente)
        self.assertNotContains(self.client.get(url), 'id="estilo-tactil"')

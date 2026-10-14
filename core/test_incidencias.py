"""Pruebas de la fase 2, parte 3: incidencias de criticidad Alta (decisión de gestión y correctivas)."""
import re

from django.db import IntegrityError, transaction
from django.urls import reverse

from core import incidencias, ordenes
from core.models import DecisionIncidenciaOT, OrdenTrabajo, PuntoChecklistOT
from core.ordenes import ReglaError
from core.test_checklist import ChecklistBase

JUSTIFICACION = 'Se asume el riesgo hasta la próxima visita'


class IncidenciasBase(ChecklistBase):
    def setUp(self):
        super().setUp()
        self.req = self.peticion(self.tec)
        self.gerente_req = self.peticion(self.gerente)

    def _nueva(self, **extra):
        from core.models import EquipoHVAC
        otro, _ = EquipoHVAC.objects.get_or_create(codigo_identificador='OT-9', defaults={'nombre': 'Otro', 'ubicacion': 'Sótano'})
        datos = dict(equipo=otro, tipo='PREVENTIVO', descripcion='Cambiar válvula')
        datos.update(extra)
        return OrdenTrabajo(**datos)

    def en_aprobacion(self, altas=1, otras=0):
        """Orden Pendiente de aprobación con `altas` incidencias Alta y `otras` de gravedad Media."""
        o = self.en_ejecucion('SPLIT')
        self.completar_checklist(o)
        puntos = list(o.puntos.all())
        for p in puntos[:altas]:
            ordenes.marcar_punto(o, p.codigo, 'INCIDENCIA', 'ALTA', 'Fuga en válvula', self.req)
        for p in puntos[altas:altas + otras]:
            ordenes.marcar_punto(o, p.codigo, 'INCIDENCIA', 'MEDIA', 'Desgaste', self.req)
        o.observaciones, o.sin_materiales = 'Con incidencias', True
        o.save()
        ordenes.enviar(o, self.req)
        return o


class ModeloIncidenciasTests(IncidenciasBase):
    def setUp(self):
        super().setUp()
        self.o = self.en_aprobacion(altas=2)
        self.p1, self.p2 = list(self.o.puntos.filter(gravedad='ALTA'))

    def _decision(self, punto, **datos):
        with transaction.atomic():
            return DecisionIncidenciaOT.objects.create(punto=punto, **datos)

    def test_una_decision_por_punto(self):
        self._decision(self.p1, tipo='JUSTIFICADA', justificacion=JUSTIFICACION)
        with self.assertRaises(IntegrityError):
            self._decision(self.p1, tipo='JUSTIFICADA', justificacion=JUSTIFICACION)

    def test_correctiva_exige_orden_y_sin_justificacion(self):
        with self.assertRaises(IntegrityError):
            self._decision(self.p1, tipo='CORRECTIVA')
        otra = self.orden()
        with self.assertRaises(IntegrityError):
            self._decision(self.p1, tipo='CORRECTIVA', orden_correctiva=otra, justificacion='texto')
        self._decision(self.p1, tipo='CORRECTIVA', orden_correctiva=otra)

    def test_justificada_exige_texto_y_sin_orden(self):
        with self.assertRaises(IntegrityError):
            self._decision(self.p1, tipo='JUSTIFICADA')
        with self.assertRaises(IntegrityError):
            self._decision(self.p1, tipo='JUSTIFICADA', justificacion='texto', orden_correctiva=self.orden())

    def test_orden_origen_es_opcional_y_correctivas_las_lista(self):
        self.assertIsNone(self.o.orden_origen)
        hija = self.orden()
        hija.orden_origen = self.o
        hija.save()
        self.assertEqual(list(self.o.correctivas.all()), [hija])


class ServiciosIncidenciasTests(IncidenciasBase):
    def setUp(self):
        super().setUp()
        self.o = self.en_aprobacion(altas=2)
        self.p1, self.p2 = incidencias.incidencias_alta(self.o)

    def test_justificar_guarda_decision_y_evento(self):
        d = incidencias.justificar(self.o, self.p1.id, f'  {JUSTIFICACION}  ', self.gerente_req)
        self.assertEqual((d.tipo, d.justificacion, d.decidida_por), ('JUSTIFICADA', JUSTIFICACION, self.gerente))
        self.assertTrue(self.o.eventos.filter(texto=f'Incidencia Alta justificada: {self.p1.texto}').exists())

    def test_justificacion_corta_o_solo_espacios_se_rechaza(self):
        for texto in ('          ', '123456789', None):
            with self.assertRaisesMessage(ReglaError, 'La justificación es obligatoria (mínimo 10 caracteres).'):
                incidencias.justificar(self.o, self.p1.id, texto, self.gerente_req)
        self.assertFalse(DecisionIncidenciaOT.objects.exists())

    def test_no_se_decide_dos_veces(self):
        incidencias.justificar(self.o, self.p1.id, JUSTIFICACION, self.gerente_req)
        with self.assertRaisesMessage(ReglaError, 'Esta incidencia ya tiene decisión.'):
            incidencias.justificar(self.o, self.p1.id, JUSTIFICACION, self.gerente_req)

    def test_punto_de_otra_orden_inexistente_no_numerico_o_no_alta(self):
        ajena = self.en_aprobacion(altas=1)
        ok = self.o.puntos.filter(resultado='OK').first()
        for punto_id in (incidencias.incidencias_alta(ajena)[0].id, 999999, 'abc', ok.id):
            with self.assertRaisesMessage(ReglaError, 'Incidencia no encontrada.'):
                incidencias.justificar(self.o, punto_id, JUSTIFICACION, self.gerente_req)
        self.assertFalse(DecisionIncidenciaOT.objects.exists())

    def test_solo_gestion_decide(self):
        with self.assertRaisesMessage(ReglaError, 'Solo un administrador o gerente puede hacer esto.'):
            incidencias.justificar(self.o, self.p1.id, JUSTIFICACION, self.req)

    def test_solo_en_pendiente_de_aprobacion(self):
        o = self.en_ejecucion('SPLIT')
        ordenes.marcar_punto(o, o.puntos.first().codigo, 'INCIDENCIA', 'ALTA', 'x', self.req)
        punto = incidencias.incidencias_alta(o)[0]
        with self.assertRaisesMessage(ReglaError, 'La OT ya no está en un estado que lo permita'):
            incidencias.justificar(o, punto.id, JUSTIFICACION, self.gerente_req)

    def test_crear_correctiva_enlaza_fuerza_equipo_y_tipo(self):
        c = incidencias.crear_correctiva(self.o, self.p1.id, self._nueva(), self.gerente_req)
        c.refresh_from_db()
        self.assertEqual((c.tipo, c.equipo, c.orden_origen), ('CORRECTIVO', self.o.equipo, self.o))
        self.assertEqual(c.estado, OrdenTrabajo.PENDIENTE)
        d = DecisionIncidenciaOT.objects.get(punto=self.p1)
        self.assertEqual((d.tipo, d.orden_correctiva, d.justificacion), ('CORRECTIVA', c, ''))
        self.assertTrue(self.o.eventos.filter(texto__startswith=f'Incidencia Alta: correctiva {c.codigo} creada').exists())
        self.assertTrue(c.eventos.filter(texto__startswith=f'Origen: incidencia Alta de {self.o.codigo}').exists())

    def test_crear_correctiva_dos_veces_solo_crea_una(self):
        incidencias.crear_correctiva(self.o, self.p1.id, self._nueva(), self.gerente_req)
        with self.assertRaisesMessage(ReglaError, 'Esta incidencia ya tiene decisión.'):
            incidencias.crear_correctiva(self.o, self.p1.id, self._nueva(), self.gerente_req)
        self.assertEqual(OrdenTrabajo.objects.filter(orden_origen=self.o).count(), 1)

    def test_deshacer_borra_justificacion(self):
        incidencias.justificar(self.o, self.p1.id, JUSTIFICACION, self.gerente_req)
        incidencias.deshacer(self.o, self.p1.id, self.gerente_req)
        self.assertFalse(DecisionIncidenciaOT.objects.exists())
        self.assertTrue(self.o.eventos.filter(texto__startswith='Decisión sobre incidencia Alta deshecha').exists())

    def test_deshacer_correctiva_activa_esta_bloqueado(self):
        incidencias.crear_correctiva(self.o, self.p1.id, self._nueva(), self.gerente_req)
        with self.assertRaisesMessage(ReglaError, 'La orden está bloqueada por una correctiva.'):
            incidencias.deshacer(self.o, self.p1.id, self.gerente_req)
        self.assertEqual(DecisionIncidenciaOT.objects.count(), 1)

    def test_deshacer_sin_decision(self):
        with self.assertRaisesMessage(ReglaError, 'Esa decisión no existe.'):
            incidencias.deshacer(self.o, self.p1.id, self.gerente_req)

    def test_bloqueada_y_pendientes(self):
        self.assertEqual(len(incidencias.pendientes_alta(self.o)), 2)
        self.assertFalse(incidencias.bloqueada_por_correctiva(self.o))
        incidencias.justificar(self.o, self.p1.id, JUSTIFICACION, self.gerente_req)
        self.assertFalse(incidencias.bloqueada_por_correctiva(self.o))
        c = incidencias.crear_correctiva(self.o, self.p2.id, self._nueva(), self.gerente_req)
        self.assertTrue(incidencias.bloqueada_por_correctiva(self.o))
        self.assertEqual(incidencias.pendientes_alta(self.o), [])
        c.estado = OrdenTrabajo.CANCELADA
        c.save()
        self.assertFalse(incidencias.bloqueada_por_correctiva(self.o))

    def test_resumen_decisiones(self):
        self.assertEqual(incidencias.resumen_decisiones(self.o), '')
        incidencias.justificar(self.o, self.p1.id, JUSTIFICACION, self.gerente_req)
        self.assertEqual(incidencias.resumen_decisiones(self.o), 'Incidencias Alta: 1 resuelta (justificada)')
        c = incidencias.crear_correctiva(self.o, self.p2.id, self._nueva(), self.gerente_req)
        self.assertEqual(incidencias.resumen_decisiones(self.o),
                         f'Incidencias Alta: 2 resueltas (justificada, correctiva {c.codigo})')


class ReglasIncidenciasTests(IncidenciasBase):
    def setUp(self):
        super().setUp()
        self.o = self.en_aprobacion(altas=2)
        self.p1, self.p2 = incidencias.incidencias_alta(self.o)

    def test_aprobar_bloqueado_con_pendientes_singular_y_plural(self):
        with self.assertRaisesMessage(ReglaError, 'Faltan 2 incidencias Alta por resolver'):
            ordenes.aprobar(self.o, self.gerente_req)
        incidencias.justificar(self.o, self.p1.id, JUSTIFICACION, self.gerente_req)
        with self.assertRaisesMessage(ReglaError, 'Falta 1 incidencia Alta por resolver'):
            ordenes.aprobar(self.o, self.gerente_req)
        self.o.refresh_from_db()
        self.assertEqual(self.o.estado, OrdenTrabajo.PENDIENTE_APROBACION)

    def test_aprobar_con_todas_decididas_aun_con_correctiva_pendiente(self):
        incidencias.justificar(self.o, self.p1.id, JUSTIFICACION, self.gerente_req)
        c = incidencias.crear_correctiva(self.o, self.p2.id, self._nueva(), self.gerente_req)
        ordenes.aprobar(self.o, self.gerente_req)
        self.assertEqual(self.o.estado, OrdenTrabajo.FINALIZADA)
        self.assertIn(f'Incidencias Alta: 2 resueltas (justificada, correctiva {c.codigo})', self.o.mantenimiento.descripcion)
        c.refresh_from_db()
        self.assertEqual(c.estado, OrdenTrabajo.PENDIENTE)

    def test_media_y_leve_no_bloquean_aprobar(self):
        o = self.en_aprobacion(altas=0, otras=2)
        ordenes.aprobar(o, self.gerente_req)
        self.assertEqual(o.estado, OrdenTrabajo.FINALIZADA)
        self.assertNotIn('Incidencias Alta', o.mantenimiento.descripcion)

    def test_orden_antigua_sin_puntos_se_aprueba_como_siempre(self):
        antigua = self.orden(OrdenTrabajo.PENDIENTE_APROBACION, self.tec)
        antigua.observaciones = 'Todo bien'
        antigua.save()
        ordenes.aprobar(antigua, self.gerente_req)
        self.assertEqual(antigua.estado, OrdenTrabajo.FINALIZADA)

    def test_subsanacion_bloqueada_con_correctiva_activa(self):
        incidencias.crear_correctiva(self.o, self.p1.id, self._nueva(), self.gerente_req)
        with self.assertRaisesMessage(ReglaError, 'La orden está bloqueada por una correctiva.'):
            ordenes.solicitar_subsanacion(self.o, 'Revisar', '', self.gerente_req)
        self.o.refresh_from_db()
        self.assertEqual(self.o.estado, OrdenTrabajo.PENDIENTE_APROBACION)

    def test_subsanacion_permitida_con_solo_justificaciones(self):
        incidencias.justificar(self.o, self.p1.id, JUSTIFICACION, self.gerente_req)
        ordenes.solicitar_subsanacion(self.o, 'Revisar', 'CHECKLIST', self.gerente_req)
        self.assertEqual(self.o.estado, OrdenTrabajo.EN_EJECUCION)

    def test_cambiar_la_gravedad_de_un_punto_justificado_anula_la_decision(self):
        incidencias.justificar(self.o, self.p1.id, JUSTIFICACION, self.gerente_req)
        incidencias.justificar(self.o, self.p2.id, JUSTIFICACION, self.gerente_req)
        ordenes.solicitar_subsanacion(self.o, 'Revisar', 'CHECKLIST', self.gerente_req)
        ordenes.marcar_punto(self.o, self.p1.codigo, 'INCIDENCIA', 'MEDIA', 'Ya no es grave', self.req)
        ordenes.marcar_punto(self.o, self.p2.codigo, 'INCIDENCIA', 'ALTA', 'Sigue grave', self.req)
        self.assertFalse(DecisionIncidenciaOT.objects.filter(punto=self.p1).exists())
        self.assertTrue(DecisionIncidenciaOT.objects.filter(punto=self.p2).exists())
        self.assertTrue(self.o.eventos.filter(texto__startswith='Decisión anulada: el punto cambió').exists())

    def test_cancelar_correctiva_libera_la_incidencia_y_desbloquea(self):
        c = incidencias.crear_correctiva(self.o, self.p1.id, self._nueva(), self.gerente_req)
        ordenes.cancelar(c, 'Ya no hace falta', self.gerente_req)
        self.assertFalse(DecisionIncidenciaOT.objects.exists())
        self.assertIn(self.p1.id, [p.id for p in incidencias.pendientes_alta(self.o)])
        self.assertFalse(incidencias.bloqueada_por_correctiva(self.o))
        self.assertTrue(self.o.eventos.filter(texto__startswith=f'Correctiva {c.codigo} cancelada').exists())
        self.assertTrue(c.eventos.filter(texto__startswith=f'Cancelada: libera la incidencia Alta de {self.o.codigo}').exists())
        ordenes.solicitar_subsanacion(self.o, 'Revisar', '', self.gerente_req)

    def test_la_original_pendiente_de_aprobacion_no_se_puede_cancelar(self):
        incidencias.crear_correctiva(self.o, self.p1.id, self._nueva(), self.gerente_req)
        self.assertFalse(ordenes.puede_cancelar(self.o, self.gerente))


class VistasIncidenciasTests(IncidenciasBase):
    def setUp(self):
        super().setUp()
        self.o = self.en_aprobacion(altas=2)
        self.p1, self.p2 = incidencias.incidencias_alta(self.o)

    def url(self, nombre, punto=None, orden=None):
        return reverse(nombre, args=[(orden or self.o).id, (punto or self.p1).id])

    def post(self, nombre, usuario=None, punto=None, **datos):
        self.client.force_login(usuario or self.gerente)
        return self.client.post(self.url(nombre, punto), datos, follow=True)

    def test_gerente_justifica_por_post(self):
        r = self.post('orden_incidencia_justificar', justificacion=JUSTIFICACION)
        self.assertContains(r, 'Incidencia justificada.')
        self.assertTrue(DecisionIncidenciaOT.objects.filter(punto=self.p1, tipo='JUSTIFICADA').exists())

    def test_justificacion_corta_muestra_error_y_no_guarda(self):
        r = self.post('orden_incidencia_justificar', justificacion='corta')
        self.assertContains(r, 'mínimo 10 caracteres')
        self.assertFalse(DecisionIncidenciaOT.objects.exists())

    def test_el_tecnico_asignado_no_puede_decidir(self):
        r = self.post('orden_incidencia_justificar', usuario=self.tec, justificacion=JUSTIFICACION)
        self.assertContains(r, 'Solo un administrador o gerente puede hacer esto.')
        self.assertFalse(DecisionIncidenciaOT.objects.exists())

    def test_otro_tecnico_recibe_404(self):
        self.client.force_login(self.tec2)
        r = self.client.post(self.url('orden_incidencia_justificar'), {'justificacion': JUSTIFICACION})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(DecisionIncidenciaOT.objects.exists())

    def test_punto_inexistente_da_mensaje(self):
        self.client.force_login(self.gerente)
        r = self.client.post(reverse('orden_incidencia_justificar', args=[self.o.id, 999999]),
                             {'justificacion': JUSTIFICACION}, follow=True)
        self.assertContains(r, 'Incidencia no encontrada.')

    def test_get_en_acciones_de_escritura_da_405_y_anonimo_redirige(self):
        self.client.force_login(self.gerente)
        for nombre in ('orden_incidencia_justificar', 'orden_incidencia_deshacer'):
            self.assertEqual(self.client.get(self.url(nombre)).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(self.url('orden_incidencia_justificar'), {}).status_code, 302)
        self.assertEqual(self.client.get(self.url('orden_incidencia_correctiva')).status_code, 302)

    def test_deshacer_por_post(self):
        self.post('orden_incidencia_justificar', justificacion=JUSTIFICACION)
        r = self.post('orden_incidencia_deshacer')
        self.assertContains(r, 'Decisión deshecha')
        self.assertFalse(DecisionIncidenciaOT.objects.exists())

    def test_get_correctiva_muestra_formulario_con_equipo_y_tipo_fijados(self):
        self.client.force_login(self.gerente)
        r = self.client.get(self.url('orden_incidencia_correctiva'))
        self.assertContains(r, 'Nueva orden correctiva')
        self.assertContains(r, f'Origen: incidencia Alta de {self.o.codigo}')
        form = r.context['form']
        self.assertTrue(form.fields['equipo'].disabled and form.fields['tipo'].disabled)
        self.assertEqual((form.initial['equipo'], form.initial['tipo']), (self.o.equipo_id, 'CORRECTIVO'))

    def test_post_correctiva_crea_la_orden_enlazada_aunque_se_manipule_equipo_y_tipo(self):
        otro = self._nueva().equipo
        r = self.post('orden_incidencia_correctiva', equipo=otro.id, tipo='PREVENTIVO', criticidad='ALTA',
                      descripcion='Sustituir la válvula con fuga')
        c = OrdenTrabajo.objects.get(orden_origen=self.o)
        self.assertEqual((c.tipo, c.equipo, c.criticidad), ('CORRECTIVO', self.o.equipo, 'ALTA'))
        self.assertContains(r, f'{c.codigo} creada y enlazada a la incidencia.')
        self.assertEqual(DecisionIncidenciaOT.objects.get(punto=self.p1).orden_correctiva, c)

    def test_post_correctiva_con_datos_invalidos_no_crea_nada(self):
        r = self.post('orden_incidencia_correctiva', criticidad='ALTA', descripcion='')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Revisa estos datos')
        self.assertFalse(OrdenTrabajo.objects.filter(orden_origen=self.o).exists())

    def test_correctiva_sobre_incidencia_ya_decidida_redirige_con_mensaje(self):
        self.post('orden_incidencia_justificar', justificacion=JUSTIFICACION)
        self.client.force_login(self.gerente)
        r = self.client.get(self.url('orden_incidencia_correctiva'), follow=True)
        self.assertContains(r, 'Esta incidencia ya tiene decisión.')


class PantallaIncidenciasTests(IncidenciasBase):
    def setUp(self):
        super().setUp()
        self.o = self.en_aprobacion(altas=2)
        self.p1, self.p2 = incidencias.incidencias_alta(self.o)

    def detalle(self, usuario, orden=None):
        self.client.force_login(usuario)
        return self.client.get(reverse('orden_detalle', args=[(orden or self.o).id]))

    def boton_aprobar_desactivado(self, r):
        html = r.content.decode()
        self.assertIn('Aprobar y finalizar', html)
        return bool(re.search(r'type="submit"\s+disabled[^>]*>Aprobar y finalizar', html))

    def test_gerente_ve_el_bloque_las_acciones_y_el_aprobar_desactivado(self):
        r = self.detalle(self.gerente)
        self.assertContains(r, 'id="incidencias-alta"')
        self.assertContains(r, 'Crear correctiva')
        self.assertContains(r, 'name="justificacion"')
        self.assertContains(r, 'Faltan 2 incidencias Alta por resolver')
        self.assertTrue(self.boton_aprobar_desactivado(r))

    def test_con_todo_decidido_el_aprobar_se_activa(self):
        incidencias.justificar(self.o, self.p1.id, JUSTIFICACION, self.gerente_req)
        r = self.detalle(self.gerente)
        self.assertContains(r, 'Falta 1 incidencia Alta por resolver')
        incidencias.justificar(self.o, self.p2.id, JUSTIFICACION, self.gerente_req)
        r = self.detalle(self.gerente)
        self.assertContains(r, 'Todas resueltas')
        self.assertContains(r, 'Deshacer decisión')
        self.assertFalse(self.boton_aprobar_desactivado(r))

    def test_el_tecnico_ve_las_incidencias_sin_acciones(self):
        incidencias.justificar(self.o, self.p1.id, JUSTIFICACION, self.gerente_req)
        r = self.detalle(self.tec)
        self.assertContains(r, 'id="incidencias-alta"')
        self.assertContains(r, JUSTIFICACION)
        self.assertContains(r, 'Sin resolver')
        for texto in ('Crear correctiva', 'name="justificacion"', 'Deshacer decisión'):
            self.assertNotContains(r, texto)

    def test_con_correctiva_activa_no_hay_deshacer_ni_devolver_al_tecnico(self):
        c = incidencias.crear_correctiva(self.o, self.p1.id, self._nueva(), self.gerente_req)
        r = self.detalle(self.gerente)
        self.assertContains(r, 'Bloqueada por una correctiva activa.')
        self.assertContains(r, 'Bloqueada por una correctiva: no se puede devolver al técnico')
        self.assertNotContains(r, 'Devolver al técnico')
        self.assertNotContains(r, f'action="{reverse("orden_incidencia_deshacer", args=[self.o.id, self.p1.id])}"')
        self.assertContains(r, c.codigo)

    def test_la_correctiva_muestra_el_origen_y_la_original_sus_correctivas(self):
        c = incidencias.crear_correctiva(self.o, self.p1.id, self._nueva(), self.gerente_req)
        r = self.detalle(self.gerente, c)
        self.assertContains(r, 'Origen')
        self.assertContains(r, f'Incidencia Alta de <a href="{reverse("orden_detalle", args=[self.o.id])}"')
        self.assertContains(r, self.p1.texto)
        r = self.detalle(self.gerente)
        self.assertContains(r, 'Correctivas')
        self.assertContains(r, reverse('orden_detalle', args=[c.id]))

    def test_el_tecnico_no_ve_enlaces_a_ordenes_que_no_puede_abrir(self):
        """La correctiva la gestiona otro técnico: el origen y las correctivas se muestran como texto, sin enlace."""
        c = incidencias.crear_correctiva(self.o, self.p1.id, self._nueva(), self.gerente_req)
        c.tecnico = self.tec2
        c.save()
        self.o.tecnico = self.tec
        self.o.save()
        # El técnico de la original ve la correctiva (otra persona) sin enlace.
        r = self.detalle(self.tec)
        self.assertContains(r, c.codigo)
        self.assertNotContains(r, reverse('orden_detalle', args=[c.id]))
        # El técnico de la correctiva ve la original (de otro) sin enlace.
        r = self.detalle(self.tec2, c)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.o.codigo)
        self.assertNotContains(r, reverse('orden_detalle', args=[self.o.id]))

    def test_el_tecnico_si_ve_el_enlace_si_la_orden_es_suya(self):
        c = incidencias.crear_correctiva(self.o, self.p1.id, self._nueva(), self.gerente_req)
        c.tecnico = self.tec
        c.save()
        self.o.tecnico = self.tec
        self.o.save()
        self.assertContains(self.detalle(self.tec), reverse('orden_detalle', args=[c.id]))
        self.assertContains(self.detalle(self.tec, c), reverse('orden_detalle', args=[self.o.id]))

    def test_el_listado_marca_las_sin_resolver_y_las_bloqueadas(self):
        self.client.force_login(self.gerente)
        self.assertContains(self.client.get(reverse('ordenes')), 'Incidencias Alta sin resolver')
        incidencias.justificar(self.o, self.p1.id, JUSTIFICACION, self.gerente_req)
        incidencias.crear_correctiva(self.o, self.p2.id, self._nueva(), self.gerente_req)
        r = self.client.get(reverse('ordenes'))
        self.assertNotContains(r, 'Incidencias Alta sin resolver')
        self.assertContains(r, 'Bloqueada')

    def test_sin_incidencias_alta_o_en_ejecucion_no_hay_bloque(self):
        o = self.en_aprobacion(altas=0, otras=1)
        self.assertNotContains(self.detalle(self.gerente, o), 'id="incidencias-alta"')
        o = self.en_ejecucion('SPLIT')
        ordenes.marcar_punto(o, o.puntos.first().codigo, 'INCIDENCIA', 'ALTA', 'x', self.req)
        self.assertNotContains(self.detalle(self.tec, o), 'id="incidencias-alta"')

    def test_orden_finalizada_muestra_las_decisiones_sin_acciones(self):
        incidencias.justificar(self.o, self.p1.id, JUSTIFICACION, self.gerente_req)
        incidencias.justificar(self.o, self.p2.id, JUSTIFICACION, self.gerente_req)
        ordenes.aprobar(self.o, self.gerente_req)
        r = self.detalle(self.gerente)
        self.assertContains(r, 'Todas resueltas')
        self.assertNotContains(r, 'Deshacer decisión')


class RevisionIncidenciasTests(IncidenciasBase):
    """Casos de la revisión independiente de la parte 3."""

    def setUp(self):
        super().setUp()
        self.o = self.en_aprobacion(altas=2)
        self.p1, self.p2 = incidencias.incidencias_alta(self.o)

    def test_cancelar_la_correctiva_de_una_original_finalizada_conserva_la_decision(self):
        incidencias.justificar(self.o, self.p1.id, JUSTIFICACION, self.gerente_req)
        c = incidencias.crear_correctiva(self.o, self.p2.id, self._nueva(), self.gerente_req)
        ordenes.aprobar(self.o, self.gerente_req)
        ordenes.cancelar(c, 'Ya no hace falta', self.gerente_req)
        self.assertTrue(DecisionIncidenciaOT.objects.filter(punto=self.p2, tipo='CORRECTIVA').exists())
        self.assertEqual(incidencias.pendientes_alta(self.o), [])
        self.assertTrue(self.o.eventos.filter(texto__contains='la decisión se conserva').exists())

    def test_anular_no_toca_la_decision_de_una_correctiva_activa(self):
        incidencias.crear_correctiva(self.o, self.p1.id, self._nueva(), self.gerente_req)
        punto = self.o.puntos.get(pk=self.p1.pk)
        punto.resultado, punto.gravedad = 'OK', ''
        incidencias.anular_si_cambia(punto, self.req)
        self.assertTrue(DecisionIncidenciaOT.objects.filter(punto=self.p1).exists())

    def test_en_subsanacion_las_decisiones_se_ven_sin_acciones(self):
        incidencias.justificar(self.o, self.p1.id, JUSTIFICACION, self.gerente_req)
        ordenes.solicitar_subsanacion(self.o, 'Revisar', 'CHECKLIST', self.gerente_req)
        for usuario in (self.gerente, self.tec):
            self.client.force_login(usuario)
            r = self.client.get(reverse('orden_detalle', args=[self.o.id]))
            self.assertContains(r, 'id="incidencias-alta"')
            self.assertContains(r, JUSTIFICACION)
            self.assertNotContains(r, 'Crear correctiva')
            self.assertNotContains(r, 'Deshacer decisión')

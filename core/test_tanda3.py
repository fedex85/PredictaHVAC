"""Tanda 3: verificación del equipo, próxima acción tras la firma y OT de emergencia creada por el técnico."""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from core import evidencias, ordenes
from core.models import Aviso, EquipoHVAC, EventoOT, OrdenTrabajo, PuntoChecklistOT
from core.ordenes import ReglaError
from core.test_ordenes import OrdenesBase, png_en_base64
from core.test_sin_conexion import SincronizacionBase


class VerificacionEquipoTests(OrdenesBase):
    def setUp(self):
        super().setUp()
        self.otro = EquipoHVAC.objects.create(nombre='Split 2', codigo_identificador='SP-002', ubicacion='Sala')
        self.o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)

    def iniciar(self, **datos):
        self.client.force_login(self.tec)
        base = {'llegada': 'NORMAL'}
        base.update(datos)
        return self.post('orden_iniciar', self.o, **base)

    def estado(self):
        self.o.refresh_from_db()
        return self.o.estado

    def test_sin_identificar_no_se_inicia(self):
        r = self.iniciar()
        self.assertContains(r, 'Identifica el equipo')
        self.assertEqual(self.estado(), OrdenTrabajo.ASIGNADA)

    def test_codigo_correcto_en_cualquier_mayuscula_inicia_y_queda_verificado(self):
        self.iniciar(equipo_codigo=' ch-001 ')
        self.assertEqual(self.estado(), OrdenTrabajo.EN_EJECUCION)
        self.assertEqual((self.o.verificacion, self.o.verificacion_detalle), ('MANUAL', 'CH-001'))

    def test_el_contenido_del_qr_es_la_url_de_la_ficha(self):
        self.iniciar(equipo_codigo=f'https://app.ejemplo.es/equipos/{self.equipo.id}/')
        self.assertEqual(self.estado(), OrdenTrabajo.EN_EJECUCION)
        self.assertEqual(self.o.verificacion, 'QR')
        self.assertTrue(EventoOT.objects.filter(orden=self.o, texto__contains='Equipo verificado por QR').exists())

    def test_otro_equipo_bloquea_el_progreso(self):
        r = self.iniciar(equipo_codigo='SP-002')
        self.assertContains(r, 'no coincide con el de la orden')
        self.assertEqual(self.estado(), OrdenTrabajo.ASIGNADA)

    def test_qr_de_otro_equipo_bloquea(self):
        self.iniciar(equipo_codigo=f'https://app.ejemplo.es/equipos/{self.otro.id}/')
        self.assertEqual(self.estado(), OrdenTrabajo.ASIGNADA)

    def test_codigo_inexistente_bloquea(self):
        self.iniciar(equipo_codigo='NO-EXISTE')
        self.assertEqual(self.estado(), OrdenTrabajo.ASIGNADA)

    def test_continuar_con_discrepancia_exige_observacion(self):
        r = self.iniciar(equipo_codigo='SP-002', continuar_discrepancia='on')
        self.assertContains(r, 'describe la incidencia')
        self.assertEqual(self.estado(), OrdenTrabajo.ASIGNADA)

    def test_discrepancia_con_observacion_inicia_registra_y_avisa_a_gestion(self):
        self.iniciar(equipo_codigo='SP-002', continuar_discrepancia='on', verificacion_nota='La etiqueta está cambiada')
        self.assertEqual(self.estado(), OrdenTrabajo.EN_EJECUCION)
        self.assertEqual(self.o.verificacion, 'DISCREPANCIA')
        self.assertIn('OT: CH-001; identificado: SP-002', self.o.verificacion_detalle)
        self.assertIn('La etiqueta está cambiada', self.o.verificacion_detalle)
        self.assertTrue(EventoOT.objects.filter(orden=self.o, usuario_nombre='Tec', texto__startswith='Discrepancia de equipo').exists())
        for u in (self.gerente, self.admin):
            self.assertTrue(Aviso.objects.filter(usuario=u, orden=self.o, texto__contains='equipo distinto').exists())

    def test_discrepancia_sin_codigo_tambien_se_registra(self):
        self.iniciar(continuar_discrepancia='on', verificacion_nota='Sin etiqueta legible')
        self.estado()
        self.assertEqual(self.o.verificacion, 'DISCREPANCIA')
        self.assertIn('sin identificar', self.o.verificacion_detalle)

    def test_el_detalle_muestra_la_verificacion(self):
        self.iniciar(equipo_codigo='SP-002', continuar_discrepancia='on', verificacion_nota='Etiqueta cambiada')
        self.client.force_login(self.gerente)
        r = self.client.get(reverse('orden_detalle', args=[self.o.id]))
        self.assertContains(r, 'Discrepancia: OT: CH-001; identificado: SP-002')


class VerificacionSinConexionTests(SincronizacionBase):
    def test_el_paquete_descargado_lleva_el_id_del_equipo(self):
        o = self.preparar()
        self.client.force_login(self.tec)
        r = self.client.post(reverse('orden_descargar', args=[o.id]))
        self.assertEqual(r.json()['paquete']['equipo']['id'], o.equipo_id)

    def test_paquete_con_equipo_correcto_queda_verificado(self):
        o = self.preparar()
        r = self.enviar(o, self.paquete(verificacion={'codigo': 'CH-001', 'continuar': False, 'nota': ''}), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.verificacion, 'MANUAL')

    def test_paquete_con_discrepancia_no_pierde_el_trabajo_pero_la_registra_y_avisa(self):
        o = self.preparar()
        r = self.enviar(o, self.paquete(verificacion={'codigo': 'ZZ-9', 'continuar': True, 'nota': 'Otra unidad'}), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual((o.estado, o.verificacion), (OrdenTrabajo.EN_EJECUCION, 'DISCREPANCIA'))
        self.assertTrue(Aviso.objects.filter(usuario=self.gerente, orden=o).exists())

    def test_paquete_con_discrepancia_sin_observacion_se_registra_sin_rechazar(self):
        o = self.preparar()
        r = self.enviar(o, self.paquete(verificacion={'codigo': 'ZZ-9', 'continuar': False, 'nota': ''}), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertIn('Sin observación', o.verificacion_detalle)

    def test_paquete_con_verificacion_mal_formada_se_rechaza(self):
        o = self.preparar()
        self.assertEqual(self.enviar(o, self.paquete(verificacion='CH-001'), usuario=self.tec).status_code, 400)

    def test_paquete_antiguo_sin_verificacion_sigue_aceptandose(self):
        o = self.preparar()
        self.assertEqual(self.enviar(o, self.paquete(), usuario=self.tec).status_code, 200)
        o.refresh_from_db()
        self.assertEqual(o.verificacion, '')


class ProximaAccionBase(OrdenesBase):
    def lista(self, con_incidencia=False):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        if not con_incidencia:
            o.con_checklist = False
            o.save()
        ordenes.iniciar(o, self.peticion(self.tec), llegada=('NORMAL', ''))
        o.refresh_from_db()
        o.observaciones, o.sin_materiales = 'Hecho', True
        o.save()
        if con_incidencia:
            self.completar_checklist(o)
            p = o.puntos.first()
            ordenes.marcar_punto(o, p.codigo, 'INCIDENCIA', 'LEVE', 'Ruido', self.peticion(self.tec))
        self.completar_evidencias(o)
        return o

    def req(self):
        return self.peticion(self.tec)


class ProximaAccionTests(ProximaAccionBase):
    def test_sin_elegir_no_se_puede_enviar(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        o.con_checklist = False
        o.save()
        ordenes.iniciar(o, self.req(), llegada=('NORMAL', ''))
        self.assertTrue(any('Elige la próxima acción' in p for p in ordenes.validar_envio(o)))

    def test_cerrar_sin_accion_sin_incidencias(self):
        o = self.lista()
        ordenes.elegir_proxima_accion(o, 'NINGUNA', None, '', self.req())
        ordenes.enviar(o, self.req())
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.PENDIENTE_APROBACION)

    def test_cerrar_sin_accion_se_rechaza_con_incidencias_abiertas(self):
        o = self.lista(con_incidencia=True)
        with self.assertRaises(ReglaError) as cm:
            ordenes.elegir_proxima_accion(o, 'NINGUNA', None, '', self.req())
        self.assertIn('incidencias abiertas', str(cm.exception))

    def test_cerrar_sin_accion_elegido_antes_de_aparecer_una_incidencia_bloquea_el_envio(self):
        o = self.lista()
        ordenes.elegir_proxima_accion(o, 'NINGUNA', None, '', self.req())
        PuntoChecklistOT.objects.create(orden=o, codigo='X1', bloque='INSPECCION', texto='Punto', resultado='INCIDENCIA', gravedad='LEVE')
        self.assertTrue(any('incidencias abiertas' in p for p in ordenes.validar_envio(o)))

    def test_revision_exige_fecha_valida(self):
        o = self.lista()
        hoy = timezone.localdate()
        for fecha in (None, hoy - timedelta(days=1), hoy.replace(year=hoy.year + 4)):
            with self.assertRaises(ReglaError):
                ordenes.elegir_proxima_accion(o, 'REVISION', fecha, '', self.req())
        ordenes.elegir_proxima_accion(o, 'REVISION', hoy + timedelta(days=30), '', self.req())
        o.refresh_from_db()
        self.assertEqual((o.proxima_accion, o.proxima_fecha), ('REVISION', hoy + timedelta(days=30)))

    def test_correctiva_exige_descripcion_y_se_crea_al_enviar(self):
        o = self.lista()
        with self.assertRaises(ReglaError):
            ordenes.elegir_proxima_accion(o, 'CORRECTIVA', None, '  ', self.req())
        ordenes.elegir_proxima_accion(o, 'CORRECTIVA', None, 'Cambiar el compresor', self.req())
        self.assertEqual(OrdenTrabajo.objects.count(), 1)
        ordenes.enviar(o, self.req())
        o.refresh_from_db()
        c = o.proxima_orden
        self.assertEqual((c.estado, c.tipo, c.equipo, c.orden_origen, c.tecnico), (OrdenTrabajo.PENDIENTE, 'CORRECTIVO', o.equipo, o, None))
        self.assertEqual(c.descripcion, 'Cambiar el compresor')
        self.assertEqual(o.estado, OrdenTrabajo.PENDIENTE_APROBACION)  # la OT actual continúa

    def test_la_correctiva_no_se_duplica_tras_una_subsanacion(self):
        o = self.lista()
        ordenes.elegir_proxima_accion(o, 'CORRECTIVA', None, 'Cambiar el compresor', self.req())
        ordenes.enviar(o, self.req())
        ordenes.solicitar_subsanacion(o, 'Amplía las observaciones', 'OBSERVACIONES', self.peticion(self.gerente))
        o.refresh_from_db()
        ordenes.guardar_ejecucion(o, 'Amplío observaciones', '', True, self.req())
        o.refresh_from_db()
        evidencias.guardar_firma_tecnico(o, png_en_base64(), self.req())
        ordenes.enviar(o, self.req())
        self.assertEqual(OrdenTrabajo.objects.filter(descripcion='Cambiar el compresor').count(), 1)

    def test_no_se_cambia_la_accion_una_vez_creada_la_correctiva(self):
        o = self.lista()
        ordenes.elegir_proxima_accion(o, 'CORRECTIVA', None, 'Cambiar el compresor', self.req())
        ordenes.enviar(o, self.req())
        ordenes.solicitar_subsanacion(o, 'Revisa', 'OBSERVACIONES', self.peticion(self.gerente))
        with self.assertRaises(ReglaError):
            ordenes.elegir_proxima_accion(o, 'NINGUNA', None, '', self.req())

    def test_solo_el_tecnico_asignado_y_en_ejecucion(self):
        o = self.lista()
        with self.assertRaises(ReglaError):
            ordenes.elegir_proxima_accion(o, 'NINGUNA', None, '', self.peticion(self.tec2))
        with self.assertRaises(ReglaError):
            ordenes.elegir_proxima_accion(o, 'NINGUNA', None, '', self.peticion(self.gerente))

    def test_opcion_desconocida(self):
        o = self.lista()
        with self.assertRaises(ReglaError):
            ordenes.elegir_proxima_accion(o, 'OTRA', None, '', self.req())

    def test_el_gerente_confirma_la_fecha_y_se_crea_la_revision(self):
        o = self.lista()
        propuesta = timezone.localdate() + timedelta(days=30)
        ordenes.elegir_proxima_accion(o, 'REVISION', propuesta, '', self.req())
        ordenes.enviar(o, self.req())
        confirmada = propuesta + timedelta(days=5)
        ordenes.aprobar(o, self.peticion(self.gerente), fecha_revision=confirmada)
        o.refresh_from_db()
        r = o.proxima_orden
        self.assertEqual((r.tipo, r.estado, r.fecha_programada, r.equipo), ('PREVENTIVO', OrdenTrabajo.PENDIENTE, confirmada, o.equipo))
        self.assertEqual(o.proxima_fecha, confirmada)
        self.assertTrue(EventoOT.objects.filter(orden=o, texto__startswith='Próxima revisión confirmada').exists())

    def test_sin_confirmar_se_usa_la_propuesta_y_una_fecha_pasada_se_rechaza(self):
        o = self.lista()
        propuesta = timezone.localdate() + timedelta(days=30)
        ordenes.elegir_proxima_accion(o, 'REVISION', propuesta, '', self.req())
        ordenes.enviar(o, self.req())
        with self.assertRaises(ReglaError):
            ordenes.aprobar(o, self.peticion(self.gerente), fecha_revision=timezone.localdate() - timedelta(days=1))
        ordenes.aprobar(o, self.peticion(self.gerente))
        o.refresh_from_db()
        self.assertEqual(o.proxima_orden.fecha_programada, propuesta)

    def test_formularios_web(self):
        o = self.lista()
        self.client.force_login(self.tec)
        r = self.client.get(reverse('orden_detalle', args=[o.id]))
        self.assertContains(r, 'Guardar próxima acción')
        r = self.post('orden_proxima', o, accion='REVISION', fecha=(timezone.localdate() + timedelta(days=10)).isoformat())
        self.assertContains(r, 'Próxima acción guardada')
        r = self.post('orden_proxima', o, accion='CORRECTIVA', texto='')
        self.assertContains(r, 'Describe la OT correctiva')
        r = self.post('orden_proxima', o, accion='')
        self.assertContains(r, 'Elige una de las tres opciones')
        ordenes.enviar(o, self.req())
        self.client.force_login(self.gerente)
        r = self.client.get(reverse('orden_detalle', args=[o.id]))
        self.assertContains(r, 'Confirma la fecha de la próxima revisión')
        self.client.post(reverse('orden_aprobar', args=[o.id]), {'proxima_fecha': (timezone.localdate() + timedelta(days=12)).isoformat()})
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.FINALIZADA)
        self.assertEqual(o.proxima_orden.fecha_programada, timezone.localdate() + timedelta(days=12))

    def test_no_se_ofrece_antes_de_la_firma(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        ordenes.iniciar(o, self.req(), llegada=('NORMAL', ''))
        self.client.force_login(self.tec)
        r = self.client.get(reverse('orden_detalle', args=[o.id]))
        self.assertContains(r, 'Se elige después de recoger la firma del cliente')
        self.assertNotContains(r, 'Guardar próxima acción')

    def test_aprobacion_automatica_crea_la_revision_con_la_fecha_propuesta(self):
        from django.test import override_settings
        o = self.lista()
        propuesta = timezone.localdate() + timedelta(days=20)
        ordenes.elegir_proxima_accion(o, 'REVISION', propuesta, '', self.req())
        with override_settings(APROBACION_AUTOMATICA=True):
            ordenes.enviar(o, self.req())
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.FINALIZADA)
        self.assertEqual(o.proxima_orden.fecha_programada, propuesta)


class EmergenciaTests(OrdenesBase):
    def datos(self, **extra):
        d = {'equipo': self.equipo.id, 'motivo': 'Compresor ruidoso', 'descripcion': 'Se oye un golpeteo', 'criticidad': 'ALTA'}
        d.update(extra)
        return d

    def test_el_tecnico_crea_una_ot_asignada_a_si_mismo_y_avisa_a_gestion(self):
        self.client.force_login(self.tec)
        r = self.client.post(reverse('orden_emergencia'), self.datos(), follow=True)
        o = OrdenTrabajo.objects.get()
        self.assertEqual((o.estado, o.tecnico, o.tipo, o.criticidad, o.creado_por), (OrdenTrabajo.ASIGNADA, self.tec, 'CORRECTIVO', 'ALTA', self.tec))
        self.assertEqual(o.descripcion, 'Compresor ruidoso: Se oye un golpeteo')
        self.assertTrue(o.con_checklist)
        self.assertContains(r, 'creada y asignada a ti')
        self.assertTrue(Aviso.objects.filter(usuario=self.gerente, orden=o, texto__contains='emergencia').exists())

    def test_la_criticidad_alta_no_bloquea_el_inicio(self):
        self.client.force_login(self.tec)
        self.client.post(reverse('orden_emergencia'), self.datos())
        o = OrdenTrabajo.objects.get()
        self.post('orden_iniciar', o, llegada='NO_ARRANCA', equipo_codigo='CH-001')
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.EN_EJECUCION)

    def test_sin_checklist_opcional(self):
        self.client.force_login(self.tec)
        self.client.post(reverse('orden_emergencia'), self.datos(sin_checklist='on'))
        self.assertFalse(OrdenTrabajo.objects.get().con_checklist)

    def test_solo_equipos_existentes_y_campos_obligatorios(self):
        self.client.force_login(self.tec)
        for malo in ({'equipo': 9999}, {'motivo': ''}, {'descripcion': ''}, {'criticidad': 'ENORME'}):
            self.client.post(reverse('orden_emergencia'), self.datos(**malo))
        self.assertEqual(OrdenTrabajo.objects.count(), 0)

    def test_con_refrigerante_exige_certificado_vigente(self):
        self.client.force_login(self.tec_caducado)
        r = self.client.post(reverse('orden_emergencia'), self.datos(requiere_refrigerante='on'))
        self.assertContains(r, 'No puedes crearla')
        self.assertEqual(OrdenTrabajo.objects.count(), 0)
        self.client.force_login(self.tec)
        self.client.post(reverse('orden_emergencia'), self.datos(requiere_refrigerante='on'))
        self.assertEqual(OrdenTrabajo.objects.count(), 1)

    def test_gestion_no_usa_esta_pantalla(self):
        self.client.force_login(self.gerente)
        self.assertEqual(self.client.get(reverse('orden_emergencia')).status_code, 403)
        self.assertEqual(self.client.post(reverse('orden_emergencia'), self.datos()).status_code, 403)

    def test_el_boton_aparece_solo_al_tecnico(self):
        self.client.force_login(self.tec)
        self.assertContains(self.client.get(reverse('ordenes')), 'Nueva correctiva')
        self.client.force_login(self.gerente)
        self.assertNotContains(self.client.get(reverse('ordenes')), 'Nueva correctiva')

    def test_crear_emergencia_rechaza_a_quien_no_es_tecnico(self):
        o = OrdenTrabajo(equipo=self.equipo, descripcion='x')
        with self.assertRaises(ReglaError):
            ordenes.crear_emergencia(o, self.peticion(self.gerente))

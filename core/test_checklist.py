"""Pruebas de la fase 2, parte 1: checklist por equipo y mediciones de las órdenes de trabajo."""
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from core import checklists, incidencias, ordenes
from core.models import EquipoHVAC, HistorialMantenimiento, MedicionOT, OrdenTrabajo, PuntoChecklistOT
from core.ordenes import ReglaError
from core.test_ordenes import OrdenesBase

MSG_MATERIALES = 'Materiales: marca SIN MATERIALES o registra al menos un material.'
MSG_OBS_SIN = 'Las observaciones técnicas son obligatorias: OT sin checklist.'
MSG_OBS_INC = 'Las observaciones técnicas son obligatorias: hay incidencias en el checklist.'


class ChecklistBase(OrdenesBase):
    def en_ejecucion(self, tipo='SPLIT', gas=False, con_checklist=True, evidencias=False):
        """Orden Asignada a `self.tec` sobre un equipo de ese tipo, ya iniciada por el servicio.

        Por defecto no exige fotos ni firma, para que las pruebas del checklist no dependan de ellas."""
        self.equipo.tipo = tipo
        self.equipo.save()
        o = OrdenTrabajo.objects.create(equipo=self.equipo, descripcion='Revisión', estado=OrdenTrabajo.ASIGNADA,
                                        tecnico=self.tec, requiere_refrigerante=gas, creado_por=self.gerente,
                                        con_checklist=con_checklist)
        ordenes.iniciar(o, self.peticion(self.tec))
        if o.con_evidencias != evidencias:
            o.con_evidencias = evidencias
            o.save()
        return o


class ModeloChecklistTests(ChecklistBase):
    def test_orden_nueva_tiene_con_checklist_pero_no_checklist_hasta_iniciar(self):
        o = self.orden()
        self.assertTrue(o.con_checklist)
        self.assertFalse(o.tiene_checklist)

    def test_tiene_checklist_con_filas_y_no_si_se_creo_sin_checklist(self):
        o = self.orden()
        PuntoChecklistOT.objects.create(orden=o, codigo='X', bloque='INSPECCION', texto='x')
        self.assertTrue(o.tiene_checklist)
        o.con_checklist = False
        self.assertFalse(o.tiene_checklist)

    def test_punto_y_medicion_son_unicos_por_orden_y_codigo(self):
        o = self.orden()
        PuntoChecklistOT.objects.create(orden=o, codigo='X', bloque='INSPECCION', texto='x')
        MedicionOT.objects.create(orden=o, codigo='M', etiqueta='m', unidad='V')
        with self.assertRaises(IntegrityError), transaction.atomic():
            PuntoChecklistOT.objects.create(orden=o, codigo='X', bloque='INSPECCION', texto='otra')
        with self.assertRaises(IntegrityError), transaction.atomic():
            MedicionOT.objects.create(orden=o, codigo='M', etiqueta='m', unidad='V')

    def test_punto_completo_exige_gravedad_si_hay_incidencia(self):
        p = PuntoChecklistOT(codigo='X', bloque='INSPECCION', texto='x')
        self.assertFalse(p.completo)
        p.resultado = 'OK'
        self.assertTrue(p.completo)
        p.resultado = 'INCIDENCIA'
        self.assertFalse(p.completo)
        p.gravedad = 'LEVE'
        self.assertTrue(p.completo)


class CatalogoTests(SimpleTestCase):
    def test_las_cinco_comprobaciones_de_arranque_estan_en_todos_los_tipos(self):
        for tipo, _ in EquipoHVAC.TIPO_CHOICES:
            puntos = checklists.puntos_para(tipo, False)
            codigos = {p.codigo for p in puntos}
            self.assertTrue(set(checklists.CODIGOS_ARRANQUE) <= codigos, tipo)
            for p in puntos:
                if p.codigo in checklists.CODIGOS_ARRANQUE:
                    self.assertEqual(p.bloque, checklists.FUNCIONAMIENTO)

    def test_bloque_refrigerante_solo_si_la_orden_lo_requiere(self):
        for tipo, _ in EquipoHVAC.TIPO_CHOICES:
            self.assertFalse([p for p in checklists.puntos_para(tipo, False) if p.bloque == checklists.REFRIGERANTE])
            self.assertGreaterEqual(
                len([p for p in checklists.puntos_para(tipo, True) if p.bloque == checklists.REFRIGERANTE]), 2)

    def test_codigos_unicos_dentro_de_cada_tipo(self):
        for tipo, _ in EquipoHVAC.TIPO_CHOICES:
            codigos = [p.codigo for p in checklists.puntos_para(tipo, True)]
            self.assertEqual(len(codigos), len(set(codigos)), tipo)

    def test_mediciones_base_siempre_y_presiones_salvo_uma(self):
        for tipo, _ in EquipoHVAC.TIPO_CHOICES:
            codigos = {m.codigo for m in checklists.mediciones_para(tipo)}
            self.assertTrue({'TEMP_IMPULSION', 'TEMP_RETORNO', 'TENSION', 'CORRIENTE'} <= codigos, tipo)
            self.assertEqual('PRESION_ALTA' in codigos and 'PRESION_BAJA' in codigos, tipo != 'UMA', tipo)

    def test_tipo_desconocido_usa_otro(self):
        self.assertEqual(checklists.puntos_para('XYZ', False), checklists.puntos_para('OTRO', False))


class GeneracionTests(ChecklistBase):
    def test_iniciar_genera_puntos_y_mediciones_del_tipo_del_equipo(self):
        o = self.en_ejecucion('CHILLER')
        codigos = set(o.puntos.values_list('codigo', flat=True))
        self.assertTrue(set(checklists.CODIGOS_ARRANQUE) <= codigos)
        self.assertEqual(o.mediciones.count(), 6)
        self.assertFalse(o.mediciones.exclude(valor=None).exists())
        self.assertFalse(o.mediciones.filter(obligatoria=False).exists())

    def test_refrigerante_solo_genera_su_bloque_si_la_orden_lo_requiere(self):
        self.assertGreaterEqual(self.en_ejecucion('SPLIT', gas=True).puntos.filter(bloque='REFRIGERANTE').count(), 2)
        self.assertEqual(self.en_ejecucion('SPLIT', gas=False).puntos.filter(bloque='REFRIGERANTE').count(), 0)

    def test_orden_sin_checklist_no_genera_filas(self):
        o = self.en_ejecucion(con_checklist=False)
        self.assertEqual(o.estado, OrdenTrabajo.EN_EJECUCION)
        self.assertEqual((o.puntos.count(), o.mediciones.count()), (0, 0))

    def test_generar_dos_veces_no_duplica_filas(self):
        o = self.en_ejecucion()
        total = o.puntos.count()
        self.assertEqual(ordenes.generar_checklist(o), (0, 0))
        self.assertEqual(o.puntos.count(), total)

    def test_cambiar_el_tipo_del_equipo_despues_no_altera_las_filas(self):
        o = self.en_ejecucion('CHILLER')
        antes = list(o.puntos.values_list('codigo', 'texto'))
        self.equipo.tipo = 'UMA'
        self.equipo.save()
        self.assertEqual(list(o.puntos.values_list('codigo', 'texto')), antes)

    def test_inicio_rechazado_por_certificado_no_genera_filas(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec_caducado, gas=True)
        with self.assertRaises(ReglaError):
            ordenes.iniciar(o, self.peticion(self.tec_caducado))
        self.assertEqual((o.puntos.count(), o.mediciones.count()), (0, 0))


class EdicionTests(ChecklistBase):
    def setUp(self):
        super().setUp()
        self.o = self.en_ejecucion('SPLIT')
        self.req = self.peticion(self.tec)

    def test_marcar_ok_y_marcar_incidencia_con_gravedad(self):
        p = ordenes.marcar_punto(self.o, 'ARR_SENAL', 'OK', '', '', self.req)
        self.assertEqual((p.resultado, p.gravedad), ('OK', ''))
        p = ordenes.marcar_punto(self.o, 'ARR_SENAL', 'INCIDENCIA', 'MEDIA', 'Ruido', self.req)
        self.assertEqual((p.resultado, p.gravedad, p.nota), ('INCIDENCIA', 'MEDIA', 'Ruido'))

    def test_incidencia_sin_gravedad_se_rechaza_y_no_guarda(self):
        with self.assertRaisesMessage(ReglaError, 'Indica la gravedad de la incidencia.'):
            ordenes.marcar_punto(self.o, 'ARR_SENAL', 'INCIDENCIA', '', '', self.req)
        self.assertEqual(self.o.puntos.get(codigo='ARR_SENAL').resultado, '')

    def test_volver_a_ok_limpia_gravedad_y_nota(self):
        ordenes.marcar_punto(self.o, 'ARR_SENAL', 'INCIDENCIA', 'ALTA', 'Fuga', self.req)
        p = ordenes.marcar_punto(self.o, 'ARR_SENAL', 'OK', '', '', self.req)
        self.assertEqual((p.gravedad, p.nota), ('', ''))

    def test_punto_desconocido(self):
        with self.assertRaisesMessage(ReglaError, 'Punto de checklist desconocido.'):
            ordenes.marcar_punto(self.o, 'NO_EXISTE', 'OK', '', '', self.req)

    def test_solo_el_tecnico_asignado_escribe(self):
        for usuario in (self.tec2, self.gerente):
            with self.assertRaisesMessage(ReglaError, 'Solo el técnico asignado puede hacer esto.'):
                ordenes.marcar_punto(self.o, 'ARR_SENAL', 'OK', '', '', self.peticion(usuario))
            with self.assertRaises(ReglaError):
                ordenes.registrar_medicion(self.o, 'TENSION', '230', self.peticion(usuario))

    def test_no_se_escribe_en_orden_pendiente_de_aprobacion(self):
        self.o.estado = OrdenTrabajo.PENDIENTE_APROBACION
        self.o.save()
        with self.assertRaises(ReglaError):
            ordenes.marcar_punto(self.o, 'ARR_SENAL', 'OK', '', '', self.req)
        with self.assertRaises(ReglaError):
            ordenes.registrar_medicion(self.o, 'TENSION', '230', self.req)
        self.assertEqual(self.o.puntos.get(codigo='ARR_SENAL').resultado, '')

    def test_medicion_acepta_coma_decimal(self):
        self.assertEqual(ordenes.registrar_medicion(self.o, 'TENSION', '230,5', self.req).valor, Decimal('230.50'))
        self.assertEqual(ordenes.registrar_medicion(self.o, 'TENSION', '12.5', self.req).valor, Decimal('12.50'))

    def test_medicion_rechaza_texto_nan_inf_y_fuera_de_rango(self):
        for codigo, valor in [('TEMP_IMPULSION', 'abc'), ('TEMP_IMPULSION', 'nan'), ('TEMP_IMPULSION', 'inf'),
                              ('TEMP_IMPULSION', '-80'), ('TENSION', '5000')]:
            with self.assertRaises(ReglaError, msg=(codigo, valor)):
                ordenes.registrar_medicion(self.o, codigo, valor, self.req)
            self.assertIsNone(self.o.mediciones.get(codigo=codigo).valor)

    def test_mensaje_de_numero_invalido(self):
        with self.assertRaisesMessage(ReglaError, 'Introduce un número válido (por ejemplo 12,5).'):
            ordenes.registrar_medicion(self.o, 'TENSION', 'abc', self.req)

    def test_valor_vacio_borra_la_medicion(self):
        ordenes.registrar_medicion(self.o, 'TENSION', '230', self.req)
        self.assertIsNone(ordenes.registrar_medicion(self.o, 'TENSION', '', self.req).valor)

    def test_elegir_mediciones_en_orden_sin_checklist_las_marca_obligatorias(self):
        o = self.en_ejecucion(con_checklist=False)
        ordenes.elegir_mediciones(o, ['TENSION', 'CORRIENTE'], self.req)
        self.assertEqual(set(o.mediciones.values_list('codigo', flat=True)), {'TENSION', 'CORRIENTE'})
        ordenes.registrar_medicion(o, 'TENSION', '230', self.req)
        ordenes.elegir_mediciones(o, ['TENSION', 'PRESION_ALTA'], self.req)
        self.assertEqual(set(o.mediciones.values_list('codigo', flat=True)), {'TENSION', 'PRESION_ALTA'})
        self.assertEqual(o.mediciones.get(codigo='TENSION').valor, Decimal('230.00'))
        self.assertTrue(o.mediciones.get(codigo='PRESION_ALTA').obligatoria)

    def test_elegir_mediciones_se_rechaza_si_la_orden_tiene_checklist(self):
        with self.assertRaisesMessage(ReglaError, 'Las mediciones se eligen solo en OT sin checklist.'):
            ordenes.elegir_mediciones(self.o, ['TENSION'], self.req)

    def test_subsanacion_en_bloque_mediciones_bloquea_el_checklist(self):
        self.o.subsanacion_motivo, self.o.subsanacion_bloque = 'Revisa', 'MEDICIONES'
        self.o.save()
        with self.assertRaisesMessage(ReglaError, 'Esta subsanación solo permite editar: Mediciones.'):
            ordenes.marcar_punto(self.o, 'ARR_SENAL', 'OK', '', '', self.req)
        self.assertEqual(ordenes.registrar_medicion(self.o, 'TENSION', '230', self.req).valor, Decimal('230.00'))


class EnvioTests(ChecklistBase):
    def setUp(self):
        super().setUp()
        self.o = self.en_ejecucion('SPLIT')
        self.req = self.peticion(self.tec)
        self.gerente_req = self.peticion(self.gerente)

    def _listo(self):
        """Checklist completo, observaciones y materiales resueltos."""
        self.completar_checklist(self.o)
        self.o.observaciones, self.o.sin_materiales = 'Todo correcto', True
        self.o.save()

    def _a_aprobacion(self):
        self._listo()
        ordenes.enviar(self.o, self.req)

    def test_envio_lista_exactamente_lo_que_falta(self):
        problemas = ordenes.validar_envio(self.o)
        for p in self.o.puntos.all():
            self.assertIn(f'Falta marcar: {p.texto}', problemas)
        self.assertIn('Falta medir: Temperatura de inyección', problemas)
        self.assertIn(MSG_MATERIALES, problemas)
        self.assertEqual(len(problemas), self.o.puntos.count() + self.o.mediciones.count() + 1)

    def test_incidencia_exige_observaciones_y_ok_no(self):
        self._listo()
        ordenes.marcar_punto(self.o, 'ARR_SENAL', 'INCIDENCIA', 'MEDIA', '', self.req)
        self.o.observaciones = ''
        self.o.save()
        self.assertEqual(ordenes.validar_envio(self.o), [MSG_OBS_INC])
        ordenes.marcar_punto(self.o, 'ARR_SENAL', 'OK', '', '', self.req)
        self.assertEqual(ordenes.validar_envio(self.o), [])

    def test_incidencia_sin_gravedad_figura_en_la_lista(self):
        self._listo()
        p = self.o.puntos.get(codigo='ARR_SENAL')
        p.resultado, p.gravedad = 'INCIDENCIA', ''
        p.save()
        self.assertIn(f'Falta indicar la gravedad de: {p.texto}', ordenes.validar_envio(self.o))

    def test_orden_sin_checklist_exige_observaciones_y_mediciones_elegidas(self):
        o = self.en_ejecucion(con_checklist=False)
        self.assertEqual(ordenes.validar_envio(o), [MSG_OBS_SIN, MSG_MATERIALES])
        ordenes.elegir_mediciones(o, ['TENSION'], self.req)
        self.assertEqual(ordenes.validar_envio(o), ['Falta medir: Tensión', MSG_OBS_SIN, MSG_MATERIALES])

    def test_orden_antigua_sin_filas_se_envia_con_observaciones_y_materiales(self):
        o = self.orden(OrdenTrabajo.EN_EJECUCION, self.tec)
        o.observaciones, o.sin_materiales = 'ok', True
        o.save()
        self.assertEqual(ordenes.validar_envio(o), [])
        ordenes.enviar(o, self.req)
        self.assertEqual(o.estado, OrdenTrabajo.PENDIENTE_APROBACION)

    def test_checklist_completo_se_envia(self):
        self._a_aprobacion()
        self.assertEqual(self.o.estado, OrdenTrabajo.PENDIENTE_APROBACION)

    def test_subsanacion_limita_la_edicion_al_bloque_indicado(self):
        self._a_aprobacion()
        ordenes.solicitar_subsanacion(self.o, 'Revisa mediciones', 'MEDICIONES', self.gerente_req)
        self.assertEqual((self.o.estado, self.o.subsanacion_bloque), (OrdenTrabajo.EN_EJECUCION, 'MEDICIONES'))
        with self.assertRaises(ReglaError):
            ordenes.guardar_ejecucion(self.o, 'cambiado', '', True, self.req)
        self.o.refresh_from_db()
        self.assertEqual(self.o.observaciones, 'Todo correcto')

    def test_subsanacion_con_bloque_invalido_se_rechaza(self):
        self._a_aprobacion()
        with self.assertRaises(ReglaError):
            ordenes.solicitar_subsanacion(self.o, 'Motivo', 'INVENTADO', self.gerente_req)

    def test_subsanacion_sin_bloque_permite_toda_la_orden(self):
        self._a_aprobacion()
        ordenes.solicitar_subsanacion(self.o, 'Motivo', '', self.gerente_req)
        ordenes.guardar_ejecucion(self.o, 'cambiado', '', True, self.req)
        self.o.refresh_from_db()
        self.assertEqual(self.o.observaciones, 'cambiado')

    def test_enviar_tras_subsanacion_limpia_motivo_y_bloque(self):
        self._a_aprobacion()
        ordenes.solicitar_subsanacion(self.o, 'Motivo', 'CHECKLIST', self.gerente_req)
        ordenes.enviar(self.o, self.req)
        self.assertEqual((self.o.subsanacion_motivo, self.o.subsanacion_bloque), ('', ''))

    def test_aprobar_incluye_resumen_de_checklist_y_mediciones_en_el_historial(self):
        self._listo()
        ordenes.marcar_punto(self.o, 'ARR_SENAL', 'INCIDENCIA', 'ALTA', 'Fuga', self.req)
        ordenes.enviar(self.o, self.req)
        punto = self.o.puntos.get(codigo='ARR_SENAL')
        incidencias.justificar(self.o, punto.id, 'Se asume el riesgo hasta la próxima visita', self.gerente_req)
        ordenes.aprobar(self.o, self.gerente_req)
        descripcion = HistorialMantenimiento.objects.get().descripcion
        self.assertIn('Checklist:', descripcion)
        self.assertIn('1 incidencias (Leve 0, Media 0, Alta 1)', descripcion)
        self.assertIn('Mediciones:', descripcion)
        self.assertIn('Tensión 10 V', descripcion)

    def test_subsanacion_por_formulario_guarda_el_bloque(self):
        self._a_aprobacion()
        self.client.force_login(self.gerente)
        self.post('orden_subsanacion', self.o, motivo='Revisa el checklist', bloque='CHECKLIST')
        self.o.refresh_from_db()
        self.assertEqual((self.o.estado, self.o.subsanacion_bloque), (OrdenTrabajo.EN_EJECUCION, 'CHECKLIST'))

    def test_enviar_con_subsanacion_en_checklist_no_revienta(self):
        self._a_aprobacion()
        ordenes.solicitar_subsanacion(self.o, 'Revisa', 'CHECKLIST', self.gerente_req)
        p = self.o.puntos.get(codigo='ARR_SENAL')
        p.resultado = ''
        p.save()
        self.client.force_login(self.tec)
        r = self.post('orden_enviar', self.o, observaciones='otra cosa', sin_materiales='on')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Falta marcar')


class AutoguardadoTests(ChecklistBase):
    def setUp(self):
        super().setUp()
        self.o = self.en_ejecucion('SPLIT')
        self.client.force_login(self.tec)

    def _json(self, nombre, *args, **datos):
        return self.client.post(reverse(nombre, args=[self.o.id, *args]), datos)

    def test_marcar_punto_responde_json_con_avance_y_faltantes(self):
        r = self._json('orden_punto', 'ARR_SENAL', resultado='OK')
        self.assertEqual(r.status_code, 200)
        datos = r.json()
        self.assertTrue(datos['ok'])
        self.assertEqual(datos['avance']['FUNCIONAMIENTO']['hechos'], 1)
        self.assertIsInstance(datos['faltan'], list)

    def test_valor_invalido_responde_400_con_el_mensaje(self):
        r = self._json('orden_medicion', 'TENSION', valor='abc')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {'ok': False, 'errores': ['Introduce un número válido (por ejemplo 12,5).']})

    def test_medicion_valida_responde_ok(self):
        r = self._json('orden_medicion', 'TENSION', valor='230,5')
        self.assertTrue(r.json()['ok'])
        self.assertEqual(self.o.mediciones.get(codigo='TENSION').valor, Decimal('230.50'))

    def test_orden_ajena_responde_404_y_get_405(self):
        self.client.force_login(self.tec2)
        self.assertEqual(self._json('orden_punto', 'ARR_SENAL', resultado='OK').status_code, 404)
        self.client.force_login(self.tec)
        self.assertEqual(self.client.get(reverse('orden_punto', args=[self.o.id, 'ARR_SENAL'])).status_code, 405)

    def test_gestor_no_puede_escribir(self):
        self.client.force_login(self.gerente)
        r = self._json('orden_punto', 'ARR_SENAL', resultado='OK')
        self.assertEqual(r.status_code, 400)
        self.assertIn('Solo el técnico asignado', r.json()['errores'][0])

    def test_guardar_observaciones_por_fetch_devuelve_json(self):
        r = self.client.post(reverse('orden_guardar', args=[self.o.id]), {'observaciones': 'x', 'sin_materiales': 'on'},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(r.json()['ok'])
        self.o.refresh_from_db()
        self.assertEqual(self.o.observaciones, 'x')

    def test_elegir_mediciones_por_post_redirige_al_detalle(self):
        o = self.en_ejecucion(con_checklist=False)
        r = self.client.post(reverse('orden_mediciones', args=[o.id]), {'codigos': ['TENSION', 'CORRIENTE']})
        self.assertRedirects(r, reverse('orden_detalle', args=[o.id]))
        self.assertEqual(set(o.mediciones.values_list('codigo', flat=True)), {'TENSION', 'CORRIENTE'})


class PantallaChecklistTests(ChecklistBase):
    def ver(self, orden, usuario, **params):
        self.client.force_login(usuario)
        return self.client.get(reverse('orden_detalle', args=[orden.id]), params)

    def test_tecnico_ve_bloques_botones_ok_incidencia_y_mediciones(self):
        o = self.en_ejecucion('SPLIT')
        r = self.ver(o, self.tec)
        self.assertContains(r, 'Funcionamiento')
        self.assertContains(r, 'Señal de arranque y contactor-compresor correctos')
        self.assertContains(r, 'data-resultado="INCIDENCIA"')
        self.assertContains(r, 'Temperatura de inyección')
        self.assertNotContains(r, 'No aplica')

    def test_orden_sin_checklist_muestra_indicador_y_selector_de_mediciones(self):
        o = self.en_ejecucion(con_checklist=False)
        r = self.ver(o, self.tec)
        self.assertContains(r, 'Sin checklist')
        self.assertContains(r, 'Mediciones necesarias')

    def test_orden_antigua_sin_filas_se_muestra_sin_errores(self):
        o = self.orden(OrdenTrabajo.EN_EJECUCION, self.tec)
        o.inicio = timezone.now()
        o.save()
        r = self.ver(o, self.tec)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Sin checklist')

    def test_gestion_ve_resumen_con_incidencias_resaltadas_en_pendiente_de_aprobacion(self):
        o = self.en_ejecucion('SPLIT')
        ordenes.marcar_punto(o, 'ARR_SENAL', 'INCIDENCIA', 'ALTA', 'Fuga de aceite', self.peticion(self.tec))
        o.estado = OrdenTrabajo.PENDIENTE_APROBACION
        o.save()
        r = self.ver(o, self.gerente)
        self.assertContains(r, 'Señal de arranque y contactor-compresor correctos')
        self.assertContains(r, 'Incidencia · Alta')
        self.assertContains(r, 'Fuga de aceite')
        self.assertNotContains(r, 'data-resultado')

    def test_orden_finalizada_y_cancelada_no_ofrecen_edicion(self):
        o = self.en_ejecucion('SPLIT')
        for estado in (OrdenTrabajo.FINALIZADA, OrdenTrabajo.CANCELADA):
            o.estado = estado
            o.save()
            for usuario in (self.tec, self.gerente):
                self.assertNotContains(self.ver(o, usuario), 'data-autoguardado')

    def test_subsanacion_en_bloque_solo_deja_editable_ese_bloque(self):
        o = self.en_ejecucion('SPLIT')
        o.subsanacion_motivo, o.subsanacion_bloque = 'Corrige', 'OBSERVACIONES'
        o.save()
        r = self.ver(o, self.tec)
        self.assertNotContains(r, 'data-resultado')
        self.assertNotContains(r, 'data-valor')

    def test_revisar_checklist_muestra_resumen_y_lo_que_falta(self):
        o = self.en_ejecucion('SPLIT')
        r = self.ver(o, self.tec, revisar='1')
        self.assertContains(r, 'Revisión del checklist')
        self.assertContains(r, 'Falta marcar')

    def test_detalle_se_muestra_para_cada_estado_y_rol_con_checklist(self):
        for estado, _ in OrdenTrabajo.ESTADO_CHOICES:
            o = self.orden(estado, self.tec)
            ordenes.generar_checklist(o)
            for usuario in (self.admin, self.gerente, self.tec):
                self.assertEqual(self.ver(o, usuario).status_code, 200, (estado, usuario))


class AltaYListadoTests(ChecklistBase):
    def test_orden_correctiva_se_crea_sin_checklist(self):
        self.client.force_login(self.gerente)
        self.client.post(reverse('orden_crear'), self.datos(tipo='CORRECTIVO', sin_checklist='on'))
        self.assertFalse(OrdenTrabajo.objects.get().con_checklist)

    def test_orden_preventiva_no_puede_crearse_sin_checklist(self):
        self.client.force_login(self.gerente)
        r = self.client.post(reverse('orden_crear'), self.datos(sin_checklist='on'))
        self.assertContains(r, 'Solo las órdenes correctivas pueden crearse sin checklist.')
        self.assertEqual(OrdenTrabajo.objects.count(), 0)

    def test_alta_sin_marcar_nada_crea_orden_con_checklist(self):
        self.client.force_login(self.gerente)
        self.client.post(reverse('orden_crear'), self.datos(tipo='CORRECTIVO'))
        self.assertTrue(OrdenTrabajo.objects.get().con_checklist)

    def test_listado_muestra_sin_checklist_y_numero_de_incidencias(self):
        self.en_ejecucion(con_checklist=False)
        o = self.en_ejecucion('SPLIT')
        ordenes.marcar_punto(o, 'ARR_SENAL', 'INCIDENCIA', 'LEVE', '', self.peticion(self.tec))
        self.client.force_login(self.gerente)
        r = self.client.get(reverse('ordenes'))
        self.assertContains(r, 'Sin checklist')
        self.assertContains(r, '1 incidencia')

    def test_tecnico_no_ve_incidencias_de_ordenes_ajenas(self):
        o = self.en_ejecucion('SPLIT')
        ordenes.marcar_punto(o, 'ARR_SENAL', 'INCIDENCIA', 'LEVE', '', self.peticion(self.tec))
        self.client.force_login(self.tec2)
        r = self.client.get(reverse('ordenes'))
        self.assertNotContains(r, '1 incidencia')


class LimitesYEtiquetasTests(ChecklistBase):
    def test_etiquetas_y_topes_de_las_mediciones(self):
        from core import checklists
        m = checklists.MEDICIONES
        self.assertEqual(m['TEMP_IMPULSION'].etiqueta, 'Temperatura de inyección')
        self.assertEqual(m['VELOCIDAD_AIRE'].unidad, 'm/s')
        topes = {'TEMP_IMPULSION': 60, 'TEMP_RETORNO': 60, 'TENSION': 480, 'CORRIENTE': 300,
                 'PRESION_ALTA': 45, 'PRESION_BAJA': 20, 'VELOCIDAD_AIRE': 20}
        for codigo, tope in topes.items():
            self.assertEqual(m[codigo].maximo, tope, codigo)

    def test_velocidad_de_aire_solo_es_opcional(self):
        from core import checklists
        base = [d.codigo for d in checklists.mediciones_para('SPLIT')]
        self.assertNotIn('VELOCIDAD_AIRE', base)

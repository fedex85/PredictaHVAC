"""Especificación de flujo de OT (tanda 1): OT sin checklist con evidencias, estado de llegada, notas
administrativas, OT de continuación y aprobación automática."""
import json
from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core import ordenes
from core.models import EventoOT, NotaAdministrativa, OrdenTrabajo
from core.ordenes import ReglaError
from core.test_ordenes import OrdenesBase
from core.test_sin_conexion import SincronizacionBase


class SinChecklistEvidenciasTests(OrdenesBase):
    def iniciada_sin_checklist(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        o.con_checklist = False
        o.save()
        ordenes.iniciar(o, self.peticion(self.tec), llegada=('NORMAL', ''))
        o.refresh_from_db()
        return o

    def test_iniciar_una_ot_sin_checklist_exige_fotos_y_firmas(self):
        o = self.iniciada_sin_checklist()
        self.assertTrue(o.con_evidencias)
        self.assertFalse(o.puntos.exists())

    def test_envio_sin_checklist_lista_fotos_y_las_dos_firmas(self):
        o = self.iniciada_sin_checklist()
        problemas = ordenes.validar_envio(o)
        self.assertIn('Faltan 3 fotografías', problemas)
        self.assertIn('Falta la firma del cliente', problemas)
        self.assertIn('Falta la firma del técnico', problemas)
        self.assertIn('Las observaciones técnicas son obligatorias: OT sin checklist.', problemas)

    def test_flujo_completo_sin_checklist_se_puede_enviar(self):
        o = self.iniciada_sin_checklist()
        o.observaciones, o.sin_materiales = 'Cambio de fusible', True
        o.save()
        self.completar_evidencias(o)
        self.assertEqual(ordenes.validar_envio(o), [])
        ordenes.enviar(o, self.peticion(self.tec))
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.PENDIENTE_APROBACION)


class LlegadaTests(OrdenesBase):
    def iniciar(self, o, **datos):
        self.client.force_login(self.tec)
        datos.setdefault('equipo_codigo', 'CH-001')
        return self.post('orden_iniciar', o, **datos)

    def test_sin_estado_de_llegada_no_se_inicia(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        r = self.iniciar(o)
        self.assertContains(r, 'Indica el estado en el que encuentras el equipo')
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.ASIGNADA)

    def test_estado_desconocido_no_se_acepta(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        self.iniciar(o, llegada='EN_RUTA')
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.ASIGNADA)

    def test_otro_exige_texto(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        r = self.iniciar(o, llegada='OTRO', llegada_texto='  ')
        self.assertContains(r, 'Describe el estado de llegada')
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.ASIGNADA)

    def test_llegada_valida_se_guarda_deja_evento_y_se_muestra(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        r = self.iniciar(o, llegada='OTRO', llegada_texto='Olor a quemado')
        o.refresh_from_db()
        self.assertEqual((o.estado, o.llegada, o.llegada_texto), (OrdenTrabajo.EN_EJECUCION, 'OTRO', 'Olor a quemado'))
        self.assertTrue(EventoOT.objects.filter(orden=o, texto__contains='Estado de llegada: Otro: Olor a quemado').exists())
        self.assertContains(r, 'Otro: Olor a quemado')

    def test_el_texto_se_descarta_si_no_es_otro(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        self.iniciar(o, llegada='FUGA', llegada_texto='ignorar')
        o.refresh_from_db()
        self.assertEqual((o.llegada, o.llegada_texto), ('FUGA', ''))

    def test_certificado_se_comprueba_antes_que_la_llegada(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec_caducado, gas=True)
        with self.assertRaises(ReglaError) as cm:
            ordenes.iniciar(o, self.peticion(self.tec_caducado), llegada=('', ''))
        self.assertIn('No se puede iniciar la intervención', str(cm.exception))


class LlegadaSinConexionTests(SincronizacionBase):
    def test_el_paquete_con_llegada_la_guarda(self):
        o = self.preparar()
        r = self.enviar(o, self.paquete(llegada={'estado': 'NO_ARRANCA', 'texto': ''}), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.llegada, 'NO_ARRANCA')

    def test_paquete_con_llegada_invalida_se_rechaza_sin_iniciar(self):
        o = self.preparar()
        r = self.enviar(o, self.paquete(llegada={'estado': 'ZZZ', 'texto': ''}), usuario=self.tec)
        self.assertGreaterEqual(r.status_code, 400)
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.ASIGNADA)

    def test_paquete_con_llegada_que_no_es_objeto_se_rechaza(self):
        o = self.preparar()
        r = self.enviar(o, self.paquete(llegada='NORMAL'), usuario=self.tec)
        self.assertEqual(r.status_code, 400)

    def test_paquete_antiguo_sin_llegada_sigue_aceptandose(self):
        o = self.preparar()
        r = self.enviar(o, self.paquete(), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual((o.estado, o.llegada), (OrdenTrabajo.EN_EJECUCION, ''))

    def test_el_paquete_descargado_marca_evidencias_tambien_sin_checklist(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        o.con_checklist = False
        o.save()
        self.client.force_login(self.tec)
        r = self.client.post(reverse('orden_descargar', args=[o.id]))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(json.loads(r.content)['paquete']['orden']['con_evidencias'])


class NotasAdministrativasTests(OrdenesBase):
    def test_gestion_anade_nota_a_una_finalizada(self):
        o = self.orden(OrdenTrabajo.FINALIZADA, self.tec)
        self.client.force_login(self.gerente)
        r = self.post('orden_nota', o, texto='Cliente avisó de la factura')
        self.assertContains(r, 'Cliente avisó de la factura')
        n = NotaAdministrativa.objects.get()
        self.assertEqual((n.orden, n.usuario_nombre), (o, 'Gerente'))
        self.assertTrue(EventoOT.objects.filter(orden=o, texto='Nota administrativa añadida').exists())

    def test_tambien_a_una_cancelada(self):
        o = self.orden(OrdenTrabajo.CANCELADA, self.tec)
        ordenes.añadir_nota(o, 'Nota', self.peticion(self.admin))
        self.assertEqual(o.notas_admin.count(), 1)

    def test_no_se_admite_en_una_orden_abierta(self):
        o = self.orden(OrdenTrabajo.EN_EJECUCION, self.tec)
        with self.assertRaises(ReglaError):
            ordenes.añadir_nota(o, 'Nota', self.peticion(self.gerente))

    def test_el_tecnico_no_puede_anadir_notas(self):
        o = self.orden(OrdenTrabajo.FINALIZADA, self.tec)
        self.client.force_login(self.tec)
        self.post('orden_nota', o, texto='Intento')
        self.assertEqual(NotaAdministrativa.objects.count(), 0)

    def test_nota_vacia_se_rechaza(self):
        o = self.orden(OrdenTrabajo.FINALIZADA, self.tec)
        self.client.force_login(self.gerente)
        self.post('orden_nota', o, texto='   ')
        self.assertEqual(NotaAdministrativa.objects.count(), 0)

    def test_el_tecnico_no_ve_las_notas(self):
        o = self.orden(OrdenTrabajo.FINALIZADA, self.tec)
        ordenes.añadir_nota(o, 'Texto interno de gestión', self.peticion(self.gerente))
        self.client.force_login(self.tec)
        r = self.client.get(reverse('orden_detalle', args=[o.id]))
        self.assertNotContains(r, 'Texto interno de gestión')

    def test_la_nota_no_cambia_los_datos_tecnicos(self):
        o = self.orden(OrdenTrabajo.FINALIZADA, self.tec)
        o.observaciones = 'Original'
        o.save()
        ordenes.añadir_nota(o, 'Nota', self.peticion(self.gerente))
        o.refresh_from_db()
        self.assertEqual((o.estado, o.observaciones), (OrdenTrabajo.FINALIZADA, 'Original'))


class ContinuacionTests(OrdenesBase):
    def original(self):
        o = self.orden(OrdenTrabajo.FINALIZADA, self.tec)
        o.con_checklist = False
        o.observaciones = 'Compresor no arranca; falta pieza'
        o.save()
        return o

    def test_el_formulario_propone_los_datos_de_la_original(self):
        o = self.original()
        self.client.force_login(self.gerente)
        r = self.client.get(reverse('orden_crear') + f'?continuacion={o.id}')
        self.assertContains(r, f'Continuación de {o.codigo}')
        self.assertEqual(r.context['form'].initial['equipo'], self.equipo.id)

    def test_la_nueva_nace_vinculada_con_antecedente_del_servidor(self):
        o = self.original()
        self.client.force_login(self.gerente)
        r = self.client.post(reverse('orden_crear'), self.datos(continuacion=o.id, tipo='CORRECTIVO',
                                                                 antecedente='FALSIFICADO'), follow=True)
        nueva = OrdenTrabajo.objects.exclude(pk=o.pk).get()
        self.assertEqual(nueva.continuacion_de, o)
        self.assertEqual(nueva.estado, OrdenTrabajo.PENDIENTE)
        self.assertIn('Compresor no arranca; falta pieza', nueva.antecedente)
        self.assertNotIn('FALSIFICADO', nueva.antecedente)
        self.assertContains(r, f'OT #{o.pk}')
        self.assertContains(r, 'Antecedente (bloqueado)')

    def test_la_original_no_muestra_la_relacion(self):
        o = self.original()
        self.client.force_login(self.gerente)
        self.client.post(reverse('orden_crear'), self.datos(continuacion=o.id, tipo='CORRECTIVO'))
        r = self.client.get(reverse('orden_detalle', args=[o.id]))
        self.assertNotContains(r, 'Antecedente (bloqueado)')

    def test_continuacion_inexistente_se_ignora(self):
        self.client.force_login(self.gerente)
        self.client.post(reverse('orden_crear'), self.datos(continuacion=99999))
        n = OrdenTrabajo.objects.get()
        self.assertIsNone(n.continuacion_de)

    def test_el_tecnico_no_puede_crear_continuaciones(self):
        o = self.original()
        self.client.force_login(self.tec)
        r = self.client.get(reverse('orden_crear') + f'?continuacion={o.id}')
        self.assertNotEqual(r.status_code, 200)

    def test_el_boton_aparece_solo_en_ordenes_cerradas_para_gestion(self):
        o = self.original()
        self.client.force_login(self.gerente)
        self.assertContains(self.client.get(reverse('orden_detalle', args=[o.id])), 'Crear OT de continuación')
        abierta = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        self.assertNotContains(self.client.get(reverse('orden_detalle', args=[abierta.id])), 'Crear OT de continuación')


class AprobacionAutomaticaTests(OrdenesBase):
    def lista_para_enviar(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        o.con_checklist = False
        o.save()
        ordenes.iniciar(o, self.peticion(self.tec), llegada=('NORMAL', ''))
        o.refresh_from_db()
        o.observaciones, o.sin_materiales = 'Hecho', True
        o.save()
        self.completar_evidencias(o)
        return o

    def test_por_defecto_la_orden_espera_al_gerente(self):
        o = self.lista_para_enviar()
        ordenes.enviar(o, self.peticion(self.tec))
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.PENDIENTE_APROBACION)

    @override_settings(APROBACION_AUTOMATICA=True)
    def test_con_aprobacion_automatica_se_finaliza_y_queda_registrada(self):
        o = self.lista_para_enviar()
        ordenes.enviar(o, self.peticion(self.tec))
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.FINALIZADA)
        self.assertIsNotNone(o.fin)
        self.assertIsNotNone(o.mantenimiento)
        self.assertIn('Estado de llegada: Normal', o.mantenimiento.descripcion)
        self.assertTrue(EventoOT.objects.filter(orden=o, texto__startswith='Aprobada automáticamente').exists())

    @override_settings(APROBACION_AUTOMATICA=True)
    def test_con_incidencia_alta_sin_resolver_no_se_aprueba_sola(self):
        from unittest import mock
        o = self.lista_para_enviar()
        with mock.patch('core.incidencias.pendientes_alta', return_value=[object()]):
            ordenes.enviar(o, self.peticion(self.tec))
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.PENDIENTE_APROBACION)

    @override_settings(APROBACION_AUTOMATICA=True)
    def test_si_no_se_puede_enviar_no_se_aprueba(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        ordenes.iniciar(o, self.peticion(self.tec), llegada=('NORMAL', ''))
        with self.assertRaises(ReglaError):
            ordenes.enviar(o, self.peticion(self.tec))
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.EN_EJECUCION)

"""Plan de mantenimiento preventivo: fechas, estados, generación de órdenes, pantalla y comando."""
from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase
from django.urls import reverse

from core import preventivos
from core.forms import EquipoHVACEditForm, EquipoHVACForm
from core.models import EquipoHVAC, EventoOT, HistorialMantenimiento, OrdenTrabajo, RegistroActividad
from core.test_ordenes import OrdenesBase

HOY = date(2026, 10, 13)


class FechasTests(SimpleTestCase):
    def test_sumar_meses_ajusta_el_dia_al_ultimo_del_mes(self):
        self.assertEqual(preventivos.sumar_meses(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(preventivos.sumar_meses(date(2024, 1, 31), 1), date(2024, 2, 29))
        self.assertEqual(preventivos.sumar_meses(date(2026, 8, 31), 6), date(2027, 2, 28))

    def test_sumar_meses_cruza_el_anio(self):
        self.assertEqual(preventivos.sumar_meses(date(2026, 11, 15), 3), date(2027, 2, 15))
        self.assertEqual(preventivos.sumar_meses(date(2026, 12, 1), 1), date(2027, 1, 1))
        self.assertEqual(preventivos.sumar_meses(date(2026, 3, 10), 12), date(2027, 3, 10))


class PlanBase(OrdenesBase):
    def setUp(self):
        super().setUp()
        self.equipo.periodicidad_meses = 6
        self.equipo.save()

    def mant(self, fecha, tipo='PREVENTIVO', equipo=None):
        return HistorialMantenimiento.objects.create(equipo=equipo or self.equipo, tipo_mantenimiento=tipo,
                                                     descripcion='x', fecha_mantenimiento=fecha, tecnico_responsable='T')

    def preventiva(self, estado, fecha=None, equipo=None):
        return OrdenTrabajo.objects.create(equipo=equipo or self.equipo, tipo='PREVENTIVO', descripcion='p', estado=estado,
                                           fecha_programada=fecha, creado_por=self.gerente)

    def sit(self, equipo=None):
        return preventivos.situacion(equipo or EquipoHVAC.objects.get(pk=self.equipo.pk), HOY)


class ProximoTests(PlanBase):
    def test_sin_periodicidad_no_hay_plan(self):
        self.equipo.periodicidad_meses = None
        self.equipo.save()
        s = self.sit()
        self.assertEqual((s['estado'], s['proximo'], s['toca']), (preventivos.SIN_PLAN, None, False))

    def test_se_cuenta_desde_el_ultimo_preventivo(self):
        self.mant(date(2026, 4, 20))
        self.assertEqual(self.sit()['proximo'], date(2026, 10, 20))

    def test_un_correctivo_no_cuenta_como_preventivo(self):
        self.mant(date(2026, 9, 1), tipo='CORRECTIVO')
        self.mant(date(2026, 3, 1))
        self.assertEqual(self.sit()['ultimo'], date(2026, 3, 1))

    def test_sin_historial_se_cuenta_desde_la_instalacion(self):
        self.equipo.fecha_instalacion = date(2026, 5, 1)
        self.equipo.save()
        self.assertEqual(self.sit()['proximo'], date(2026, 11, 1))

    def test_sin_historial_ni_instalacion_toca_hoy(self):
        s = self.sit()
        self.assertEqual((s['proximo'], s['estado'], s['toca']), (HOY, preventivos.PROXIMO, True))


class EstadoTests(PlanBase):
    def con_ultimo(self, proximo):
        self.mant(preventivos.sumar_meses(proximo, -6))

    def test_vencido(self):
        self.con_ultimo(HOY - timedelta(days=1))
        s = self.sit()
        self.assertEqual((s['estado'], s['toca']), (preventivos.VENCIDO, True))

    def test_proximo_justo_en_el_limite_de_la_ventana(self):
        self.con_ultimo(HOY + timedelta(days=15))
        self.assertEqual(self.sit()['estado'], preventivos.PROXIMO)

    def test_un_dia_fuera_de_la_ventana_esta_al_dia(self):
        self.con_ultimo(HOY + timedelta(days=16))
        s = self.sit()
        self.assertEqual((s['estado'], s['toca']), (preventivos.AL_DIA, False))

    def test_con_orden_preventiva_abierta_no_toca(self):
        self.con_ultimo(HOY - timedelta(days=5))
        o = self.preventiva(OrdenTrabajo.ASIGNADA)
        s = self.sit()
        self.assertEqual((s['estado'], s['abierta'], s['toca']), (preventivos.ABIERTA, o, False))

    def test_una_correctiva_abierta_no_impide_el_preventivo(self):
        self.con_ultimo(HOY - timedelta(days=5))
        OrdenTrabajo.objects.create(equipo=self.equipo, tipo='CORRECTIVO', descripcion='c', estado=OrdenTrabajo.PENDIENTE,
                                    creado_por=self.gerente)
        self.assertTrue(self.sit()['toca'])

    def test_orden_cancelada_para_esa_fecha_se_respeta(self):
        self.con_ultimo(HOY - timedelta(days=5))
        self.preventiva(OrdenTrabajo.CANCELADA, fecha=HOY - timedelta(days=5))
        s = self.sit()
        self.assertEqual((s['estado'], s['toca']), (preventivos.CANCELADA, False))

    def test_orden_cancelada_de_otra_fecha_no_bloquea(self):
        self.con_ultimo(HOY - timedelta(days=5))
        self.preventiva(OrdenTrabajo.CANCELADA, fecha=HOY - timedelta(days=200))
        self.assertTrue(self.sit()['toca'])

    def test_equipo_fuera_de_servicio_no_toca(self):
        self.con_ultimo(HOY - timedelta(days=5))
        self.equipo.estado = 'FUERA_SERVICIO'
        self.equipo.save()
        s = self.sit()
        self.assertEqual((s['estado'], s['toca']), (preventivos.FUERA_SERVICIO, False))


class GenerarTests(PlanBase):
    def setUp(self):
        super().setUp()
        self.mant(date(2026, 4, 1))   # próximo: 01/10/2026, vencido a 13/10

    def test_crea_una_orden_pendiente_sin_tecnico_con_la_fecha_que_toca(self):
        creadas = preventivos.generar(HOY, usuario=self.gerente)
        self.assertEqual([(e.pk, f) for e, f in creadas], [(self.equipo.pk, date(2026, 10, 1))])
        o = OrdenTrabajo.objects.get()
        self.assertEqual((o.tipo, o.estado, o.tecnico, o.fecha_programada, o.creado_por),
                         ('PREVENTIVO', OrdenTrabajo.PENDIENTE, None, date(2026, 10, 1), self.gerente))
        self.assertFalse(o.requiere_refrigerante)
        self.assertIn('cada 6 meses', o.descripcion)
        self.assertEqual(EventoOT.objects.get(orden=o).texto, 'Generada por el plan preventivo del equipo')

    def test_es_idempotente(self):
        preventivos.generar(HOY, usuario=self.gerente)
        self.assertEqual(preventivos.generar(HOY, usuario=self.gerente), [])
        self.assertEqual(OrdenTrabajo.objects.count(), 1)

    def test_simular_no_crea_nada(self):
        self.assertEqual(len(preventivos.generar(HOY, simular=True)), 1)
        self.assertEqual(OrdenTrabajo.objects.count(), 0)

    def test_ejecucion_automatica_queda_como_sistema(self):
        preventivos.generar(HOY)
        o = OrdenTrabajo.objects.get()
        self.assertIsNone(o.creado_por)
        self.assertEqual(EventoOT.objects.get(orden=o).usuario_nombre, 'Sistema')
        self.assertEqual(RegistroActividad.objects.get(accion=RegistroActividad.ORDEN_CREADA).usuario_nombre, 'Sistema')

    def test_solo_equipos_con_plan_y_que_tocan(self):
        EquipoHVAC.objects.create(nombre='Sin plan', codigo_identificador='SP-1', ubicacion='x')
        otro = EquipoHVAC.objects.create(nombre='Al día', codigo_identificador='AD-1', ubicacion='x', periodicidad_meses=12)
        self.mant(HOY - timedelta(days=10), equipo=otro)
        preventivos.generar(HOY)
        self.assertEqual(list(OrdenTrabajo.objects.values_list('equipo_id', flat=True)), [self.equipo.pk])

    def test_al_finalizar_la_orden_el_siguiente_se_cuenta_desde_ese_mantenimiento(self):
        preventivos.generar(HOY)
        orden = OrdenTrabajo.objects.get()
        orden.mantenimiento = self.mant(HOY)
        orden.estado = OrdenTrabajo.FINALIZADA
        orden.save()
        s = preventivos.situacion(EquipoHVAC.objects.get(pk=self.equipo.pk), HOY)
        self.assertEqual((s['proximo'], s['estado']), (date(2027, 4, 13), preventivos.AL_DIA))


class PantallaTests(PlanBase):
    def setUp(self):
        super().setUp()
        self.mant(date(2026, 4, 1))

    def test_la_pantalla_lista_los_equipos_con_plan(self):
        self.client.force_login(self.gerente)
        r = self.client.get(reverse('preventivos'))
        self.assertContains(r, f'data-equipo="{self.equipo.id}"')
        self.assertContains(r, 'Generar órdenes pendientes')

    def test_el_boton_esta_desactivado_si_no_hay_nada_que_generar(self):
        self.equipo.periodicidad_meses = None
        self.equipo.save()
        self.client.force_login(self.gerente)
        r = self.client.get(reverse('preventivos'))
        self.assertContains(r, 'disabled')
        self.assertContains(r, 'id="motivo-desactivado"')   # el usuario ve por qué no puede pulsarlo

    def test_con_equipos_al_dia_el_motivo_lo_explica(self):
        self.mant(date.today())   # recién hecho: no toca
        self.client.force_login(self.gerente)
        self.assertContains(self.client.get(reverse('preventivos')), 'están al día')

    def test_generar_crea_las_ordenes_y_avisa(self):
        self.client.force_login(self.gerente)
        r = self.client.post(reverse('preventivos_generar'), follow=True)
        self.assertEqual(OrdenTrabajo.objects.filter(tipo='PREVENTIVO', estado=OrdenTrabajo.PENDIENTE).count(), 1)
        self.assertContains(r, 'Se crearon 1 orden')

    def test_generar_dos_veces_no_duplica(self):
        self.client.force_login(self.gerente)
        self.client.post(reverse('preventivos_generar'))
        r = self.client.post(reverse('preventivos_generar'), follow=True)
        self.assertEqual(OrdenTrabajo.objects.count(), 1)
        self.assertContains(r, 'No hay preventivos por generar')

    def test_solo_gestion_y_con_sesion(self):
        self.client.force_login(self.tec)
        self.assertEqual(self.client.get(reverse('preventivos')).status_code, 403)
        self.assertEqual(self.client.post(reverse('preventivos_generar')).status_code, 403)
        self.assertEqual(OrdenTrabajo.objects.count(), 0)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('preventivos')).status_code, 302)
        self.assertEqual(self.client.post(reverse('preventivos_generar')).status_code, 302)

    def test_generar_no_acepta_get(self):
        self.client.force_login(self.gerente)
        self.assertEqual(self.client.get(reverse('preventivos_generar')).status_code, 405)

    def test_enlace_desde_ordenes_solo_para_gestion(self):
        self.client.force_login(self.gerente)
        self.assertContains(self.client.get(reverse('ordenes')), reverse('preventivos'))
        self.client.force_login(self.tec)
        self.assertNotContains(self.client.get(reverse('ordenes')), reverse('preventivos'))

    def test_la_orden_generada_aparece_en_el_calendario(self):
        preventivos_ordenes = preventivos.generar(HOY, usuario=self.gerente)
        self.assertEqual(len(preventivos_ordenes), 1)
        o = OrdenTrabajo.objects.get()
        self.client.force_login(self.gerente)
        self.assertContains(self.client.get(reverse('calendario'), {'mes': '2026-10'}), f'data-chip-orden="{o.id}"')


class ComandoTests(PlanBase):
    def setUp(self):
        super().setUp()
        self.mant(date(2025, 1, 1))   # muy vencido

    def test_dry_run_lista_sin_crear(self):
        salida = StringIO()
        call_command('generar_preventivos', '--dry-run', stdout=salida)
        self.assertIn('Se crearían 1', salida.getvalue())
        self.assertEqual(OrdenTrabajo.objects.count(), 0)

    def test_el_comando_crea_y_es_idempotente(self):
        call_command('generar_preventivos', stdout=StringIO())
        salida = StringIO()
        call_command('generar_preventivos', stdout=salida)
        self.assertEqual(OrdenTrabajo.objects.count(), 1)
        self.assertIn('Creadas 0', salida.getvalue())


class FormularioTests(OrdenesBase):
    BASE = {'nombre': 'Split', 'codigo_identificador': 'SP-9', 'tipo': 'SPLIT', 'ubicacion': 'Oficina'}

    def test_se_guarda_la_periodicidad(self):
        f = EquipoHVACForm({**self.BASE, 'periodicidad_meses': '3'})
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.save().periodicidad_meses, 3)

    def test_sin_plan_es_valido(self):
        f = EquipoHVACForm({**self.BASE, 'periodicidad_meses': ''})
        self.assertTrue(f.is_valid(), f.errors)
        self.assertIsNone(f.save().periodicidad_meses)

    def test_una_periodicidad_no_permitida_se_rechaza(self):
        for malo in ('5', '0', '-1', 'abc'):
            self.assertFalse(EquipoHVACForm({**self.BASE, 'periodicidad_meses': malo}).is_valid(), malo)

    def test_la_edicion_cambia_la_periodicidad(self):
        datos = {'nombre': self.equipo.nombre, 'codigo_identificador': self.equipo.codigo_identificador, 'tipo': self.equipo.tipo,
                 'ubicacion': self.equipo.ubicacion, 'estado': 'OPERATIVO', 'periodicidad_meses': '12'}
        f = EquipoHVACEditForm(datos, instance=self.equipo)
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.save().periodicidad_meses, 12)

    def test_las_pantallas_de_crear_y_editar_muestran_el_campo(self):
        self.client.force_login(self.gerente)
        self.assertContains(self.client.get(reverse('crear_equipo')), 'name="periodicidad_meses"')
        self.assertContains(self.client.get(reverse('editar_equipo', args=[self.equipo.id])), 'name="periodicidad_meses"')

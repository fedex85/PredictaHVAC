"""Calendario real de órdenes para gestión."""
from datetime import date

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from core import calendario
from core.models import OrdenTrabajo
from core.test_ordenes import OrdenesBase


class CalendarioLogicaTests(SimpleTestCase):
    HOY = date(2026, 9, 15)

    def test_parsear_mes_valido_e_invalido(self):
        self.assertEqual(calendario.parsear_mes('2026-03', self.HOY), (2026, 3))
        for malo in ('', 'x', '2026-13', '2026-00', '1999-05', '2101-01', '2026', '2026-5-1', None):
            self.assertEqual(calendario.parsear_mes(malo, self.HOY), (2026, 9), malo)

    def test_mes_vecino_cruza_anio_y_respeta_limites(self):
        self.assertEqual(calendario.mes_vecino(2026, 12, 1), (2027, 1))
        self.assertEqual(calendario.mes_vecino(2026, 1, -1), (2025, 12))
        self.assertIsNone(calendario.mes_vecino(2000, 1, -1))
        self.assertIsNone(calendario.mes_vecino(2100, 12, 1))

    def test_semanas_empiezan_en_lunes_y_marcan_hoy(self):
        semanas = calendario.semanas_del_mes(2026, 9, [], self.HOY)
        self.assertTrue(all(len(s) == 7 for s in semanas))
        self.assertTrue(all(s[0]['fecha'].weekday() == 0 for s in semanas))
        self.assertEqual([d['fecha'] for s in semanas for d in s if d['es_hoy']], [self.HOY])
        self.assertEqual(sum(d['del_mes'] for s in semanas for d in s), 30)


class CalendarioVistaTests(OrdenesBase):
    def orden(self, fecha, estado=OrdenTrabajo.ASIGNADA, tecnico=None):
        return OrdenTrabajo.objects.create(equipo=self.equipo, descripcion='Tarea', estado=estado, fecha_programada=fecha,
                                           tecnico=tecnico or self.tec, creado_por=self.gerente)

    def get(self, usuario=None, **params):
        self.client.force_login(usuario or self.gerente)
        return self.client.get(reverse('calendario'), params)

    def test_muestra_las_ordenes_del_mes_con_enlace(self):
        o = self.orden(date(2026, 9, 10))
        html = self.get(mes='2026-09').content.decode()
        self.assertIn('Septiembre 2026', html)
        self.assertIn(f'data-chip-orden="{o.id}"', html)
        self.assertIn(reverse('orden_detalle', args=[o.id]), html)

    def test_otro_mes_no_aparece_y_canceladas_se_ocultan(self):
        otra = self.orden(date(2026, 10, 2))
        cancelada = self.orden(date(2026, 9, 11), estado=OrdenTrabajo.CANCELADA)
        html = self.get(mes='2026-09').content.decode()
        self.assertNotIn(f'data-chip-orden="{otra.id}"', html)
        self.assertNotIn(f'data-chip-orden="{cancelada.id}"', html)

    def test_sin_fecha_lista_solo_pendientes_y_asignadas(self):
        pend = self.orden(None, estado=OrdenTrabajo.PENDIENTE)
        fin = self.orden(None, estado=OrdenTrabajo.FINALIZADA)
        html = self.get(mes='2026-09').content.decode()
        zona = html[html.index('id="sin-fecha"'):]
        self.assertIn(f'data-chip-orden="{pend.id}"', zona)
        self.assertNotIn(f'data-chip-orden="{fin.id}"', zona)

    def test_filtro_por_tecnico(self):
        a = self.orden(date(2026, 9, 3), tecnico=self.tec)
        b = self.orden(date(2026, 9, 4), tecnico=self.tec2)
        html = self.get(mes='2026-09', tecnico=self.tec2.id).content.decode()
        self.assertIn(f'data-chip-orden="{b.id}"', html)
        self.assertNotIn(f'data-chip-orden="{a.id}"', html)

    def test_parametros_basura_no_rompen(self):
        for params in ({'mes': 'abc'}, {'mes': '2026-99'}, {'tecnico': 'x'}, {'tecnico': '99999'}):
            self.assertEqual(self.get(**params).status_code, 200, params)

    def test_mes_por_defecto_es_el_actual(self):
        hoy = timezone.localdate()
        self.assertIn(calendario.MESES[hoy.month - 1].capitalize(), self.get().content.decode())

    def test_mas_de_tres_ordenes_en_un_dia_las_muestra_todas(self):
        ids = [self.orden(date(2026, 9, 7)).id for _ in range(5)]
        html = self.get(mes='2026-09').content.decode()
        for i in ids:
            self.assertIn(f'data-chip-orden="{i}"', html)
        self.assertIn('+2 más', html)

    def test_tecnico_no_accede_y_anonimo_va_a_login(self):
        self.client.force_login(self.tec)
        self.assertEqual(self.client.get(reverse('calendario')).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('calendario')).status_code, 302)

    def test_admin_tambien_accede(self):
        self.assertEqual(self.get(self.admin).status_code, 200)

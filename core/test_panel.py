"""El panel y el inventario muestran datos reales, no ejemplos escritos en la plantilla."""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from core.models import EquipoHVAC, OrdenTrabajo
from core.test_ordenes import OrdenesBase


class PanelRealTests(OrdenesBase):
    def test_sin_datos_no_hay_ejemplos_inventados(self):
        EquipoHVAC.objects.all().delete()
        self.client.force_login(self.gerente)
        panel = self.client.get(reverse('dashboard')).content.decode()
        self.assertNotIn('Chiller Principal', panel)
        self.assertNotIn('94.2', panel)
        self.assertNotIn('vibración anómala', panel)
        self.assertIn('No hay mantenimientos programados.', panel)
        inventario = self.client.get(reverse('equipos')).content.decode()
        self.assertNotIn('Chiller Principal', inventario)
        self.assertIn('Todavía no hay equipos registrados.', inventario)

    def test_el_panel_lista_las_proximas_ordenes_y_el_porcentaje_operativo(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        o.fecha_programada = timezone.localdate() + timedelta(days=2)
        o.save()
        EquipoHVAC.objects.create(nombre='Split 2', codigo_identificador='SP-2', ubicacion='Sala', estado='FUERA_SERVICIO')
        self.client.force_login(self.gerente)
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.context['porcentaje_operativos'], 50)
        self.assertEqual(list(r.context['proximas_ordenes']), [o])
        self.assertContains(r, '1 equipo fuera de servicio')

"""Pruebas del listado de órdenes: las etiquetas de la columna Tipo no se superponen en pantallas estrechas."""
from django.urls import reverse

from core.models import OrdenTrabajo
from core.test_ordenes import OrdenesBase


class EtiquetasListadoTests(OrdenesBase):
    def test_etiquetas_de_tipo_en_contenedor_que_las_reparte_en_filas(self):
        OrdenTrabajo.objects.create(equipo=self.equipo, tipo='CORRECTIVO', descripcion='Avería', con_checklist=False,
                                    creado_por=self.gerente)
        self.client.force_login(self.gerente)
        r = self.client.get(reverse('ordenes'))
        self.assertContains(r, 'Correctivo')
        self.assertContains(r, 'Sin checklist')
        self.assertContains(r, '<div class="flex flex-wrap gap-1">')
        self.assertNotContains(r, 'class="ml-1 px-2 py-1')

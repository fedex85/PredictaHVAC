"""Pruebas de la fase 2, parte 4: informe en PDF de la orden de trabajo."""
from unittest import mock

from django.urls import reverse

from core import checklists, incidencias, informe_ot, ordenes
from core.models import OrdenTrabajo, RegistroActividad
from core.test_incidencias import IncidenciasBase

JUSTIFICACION = 'El cliente asume el riesgo por escrito'


class InformeBase(IncidenciasBase):
    def con_firma(self):
        """Orden Pendiente de aprobación con fotos y firma vigente."""
        o = self.en_ejecucion('SPLIT', evidencias=True)
        self.completar_checklist(o)
        o.observaciones, o.sin_materiales = 'Todo bien', True
        o.save()
        self.completar_evidencias(o)
        ordenes.enviar(o, self.req)
        return o

    def sin_checklist(self):
        o = self.en_ejecucion('SPLIT', con_checklist=False)
        o.observaciones, o.sin_materiales, o.estado = 'Revisión general', True, OrdenTrabajo.PENDIENTE_APROBACION
        o.save()
        return o

    def aprobada(self):
        o = self.en_aprobacion(altas=1)
        incidencias.justificar(o, incidencias.incidencias_alta(o)[0].id, JUSTIFICACION, self.gerente_req)
        ordenes.aprobar(o, self.gerente_req)
        o.refresh_from_db()
        return o


class DatosInformeTests(InformeBase):
    def test_version_provisional_y_definitivo(self):
        o = self.en_aprobacion(altas=1)
        self.assertEqual(informe_ot.datos_informe(o)['version'], 'PROVISIONAL')
        incidencias.justificar(o, incidencias.incidencias_alta(o)[0].id, JUSTIFICACION, self.gerente_req)
        ordenes.aprobar(o, self.gerente_req)
        o.refresh_from_db()
        self.assertEqual(informe_ot.datos_informe(o)['version'], 'DEFINITIVO')

    def test_estado_no_admitido_lanza_valueerror(self):
        o = self.en_ejecucion('SPLIT')
        with self.assertRaises(ValueError):
            informe_ot.datos_informe(o)

    def test_cabecera_y_tiempos(self):
        o = self.en_aprobacion()
        d = informe_ot.datos_informe(o)
        self.assertEqual(d['codigo'], o.codigo)
        self.assertIn(self.equipo.codigo_identificador, d['equipo'])
        self.assertEqual(d['tecnico'], self.tec.get_full_name() or self.tec.username)
        self.assertEqual(d['tiempo_efectivo'], o.tiempo_efectivo_texto)

    def test_puntos_incluyen_resultado_nota_y_bloque(self):
        o = self.en_aprobacion(altas=1)
        d = informe_ot.datos_informe(o)
        alta = [p for p in d['puntos'] if p['resultado'] == 'Incidencia Alta']
        self.assertEqual(len(alta), 1)
        self.assertEqual(alta[0]['nota'], 'Fuga en válvula')
        self.assertTrue(alta[0]['bloque'])
        self.assertTrue(all(p['resultado'] == 'OK' for p in d['puntos'] if p is not alta[0]))

    def test_incidencia_alta_pendiente_se_marca(self):
        o = self.en_aprobacion(altas=1)
        alta = [p for p in informe_ot.datos_informe(o)['puntos'] if p['resultado'] == 'Incidencia Alta'][0]
        self.assertTrue(alta['alta_pendiente'])
        self.assertIsNone(alta['decision'])

    def test_decision_justificada(self):
        o = self.en_aprobacion(altas=1)
        incidencias.justificar(o, incidencias.incidencias_alta(o)[0].id, JUSTIFICACION, self.gerente_req)
        alta = [p for p in informe_ot.datos_informe(o)['puntos'] if p['resultado'] == 'Incidencia Alta'][0]
        self.assertFalse(alta['alta_pendiente'])
        dec = alta['decision']
        self.assertEqual(dec['tipo'], 'JUSTIFICADA')
        self.assertEqual(dec['justificacion'], JUSTIFICACION)
        self.assertEqual(dec['por'], self.gerente.get_full_name() or self.gerente.username)
        self.assertIsNotNone(dec['en'])

    def test_decision_correctiva_conserva_codigo_aunque_se_cancele_despues(self):
        o = self.en_aprobacion(altas=1)
        c = incidencias.crear_correctiva(o, incidencias.incidencias_alta(o)[0].id, self._nueva(), self.gerente_req)
        ordenes.aprobar(o, self.gerente_req)
        ordenes.cancelar(c, 'Ya no hace falta', self.gerente_req)
        o.refresh_from_db()
        alta = [p for p in informe_ot.datos_informe(o)['puntos'] if p['resultado'] == 'Incidencia Alta'][0]
        self.assertEqual(alta['decision']['tipo'], 'CORRECTIVA')
        self.assertEqual(alta['decision']['correctiva'], c.codigo)

    def test_mediciones_con_valor_unidad_y_rango(self):
        o = self.en_aprobacion()
        m = o.mediciones.first()
        definicion = checklists.MEDICIONES[m.codigo]
        fila = informe_ot.datos_informe(o)['mediciones'][0]
        self.assertEqual(fila['unidad'], m.unidad)
        self.assertEqual(fila['valor'], f'{m.valor.normalize():f}')
        self.assertEqual(fila['rango'], f'{definicion.minimo:f} a {definicion.maximo:f}')

    def test_medicion_sin_valor_y_orden_sin_mediciones(self):
        o = self.en_aprobacion()
        m = o.mediciones.first()
        m.valor = None
        m.save()
        self.assertEqual(informe_ot.datos_informe(o)['mediciones'][0]['valor'], 'Sin medir')
        s = self.sin_checklist()
        d = informe_ot.datos_informe(s)
        self.assertEqual((d['puntos'], d['mediciones']), ([], []))

    def test_materiales_sin_materiales_y_observaciones(self):
        o = self.en_aprobacion(altas=1)
        d = informe_ot.datos_informe(o)
        self.assertEqual(d['materiales'], 'Sin materiales')
        self.assertEqual(d['observaciones'], o.observaciones)

    def test_firma_sin_vigente_y_obsoleta(self):
        o = self.en_aprobacion()
        sin = informe_ot.datos_informe(o)['firma']
        self.assertEqual((sin['estado'], sin['firmante'], sin['fecha']), ('sin', '', None))
        f = self.con_firma()
        vigente = informe_ot.datos_informe(f)['firma']
        self.assertEqual(vigente['estado'], 'vigente')
        self.assertEqual(vigente['firmante'], 'Cliente de prueba')
        self.assertIsNotNone(vigente['fecha'])
        f.observaciones = 'Cambiadas después de firmar'
        f.save()
        obsoleta = informe_ot.datos_informe(f)['firma']
        self.assertEqual((obsoleta['estado'], obsoleta['firmante']), ('obsoleta', 'Cliente de prueba'))


class ResumenInformeTests(InformeBase):
    def resumen(self, o):
        return informe_ot.datos_informe(o)['resumen']

    def test_sin_incidencias(self):
        r = self.resumen(self.en_aprobacion(altas=0))
        self.assertEqual(r['incidencias'], 0)
        self.assertEqual(r['ok'], r['puntos'])
        self.assertEqual(r['frase'], f"Sin incidencias: los {r['puntos']} puntos revisados están OK.")

    def test_alta_pendiente(self):
        r = self.resumen(self.en_aprobacion(altas=1))
        self.assertEqual((r['incidencias'], r['alta'], r['alta_pendientes']), (1, 1, 1))
        self.assertEqual(r['frase'], '1 incidencia: 1 Alta (1 pendiente de resolver).')

    def test_alta_justificada_y_media(self):
        o = self.en_aprobacion(altas=1, otras=1)
        incidencias.justificar(o, incidencias.incidencias_alta(o)[0].id, JUSTIFICACION, self.gerente_req)
        r = self.resumen(o)
        self.assertEqual((r['incidencias'], r['media'], r['alta_pendientes']), (2, 1, 0))
        self.assertEqual(r['frase'], '2 incidencias: 1 Alta (1 justificada), 1 Media.')

    def test_alta_con_correctiva(self):
        o = self.en_aprobacion(altas=1)
        c = incidencias.crear_correctiva(o, incidencias.incidencias_alta(o)[0].id, self._nueva(), self.gerente_req)
        r = self.resumen(o)
        self.assertEqual(r['correctivas'], [c.codigo])
        self.assertEqual(r['frase'], f'1 incidencia: 1 Alta (correctiva {c.codigo}).')

    def test_sin_checklist_y_mediciones_tomadas(self):
        self.assertEqual(self.resumen(self.sin_checklist())['frase'], 'Sin checklist en esta orden.')
        r = self.resumen(self.en_aprobacion())
        self.assertGreater(r['mediciones'], 0)
        self.assertEqual(r['mediciones_tomadas'], r['mediciones'])


class GenerarInformeTests(InformeBase):
    def pdf(self, orden):
        return informe_ot.generar_informe_ot(orden, self.gerente)

    def test_genera_pdf_provisional_y_definitivo(self):
        o = self.en_aprobacion(altas=1)
        provisional = self.pdf(o)
        incidencias.justificar(o, incidencias.incidencias_alta(o)[0].id, JUSTIFICACION, self.gerente_req)
        ordenes.aprobar(o, self.gerente_req)
        o.refresh_from_db()
        definitivo = self.pdf(o)
        self.assertTrue(provisional.startswith(b'%PDF'))
        self.assertTrue(definitivo.startswith(b'%PDF'))
        self.assertNotEqual(provisional, definitivo)

    def test_estado_no_admitido_lanza_valueerror(self):
        with self.assertRaises(ValueError):
            self.pdf(self.en_ejecucion('SPLIT'))

    def test_texto_con_caracteres_especiales_no_rompe(self):
        o = self.en_aprobacion(altas=1)
        o.observaciones = 'Presión <alta> & "fuga"\nlínea 2 <b>sin cerrar'
        o.materiales, o.sin_materiales = 'Tubo <i> & junta', False
        o.save()
        punto = incidencias.incidencias_alta(o)[0]
        punto.nota = 'Nota <u>rara</u> & más'
        punto.save()
        incidencias.justificar(o, punto.id, 'Justificación <b>con marcado</b> & símbolos', self.gerente_req)
        o.pausas.create(motivo='Pausa <b>x</b> & y', desde=o.inicio, hasta=o.fin or o.inicio)
        self.assertTrue(self.pdf(o).startswith(b'%PDF'))

    def test_firma_ausente_obsoleta_y_vigente_generan(self):
        self.assertTrue(self.pdf(self.en_aprobacion()).startswith(b'%PDF'))
        f = self.con_firma()
        self.assertTrue(self.pdf(f).startswith(b'%PDF'))
        f.observaciones = 'Cambiadas después de firmar'
        f.save()
        self.assertTrue(self.pdf(f).startswith(b'%PDF'))

    def test_archivo_de_firma_borrado_no_rompe(self):
        f = self.con_firma()
        firma = f.firma
        firma.imagen.storage.delete(firma.imagen.name)
        with self.assertLogs('core.informe_ot', 'WARNING'):  # rama de respaldo: se avisa en el log y se genera igual
            self.assertTrue(self.pdf(f).startswith(b'%PDF'))

    def test_firma_muy_alta_y_estrecha_no_rompe(self):
        import base64
        import io
        from PIL import Image, ImageDraw
        f = self.en_ejecucion('SPLIT', evidencias=True)
        self.completar_checklist(f)
        f.observaciones, f.sin_materiales = 'Todo bien', True
        f.save()
        imagen = Image.new('RGBA', (100, 15000), (0, 0, 0, 0))
        ImageDraw.Draw(imagen).line([(5, 10), (95, 14990)], fill=(0, 0, 0, 255), width=6)
        buffer = io.BytesIO()
        imagen.save(buffer, 'PNG')
        data = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
        from core import evidencias
        evidencias.guardar_firma(f, 'Cliente', data, self.peticion(f.tecnico))
        f.estado = OrdenTrabajo.PENDIENTE_APROBACION
        f.save()
        self.assertTrue(self.pdf(f).startswith(b'%PDF'))

    def test_justificacion_muy_larga_no_rompe(self):
        o = self.en_aprobacion(altas=1)
        incidencias.justificar(o, incidencias.incidencias_alta(o)[0].id, ('Justificación larga de prueba. ' * 12 + '\n') * 40,
                               self.gerente_req)
        self.assertTrue(self.pdf(o).startswith(b'%PDF'))

    def test_orden_sin_checklist_ni_mediciones_genera(self):
        self.assertTrue(self.pdf(self.sin_checklist()).startswith(b'%PDF'))

    def test_documento_largo_ocupa_varias_paginas(self):
        import re
        o = self.en_aprobacion()
        o.observaciones = ('Observación larga de prueba. ' * 12 + '\n') * 40
        o.save()
        self.assertGreaterEqual(len(re.findall(rb'/Type\s*/Page(?!s)', self.pdf(o))), 2)


class VistaInformeTests(InformeBase):
    def url(self, orden):
        return reverse('orden_informe_pdf', args=[orden.id])

    def descargas(self):
        return RegistroActividad.objects.filter(accion=RegistroActividad.REPORTE_DESCARGADO)

    def test_gerente_admin_y_tecnico_asignado_descargan(self):
        o = self.en_aprobacion(altas=1)
        for usuario in (self.gerente, self.admin, self.tec):
            self.client.force_login(usuario)
            r = self.client.get(self.url(o))
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r['Content-Type'], 'application/pdf')
            self.assertTrue(r.content.startswith(b'%PDF'))
            self.assertIn('attachment', r['Content-Disposition'])
            self.assertIn(f'Informe_{o.codigo}_provisional.pdf', r['Content-Disposition'])
        incidencias.justificar(o, incidencias.incidencias_alta(o)[0].id, JUSTIFICACION, self.gerente_req)
        ordenes.aprobar(o, self.gerente_req)
        r = self.client.get(self.url(o))
        self.assertIn(f'Informe_{o.codigo}_definitivo.pdf', r['Content-Disposition'])

    def test_tecnico_ajeno_recibe_404(self):
        o = self.en_aprobacion()
        self.client.force_login(self.tec2)
        self.assertEqual(self.client.get(self.url(o)).status_code, 404)
        self.assertEqual(self.descargas().count(), 0)

    def test_sin_sesion_redirige_al_acceso(self):
        o = self.en_aprobacion()
        self.assertRedirects(self.client.get(self.url(o)), f"{reverse('login')}?next={self.url(o)}",
                             fetch_redirect_response=False)

    def test_estados_no_admitidos_dan_404(self):
        self.client.force_login(self.gerente)
        pendiente = self.orden()
        asignada = self.orden(estado=OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        en_ejecucion = self.en_ejecucion('SPLIT')
        cancelada = self.orden(estado=OrdenTrabajo.CANCELADA)
        for o in (pendiente, asignada, en_ejecucion, cancelada):
            self.assertEqual(self.client.get(self.url(o)).status_code, 404, o.estado)
        self.assertEqual(self.descargas().count(), 0)

    def test_descarga_queda_en_el_log(self):
        o = self.en_aprobacion()
        self.client.force_login(self.gerente)
        self.client.get(self.url(o))
        registro = self.descargas().get()
        self.assertIn(o.codigo, registro.detalle)

    def test_fallo_de_generacion_vuelve_al_detalle_con_mensaje(self):
        o = self.en_aprobacion()
        self.client.force_login(self.gerente)
        with mock.patch('core.informe_ot.generar_informe_ot', side_effect=Exception('x')), \
                self.assertLogs('core.views_ordenes', 'ERROR'):
            r = self.client.get(self.url(o), follow=True)
        self.assertRedirects(r, reverse('orden_detalle', args=[o.id]))
        self.assertIn('No se pudo generar el informe', ' '.join(str(m) for m in r.context['messages']))
        self.assertEqual(self.descargas().count(), 0)

    def test_boton_en_detalle_segun_estado(self):
        o = self.en_aprobacion(altas=1)
        for usuario in (self.gerente, self.tec):
            self.client.force_login(usuario)
            r = self.client.get(reverse('orden_detalle', args=[o.id]))
            self.assertContains(r, 'Descargar informe provisional')
            self.assertContains(r, self.url(o))
        incidencias.justificar(o, incidencias.incidencias_alta(o)[0].id, JUSTIFICACION, self.gerente_req)
        ordenes.aprobar(o, self.gerente_req)
        self.assertContains(self.client.get(reverse('orden_detalle', args=[o.id])), 'Descargar informe definitivo')
        e = self.en_ejecucion('SPLIT')
        self.assertNotContains(self.client.get(reverse('orden_detalle', args=[e.id])), 'Descargar informe')

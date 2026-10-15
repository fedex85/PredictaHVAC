"""Pruebas de la fase 2, parte 2: fotografías y firma del cliente."""
import base64
import io
import os
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.urls import reverse
from PIL import Image

from core import evidencias, ordenes
from core.models import FirmaOT, FirmaTecnicoOT, FotoOT, OrdenTrabajo, ruta_firma, ruta_foto
from core.ordenes import ReglaError
from core.test_checklist import ChecklistBase
from core.test_ordenes import imagen_de_prueba, png_en_base64


class EvidenciasBase(ChecklistBase):
    def setUp(self):
        super().setUp()
        self.o = self.en_ejecucion('SPLIT', evidencias=True)
        self.req = self.peticion(self.tec)

    def subir(self, n=1):
        return [evidencias.subir_foto(self.o, imagen_de_prueba(nombre=f'f{i}.jpg'), self.req) for i in range(n)]


class ModeloEvidenciasTests(ChecklistBase):
    def test_orden_nueva_no_exige_evidencias_por_defecto(self):
        self.assertFalse(self.orden().con_evidencias)

    def test_las_rutas_usan_uuid_y_la_orden_no_el_nombre_original(self):
        o = self.orden()
        ruta = ruta_foto(FotoOT(orden=o), 'mi casa.PNG')
        self.assertTrue(ruta.startswith(f'ordenes/{o.id}/fotos/') and ruta.endswith('.jpg'))
        self.assertNotIn('mi casa', ruta)
        ruta = ruta_firma(FirmaOT(orden=o), 'otra.JPG')
        self.assertTrue(ruta.startswith(f'ordenes/{o.id}/firma/') and ruta.endswith('.png'))

    def test_una_firma_por_orden(self):
        o = self.orden()
        FirmaOT.objects.create(orden=o, imagen='x.png', firmante='A', huella='h')
        with self.assertRaises(IntegrityError), transaction.atomic():
            FirmaOT.objects.create(orden=o, imagen='y.png', firmante='B', huella='h')

    def test_los_bloques_de_subsanacion_incluyen_fotos_y_firma(self):
        self.assertTrue({'FOTOS', 'FIRMA'} <= set(dict(OrdenTrabajo.BLOQUES)))


class FotosTests(EvidenciasBase):
    def test_subir_foto_valida_la_reduce_y_la_guarda_como_jpeg(self):
        foto = evidencias.subir_foto(self.o, imagen_de_prueba(3000, 1500), self.req)
        with Image.open(foto.imagen.path) as guardada:
            self.assertEqual(guardada.format, 'JPEG')
            self.assertEqual(max(guardada.size), 1600)
        self.assertEqual(self.o.fotos.count(), 1)
        self.assertTrue(self.o.eventos.filter(texto='Fotografía añadida').exists())

    def test_foto_png_se_convierte_a_jpeg(self):
        foto = evidencias.subir_foto(self.o, imagen_de_prueba(formato='PNG', nombre='f.png'), self.req)
        with Image.open(foto.imagen.path) as guardada:
            self.assertEqual(guardada.format, 'JPEG')

    def test_la_orientacion_exif_se_aplica_y_los_metadatos_se_eliminan(self):
        exif = Image.Exif()
        exif[0x0112] = 6
        buffer = io.BytesIO()
        Image.new('RGB', (200, 100), (10, 120, 10)).save(buffer, 'JPEG', exif=exif)
        archivo = SimpleUploadedFile('movil.jpg', buffer.getvalue(), 'image/jpeg')
        foto = evidencias.subir_foto(self.o, archivo, self.req)
        with Image.open(foto.imagen.path) as guardada:
            self.assertEqual(guardada.size, (100, 200))
            self.assertEqual(len(guardada.getexif()), 0)

    def test_archivo_que_no_es_imagen_se_rechaza(self):
        archivo = SimpleUploadedFile('x.jpg', b'esto es texto', 'image/jpeg')
        with self.assertRaisesMessage(ReglaError, 'El archivo no es una imagen válida (JPG, PNG o WebP).'):
            evidencias.subir_foto(self.o, archivo, self.req)
        self.assertEqual(self.o.fotos.count(), 0)

    def test_bomba_de_descompresion_se_rechaza(self):
        anterior = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = 1000
        self.addCleanup(setattr, Image, 'MAX_IMAGE_PIXELS', anterior)
        with self.assertRaises(ReglaError):
            evidencias.subir_foto(self.o, imagen_de_prueba(200, 100), self.req)
        self.assertEqual(self.o.fotos.count(), 0)

    def test_imagen_demasiado_grande_se_rechaza(self):
        archivo = SimpleUploadedFile('g.jpg', b'0' * (10 * 1024 * 1024 + 1), 'image/jpeg')
        with self.assertRaisesMessage(ReglaError, 'La imagen supera los 10 MB.'):
            evidencias.subir_foto(self.o, archivo, self.req)

    def test_limite_de_veinte_fotos(self):
        self.subir(20)
        with self.assertRaisesMessage(ReglaError, 'Ya hay 20 fotografías: elimina alguna antes de subir otra.'):
            evidencias.subir_foto(self.o, imagen_de_prueba(), self.req)

    def test_borrar_foto_elimina_fila_y_archivo(self):
        foto = self.subir()[0]
        ruta = foto.imagen.path
        with self.captureOnCommitCallbacks(execute=True):
            evidencias.borrar_foto(self.o, foto.id, self.req)
        self.assertFalse(FotoOT.objects.filter(pk=foto.id).exists())
        self.assertFalse(os.path.exists(ruta))

    def test_borrar_foto_de_otra_orden_no_se_encuentra(self):
        otra = self.en_ejecucion('SPLIT', evidencias=True)
        ajena = evidencias.subir_foto(otra, imagen_de_prueba(), self.req)
        with self.assertRaisesMessage(ReglaError, 'Fotografía no encontrada.'):
            evidencias.borrar_foto(self.o, ajena.id, self.req)
        self.assertTrue(FotoOT.objects.filter(pk=ajena.id).exists())

    def test_solo_el_tecnico_asignado_en_ejecucion_sube_fotos(self):
        for usuario in (self.gerente, self.tec2):
            with self.assertRaises(ReglaError):
                evidencias.subir_foto(self.o, imagen_de_prueba(), self.peticion(usuario))
        self.o.estado = OrdenTrabajo.PENDIENTE_APROBACION
        self.o.save()
        with self.assertRaises(ReglaError):
            evidencias.subir_foto(self.o, imagen_de_prueba(), self.req)
        self.assertEqual(self.o.fotos.count(), 0)

    def test_fotos_faltantes(self):
        self.assertEqual(evidencias.fotos_faltantes(self.o), 3)
        self.subir(2)
        self.assertEqual(evidencias.fotos_faltantes(self.o), 1)
        self.subir(3)
        self.assertEqual(evidencias.fotos_faltantes(self.o), 0)


class FirmaTests(EvidenciasBase):
    def firmar(self, nombre='Ana Pérez', **kw):
        data = kw['data'] if 'data' in kw else png_en_base64()
        return evidencias.guardar_firma(self.o, nombre, data, self.req)

    def test_guardar_firma_valida_guarda_imagen_nombre_y_huella(self):
        firma = self.firmar()
        self.assertEqual((firma.firmante, firma.recogida_por), ('Ana Pérez', self.tec))
        self.assertEqual(firma.huella, evidencias.huella_resumen(self.o))
        with Image.open(firma.imagen.path) as guardada:
            self.assertEqual(guardada.format, 'PNG')
        self.assertTrue(self.o.eventos.filter(texto='Firma del cliente recogida: Ana Pérez').exists())

    def test_firma_sin_nombre_se_rechaza(self):
        for nombre in ('', '   '):
            with self.assertRaisesMessage(ReglaError, 'El nombre del firmante es obligatorio.'):
                self.firmar(nombre)
        self.assertFalse(FirmaOT.objects.exists())

    def test_firma_en_blanco_se_rechaza(self):
        with self.assertRaisesMessage(ReglaError, 'La firma está en blanco: pide al cliente que firme.'):
            self.firmar(data=png_en_base64(trazos=False))

    def test_dato_que_no_es_png_en_base64_se_rechaza(self):
        malos = ['hola', 'data:image/png;base64,@@@', 'data:image/jpeg;base64,' + 'AAAA',
                 'data:image/png;base64,' + base64.b64encode(b'hola').decode(), None]
        for dato in malos:
            with self.assertRaisesMessage(ReglaError, 'La firma no es válida.'):
                self.firmar(data=dato)

    def test_firma_demasiado_grande_se_rechaza(self):
        ruido = Image.frombytes('RGB', (600, 600), os.urandom(600 * 600 * 3))
        buffer = io.BytesIO()
        ruido.save(buffer, 'PNG')
        grande = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
        with self.assertRaisesMessage(ReglaError, 'La firma es demasiado grande.'):
            self.firmar(data=grande)

    def test_una_firma_rechazada_no_sustituye_a_la_anterior(self):
        primera = self.firmar()
        ruta, huella = primera.imagen.path, primera.huella
        with self.assertRaises(ReglaError):
            self.firmar(data=png_en_base64(trazos=False))
        actual = FirmaOT.objects.get(orden=self.o)
        self.assertEqual((actual.imagen.path, actual.huella), (ruta, huella))
        self.assertTrue(os.path.exists(ruta))

    def test_firmar_de_nuevo_sustituye_la_firma_y_borra_el_archivo_anterior(self):
        vieja = self.firmar().imagen.path
        with self.captureOnCommitCallbacks(execute=True):
            nueva = self.firmar('Luis Gómez')
        self.assertEqual(FirmaOT.objects.filter(orden=self.o).count(), 1)
        self.assertEqual(nueva.firmante, 'Luis Gómez')
        self.assertFalse(os.path.exists(vieja))
        self.assertTrue(os.path.exists(nueva.imagen.path))

    def test_la_huella_cambia_si_cambia_una_medicion_y_la_firma_deja_de_ser_vigente(self):
        self.firmar()
        self.assertTrue(evidencias.firma_vigente(self.o))
        ordenes.registrar_medicion(self.o, 'TENSION', '230', self.req)
        self.assertFalse(evidencias.firma_vigente(self.o))

    def test_sin_firma_no_es_vigente(self):
        self.assertFalse(evidencias.firma_vigente(self.o))

    # --- Sello de integridad (M-10) ---
    def test_sin_firma_la_integridad_es_sin(self):
        self.assertEqual(evidencias.integridad_firma(self.o), 'sin')
        self.assertEqual(evidencias.integridad_firma(self.o, tecnico=True), 'sin')

    def test_firmar_anota_el_sello_en_el_historial_y_la_firma_figura_integra(self):
        firma = self.firmar()
        sello = evidencias.sello_firma(firma)
        self.assertEqual(len(sello), 64)
        self.assertTrue(self.o.eventos.filter(texto=evidencias.PREFIJO_SELLO_CLIENTE + sello).exists())
        self.assertEqual(evidencias.sello_anotado(self.o), sello)
        self.assertEqual(evidencias.integridad_firma(self.o), 'integra')

    def test_sustituir_la_imagen_guardada_deja_la_firma_alterada(self):
        firma = self.firmar()
        otra = base64.b64decode(png_en_base64(trazos=False).split(',', 1)[1])
        with open(firma.imagen.path, 'wb') as archivo:
            archivo.write(otra)
        self.assertEqual(evidencias.integridad_firma(self.o), 'alterada')

    def test_cambiar_el_firmante_guardado_deja_la_firma_alterada(self):
        firma = self.firmar()
        FirmaOT.objects.filter(pk=firma.pk).update(firmante='Otra persona')
        self.assertEqual(evidencias.integridad_firma(self.o), 'alterada')

    def test_si_falta_el_archivo_de_la_firma_figura_alterada(self):
        firma = self.firmar()
        os.remove(firma.imagen.path)
        self.assertEqual(evidencias.sello_firma(FirmaOT.objects.get(pk=firma.pk)), '')
        self.assertEqual(evidencias.integridad_firma(self.o), 'alterada')

    def test_una_firma_anterior_al_sello_figura_sin_sello(self):
        self.firmar()
        self.o.eventos.filter(texto__startswith=evidencias.PREFIJO_SELLO_CLIENTE).delete()
        self.assertEqual(evidencias.integridad_firma(self.o), 'sin_sello')

    def test_actualizar_la_huella_de_una_firma_conservada_no_altera_el_sello(self):
        firma = self.firmar()
        FirmaOT.objects.filter(pk=firma.pk).update(huella='x' * 64)
        self.assertEqual(evidencias.integridad_firma(self.o), 'integra')

    def test_volver_a_firmar_anota_un_sello_nuevo_y_vale_el_ultimo(self):
        primera = self.firmar('Ana Pérez')
        segunda = self.firmar('Ana Pérez García')  # el nombre distinto evita depender de la resolución del reloj
        self.assertNotEqual(evidencias.sello_firma(primera), evidencias.sello_firma(segunda))
        self.assertEqual(evidencias.sello_anotado(self.o), evidencias.sello_firma(segunda))
        self.assertEqual(evidencias.integridad_firma(self.o), 'integra')

    def test_el_sello_del_tecnico_se_anota_aparte(self):
        self.firmar()
        evidencias.guardar_firma_tecnico(self.o, png_en_base64(), self.req)
        self.assertEqual(evidencias.integridad_firma(self.o, tecnico=True), 'integra')
        self.assertNotEqual(evidencias.sello_anotado(self.o, tecnico=True), evidencias.sello_anotado(self.o))
        self.assertTrue(self.o.eventos.filter(texto__startswith=evidencias.PREFIJO_SELLO_TECNICO).exists())

    def test_resumen_incluye_checklist_mediciones_observaciones_materiales_y_fotos(self):
        ordenes.marcar_punto(self.o, 'ARR_SENAL', 'INCIDENCIA', 'ALTA', 'Ruido', self.req)
        ordenes.registrar_medicion(self.o, 'TENSION', '230', self.req)
        self.o.observaciones, self.o.sin_materiales = 'Todo bien', True
        self.o.save()
        resumen = evidencias.resumen_para_firma(self.o)
        self.assertIn('Señal de arranque y contactor-compresor correctos: Incidencia Alta. Ruido', resumen)
        self.assertIn('Tensión: 230 V', resumen)
        self.assertIn('Corriente: sin medir', resumen)
        self.assertEqual(resumen[-3:], ['Observaciones: Todo bien', 'Materiales: ninguno', 'Fotografías: 0'])

    def test_solo_el_tecnico_asignado_en_ejecucion_firma(self):
        for usuario in (self.gerente, self.tec2):
            with self.assertRaises(ReglaError):
                evidencias.guardar_firma(self.o, 'Ana', png_en_base64(), self.peticion(usuario))
        self.o.estado = OrdenTrabajo.PENDIENTE_APROBACION
        self.o.save()
        with self.assertRaises(ReglaError):
            self.firmar()


class ReglasEvidenciasTests(EvidenciasBase):
    def _completo(self):
        """Todo resuelto: checklist, observaciones, materiales, 3 fotos y firma (en este orden, porque la firma
        cubre el resumen completo)."""
        self.completar_checklist(self.o)
        self.o.observaciones, self.o.sin_materiales = 'Todo correcto', True
        self.o.save()
        self.completar_evidencias(self.o)

    def test_iniciar_activa_las_evidencias_pero_una_orden_antigua_no_las_exige(self):
        nueva = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        ordenes.iniciar(nueva, self.req)
        self.assertTrue(nueva.con_evidencias)
        antigua = self.orden(OrdenTrabajo.EN_EJECUCION, self.tec)
        self.assertFalse(antigua.con_evidencias)
        problemas = ' '.join(ordenes.validar_envio(antigua))
        self.assertNotIn('fotograf', problemas.lower())
        self.assertNotIn('firma', problemas.lower())

    def test_validar_envio_lista_fotos_y_firma_con_los_textos_exactos(self):
        self.assertIn('Faltan 3 fotografías', ordenes.validar_envio(self.o))
        self.assertIn('Falta la firma del cliente', ordenes.validar_envio(self.o))
        self.subir(1)
        self.assertIn('Faltan 2 fotografías', ordenes.validar_envio(self.o))
        self.subir(1)
        self.assertIn('Falta 1 fotografía', ordenes.validar_envio(self.o))
        self.subir(1)
        self.assertFalse([p for p in ordenes.validar_envio(self.o) if 'fotograf' in p.lower()])

    def test_firma_obsoleta_exige_firmar_de_nuevo(self):
        self._completo()
        self.assertEqual(ordenes.validar_envio(self.o), [])
        ordenes.registrar_medicion(self.o, 'TENSION', '231', self.req)
        problemas = ordenes.validar_envio(self.o)
        self.assertIn('El resumen cambió después de la firma: recoge la firma de nuevo', problemas)
        self.assertNotIn('Falta la firma del cliente', problemas)

    def test_sin_firma_del_tecnico_no_se_puede_enviar(self):
        self._completo()
        self.o.firma_tecnico.delete()
        self.assertIn('Falta la firma del técnico', ordenes.validar_envio(self.o))
        with self.assertRaises(ReglaError):
            ordenes.enviar(self.o, self.req)

    def test_la_firma_del_tecnico_queda_obsoleta_si_cambia_el_resumen(self):
        self._completo()
        self.assertEqual(evidencias.estado_firma_tecnico(self.o), 'vigente')
        ordenes.registrar_medicion(self.o, 'TENSION', '232', self.req)
        self.assertEqual(evidencias.estado_firma_tecnico(self.o), 'obsoleta')
        self.assertIn('El resumen cambió después de tu firma: firma de nuevo como técnico', ordenes.validar_envio(self.o))

    def test_solo_el_tecnico_asignado_firma_como_tecnico(self):
        with self.assertRaises(ReglaError):
            evidencias.guardar_firma_tecnico(self.o, png_en_base64(), self.peticion(self.tec2))
        self.assertFalse(FirmaTecnicoOT.objects.exists())

    def test_el_tecnico_no_firma_antes_que_el_cliente(self):
        with self.assertRaisesMessage(ReglaError, 'El cliente debe firmar antes que el técnico'):
            evidencias.guardar_firma_tecnico(self.o, png_en_base64(), self.req)

    def test_firma_del_tecnico_por_vista_y_verla(self):
        evidencias.guardar_firma(self.o, 'Ana', png_en_base64(), self.req)
        self.client.force_login(self.tec)
        r = self.client.post(reverse('orden_firma_tecnico_guardar', args=[self.o.id]),
                             {'imagen': png_en_base64(), 'huella': evidencias.huella_resumen(self.o)},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['firma_tecnico_estado'], 'vigente')
        v = self.client.get(reverse('orden_firma_tecnico_ver', args=[self.o.id]))
        self.assertEqual((v.status_code, v['Content-Type']), (200, 'image/png'))

    def test_orden_completa_con_fotos_y_firma_se_envia(self):
        self._completo()
        ordenes.enviar(self.o, self.req)
        self.assertEqual(self.o.estado, OrdenTrabajo.PENDIENTE_APROBACION)

    def test_avance_incluye_fotos_y_firma_solo_con_evidencias(self):
        self.subir(2)
        avance = ordenes.avance_por_bloque(self.o)
        self.assertEqual(avance['FOTOS'], {'hechos': 2, 'total': 3})
        self.assertEqual(avance['FIRMA'], {'hechos': 0, 'total': 2})
        antigua = self.orden(OrdenTrabajo.EN_EJECUCION, self.tec)
        self.assertNotIn('FOTOS', ordenes.avance_por_bloque(antigua))

    def test_subsanacion_en_bloque_fotos_solo_deja_tocar_las_fotos_y_conserva_la_firma(self):
        evidencias.guardar_firma(self.o, 'Ana', png_en_base64(), self.req)
        self.o.subsanacion_motivo, self.o.subsanacion_bloque = 'Faltan fotos', 'FOTOS'
        self.o.save()
        with self.assertRaisesMessage(ReglaError, 'Esta subsanación solo permite editar: Fotografías.'):
            evidencias.guardar_firma(self.o, 'Ana', png_en_base64(), self.req)  # firma vigente: no se toca
        with self.assertRaises(ReglaError):
            ordenes.marcar_punto(self.o, 'ARR_SENAL', 'OK', '', '', self.req)
        self.assertEqual(len(self.subir(1)), 1)  # la firma del cliente se conserva en la subsanación
        self.assertTrue(evidencias.firma_vigente(self.o))
        evidencias.guardar_firma_tecnico(self.o, png_en_base64(), self.req)
        self.assertTrue(evidencias.firma_tecnico_vigente(self.o))

    def test_la_huella_del_resumen_visto_debe_coincidir_para_firmar(self):
        vista = evidencias.huella_resumen(self.o)
        ordenes.registrar_medicion(self.o, 'TENSION', '233', self.req)
        with self.assertRaisesMessage(ReglaError, 'El resumen cambió mientras se firmaba'):
            evidencias.guardar_firma(self.o, 'Ana', png_en_base64(), self.req, huella=vista)
        self.assertFalse(FirmaOT.objects.exists())
        evidencias.guardar_firma(self.o, 'Ana', png_en_base64(), self.req, huella=evidencias.huella_resumen(self.o))

    def test_imagenes_con_demasiados_pixeles_se_rechazan_antes_de_cargarlas(self):
        with mock.patch.object(evidencias, 'PIXELES_MAXIMOS_FOTO', 100):
            with self.assertRaisesMessage(ReglaError, 'El archivo no es una imagen válida'):
                evidencias.subir_foto(self.o, imagen_de_prueba(200, 100), self.req)
        with mock.patch.object(evidencias, 'PIXELES_MAXIMOS_FIRMA', 100):
            with self.assertRaisesMessage(ReglaError, 'La firma no es válida.'):
                evidencias.guardar_firma(self.o, 'Ana', png_en_base64(), self.req)

    def test_el_detalle_agrupa_solo_los_bloques_de_puntos(self):
        self.client.force_login(self.tec)
        r = self.client.get(reverse('orden_detalle', args=[self.o.id]))
        self.assertEqual(r.status_code, 200)
        codigos = {b['codigo'] for b in r.context['bloques']}
        self.assertTrue(codigos and codigos <= {'INSPECCION', 'FUNCIONAMIENTO', 'REFRIGERANTE'})


class VistasEvidenciasTests(EvidenciasBase):
    AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}

    def _subir(self, usuario=None, orden=None, **extra):
        self.client.force_login(usuario or self.tec)
        orden = orden or self.o
        return self.client.post(reverse('orden_foto_subir', args=[orden.id]),
                                {'archivo': imagen_de_prueba()}, **self.AJAX, **extra)

    def test_subir_foto_devuelve_json_con_url_y_avance(self):
        r = self._subir()
        self.assertEqual(r.status_code, 200)
        datos = r.json()
        self.assertTrue(datos['ok'])
        self.assertEqual(datos['avance']['FOTOS'], {'hechos': 1, 'total': 3})
        self.assertEqual(datos['foto']['url'], reverse('orden_foto_ver', args=[self.o.id, datos['foto']['id']]))

    def test_subir_sin_archivo_da_error_400(self):
        self.client.force_login(self.tec)
        r = self.client.post(reverse('orden_foto_subir', args=[self.o.id]), {}, **self.AJAX)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()['ok'])

    def test_subir_archivo_no_imagen_da_400(self):
        self.client.force_login(self.tec)
        falso = SimpleUploadedFile('x.jpg', b'no soy una imagen', content_type='image/jpeg')
        r = self.client.post(reverse('orden_foto_subir', args=[self.o.id]), {'archivo': falso}, **self.AJAX)
        self.assertEqual(r.status_code, 400)
        self.assertIn('no es una imagen válida', r.json()['errores'][0])

    def test_solo_post_para_subir_borrar_y_firmar(self):
        self.client.force_login(self.tec)
        foto = self.subir(1)[0]
        for nombre, args in (('orden_foto_subir', [self.o.id]), ('orden_foto_borrar', [self.o.id, foto.id]),
                             ('orden_firma_guardar', [self.o.id])):
            self.assertEqual(self.client.get(reverse(nombre, args=args)).status_code, 405)

    def test_ver_foto_la_sirve_privada_y_sin_sniffing(self):
        foto = self.subir(1)[0]
        self.client.force_login(self.tec)
        r = self.client.get(reverse('orden_foto_ver', args=[self.o.id, foto.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'image/jpeg')
        self.assertIn('private', r['Cache-Control'])
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        Image.open(io.BytesIO(b''.join(r.streaming_content))).verify()

    def test_gerente_puede_ver_pero_otro_tecnico_y_anonimo_no(self):
        foto = self.subir(1)[0]
        url = reverse('orden_foto_ver', args=[self.o.id, foto.id])
        self.client.force_login(self.gerente)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.tec2)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_no_se_puede_ver_una_foto_de_otra_orden_cambiando_el_id(self):
        otra = self.en_ejecucion('SPLIT', evidencias=True)
        foto_otra = evidencias.subir_foto(otra, imagen_de_prueba(), self.req)
        self.client.force_login(self.gerente)
        self.assertEqual(self.client.get(reverse('orden_foto_ver', args=[self.o.id, foto_otra.id])).status_code, 404)

    def test_otro_tecnico_no_puede_subir_a_una_orden_ajena(self):
        r = self._subir(usuario=self.tec2)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.o.fotos.count(), 0)

    def test_borrar_foto_por_vista(self):
        foto = self.subir(1)[0]
        self.client.force_login(self.tec)
        r = self.client.post(reverse('orden_foto_borrar', args=[self.o.id, foto.id]), **self.AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.o.fotos.count(), 0)

    def test_guardar_firma_por_vista_y_verla(self):
        self.client.force_login(self.tec)
        r = self.client.post(reverse('orden_firma_guardar', args=[self.o.id]),
                             {'firmante': 'Ana Cliente', 'imagen': png_en_base64(),
                              'huella': evidencias.huella_resumen(self.o)}, **self.AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['avance']['FIRMA'], {'hechos': 1, 'total': 2})
        v = self.client.get(reverse('orden_firma_ver', args=[self.o.id]))
        self.assertEqual(v.status_code, 200)
        self.assertEqual(v['Content-Type'], 'image/png')

    def test_firmar_sin_huella_o_con_huella_antigua_da_400(self):
        self.client.force_login(self.tec)
        for extra in ({}, {'huella': 'antigua'}):
            r = self.client.post(reverse('orden_firma_guardar', args=[self.o.id]),
                                 {'firmante': 'Ana', 'imagen': png_en_base64(), **extra}, **self.AJAX)
            self.assertEqual(r.status_code, 400)
        self.assertFalse(FirmaOT.objects.exists())

    def test_firma_en_blanco_o_sin_nombre_da_400_y_sin_firma_ver_da_404(self):
        self.client.force_login(self.tec)
        r = self.client.post(reverse('orden_firma_guardar', args=[self.o.id]),
                             {'firmante': 'Ana', 'imagen': png_en_base64(trazos=False), 'huella': evidencias.huella_resumen(self.o)}, **self.AJAX)
        self.assertEqual(r.status_code, 400)
        r = self.client.post(reverse('orden_firma_guardar', args=[self.o.id]),
                             {'firmante': ' ', 'imagen': png_en_base64(), 'huella': evidencias.huella_resumen(self.o)}, **self.AJAX)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get(reverse('orden_firma_ver', args=[self.o.id])).status_code, 404)


class PantallaEvidenciasTests(EvidenciasBase):
    def _detalle(self, usuario=None):
        self.client.force_login(usuario or self.tec)
        return self.client.get(reverse('orden_detalle', args=[self.o.id]))

    def test_el_tecnico_ve_los_bloques_dentro_del_checklist(self):
        r = self._detalle()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-bloque="FOTOS"')
        self.assertContains(r, 'data-bloque="FIRMA"')
        self.assertContains(r, 'id="foto-archivo"')
        self.assertContains(r, 'capture="environment"')
        self.assertContains(r, 'id="firma-lienzo"')
        self.assertContains(r, 'Aún no hay fotografías.')
        html = r.content.decode()
        self.assertLess(html.index('id="checklist"'), html.index('data-bloque="FOTOS"'))

    def test_muestra_miniaturas_con_urls_privadas(self):
        foto = self.subir(1)[0]
        r = self._detalle()
        self.assertContains(r, reverse('orden_foto_ver', args=[self.o.id, foto.id]))
        self.assertContains(r, 'data-borrar-foto')
        self.assertNotContains(r, '/media/')

    def test_firma_vigente_y_obsoleta_se_indican(self):
        self.completar_checklist(self.o)
        self.completar_evidencias(self.o)
        self.assertContains(self._detalle(), 'Vigente')
        self.o.observaciones = 'Cambio posterior'
        self.o.save()
        self.assertContains(self._detalle(), 'Hay que firmar de nuevo')

    def test_resumen_para_firmar_aparece(self):
        self.assertContains(self._detalle(), 'Resumen que se firma')

    def test_el_gerente_ve_solo_lectura_sin_controles(self):
        self.subir(1)
        r = self._detalle(self.gerente)
        self.assertContains(r, 'data-bloque="FOTOS"')
        self.assertNotContains(r, 'id="foto-archivo"')
        self.assertNotContains(r, 'id="firma-lienzo"')
        self.assertNotContains(r, 'data-borrar-foto')

    def test_en_subsanacion_de_fotos_la_firma_solo_es_editable_si_no_esta_vigente(self):
        evidencias.guardar_firma(self.o, 'Ana', png_en_base64(), self.req)
        self.o.subsanacion_motivo, self.o.subsanacion_bloque = 'Faltan fotos', 'FOTOS'
        self.o.save()
        r = self._detalle()
        self.assertContains(r, 'id="foto-archivo"')
        self.assertNotContains(r, 'id="firma-lienzo"')
        self.subir(1)
        # La firma del cliente se conserva aunque cambie el resumen: no se vuelve a pedir.
        self.assertNotContains(self._detalle(), 'id="firma-lienzo"')

    def test_la_firma_se_conserva_en_una_subsanacion_que_no_es_de_firma(self):
        evidencias.guardar_firma(self.o, 'Ana', png_en_base64(), self.req)
        self.o.subsanacion_motivo, self.o.subsanacion_bloque = 'Faltan fotos', 'FOTOS'
        self.o.save()
        self.subir(1)
        self.assertTrue(evidencias.conserva_firma(self.o))
        self.assertEqual(evidencias.estado_firma(self.o), 'vigente')
        self.assertTrue(evidencias.fijar_firma_conservada(self.o))
        self.o.refresh_from_db()
        self.assertEqual(self.o.firma.huella, evidencias.huella_resumen(self.o))

    def test_la_subsanacion_de_firma_no_conserva_la_firma(self):
        evidencias.guardar_firma(self.o, 'Ana', png_en_base64(), self.req)
        self.o.subsanacion_motivo, self.o.subsanacion_bloque = 'Firma ilegible', 'FIRMA'
        self.o.save()
        self.assertFalse(evidencias.conserva_firma(self.o))

    def test_el_lienzo_lleva_la_huella_del_resumen(self):
        self.assertContains(self._detalle(), f'data-huella="{evidencias.huella_resumen(self.o)}"')

    def test_orden_antigua_sin_evidencias_no_muestra_los_bloques(self):
        antigua = self.en_ejecucion('SPLIT')
        self.client.force_login(self.tec)
        r = self.client.get(reverse('orden_detalle', args=[antigua.id]))
        self.assertNotContains(r, 'data-bloque="FOTOS"')

    def test_orden_sin_checklist_no_muestra_evidencias(self):
        o = self.en_ejecucion('SPLIT', con_checklist=False)
        self.client.force_login(self.tec)
        r = self.client.get(reverse('orden_detalle', args=[o.id]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'data-bloque="FOTOS"')

    def test_no_hay_ruta_publica_de_media(self):
        self.assertEqual(self.client.get('/media/ordenes/1/fotos/x.jpg').status_code, 404)

    def test_el_resumen_se_muestra_como_tabla_con_el_valor_a_la_derecha(self):
        self.completar_checklist(self.o)
        filas = evidencias.filas_resumen(self.o)
        self.assertIn(('Estado de los filtros', 'OK'), filas)
        r = self._detalle()
        self.assertContains(r, 'justify-between gap-3 py-1.5')
        self.assertContains(r, 'text-emerald-400">OK</span>')

    def test_con_firma_vigente_el_recuadro_queda_plegado_tras_volver_a_firmar(self):
        evidencias.guardar_firma(self.o, 'Ana', png_en_base64(), self.req)
        r = self._detalle()
        self.assertContains(r, 'Volver a firmar')
        self.assertContains(r, 'id="firma-lienzo"')

    def test_sin_firma_no_aparece_volver_a_firmar(self):
        self.assertNotContains(self._detalle(), 'Volver a firmar')

    def test_el_historial_pliega_los_eventos_anteriores(self):
        from core.models import EventoOT
        for i in range(10):
            EventoOT.objects.create(orden=self.o, usuario_nombre='Tec', texto=f'Evento {i}')
        r = self._detalle()
        self.assertEqual(len(r.context['eventos']), 6)
        self.assertTrue(r.context['eventos_antiguos'])
        self.assertContains(r, 'anteriores')


class FirmaConResumenCambiadoTests(EvidenciasBase):
    def test_firma_rechazada_devuelve_el_resumen_actual_para_firmar_otra_vez(self):
        self.client.force_login(self.tec)
        vieja = evidencias.huella_resumen(self.o)
        ordenes.registrar_medicion(self.o, 'TENSION', '231', self.req)
        r = self.client.post(reverse('orden_firma_guardar', args=[self.o.id]),
                             {'firmante': 'Ana', 'imagen': png_en_base64(), 'huella': vieja},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 400)
        datos = r.json()
        self.assertEqual(datos['huella'], evidencias.huella_resumen(self.o))
        self.assertTrue(datos['resumen_firma'])
        self.assertFalse(FirmaOT.objects.exists())
        r2 = self.client.post(reverse('orden_firma_guardar', args=[self.o.id]),
                              {'firmante': 'Ana', 'imagen': png_en_base64(), 'huella': datos['huella']},
                              HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r2.status_code, 200)

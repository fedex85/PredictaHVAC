"""Hallazgos bajos de la auditoría: B-01 (imágenes), B-02 (dígitos Unicode), B-03 (enumeración), B-04 (nombre de archivo)."""
import io
import json
import uuid
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse
from PIL import Image

from core import evidencias
from core.forms import EquipoHVACForm
from core.models import EquipoHVAC, HistorialMantenimiento, OrdenTrabajo
from core.ordenes import ReglaError
from core.test_ordenes import OrdenesBase
from core.utiles import entero_o_none, nombre_archivo_seguro

MALOS_DIGITOS = ['²', '³', '¹', '٣', '３', '५', '²³', 'OT-²', '9' * 40, '-1', '1.5', ' ', '१२३']


class UtilesTests(SimpleTestCase):
    def test_entero_o_none(self):
        self.assertEqual(entero_o_none('42'), 42)
        self.assertEqual(entero_o_none(' 7 '), 7)
        self.assertEqual(entero_o_none('007'), 7)
        for malo in MALOS_DIGITOS + ['', None, 'abc', '12a']:
            self.assertIsNone(entero_o_none(malo), repr(malo))

    def test_la_causa_del_error_500_que_se_comprobo(self):
        self.assertTrue('²'.isdigit())
        with self.assertRaises(ValueError):
            int('²')

    def test_nombre_archivo_seguro(self):
        self.assertEqual(nombre_archivo_seguro('CH-001'), 'CH-001')
        self.assertEqual(nombre_archivo_seguro('AC/01 "x"'), 'AC_01_x')
        for malo in ('a"b', 'a\r\nSet-Cookie: x=1', '../../etc/passwd', 'ñandú ✓'):
            r = nombre_archivo_seguro(malo)
            self.assertRegex(r, r'^[A-Za-z0-9._-]+$')
            self.assertNotIn('..', r.replace('._', ''))
        self.assertEqual(nombre_archivo_seguro('"""', 'equipo'), 'equipo')
        self.assertEqual(nombre_archivo_seguro(None), 'archivo')
        self.assertLessEqual(len(nombre_archivo_seguro('x' * 500)), 80)


class DigitosUnicodeTests(OrdenesBase):
    """B-02: ningún parámetro numérico del navegador puede provocar un error 500."""

    def test_buscador_de_ordenes(self):
        self.client.force_login(self.gerente)
        for malo in MALOS_DIGITOS:
            r = self.client.get(reverse('ordenes'), {'q': malo})
            self.assertEqual(r.status_code, 200, malo)

    def test_buscador_sigue_encontrando_por_numero(self):
        o = self.orden()
        self.client.force_login(self.gerente)
        for q in (str(o.id), f'OT-{o.id}', f'ot-{o.id}'):
            r = self.client.get(reverse('ordenes'), {'q': q})
            self.assertIn(o, list(r.context['pagina']), q)

    def test_nueva_orden_con_equipo_invalido(self):
        self.client.force_login(self.gerente)
        for malo in MALOS_DIGITOS:
            self.assertEqual(self.client.get(reverse('orden_crear'), {'equipo': malo}).status_code, 200, malo)
        r = self.client.get(reverse('orden_crear'), {'equipo': str(self.equipo.id)})
        self.assertEqual(r.context['form'].initial.get('equipo'), self.equipo.id)

    def test_bitacora_con_usuario_invalido(self):
        self.client.force_login(self.admin)
        for malo in MALOS_DIGITOS:
            self.assertEqual(self.client.get(reverse('actividad'), {'usuario': malo}).status_code, 200, malo)
        r = self.client.get(reverse('actividad'), {'usuario': str(self.tec.id)})
        self.assertEqual(r.status_code, 200)


class EnumeracionTests(OrdenesBase):
    """B-03: un técnico no distingue «no existe» de «es de otro»."""

    def respuestas(self, nombre_url, inexistente=999999, **datos):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        self.client.force_login(self.tec2)
        ajena = self.client.post(reverse(nombre_url, args=[o.id]), datos)
        vacia = self.client.post(reverse(nombre_url, args=[inexistente]), datos)
        return ajena, vacia

    def test_descargar(self):
        ajena, vacia = self.respuestas('orden_descargar')
        self.assertEqual((ajena.status_code, vacia.status_code), (404, 404))
        self.assertEqual(ajena.json(), vacia.json())

    def test_sincronizar(self):
        paquete = json.dumps({'paquete_id': str(uuid.uuid4())})
        ajena, vacia = self.respuestas('orden_sincronizar', paquete=paquete)
        self.assertEqual((ajena.status_code, vacia.status_code), (404, 404))
        self.assertEqual(ajena.json(), vacia.json())

    def test_gestion_sigue_recibiendo_un_403_claro(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        self.client.force_login(self.gerente)
        r = self.client.post(reverse('orden_descargar', args=[o.id]))
        self.assertEqual(r.status_code, 403)
        self.assertIn('técnico asignado', r.json()['errores'][0])


class CodigoEquipoTests(OrdenesBase):
    """B-04: el código del equipo no puede romper la cabecera del PDF."""

    def form(self, codigo):
        return EquipoHVACForm({'nombre': 'Equipo', 'codigo_identificador': codigo, 'tipo': 'SPLIT', 'ubicacion': 'Azotea'})

    def test_codigos_validos(self):
        for ok in ('CH-777', 'AC/01', 'Split 3.2', 'chiller_7', 'Cámara fría 2', 'A'):
            self.assertTrue(self.form(ok).is_valid(), ok)

    def test_codigos_con_simbolos_peligrosos_se_rechazan(self):
        for malo in ('A"B', "A'B", 'A\nB', 'A;B', 'A<b>', '-X', ' ', 'A\\B', 'A\r\nX: y'):
            f = self.form(malo)
            self.assertFalse(f.is_valid(), repr(malo))
            self.assertIn('codigo_identificador', f.errors, repr(malo))

    def test_pdf_con_codigo_antiguo_no_valido_no_rompe_la_cabecera(self):
        # Datos anteriores a la validación: se crea saltándose los validadores
        equipo = EquipoHVAC.objects.create(nombre='Raro', codigo_identificador='RA"RO;x', ubicacion='Sótano')
        m = HistorialMantenimiento.objects.create(equipo=equipo, tipo_mantenimiento='PREVENTIVO', descripcion='Revisión',
                                                  fecha_mantenimiento='2026-09-01', tecnico_responsable='X')
        self.client.force_login(self.gerente)
        r = self.client.get(reverse('descargar_reporte_pdf', args=[m.id]))
        self.assertEqual(r.status_code, 200)
        cabecera = r['Content-Disposition']
        self.assertEqual(cabecera.count('"'), 2)  # solo las comillas que delimitan el nombre
        self.assertNotIn(';x', cabecera)


def _subida(imagen, formato, nombre):
    b = io.BytesIO()
    imagen.save(b, formato)
    return SimpleUploadedFile(nombre, b.getvalue(), {'JPEG': 'image/jpeg', 'PNG': 'image/png'}[formato])


class ImagenesGrandesTests(SimpleTestCase):
    """B-01: fotos enormes sin reservar memoria enorme."""

    def test_jpeg_grande_se_decodifica_reducido(self):
        archivo = _subida(Image.new('RGB', (6000, 4000), (30, 90, 160)), 'JPEG', 'g.jpg')
        with mock.patch('PIL.JpegImagePlugin.JpegImageFile.draft', autospec=True, return_value=None) as draft:
            # draft simulado (no reduce nada): lo que se comprueba es que se pida con el tamaño final correcto
            imagen = evidencias._abrir_imagen(archivo)
        self.assertTrue(draft.called)
        self.assertEqual(draft.call_args.args[1], 'RGB')
        pedido = draft.call_args.args[2]
        self.assertLessEqual(max(pedido), evidencias.LADO_MAXIMO)
        self.assertEqual(imagen.format, 'JPEG')

    def test_jpeg_grande_real_baja_de_tamano_al_cargar(self):
        archivo = _subida(Image.new('RGB', (6000, 4000), (30, 90, 160)), 'JPEG', 'g.jpg')
        imagen = evidencias._abrir_imagen(archivo)
        self.assertLess(imagen.width * imagen.height, 6000 * 4000)   # draft redujo la decodificación
        self.assertGreaterEqual(max(imagen.size), evidencias.LADO_MAXIMO)  # sin perder resolución útil

    def test_jpeg_pequeno_no_se_toca(self):
        archivo = _subida(Image.new('RGB', (800, 600), (30, 90, 160)), 'JPEG', 'p.jpg')
        self.assertEqual(evidencias._abrir_imagen(archivo).size, (800, 600))

    def test_png_de_mas_de_16_megapixeles_se_rechaza_pero_uno_menor_se_acepta(self):
        grande = _subida(Image.new('RGB', (4200, 4000), (1, 2, 3)), 'PNG', 'g.png')   # 16,8 MP
        with self.assertRaises(ReglaError):
            evidencias._abrir_imagen(grande)
        aceptable = _subida(Image.new('RGB', (4000, 3900), (1, 2, 3)), 'PNG', 'a.png')  # 15,6 MP
        self.assertEqual(evidencias._abrir_imagen(aceptable).format, 'PNG')

    def test_limite_de_jpeg_sigue_en_50_megapixeles(self):
        self.assertEqual(evidencias.PIXELES_MAXIMOS_FOTO, 50_000_000)
        self.assertLess(evidencias.PIXELES_MAXIMOS_OTROS, evidencias.PIXELES_MAXIMOS_FOTO)

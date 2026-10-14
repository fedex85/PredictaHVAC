import base64
import io
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from PIL import Image, ImageDraw

from core import evidencias, ordenes
from core.models import EquipoHVAC, HistorialMantenimiento, OrdenTrabajo, PerfilUsuario, RegistroActividad


def _usuario(nombre, rol, cert_dias=None):
    u = get_user_model().objects.create_user(nombre, email=f'{nombre}@ejemplo.com', password='clave-segura-123',
                                             first_name=nombre.capitalize())
    u.perfil.rol = rol
    if cert_dias is not None:
        u.perfil.cert_numero = 'ES-GF-1'
        u.perfil.cert_caducidad = timezone.localdate() + timedelta(days=cert_dias)
    u.perfil.save()
    return u


def imagen_de_prueba(ancho=200, alto=100, formato='JPEG', nombre='foto.jpg'):
    """Imagen válida en memoria, lista para subir como si viniera de un formulario."""
    buf = io.BytesIO()
    Image.new('RGB', (ancho, alto), (200, 30, 30)).save(buf, formato)
    tipos = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}
    return SimpleUploadedFile(nombre, buf.getvalue(), tipos[formato])


def png_en_base64(trazos=True):
    """Data URL de un PNG de firma: transparente con un trazo negro, o en blanco si `trazos` es falso."""
    imagen = Image.new('RGBA', (200, 80), (0, 0, 0, 0))
    if trazos:
        ImageDraw.Draw(imagen).line([(10, 60), (90, 20), (170, 60)], fill=(0, 0, 0, 255), width=4)
    buffer = io.BytesIO()
    imagen.save(buffer, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


class OrdenesBase(TestCase):
    def setUp(self):
        self._media = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self._media)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self._media, True)
        self.admin = _usuario('admin', PerfilUsuario.ADMIN)
        self.gerente = _usuario('gerente', PerfilUsuario.GERENTE)
        self.tec = _usuario('tec', PerfilUsuario.TECNICO, cert_dias=365)
        self.tec2 = _usuario('tec2', PerfilUsuario.TECNICO, cert_dias=365)
        self.tec_caducado = _usuario('caducado', PerfilUsuario.TECNICO, cert_dias=-5)
        self.tec_sin_cert = _usuario('sincert', PerfilUsuario.TECNICO)
        self.equipo = EquipoHVAC.objects.create(nombre='Chiller 1', codigo_identificador='CH-001', ubicacion='Azotea')

    def orden(self, estado=OrdenTrabajo.PENDIENTE, tecnico=None, gas=False, creador=None):
        return OrdenTrabajo.objects.create(equipo=self.equipo, descripcion='Revisión semestral', estado=estado,
                                           tecnico=tecnico, requiere_refrigerante=gas, creado_por=creador or self.gerente)

    def datos(self, **extra):
        d = {'equipo': self.equipo.id, 'tipo': 'PREVENTIVO', 'criticidad': 'MEDIA', 'descripcion': 'Limpieza de filtros'}
        d.update(extra)
        return d

    def post(self, nombre, orden, **datos):
        return self.client.post(reverse(nombre, args=[orden.id]), datos, follow=True)

    def peticion(self, usuario):
        r = RequestFactory().post('/')
        r.user = usuario
        return r

    def completar_evidencias(self, orden):
        """Sube 3 fotos y recoge la firma. Hacerlo después de dejar observaciones y materiales como estarán al enviar."""
        req = self.peticion(orden.tecnico)
        for i in range(3):
            evidencias.subir_foto(orden, imagen_de_prueba(nombre=f'f{i}.jpg'), req)
        evidencias.guardar_firma(orden, 'Cliente de prueba', png_en_base64(), req)
        evidencias.guardar_firma_tecnico(orden, png_en_base64(), req)

    def completar_checklist(self, orden):
        """Marca todos los puntos como OK y rellena todas las mediciones de una orden iniciada."""
        req = self.peticion(orden.tecnico)
        for p in orden.puntos.all():
            ordenes.marcar_punto(orden, p.codigo, 'OK', '', '', req)
        for m in orden.mediciones.all():
            ordenes.registrar_medicion(orden, m.codigo, '10', req)


class CreacionTests(OrdenesBase):
    def test_gerente_crea_orden_sin_tecnico_queda_pendiente(self):
        self.client.force_login(self.gerente)
        r = self.client.post(reverse('orden_crear'), self.datos())
        o = OrdenTrabajo.objects.get()
        self.assertRedirects(r, reverse('orden_detalle', args=[o.id]))
        self.assertEqual((o.estado, o.codigo, o.creado_por), (OrdenTrabajo.PENDIENTE, f'OT-{o.id:04d}', self.gerente))
        self.assertEqual(RegistroActividad.objects.filter(accion=RegistroActividad.ORDEN_CREADA).count(), 1)

    def test_con_tecnico_queda_asignada(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('orden_crear'), self.datos(tecnico=self.tec.id))
        self.assertEqual(OrdenTrabajo.objects.get().estado, OrdenTrabajo.ASIGNADA)

    def test_certificado_caducado_o_ausente_bloquea_la_asignacion(self):
        self.client.force_login(self.gerente)
        for t in (self.tec_caducado, self.tec_sin_cert):
            r = self.client.post(reverse('orden_crear'), self.datos(tecnico=t.id, requiere_refrigerante='on'))
            self.assertContains(r, 'No se puede asignar')
        self.assertEqual(OrdenTrabajo.objects.count(), 0)

    def test_certificado_caducado_no_importa_sin_refrigerante(self):
        self.client.force_login(self.gerente)
        self.client.post(reverse('orden_crear'), self.datos(tecnico=self.tec_caducado.id))
        self.assertEqual(OrdenTrabajo.objects.get().estado, OrdenTrabajo.ASIGNADA)

    def test_tecnico_no_crea_ordenes(self):
        self.client.force_login(self.tec)
        self.assertEqual(self.client.get(reverse('orden_crear')).status_code, 403)
        self.assertEqual(self.client.post(reverse('orden_crear'), self.datos()).status_code, 403)
        self.assertEqual(OrdenTrabajo.objects.count(), 0)


class VisibilidadTests(OrdenesBase):
    def test_tecnico_solo_ve_sus_ordenes(self):
        mia, ajena = self.orden(OrdenTrabajo.ASIGNADA, self.tec), self.orden(OrdenTrabajo.ASIGNADA, self.tec2)
        self.client.force_login(self.tec)
        r = self.client.get(reverse('ordenes'))
        self.assertContains(r, mia.codigo)
        self.assertNotContains(r, ajena.codigo)
        self.assertEqual(self.client.get(reverse('orden_detalle', args=[ajena.id])).status_code, 404)

    def test_gerente_ve_todas_y_filtra_por_estado(self):
        a, b = self.orden(OrdenTrabajo.PENDIENTE), self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        self.client.force_login(self.gerente)
        r = self.client.get(reverse('ordenes'), {'estado': OrdenTrabajo.PENDIENTE})
        self.assertContains(r, a.codigo)
        self.assertNotContains(r, b.codigo)

    def test_busqueda_por_codigo(self):
        a, b = self.orden(), self.orden()
        self.client.force_login(self.gerente)
        r = self.client.get(reverse('ordenes'), {'q': a.codigo})
        self.assertContains(r, a.codigo)
        self.assertNotContains(r, b.codigo)

    def test_tecnico_no_puede_actuar_sobre_orden_ajena(self):
        ajena = self.orden(OrdenTrabajo.ASIGNADA, self.tec2)
        self.client.force_login(self.tec)
        self.assertEqual(self.client.post(reverse('orden_iniciar', args=[ajena.id])).status_code, 404)

    def test_las_acciones_exigen_post(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        self.client.force_login(self.tec)
        self.assertEqual(self.client.get(reverse('orden_iniciar', args=[o.id])).status_code, 405)


class AsignacionTests(OrdenesBase):
    def test_gerente_asigna_y_reasigna(self):
        o = self.orden()
        self.client.force_login(self.gerente)
        self.post('orden_asignar', o, tecnico=self.tec.id)
        o.refresh_from_db()
        self.assertEqual((o.estado, o.tecnico), (OrdenTrabajo.ASIGNADA, self.tec))
        self.post('orden_asignar', o, tecnico=self.tec2.id)
        o.refresh_from_db()
        self.assertEqual(o.tecnico, self.tec2)

    def test_asignar_a_tecnico_sin_certificado_con_gas_se_bloquea(self):
        o = self.orden(gas=True)
        self.client.force_login(self.gerente)
        r = self.post('orden_asignar', o, tecnico=self.tec_caducado.id)
        self.assertContains(r, 'No se puede asignar')
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.PENDIENTE)

    def test_tecnico_no_puede_asignar(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        self.client.force_login(self.tec)
        self.post('orden_asignar', o, tecnico=self.tec2.id)
        o.refresh_from_db()
        self.assertEqual(o.tecnico, self.tec)


class FlujoTests(OrdenesBase):
    def test_ciclo_completo_hasta_finalizar_y_registrar_en_historial(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec, gas=True)
        self.client.force_login(self.tec)
        self.post('orden_iniciar', o)
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.EN_EJECUCION)
        self.assertIsNotNone(o.inicio)
        # no se puede enviar sin observaciones ni materiales
        r = self.post('orden_enviar', o, observaciones='', materiales='')
        self.assertContains(r, 'Falta marcar')
        self.assertContains(r, 'Faltan 3 fotografías')
        self.assertContains(r, 'Falta la firma del cliente')
        self.assertContains(r, 'SIN MATERIALES')
        # pausa activa bloquea el envío
        self.post('orden_pausar', o, motivo='Sin acceso al equipo')
        r = self.post('orden_enviar', o, observaciones='Todo correcto', sin_materiales='on')
        self.assertContains(r, 'Hay una pausa activa')
        self.post('orden_reanudar', o)
        self.completar_checklist(o)
        self.completar_evidencias(o)
        r = self.post('orden_enviar', o, observaciones='Todo correcto', sin_materiales='on')
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.PENDIENTE_APROBACION)
        self.assertEqual(o.pausas.count(), 1)
        # el gerente aprueba
        self.client.force_login(self.gerente)
        self.post('orden_aprobar', o)
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.FINALIZADA)
        self.assertIsNotNone(o.fin)
        h = HistorialMantenimiento.objects.get()
        self.assertEqual((h.equipo, h.tecnico_responsable, o.mantenimiento), (self.equipo, 'Tec', h))
        self.assertIn(o.codigo, h.descripcion)
        self.assertGreaterEqual(o.eventos.count(), 5)

    def test_inicio_bloqueado_por_certificado_caducado(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec_caducado, gas=True)
        self.client.force_login(self.tec_caducado)
        r = self.post('orden_iniciar', o)
        self.assertContains(r, 'No se puede iniciar la intervención')
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.ASIGNADA)

    def test_solo_el_tecnico_asignado_ejecuta(self):
        o = self.orden(OrdenTrabajo.EN_EJECUCION, self.tec)
        self.client.force_login(self.gerente)  # el gerente ve la orden pero no la ejecuta
        self.post('orden_pausar', o, motivo='x')
        self.post('orden_enviar', o, observaciones='x', sin_materiales='on')
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.EN_EJECUCION)
        self.assertEqual(o.pausas.count(), 0)

    def test_pausa_exige_motivo(self):
        o = self.orden(OrdenTrabajo.EN_EJECUCION, self.tec)
        self.client.force_login(self.tec)
        self.post('orden_pausar', o, motivo='  ')
        self.assertEqual(o.pausas.count(), 0)

    def test_subsanacion_devuelve_la_orden_al_tecnico(self):
        o = self.orden(OrdenTrabajo.PENDIENTE_APROBACION, self.tec)
        self.client.force_login(self.gerente)
        self.post('orden_subsanacion', o, motivo='')
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.PENDIENTE_APROBACION)  # sin motivo no pasa
        self.post('orden_subsanacion', o, motivo='Faltan detalles de la bomba')
        o.refresh_from_db()
        self.assertEqual((o.estado, o.subsanacion_motivo), (OrdenTrabajo.EN_EJECUCION, 'Faltan detalles de la bomba'))

    def test_tecnico_no_puede_aprobar(self):
        o = self.orden(OrdenTrabajo.PENDIENTE_APROBACION, self.tec)
        self.client.force_login(self.tec)
        self.post('orden_aprobar', o)
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.PENDIENTE_APROBACION)
        self.assertEqual(HistorialMantenimiento.objects.count(), 0)

    def test_no_se_puede_aprobar_dos_veces(self):
        o = self.orden(OrdenTrabajo.PENDIENTE_APROBACION, self.tec)
        o.observaciones = 'ok'
        o.save()
        self.client.force_login(self.gerente)
        self.post('orden_aprobar', o)
        self.post('orden_aprobar', o)
        self.assertEqual(HistorialMantenimiento.objects.count(), 1)

    def test_cambios_quedan_en_el_registro_de_actividad(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        self.client.force_login(self.tec)
        self.post('orden_iniciar', o)
        r = RegistroActividad.objects.filter(accion=RegistroActividad.ORDEN_ACTUALIZADA).get()
        self.assertIn(o.codigo, r.detalle)
        self.assertEqual(r.usuario, self.tec)


class CancelacionTests(OrdenesBase):
    def cancelar(self, usuario, orden, motivo='Cliente cancela la visita'):
        self.client.force_login(usuario)
        self.post('orden_cancelar', orden, motivo=motivo)
        orden.refresh_from_db()
        return orden.estado

    def test_gerente_cancela_en_cualquier_estado_cancelable(self):
        for estado in (OrdenTrabajo.PENDIENTE, OrdenTrabajo.ASIGNADA, OrdenTrabajo.EN_EJECUCION):
            self.assertEqual(self.cancelar(self.gerente, self.orden(estado, self.tec)), OrdenTrabajo.CANCELADA)

    def test_motivo_obligatorio(self):
        self.assertEqual(self.cancelar(self.gerente, self.orden(), motivo=' '), OrdenTrabajo.PENDIENTE)

    def test_pendiente_de_aprobacion_finalizada_y_cancelada_no_se_cancelan(self):
        for estado in (OrdenTrabajo.PENDIENTE_APROBACION, OrdenTrabajo.FINALIZADA, OrdenTrabajo.CANCELADA):
            self.assertEqual(self.cancelar(self.admin, self.orden(estado, self.tec)), estado)

    def test_tecnico_asignado_cancela_asignada_pero_no_pendiente(self):
        self.assertEqual(self.cancelar(self.tec, self.orden(OrdenTrabajo.ASIGNADA, self.tec)), OrdenTrabajo.CANCELADA)
        pendiente_ajena = self.orden(OrdenTrabajo.PENDIENTE, None)
        self.client.force_login(self.tec)  # no la ve: 404, no cambia
        self.post('orden_cancelar', pendiente_ajena, motivo='x')
        pendiente_ajena.refresh_from_db()
        self.assertEqual(pendiente_ajena.estado, OrdenTrabajo.PENDIENTE)

    def test_cancelacion_guarda_quien_cuando_y_estado_previo(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        self.cancelar(self.gerente, o)
        self.assertEqual((o.cancelada_por, o.estado_previo_cancelacion), (self.gerente, OrdenTrabajo.ASIGNADA))
        self.assertEqual(o.motivo_cancelacion, 'Cliente cancela la visita')
        self.assertIsNotNone(o.cancelada_en)

    def test_orden_cancelada_no_se_reabre(self):
        o = self.orden(OrdenTrabajo.CANCELADA, self.tec)
        self.client.force_login(self.tec)
        self.post('orden_iniciar', o)
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.CANCELADA)


class PantallasTests(OrdenesBase):
    def test_el_menu_muestra_ordenes_de_trabajo_a_todos_los_roles(self):
        for u in (self.admin, self.gerente, self.tec):
            self.client.force_login(u)
            self.assertContains(self.client.get(reverse('dashboard'), follow=True), 'rdenes')

    def test_detalle_se_muestra_para_cada_estado_y_rol(self):
        for estado in OrdenTrabajo.ESTADO_CHOICES:
            o = self.orden(estado[0], self.tec)
            for u in (self.admin, self.gerente, self.tec):
                self.client.force_login(u)
                self.assertEqual(self.client.get(reverse('orden_detalle', args=[o.id])).status_code, 200, (estado, u))

    def test_ficha_del_equipo_ofrece_nueva_orden_solo_a_gestion(self):
        self.client.force_login(self.gerente)
        self.assertContains(self.client.get(reverse('detalle_equipo', args=[self.equipo.id])), 'Nueva orden')
        self.client.force_login(self.tec)
        self.assertNotContains(self.client.get(reverse('detalle_equipo', args=[self.equipo.id])), 'Nueva orden')

    def test_crear_desde_la_ficha_preselecciona_el_equipo(self):
        self.client.force_login(self.gerente)
        r = self.client.get(reverse('orden_crear'), {'equipo': self.equipo.id})
        self.assertContains(r, f'value="{self.equipo.id}" selected')

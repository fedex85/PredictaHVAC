"""Tanda 2: clientes e instalaciones, informe por correo con reintentos y avisos a gestión."""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from core import avisos, correo_informe, ordenes
from core.forms import ClienteForm, EquipoHVACEditForm
from core.models import Aviso, Cliente, EnvioInforme, Instalacion, OrdenTrabajo, separar_correos
from core.ordenes import ReglaError
from core.test_ordenes import OrdenesBase


class CorreosTests(OrdenesBase):
    def test_separar_correos_limpia_valida_y_no_repite(self):
        self.assertEqual(separar_correos('a@x.com; B@y.com,\n a@X.com  mal@ , c@z.org'), ['a@x.com', 'B@y.com', 'c@z.org'])
        self.assertEqual(separar_correos(''), [])

    def test_el_formulario_rechaza_correos_mal_escritos(self):
        f = ClienteForm({'nombre': 'ACME', 'destinatarios': 'ok@x.com, roto@'})
        self.assertFalse(f.is_valid())
        self.assertIn('destinatarios', f.errors)

    def test_el_formulario_normaliza_los_destinatarios(self):
        f = ClienteForm({'nombre': 'ACME', 'destinatarios': 'a@x.com; b@x.com'})
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data['destinatarios'], 'a@x.com\nb@x.com')


class GestionClientesTests(OrdenesBase):
    def test_gerente_crea_cliente_e_instalacion(self):
        self.client.force_login(self.gerente)
        self.client.post(reverse('clientes'), {'c-nombre': 'ACME', 'c-destinatarios': 'info@acme.com', 'c-telefono': ''})
        cliente = Cliente.objects.get()
        self.assertEqual(cliente.lista_destinatarios, ['info@acme.com'])
        r = self.client.post(reverse('clientes'), {'i-cliente': cliente.id, 'i-nombre': 'Sede Norte', 'i-direccion': 'C/ Sol 1'},
                             follow=True)
        self.assertContains(r, 'Sede Norte')
        self.assertEqual(Instalacion.objects.get().cliente, cliente)

    def test_instalacion_repetida_para_el_mismo_cliente_se_rechaza(self):
        c = Cliente.objects.create(nombre='ACME')
        Instalacion.objects.create(cliente=c, nombre='Sede')
        self.client.force_login(self.gerente)
        self.client.post(reverse('clientes'), {'i-cliente': c.id, 'i-nombre': 'Sede'})
        self.assertEqual(Instalacion.objects.count(), 1)

    def test_el_tecnico_no_accede(self):
        self.client.force_login(self.tec)
        self.assertEqual(self.client.get(reverse('clientes')).status_code, 403)
        self.assertEqual(self.client.post(reverse('clientes'), {'c-nombre': 'X'}).status_code, 403)

    def test_editar_cliente(self):
        c = Cliente.objects.create(nombre='ACME')
        self.client.force_login(self.gerente)
        self.client.post(reverse('cliente_editar', args=[c.id]), {'nombre': 'ACME SL', 'destinatarios': 'x@acme.com'})
        c.refresh_from_db()
        self.assertEqual((c.nombre, c.destinatarios), ('ACME SL', 'x@acme.com'))

    def test_el_equipo_se_vincula_a_una_instalacion(self):
        c = Cliente.objects.create(nombre='ACME')
        i = Instalacion.objects.create(cliente=c, nombre='Sede')
        self.client.force_login(self.gerente)
        datos = {'nombre': 'Chiller 1', 'codigo_identificador': 'CH-001', 'tipo': 'SPLIT', 'ubicacion': 'Azotea', 'estado': 'OPERATIVO',
                 'instalacion': i.id}
        f = EquipoHVACEditForm(datos, instance=self.equipo)
        self.assertTrue(f.is_valid(), f.errors)
        f.save()
        self.equipo.refresh_from_db()
        self.assertEqual(self.equipo.instalacion, i)
        r = self.client.get(reverse('detalle_equipo', args=[self.equipo.id]))
        self.assertContains(r, 'ACME · Sede')

    def test_el_selector_de_equipo_de_la_orden_muestra_cliente(self):
        c = Cliente.objects.create(nombre='ACME')
        self.equipo.instalacion = Instalacion.objects.create(cliente=c, nombre='Sede')
        self.equipo.save()
        self.client.force_login(self.gerente)
        self.assertContains(self.client.get(reverse('orden_crear')), 'ACME · Sede')

    def test_no_se_borra_un_cliente_con_instalaciones(self):
        from django.db.models import ProtectedError
        c = Cliente.objects.create(nombre='ACME')
        Instalacion.objects.create(cliente=c, nombre='Sede')
        with self.assertRaises(ProtectedError):
            c.delete()


class InformeBase(OrdenesBase):
    def setUp(self):
        super().setUp()
        self.cliente = Cliente.objects.create(nombre='ACME', destinatarios='info@acme.com\nconta@acme.com')
        self.equipo.instalacion = Instalacion.objects.create(cliente=self.cliente, nombre='Sede')
        self.equipo.save()

    def pendiente_de_aprobacion(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        o.con_checklist = False
        o.save()
        ordenes.iniciar(o, self.peticion(self.tec), llegada=('NORMAL', ''))
        o.refresh_from_db()
        o.observaciones, o.sin_materiales = 'Hecho', True
        o.save()
        self.completar_evidencias(o)
        with self.captureOnCommitCallbacks(execute=True):
            ordenes.enviar(o, self.peticion(self.tec))
        o.refresh_from_db()
        mail.outbox.clear()
        return o

    def aprobar(self, o):
        with self.captureOnCommitCallbacks(execute=True):
            ordenes.aprobar(o, self.peticion(self.gerente))
        o.refresh_from_db()


class InformePorCorreoTests(InformeBase):
    def test_al_aprobar_se_envia_el_pdf_a_los_destinatarios_del_cliente(self):
        o = self.pendiente_de_aprobacion()
        self.aprobar(o)
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ['info@acme.com', 'conta@acme.com'])
        self.assertEqual(m.attachments[0][0], f'informe_{o.codigo}.pdf')
        self.assertTrue(m.attachments[0][1].startswith(b'%PDF'))
        self.assertEqual(o.envio_informe.estado, EnvioInforme.ENVIADO)
        self.assertEqual(o.envio_informe.intentos, 1)

    def test_los_destinatarios_quedan_en_la_orden_aunque_cambie_la_ficha(self):
        o = self.pendiente_de_aprobacion()
        self.aprobar(o)
        self.cliente.destinatarios = 'otro@acme.com'
        self.cliente.save()
        o.refresh_from_db()
        self.assertEqual(o.destinatarios_informe.split(), ['info@acme.com', 'conta@acme.com'])
        mail.outbox.clear()
        self.client.force_login(self.gerente)
        self.post('orden_reenviar_informe', o)
        self.assertEqual(mail.outbox[0].to, ['info@acme.com', 'conta@acme.com'])

    def test_sin_destinatarios_se_avisa_a_gestion_y_no_se_envia_al_cliente(self):
        self.cliente.destinatarios = ''
        self.cliente.save()
        o = self.pendiente_de_aprobacion()
        self.aprobar(o)
        self.assertFalse(EnvioInforme.objects.exists())
        self.assertTrue(Aviso.objects.filter(usuario=self.gerente, texto__contains='sin destinatarios').exists())
        self.assertTrue(all(m.to != ['info@acme.com'] for m in mail.outbox))

    def test_equipo_sin_instalacion_tambien_avisa(self):
        self.equipo.instalacion = None
        self.equipo.save()
        o = self.pendiente_de_aprobacion()
        self.aprobar(o)
        self.assertEqual(o.estado, OrdenTrabajo.FINALIZADA)
        self.assertTrue(Aviso.objects.filter(texto__contains='sin destinatarios').exists())

    def test_fallo_de_correo_no_impide_finalizar_y_deja_pendiente(self):
        o = self.pendiente_de_aprobacion()
        with mock.patch('django.core.mail.EmailMessage.send', side_effect=OSError('SMTP caído')):
            self.aprobar(o)
        self.assertEqual(o.estado, OrdenTrabajo.FINALIZADA)
        e = o.envio_informe
        self.assertEqual((e.estado, e.intentos), (EnvioInforme.PENDIENTE, 1))
        self.assertIn('SMTP caído', e.ultimo_error)

    def test_tres_fallos_marcan_fallido_y_avisan_una_vez(self):
        o = self.pendiente_de_aprobacion()
        with mock.patch('django.core.mail.EmailMessage.send', side_effect=OSError('SMTP caído')):
            self.aprobar(o)
            with self.captureOnCommitCallbacks(execute=True):
                correo_informe.intentar(o.envio_informe.pk)
                correo_informe.intentar(o.envio_informe.pk)
                correo_informe.intentar(o.envio_informe.pk)  # ya fallido: no cuenta
        e = EnvioInforme.objects.get()
        self.assertEqual((e.estado, e.intentos), (EnvioInforme.FALLIDO, 3))
        self.assertEqual(Aviso.objects.filter(usuario=self.gerente, texto__contains='No se pudo enviar el informe').count(), 1)

    def test_un_reintento_posterior_que_funciona_envia(self):
        o = self.pendiente_de_aprobacion()
        with mock.patch('django.core.mail.EmailMessage.send', side_effect=OSError('x')):
            self.aprobar(o)
        correo_informe.intentar(o.envio_informe.pk)
        e = EnvioInforme.objects.get()
        self.assertEqual((e.estado, e.intentos, e.ultimo_error), (EnvioInforme.ENVIADO, 2, ''))

    def test_los_reintentos_esperan_y_el_comando_los_procesa(self):
        o = self.pendiente_de_aprobacion()
        with mock.patch('django.core.mail.EmailMessage.send', side_effect=OSError('x')):
            self.aprobar(o)
        self.assertEqual(correo_informe.reintentos_pendientes(), [])  # acaba de intentarse
        EnvioInforme.objects.update(ultimo_intento=timezone.now() - timedelta(minutes=6))
        self.assertEqual(len(correo_informe.reintentos_pendientes()), 1)
        out = StringIO()
        call_command('enviar_informes', stdout=out)
        self.assertIn('1 enviado(s)', out.getvalue())
        self.assertEqual(EnvioInforme.objects.get().estado, EnvioInforme.ENVIADO)

    def test_reenvio_manual_tras_fallo(self):
        o = self.pendiente_de_aprobacion()
        with mock.patch('django.core.mail.EmailMessage.send', side_effect=OSError('x')):
            self.aprobar(o)
            for _ in range(2):
                correo_informe.intentar(o.envio_informe.pk)
        self.assertEqual(EnvioInforme.objects.get().estado, EnvioInforme.FALLIDO)
        self.client.force_login(self.gerente)
        r = self.post('orden_reenviar_informe', o)
        self.assertContains(r, 'Informe reenviado')
        self.assertEqual(EnvioInforme.objects.get().estado, EnvioInforme.ENVIADO)

    def test_reenvio_manual_que_falla_informa_del_error(self):
        o = self.pendiente_de_aprobacion()
        self.aprobar(o)
        self.client.force_login(self.gerente)
        with mock.patch('django.core.mail.EmailMessage.send', side_effect=OSError('sin red')):
            r = self.post('orden_reenviar_informe', o)
        self.assertContains(r, 'No se pudo enviar el informe')

    def test_el_tecnico_no_puede_reenviar(self):
        o = self.pendiente_de_aprobacion()
        self.aprobar(o)
        mail.outbox.clear()
        self.client.force_login(self.tec)
        self.post('orden_reenviar_informe', o)
        self.assertEqual(len(mail.outbox), 0)

    def test_reenviar_exige_orden_finalizada_y_destinatarios(self):
        o = self.pendiente_de_aprobacion()
        with self.assertRaises(ReglaError):
            correo_informe.reenviar_manual(o, self.gerente)
        self.aprobar(o)
        OrdenTrabajo.objects.filter(pk=o.pk).update(destinatarios_informe='')
        o.refresh_from_db()
        with self.assertRaises(ReglaError):
            correo_informe.reenviar_manual(o, self.gerente)

    def test_el_detalle_muestra_el_estado_del_envio_a_gestion(self):
        o = self.pendiente_de_aprobacion()
        self.aprobar(o)
        self.client.force_login(self.gerente)
        r = self.client.get(reverse('orden_detalle', args=[o.id]))
        self.assertContains(r, 'Informe al cliente')
        self.assertContains(r, 'info@acme.com')
        self.assertContains(r, 'Enviado el')
        self.client.force_login(self.tec)
        self.assertNotContains(self.client.get(reverse('orden_detalle', args=[o.id])), 'Informe al cliente')


class AvisosTests(InformeBase):
    def test_enviar_a_aprobacion_avisa_a_gerente_y_administrador_en_app_y_por_correo(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, self.tec)
        o.con_checklist = False
        o.save()
        ordenes.iniciar(o, self.peticion(self.tec), llegada=('NORMAL', ''))
        o.refresh_from_db()
        o.observaciones, o.sin_materiales = 'Hecho', True
        o.save()
        self.completar_evidencias(o)
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            ordenes.enviar(o, self.peticion(self.tec))
        for u in (self.gerente, self.admin):
            self.assertTrue(Aviso.objects.filter(usuario=u, orden=o, texto__contains='espera tu aprobación').exists())
        self.assertFalse(Aviso.objects.filter(usuario=self.tec).exists())
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['admin@ejemplo.com', 'gerente@ejemplo.com'])

    def test_un_fallo_de_correo_no_rompe_el_flujo_y_el_aviso_queda_en_la_app(self):
        with mock.patch('django.core.mail.EmailMessage.send', side_effect=OSError('x')):
            with self.captureOnCommitCallbacks(execute=True):
                avisos.notificar_gestion('Prueba')
        self.assertEqual(Aviso.objects.filter(texto='Prueba').count(), 2)

    def test_usuarios_inactivos_o_tecnicos_no_reciben_avisos(self):
        self.admin.is_active = False
        self.admin.save()
        avisos.notificar_gestion('Prueba')
        self.assertEqual(list(Aviso.objects.values_list('usuario__username', flat=True)), ['gerente'])

    def test_pagina_de_avisos_solo_muestra_los_propios_y_marca_leidos(self):
        Aviso.objects.create(usuario=self.gerente, texto='Para gerente')
        Aviso.objects.create(usuario=self.admin, texto='Para admin')
        self.client.force_login(self.gerente)
        r = self.client.get(reverse('avisos'))
        self.assertContains(r, 'Para gerente')
        self.assertNotContains(r, 'Para admin')
        self.assertEqual(avisos.sin_leer(self.gerente), 1)
        self.client.post(reverse('avisos_leer'))
        self.assertEqual(avisos.sin_leer(self.gerente), 0)
        self.assertEqual(avisos.sin_leer(self.admin), 1)

    def test_el_menu_muestra_el_contador(self):
        Aviso.objects.create(usuario=self.gerente, texto='x')
        self.client.force_login(self.gerente)
        self.assertContains(self.client.get(reverse('ordenes')), 'bg-amber-500 px-2 py-0.5 text-[11px]')

    def test_el_tecnico_no_ve_la_pagina_de_avisos(self):
        self.client.force_login(self.tec)
        self.assertEqual(self.client.get(reverse('avisos')).status_code, 403)
        self.client.post(reverse('avisos_leer'))

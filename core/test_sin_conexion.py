"""Modo sin conexión (parte 5a): descarga, bloqueo de reasignación y sincronización."""
import json
import os
import uuid
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core import checklists, evidencias, ordenes
from core.models import EventoOT, FirmaOT, FotoOT, OrdenTrabajo, RegistroActividad, SincronizacionOT
from core.ordenes import ReglaError
from core.test_ordenes import OrdenesBase, imagen_de_prueba, png_en_base64


class ReglasDescargaTests(OrdenesBase):
    def descargada(self, estado=OrdenTrabajo.ASIGNADA, **kw):
        o = self.orden(estado, tecnico=self.tec, **kw)
        o.descargada_en = timezone.now()
        o.save()
        return o

    def test_reasignar_bloqueado_si_descargada(self):
        o = self.descargada()
        with self.assertRaises(ReglaError) as cm:
            ordenes.asignar(o, self.tec2, self.peticion(self.gerente))
        self.assertIn('ya descargó', str(cm.exception))
        o.refresh_from_db()
        self.assertEqual(o.tecnico, self.tec)

    def test_reasignar_permitido_tras_liberar(self):
        o = self.descargada()
        ordenes.liberar_descarga(o, self.peticion(self.gerente))
        ordenes.asignar(o, self.tec2, self.peticion(self.gerente))
        o.refresh_from_db()
        self.assertEqual(o.tecnico, self.tec2)

    def test_liberar_solo_gestion(self):
        o = self.descargada()
        with self.assertRaises(ReglaError):
            ordenes.liberar_descarga(o, self.peticion(self.tec))
        o.refresh_from_db()
        self.assertIsNotNone(o.descargada_en)

    def test_liberar_exige_descarga_activa(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        with self.assertRaises(ReglaError):
            ordenes.liberar_descarga(o, self.peticion(self.gerente))

    def test_liberar_deja_evento_y_limpia_el_campo(self):
        o = self.descargada()
        ordenes.liberar_descarga(o, self.peticion(self.gerente))
        o.refresh_from_db()
        self.assertIsNone(o.descargada_en)
        self.assertTrue(EventoOT.objects.filter(orden=o, texto__startswith='Descarga liberada por').exists())

    def test_certificado_se_evalua_en_la_fecha_dada(self):
        fecha_cad = self.tec.perfil.cert_caducidad
        self.assertIsNone(ordenes.certificado_problema(self.tec, True, fecha_cad - timedelta(days=1)))
        self.assertIsNone(ordenes.certificado_problema(self.tec, True, fecha_cad))
        self.assertIn('caducado', ordenes.certificado_problema(self.tec, True, fecha_cad + timedelta(days=1)))
        self.assertIn('no tiene certificado', ordenes.certificado_problema(self.tec_sin_cert, True, fecha_cad))

    def test_iniciar_con_hora_dada_guarda_esa_hora(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        hora = timezone.now() - timedelta(minutes=20)
        ordenes.iniciar(o, self.peticion(self.tec), inicio=hora)
        o.refresh_from_db()
        self.assertEqual(o.inicio, hora)
        self.assertEqual(o.estado, OrdenTrabajo.EN_EJECUCION)

    def test_iniciar_con_hora_valida_certificado_en_esa_fecha(self):
        # Certificado caducado hace 5 días: con una hora de hace 10 días estaba vigente; hoy no.
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec_caducado, gas=True)
        ordenes.iniciar(o, self.peticion(self.tec_caducado), inicio=timezone.now() - timedelta(days=10))
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.EN_EJECUCION)
        o2 = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec_caducado, gas=True)
        with self.assertRaises(ReglaError):
            ordenes.iniciar(o2, self.peticion(self.tec_caducado), inicio=timezone.now())

    def test_iniciar_sin_hora_se_comporta_como_antes(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec_caducado, gas=True)
        with self.assertRaises(ReglaError):
            ordenes.iniciar(o, self.peticion(self.tec_caducado))
        o2 = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        antes = timezone.now()
        ordenes.iniciar(o2, self.peticion(self.tec))
        o2.refresh_from_db()
        self.assertGreaterEqual(o2.inicio, antes)


class DescargaTests(OrdenesBase):
    def descargar(self, orden, usuario=None):
        if usuario is not None:
            self.client.force_login(usuario)
        return self.client.post(reverse('orden_descargar', args=[orden.id]))

    def test_tecnico_asignado_descarga_y_queda_marcada(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        r = self.descargar(o, self.tec)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        o.refresh_from_db()
        self.assertIsNotNone(o.descargada_en)
        self.assertTrue(EventoOT.objects.filter(orden=o, texto='Descargada para trabajo sin conexión').exists())

    def test_segunda_descarga_no_cambia_la_marca(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        self.descargar(o, self.tec)
        o.refresh_from_db()
        primera = o.descargada_en
        self.descargar(o)
        o.refresh_from_db()
        self.assertEqual(o.descargada_en, primera)
        self.assertEqual(EventoOT.objects.filter(orden=o, texto='Descargada para trabajo sin conexión').count(), 1)

    def test_paquete_trae_catalogo_del_servidor(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec, gas=True)
        p = self.descargar(o, self.tec).json()['paquete']
        esperados = checklists.puntos_para(self.equipo.tipo, True)
        self.assertEqual([x['codigo'] for x in p['catalogo']['puntos']], [d.codigo for d in esperados])
        self.assertEqual([x['texto'] for x in p['catalogo']['puntos']], [d.texto for d in esperados])
        med = {m['codigo']: m for m in p['catalogo']['mediciones']}
        self.assertEqual(med['TENSION']['unidad'], 'V')
        self.assertEqual(med['TENSION']['minimo'], '0')
        self.assertEqual(med['TENSION']['maximo'], '480')
        self.assertEqual(p['catalogo']['mediciones_elegibles'], [])
        self.assertEqual(p['limites'], {'fotos_min': 3, 'fotos_max': 20, 'foto_bytes': 10 * 1024 * 1024})
        self.assertEqual(p['orden']['codigo'], o.codigo)
        self.assertEqual(p['equipo']['codigo'], 'CH-001')

    def test_paquete_de_orden_en_ejecucion_trae_estado_actual(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        req = self.peticion(self.tec)
        ordenes.iniciar(o, req)
        ordenes.marcar_punto(o, 'INS_FILTROS', 'OK', '', '', req)
        ordenes.registrar_medicion(o, 'TENSION', '230', req)
        o.observaciones = 'Todo bien'
        o.save()
        p = self.descargar(o, self.tec).json()['paquete']
        puntos = {x['codigo']: x for x in p['estado_actual']['puntos']}
        self.assertEqual(puntos['INS_FILTROS']['resultado'], 'OK')
        medidas = {x['codigo']: x['valor'] for x in p['estado_actual']['mediciones']}
        self.assertEqual(medidas['TENSION'], '230.00')
        self.assertEqual(p['estado_actual']['observaciones'], 'Todo bien')
        self.assertEqual(p['orden']['estado'], OrdenTrabajo.EN_EJECUCION)

    def test_orden_sin_checklist_trae_mediciones_elegibles(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        o.con_checklist = False
        o.save()
        p = self.descargar(o, self.tec).json()['paquete']
        self.assertEqual(p['catalogo']['puntos'], [])
        self.assertEqual(len(p['catalogo']['mediciones_elegibles']), len(checklists.MEDICIONES))

    def test_otro_tecnico_403(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        self.assertEqual(self.descargar(o, self.tec2).status_code, 403)
        o.refresh_from_db()
        self.assertIsNone(o.descargada_en)

    def test_gestion_403(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        self.assertEqual(self.descargar(o, self.gerente).status_code, 403)
        self.assertEqual(self.descargar(o, self.admin).status_code, 403)

    def test_sin_sesion_redirige_al_acceso(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        url = reverse('orden_descargar', args=[o.id])
        self.assertRedirects(self.client.post(url), f"{reverse('login')}?next={url}", fetch_redirect_response=False)

    def test_get_no_permitido(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        self.client.force_login(self.tec)
        self.assertEqual(self.client.get(reverse('orden_descargar', args=[o.id])).status_code, 405)

    def test_estado_no_permitido_400(self):
        for estado in (OrdenTrabajo.PENDIENTE_APROBACION, OrdenTrabajo.FINALIZADA, OrdenTrabajo.CANCELADA):
            o = self.orden(estado, tecnico=self.tec)
            r = self.descargar(o, self.tec)
            self.assertEqual(r.status_code, 400, estado)
            o.refresh_from_db()
            self.assertIsNone(o.descargada_en)

    def test_certificado_caducado_con_refrigerante_400(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec_caducado, gas=True)
        r = self.descargar(o, self.tec_caducado)
        self.assertEqual(r.status_code, 400)
        self.assertIn('caducado', r.json()['errores'][0])

    def test_certificado_caducado_sin_refrigerante_permitido(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec_caducado)
        self.assertEqual(self.descargar(o, self.tec_caducado).status_code, 200)


class SincronizacionBase(OrdenesBase):
    def preparar(self, estado=OrdenTrabajo.ASIGNADA, tecnico=None, gas=False, descargada_hace=timedelta(minutes=10)):
        """Orden asignada y descargada hace `descargada_hace`."""
        o = self.orden(estado, tecnico=tecnico or self.tec, gas=gas)
        o.descargada_en = timezone.now() - descargada_hace
        o.save()
        return o

    def paquete(self, **extra):
        d = {'paquete_id': str(uuid.uuid4()), 'inicio': (timezone.now() - timedelta(minutes=1)).isoformat()}
        d.update(extra)
        return d

    def enviar(self, orden, paquete, fotos=(), usuario=None, bruto=None):
        if usuario is not None:
            self.client.force_login(usuario)
        datos = {'paquete': bruto if bruto is not None else json.dumps(paquete)}
        if fotos:
            datos['fotos'] = list(fotos)
        return self.client.post(reverse('orden_sincronizar', args=[orden.id]), datos)

    def instantanea(self, o):
        o.refresh_from_db()
        return (o.estado, o.inicio, o.observaciones, o.materiales,
                list(o.puntos.values_list('codigo', 'resultado')), list(o.mediciones.values_list('codigo', 'valor')),
                o.sincronizaciones.count(), o.fotos.count(), o.eventos.count())

    def codigos_puntos(self, gas=False):
        return [p.codigo for p in checklists.puntos_para(self.equipo.tipo, gas)]

    def todos_ok(self, gas=False):
        return [{'codigo': c, 'resultado': 'OK'} for c in self.codigos_puntos(gas)]

    def todas_medidas(self):
        return [{'codigo': m.codigo, 'valor': '10'} for m in checklists.mediciones_para(self.equipo.tipo)]


class SincronizarTests(SincronizacionBase):
    def test_desde_asignada_inicia_con_la_hora_del_cliente_y_aplica_todo(self):
        o = self.preparar()
        hora = timezone.now() - timedelta(minutes=3)
        r = self.enviar(o, self.paquete(
            inicio=hora.isoformat(),
            puntos=[{'codigo': 'INS_FILTROS', 'resultado': 'OK'},
                    {'codigo': 'INS_BATERIA', 'resultado': 'INCIDENCIA', 'gravedad': 'MEDIA', 'nota': 'Sucia'}],
            mediciones=[{'codigo': 'TENSION', 'valor': '230,5'}],
            observaciones='Todo en orden', materiales='Filtro', sin_materiales=False), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['ok'])
        self.assertFalse(r.json()['repetido'])
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.EN_EJECUCION)
        self.assertEqual(o.inicio, hora)
        self.assertEqual(o.puntos.count(), len(self.codigos_puntos()))
        self.assertEqual(o.puntos.get(codigo='INS_FILTROS').resultado, 'OK')
        bateria = o.puntos.get(codigo='INS_BATERIA')
        self.assertEqual((bateria.resultado, bateria.gravedad, bateria.nota), ('INCIDENCIA', 'MEDIA', 'Sucia'))
        self.assertEqual(str(o.mediciones.get(codigo='TENSION').valor), '230.50')
        self.assertEqual((o.observaciones, o.materiales), ('Todo en orden', 'Filtro'))
        self.assertTrue(EventoOT.objects.filter(orden=o, texto__startswith='Sincronizado desde modo sin conexión').exists())
        self.assertTrue(RegistroActividad.objects.filter(accion=RegistroActividad.ORDEN_ACTUALIZADA,
                                                         detalle__contains='Sincronizado').exists())
        self.assertEqual(o.sincronizaciones.count(), 1)

    def test_desde_en_ejecucion_ignora_inicio(self):
        o = self.preparar()
        ordenes.iniciar(o, self.peticion(self.tec))
        o.refresh_from_db()
        original = o.inicio
        r = self.enviar(o, self.paquete(inicio=(timezone.now() - timedelta(hours=5)).isoformat(),
                                        puntos=[{'codigo': 'INS_FILTROS', 'resultado': 'OK'}]), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.inicio, original)
        self.assertEqual(o.puntos.get(codigo='INS_FILTROS').resultado, 'OK')

    def test_paquete_repetido_no_duplica(self):
        o = self.preparar()
        p = self.paquete(puntos=[{'codigo': 'INS_FILTROS', 'resultado': 'OK'}])
        self.enviar(o, p, usuario=self.tec)
        eventos = o.eventos.count()
        r = self.enviar(o, p)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['repetido'])
        self.assertEqual(SincronizacionOT.objects.count(), 1)
        self.assertEqual(o.eventos.count(), eventos)

    def test_repetido_tras_enviar_a_aprobacion_sigue_ok(self):
        o = self.preparar()
        p = self.paquete(puntos=[{'codigo': 'INS_FILTROS', 'resultado': 'OK'}])
        self.enviar(o, p, usuario=self.tec)
        OrdenTrabajo.objects.filter(pk=o.pk).update(estado=OrdenTrabajo.PENDIENTE_APROBACION)
        r = self.enviar(o, p)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['repetido'])
        self.assertEqual(r.json()['estado'], OrdenTrabajo.PENDIENTE_APROBACION)

    def test_paquete_ya_registrado_no_se_vuelve_a_aplicar(self):
        # Equivale a la segunda de dos peticiones simultáneas: la fila ya está registrada cuando obtiene el bloqueo.
        o = self.preparar()
        ident = uuid.uuid4()
        SincronizacionOT.objects.create(paquete_id=ident, orden=o, usuario=self.tec, firma='ninguna')
        antes = self.instantanea(o)
        r = self.enviar(o, self.paquete(paquete_id=str(ident), observaciones='NO debe aplicarse'), usuario=self.tec)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['repetido'])
        self.assertEqual(self.instantanea(o), antes)

    def test_paquete_de_otra_orden_se_rechaza(self):
        o1, o2 = self.preparar(), self.preparar()
        p = self.paquete()
        self.enviar(o1, p, usuario=self.tec)
        r = self.enviar(o2, p)
        self.assertEqual(r.status_code, 400)

    def test_texto_del_punto_viene_del_catalogo(self):
        o = self.preparar()
        self.enviar(o, self.paquete(puntos=[{'codigo': 'INS_FILTROS', 'resultado': 'OK', 'texto': 'TEXTO FALSO'}]),
                    usuario=self.tec)
        self.assertEqual(o.puntos.get(codigo='INS_FILTROS').texto, 'Estado de los filtros')

    def test_orden_sin_checklist_con_elegidas(self):
        o = self.preparar()
        o.con_checklist = False
        o.save()
        r = self.enviar(o, self.paquete(elegidas=['TENSION', 'CORRIENTE'],
                                        mediciones=[{'codigo': 'TENSION', 'valor': 230}], observaciones='Revisada'),
                        usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(set(o.mediciones.values_list('codigo', flat=True)), {'TENSION', 'CORRIENTE'})
        self.assertEqual(str(o.mediciones.get(codigo='TENSION').valor), '230.00')
        self.assertEqual(o.puntos.count(), 0)

    def test_respuesta_incluye_faltan_de_validar_envio(self):
        o = self.preparar()
        r = self.enviar(o, self.paquete(puntos=[{'codigo': 'INS_FILTROS', 'resultado': 'OK'}]), usuario=self.tec)
        self.assertTrue(any(f.startswith('Falta marcar') for f in r.json()['faltan']))
        o.refresh_from_db()
        self.assertEqual(r.json()['faltan'], ordenes.validar_envio(o))

    def test_punto_sin_resultado_se_ignora(self):
        o = self.preparar()
        r = self.enviar(o, self.paquete(puntos=[{'codigo': 'INS_FILTROS', 'resultado': ''}]), usuario=self.tec)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(o.puntos.get(codigo='INS_FILTROS').resultado, '')


class SincronizarRechazosTests(SincronizacionBase):
    def rechaza(self, o, paquete, codigo=400, usuario=None, **kw):
        antes = self.instantanea(o)
        r = self.enviar(o, paquete, usuario=usuario or self.tec, **kw)
        self.assertEqual(r.status_code, codigo, r.content)
        self.assertFalse(r.json()['ok'])
        self.assertTrue(r.json()['errores'])
        self.assertEqual(self.instantanea(o), antes)
        return r.json()['errores']

    def test_orden_cancelada_409_con_motivo(self):
        o = self.preparar()
        OrdenTrabajo.objects.filter(pk=o.pk).update(estado=OrdenTrabajo.CANCELADA, motivo_cancelacion='Cliente anuló')
        errores = self.rechaza(o, self.paquete(), 409)
        self.assertIn('Cliente anuló', errores[0])

    def test_estado_que_no_admite_cambios_409(self):
        o = self.preparar(OrdenTrabajo.PENDIENTE_APROBACION)
        self.rechaza(o, self.paquete(), 409)

    def test_sin_descarga_400(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        self.rechaza(o, self.paquete())

    def test_descarga_liberada_400(self):
        o = self.preparar()
        ordenes.liberar_descarga(o, self.peticion(self.gerente))
        self.rechaza(o, self.paquete())

    def test_otro_tecnico_403(self):
        o = self.preparar()
        self.rechaza(o, self.paquete(), 403, usuario=self.tec2)

    def test_gestion_403(self):
        o = self.preparar()
        self.rechaza(o, self.paquete(), 403, usuario=self.gerente)

    def test_inicio_anterior_a_la_descarga_400(self):
        o = self.preparar()
        errores = self.rechaza(o, self.paquete(inicio=(timezone.now() - timedelta(minutes=30)).isoformat()))
        self.assertIn('teléfono', errores[0])

    def test_inicio_futuro_400(self):
        o = self.preparar()
        errores = self.rechaza(o, self.paquete(inicio=(timezone.now() + timedelta(minutes=30)).isoformat()))
        self.assertIn('futuro', errores[0])

    def test_inicio_dentro_de_la_tolerancia_se_acepta(self):
        o = self.preparar()
        r = self.enviar(o, self.paquete(inicio=(timezone.now() + timedelta(minutes=2)).isoformat()), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)

    def test_inicio_sin_zona_horaria_400(self):
        o = self.preparar()
        self.rechaza(o, self.paquete(inicio='2026-10-09T10:00:00'))

    def test_inicio_obligatorio_si_asignada_400(self):
        o = self.preparar()
        p = self.paquete()
        del p['inicio']
        self.rechaza(o, p)

    def test_certificado_caducado_antes_del_inicio_400(self):
        # El certificado de `tec_caducado` caducó hace 5 días: el inicio (hace 30 h) ya cae fuera de vigencia.
        o = self.preparar(tecnico=self.tec_caducado, gas=True, descargada_hace=timedelta(hours=40))
        errores = self.rechaza(o, self.paquete(inicio=(timezone.now() - timedelta(hours=30)).isoformat()),
                               usuario=self.tec_caducado)
        self.assertIn('caducado', errores[0])

    def test_certificado_que_caduca_despues_del_inicio_es_valido(self):
        # Regla de producto: si el certificado estaba vigente el día del inicio, el trabajo se acepta aunque
        # el certificado caduque antes de que llegue la sincronización (siempre dentro del tope de antigüedad).
        o = self.preparar(tecnico=self.tec_caducado, gas=True, descargada_hace=timedelta(hours=40))
        inicio = timezone.now() - timedelta(hours=30)
        self.tec_caducado.perfil.cert_caducidad = timezone.localtime(inicio).date()  # vigente ese día, caducado hoy
        self.tec_caducado.perfil.save()
        r = self.enviar(o, self.paquete(inicio=inicio.isoformat()), usuario=self.tec_caducado)
        self.assertEqual(r.status_code, 200, r.content)

    # --- M-02: la hora de inicio declarada por el teléfono tiene tope -------------------------------
    def test_inicio_mas_de_48h_despues_de_la_descarga_400(self):
        o = self.preparar(descargada_hace=timedelta(hours=60))
        errores = self.rechaza(o, self.paquete(inicio=(timezone.now() - timedelta(hours=1)).isoformat()))
        self.assertIn('48 horas', errores[0])
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.ASIGNADA)

    def test_inicio_con_mas_de_48h_de_antiguedad_400(self):
        o = self.preparar(descargada_hace=timedelta(hours=50))
        errores = self.rechaza(o, self.paquete(inicio=(timezone.now() - timedelta(hours=49)).isoformat()))
        self.assertIn('antigüedad', errores[0])
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.ASIGNADA)

    def test_el_fraude_del_certificado_retrocediendo_el_inicio_queda_cerrado(self):
        # Descarga con el certificado vigente, trabaja días después y declara el inicio justo tras la descarga
        o = self.preparar(tecnico=self.tec_caducado, gas=True, descargada_hace=timedelta(days=7))
        self.tec_caducado.perfil.cert_caducidad = timezone.localtime(timezone.now() - timedelta(days=6)).date()
        self.tec_caducado.perfil.save()
        inicio = timezone.now() - timedelta(days=7) + timedelta(minutes=5)  # vigente ese día
        self.rechaza(o, self.paquete(inicio=inicio.isoformat()), usuario=self.tec_caducado)
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.ASIGNADA)

    def test_inicio_justo_dentro_de_los_topes_se_acepta(self):
        o = self.preparar(descargada_hace=timedelta(hours=47))
        r = self.enviar(o, self.paquete(inicio=(timezone.now() - timedelta(hours=46, minutes=30)).isoformat()), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)

    @override_settings(OFFLINE_VENTANA_HORAS=72)
    def test_la_ventana_se_puede_configurar(self):
        o = self.preparar(descargada_hace=timedelta(hours=70))
        r = self.enviar(o, self.paquete(inicio=(timezone.now() - timedelta(hours=60)).isoformat()), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)

    def test_el_evento_de_inicio_registra_la_diferencia_entre_declarado_y_recibido(self):
        o = self.preparar(descargada_hace=timedelta(hours=5))
        r = self.enviar(o, self.paquete(inicio=(timezone.now() - timedelta(hours=3, minutes=20)).isoformat()), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        texto = EventoOT.objects.filter(orden=o, texto__startswith='Intervención iniciada').first().texto
        self.assertIn('sin conexión', texto)
        self.assertIn('inicio declarado', texto)
        self.assertIn('diferencia 3 h 20 min', texto)
        self.assertLessEqual(len(texto), 255)

    def test_punto_desconocido_400_y_revierte_todo(self):
        o = self.preparar()
        self.rechaza(o, self.paquete(puntos=[{'codigo': 'INS_FILTROS', 'resultado': 'OK'},
                                             {'codigo': 'NO_EXISTE', 'resultado': 'OK'}], observaciones='x'))
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.ASIGNADA)
        self.assertIsNone(o.inicio)

    def test_medicion_fuera_de_rango_400_y_revierte_todo(self):
        o = self.preparar()
        errores = self.rechaza(o, self.paquete(puntos=[{'codigo': 'INS_FILTROS', 'resultado': 'OK'}],
                                               mediciones=[{'codigo': 'TENSION', 'valor': '5000'}]))
        self.assertIn('Tensión', errores[0])

    def test_incidencia_sin_gravedad_400(self):
        o = self.preparar()
        self.rechaza(o, self.paquete(puntos=[{'codigo': 'INS_FILTROS', 'resultado': 'INCIDENCIA'}]))

    def test_subsanacion_solo_bloque_indicado(self):
        o = self.preparar()
        ordenes.iniciar(o, self.peticion(self.tec))
        OrdenTrabajo.objects.filter(pk=o.pk).update(subsanacion_motivo='Falta medir', subsanacion_bloque='MEDICIONES')
        errores = self.rechaza(o, self.paquete(puntos=[{'codigo': 'INS_FILTROS', 'resultado': 'OK'}]))
        self.assertIn('Mediciones', errores[0])
        r = self.enviar(o, self.paquete(mediciones=[{'codigo': 'TENSION', 'valor': '230'}]), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)

    def test_subsanacion_reenviando_lo_ya_guardado_no_se_rechaza(self):
        o = self.preparar()
        req = self.peticion(self.tec)
        ordenes.iniciar(o, req)
        ordenes.marcar_punto(o, 'INS_FILTROS', 'OK', '', '', req)
        ordenes.marcar_punto(o, 'INS_BATERIA', 'INCIDENCIA', 'MEDIA', 'Sucia', req)
        ordenes.registrar_medicion(o, 'TENSION', '230', req)
        o.observaciones, o.materiales = 'Obs', 'Mat'
        o.save()
        OrdenTrabajo.objects.filter(pk=o.pk).update(subsanacion_motivo='Corrige la tensión', subsanacion_bloque='MEDICIONES')
        r = self.enviar(o, self.paquete(
            puntos=[{'codigo': 'INS_FILTROS', 'resultado': 'OK'},
                    {'codigo': 'INS_BATERIA', 'resultado': 'INCIDENCIA', 'gravedad': 'MEDIA', 'nota': 'Sucia'},
                    {'codigo': 'INS_FIJACIONES', 'resultado': ''}],
            mediciones=[{'codigo': 'TENSION', 'valor': '231'}, {'codigo': 'CORRIENTE', 'valor': ''}],
            observaciones='Obs', materiales='Mat', sin_materiales=False), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(str(o.mediciones.get(codigo='TENSION').valor), '231.00')

    def test_codigo_desconocido_se_rechaza_aunque_venga_sin_resultado(self):
        o = self.preparar()
        self.rechaza(o, self.paquete(puntos=[{'codigo': 'NO_EXISTE', 'resultado': ''}]))
        self.rechaza(o, self.paquete(mediciones=[{'codigo': 'NO_EXISTE', 'valor': ''}]))

    def test_caracter_nulo_400(self):
        o = self.preparar()
        self.rechaza(o, self.paquete(observaciones='hola\u0000mundo'))
        self.rechaza(o, self.paquete(mediciones=[{'codigo': 'TENSION', 'valor': '1\u0000'}]))

    def test_json_roto_400(self):
        self.rechaza(self.preparar(), None, bruto='{no es json')

    def test_sin_campo_paquete_400(self):
        o = self.preparar()
        self.client.force_login(self.tec)
        self.assertEqual(self.client.post(reverse('orden_sincronizar', args=[o.id])).status_code, 400)

    def test_json_que_no_es_objeto_400(self):
        self.rechaza(self.preparar(), None, bruto='[1, 2, 3]')

    def test_uuid_invalido_400(self):
        self.rechaza(self.preparar(), self.paquete(paquete_id='no-es-un-uuid'))

    def test_puntos_no_es_lista_400(self):
        self.rechaza(self.preparar(), self.paquete(puntos='INS_FILTROS'))

    def test_valores_de_tipo_incorrecto_400(self):
        o = self.preparar()
        self.rechaza(o, self.paquete(observaciones=5))
        self.rechaza(o, self.paquete(sin_materiales='si'))
        self.rechaza(o, self.paquete(puntos=[['INS_FILTROS', 'OK']]))
        self.rechaza(o, self.paquete(mediciones=[{'codigo': 'TENSION', 'valor': True}]))
        self.rechaza(o, self.paquete(firma='firmado'))

    def test_demasiados_puntos_400(self):
        o = self.preparar()
        self.rechaza(o, self.paquete(puntos=[{'codigo': f'P{i}', 'resultado': 'OK'} for i in range(101)]))

    def test_get_405(self):
        o = self.preparar()
        self.client.force_login(self.tec)
        self.assertEqual(self.client.get(reverse('orden_sincronizar', args=[o.id])).status_code, 405)

    def test_sin_sesion_redirige_al_acceso(self):
        o = self.preparar()
        url = reverse('orden_sincronizar', args=[o.id])
        self.assertRedirects(self.client.post(url), f"{reverse('login')}?next={url}", fetch_redirect_response=False)


class SincronizarEvidenciasTests(SincronizacionBase):
    def resumen_cliente(self, fotos=3):
        """Lo que la pantalla sin conexión mostraría al cliente: todo OK, mediciones en 10, sin materiales."""
        lineas = [f'{p.texto}: OK' for p in checklists.puntos_para(self.equipo.tipo, False)]
        lineas += [f'{m.etiqueta}: 10 {m.unidad}' for m in checklists.mediciones_para(self.equipo.tipo)]
        return lineas + ['Observaciones: ', 'Materiales: ninguno', f'Fotografías: {fotos}']

    def completo(self, fotos=3, **extra):
        return self.paquete(puntos=self.todos_ok(), mediciones=self.todas_medidas(), sin_materiales=True, **extra)

    def fotos(self, n):
        return [imagen_de_prueba(nombre=f'f{i}.jpg') for i in range(n)]

    def archivos_en_media(self):
        return sum(len(f) for _, _, f in os.walk(self._media))

    def test_sube_las_fotos_y_cuenta_en_el_evento(self):
        o = self.preparar()
        r = self.enviar(o, self.paquete(), fotos=self.fotos(2), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(o.fotos.count(), 2)
        self.assertTrue(EventoOT.objects.filter(orden=o, texto__contains='2 fotos').exists())

    def test_foto_invalida_400_revierte_todo(self):
        o = self.preparar()
        mala = SimpleUploadedFile('x.jpg', b'esto no es una imagen', 'image/jpeg')
        antes = self.instantanea(o)
        r = self.enviar(o, self.paquete(observaciones='x'), fotos=self.fotos(1) + [mala], usuario=self.tec)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.instantanea(o), antes)

    def test_veintiuna_fotos_400(self):
        o = self.preparar()
        antes = self.instantanea(o)
        r = self.enviar(o, self.paquete(), fotos=self.fotos(21), usuario=self.tec)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.instantanea(o), antes)
        self.assertEqual(self.archivos_en_media(), 0)

    def test_foto_de_mas_de_10mb_400(self):
        o = self.preparar()
        grande = SimpleUploadedFile('g.jpg', b'0' * (10 * 1024 * 1024 + 1), 'image/jpeg')
        r = self.enviar(o, self.paquete(), fotos=[grande], usuario=self.tec)
        self.assertEqual(r.status_code, 400)
        self.assertIn('10 MB', r.json()['errores'][0])

    def test_no_quedan_archivos_huerfanos_tras_revertir(self):
        o = self.preparar()
        mala = SimpleUploadedFile('x.jpg', b'no es imagen', 'image/jpeg')
        r = self.enviar(o, self.paquete(), fotos=self.fotos(2) + [mala], usuario=self.tec)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(FotoOT.objects.count(), 0)
        self.assertEqual(self.archivos_en_media(), 0)

    def test_firma_con_resumen_igual_se_guarda_vigente(self):
        o = self.preparar()
        firma = {'firmante': 'Cliente S.L.', 'imagen': png_en_base64(), 'resumen': self.resumen_cliente()}
        r = self.enviar(o, self.completo(firma=firma), fotos=self.fotos(3), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['firma'], 'guardada')
        self.assertEqual(r.json()['avisos'], [])
        o.refresh_from_db()
        self.assertTrue(evidencias.firma_vigente(o))
        self.assertEqual(FirmaOT.objects.get(orden=o).firmante, 'Cliente S.L.')

    def test_firma_del_tecnico_sin_conexion_se_guarda_tras_la_del_cliente(self):
        o = self.preparar()
        firma = {'firmante': 'Cliente S.L.', 'imagen': png_en_base64(), 'resumen': self.resumen_cliente()}
        ft = {'imagen': png_en_base64(), 'resumen': self.resumen_cliente()}
        r = self.enviar(o, self.completo(firma=firma, firma_tecnico=ft), fotos=self.fotos(3), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        datos = r.json()
        self.assertEqual((datos['firma'], datos['firma_tecnico']), ('guardada', 'guardada'))
        self.assertEqual(datos['firma_tecnico_estado'], 'vigente')
        self.assertEqual(datos['firma_tecnico_resumen'], self.resumen_cliente())
        self.assertEqual(datos['faltan'], [])

    def test_firma_del_tecnico_sin_firma_del_cliente_se_descarta_con_aviso(self):
        o = self.preparar()
        ft = {'imagen': png_en_base64(), 'resumen': self.resumen_cliente()}
        r = self.enviar(o, self.completo(firma_tecnico=ft), fotos=self.fotos(3), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['firma_tecnico'], 'descartada')
        self.assertIn('cliente debe firmar antes', ' '.join(r.json()['avisos']))
        self.assertIn('Falta la firma del técnico', r.json()['faltan'])

    def test_firma_del_tecnico_con_resumen_distinto_se_descarta(self):
        o = self.preparar()
        firma = {'firmante': 'Cliente S.L.', 'imagen': png_en_base64(), 'resumen': self.resumen_cliente()}
        ft = {'imagen': png_en_base64(), 'resumen': ['otra cosa']}
        r = self.enviar(o, self.completo(firma=firma, firma_tecnico=ft), fotos=self.fotos(3), usuario=self.tec)
        self.assertEqual(r.json()['firma_tecnico'], 'descartada')

    def test_firma_con_resumen_distinto_se_descarta_y_guarda_el_resto(self):
        o = self.preparar()
        firma = {'firmante': 'Cliente', 'imagen': png_en_base64(), 'resumen': ['otra cosa']}
        r = self.enviar(o, self.completo(firma=firma), fotos=self.fotos(3), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['firma'], 'descartada')
        self.assertIn('firmar de nuevo', r.json()['avisos'][0])
        self.assertFalse(FirmaOT.objects.filter(orden=o).exists())
        self.assertEqual(o.fotos.count(), 3)
        self.assertEqual(o.puntos.exclude(resultado='OK').count(), 0)
        self.assertIn('Falta la firma del cliente', r.json()['faltan'])

    def test_firma_en_blanco_se_descarta_con_aviso(self):
        o = self.preparar()
        firma = {'firmante': 'Cliente', 'imagen': png_en_base64(trazos=False), 'resumen': self.resumen_cliente()}
        r = self.enviar(o, self.completo(firma=firma), fotos=self.fotos(3), usuario=self.tec)
        self.assertEqual(r.json()['firma'], 'descartada')
        self.assertIn('blanco', r.json()['avisos'][0])
        self.assertFalse(FirmaOT.objects.filter(orden=o).exists())

    def test_firma_sin_nombre_se_descarta(self):
        o = self.preparar()
        firma = {'firmante': '', 'imagen': png_en_base64(), 'resumen': self.resumen_cliente()}
        r = self.enviar(o, self.completo(firma=firma), fotos=self.fotos(3), usuario=self.tec)
        self.assertEqual(r.json()['firma'], 'descartada')

    def test_firma_en_orden_sin_evidencias_se_descarta(self):
        o = self.preparar()
        o.con_checklist = False
        o.save()
        firma = {'firmante': 'Cliente', 'imagen': png_en_base64(), 'resumen': []}
        r = self.enviar(o, self.paquete(firma=firma, observaciones='x'), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['firma'], 'descartada')

    def test_sin_firma_responde_ninguna(self):
        o = self.preparar()
        r = self.enviar(o, self.paquete(), usuario=self.tec)
        self.assertEqual(r.json()['firma'], 'ninguna')

    def test_resumen_de_referencia(self):
        """Contrato con la pantalla sin conexión (5b): estas líneas deben salir idénticas en el teléfono."""
        o = self.preparar()
        req = self.peticion(self.tec)
        ordenes.iniciar(o, req)
        ordenes.marcar_punto(o, 'INS_FILTROS', 'OK', '', '', req)
        ordenes.marcar_punto(o, 'INS_BATERIA', 'INCIDENCIA', 'ALTA', 'Fuga', req)
        ordenes.registrar_medicion(o, 'TENSION', '230', req)
        o.observaciones, o.materiales = 'Revisión completa', 'Filtro x2'
        o.save()
        for i in range(3):
            evidencias.subir_foto(o, imagen_de_prueba(nombre=f'f{i}.jpg'), req)
        self.assertEqual(evidencias.resumen_para_firma(o), [
            'Estado de los filtros: OK',
            'Estado del serpentín: Incidencia Alta. Fuga',
            'Fijaciones y soportes en buen estado: sin marcar',
            'Aislamiento de las tuberías en buen estado: sin marcar',
            'Limpieza general del equipo: sin marcar',
            'Limpieza de la unidad interior: sin marcar',
            'Señal de arranque y contactor-compresor correctos: sin marcar',
            'Ventilación correcta: sin marcar',
            'Drenaje de condensación correcto: sin marcar',
            'Funcionamiento estable, sin vibraciones anómalas: sin marcar',
            'Sin fugas visibles de refrigerante, agua helada o aceite: sin marcar',
            'Temperatura de inyección: sin medir',
            'Temperatura de retorno: sin medir',
            'Tensión: 230 V',
            'Corriente: sin medir',
            'Presión alta: sin medir',
            'Presión baja: sin medir',
            'Observaciones: Revisión completa',
            'Materiales: Filtro x2',
            'Fotografías: 3',
        ])

    def test_flujo_completo_deja_la_orden_lista_para_enviar(self):
        o = self.preparar()
        firma = {'firmante': 'Cliente S.L.', 'imagen': png_en_base64(), 'resumen': self.resumen_cliente()}
        r = self.enviar(o, self.completo(firma=firma), fotos=self.fotos(3), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        # Sin firma del técnico en el paquete, es lo único que falta tras sincronizar.
        self.assertEqual(r.json()['faltan'], ['Falta la firma del técnico'])
        evidencias.guardar_firma_tecnico(o, png_en_base64(), self.peticion(self.tec))
        o.refresh_from_db()
        self.assertEqual(ordenes.validar_envio(o), [])
        ordenes.enviar(o, self.peticion(self.tec))
        o.refresh_from_db()
        self.assertEqual(o.estado, OrdenTrabajo.PENDIENTE_APROBACION)

    def test_misma_foto_con_mismo_identificador_no_se_duplica(self):
        o = self.preparar()
        ids = [str(uuid.uuid4()) for _ in range(2)]
        r1 = self.enviar(o, self.paquete(fotos_ids=ids), fotos=self.fotos(2), usuario=self.tec)
        self.assertEqual(r1.status_code, 200, r1.content)
        # El teléfono no recibió la respuesta y reenvía con otro paquete_id y las mismas fotos.
        r2 = self.enviar(o, self.paquete(fotos_ids=ids), fotos=self.fotos(2), usuario=self.tec)
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(o.fotos.count(), 2)
        self.assertEqual(self.archivos_en_media(), 2)

    def test_fotos_e_identificadores_deben_coincidir(self):
        o = self.preparar()
        r = self.enviar(o, self.paquete(fotos_ids=[str(uuid.uuid4())]), fotos=self.fotos(2), usuario=self.tec)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(o.fotos.count(), 0)

    def test_identificador_de_foto_incorrecto_400(self):
        o = self.preparar()
        r = self.enviar(o, self.paquete(fotos_ids=['no-es-uuid']), fotos=self.fotos(1), usuario=self.tec)
        self.assertEqual(r.status_code, 400)

    def test_paquete_sin_identificadores_sigue_funcionando(self):
        o = self.preparar()
        r = self.enviar(o, self.paquete(), fotos=self.fotos(1), usuario=self.tec)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(o.fotos.count(), 1)

    def test_respuesta_informa_del_estado_real_de_la_firma(self):
        o = self.preparar()
        firma = {'firmante': 'Cliente S.L.', 'imagen': png_en_base64(), 'resumen': self.resumen_cliente()}
        r = self.enviar(o, self.completo(firma=firma), fotos=self.fotos(3), usuario=self.tec).json()
        self.assertEqual(r['firma_estado'], 'vigente')
        self.assertEqual(r['firma_resumen'], self.resumen_cliente())
        r2 = self.enviar(o, self.paquete(observaciones='Cambio posterior'), usuario=self.tec).json()
        self.assertEqual(r2['firma_estado'], 'obsoleta')
        self.assertIsNone(r2['firma_resumen'])

    def test_descarga_incluye_resumen_firmado_solo_si_es_vigente(self):
        o = self.preparar()
        self.client.force_login(self.tec)
        sin = self.client.post(reverse('orden_descargar', args=[o.id])).json()['paquete']
        self.assertIsNone(sin['estado_actual']['firma_resumen'])
        firma = {'firmante': 'Cliente S.L.', 'imagen': png_en_base64(), 'resumen': self.resumen_cliente()}
        self.enviar(o, self.completo(firma=firma), fotos=self.fotos(3), usuario=self.tec)
        vigente = self.client.post(reverse('orden_descargar', args=[o.id])).json()['paquete']
        self.assertEqual(vigente['estado_actual']['firma_resumen'], self.resumen_cliente())
        self.enviar(o, self.paquete(observaciones='Otra'), usuario=self.tec)
        obsoleta = self.client.post(reverse('orden_descargar', args=[o.id])).json()['paquete']
        self.assertTrue(obsoleta['estado_actual']['firma'])
        self.assertIsNone(obsoleta['estado_actual']['firma_resumen'])


class GestionDescargaTests(SincronizacionBase):
    def detalle(self, o, usuario):
        self.client.force_login(usuario)
        return self.client.get(reverse('orden_detalle', args=[o.id]))

    def test_gestion_ve_aviso_y_boton_liberar(self):
        o = self.preparar()
        for u in (self.gerente, self.admin):
            r = self.detalle(o, u)
            self.assertContains(r, 'Descargada por el técnico el')
            self.assertContains(r, reverse('orden_liberar_descarga', args=[o.id]))
            self.assertTrue(r.context['puede_liberar'])

    def test_tecnico_no_ve_liberar(self):
        o = self.preparar()
        r = self.detalle(o, self.tec)
        self.assertNotContains(r, reverse('orden_liberar_descarga', args=[o.id]))
        self.assertNotContains(r, 'Descargada por el técnico el')

    def test_sin_descarga_no_hay_aviso(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        r = self.detalle(o, self.gerente)
        self.assertNotContains(r, 'Descargada por el técnico el')
        self.assertFalse(r.context['descarga_activa'])

    def test_formulario_de_reasignar_deshabilitado_con_motivo(self):
        o = self.preparar()
        r = self.detalle(o, self.gerente)
        self.assertTrue(r.context['form_asignar'].fields['tecnico'].disabled)
        self.assertContains(r, 'No se puede reasignar: el técnico descargó la orden')

    def test_liberar_post_limpia_y_avisa(self):
        o = self.preparar()
        self.client.force_login(self.gerente)
        r = self.client.post(reverse('orden_liberar_descarga', args=[o.id]), follow=True)
        self.assertContains(r, 'Descarga liberada')
        o.refresh_from_db()
        self.assertIsNone(o.descargada_en)

    def test_liberar_solo_gestion(self):
        o = self.preparar()
        self.client.force_login(self.tec)
        self.assertEqual(self.client.post(reverse('orden_liberar_descarga', args=[o.id])).status_code, 403)
        o.refresh_from_db()
        self.assertIsNotNone(o.descargada_en)

    def test_liberar_get_405(self):
        o = self.preparar()
        self.client.force_login(self.gerente)
        self.assertEqual(self.client.get(reverse('orden_liberar_descarga', args=[o.id])).status_code, 405)

    def test_liberar_sin_descarga_muestra_error(self):
        o = self.orden(OrdenTrabajo.ASIGNADA, tecnico=self.tec)
        self.client.force_login(self.gerente)
        r = self.client.post(reverse('orden_liberar_descarga', args=[o.id]), follow=True)
        self.assertContains(r, 'no está descargada')

    def test_reasignar_por_post_con_descarga_muestra_error(self):
        o = self.preparar()
        self.client.force_login(self.gerente)
        r = self.client.post(reverse('orden_asignar', args=[o.id]), {'tecnico': self.tec2.id}, follow=True)
        self.assertContains(r, 'ya descargó')
        o.refresh_from_db()
        self.assertEqual(o.tecnico, self.tec)

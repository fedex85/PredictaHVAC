"""Envío automático del informe PDF al cliente al finalizar una OT.

Destinatarios: los de la ficha del cliente en el momento de finalizar, guardados en la propia OT (instantánea).
Un intento inicial y dos reintentos (comando `enviar_informes`); si falla el tercero se avisa a gestión, que puede
reenviar a mano con los destinatarios guardados o descargar el PDF.
"""
import logging
from datetime import timedelta
from types import SimpleNamespace

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from core import avisos, informe_ot
from core.models import EnvioInforme, OrdenTrabajo, separar_correos

logger = logging.getLogger(__name__)

ESPERA_REINTENTO = timedelta(minutes=5)
_AUTOMATICO = SimpleNamespace(get_full_name=lambda: 'envío automático', get_username=lambda: 'envío automático')


def preparar(orden):
    """Al finalizar: guarda la instantánea de destinatarios y programa el envío. Llamar dentro de la transacción."""
    inst = orden.equipo.instalacion
    correos = inst.cliente.lista_destinatarios if inst else []
    orden.destinatarios_informe = '\n'.join(correos)
    orden.save(update_fields=['destinatarios_informe'])
    if not correos:
        avisos.notificar_gestion(f'{orden.codigo} finalizada sin destinatarios para el informe: no se envió al cliente. '
                                 'Descárgalo desde la orden.', orden)
        return None
    envio = EnvioInforme.objects.create(orden=orden)
    transaction.on_commit(lambda: intentar(envio.pk))
    return envio


def _enviar(orden, generado_por):
    pdf = informe_ot.generar_informe_ot(orden, generado_por)
    mensaje = EmailMessage(
        subject=f'Informe de intervención {orden.codigo} · {orden.equipo.codigo_identificador}',
        body=(f'Adjuntamos el informe de la intervención {orden.codigo} sobre el equipo '
              f'{orden.equipo.nombre} ({orden.equipo.codigo_identificador}).\n\nUn saludo.'),
        from_email=settings.DEFAULT_FROM_EMAIL, to=separar_correos(orden.destinatarios_informe))
    mensaje.attach(f'informe_{orden.codigo}.pdf', pdf, 'application/pdf')
    mensaje.send(fail_silently=False)


def intentar(envio_id, generado_por=None):
    """Un intento de envío. Devuelve el estado resultante. Nunca lanza: el fallo queda anotado."""
    with transaction.atomic():
        envio = EnvioInforme.objects.select_for_update().select_related('orden__equipo').filter(pk=envio_id).first()
        if envio is None or envio.estado != EnvioInforme.PENDIENTE:
            return envio.estado if envio else None
        orden = envio.orden
        envio.intentos += 1
        envio.ultimo_intento = timezone.now()
        try:
            _enviar(orden, generado_por or _AUTOMATICO)
        except Exception as e:
            logger.warning('Fallo al enviar el informe de %s (intento %s)', orden.codigo, envio.intentos, exc_info=True)
            envio.ultimo_error = f'{type(e).__name__}: {e}'[:255]
            if envio.intentos >= EnvioInforme.MAX_INTENTOS:
                envio.estado = EnvioInforme.FALLIDO
                avisos.notificar_gestion(
                    f'No se pudo enviar el informe de {orden.codigo} al cliente tras {envio.intentos} intentos. '
                    'Reenvíalo o descárgalo desde la orden.', orden)
        else:
            envio.estado, envio.enviado_en, envio.ultimo_error = EnvioInforme.ENVIADO, timezone.now(), ''
        envio.save()
        return envio.estado


def reintentos_pendientes(ahora=None):
    """Envíos pendientes cuyo último intento tiene más de ESPERA_REINTENTO (o que no llegaron a intentarse)."""
    ahora = ahora or timezone.now()
    limite = ahora - ESPERA_REINTENTO
    return [e.pk for e in EnvioInforme.objects.filter(estado=EnvioInforme.PENDIENTE)
            if e.ultimo_intento is None or e.ultimo_intento <= limite]


def reenviar_manual(orden, usuario):
    """Gestión reenvía a los destinatarios guardados en la OT (un intento, sin límite de veces). ReglaError si no se puede."""
    from core.ordenes import ReglaError
    if orden.estado != OrdenTrabajo.FINALIZADA:
        raise ReglaError('Solo se envía el informe de una orden finalizada.')
    if not separar_correos(orden.destinatarios_informe):
        raise ReglaError('Esta orden no tiene destinatarios guardados. Descarga el informe y envíalo por otro medio.')
    envio, _ = EnvioInforme.objects.get_or_create(orden=orden)
    envio.estado, envio.intentos = EnvioInforme.PENDIENTE, EnvioInforme.MAX_INTENTOS - 1
    envio.save()
    resultado = intentar(envio.pk, usuario)
    if resultado != EnvioInforme.ENVIADO:
        envio.refresh_from_db()
        raise ReglaError(f'No se pudo enviar el informe: {envio.ultimo_error or "error desconocido"}')

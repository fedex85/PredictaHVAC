"""Asistente IA: validación de lo que envía el navegador y límite de consultas por usuario."""
import json
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from core.models import RegistroActividad

MAX_MENSAJE = 1000
MAX_TURNOS = 6                 # pares pregunta/respuesta que se reenvían a la IA
MAX_TEXTO_HISTORIAL = 4000     # una respuesta de la IA puede ser larga
ROLES_HISTORIAL = ('user', 'assistant')


class ConsultaInvalida(Exception):
    """Dato recibido del navegador que no se puede aceptar; el texto es seguro de mostrar al usuario."""


def limite_por_hora():
    return int(getattr(settings, 'IA_LIMITE_POR_HORA', 20))


def consultas_en_la_ultima_hora(usuario):
    desde = timezone.now() - timedelta(hours=1)
    return RegistroActividad.objects.filter(usuario=usuario, accion=RegistroActividad.CONSULTA_IA, fecha__gte=desde).count()


def limite_superado(usuario):
    return consultas_en_la_ultima_hora(usuario) >= limite_por_hora()


def validar_mensaje(texto):
    texto = (texto or '').strip()
    if not texto:
        raise ConsultaInvalida('El mensaje no puede estar vacío.')
    if len(texto) > MAX_MENSAJE:
        raise ConsultaInvalida(f'El mensaje es demasiado largo (máximo {MAX_MENSAJE} caracteres).')
    return texto


def validar_historial(crudo):
    """JSON de [{role, content}] -> lista limpia con los últimos turnos. Lo malformado se rechaza; lo ajeno se descarta."""
    if not crudo:
        return []
    try:
        datos = json.loads(crudo)
    except (TypeError, ValueError):
        raise ConsultaInvalida('El historial de la conversación no es válido.')
    if not isinstance(datos, list):
        raise ConsultaInvalida('El historial de la conversación no es válido.')
    limpio = []
    for item in datos:
        if not isinstance(item, dict) or item.get('role') not in ROLES_HISTORIAL or not isinstance(item.get('content'), str):
            continue
        contenido = item['content'].strip()[:MAX_TEXTO_HISTORIAL]
        if contenido:
            limpio.append({'role': item['role'], 'content': contenido})
    return limpio[-MAX_TURNOS * 2:]

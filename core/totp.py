"""Códigos de un solo uso basados en el tiempo (TOTP, RFC 6238) con la librería estándar.

Compatible con Google Authenticator, Microsoft Authenticator, Authy, 1Password, etc.
SHA-1, 6 dígitos, intervalos de 30 segundos.
"""
import base64
import hmac
import secrets
import struct
import time
from hashlib import sha1
from urllib.parse import quote

INTERVALO = 30
DIGITOS = 6


def nuevo_secreto():
    """Secreto aleatorio de 160 bits en base32 (32 caracteres)."""
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii')


def _clave(secreto):
    secreto = secreto.replace(' ', '').upper()
    return base64.b32decode(secreto + '=' * (-len(secreto) % 8))


def codigo_para(secreto, paso, digitos=DIGITOS):
    """Código TOTP del intervalo `paso` (segundos Unix // 30)."""
    h = hmac.new(_clave(secreto), struct.pack('>Q', paso), sha1).digest()
    desplazamiento = h[-1] & 0x0F
    numero = struct.unpack('>I', h[desplazamiento:desplazamiento + 4])[0] & 0x7FFFFFFF
    return str(numero % 10 ** digitos).zfill(digitos)


def verificar(secreto, entrada, ultimo_paso=0, ahora=None, ventana=1):
    """Devuelve el intervalo aceptado si `entrada` es válida, o None.

    Acepta ±`ventana` intervalos (desfase de reloj del teléfono) y rechaza cualquier intervalo
    igual o anterior a `ultimo_paso`, de modo que un código no se puede reutilizar.
    """
    entrada = ''.join(str(entrada or '').split())
    if len(entrada) != DIGITOS or not (entrada.isascii() and entrada.isdigit()):
        return None
    actual = int((time.time() if ahora is None else ahora) // INTERVALO)
    aceptado = None
    for paso in range(actual - ventana, actual + ventana + 1):
        # Se recorren todos los intervalos sin cortar antes, para que el tiempo no dependa de cuál acierta.
        if hmac.compare_digest(codigo_para(secreto, paso), entrada) and paso > ultimo_paso:
            aceptado = paso
    return aceptado


def uri_aprovisionamiento(secreto, cuenta, emisor='PredictaHVAC'):
    """URI otpauth:// que las apps de autenticación leen desde un código QR."""
    return (f'otpauth://totp/{quote(emisor)}:{quote(cuenta)}?secret={secreto}&issuer={quote(emisor)}'
            f'&algorithm=SHA1&digits={DIGITOS}&period={INTERVALO}')

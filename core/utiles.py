"""Utilidades pequeñas para validar entradas del usuario."""
import re


def entero_o_none(texto, max_digitos=9):
    """Convierte a int solo cadenas formadas por dígitos ASCII (0-9) y de longitud razonable; si no, None.

    `str.isdigit()` no basta: acepta caracteres como «²» o dígitos de otros alfabetos, y `int()` falla con ellos
    (error 500), y un número larguísimo desborda la columna entera de la base de datos.
    """
    t = str(texto or '').strip()
    if t.isascii() and t.isdecimal() and 0 < len(t) <= max_digitos:
        return int(t)
    return None


def nombre_archivo_seguro(texto, por_defecto='archivo'):
    """Texto apto para el nombre de un archivo en una cabecera Content-Disposition (solo A-Z a-z 0-9 . _ -)."""
    limpio = re.sub(r'[^A-Za-z0-9._-]+', '_', str(texto or '')).strip('._')
    return limpio[:80] or por_defecto

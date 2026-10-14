"""QR de la ficha de un equipo: apunta a la URL de su ficha técnica para escanearlo en campo."""
import io

import segno
from django.urls import reverse
from django.utils.safestring import mark_safe


def url_ficha(request, equipo):
    """URL absoluta de la ficha, con el host y el esquema desde los que se pidió la página."""
    return request.build_absolute_uri(reverse('detalle_equipo', args=[equipo.id]))


def svg_qr(url):
    """QR en SVG sin tamaño fijo (se dimensiona con CSS), con corrección de errores alta y margen de silencio."""
    salida = io.BytesIO()
    segno.make(url, error='h').save(salida, kind='svg', scale=1, border=2, xmldecl=False, omitsize=True,
                                     dark='#000000', light='#ffffff')
    return mark_safe(salida.getvalue().decode('utf-8'))

"""Dibujo del informe PDF de una orden (fase 2, parte 4): solo reportlab, sin acceso a la base de datos.

`dibujar(datos, firma_png, generado)` recibe el diccionario de `informe_ot.datos_informe`.
"""
import io
import logging
from pathlib import Path

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import (BaseDocTemplate, Frame, HRFlowable, Image, KeepTogether, NextPageTemplate,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

from core.pdf_service import _texto

logger = logging.getLogger(__name__)

MARINO = colors.HexColor('#0B1E47')
CIAN = colors.HexColor('#0A6BFF')
TEXTO = colors.HexColor('#374151')
GRIS = colors.HexColor('#6B7280')
LINEA = colors.HexColor('#D8DEE6')
ZEBRA = colors.HexColor('#F3F6FA')
CLARO = colors.HexColor('#BFD3E6')
ROJO = '#B91C1C'

MARGEN = 40
ANCHO = A4[0] - 2 * MARGEN
PIE = 46

# Etiqueta con color Y con texto: se entiende también impreso en blanco y negro.
ETIQUETAS = {
    'OK': ('#047857', '#D1FAE5'),
    'Incidencia Alta': ('#B91C1C', '#FEE2E2'),
    'Incidencia Media': ('#B45309', '#FEF3C7'),
    'Incidencia Leve': ('#1D4ED8', '#DBEAFE'),
    'Sin marcar': ('#4B5563', '#E5E7EB'),
}
INSIGNIAS = {'PROVISIONAL': ('#92400E', '#FEF3C7'), 'DEFINITIVO': ('#065F46', '#D1FAE5')}


def _estilo(nombre, **kw):
    base = dict(fontName='Helvetica', fontSize=9, leading=12, textColor=TEXTO)
    base.update(kw)
    return ParagraphStyle(nombre, **base)


_NORMAL = _estilo('InfNormal')
_ETIQUETA = _estilo('InfEtiqueta', fontName='Helvetica-Bold', fontSize=7.5, leading=10, textColor=GRIS)
_TITULO = _estilo('InfTitulo', fontName='Helvetica-Bold', fontSize=20, leading=24, textColor=MARINO)
_SUBTITULO = _estilo('InfSubtitulo', fontSize=9.5, textColor=GRIS, spaceAfter=10)
_SECCION = _estilo('InfSeccion', fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=MARINO, spaceBefore=14)
_BLOQUE = _estilo('InfBloque', fontName='Helvetica-Bold', fontSize=9, leading=12, textColor=MARINO, spaceBefore=6, spaceAfter=3)
_CIFRA = _estilo('InfCifra', fontName='Helvetica-Bold', fontSize=17, leading=20, textColor=MARINO)
_DECISION = _estilo('InfDecision', fontSize=8, leading=10.5, textColor=GRIS, leftIndent=6)
_RESULTADO = _estilo('InfResultado', fontSize=10, leading=14)


def _fecha(valor):
    return timezone.localtime(valor).strftime('%d/%m/%Y %H:%M') if valor else '—'


def _p(texto, estilo=_NORMAL):
    texto = str(texto)
    return Paragraph(_texto(texto) if texto.strip() else '—', estilo)


def _etiqueta(resultado):
    """Párrafo con el resultado de un punto como etiqueta de color."""
    fg, fondo = ETIQUETAS.get(resultado, ETIQUETAS['Sin marcar'])
    return Paragraph(f'<font color="{fg}" backColor="{fondo}">&nbsp;<b>{_texto(resultado)}</b>&nbsp;</font>', _NORMAL)


def _seccion(titulo):
    return [Paragraph(_texto(titulo), _SECCION), HRFlowable(width='100%', thickness=0.8, color=CIAN, spaceBefore=2, spaceAfter=6)]


def _tabla(filas, anchos, cabecera=False):
    """Tabla sin rejilla: líneas finas entre filas y, si hay cabecera, filas alternas."""
    # splitInRow: una celda con mucho texto (observaciones, justificación) puede ocupar más de una página
    tabla = Table(filas, colWidths=anchos, repeatRows=1 if cabecera else 0, splitInRow=1)
    estilo = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LINEBELOW', (0, 0), (-1, -1), 0.3, LINEA),
              ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
              ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5)]
    if cabecera:
        estilo += [('LINEBELOW', (0, 0), (-1, 0), 0.8, MARINO), ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, ZEBRA])]
    tabla.setStyle(TableStyle(estilo))
    return tabla


def _resumen(d):
    r = d['resumen']
    cifras = [('Tiempo trabajado', d['tiempo_efectivo']),
              ('Puntos revisados', f"{r['ok']}/{r['puntos']}" if r['puntos'] else '—'),
              ('Incidencias', str(r['incidencias']) if r['puntos'] else '—'),
              ('Mediciones', f"{r['mediciones_tomadas']}/{r['mediciones']}" if r['mediciones'] else '—')]
    ancho = ANCHO / 4
    fila = [[[Paragraph(_texto(valor), _CIFRA), Paragraph(etiqueta, _ETIQUETA)] for etiqueta, valor in cifras]]
    tabla = Table(fila, colWidths=[ancho] * 4)
    tabla.setStyle(TableStyle([('LINEABOVE', (0, 0), (-1, 0), 0.8, CIAN), ('LINEBELOW', (0, 0), (-1, 0), 0.8, CIAN),
                               ('LINEAFTER', (0, 0), (-2, 0), 0.4, LINEA), ('TOPPADDING', (0, 0), (-1, -1), 8),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 8), ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    resultado = Table([[Paragraph(_texto(r['frase']), _RESULTADO)]], colWidths=[ANCHO])
    resultado.setStyle(TableStyle([('LINEBEFORE', (0, 0), (0, 0), 3, CIAN), ('BACKGROUND', (0, 0), (0, 0), ZEBRA),
                                   ('TOPPADDING', (0, 0), (0, 0), 7), ('BOTTOMPADDING', (0, 0), (0, 0), 7),
                                   ('LEFTPADDING', (0, 0), (0, 0), 10)]))
    return [tabla, Spacer(1, 8), resultado]


def _datos_generales(d):
    pausas = '; '.join(f"{p['motivo']} ({_fecha(p['desde'])} a {_fecha(p['hasta'])})" for p in d['pausas']) or 'Sin pausas'
    filas = [[_p('Equipo', _ETIQUETA), _p(d['equipo']), _p('Tipo', _ETIQUETA), _p(d['tipo'])],
             [_p('Técnico', _ETIQUETA), _p(d['tecnico']), _p('Estado', _ETIQUETA), _p(d['estado'])],
             [_p('Inicio', _ETIQUETA), _p(_fecha(d['inicio'])), _p('Fin', _ETIQUETA), _p(_fecha(d['fin']))],
             [_p('Pausas', _ETIQUETA), _p(pausas), '', '']]
    tabla = _tabla(filas, [60, 205, 50, ANCHO - 315])
    tabla.setStyle(TableStyle([('SPAN', (1, 3), (3, 3))]))
    return _seccion('Datos generales') + [tabla]


def _detalle(p):
    partes = []
    if p['nota']:
        partes.append(Paragraph(_texto(p['nota']), _NORMAL))
    dec = p['decision']
    if dec:
        quien = f"Por {_texto(dec['por'])}, {_fecha(dec['en'])}"
        if dec['tipo'] == 'CORRECTIVA':
            partes.append(Paragraph(f"<b>Decisión: correctiva {_texto(dec['correctiva'])}.</b> {quien}", _DECISION))
        else:
            partes.append(Paragraph(f"<b>Decisión: justificada.</b> {_texto(dec['justificacion'])} {quien}", _DECISION))
    elif p['alta_pendiente']:
        partes.append(Paragraph(f'<font color="{ROJO}"><b>Pendiente de resolver</b></font>', _NORMAL))
    return partes or Paragraph('—', _NORMAL)


def _checklist(d):
    if not d['puntos']:
        return []
    historia = _seccion('Checklist')
    bloques = []
    for p in d['puntos']:
        if not bloques or bloques[-1][0] != p['bloque']:
            bloques.append((p['bloque'], []))
        bloques[-1][1].append(p)
    for nombre, puntos in bloques:
        filas = [[_p('Punto', _ETIQUETA), _p('Resultado', _ETIQUETA), _p('Detalle', _ETIQUETA)]]
        filas += [[_p(p['texto']), _etiqueta(p['resultado']), _detalle(p)] for p in puntos]
        historia += [Paragraph(_texto(nombre), _BLOQUE), _tabla(filas, [190, 90, ANCHO - 280], True)]
    return historia


def _mediciones(d):
    if not d['mediciones']:
        return []
    filas = [[_p(t, _ETIQUETA) for t in ('Medición', 'Valor', 'Unidad', 'Rango permitido')]]
    filas += [[_p(m['etiqueta']), _p(m['valor']), _p(m['unidad']), _p(m['rango'])] for m in d['mediciones']]
    return _seccion('Mediciones') + [_tabla(filas, [215, 90, 60, ANCHO - 365], True)]


def _texto_libre(d):
    filas = [[_p('Materiales', _ETIQUETA), _p(d['materiales'])], [_p('Observaciones', _ETIQUETA), _p(d['observaciones'])]]
    return _seccion('Materiales y observaciones') + [_tabla(filas, [90, ANCHO - 90])]


def _imagen_firma(firma_png):
    """Imagen de la firma ajustada a 200 x 100 pt sea cual sea su proporción; None si no se puede leer."""
    if not firma_png:
        return None
    try:
        ancho, alto = ImageReader(io.BytesIO(firma_png)).getSize()
        escala = min(200 / ancho, 100 / alto, 1)
        return Image(io.BytesIO(firma_png), width=ancho * escala, height=alto * escala, mask='auto')
    except Exception:  # imagen corrupta: el informe sigue sin ella
        logger.warning('La imagen de la firma no se pudo leer para el informe', exc_info=True)
        return None


def _firma(d, firma_png, titulo='Firma del cliente', clave='firma', sin='Sin firma del cliente.'):
    firma = d[clave]
    historia = _seccion(titulo)
    if firma['estado'] == 'sin':
        return historia + [Paragraph(f'<i>{sin}</i>', _NORMAL)]
    contenido = [_imagen_firma(firma_png) or Paragraph('<i>Firma no disponible.</i>', _NORMAL), Spacer(1, 6),
                 Paragraph(f"<b>{_texto(firma['firmante'])}</b>", _NORMAL),
                 Paragraph(f"{_fecha(firma['fecha'])} · firma manuscrita digital", _ETIQUETA)]
    if firma['estado'] == 'obsoleta':
        contenido += [Spacer(1, 4), Paragraph(
            f'<font color="{ROJO}"><b>El resumen cambió después de firmar: esta firma ya no es vigente.</b></font>', _NORMAL)]
    caja = Table([[contenido]], colWidths=[260])
    caja.setStyle(TableStyle([('BOX', (0, 0), (0, 0), 0.8, LINEA), ('LEFTPADDING', (0, 0), (0, 0), 12),
                              ('TOPPADDING', (0, 0), (0, 0), 10), ('BOTTOMPADDING', (0, 0), (0, 0), 10)]))
    caja.hAlign = 'LEFT'
    return historia + [KeepTogether([caja])]


def _insignia(lienzo, version, x_derecha, y, alto=15):
    """Pastilla PROVISIONAL / DEFINITIVO con el borde derecho en x_derecha."""
    fg, fondo = INSIGNIAS[version]
    ancho = stringWidth(version, 'Helvetica-Bold', 8) + 16
    lienzo.setFillColor(colors.HexColor(fondo))
    lienzo.roundRect(x_derecha - ancho, y, ancho, alto, 7, stroke=0, fill=1)
    lienzo.setFillColor(colors.HexColor(fg))
    lienzo.setFont('Helvetica-Bold', 8)
    lienzo.drawCentredString(x_derecha - ancho / 2, y + 4.6, version)
    return ancho


LOGO = Path(__file__).resolve().parent / 'static' / 'img' / 'icono-app.png'


def _dibujar_logo(lienzo, x, y, lado):
    """Dibuja el ícono de la app (esquinas redondeadas) y devuelve lo que hay que desplazar el texto; 0 si falta el archivo."""
    try:
        imagen = ImageReader(str(LOGO))
    except Exception:  # el informe no debe fallar por un logo ausente o ilegible
        logger.warning('No se pudo cargar el logo del informe: %s', LOGO)
        return 0
    lienzo.saveState()
    trazo = lienzo.beginPath()
    trazo.roundRect(x, y, lado, lado, lado * 0.22)
    lienzo.clipPath(trazo, stroke=0, fill=0)
    lienzo.drawImage(imagen, x, y, lado, lado, mask='auto')
    lienzo.restoreState()
    return lado + 10


class _Lienzo(canvas.Canvas):
    """Canvas de dos pasadas para poder escribir «Página N de M» y dibujar la cabecera de cada hoja."""

    def __init__(self, *args, datos, generado, **kwargs):
        super().__init__(*args, **kwargs)
        self._datos, self._generado, self._estados = datos, generado, []

    def showPage(self):
        self._estados.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._estados)
        for estado in self._estados:
            self.__dict__.update(estado)
            self._decorar(total)
            super().showPage()
        super().save()

    def _decorar(self, total):
        ancho, alto = A4
        d, primera = self._datos, self._pageNumber == 1
        banda = 64 if primera else 28
        self.saveState()
        self.setFillColor(MARINO)
        self.rect(0, alto - banda, ancho, banda, stroke=0, fill=1)
        self.setFillColor(CIAN)
        self.rect(0, alto - banda - 2.5, ancho, 2.5, stroke=0, fill=1)
        self.setFillColor(colors.white)
        derecha = ancho - MARGEN
        if primera:
            izquierda = MARGEN + _dibujar_logo(self, MARGEN, alto - 56, 44)
            self.setFont('Helvetica-Bold', 17)
            self.drawString(izquierda, alto - 32, 'PredictaHVAC')
            self.setFillColor(CLARO)
            self.setFont('Helvetica', 8.5)
            self.drawString(izquierda, alto - 47, 'Informe de servicio técnico HVAC')
            self.setFillColor(colors.white)
            self.setFont('Helvetica-Bold', 13)
            self.drawRightString(derecha, alto - 30, d['codigo'])
            _insignia(self, d['version'], derecha, alto - 55)
        else:
            self.setFont('Helvetica-Bold', 9)
            self.drawString(MARGEN, alto - 18, 'PredictaHVAC')
            self.setFont('Helvetica-Bold', 9)
            self.drawRightString(derecha, alto - 18, d['codigo'])
            ancho_codigo = stringWidth(d['codigo'], 'Helvetica-Bold', 9)
            _insignia(self, d['version'], derecha - ancho_codigo - 8, alto - 22.5, alto=13)
        self.setStrokeColor(LINEA)
        self.setLineWidth(0.5)
        self.line(MARGEN, 34, ancho - MARGEN, 34)
        self.setFillColor(GRIS)
        self.setFont('Helvetica', 7.5)
        self.drawString(MARGEN, 22, self._generado)
        self.drawRightString(ancho - MARGEN, 22, f'Página {self._pageNumber} de {total}')
        self.restoreState()


def dibujar(datos, firma_png, generado, firma_tecnico_png=None):
    """PDF del informe (bytes). `firma_png` son los bytes de la imagen de la firma o None; `generado` es el texto del pie."""
    ancho, alto = A4
    buffer = io.BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=A4, leftMargin=MARGEN, rightMargin=MARGEN, author='PredictaHVAC',
                          title=f"Informe {datos['codigo']} ({datos['version'].lower()})")
    ajustes = dict(leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate(id='primera', frames=[Frame(MARGEN, PIE, ANCHO, alto - PIE - 64 - 18, **ajustes)]),
        PageTemplate(id='resto', frames=[Frame(MARGEN, PIE, ANCHO, alto - PIE - 28 - 16, **ajustes)]),
    ])
    historia = [NextPageTemplate('resto'),
                Paragraph(_texto(datos['equipo']), _TITULO),
                Paragraph(f"{_texto(datos['tipo'])} · {_texto(datos['estado'])} · Orden {_texto(datos['codigo'])}", _SUBTITULO)]
    historia += _resumen(datos) + _datos_generales(datos) + _checklist(datos) + _mediciones(datos)
    historia += _texto_libre(datos) + _firma(datos, firma_png)
    if 'firma_tecnico' in datos:
        historia += _firma(datos, firma_tecnico_png, 'Firma del técnico', 'firma_tecnico', 'Sin firma del técnico.')
    doc.build(historia, canvasmaker=lambda *a, **k: _Lienzo(*a, datos=datos, generado=generado, **k))
    return buffer.getvalue()

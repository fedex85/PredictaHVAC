import io
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def _texto(valor):
    """Escapa el texto para Paragraph de ReportLab (interpreta marcado XML) y conserva los saltos de línea."""
    return escape(str(valor)).replace('\n', '<br/>')


def generar_pdf_mantenimiento(mantenimiento):
    """
    Genera un archivo PDF en memoria a partir de una instancia de HistorialMantenimiento.
    Devuelve un buffer BytesIO.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # Estilos personalizados
    titulo_style = ParagraphStyle(
        'TituloReporte',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#1E3A8A'),
        spaceAfter=12
    )
    
    subtitulo_style = ParagraphStyle(
        'SubtituloReporte',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=colors.HexColor('#4B5563'),
        spaceAfter=18
    )
    
    # Encabezado
    story.append(Paragraph("REPORTE DE SERVICIO TÉCNICO HVAC", titulo_style))
    story.append(Paragraph(
        f"Reporte ID: #{mantenimiento.id} | Fecha: {mantenimiento.fecha_mantenimiento.strftime('%d/%m/%Y')}", 
        subtitulo_style
    ))
    story.append(Spacer(1, 10))
    
    # Datos del Equipo
    equipo = mantenimiento.equipo
    datos_equipo = [
        [Paragraph("<b>Equipo:</b>", styles['Normal']), Paragraph(_texto(equipo.nombre), styles['Normal'])],
        [Paragraph("<b>Código / Serie:</b>", styles['Normal']), Paragraph(_texto(equipo.codigo_identificador), styles['Normal'])],
        [Paragraph("<b>Ubicación:</b>", styles['Normal']), Paragraph(_texto(equipo.ubicacion), styles['Normal'])],
        [Paragraph("<b>Tipo de Mantenimiento:</b>", styles['Normal']), Paragraph(_texto(mantenimiento.get_tipo_mantenimiento_display()), styles['Normal'])],
        [Paragraph("<b>Técnico Responsable:</b>", styles['Normal']), Paragraph(_texto(mantenimiento.tecnico_responsable), styles['Normal'])],
    ]
    
    tabla_equipo = Table(datos_equipo, colWidths=[150, 390])
    tabla_equipo.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F3F4F6')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#D1D5DB')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    story.append(tabla_equipo)
    story.append(Spacer(1, 15))
    
    # Detalle del Trabajo Realizado
    story.append(Paragraph("<b>Descripción del Trabajo Realizado:</b>", styles['Heading3']))
    story.append(Paragraph(_texto(mantenimiento.descripcion), styles['Normal']))
    story.append(Spacer(1, 15))
        
    doc.build(story)
    buffer.seek(0)
    return buffer
"""Fotografías y firma del cliente de una orden de trabajo, y el resumen que se firma."""
import base64
import binascii
import hashlib
import io
from datetime import timezone

from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError

from core.models import EventoOT, FirmaOT, FirmaTecnicoOT, FotoOT
from core.ordenes import ReglaError, _bloquear, _evento, _exigir_edicion, nombre_de

FOTOS_MINIMAS = 3
FOTOS_MAXIMAS = 20
TAMANO_MAXIMO = 10 * 1024 * 1024
LADO_MAXIMO = 1600
FIRMA_MAXIMA = 300 * 1024
PIXELES_MAXIMOS_FOTO = 50_000_000       # JPEG: se decodifica reducido (draft), así que gasta poca memoria
PIXELES_MAXIMOS_OTROS = 16_000_000      # PNG/WebP no admiten decodificación reducida: ~64 MB de RAM como máximo
PIXELES_MAXIMOS_FIRMA = 2_000_000
FORMATOS = ('JPEG', 'PNG', 'WEBP')

MSG_IMAGEN = 'El archivo no es una imagen válida (JPG, PNG o WebP).'
MSG_FIRMA_INVALIDA = 'La firma no es válida.'
_PREFIJO_PNG = 'data:image/png;base64,'


def _firma(orden):
    """Consulta directa: evita la caché de la relación inversa, que puede quedar obsoleta tras firmar."""
    return FirmaOT.objects.filter(orden=orden).first()


def _firma_tecnico(orden):
    return FirmaTecnicoOT.objects.filter(orden=orden).first()


def _borrar_al_confirmar(campo):
    """Borra el archivo solo si la transacción se confirma; si se revierte, la fila sigue teniendo su archivo."""
    almacen, nombre = campo.storage, campo.name
    if nombre:
        transaction.on_commit(lambda: almacen.delete(nombre))


def fotos_faltantes(orden):
    return max(0, FOTOS_MINIMAS - orden.fotos.count())


def _abrir_imagen(archivo):
    try:
        archivo.seek(0)
        Image.open(archivo).verify()
        archivo.seek(0)
        imagen = Image.open(archivo)
        pixeles = imagen.width * imagen.height
        if pixeles > PIXELES_MAXIMOS_FOTO or (imagen.format != 'JPEG' and pixeles > PIXELES_MAXIMOS_OTROS):
            raise ReglaError(MSG_IMAGEN)
        if imagen.format == 'JPEG':
            # Decodifica el JPEG ya a escala reducida (1/2, 1/4 o 1/8) cuando la foto va a quedar en LADO_MAXIMO:
            # una foto enorme no obliga a reservar cientos de MB (Gunicorn tiene pocos procesos).
            escala = LADO_MAXIMO / max(imagen.width, imagen.height)
            if escala < 1:
                imagen.draft('RGB', (max(1, round(imagen.width * escala)), max(1, round(imagen.height * escala))))
        imagen.load()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise ReglaError(MSG_IMAGEN)
    if imagen.format not in FORMATOS:
        raise ReglaError(MSG_IMAGEN)
    return imagen


@transaction.atomic
def subir_foto(orden, archivo, request):
    _bloquear(orden)
    _exigir_edicion(orden, request, 'FOTOS')
    if archivo.size > TAMANO_MAXIMO:
        raise ReglaError('La imagen supera los 10 MB.')
    if orden.fotos.count() >= FOTOS_MAXIMAS:
        raise ReglaError(f'Ya hay {FOTOS_MAXIMAS} fotografías: elimina alguna antes de subir otra.')
    imagen = ImageOps.exif_transpose(_abrir_imagen(archivo)).convert('RGB')
    imagen.thumbnail((LADO_MAXIMO, LADO_MAXIMO))
    buffer = io.BytesIO()
    imagen.save(buffer, 'JPEG', quality=85)
    foto = FotoOT(orden=orden, subida_por=request.user)
    foto.imagen.save('foto.jpg', ContentFile(buffer.getvalue()), save=False)
    foto.save()
    _evento(orden, request, 'Fotografía añadida')
    return foto


@transaction.atomic
def borrar_foto(orden, foto_id, request):
    _bloquear(orden)
    _exigir_edicion(orden, request, 'FOTOS')
    foto = orden.fotos.filter(pk=foto_id).first()
    if foto is None:
        raise ReglaError('Fotografía no encontrada.')
    _borrar_al_confirmar(foto.imagen)
    foto.delete()
    _evento(orden, request, 'Fotografía eliminada')


def resumen_para_firma(orden):
    """Líneas legibles que ve el cliente antes de firmar. Cualquier cambio en ellas invalida la firma."""
    lineas = []
    for p in orden.puntos.all():
        if p.resultado == 'OK':
            estado = 'OK'
        elif p.resultado == 'INCIDENCIA':
            estado = f'Incidencia {p.gravedad.capitalize()}' + (f'. {p.nota}' if p.nota else '')
        else:
            estado = 'sin marcar'
        lineas.append(f'{p.texto}: {estado}')
    for m in orden.mediciones.all():
        valor = f'{m.valor.normalize():f} {m.unidad}' if m.valor is not None else 'sin medir'
        lineas.append(f'{m.etiqueta}: {valor}')
    lineas.append(f'Observaciones: {orden.observaciones.strip()}')
    lineas.append('Materiales: ninguno' if orden.sin_materiales else f'Materiales: {orden.materiales.strip()}')
    lineas.append(f'Fotografías: {orden.fotos.count()}')
    return lineas


def filas_resumen(orden):
    """El mismo resumen como pares (etiqueta, valor) para mostrarlo en forma de tabla, con el valor a la derecha."""
    filas = []
    for linea in resumen_para_firma(orden):
        etiqueta, _, valor = linea.partition(': ')
        filas.append((etiqueta, valor))
    return filas


def huella_resumen(orden):
    return hashlib.sha256('\n'.join(resumen_para_firma(orden)).encode('utf-8')).hexdigest()


def conserva_firma(orden):
    """En una subsanación la firma del cliente se conserva: no se le vuelve a pedir, salvo que gestión
    haya devuelto precisamente el bloque de la firma."""
    return bool(orden.subsanacion_motivo) and orden.subsanacion_bloque != 'FIRMA'


def estado_firma(orden):
    """'sin' si no hay firma, 'vigente' si firma el resumen actual (o se conserva por una subsanación),
    'obsoleta' si el resumen cambió después."""
    firma = _firma(orden)
    if firma is None:
        return 'sin'
    return 'vigente' if firma.huella == huella_resumen(orden) or conserva_firma(orden) else 'obsoleta'


def fijar_firma_conservada(orden):
    """Al reenviar una subsanación, la firma conservada pasa a cubrir el resumen definitivo.
    Devuelve True si hubo que actualizarla."""
    firma = _firma(orden)
    actual = huella_resumen(orden)
    if firma is None or firma.huella == actual or not conserva_firma(orden):
        return False
    firma.huella = actual
    firma.save(update_fields=['huella'])
    return True


def firma_vigente(orden):
    return estado_firma(orden) == 'vigente'


def estado_firma_tecnico(orden):
    """'sin' | 'vigente' | 'obsoleta'. La del técnico nunca se conserva: si el resumen cambia, firma de nuevo."""
    firma = _firma_tecnico(orden)
    if firma is None:
        return 'sin'
    return 'vigente' if firma.huella == huella_resumen(orden) else 'obsoleta'


def firma_tecnico_vigente(orden):
    return estado_firma_tecnico(orden) == 'vigente'


PREFIJO_SELLO_CLIENTE = 'Sello de la firma del cliente: '
PREFIJO_SELLO_TECNICO = 'Sello de la firma del técnico: '


def sello_firma(firma):
    """SHA-256 que liga la imagen de la firma con la orden, el firmante y el instante en que se firmó.
    No incluye la `huella` del resumen porque, al reenviar una subsanación, la firma conservada pasa a cubrir
    el resumen definitivo (`fijar_firma_conservada`). Devuelve '' si el archivo de la imagen no se puede leer."""
    try:
        with firma.imagen.storage.open(firma.imagen.name, 'rb') as archivo:
            hash_imagen = hashlib.sha256(archivo.read()).hexdigest()
    except Exception:  # archivo ausente o ilegible
        return ''
    partes = (str(firma.orden_id), hash_imagen, firma.firmante, firma.firmada_en.astimezone(timezone.utc).isoformat())
    return hashlib.sha256('|'.join(partes).encode('utf-8')).hexdigest()


def _anotar_sello(orden, request, firma, prefijo):
    """Anota el sello en el historial de la orden (tabla distinta de la de la firma): sustituir después la imagen
    guardada ya no coincide con lo anotado. No protege frente a quien pueda editar toda la base de datos."""
    sello = sello_firma(firma)
    if sello:
        _evento(orden, request, prefijo + sello)


def sello_anotado(orden, tecnico=False):
    prefijo = PREFIJO_SELLO_TECNICO if tecnico else PREFIJO_SELLO_CLIENTE
    texto = (EventoOT.objects.filter(orden=orden, texto__startswith=prefijo)
             .order_by('-fecha', '-id').values_list('texto', flat=True).first())
    return texto[len(prefijo):].strip() if texto else ''


def integridad_firma(orden, tecnico=False):
    """'sin' (no hay firma) | 'sin_sello' (firmada antes de existir el sello) | 'integra' | 'alterada'."""
    firma = _firma_tecnico(orden) if tecnico else _firma(orden)
    if firma is None:
        return 'sin'
    anotado = sello_anotado(orden, tecnico)
    if not anotado:
        return 'sin_sello'
    return 'integra' if anotado == sello_firma(firma) else 'alterada'


def _decodificar_firma(data_url):
    if not isinstance(data_url, str) or not data_url.startswith(_PREFIJO_PNG):
        raise ReglaError(MSG_FIRMA_INVALIDA)
    try:
        datos = base64.b64decode(data_url[len(_PREFIJO_PNG):], validate=True)
    except (binascii.Error, ValueError):
        raise ReglaError(MSG_FIRMA_INVALIDA)
    if len(datos) > FIRMA_MAXIMA:
        raise ReglaError('La firma es demasiado grande.')
    try:
        imagen = Image.open(io.BytesIO(datos))
        if imagen.width * imagen.height > PIXELES_MAXIMOS_FIRMA:
            raise ReglaError(MSG_FIRMA_INVALIDA)
        imagen.load()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise ReglaError(MSG_FIRMA_INVALIDA)
    if imagen.format != 'PNG':
        raise ReglaError(MSG_FIRMA_INVALIDA)
    sobre_blanco = Image.new('RGBA', imagen.size, 'white')
    sobre_blanco.alpha_composite(imagen.convert('RGBA'))
    if ImageChops.difference(sobre_blanco.convert('L'), Image.new('L', imagen.size, 255)).getbbox() is None:
        raise ReglaError('La firma está en blanco: pide al cliente que firme.')
    salida = io.BytesIO()
    imagen.save(salida, 'PNG')
    return salida.getvalue()


@transaction.atomic
def guardar_firma(orden, firmante, data_url, request, huella=None):
    """`huella` es la del resumen que vio el cliente; si ya no coincide con el actual, no se firma."""
    _bloquear(orden)
    _exigir_edicion(orden, request, 'FIRMA')
    firmante = (firmante or '').strip()
    if not firmante:
        raise ReglaError('El nombre del firmante es obligatorio.')
    png = _decodificar_firma(data_url)
    if huella is not None and huella != huella_resumen(orden):
        raise ReglaError('El resumen cambió mientras se firmaba: recarga la página, revísalo y firma de nuevo.')
    anterior = _firma(orden)
    if anterior:
        _borrar_al_confirmar(anterior.imagen)
        anterior.delete()
    firma = FirmaOT(orden=orden, firmante=firmante[:120], recogida_por=request.user, huella=huella_resumen(orden))
    firma.imagen.save('firma.png', ContentFile(png), save=False)
    firma.save()
    _evento(orden, request, f'Firma del cliente recogida: {firmante[:120]}')
    _anotar_sello(orden, request, firma, PREFIJO_SELLO_CLIENTE)
    return firma


@transaction.atomic
def guardar_firma_tecnico(orden, data_url, request, huella=None):
    """Firma del técnico asignado (el nombre sale de su usuario). `huella` es la del resumen que vio al firmar."""
    _bloquear(orden)
    _exigir_edicion(orden, request, 'FIRMA_TECNICO')
    if estado_firma(orden) != 'vigente':
        raise ReglaError('El cliente debe firmar antes que el técnico: así el técnico revisa el resumen firmado.')
    png = _decodificar_firma(data_url)
    if huella is not None and huella != huella_resumen(orden):
        raise ReglaError('El resumen cambió mientras se firmaba: recarga la página, revísalo y firma de nuevo.')
    firmante = nombre_de(request.user)[:120]
    anterior = _firma_tecnico(orden)
    if anterior:
        _borrar_al_confirmar(anterior.imagen)
        anterior.delete()
    firma = FirmaTecnicoOT(orden=orden, firmante=firmante, huella=huella_resumen(orden))
    firma.imagen.save('firma.png', ContentFile(png), save=False)
    firma.save()
    _evento(orden, request, f'Firma del técnico recogida: {firmante}')
    _anotar_sello(orden, request, firma, PREFIJO_SELLO_TECNICO)
    return firma

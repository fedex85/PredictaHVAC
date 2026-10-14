// Reduce las fotos antes de guardarlas: lado máximo 1600 px, JPEG 0,85 (igual que el servidor).
export const LADO_MAXIMO = 1600;
export const CALIDAD = 0.85;

export function tamanoReducido(ancho, alto, maximo = LADO_MAXIMO) {
  const mayor = Math.max(ancho, alto);
  if (mayor <= maximo) return { ancho, alto };
  const f = maximo / mayor;
  return { ancho: Math.max(1, Math.round(ancho * f)), alto: Math.max(1, Math.round(alto * f)) };
}

export async function reducirFoto(archivo, { limite = 10 * 1024 * 1024 } = {}) {
  try {
    const imagen = await createImageBitmap(archivo, { imageOrientation: 'from-image' });
    const { ancho, alto } = tamanoReducido(imagen.width, imagen.height);
    const lienzo = document.createElement('canvas');
    lienzo.width = ancho;
    lienzo.height = alto;
    lienzo.getContext('2d').drawImage(imagen, 0, 0, ancho, alto);
    if (imagen.close) imagen.close();
    const blob = await new Promise((ok) => lienzo.toBlob(ok, 'image/jpeg', CALIDAD));
    if (!blob) throw new Error('sin blob');
    return blob;
  } catch (e) {
    if (archivo.size <= limite) return archivo;
    throw new Error('No se pudo preparar la fotografía. Vuelve a tomarla.');
  }
}

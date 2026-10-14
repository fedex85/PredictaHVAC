// Conversación del asistente guardada en el navegador de cada usuario (localStorage), nunca en el servidor.
// Se conserva al cambiar de sección o recargar y se borra solo con «Nueva conversación».
export const MAX_MENSAJES = 100;   // tope de lo que se guarda (≈ 50 intercambios) para no llenar el almacenamiento

export function clave(usuario) {
  return `predicta.asistente.${usuario || 'anonimo'}`;
}

function valido(m) {
  return m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string' && m.content.length > 0;
}

/** Devuelve la lista guardada o [] si no hay nada, está dañada o el almacenamiento no está disponible. */
export function cargar(almacen, usuario) {
  try {
    const bruto = almacen.getItem(clave(usuario));
    const datos = bruto ? JSON.parse(bruto) : [];
    return Array.isArray(datos) ? datos.filter(valido).slice(-MAX_MENSAJES) : [];
  } catch (e) {
    return [];
  }
}

/** Guarda los últimos MAX_MENSAJES; si el almacenamiento falla (privado, lleno) la pantalla sigue funcionando. */
export function guardar(almacen, usuario, historial) {
  try {
    almacen.setItem(clave(usuario), JSON.stringify(historial.filter(valido).slice(-MAX_MENSAJES)));
    return true;
  } catch (e) {
    return false;
  }
}

export function borrar(almacen, usuario) {
  try { almacen.removeItem(clave(usuario)); } catch (e) { /* nada que borrar */ }
}

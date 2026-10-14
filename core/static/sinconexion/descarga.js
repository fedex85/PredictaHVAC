import { crearTrabajo, tieneTrabajoLocal } from './trabajo.js';

// Pide el paquete al servidor y lo guarda en el teléfono.
// No pisa trabajo local sin sincronizar; si la orden ya estaba sincronizada, la reemplaza por la nueva base.
export async function descargarOrden(id, { almacen, fetch, csrf, usuarioId }) {
  const previo = await almacen.obtener(id);
  const conservar = Boolean(previo && previo.usuario_id === usuarioId && tieneTrabajoLocal(previo));
  let respuesta;
  try {
    respuesta = await fetch(`/ordenes/${id}/descargar/`, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf || '' },
      credentials: 'same-origin',
    });
  } catch (e) {
    return { ok: false, mensaje: 'No hay conexión. Necesitas señal para preparar la orden.' };
  }
  let datos = null;
  try { datos = await respuesta.json(); } catch (e) { datos = null; }
  if (!respuesta.ok || !datos || !datos.ok) {
    const errores = datos && datos.errores;
    const mensaje = (errores && errores[0]) || 'No se pudo preparar la orden. Inténtalo de nuevo con señal.';
    return { ok: false, mensaje };
  }
  const trabajo = crearTrabajo(datos.paquete, usuarioId);
  // Con trabajo sin enviar se renueva lo que dice el servidor, pero nunca se pierde lo hecho en el teléfono.
  if (conservar) { trabajo.local = previo.local; trabajo.sync = previo.sync; }
  await almacen.guardar(trabajo);
  return { ok: true, mensaje: conservar ? 'Descarga actualizada. Tu trabajo en el teléfono se conserva.' : 'Lista para trabajar sin conexión.', trabajo };
}

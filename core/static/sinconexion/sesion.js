// Seguridad de los datos en el teléfono: qué hay pendiente, salir de la sesión y limpiar.
import { tieneTrabajoLocal } from './trabajo.js';
import { sincronizarPendientes, encolar } from './sync.js';

export async function pendientes(almacen, usuarioId) {
  return (await almacen.listar()).filter((t) => t.usuario_id === usuarioId && tieneTrabajoLocal(t));
}

// Borra del teléfono las órdenes de este usuario que ya no tienen nada por enviar.
export async function limpiarLocal(almacen, usuarioId) {
  let borradas = 0;
  for (const t of await almacen.listar()) {
    if (t.usuario_id === usuarioId && !tieneTrabajoLocal(t)) { await almacen.borrar(t.id); borradas++; }
  }
  return borradas;
}

// Días que una orden descargada sin trabajo pendiente permanece en el teléfono. El servidor ya no deja empezar
// una orden pasadas 48 h desde la descarga (OFFLINE_VENTANA_HORAS), así que pasado este plazo ya no sirve para
// trabajar sin conexión y solo deja datos del cliente en el teléfono.
export const DIAS_RETENCION = 3;

function caducada(t, ahora, dias) {
  const descarga = new Date(t.descargada_en).getTime();
  return Number.isFinite(descarga) && ahora.getTime() - descarga > dias * 24 * 60 * 60 * 1000;
}

// Borra las órdenes de este usuario descargadas hace más de `dias` días que NO tienen nada por enviar.
// Nunca toca una orden con trabajo local (aunque sea antigua o esté en error): perder trabajo es peor que
// conservar datos. Cada borrado se hace dentro de la cola de escrituras y tras releer la orden, para no
// competir con una descarga nueva o con un cambio que se esté guardando.
export async function caducarLocal(almacen, usuarioId, { ahora = new Date(), dias = DIAS_RETENCION } = {}) {
  let borradas = 0;
  for (const t of await almacen.listar()) {
    if (t.usuario_id !== usuarioId || tieneTrabajoLocal(t) || !caducada(t, ahora, dias)) continue;
    await encolar(async () => {
      const actual = await almacen.obtener(t.id);
      if (actual && actual.usuario_id === usuarioId && !tieneTrabajoLocal(actual) && caducada(actual, ahora, dias)) {
        await almacen.borrar(t.id);
        borradas++;
      }
    });
  }
  return borradas;
}

// Si otro técnico usa el mismo teléfono, sus órdenes ya enviadas no deben quedar aquí.
// Las que tienen trabajo sin enviar se conservan (nunca se pierde trabajo), pero no se muestran a otros.
export async function purgarAjenos(almacen, usuarioId) {
  let borradas = 0;
  for (const t of await almacen.listar()) {
    if (t.usuario_id !== usuarioId && !tieneTrabajoLocal(t)) { await almacen.borrar(t.id); borradas++; }
  }
  return borradas;
}

// Cerrar sesión solo se permite si no queda trabajo sin enviar. Intenta sincronizar antes de negarse.
export async function intentarSalir({ almacen, fetch, csrf, usuarioId, enLinea = true }) {
  let faltan = await pendientes(almacen, usuarioId);
  if (faltan.length && enLinea) {
    await sincronizarPendientes({ almacen, fetch, csrf, usuarioId, incluirErrores: true });
    faltan = await pendientes(almacen, usuarioId);
  }
  if (faltan.length) {
    const n = faltan.length;
    return { puede: false, mensaje: `Tienes trabajo sin enviar en ${n} ${n === 1 ? 'orden' : 'órdenes'}. Conéctate y sincroniza antes de cerrar sesión.` };
  }
  await limpiarLocal(almacen, usuarioId);
  return { puede: true, mensaje: '' };
}

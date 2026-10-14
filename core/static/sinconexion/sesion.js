// Seguridad de los datos en el teléfono: qué hay pendiente, salir de la sesión y limpiar.
import { tieneTrabajoLocal } from './trabajo.js';
import { sincronizarPendientes } from './sync.js';

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

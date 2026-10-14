// Envío del trabajo hecho sin conexión. Una orden = un paquete atómico e idempotente.
import { construirPaquete, erroresLocales } from './paquete.js';
import { tieneTrabajoLocal, consolidar } from './trabajo.js';

// Las escrituras al almacén se encadenan aquí para que una sincronización nunca lea datos a medio guardar.
let cola = Promise.resolve();
export function encolar(tarea) { const r = cola.then(tarea, tarea); cola = r.catch(() => {}); return r; }
export function vaciarCola() { return cola; }

const enCurso = new Set();
export function sincronizando(id) { return enCurso.has(id); }

function resultado(estado, mensaje, avisos = []) { return { estado, mensaje, avisos }; }

async function guardarEstado(almacen, id, cambio) {
  const t = await almacen.obtener(id);
  if (!t) return;
  await almacen.guardar(cambio(t));
}

export async function sincronizarOrden(id, { almacen, fetch, csrf }) {
  if (enCurso.has(id)) return resultado('ocupada', 'Ya se está sincronizando esta orden.');
  enCurso.add(id);
  try {
    await vaciarCola();
    const t = await almacen.obtener(id);
    if (!t) return resultado('error', 'La orden no está en este teléfono.');
    if (!tieneTrabajoLocal(t)) return resultado('sincronizada', 'No hay nada que enviar.');
    const locales = erroresLocales(t);
    if (locales.length) {
      await guardarEstado(almacen, id, (x) => ({ ...x, sync: { ...x.sync, estado: 'error', mensaje: locales[0] } }));
      return resultado('error', locales[0]);
    }
    const { paquete, fotos } = construirPaquete(t);
    // El identificador se guarda antes de enviar: si la respuesta se pierde, el reenvío es el mismo paquete.
    if (t.sync.paquete_id !== paquete.paquete_id) {
      await guardarEstado(almacen, id, (x) => ({ ...x, sync: { ...x.sync, paquete_id: paquete.paquete_id } }));
    }
    const cuerpo = new FormData();
    cuerpo.append('paquete', JSON.stringify(paquete));
    for (const f of fotos) cuerpo.append('fotos', f.blob, f.nombre);

    let respuesta;
    try {
      respuesta = await fetch(`/ordenes/${id}/sincronizar/`, { method: 'POST', body: cuerpo, headers: { 'X-CSRFToken': csrf || '' }, credentials: 'same-origin' });
    } catch (e) {
      return resultado('pendiente', 'Sin conexión. Se enviará cuando vuelva la señal.');
    }
    if (respuesta.redirected || respuesta.status === 401) {
      const m = 'Inicia sesión para sincronizar. Tu trabajo sigue guardado en el teléfono.';
      await guardarEstado(almacen, id, (x) => ({ ...x, sync: { ...x.sync, estado: 'sin_sesion', mensaje: m } }));
      return resultado('sin_sesion', m);
    }
    let datos = null;
    try { datos = await respuesta.json(); } catch (e) { datos = null; }
    if (respuesta.ok && datos && datos.ok) {
      const avisos = datos.avisos || [];
      const descartada = datos.firma === 'descartada' || datos.firma_tecnico === 'descartada';
      let cambiado = false;
      await guardarEstado(almacen, id, (x) => {
        // Si hubo cambios mientras se enviaba (otra pestaña), no se da por enviado nada: se reenviará todo
        // y el servidor ignora lo repetido (valores iguales, fotos con el mismo identificador).
        if (x.sync.paquete_id !== paquete.paquete_id) { cambiado = true; return { ...x, sync: { ...x.sync, estado: 'pendiente' } }; }
        const nuevo = consolidar(x, datos);
        nuevo.sync = { estado: 'sincronizada', paquete_id: null, avisos, faltan: datos.faltan || [], mensaje: '' };
        if (descartada) nuevo.sync.firma_descartada = true;
        return nuevo;
      });
      if (cambiado) return resultado('pendiente', 'Hubo cambios durante el envío; se enviarán de nuevo.');
      return resultado('sincronizada', 'Sincronizada.', avisos);
    }
    const mensaje = (datos && datos.errores && datos.errores[0]) || 'El servidor no pudo procesar el envío. Inténtalo de nuevo.';
    await guardarEstado(almacen, id, (x) => ({ ...x, sync: { ...x.sync, estado: 'error', mensaje } }));
    return resultado('error', mensaje);
  } finally {
    enCurso.delete(id);
    if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('sc-sync-fin', { detail: { id } }));
  }
}

// Procesa de una en una las órdenes con trabajo sin enviar. En automático no reintenta las que dieron error.
export async function sincronizarPendientes({ almacen, fetch, csrf, usuarioId, incluirErrores = false }) {
  const todas = (await almacen.listar()).filter((t) => t.usuario_id === usuarioId && tieneTrabajoLocal(t));
  const resultados = [];
  for (const t of todas) {
    if (!incluirErrores && t.sync.estado === 'error') continue;
    resultados.push({ id: t.id, ...(await sincronizarOrden(t.id, { almacen, fetch, csrf })) });
  }
  return resultados;
}

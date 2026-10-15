// Se carga en todas las páginas del técnico: registra el Service Worker y, en el detalle de una orden,
// ofrece «Preparar para trabajar sin conexión».
import { almacenIdb } from './almacen.js';
import { descargarOrden } from './descarga.js';
import { leerCookie } from './util.js';
import { sincronizarPendientes } from './sync.js';
import { pendientes, purgarAjenos, caducarLocal, intentarSalir } from './sesion.js';

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
}
if (navigator.storage && navigator.storage.persist) {
  navigator.storage.persist().catch(() => {});
}

function pintarBloque(bloque) {
  const id = Number(bloque.dataset.orden);
  const usuarioId = Number(bloque.dataset.usuario);
  if (!('indexedDB' in window) || !id) {
    bloque.textContent = 'Este navegador no permite trabajar sin conexión.';
    return;
  }
  const almacen = almacenIdb();
  const crear = (tag, clases, texto) => {
    const e = document.createElement(tag);
    e.className = clases;
    if (texto) e.textContent = texto;
    return e;
  };
  // Las clases de Tailwind se escriben completas para que el CDN las detecte.
  bloque.className = 'bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3';
  bloque.innerHTML = '';
  const estado = crear('p', 'text-sm font-semibold text-white');
  const detalle = crear('p', 'text-sm text-slate-400');
  const aviso = crear('p', 'text-sm text-red-300');
  aviso.setAttribute('role', 'status');
  const principal = crear('button', 'w-full min-h-[48px] px-4 py-3 rounded-lg bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-700 disabled:text-slate-400 text-white font-semibold');
  principal.type = 'button';
  const secundario = crear('button', 'w-full min-h-[48px] px-4 py-3 rounded-lg border border-slate-600 text-slate-200 font-medium');
  secundario.type = 'button';
  secundario.textContent = 'Actualizar descarga';
  const enlace = crear('a', 'block w-full min-h-[48px] px-4 py-3 text-center text-cyan-300 font-medium', 'Ver mis órdenes descargadas');
  enlace.href = '/sin-conexion/';
  bloque.append(estado, detalle, aviso, principal, secundario, enlace);

  async function refrescar() {
    const t = await almacen.obtener(id).catch(() => undefined);
    const lista = Boolean(t && t.usuario_id === usuarioId);
    const conTrabajo = lista && Object.keys(t.local || {}).length > 0;
    if (!lista) {
      estado.textContent = '¿Vas a trabajar sin señal?';
      detalle.textContent = 'Descarga esta orden al teléfono ahora que tienes conexión.';
      principal.textContent = 'Descargar para trabajar sin conexión';
    } else {
      estado.textContent = '✓ Descargada en tu teléfono';
      detalle.textContent = conTrabajo
        ? 'Tienes trabajo guardado en el teléfono pendiente de enviar.'
        : 'Ya puedes abrirla desde «Mis órdenes descargadas», aunque no haya señal.';
    }
    estado.className = 'text-sm font-semibold ' + (lista ? 'text-emerald-300' : 'text-white');
    principal.hidden = lista;
    secundario.hidden = !lista;
    enlace.hidden = !lista;
  }

  async function descargar(boton) {
    boton.disabled = true;
    aviso.textContent = 'Descargando…';
    const r = await descargarOrden(id, {
      almacen, fetch: window.fetch.bind(window), csrf: leerCookie('csrftoken', document.cookie), usuarioId,
    });
    aviso.textContent = r.ok ? '' : r.mensaje;
    boton.disabled = false;
    await refrescar();
  }
  principal.addEventListener('click', () => descargar(principal));
  secundario.addEventListener('click', () => descargar(secundario));
  refrescar();
}

const bloque = document.getElementById('bloque-sin-conexion');
if (bloque) pintarBloque(bloque);

// Al abrir cualquier página del técnico y al volver la señal, se envía el trabajo pendiente.
const guion = document.querySelector('script[src*="sinconexion/arranque.js"]');
const usuarioActual = guion ? Number(guion.dataset.usuario) : 0;
function enviarPendientes() {
  if (!usuarioActual || !navigator.onLine || !('indexedDB' in window)) return;
  sincronizarPendientes({ almacen: almacenIdb(), fetch: window.fetch.bind(window), csrf: leerCookie('csrftoken', document.cookie), usuarioId: usuarioActual }).catch(() => {});
}
try { if (usuarioActual) localStorage.setItem('sc-usuario', String(usuarioActual)); } catch (e) { /* sin almacenamiento */ }
window.addEventListener('online', enviarPendientes);
enviarPendientes();

// ---------------------------------------------------------------- seguridad de los datos locales
const contador = document.getElementById('contador-pendientes');
async function actualizarContador() {
  if (!contador || !usuarioActual || !('indexedDB' in window)) return;
  try {
    const n = (await pendientes(almacenIdb(), usuarioActual)).length;
    contador.hidden = n === 0;
    contador.textContent = `${n} por enviar`;
  } catch (e) { /* sin almacenamiento */ }
}
window.addEventListener('sc-sync-fin', actualizarContador);
actualizarContador();
if (usuarioActual && 'indexedDB' in window) {
  purgarAjenos(almacenIdb(), usuarioActual).catch(() => {});
  caducarLocal(almacenIdb(), usuarioActual).then(actualizarContador).catch(() => {});  // órdenes viejas ya sincronizadas
}

function aviso(texto) {
  let caja = document.getElementById('sc-aviso-salida');
  if (!caja) {
    caja = document.createElement('div');
    caja.id = 'sc-aviso-salida';
    caja.setAttribute('role', 'alert');
    caja.style.cssText = 'position:fixed;left:12px;right:12px;bottom:76px;z-index:9999;padding:14px 16px;border-radius:12px;background:#7f1d1d;color:#fff;font:16px/1.4 system-ui,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.5)';
    document.body.append(caja);
  }
  caja.textContent = texto;
}

for (const form of document.querySelectorAll('form[action$="/logout/"]')) {
  form.addEventListener('submit', async (e) => {
    if (!usuarioActual || !('indexedDB' in window)) return;
    e.preventDefault();
    aviso('Comprobando que no quede trabajo sin enviar…');
    let r;
    try {
      r = await intentarSalir({ almacen: almacenIdb(), fetch: window.fetch.bind(window), csrf: leerCookie('csrftoken', document.cookie), usuarioId: usuarioActual, enLinea: navigator.onLine });
    } catch (err) {
      r = { puede: false, mensaje: 'No se pudo comprobar el trabajo guardado en el teléfono. Inténtalo de nuevo.' };
    }
    if (!r.puede) { aviso(r.mensaje); actualizarContador(); return; }
    try { localStorage.removeItem('sc-usuario'); } catch (err) { /* sin almacenamiento */ }
    HTMLFormElement.prototype.submit.call(form);
  });
}

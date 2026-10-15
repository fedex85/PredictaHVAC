// Pantalla /sin-conexion/: lista de órdenes descargadas y pantalla de ejecución (#/orden/<id>).
import { almacenIdb } from './almacen.js';
import { estadoLegible } from './trabajo.js';
import { el } from './dom.js';
import { abrirPantalla } from './pantalla.js';
import { sincronizarPendientes } from './sync.js';
import { caducarLocal } from './sesion.js';
import { leerCookie } from './util.js';
import { seccionFotos, seccionFirma, seccionFirmaTecnico } from './evidencias_ui.js';

const raiz = document.getElementById('contenido');
// El HTML de esta pantalla puede venir de la caché, así que el usuario se toma del último acceso real
// (lo guarda arranque.js en cada página del técnico) y no del atributo de la página.
function usuarioActual() {
  try { const v = localStorage.getItem('sc-usuario'); if (v) return Number(v); } catch (e) { /* sin almacenamiento */ }
  return Number(document.body.dataset.usuario);
}
const usuarioId = usuarioActual();
const almacen = almacenIdb();

function tarjeta(t) {
  return el('li', { clase: 'sc-tarjeta' },
    el('a', { clase: 'sc-tarjeta-enlace', href: `#/orden/${t.id}` },
      el('p', { clase: 'sc-codigo', texto: t.orden.codigo }),
      el('p', { texto: `${t.equipo.codigo} · ${t.equipo.nombre}` }),
      el('p', { clase: 'sc-suave', texto: t.equipo.ubicacion || 'Sin ubicación' }),
      el('p', { clase: 'sc-estado', texto: estadoLegible(t) }),
      el('p', { clase: 'sc-abrir', texto: 'Abrir →' })));
}

async function pintarLista() {
  let ordenes = [];
  try { ordenes = (await almacen.listar()).filter((t) => t.usuario_id === usuarioId); } catch (e) { ordenes = []; }
  ordenes.sort((a, b) => a.id - b.id);
  raiz.replaceChildren(...[
    el('p', { clase: 'sc-suave', texto: 'Estas son las órdenes que descargaste en este teléfono. Toca una para trabajarla, aunque no haya señal.' }),
    el('ul', { clase: 'sc-lista' }, ordenes.length ? ordenes.map(tarjeta)
      : el('li', { clase: 'sc-vacio', texto: 'No tienes órdenes descargadas. Abre una orden con señal y pulsa «Descargar para trabajar sin conexión».' })),
    ordenes.some((t) => Object.keys(t.local || {}).length) ? el('button', { type: 'button', clase: 'sc-boton', texto: 'Sincronizar todo', onclick: sincronizarTodo }) : null,
    el('p', { id: 'resultado-sync', clase: 'sc-suave', role: 'status' }),
    el('a', { clase: 'sc-volver', href: '/ordenes/', texto: '← Mis órdenes (con conexión)' })].filter(Boolean));
}

const deps = () => ({ almacen, fetch: window.fetch.bind(window), csrf: leerCookie('csrftoken', document.cookie), usuarioId });

async function sincronizarTodo() {
  const salida = document.getElementById('resultado-sync');
  if (salida) salida.textContent = 'Sincronizando…';
  const r = await sincronizarPendientes({ ...deps(), incluirErrores: true });
  const errores = r.filter((x) => x.estado === 'error');
  if (salida) salida.textContent = errores.length ? `${errores.length} orden(es) con error: ábrelas para ver el motivo.` : 'Todo sincronizado.';
}

function ruta() {
  const m = /^#\/orden\/(\d+)$/.exec(location.hash);
  if (m) abrirPantalla(raiz, { almacen, id: Number(m[1]), usuarioId, extras: [seccionFotos, seccionFirma, seccionFirmaTecnico] });
  else pintarLista();
}

window.addEventListener('hashchange', ruta);
window.addEventListener('sc-sync-fin', () => { if (!location.hash.startsWith('#/orden/')) pintarLista(); });
window.addEventListener('online', () => sincronizarPendientes(deps()));
ruta();
// Quita de la lista las órdenes viejas ya enviadas (no bloquea la pantalla; vuelve a pintar solo si borró alguna).
caducarLocal(almacen, usuarioId)
  .then((n) => { if (n && !location.hash.startsWith('#/orden/')) pintarLista(); })
  .catch(() => {});
if (navigator.onLine) sincronizarPendientes(deps());

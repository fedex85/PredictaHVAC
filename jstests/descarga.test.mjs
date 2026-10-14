import test from 'node:test';
import assert from 'node:assert/strict';
import { almacenEnMemoria } from '../core/static/sinconexion/almacen.js';
import { descargarOrden } from '../core/static/sinconexion/descarga.js';
import { crearTrabajo, estadoLegible, tieneTrabajoLocal } from '../core/static/sinconexion/trabajo.js';

const paquete = (extra = {}) => ({
  orden: { id: 7, codigo: 'OT-7', estado: 'ASIGNADA' },
  equipo: { codigo: 'CH-001', nombre: 'Chiller', ubicacion: 'Azotea', tipo: 'SPLIT' },
  catalogo: { puntos: [], mediciones: [], mediciones_elegibles: [] },
  estado_actual: { puntos: {}, mediciones: {}, observaciones: '', materiales: '' },
  limites: { fotos_min: 3, fotos_max: 20, foto_bytes: 10485760 },
  descargada_en: '2026-10-12T10:00:00+00:00',
  ...extra,
});
const respuesta = (cuerpo, estado = 200) => ({ ok: estado < 400, status: estado, json: async () => cuerpo });

test('descarga correcta guarda el trabajo con usuario, fecha y catálogo', async () => {
  const almacen = almacenEnMemoria();
  let llamada;
  const fetch = async (url, op) => { llamada = { url, op }; return respuesta({ ok: true, paquete: paquete() }); };
  const r = await descargarOrden(7, { almacen, fetch, csrf: 'tok', usuarioId: 3 });
  assert.equal(r.ok, true);
  assert.equal(llamada.url, '/ordenes/7/descargar/');
  assert.equal(llamada.op.method, 'POST');
  assert.equal(llamada.op.headers['X-CSRFToken'], 'tok');
  const t = await almacen.obtener(7);
  assert.equal(t.usuario_id, 3);
  assert.equal(t.descargada_en, '2026-10-12T10:00:00+00:00');
  assert.ok(t.catalogo);
});

test('rechazo del servidor devuelve el primer error y no guarda', async () => {
  const almacen = almacenEnMemoria();
  const fetch = async () => respuesta({ ok: false, errores: ['Primero', 'Segundo'] }, 409);
  const r = await descargarOrden(7, { almacen, fetch, csrf: 't', usuarioId: 3 });
  assert.equal(r.ok, false);
  assert.equal(r.mensaje, 'Primero');
  assert.equal(await almacen.obtener(7), undefined);
});

test('respuesta que no es JSON devuelve error genérico', async () => {
  const almacen = almacenEnMemoria();
  const fetch = async () => ({ ok: false, status: 500, json: async () => { throw new Error('x'); } });
  const r = await descargarOrden(7, { almacen, fetch, csrf: 't', usuarioId: 3 });
  assert.equal(r.ok, false);
  assert.equal(await almacen.obtener(7), undefined);
});

test('error de red: No hay conexión', async () => {
  const almacen = almacenEnMemoria();
  const fetch = async () => { throw new TypeError('Failed to fetch'); };
  const r = await descargarOrden(7, { almacen, fetch, csrf: 't', usuarioId: 3 });
  assert.equal(r.ok, false);
  assert.match(r.mensaje, /No hay conexión/);
});

test('al actualizar la descarga no se pierde el trabajo local', async () => {
  const almacen = almacenEnMemoria();
  const t = crearTrabajo(paquete(), 3);
  t.local = { inicio: '2026-10-12T11:00:00Z' };
  await almacen.guardar(t);
  t.sync = { estado: 'error', paquete_id: 'P1', mensaje: 'x' };
  await almacen.guardar(t);
  const nuevo = paquete({ descargada_en: '2026-10-12T12:00:00+00:00' });
  const fetch = async () => respuesta({ ok: true, paquete: nuevo });
  const r = await descargarOrden(7, { almacen, fetch, csrf: 't', usuarioId: 3 });
  assert.equal(r.ok, true);
  assert.match(r.mensaje, /se conserva/);
  const g = await almacen.obtener(7);
  assert.deepEqual(g.local, { inicio: '2026-10-12T11:00:00Z' });
  assert.equal(g.sync.paquete_id, 'P1');
  assert.equal(g.descargada_en, '2026-10-12T12:00:00+00:00');
});

test('una orden ya sincronizada se reemplaza por la nueva base', async () => {
  const almacen = almacenEnMemoria();
  const t = crearTrabajo(paquete(), 3);
  t.sync.estado = 'sincronizada';
  await almacen.guardar(t);
  const nuevo = paquete({ estado_actual: { puntos: {}, mediciones: {}, observaciones: 'nueva', materiales: '' } });
  const fetch = async () => respuesta({ ok: true, paquete: nuevo });
  const r = await descargarOrden(7, { almacen, fetch, csrf: 't', usuarioId: 3 });
  assert.equal(r.ok, true);
  assert.equal((await almacen.obtener(7)).base.observaciones, 'nueva');
});

test('estadoLegible', () => {
  const t = crearTrabajo(paquete(), 3);
  assert.equal(estadoLegible(t), 'Sin iniciar');
  t.orden.estado = 'EN_EJECUCION';
  assert.equal(estadoLegible(t), 'En curso');
  t.local = { inicio: 'x' };
  assert.equal(tieneTrabajoLocal(t), true);
  assert.equal(estadoLegible(t), 'Pendiente de sincronizar');
  t.local = {};
  t.sync.estado = 'sincronizada';
  assert.equal(estadoLegible(t), 'Sincronizada');
  t.sync.estado = 'error';
  assert.equal(estadoLegible(t), 'Error');
});

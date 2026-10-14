import test from 'node:test';
import assert from 'node:assert/strict';
import { almacenEnMemoria } from '../core/static/sinconexion/almacen.js';
import * as T from '../core/static/sinconexion/trabajo.js';
import { pendientes, limpiarLocal, purgarAjenos, intentarSalir } from '../core/static/sinconexion/sesion.js';
import { nuevoTrabajo, AHORA } from './fixture.mjs';

const conTrabajo = (id, usuario) => {
  const t = T.marcarPunto(T.iniciar(nuevoTrabajo(), AHORA), 'INS_FILTROS', { resultado: 'OK' });
  t.id = id; t.usuario_id = usuario; t.orden = { ...t.orden, id };
  return t;
};
const limpia = (id, usuario) => { const t = nuevoTrabajo(); t.id = id; t.usuario_id = usuario; return t; };
const OK = { ok: true, status: 200, redirected: false, json: async () => ({ ok: true, estado: 'EN_EJECUCION', firma: 'ninguna', avisos: [], faltan: [] }) };

async function lleno() {
  const a = almacenEnMemoria();
  for (const t of [conTrabajo(1, 3), limpia(2, 3), limpia(3, 9), conTrabajo(4, 9)]) await a.guardar(t);
  return a;
}

test('pendientes solo cuenta las del usuario con trabajo sin enviar', async () => {
  assert.deepEqual((await pendientes(await lleno(), 3)).map((t) => t.id), [1]);
});

test('limpiarLocal borra las del usuario sin pendiente y conserva el resto', async () => {
  const a = await lleno();
  assert.equal(await limpiarLocal(a, 3), 1);
  assert.deepEqual((await a.listar()).map((t) => t.id).sort(), [1, 3, 4]);
});

test('purgarAjenos borra las de otros sin pendiente y conserva las que tienen trabajo', async () => {
  const a = await lleno();
  assert.equal(await purgarAjenos(a, 3), 1);
  assert.deepEqual((await a.listar()).map((t) => t.id).sort(), [1, 2, 4]);
});

test('salir sin pendientes: permitido y limpia lo del usuario', async () => {
  const a = almacenEnMemoria();
  await a.guardar(limpia(2, 3));
  const r = await intentarSalir({ almacen: a, fetch: async () => OK, csrf: 't', usuarioId: 3 });
  assert.equal(r.puede, true);
  assert.equal((await a.listar()).length, 0);
});

test('salir con pendientes y sin señal: bloqueado y nada se borra', async () => {
  const a = await lleno();
  const r = await intentarSalir({ almacen: a, fetch: async () => { throw new TypeError('x'); }, csrf: 't', usuarioId: 3, enLinea: false });
  assert.equal(r.puede, false);
  assert.match(r.mensaje, /1 orden\. Conéctate/);
  assert.equal((await a.listar()).length, 4);
});

test('salir con pendientes y con señal: sincroniza y entonces permite salir', async () => {
  const a = await lleno();
  const r = await intentarSalir({ almacen: a, fetch: async () => OK, csrf: 't', usuarioId: 3 });
  assert.equal(r.puede, true);
  assert.deepEqual((await a.listar()).map((t) => t.id), [3, 4]);
});

test('salir con pendientes si el servidor rechaza: sigue bloqueado', async () => {
  const a = await lleno();
  const rechazo = { ok: false, status: 409, redirected: false, json: async () => ({ ok: false, errores: ['La orden fue cancelada'] }) };
  const r = await intentarSalir({ almacen: a, fetch: async () => rechazo, csrf: 't', usuarioId: 3 });
  assert.equal(r.puede, false);
  assert.equal((await pendientes(a, 3)).length, 1);
});

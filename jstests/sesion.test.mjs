import test from 'node:test';
import assert from 'node:assert/strict';
import { almacenEnMemoria } from '../core/static/sinconexion/almacen.js';
import * as T from '../core/static/sinconexion/trabajo.js';
import { pendientes, limpiarLocal, purgarAjenos, caducarLocal, DIAS_RETENCION, intentarSalir } from '../core/static/sinconexion/sesion.js';
import { nuevoTrabajo, AHORA } from './fixture.mjs';

const conTrabajo = (id, usuario) => {
  const t = T.marcarPunto(T.iniciar(nuevoTrabajo(), AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' }), 'INS_FILTROS', { resultado: 'OK' });
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

// ---------------------------------------------------------------- caducidad de datos locales
// Las órdenes de prueba se "descargaron" el 12/10/2026 a las 10:00 UTC (descargada_en del fixture).
const TRES_DIAS_Y_UN_MS = new Date('2026-10-15T10:00:00.001Z');
const justo_tres_dias = new Date('2026-10-15T10:00:00.000Z');

test('el plazo de retención es de 3 días', () => {
  assert.equal(DIAS_RETENCION, 3);
});

test('caducarLocal borra las del usuario sin pendiente que pasaron el plazo', async () => {
  const a = await lleno();
  assert.equal(await caducarLocal(a, 3, { ahora: TRES_DIAS_Y_UN_MS }), 1);
  assert.deepEqual((await a.listar()).map((t) => t.id).sort(), [1, 3, 4]);
});

test('caducarLocal conserva las que tienen trabajo sin enviar aunque sean viejas', async () => {
  const a = await lleno();
  await caducarLocal(a, 3, { ahora: new Date('2027-01-01T00:00:00Z') });
  assert.ok(await a.obtener(1), 'la orden con trabajo local sigue en el teléfono');
});

test('caducarLocal no borra en el límite exacto ni antes del plazo', async () => {
  const a = await lleno();
  assert.equal(await caducarLocal(a, 3, { ahora: justo_tres_dias }), 0);
  assert.equal(await caducarLocal(a, 3, { ahora: AHORA }), 0);
  assert.equal((await a.listar()).length, 4);
});

test('caducarLocal no toca las de otros usuarios', async () => {
  const a = await lleno();
  await caducarLocal(a, 3, { ahora: new Date('2027-01-01T00:00:00Z') });
  assert.deepEqual((await a.listar()).map((t) => t.id).sort(), [1, 3, 4]);
});

test('caducarLocal respeta un plazo distinto', async () => {
  const a = await lleno();
  assert.equal(await caducarLocal(a, 3, { ahora: AHORA, dias: 0 }), 1);
});

test('caducarLocal ignora las órdenes sin fecha de descarga válida', async () => {
  const a = almacenEnMemoria();
  const sinFecha = limpia(2, 3); delete sinFecha.descargada_en;
  const rota = limpia(5, 3); rota.descargada_en = 'no es una fecha';
  await a.guardar(sinFecha); await a.guardar(rota);
  assert.equal(await caducarLocal(a, 3, { ahora: new Date('2030-01-01T00:00:00Z') }), 0);
  assert.equal((await a.listar()).length, 2);
});

test('caducarLocal relee la orden antes de borrar: si mientras tanto tiene trabajo, no la borra', async () => {
  const a = almacenEnMemoria();
  await a.guardar(limpia(2, 3));
  const conCambios = conTrabajo(2, 3);
  // listar() devuelve la copia vieja sin trabajo; cuando se relee, ya hay trabajo guardado
  const carrera = { ...a, obtener: async () => conCambios };
  assert.equal(await caducarLocal(carrera, 3, { ahora: TRES_DIAS_Y_UN_MS }), 0);
  assert.equal((await a.listar()).length, 1);
});

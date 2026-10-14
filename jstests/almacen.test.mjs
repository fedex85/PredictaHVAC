import test from 'node:test';
import assert from 'node:assert/strict';
import { almacenEnMemoria } from '../core/static/sinconexion/almacen.js';
import { leerCookie } from '../core/static/sinconexion/util.js';

test('guardar, obtener, listar y borrar', async () => {
  const a = almacenEnMemoria();
  await a.guardar({ id: 1, x: 'a' });
  await a.guardar({ id: 2, x: 'b' });
  assert.deepEqual(await a.obtener(1), { id: 1, x: 'a' });
  assert.equal((await a.listar()).length, 2);
  await a.borrar(1);
  assert.equal(await a.obtener(1), undefined);
  assert.equal((await a.listar()).length, 1);
});

test('obtener de un id inexistente devuelve undefined', async () => {
  assert.equal(await almacenEnMemoria().obtener(99), undefined);
});

test('el almacén guarda copias, no referencias', async () => {
  const a = almacenEnMemoria();
  const t = { id: 1, local: {} };
  await a.guardar(t);
  t.local.x = 1;
  assert.deepEqual((await a.obtener(1)).local, {});
});

test('leerCookie', () => {
  assert.equal(leerCookie('csrftoken', 'a=1; csrftoken=abc%20d; b=2'), 'abc d');
  assert.equal(leerCookie('nada', 'a=1'), null);
  assert.equal(leerCookie('a', ''), null);
});

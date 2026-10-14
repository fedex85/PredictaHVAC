import test from 'node:test';
import assert from 'node:assert/strict';
import { cargar, guardar, borrar, clave, MAX_MENSAJES } from '../core/static/asistente/conversacion.js';

function almacenFalso() {
  const datos = new Map();
  return { getItem: (k) => (datos.has(k) ? datos.get(k) : null), setItem: (k, v) => datos.set(k, String(v)), removeItem: (k) => datos.delete(k), datos };
}
const turno = (i) => [{ role: 'user', content: `pregunta ${i}` }, { role: 'assistant', content: `respuesta ${i}` }];

test('lo guardado se recupera igual al volver a abrir la pantalla', () => {
  const a = almacenFalso(); const h = [...turno(1), ...turno(2)];
  assert.ok(guardar(a, 7, h));
  assert.deepEqual(cargar(a, 7), h);
});

test('cada usuario tiene su propia conversación', () => {
  const a = almacenFalso(); guardar(a, 1, turno(1)); guardar(a, 2, turno(2));
  assert.equal(cargar(a, 1)[0].content, 'pregunta 1');
  assert.equal(cargar(a, 2)[0].content, 'pregunta 2');
  assert.notEqual(clave(1), clave(2));
});

test('«Nueva conversación» borra solo la del usuario actual', () => {
  const a = almacenFalso(); guardar(a, 1, turno(1)); guardar(a, 2, turno(2));
  borrar(a, 1);
  assert.deepEqual(cargar(a, 1), []);
  assert.equal(cargar(a, 2).length, 2);
});

test('sin nada guardado o con datos dañados devuelve una lista vacía', () => {
  const a = almacenFalso();
  assert.deepEqual(cargar(a, 1), []);
  a.setItem(clave(1), '{no es json');
  assert.deepEqual(cargar(a, 1), []);
  a.setItem(clave(1), '{"role":"user"}');
  assert.deepEqual(cargar(a, 1), []);
});

test('descarta entradas con formato inválido y no deja pasar otros roles', () => {
  const a = almacenFalso();
  a.setItem(clave(1), JSON.stringify([{ role: 'system', content: 'x' }, { role: 'user', content: '' }, { role: 'user' }, null, ...turno(1)]));
  assert.deepEqual(cargar(a, 1), turno(1));
});

test('solo se guardan los últimos mensajes', () => {
  const a = almacenFalso(); const largo = [];
  for (let i = 0; i < MAX_MENSAJES; i++) largo.push(...turno(i));
  guardar(a, 1, largo);
  const g = cargar(a, 1);
  assert.equal(g.length, MAX_MENSAJES);
  assert.equal(g.at(-1).content, `respuesta ${MAX_MENSAJES - 1}`);
});

test('si el almacenamiento falla la pantalla no se rompe', () => {
  const roto = { getItem() { throw new Error('bloqueado'); }, setItem() { throw new Error('lleno'); }, removeItem() { throw new Error('x'); } };
  assert.deepEqual(cargar(roto, 1), []);
  assert.equal(guardar(roto, 1, turno(1)), false);
  assert.doesNotThrow(() => borrar(roto, 1));
});

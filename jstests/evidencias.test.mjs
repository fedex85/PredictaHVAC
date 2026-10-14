import test from 'node:test';
import assert from 'node:assert/strict';
import { tamanoReducido } from '../core/static/sinconexion/camara.js';
import { registroTrazos } from '../core/static/sinconexion/firma.js';

test('tamanoReducido respeta 1600 px de lado máximo y la proporción', () => {
  assert.deepEqual(tamanoReducido(4000, 3000), { ancho: 1600, alto: 1200 });
  assert.deepEqual(tamanoReducido(3000, 4000), { ancho: 1200, alto: 1600 });
  assert.deepEqual(tamanoReducido(800, 600), { ancho: 800, alto: 600 });
});

test('la firma está vacía hasta que hay un trazo con movimiento', () => {
  const r = registroTrazos();
  assert.equal(r.vacio(), true);
  r.iniciar(1, 1); r.terminar();
  assert.equal(r.vacio(), true); // un toque no es firma
  r.iniciar(1, 1); r.mover(5, 5); r.terminar();
  assert.equal(r.vacio(), false);
  r.limpiar();
  assert.equal(r.vacio(), true);
});

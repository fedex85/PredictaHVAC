import test from 'node:test';
import assert from 'node:assert/strict';
import { almacenEnMemoria } from '../core/static/sinconexion/almacen.js';
import * as T from '../core/static/sinconexion/trabajo.js';
import { nuevoTrabajo, AHORA } from './fixture.mjs';

test('una secuencia completa deja solo fotos y firma por hacer, y se conserva al recargar', async () => {
  const almacen = almacenEnMemoria();
  let t = T.iniciar(nuevoTrabajo(), AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' });
  await almacen.guardar(t);
  for (const p of t.catalogo.puntos) { t = T.marcarPunto(t, p.codigo, { resultado: 'OK' }); await almacen.guardar(t); }
  for (const m of t.catalogo.mediciones) { t = T.registrarMedicion(t, m.codigo, '12,5'); await almacen.guardar(t); }
  t = T.fijarTextos(t, { observaciones: 'Todo correcto', sin_materiales: true });
  await almacen.guardar(t);

  const recargado = await almacen.obtener(7);
  assert.deepEqual(T.faltantes(recargado), ['Faltan 3 fotografías', 'Falta la firma del cliente', 'Falta la firma del técnico']);
  assert.equal(recargado.local.mediciones.TENSION, '12.5');
  assert.equal(recargado.local.inicio, AHORA.toISOString());
  assert.equal(T.estadoLegible(recargado), 'Pendiente de sincronizar');
});

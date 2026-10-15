import test from 'node:test';
import assert from 'node:assert/strict';
import * as T from '../core/static/sinconexion/trabajo.js';
import { construirPaquete, erroresLocales, uuid4 } from '../core/static/sinconexion/paquete.js';
import { nuevoTrabajo, AHORA } from './fixture.mjs';

const PNG = 'data:image/png;base64,AAAA';
const foto = (id) => ({ id, blob: { size: 5 }, nombre: `${id}.jpg` });

test('uuid4 tiene formato válido y es distinto cada vez', () => {
  const a = uuid4(), b = uuid4();
  assert.match(a, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.notEqual(a, b);
});

test('el paquete lleva solo los cambios, inicio si estaba Asignada y fotos no enviadas', () => {
  let t = T.iniciar(nuevoTrabajo(), AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' });
  t = T.marcarPunto(t, 'INS_FILTROS', { resultado: 'OK' });
  t = T.registrarMedicion(t, 'TENSION', '230');
  t = T.registrarMedicion(t, 'CORRIENTE', '');
  t = T.fijarTextos(t, { observaciones: 'obs' });
  t = T.agregarFoto(T.agregarFoto(t, foto('a')), foto('b'));
  t.local.fotos[0].enviada = true;
  const { paquete, fotos } = construirPaquete(t, () => 'ID-1');
  assert.equal(paquete.paquete_id, 'ID-1');
  assert.equal(paquete.inicio, AHORA.toISOString());
  assert.deepEqual(paquete.puntos, [{ codigo: 'INS_FILTROS', resultado: 'OK', gravedad: '', nota: '' }]);
  assert.deepEqual(paquete.mediciones, [{ codigo: 'TENSION', valor: '230' }]);
  assert.equal(paquete.observaciones, 'obs');
  assert.equal('materiales' in paquete, false);
  assert.deepEqual(fotos.map((f) => f.id), ['b']);
  assert.equal('firma' in paquete, false);
});

test('sin inicio si la orden ya estaba en ejecución', () => {
  const t = nuevoTrabajo();
  t.orden = { ...t.orden, estado: 'EN_EJECUCION' };
  const { paquete } = construirPaquete(T.marcarPunto(t, 'INS_FILTROS', { resultado: 'OK' }), () => 'X');
  assert.equal('inicio' in paquete, false);
});

test('la firma solo viaja si está vigente', () => {
  let t = T.guardarFirma(T.iniciar(nuevoTrabajo(), AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' }), { firmante: 'C', imagen: PNG });
  assert.deepEqual(Object.keys(construirPaquete(t, () => 'X').paquete.firma).sort(), ['firmante', 'imagen', 'resumen']);
  t = T.registrarMedicion(t, 'TENSION', '1');
  assert.equal('firma' in construirPaquete(t, () => 'X').paquete, false);
});

test('el identificador se conserva en un reenvío y se renueva con cada cambio', () => {
  let t = T.marcarPunto(T.iniciar(nuevoTrabajo(), AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' }), 'INS_FILTROS', { resultado: 'OK' });
  t = { ...t, sync: { estado: 'pendiente', paquete_id: 'ENVIADO' } };
  assert.equal(construirPaquete(t, () => 'NUEVO').paquete.paquete_id, 'ENVIADO');
  const cambiado = T.registrarMedicion(t, 'TENSION', '5');
  assert.equal(cambiado.sync.paquete_id, null);
  assert.equal(construirPaquete(cambiado, () => 'NUEVO').paquete.paquete_id, 'NUEVO');
});

test('erroresLocales detecta incidencia sin gravedad y medición fuera de rango', () => {
  const t = T.iniciar(nuevoTrabajo(), AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' });
  assert.deepEqual(erroresLocales(t), []);
  t.local.puntos = { INS_FILTROS: { resultado: 'INCIDENCIA', gravedad: '', nota: '' } };
  t.local.mediciones = { TENSION: '900' };
  const e = erroresLocales(t);
  assert.equal(e.length, 2);
  assert.match(e[0], /gravedad/);
  assert.match(e[1], /Tensión debe estar entre/);
});

test('las fotos viajan con su identificador para que el servidor no las duplique', () => {
  let t = T.agregarFoto(T.iniciar(nuevoTrabajo(), AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' }), foto('uno'));
  const { paquete, fotos } = construirPaquete(t, () => 'X');
  assert.deepEqual(paquete.fotos_ids, ['uno']);
  assert.equal(fotos.length, 1);
});

test('no se envían mediciones que ya no están elegidas', () => {
  const sin = nuevoTrabajo();
  sin.catalogo = { puntos: [], mediciones: [], mediciones_elegibles: [{ codigo: 'TENSION', etiqueta: 'Tensión', unidad: 'V', minimo: '0.00', maximo: '500.00' }] };
  const t = T.iniciar(sin, AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' });
  t.local.elegidas = ['TENSION'];
  t.local.mediciones = { TENSION: '12', CORRIENTE: '4' };
  const { paquete } = construirPaquete(t, () => 'X');
  assert.deepEqual(paquete.mediciones, [{ codigo: 'TENSION', valor: '12' }]);
  assert.deepEqual(erroresLocales(t), []);
});

test('el paquete lleva el estado de llegada solo mientras la orden está Asignada', () => {
  const t = T.iniciar(nuevoTrabajo(), AHORA, { estado: 'FUGA' }, { codigo: 'SP-1' });
  assert.deepEqual(construirPaquete(t).paquete.llegada, { estado: 'FUGA', texto: '' });
  const ya = { ...t, orden: { ...t.orden, estado: 'EN_EJECUCION' } };
  assert.equal('llegada' in construirPaquete(ya).paquete, false);
});

test('el paquete lleva la verificación del equipo solo mientras la orden está Asignada', () => {
  const t = T.iniciar(nuevoTrabajo(), AHORA, { estado: 'NORMAL' }, { codigo: 'XX', continuar: true, nota: 'otra unidad' });
  assert.deepEqual(construirPaquete(t).paquete.verificacion, { codigo: 'XX', continuar: true, nota: 'otra unidad' });
  const ya = { ...t, orden: { ...t.orden, estado: 'EN_EJECUCION' } };
  assert.equal('verificacion' in construirPaquete(ya).paquete, false);
});

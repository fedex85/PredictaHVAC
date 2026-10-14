import test from 'node:test';
import assert from 'node:assert/strict';
import { formatoNumero, resumenParaFirma } from '../core/static/sinconexion/resumen.js';
import { iniciar, marcarPunto, registrarMedicion, fijarTextos, agregarFoto } from '../core/static/sinconexion/trabajo.js';
import { nuevoTrabajo, AHORA } from './fixture.mjs';

test('formatoNumero equivale a Decimal.normalize()', () => {
  const casos = { '230.00': '230', '12.50': '12.5', '0.00': '0', '-5.00': '-5', '100': '100', '0.5': '0.5', '1000.00': '1000', '007.10': '7.1', '12,5': '12.5' };
  for (const [entrada, salida] of Object.entries(casos)) assert.equal(formatoNumero(entrada), salida, entrada);
});

const REFERENCIA = [
  'Estado de los filtros: OK',
  'Estado de la batería y del serpentín: Incidencia Alta. Fuga',
  'Fijaciones y soportes en buen estado: sin marcar',
  'Aislamiento de las tuberías en buen estado: sin marcar',
  'Limpieza general del equipo: sin marcar',
  'Limpieza de la unidad interior: sin marcar',
  'Señal de arranque y contactor-compresor correctos: sin marcar',
  'Ventilación correcta: sin marcar',
  'Evacuación de condensados correcta: sin marcar',
  'Funcionamiento estable, sin vibraciones anómalas: sin marcar',
  'Sin fugas visibles de refrigerante ni de aceite: sin marcar',
  'Temperatura de impulsión: sin medir',
  'Temperatura de retorno: sin medir',
  'Tensión: 230 V',
  'Corriente: sin medir',
  'Presión alta: sin medir',
  'Presión baja: sin medir',
  'Observaciones: Revisión completa',
  'Materiales: Filtro x2',
  'Fotografías: 3',
];

function trabajoDeReferencia() {
  let t = iniciar(nuevoTrabajo(), AHORA);
  t = marcarPunto(t, 'INS_FILTROS', { resultado: 'OK' });
  t = marcarPunto(t, 'INS_BATERIA', { resultado: 'INCIDENCIA', gravedad: 'ALTA', nota: 'Fuga' });
  t = registrarMedicion(t, 'TENSION', '230');
  t = fijarTextos(t, { observaciones: 'Revisión completa', materiales: 'Filtro x2' });
  for (let i = 0; i < 3; i++) t = agregarFoto(t, { id: `f${i}`, blob: { size: 10 }, nombre: `f${i}.jpg` });
  return t;
}

test('el resumen coincide línea a línea con el del servidor', () => {
  assert.deepEqual(resumenParaFirma(trabajoDeReferencia()), REFERENCIA);
});

test('sin materiales y fotos del servidor se suman a las locales', () => {
  let t = nuevoTrabajo({ estado_actual: { puntos: [], mediciones: [], observaciones: '', materiales: '', sin_materiales: false, fotos: 2, firma: false } });
  t = iniciar(t, AHORA);
  t = fijarTextos(t, { sin_materiales: true });
  t = agregarFoto(t, { id: 'a', blob: { size: 1 }, nombre: 'a.jpg' });
  const r = resumenParaFirma(t);
  assert.equal(r.at(-2), 'Materiales: ninguno');
  assert.equal(r.at(-1), 'Fotografías: 3');
});

test('los valores del servidor se normalizan', () => {
  const t = nuevoTrabajo({ estado_actual: { puntos: [], mediciones: [{ codigo: 'TENSION', valor: '230.00' }, { codigo: 'P_BAJA', valor: '12.50' }], observaciones: ' hola ', materiales: '', sin_materiales: false, fotos: 0, firma: false } });
  const r = resumenParaFirma(t);
  assert.ok(r.includes('Tensión: 230 V'));
  assert.ok(r.includes('Presión baja: 12.5 bar'));
  assert.ok(r.includes('Observaciones: hola'));
});

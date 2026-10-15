import test from 'node:test';
import assert from 'node:assert/strict';
import * as T from '../core/static/sinconexion/trabajo.js';
import { nuevoTrabajo, AHORA } from './fixture.mjs';

const iniciada = () => T.iniciar(nuevoTrabajo(), AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' });
const foto = (id) => ({ id, blob: { size: 5 }, nombre: `${id}.jpg` });
const PNG = 'data:image/png;base64,AAAA';

test('iniciar guarda la hora y no modifica el original', () => {
  const t = nuevoTrabajo();
  const i = T.iniciar(t, AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' });
  assert.equal(i.local.inicio, AHORA.toISOString());
  assert.deepEqual(t.local, {});
});

test('iniciar rechaza una hora anterior a la descarga y una orden ya iniciada', () => {
  assert.throws(() => T.iniciar(nuevoTrabajo(), new Date('2026-10-12T09:00:00Z'), { estado: 'NORMAL' }, { codigo: 'SP-1' }), /fecha y la hora/);
  assert.throws(() => T.iniciar(iniciada(), AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' }), /ya está iniciada/);
  const enEjecucion = nuevoTrabajo(); enEjecucion.orden = { ...enEjecucion.orden, estado: 'EN_EJECUCION' };
  assert.throws(() => T.iniciar(enEjecucion, AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' }), /ya está iniciada/);
});

test('nada se puede editar antes de iniciar', () => {
  assert.equal(T.edicionPermitida(nuevoTrabajo(), 'CHECKLIST'), false);
  assert.throws(() => T.marcarPunto(nuevoTrabajo(), 'INS_FILTROS', { resultado: 'OK' }), /inicia la intervención/);
  assert.equal(T.edicionPermitida(iniciada(), 'CHECKLIST'), true);
});

test('marcar OK borra gravedad y nota; la incidencia exige gravedad válida', () => {
  let t = T.marcarPunto(iniciada(), 'INS_FILTROS', { resultado: 'INCIDENCIA', gravedad: 'MEDIA', nota: ' sucio ' });
  assert.deepEqual(t.local.puntos.INS_FILTROS, { resultado: 'INCIDENCIA', gravedad: 'MEDIA', nota: 'sucio' });
  t = T.marcarPunto(t, 'INS_FILTROS', { resultado: 'OK', gravedad: 'ALTA', nota: 'x' });
  assert.deepEqual(t.local.puntos.INS_FILTROS, { resultado: 'OK', gravedad: '', nota: '' });
  assert.throws(() => T.marcarPunto(t, 'INS_FILTROS', { resultado: 'INCIDENCIA' }), /gravedad/);
  assert.throws(() => T.marcarPunto(t, 'INS_FILTROS', { resultado: 'INCIDENCIA', gravedad: 'GRAVISIMA' }), /gravedad/);
  assert.throws(() => T.marcarPunto(t, 'NO_EXISTE', { resultado: 'OK' }), /desconocido/);
});

test('mediciones: coma decimal, 2 decimales, texto y rango', () => {
  const t = iniciada();
  assert.equal(T.registrarMedicion(t, 'TENSION', '230,5').local.mediciones.TENSION, '230.5');
  assert.throws(() => T.registrarMedicion(t, 'TENSION', '230.123'), /2 decimales/);
  assert.throws(() => T.registrarMedicion(t, 'TENSION', 'abc'), /número válido/);
  assert.throws(() => T.registrarMedicion(t, 'TENSION', '1e3'), /número válido/);
  assert.throws(() => T.registrarMedicion(t, 'TENSION', '900'), /Tensión debe estar entre 0.00 y 500.00 V/);
  assert.throws(() => T.registrarMedicion(t, 'NADA', '1'), /desconocida/);
  const vacia = T.registrarMedicion(T.registrarMedicion(t, 'TENSION', '5'), 'TENSION', '');
  assert.equal(vacia.local.mediciones, undefined);
});

test('textos: sin materiales vacía los materiales', () => {
  let t = T.fijarTextos(iniciada(), { materiales: 'Filtro', observaciones: 'ok' });
  t = T.fijarTextos(t, { sin_materiales: true });
  assert.equal(t.local.sin_materiales, true);
  assert.equal(t.local.materiales, '');
  t = T.fijarTextos(t, { materiales: 'otro' });
  assert.equal(t.local.materiales, '');
});

test('fotos: se añaden, se quitan, no más del máximo ni las ya enviadas', () => {
  let t = T.agregarFoto(iniciada(), foto('a'));
  t = T.quitarFoto(t, 'a');
  assert.equal(t.local.fotos, undefined);
  assert.throws(() => T.quitarFoto(t, 'zzz'), /ya está en el servidor/);
  t = T.agregarFoto(t, foto('b'));
  t.local.fotos[0].enviada = true;
  assert.throws(() => T.quitarFoto(t, 'b'), /ya está en el servidor/);
  assert.throws(() => T.agregarFoto(iniciada(), { id: 'g', blob: { size: 11 * 1024 * 1024 }, nombre: 'g.jpg' }), /10 MB/);
  let lleno = iniciada();
  for (let i = 0; i < 20; i++) lleno = T.agregarFoto(lleno, foto(`f${i}`));
  assert.throws(() => T.agregarFoto(lleno, foto('extra')), /Máximo 20/);
});

test('la firma queda vigente y cualquier cambio posterior la invalida', () => {
  let t = T.guardarFirma(iniciada(), { firmante: ' Cliente ', imagen: PNG });
  assert.equal(t.local.firma.firmante, 'Cliente');
  assert.equal(T.firmaVigente(t), true);
  t = T.registrarMedicion(t, 'TENSION', '230');
  assert.equal(T.firmaVigente(t), false);
  assert.ok(T.faltantes(t).includes('El resumen cambió después de la firma: recoge la firma de nuevo'));
});

test('la firma exige nombre e imagen PNG', () => {
  assert.throws(() => T.guardarFirma(iniciada(), { firmante: ' ', imagen: PNG }), /nombre/);
  assert.throws(() => T.guardarFirma(iniciada(), { firmante: 'A', imagen: 'x' }), /no es válida/);
});

test('subsanación: solo se edita el bloque indicado', () => {
  const t = nuevoTrabajo();
  t.orden = { ...t.orden, estado: 'EN_EJECUCION', subsanacion_motivo: 'Faltan datos', subsanacion_bloque: 'MEDICIONES' };
  assert.equal(T.edicionPermitida(t, 'MEDICIONES'), true);
  assert.equal(T.edicionPermitida(t, 'CHECKLIST'), false);
  assert.throws(() => T.marcarPunto(t, 'INS_FILTROS', { resultado: 'OK' }), /solo permite editar: Mediciones/);
  assert.equal(T.edicionPermitida(t, 'FIRMA'), true);
  T.registrarMedicion(t, 'TENSION', '230');
  const toda = nuevoTrabajo();
  toda.orden = { ...toda.orden, estado: 'EN_EJECUCION', subsanacion_motivo: 'Revisar', subsanacion_bloque: '' };
  assert.equal(T.edicionPermitida(toda, 'FOTOS'), true);
});

test('faltantes de una orden recién iniciada replica validar_envio', () => {
  const f = T.faltantes(iniciada());
  assert.ok(f.includes('Falta marcar: Estado de los filtros'));
  assert.ok(f.includes('Falta medir: Tensión'));
  assert.ok(f.includes('Faltan 3 fotografías'));
  assert.ok(f.includes('Falta la firma del cliente'));
  assert.ok(f.includes('Materiales: marca SIN MATERIALES o registra al menos un material.'));
  assert.ok(!f.some((x) => x.startsWith('Las observaciones')));
});

test('faltantes: observaciones obligatorias con incidencias y sin checklist; una foto', () => {
  let t = T.marcarPunto(iniciada(), 'INS_FILTROS', { resultado: 'INCIDENCIA', gravedad: 'LEVE' });
  assert.ok(T.faltantes(t).includes('Las observaciones técnicas son obligatorias: hay incidencias en el checklist.'));
  t = T.agregarFoto(T.agregarFoto(t, foto('a')), foto('b'));
  assert.ok(T.faltantes(t).includes('Falta 1 fotografía'));
  const sin = nuevoTrabajo();
  sin.catalogo = { puntos: [], mediciones: [], mediciones_elegibles: [] };
  assert.ok(T.faltantes(T.iniciar(sin, AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' })).includes('Las observaciones técnicas son obligatorias: OT sin checklist.'));
});

test('orden completa: no falta nada', () => {
  let t = iniciada();
  for (const p of t.catalogo.puntos) t = T.marcarPunto(t, p.codigo, { resultado: 'OK' });
  for (const m of t.catalogo.mediciones) t = T.registrarMedicion(t, m.codigo, '10');
  t = T.fijarTextos(t, { observaciones: 'Todo bien', sin_materiales: true });
  for (let i = 0; i < 3; i++) t = T.agregarFoto(t, foto(`f${i}`));
  t = T.guardarFirma(t, { firmante: 'Cliente', imagen: PNG });
  t = T.guardarFirmaTecnico(t, { imagen: PNG });
  assert.deepEqual(T.faltantes(t), []);
});

test('el técnico firma después del cliente y su firma no se conserva si el resumen cambia', () => {
  assert.throws(() => T.guardarFirmaTecnico(iniciada(), { imagen: PNG }), /cliente debe firmar antes/);
  let t = T.guardarFirma(iniciada(), { firmante: 'Cliente', imagen: PNG });
  t = T.guardarFirmaTecnico(t, { imagen: PNG });
  assert.equal(T.firmaTecnicoVigente(t), true);
  assert.throws(() => T.guardarFirmaTecnico(t, { imagen: 'x' }), /no es válida/);
  t = T.registrarMedicion(t, 'TENSION', '230');
  assert.equal(T.firmaTecnicoVigente(t), false);
  assert.ok(T.faltantes(t).includes('El resumen cambió después de tu firma: firma de nuevo como técnico'));
});

test('subsanación: el técnico siempre puede renovar su firma y la del cliente se conserva', () => {
  let t = T.guardarFirma(iniciada(), { firmante: 'Cliente', imagen: PNG });
  t.orden = { ...t.orden, subsanacion_motivo: 'Faltan fotos', subsanacion_bloque: 'FOTOS' };
  assert.equal(T.edicionPermitida(t, 'FIRMA_TECNICO'), true);
  t = T.agregarFoto(t, foto('a'));
  assert.equal(T.firmaVigente(t), true);
  assert.equal(T.faltantes(t).includes('Falta la firma del técnico'), true);
});

test('elegir mediciones en una OT sin checklist', () => {
  const t = nuevoTrabajo();
  t.catalogo = { puntos: [], mediciones: [], mediciones_elegibles: [
    { codigo: 'TENSION', etiqueta: 'Tensión', unidad: 'V', minimo: '0.00', maximo: '500.00' },
    { codigo: 'CORRIENTE', etiqueta: 'Corriente', unidad: 'A', minimo: '0.00', maximo: '500.00' }] };
  let i = T.iniciar(t, AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' });
  assert.throws(() => T.elegirMediciones(i, ['NADA']), /desconocida/);
  i = T.elegirMediciones(i, ['TENSION', 'CORRIENTE']);
  i = T.registrarMedicion(i, 'TENSION', '230');
  assert.ok(T.faltantes(i).includes('Falta medir: Corriente'));
});

test('no se puede borrar una medición que el servidor ya tiene', () => {
  const t = T.iniciar(nuevoTrabajo({ estado_actual: { puntos: [], mediciones: [{ codigo: 'TENSION', valor: '12.50' }], observaciones: '', materiales: '', sin_materiales: false, fotos: 0, firma: false } }), AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' });
  assert.throws(() => T.registrarMedicion(t, 'TENSION', ''), /no se puede borrar/);
  assert.equal(T.registrarMedicion(t, 'TENSION', '13').local.mediciones.TENSION, '13');
});

test('una firma obsoleta del servidor no se da por vigente', () => {
  const t = T.iniciar(nuevoTrabajo({ estado_actual: { puntos: [], mediciones: [], observaciones: '', materiales: '', sin_materiales: false, fotos: 0, firma: true, firma_resumen: null } }), AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' });
  assert.equal(T.firmaVigente(t), false);
  assert.equal(T.edicionPermitida(t, 'FIRMA'), true);
  assert.ok(T.faltantes(t).includes('El resumen cambió después de la firma: recoge la firma de nuevo'));
});

test('desmarcar una medición elimina sus valores locales', () => {
  const sin = nuevoTrabajo();
  sin.catalogo = { puntos: [], mediciones: [], mediciones_elegibles: [{ codigo: 'TENSION', etiqueta: 'Tensión', unidad: 'V', minimo: '0.00', maximo: '500.00' }] };
  let t = T.elegirMediciones(T.iniciar(sin, AHORA, { estado: 'NORMAL' }, { codigo: 'SP-1' }), ['TENSION']);
  t = T.registrarMedicion(t, 'TENSION', '12');
  t = T.elegirMediciones(t, []);
  assert.equal(t.local.mediciones, undefined);
});

test('iniciar exige el estado de llegada y «Otro» exige texto', () => {
  assert.throws(() => T.iniciar(nuevoTrabajo(), AHORA), /estado en el que encuentras el equipo/);
  assert.throws(() => T.iniciar(nuevoTrabajo(), AHORA, { estado: 'XX' }), /estado en el que encuentras el equipo/);
  assert.throws(() => T.iniciar(nuevoTrabajo(), AHORA, { estado: 'OTRO', texto: '  ' }), /Describe el estado/);
  const t = T.iniciar(nuevoTrabajo(), AHORA, { estado: 'OTRO', texto: ' Gotea ' }, { codigo: 'SP-1' });
  assert.deepEqual(t.local.llegada, { estado: 'OTRO', texto: 'Gotea' });
  assert.deepEqual(T.iniciar(nuevoTrabajo(), AHORA, { estado: 'NORMAL', texto: 'x' }, { codigo: 'SP-1' }).local.llegada, { estado: 'NORMAL', texto: '' });
});

test('iniciar exige identificar el equipo: código, QR o discrepancia con observación', () => {
  const LL = { estado: 'NORMAL' };
  assert.throws(() => T.iniciar(nuevoTrabajo(), AHORA, LL), /Identifica el equipo/);
  assert.throws(() => T.iniciar(nuevoTrabajo(), AHORA, LL, { codigo: 'OTRO-9' }), /no coincide con el de la orden \(SP-1\)/);
  assert.throws(() => T.iniciar(nuevoTrabajo(), AHORA, LL, { codigo: 'OTRO-9', continuar: true }), /describe la incidencia/);
  assert.deepEqual(T.iniciar(nuevoTrabajo(), AHORA, LL, { codigo: ' sp-1 ' }).local.verificacion, { codigo: 'sp-1', continuar: false, nota: '' });
  const d = T.iniciar(nuevoTrabajo(), AHORA, LL, { codigo: 'OTRO-9', continuar: true, nota: 'Es la unidad de al lado' });
  assert.deepEqual(d.local.verificacion, { codigo: 'OTRO-9', continuar: true, nota: 'Es la unidad de al lado' });
  const conId = nuevoTrabajo(); conId.equipo.id = 7;
  assert.equal(T.equipoCoincide(conId, 'https://x.es/equipos/7/'), true);
  assert.equal(T.equipoCoincide(conId, 'https://x.es/equipos/8/'), false);
  assert.equal(T.equipoCoincide(nuevoTrabajo(), 'https://x.es/equipos/7/'), false);
});

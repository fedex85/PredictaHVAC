import test from 'node:test';
import assert from 'node:assert/strict';
import { almacenEnMemoria } from '../core/static/sinconexion/almacen.js';
import * as T from '../core/static/sinconexion/trabajo.js';
import { sincronizarOrden, sincronizarPendientes, sincronizando } from '../core/static/sinconexion/sync.js';
import { nuevoTrabajo, AHORA } from './fixture.mjs';

const PNG = 'data:image/png;base64,AAAA';
const blob = (n = 5) => new Blob([new Uint8Array(n)], { type: 'image/jpeg' });
const respuesta = (cuerpo, estado = 200, extra = {}) => ({ ok: estado < 400, status: estado, redirected: false, json: async () => cuerpo, ...extra });
const OK = (extra = {}) => respuesta({ ok: true, repetido: false, estado: 'EN_EJECUCION', firma: 'ninguna', avisos: [], faltan: [], ...extra });

async function preparar(configurar = (t) => t) {
  const almacen = almacenEnMemoria();
  let t = T.iniciar(nuevoTrabajo(), AHORA);
  t = T.marcarPunto(t, 'INS_FILTROS', { resultado: 'OK' });
  t = T.registrarMedicion(t, 'TENSION', '230');
  t = T.fijarTextos(t, { observaciones: 'obs', sin_materiales: true });
  t = T.agregarFoto(t, { id: 'a', blob: blob(), nombre: 'a.jpg' });
  t = configurar(t);
  await almacen.guardar(t);
  return almacen;
}
const ctx = (almacen, fetch) => ({ almacen, fetch, csrf: 'tok' });

test('éxito: marca la orden como sincronizada y consolida lo enviado', async () => {
  const almacen = await preparar();
  let llamada;
  const r = await sincronizarOrden(7, ctx(almacen, async (url, op) => { llamada = { url, op }; return OK(); }));
  assert.equal(r.estado, 'sincronizada');
  assert.equal(llamada.url, '/ordenes/7/sincronizar/');
  assert.equal(llamada.op.headers['X-CSRFToken'], 'tok');
  const t = await almacen.obtener(7);
  assert.deepEqual(t.local, {});
  assert.equal(t.sync.estado, 'sincronizada');
  assert.equal(t.orden.estado, 'EN_EJECUCION');
  assert.equal(t.base.fotos, 1);
  assert.equal(t.base.observaciones, 'obs');
  assert.equal(T.estadoLegible(t), 'Sincronizada');
  assert.equal(T.faltantes(t).includes('Faltan 2 fotografías'), true);
});

test('el cuerpo es multipart: paquete JSON y una foto por cada no enviada', async () => {
  const almacen = await preparar((t) => T.agregarFoto(t, { id: 'b', blob: blob(), nombre: 'b.jpg' }));
  let cuerpo;
  await sincronizarOrden(7, ctx(almacen, async (u, op) => { cuerpo = op.body; return OK(); }));
  const paquete = JSON.parse(cuerpo.get('paquete'));
  assert.match(paquete.paquete_id, /^[0-9a-f-]{36}$/);
  assert.equal(paquete.inicio, AHORA.toISOString());
  assert.equal(cuerpo.getAll('fotos').length, 2);
});

test('la firma guardada queda vigente tras sincronizar', async () => {
  const almacen = await preparar((t) => T.guardarFirma(t, { firmante: 'C', imagen: PNG }));
  await sincronizarOrden(7, ctx(almacen, async () => OK({ firma: 'guardada' })));
  const t = await almacen.obtener(7);
  assert.equal(t.base.firma, true);
  assert.equal(T.firmaVigente(t), true);
});

test('firma descartada: queda el aviso y la firma por recoger de nuevo', async () => {
  const almacen = await preparar((t) => T.guardarFirma(t, { firmante: 'C', imagen: PNG }));
  const r = await sincronizarOrden(7, ctx(almacen, async () => OK({ firma: 'descartada', avisos: ['La firma no corresponde al resumen actual de la orden: el cliente debe firmar de nuevo.'] })));
  assert.equal(r.estado, 'sincronizada');
  assert.equal(r.avisos.length, 1);
  const t = await almacen.obtener(7);
  assert.equal(t.sync.avisos.length, 1);
  assert.ok(T.faltantes(t).includes('Falta la firma del cliente'));
});

test('repetido:true se trata como éxito', async () => {
  const almacen = await preparar();
  const r = await sincronizarOrden(7, ctx(almacen, async () => OK({ repetido: true })));
  assert.equal(r.estado, 'sincronizada');
});

for (const [codigo, texto] of [[400, 'Paquete mal'], [403, 'No eres el técnico'], [409, 'La orden fue cancelada']]) {
  test(`HTTP ${codigo}: Error con el primer mensaje y nada se da por enviado`, async () => {
    const almacen = await preparar();
    const r = await sincronizarOrden(7, ctx(almacen, async () => respuesta({ ok: false, errores: [texto, 'otro'] }, codigo)));
    assert.equal(r.estado, 'error');
    assert.equal(r.mensaje, texto);
    const t = await almacen.obtener(7);
    assert.equal(t.sync.estado, 'error');
    assert.equal(t.local.fotos.length, 1);
    assert.equal(t.local.fotos[0].enviada, undefined);
    assert.equal(T.estadoLegible(t), 'Error');
  });
}

test('sesión caducada (redirigida o 401): pide iniciar sesión y conserva los datos', async () => {
  for (const r401 of [respuesta('<html>', 200, { redirected: true, json: async () => { throw new Error('html'); } }), respuesta({}, 401)]) {
    const almacen = await preparar();
    const r = await sincronizarOrden(7, ctx(almacen, async () => r401));
    assert.equal(r.estado, 'sin_sesion');
    assert.match(r.mensaje, /Inicia sesión para sincronizar/);
    assert.equal((await almacen.obtener(7)).local.inicio, AHORA.toISOString());
  }
});

test('fallo de red: sigue pendiente, sin error, y el reenvío reutiliza el identificador', async () => {
  const almacen = await preparar();
  const r = await sincronizarOrden(7, ctx(almacen, async () => { throw new TypeError('Failed'); }));
  assert.equal(r.estado, 'pendiente');
  const t = await almacen.obtener(7);
  assert.notEqual(t.sync.estado, 'error');
  const id1 = t.sync.paquete_id;
  assert.ok(id1);
  let id2;
  await sincronizarOrden(7, ctx(almacen, async (u, op) => { id2 = JSON.parse(op.body.get('paquete')).paquete_id; return OK(); }));
  assert.equal(id2, id1);
});

test('dos sincronizaciones simultáneas: la segunda es «ocupada» y solo hay un fetch', async () => {
  const almacen = await preparar();
  let llamadas = 0, liberar;
  const espera = new Promise((ok) => { liberar = ok; });
  const fetch = async () => { llamadas++; await espera; return OK(); };
  const a = sincronizarOrden(7, ctx(almacen, fetch));
  await new Promise((ok) => setTimeout(ok, 10));
  assert.equal(sincronizando(7), true);
  const b = await sincronizarOrden(7, ctx(almacen, fetch));
  assert.equal(b.estado, 'ocupada');
  liberar();
  assert.equal((await a).estado, 'sincronizada');
  assert.equal(llamadas, 1);
  assert.equal(sincronizando(7), false);
});

test('un cambio posterior renueva el identificador y reenvía solo lo nuevo', async () => {
  const almacen = await preparar();
  let primero;
  await sincronizarOrden(7, ctx(almacen, async (u, op) => { primero = JSON.parse(op.body.get('paquete')).paquete_id; return OK(); }));
  let t = await almacen.obtener(7);
  t = T.registrarMedicion(t, 'CORRIENTE', '10');
  await almacen.guardar(t);
  let cuerpo;
  await sincronizarOrden(7, ctx(almacen, async (u, op) => { cuerpo = op.body; return OK(); }));
  const p = JSON.parse(cuerpo.get('paquete'));
  assert.notEqual(p.paquete_id, primero);
  assert.deepEqual(p.mediciones, [{ codigo: 'CORRIENTE', valor: '10' }]);
  assert.equal('inicio' in p, false);
  assert.equal('puntos' in p, false);
  assert.equal(cuerpo.getAll('fotos').length, 0);
});

test('sin cambios locales no se envía nada', async () => {
  const almacen = almacenEnMemoria();
  await almacen.guardar(nuevoTrabajo());
  let llamado = false;
  const r = await sincronizarOrden(7, ctx(almacen, async () => { llamado = true; return OK(); }));
  assert.equal(llamado, false);
  assert.equal(r.estado, 'sincronizada');
});

test('sincronizarPendientes procesa solo las que tienen cambios, de una en una, y salta las que dieron error', async () => {
  const almacen = almacenEnMemoria();
  const a = T.marcarPunto(T.iniciar(nuevoTrabajo(), AHORA), 'INS_FILTROS', { resultado: 'OK' });
  const b = structuredClone(a); b.id = 8; b.orden = { ...b.orden, id: 8 };
  const c = nuevoTrabajo(); c.id = 9; c.orden = { ...c.orden, id: 9 };
  const d = structuredClone(a); d.id = 10; d.orden = { ...d.orden, id: 10 }; d.sync = { estado: 'error', paquete_id: null, mensaje: 'x' };
  const otro = structuredClone(a); otro.id = 11; otro.usuario_id = 99;
  for (const t of [a, b, c, d, otro]) await almacen.guardar(t);
  const urls = [];
  let simultaneas = 0, maxima = 0;
  const fetch = async (u) => { urls.push(u); simultaneas++; maxima = Math.max(maxima, simultaneas); await new Promise((ok) => setTimeout(ok, 5)); simultaneas--; return OK(); };
  const r = await sincronizarPendientes({ almacen, fetch, csrf: 't', usuarioId: 3 });
  assert.deepEqual(r.map((x) => x.id), [7, 8]);
  assert.equal(maxima, 1);
  const manual = await sincronizarPendientes({ almacen, fetch, csrf: 't', usuarioId: 3, incluirErrores: true });
  assert.deepEqual(manual.map((x) => x.id), [10]);
});

test('un fallo de escritura no bloquea las siguientes sincronizaciones', async () => {
  const { encolar, vaciarCola } = await import('../core/static/sinconexion/sync.js');
  await encolar(async () => { throw new Error('disco lleno'); }).catch(() => {});
  await vaciarCola(); // no debe lanzar
  const almacen = await preparar();
  const r = await sincronizarOrden(7, ctx(almacen, async () => OK()));
  assert.equal(r.estado, 'sincronizada');
});

test('si hubo cambios durante el envío no se da nada por enviado', async () => {
  const almacen = await preparar();
  const r = await sincronizarOrden(7, ctx(almacen, async () => {
    const t = await almacen.obtener(7);
    await almacen.guardar(T.registrarMedicion(t, 'CORRIENTE', '3')); // otra pestaña edita mientras se envía
    return OK();
  }));
  assert.equal(r.estado, 'pendiente');
  const t = await almacen.obtener(7);
  assert.equal(t.local.mediciones.CORRIENTE, '3');
  assert.equal(t.local.mediciones.TENSION, '230');
});

test('el estado real de la firma del servidor manda tras sincronizar', async () => {
  const almacen = await preparar((t) => T.guardarFirma(t, { firmante: 'C', imagen: PNG }));
  await sincronizarOrden(7, ctx(almacen, async () => OK({ firma: 'guardada', firma_estado: 'obsoleta', firma_resumen: null })));
  const t = await almacen.obtener(7);
  assert.equal(t.base.firma, true);
  assert.equal(t.base.firma_resumen, null);
  assert.equal(T.firmaVigente(t), false);
});

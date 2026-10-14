// Construye lo que se envía a /ordenes/<id>/sincronizar/. Solo cambios hechos en el teléfono.
import { medicionesEfectivas } from './vista.js';
import { validarMedicion, firmaVigente, firmaTecnicoVigente, ErrorTrabajo } from './trabajo.js';

export function uuid4(cripto = globalThis.crypto) {
  const b = new Uint8Array(16);
  cripto.getRandomValues(b);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

// Reutiliza el identificador guardado (un reenvío tras un fallo es idempotente); si no hay, usa `nuevoId()`.
export function construirPaquete(t, nuevoId = uuid4) {
  const l = t.local;
  const paquete = { paquete_id: t.sync.paquete_id || nuevoId() };
  if (t.orden.estado === 'ASIGNADA' && l.inicio) paquete.inicio = l.inicio;
  if (l.elegidas) paquete.elegidas = [...l.elegidas];
  if (l.puntos) paquete.puntos = Object.entries(l.puntos).map(([codigo, p]) => ({ codigo, ...p }));
  if (l.mediciones) {
    const vigentes = new Set(medicionesEfectivas(t).map((m) => m.codigo));
    const lista = Object.entries(l.mediciones).filter(([c, v]) => v !== '' && vigentes.has(c)).map(([codigo, valor]) => ({ codigo, valor }));
    if (lista.length) paquete.mediciones = lista;
  }
  for (const campo of ['observaciones', 'materiales', 'sin_materiales']) if (l[campo] !== undefined) paquete[campo] = l[campo];
  const fotos = (l.fotos || []).filter((f) => !f.enviada).map(({ id, blob, nombre }) => ({ id, blob, nombre }));
  if (l.firma && !l.firma.enviada && firmaVigente(t)) {
    paquete.firma = { firmante: l.firma.firmante, imagen: l.firma.imagen, resumen: l.firma.resumen };
  }
  if (l.firma_tecnico && firmaTecnicoVigente(t)) {
    paquete.firma_tecnico = { imagen: l.firma_tecnico.imagen, resumen: l.firma_tecnico.resumen };
  }
  if (fotos.length) paquete.fotos_ids = fotos.map((f) => f.id);
  return { paquete, fotos };
}

export function erroresLocales(t) {
  const errores = [];
  for (const [codigo, p] of Object.entries(t.local.puntos || {})) {
    if (p.resultado === 'INCIDENCIA' && !['LEVE', 'MEDIA', 'ALTA'].includes(p.gravedad)) errores.push(`Falta la gravedad del punto ${codigo}.`);
  }
  const defs = new Map(medicionesEfectivas(t).map((m) => [m.codigo, m]));
  for (const [codigo, valor] of Object.entries(t.local.mediciones || {})) {
    if (!defs.has(codigo)) continue;
    try { validarMedicion(defs.get(codigo) || {}, valor); } catch (e) { if (e instanceof ErrorTrabajo) errores.push(e.message); else throw e; }
  }
  return errores;
}

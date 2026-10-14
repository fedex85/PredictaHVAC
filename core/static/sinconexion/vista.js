// Estado combinado de una orden descargada: lo que dice el servidor (base) más lo hecho en el teléfono (local).
import { formatoNumero } from './resumen_numero.js';

export function medicionesEfectivas(t) {
  const existentes = t.catalogo.mediciones || [];
  const elegidas = t.local.elegidas;
  if (!elegidas) return existentes;
  const conservadas = existentes.filter((m) => elegidas.includes(m.codigo));
  const codigos = new Set(existentes.map((m) => m.codigo));
  const nuevas = (t.catalogo.mediciones_elegibles || [])
    .filter((m) => elegidas.includes(m.codigo) && !codigos.has(m.codigo))
    .sort((a, b) => (a.codigo < b.codigo ? -1 : a.codigo > b.codigo ? 1 : 0));
  return [...conservadas, ...nuevas];
}

export function vista(t) {
  const base = t.base || {};
  const puntosBase = new Map((base.puntos || []).map((p) => [p.codigo, p]));
  const puntosLocal = t.local.puntos || {};
  const puntos = (t.catalogo.puntos || []).map((p) => {
    const e = puntosLocal[p.codigo] || puntosBase.get(p.codigo) || {};
    return { codigo: p.codigo, bloque: p.bloque, texto: p.texto,
             resultado: e.resultado || '', gravedad: e.gravedad || '', nota: e.nota || '' };
  });
  const medBase = new Map((base.mediciones || []).map((m) => [m.codigo, m.valor]));
  const medLocal = t.local.mediciones || {};
  const mediciones = medicionesEfectivas(t).map((m) => {
    let valor = null;
    if (Object.prototype.hasOwnProperty.call(medLocal, m.codigo)) valor = medLocal[m.codigo];
    else if (medBase.get(m.codigo) != null) valor = medBase.get(m.codigo);
    return { ...m, valor: valor === '' || valor == null ? null : formatoNumero(valor) };
  });
  const pick = (campo, defecto) => (t.local[campo] !== undefined ? t.local[campo] : base[campo] ?? defecto);
  return {
    puntos, mediciones,
    observaciones: pick('observaciones', ''),
    materiales: pick('materiales', ''),
    sin_materiales: Boolean(pick('sin_materiales', false)),
    fotos: (base.fotos || 0) + (t.local.fotos || []).length,
  };
}

// Estado de una orden descargada. Funciones puras: sin DOM ni almacenamiento; cada cambio devuelve una copia.
import { vista, medicionesEfectivas } from './vista.js';
import { resumenParaFirma, formatoNumero } from './resumen.js';

export class ErrorTrabajo extends Error {}

const ETIQUETA_BLOQUE = {
  CHECKLIST: 'Checklist', MEDICIONES: 'Mediciones', OBSERVACIONES: 'Observaciones',
  MATERIALES: 'Materiales', FOTOS: 'Fotos', FIRMA: 'Firma',
};
const GRAVEDADES = ['LEVE', 'MEDIA', 'ALTA'];
const PREFIJO_PNG = 'data:image/png;base64,';

export function crearTrabajo(paquete, usuarioId) {
  return {
    id: paquete.orden.id,
    usuario_id: usuarioId,
    descargada_en: paquete.descargada_en,
    orden: paquete.orden,
    equipo: paquete.equipo,
    catalogo: paquete.catalogo,
    limites: paquete.limites,
    base: paquete.estado_actual,
    local: {},
    sync: { estado: 'pendiente', paquete_id: null },
  };
}

export function tieneTrabajoLocal(t) {
  return Object.keys(t.local || {}).length > 0;
}

export function estadoLegible(t) {
  const estado = t.sync && t.sync.estado;
  if (estado === 'error') return 'Error';
  if (tieneTrabajoLocal(t)) return 'Pendiente de sincronizar';
  if (estado === 'sincronizada') return 'Sincronizada';
  return t.orden.estado === 'EN_EJECUCION' ? 'En curso' : 'Sin iniciar';
}

// ---------------------------------------------------------------- reglas de edición
export function iniciada(t) {
  return t.orden.estado === 'EN_EJECUCION' || Boolean(t.local.inicio);
}

// Vigente = existe una firma (local o del servidor) y firma exactamente el resumen actual.
// El servidor solo entrega `firma_resumen` cuando su firma es vigente; una firma obsoleta nunca se da por buena.
export function conservaFirma(t) {
  return Boolean(t.orden.subsanacion_motivo) && t.orden.subsanacion_bloque !== 'FIRMA';
}

export function firmaVigente(t) {
  const f = t.local.firma || (t.base.firma_resumen ? { resumen: t.base.firma_resumen } : null);
  if (!f) return false;
  // Subsanación que no pide corregir la firma: la firma del cliente se conserva (igual que en el servidor).
  if (conservaFirma(t)) return true;
  return JSON.stringify(f.resumen) === JSON.stringify(resumenParaFirma(t));
}

// La firma del técnico nunca se conserva: si el resumen cambia, firma de nuevo (igual que en el servidor).
export function firmaTecnicoVigente(t) {
  const f = t.local.firma_tecnico || (t.base.firma_tecnico_resumen ? { resumen: t.base.firma_tecnico_resumen } : null);
  return Boolean(f) && JSON.stringify(f.resumen) === JSON.stringify(resumenParaFirma(t));
}

function hayFirmaTecnico(t) {
  return Boolean(t.local.firma_tecnico || t.base.firma_tecnico_resumen || t.base.firma_tecnico);
}

function hayFirma(t) {
  return Boolean(t.local.firma || t.base.firma_resumen || t.base.firma);
}

export function edicionPermitida(t, bloque) {
  if (!iniciada(t)) return false;
  const { subsanacion_motivo: motivo, subsanacion_bloque: solo } = t.orden;
  if (!motivo) return true;
  if (bloque === 'FIRMA_TECNICO') return true;
  if (bloque === 'FIRMA' && t.orden.con_evidencias && !firmaVigente(t)) return true;
  return solo === '' || solo === bloque;
}

function exigir(t, bloque) {
  if (!iniciada(t)) throw new ErrorTrabajo('Primero inicia la intervención.');
  if (!edicionPermitida(t, bloque)) {
    throw new ErrorTrabajo(`Esta subsanación solo permite editar: ${ETIQUETA_BLOQUE[t.orden.subsanacion_bloque] || t.orden.subsanacion_bloque}.`);
  }
}

// Copia el trabajo, aplica el cambio y renueva el identificador del paquete (el contenido ya no es el mismo).
function cambiar(t, fn) {
  const c = structuredClone({ ...t, local: { ...t.local, fotos: undefined } });
  c.local.fotos = t.local.fotos ? [...t.local.fotos] : undefined;
  if (c.local.fotos === undefined) delete c.local.fotos;
  fn(c);
  for (const [k, v] of Object.entries(c.local)) {
    const vacio = v === undefined || (Array.isArray(v) && !v.length)
      || (v && typeof v === 'object' && !Array.isArray(v) && !('size' in v) && !Object.keys(v).length);
    if (vacio) delete c.local[k];
  }
  c.sync = { ...c.sync, paquete_id: null, estado: 'pendiente' };
  return c;
}

// ---------------------------------------------------------------- cambios
export const LLEGADAS = [['NORMAL', 'Normal'], ['RUIDO', 'Ruido anómalo del compresor'], ['FUGA', 'Fuga visible de líquido/aceite'],
  ['NO_ARRANCA', 'No arranca'], ['CARCASA', 'Carcasa/exterior deteriorado'], ['OTRO', 'Otro']];

// Mismas reglas que ordenes.identificar_equipo: URL de la ficha (QR) o código escrito a mano.
export function equipoCoincide(t, texto) {
  const valor = String(texto || '').trim();
  if (!valor) return null;
  const m = valor.match(/\/equipos\/(\d+)\/?(?:[?#].*)?$/);
  if (m) return t.equipo.id !== undefined ? Number(m[1]) === Number(t.equipo.id) : false;
  return valor.toLowerCase() === String(t.equipo.codigo || '').toLowerCase();
}

export function iniciar(t, ahora, llegada = {}, verificacion = {}) {
  if (t.orden.estado !== 'ASIGNADA' || t.local.inicio) throw new ErrorTrabajo('Esta orden ya está iniciada.');
  const estado = String(llegada.estado || '');
  const texto = String(llegada.texto || '').trim().slice(0, 255);
  if (!LLEGADAS.some(([c]) => c === estado)) throw new ErrorTrabajo('Indica el estado en el que encuentras el equipo al llegar.');
  if (estado === 'OTRO' && !texto) throw new ErrorTrabajo('Describe el estado de llegada («Otro»).');
  const codigo = String(verificacion.codigo || '').trim().slice(0, 300);
  const nota = String(verificacion.nota || '').trim().slice(0, 200);
  const continuar = Boolean(verificacion.continuar);
  const coincide = equipoCoincide(t, codigo) === true;
  if (!coincide) {
    if (!codigo && !continuar) throw new ErrorTrabajo('Identifica el equipo (escanea su QR o escribe su código) antes de iniciar.');
    if (!continuar) throw new ErrorTrabajo(`El equipo identificado (${codigo}) no coincide con el de la orden (${t.equipo.codigo}). Vuelve a escanear, busca manualmente o continúa y reporta una incidencia.`);
    if (!nota) throw new ErrorTrabajo('Para continuar con un equipo distinto describe la incidencia en la observación.');
  }
  if (ahora < new Date(t.descargada_en)) {
    throw new ErrorTrabajo('La hora del teléfono es anterior a la descarga de la orden. Revisa la fecha y la hora del teléfono.');
  }
  return cambiar(t, (c) => { c.local.inicio = ahora.toISOString(); c.local.llegada = { estado, texto: estado === 'OTRO' ? texto : '' }; c.local.verificacion = { codigo, continuar: !coincide, nota: coincide ? '' : nota }; });
}

export function marcarPunto(t, codigo, { resultado, gravedad = '', nota = '' }) {
  exigir(t, 'CHECKLIST');
  if (!t.catalogo.puntos.some((p) => p.codigo === codigo)) throw new ErrorTrabajo('Punto de checklist desconocido.');
  let valor;
  if (resultado === 'OK') valor = { resultado: 'OK', gravedad: '', nota: '' };
  else if (resultado === 'INCIDENCIA') {
    if (!GRAVEDADES.includes(gravedad)) throw new ErrorTrabajo('Indica la gravedad de la incidencia.');
    valor = { resultado: 'INCIDENCIA', gravedad, nota: String(nota || '').trim().slice(0, 255) };
  } else throw new ErrorTrabajo('Marca el punto como OK o como Incidencia.');
  return cambiar(t, (c) => { c.local.puntos = { ...(c.local.puntos || {}), [codigo]: valor }; });
}

export function validarMedicion(definicion, texto) {
  const limpio = String(texto ?? '').trim().replace(',', '.');
  if (limpio === '') return { valor: '' };
  if (!/^-?\d+(\.\d{1,2})?$/.test(limpio)) throw new ErrorTrabajo('Introduce un número válido con hasta 2 decimales (por ejemplo 12,5).');
  const n = Number(limpio);
  if (definicion.minimo != null && definicion.maximo != null && (n < Number(definicion.minimo) || n > Number(definicion.maximo))) {
    throw new ErrorTrabajo(`${definicion.etiqueta} debe estar entre ${definicion.minimo} y ${definicion.maximo} ${definicion.unidad}.`);
  }
  return { valor: limpio };
}

export function registrarMedicion(t, codigo, texto) {
  exigir(t, 'MEDICIONES');
  const definicion = medicionesEfectivas(t).find((m) => m.codigo === codigo);
  if (!definicion) throw new ErrorTrabajo('Medición desconocida.');
  const { valor } = validarMedicion(definicion, texto);
  const guardada = (t.base.mediciones || []).find((m) => m.codigo === codigo);
  if (valor === '' && guardada && guardada.valor != null && guardada.valor !== '') {
    throw new ErrorTrabajo('Esa medición ya está guardada en el servidor: no se puede borrar, corrígela con otro valor.');
  }
  return cambiar(t, (c) => {
    const m = { ...(c.local.mediciones || {}) };
    if (valor === '') delete m[codigo]; else m[codigo] = valor;
    c.local.mediciones = m;
  });
}

export function elegirMediciones(t, codigos) {
  exigir(t, 'MEDICIONES');
  if (!(t.catalogo.mediciones_elegibles || []).length) throw new ErrorTrabajo('Las mediciones se eligen solo en OT sin checklist.');
  const validos = new Set(t.catalogo.mediciones_elegibles.map((m) => m.codigo));
  if (!codigos.every((c) => validos.has(c))) throw new ErrorTrabajo('Medición desconocida.');
  return cambiar(t, (c) => {
    c.local.elegidas = [...new Set(codigos)];
    if (c.local.mediciones) {
      c.local.mediciones = Object.fromEntries(Object.entries(c.local.mediciones).filter(([k]) => codigos.includes(k)));
    }
  });
}

export function fijarTextos(t, { observaciones, materiales, sin_materiales: sinMateriales }) {
  if (observaciones !== undefined) exigir(t, 'OBSERVACIONES');
  if (materiales !== undefined || sinMateriales !== undefined) exigir(t, 'MATERIALES');
  return cambiar(t, (c) => {
    if (observaciones !== undefined) c.local.observaciones = String(observaciones);
    if (sinMateriales !== undefined) {
      c.local.sin_materiales = Boolean(sinMateriales);
      if (sinMateriales) c.local.materiales = '';
    }
    if (materiales !== undefined && !c.local.sin_materiales) c.local.materiales = String(materiales);
  });
}

export function agregarFoto(t, { id, blob, nombre }) {
  exigir(t, 'FOTOS');
  if (vista(t).fotos >= t.limites.fotos_max) throw new ErrorTrabajo(`Máximo ${t.limites.fotos_max} fotografías.`);
  if (blob && blob.size !== undefined && blob.size > t.limites.foto_bytes) throw new ErrorTrabajo('La fotografía pesa más de 10 MB.');
  const nueva = { id, blob, nombre };
  const c = cambiar(t, () => {});
  c.local.fotos = [...(t.local.fotos || []), nueva];
  return c;
}

export function quitarFoto(t, id) {
  exigir(t, 'FOTOS');
  const foto = (t.local.fotos || []).find((f) => f.id === id);
  if (!foto || foto.enviada) throw new ErrorTrabajo('Esa fotografía ya está en el servidor: no se puede quitar sin conexión.');
  const c = cambiar(t, () => {});
  c.local.fotos = (t.local.fotos || []).filter((f) => f.id !== id);
  if (!c.local.fotos.length) delete c.local.fotos;
  return c;
}

export function guardarFirma(t, { firmante, imagen }) {
  if (!t.orden.con_evidencias) throw new ErrorTrabajo('Esta orden no lleva firma del cliente.');
  exigir(t, 'FIRMA');
  const nombre = String(firmante || '').trim();
  if (!nombre) throw new ErrorTrabajo('Escribe el nombre de quien firma.');
  if (typeof imagen !== 'string' || !imagen.startsWith(PREFIJO_PNG)) throw new ErrorTrabajo('La firma no es válida. Vuelve a dibujarla.');
  const resumen = resumenParaFirma(t);
  return cambiar(t, (c) => { c.local.firma = { firmante: nombre, imagen, resumen }; });
}

export function guardarFirmaTecnico(t, { imagen }) {
  if (!t.orden.con_evidencias) throw new ErrorTrabajo('Esta orden no lleva firma del técnico.');
  exigir(t, 'FIRMA_TECNICO');
  if (!hayFirma(t) || !firmaVigente(t)) throw new ErrorTrabajo('El cliente debe firmar antes que el técnico.');
  if (typeof imagen !== 'string' || !imagen.startsWith(PREFIJO_PNG)) throw new ErrorTrabajo('La firma no es válida. Vuelve a dibujarla.');
  const resumen = resumenParaFirma(t);
  return cambiar(t, (c) => { c.local.firma_tecnico = { imagen, resumen }; });
}

// ---------------------------------------------------------------- lo que falta (misma redacción que ordenes.validar_envio)
export function faltantes(t) {
  const v = vista(t);
  const problemas = [];
  for (const p of v.puntos) {
    if (!p.resultado) problemas.push(`Falta marcar: ${p.texto}`);
    else if (p.resultado === 'INCIDENCIA' && !p.gravedad) problemas.push(`Falta indicar la gravedad de: ${p.texto}`);
  }
  for (const m of v.mediciones) if (m.valor === null) problemas.push(`Falta medir: ${m.etiqueta}`);
  if (t.orden.con_evidencias) {
    const faltan = Math.max(0, t.limites.fotos_min - v.fotos);
    if (faltan) problemas.push(faltan === 1 ? 'Falta 1 fotografía' : `Faltan ${faltan} fotografías`);
    if (!hayFirma(t)) problemas.push('Falta la firma del cliente');
    else if (!firmaVigente(t)) problemas.push('El resumen cambió después de la firma: recoge la firma de nuevo');
    if (!hayFirmaTecnico(t)) problemas.push('Falta la firma del técnico');
    else if (!firmaTecnicoVigente(t)) problemas.push('El resumen cambió después de tu firma: firma de nuevo como técnico');
  }
  if (!v.observaciones.trim()) {
    if (!v.puntos.length) problemas.push('Las observaciones técnicas son obligatorias: OT sin checklist.');
    else if (v.puntos.some((p) => p.resultado === 'INCIDENCIA')) problemas.push('Las observaciones técnicas son obligatorias: hay incidencias en el checklist.');
  }
  if (!v.sin_materiales && !v.materiales.trim()) problemas.push('Materiales: marca SIN MATERIALES o registra al menos un material.');
  return problemas;
}

export { formatoNumero };

// ---------------------------------------------------------------- tras una sincronización correcta
// Lo enviado pasa a ser la base (lo que "ya sabe el servidor") y el trabajo local queda vacío.
export function consolidar(t, respuesta) {
  const c = structuredClone({ ...t, local: { ...t.local, fotos: undefined } });
  const l = t.local;
  const base = c.base;
  c.catalogo.mediciones = structuredClone(medicionesEfectivas(t));
  if (l.inicio) c.orden.inicio = l.inicio;
  c.orden.estado = respuesta.estado || c.orden.estado;
  const puntos = new Map((base.puntos || []).map((p) => [p.codigo, p]));
  for (const [codigo, p] of Object.entries(l.puntos || {})) puntos.set(codigo, { codigo, ...p });
  base.puntos = [...puntos.values()];
  const medidas = new Map((base.mediciones || []).map((m) => [m.codigo, m]));
  for (const [codigo, valor] of Object.entries(l.mediciones || {})) if (valor !== '') medidas.set(codigo, { codigo, valor });
  base.mediciones = [...medidas.values()];
  for (const campo of ['observaciones', 'materiales', 'sin_materiales']) if (l[campo] !== undefined) base[campo] = l[campo];
  base.fotos = (base.fotos || 0) + (l.fotos || []).filter((f) => !f.enviada).length;
  if (respuesta.firma_estado !== undefined) {
    base.firma = respuesta.firma_estado !== 'sin';
    base.firma_resumen = respuesta.firma_resumen || null;
  } else if (respuesta.firma === 'guardada' && l.firma) { base.firma = true; base.firma_resumen = l.firma.resumen; }
  if (respuesta.firma_tecnico_estado !== undefined) {
    base.firma_tecnico = respuesta.firma_tecnico_estado !== 'sin';
    base.firma_tecnico_resumen = respuesta.firma_tecnico_resumen || null;
  }
  c.local = {};
  return c;
}

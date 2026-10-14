// Debe producir EXACTAMENTE las líneas de core/evidencias.py::resumen_para_firma.
import { vista } from './vista.js';
export { formatoNumero } from './resumen_numero.js';

const capitalizar = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : '');

export function resumenParaFirma(t) {
  const v = vista(t);
  const lineas = [];
  for (const p of v.puntos) {
    let estado;
    if (p.resultado === 'OK') estado = 'OK';
    else if (p.resultado === 'INCIDENCIA') estado = `Incidencia ${capitalizar(p.gravedad)}` + (p.nota ? `. ${p.nota}` : '');
    else estado = 'sin marcar';
    lineas.push(`${p.texto}: ${estado}`);
  }
  for (const m of v.mediciones) {
    lineas.push(`${m.etiqueta}: ${m.valor !== null ? `${m.valor} ${m.unidad}` : 'sin medir'}`);
  }
  lineas.push(`Observaciones: ${v.observaciones.trim()}`);
  lineas.push(v.sin_materiales ? 'Materiales: ninguno' : `Materiales: ${v.materiales.trim()}`);
  lineas.push(`Fotografías: ${v.fotos}`);
  return lineas;
}

// Separa «etiqueta: valor» por el primer «: » (las etiquetas del catálogo no llevan dos puntos).
export function partirLinea(linea) {
  const i = linea.indexOf(': ');
  return i < 0 ? { etiqueta: linea, valor: '' } : { etiqueta: linea.slice(0, i), valor: linea.slice(i + 2) };
}

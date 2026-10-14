// Secciones de fotografías y firma de la pantalla de ejecución.
import { el } from './dom.js';
import * as T from './trabajo.js';
import { vista } from './vista.js';
import { resumenParaFirma, partirLinea } from './resumen.js';
import { reducirFoto } from './camara.js';
import { crearLienzo } from './firma.js';
import { uuid4 } from './paquete.js';

// Una línea «etiqueta: valor» del resumen como fila de tabla, con el valor a la derecha.
function filaResumen(linea) {
  const { etiqueta, valor } = partirLinea(linea);
  const tono = valor === 'OK' ? 'sc-v-ok' : valor.startsWith('Incidencia') ? 'sc-v-inc' : (valor === 'sin marcar' || valor === 'sin medir') ? 'sc-v-falta' : '';
  return el('li', { clase: 'sc-fila' }, el('span', { clase: 'sc-fila-etiqueta', texto: etiqueta }), el('span', { clase: `sc-fila-valor ${tono}`.trim(), texto: valor }));
}

export function seccionFotos({ actual, aplicar, motivoBloqueo, repintar, mensaje }) {
  const t0 = actual();
  const permitido = T.edicionPermitida(t0, 'FOTOS');
  const v = vista(t0);
  const { fotos_min: minimo, fotos_max: maximo } = t0.limites;
  const miniaturas = (t0.local.fotos || []).map((f) => {
    const url = URL.createObjectURL(f.blob);
    return el('li', { clase: 'sc-miniatura' },
      el('img', { src: url, alt: `Fotografía ${f.nombre}`, onload: () => URL.revokeObjectURL(url) }),
      f.enviada ? el('span', { clase: 'sc-suave', texto: 'Enviada' }) : el('button', { type: 'button', clase: 'sc-quitar', texto: 'Quitar',
        onclick: () => { if (aplicar((t) => T.quitarFoto(t, f.id))) repintar(); } }));
  });
  const entrada = el('input', { type: 'file', accept: 'image/*', capture: 'environment', multiple: true, hidden: true,
    onchange: async (e) => {
      const archivos = [...e.target.files];
      e.target.value = '';
      for (let i = 0; i < archivos.length; i++) {
        mensaje(`Preparando foto ${i + 1} de ${archivos.length}…`);
        try {
          const blob = await reducirFoto(archivos[i], { limite: actual().limites.foto_bytes });
          const id = uuid4();
          if (!aplicar((t) => T.agregarFoto(t, { id, blob, nombre: `foto-${id.slice(0, 8)}.jpg` }))) break;
        } catch (err) { mensaje(err.message, true); break; }
      }
      repintar();
    } });
  const lleno = v.fotos >= maximo;
  return el('section', { clase: 'sc-seccion' },
    el('h3', { texto: 'Fotografías' }), motivoBloqueo('FOTOS'),
    el('p', { texto: `${v.fotos} de ${minimo} mínimas (máximo ${maximo})${t0.base.fotos ? ` · ${t0.base.fotos} ya están en el servidor` : ''}` }),
    el('button', { type: 'button', clase: 'sc-boton', disabled: !permitido || lleno, texto: lleno ? 'Máximo de fotos alcanzado' : 'Tomar o elegir fotos',
      onclick: () => entrada.click() }),
    entrada, el('ul', { clase: 'sc-miniaturas' }, miniaturas));
}

export function seccionFirma({ actual, aplicar, motivoBloqueo, repintar, mensaje }) {
  const t0 = actual();
  const permitido = T.edicionPermitida(t0, 'FIRMA');
  const estado = el('p');
  const panel = el('div', { clase: 'sc-panel-firma', hidden: true });

  function pintarEstado() {
    const t = actual();
    const hay = Boolean(t.local.firma || t.base.firma);
    if (hay && T.firmaVigente(t)) { estado.textContent = '✓ Firma guardada en el teléfono'; estado.className = 'sc-ok'; }
    else if (hay) { estado.textContent = 'La firma ya no es válida: recógela de nuevo.'; estado.className = 'sc-error'; }
    else { estado.textContent = 'Todavía no hay firma.'; estado.className = 'sc-suave'; }
  }

  function abrir() {
    const t = actual();
    const nombre = el('input', { type: 'text', clase: 'sc-campo', autocomplete: 'off', 'aria-label': 'Firma del cliente: nombre de quien firma', placeholder: 'Firma del cliente: nombre de quien firma' });
    nombre.value = (t.local.firma && t.local.firma.firmante) || '';
    const zona = el('div');
    const error = el('p', { clase: 'sc-error', role: 'alert' });
    panel.replaceChildren(
      el('p', { clase: 'sc-titulo', texto: 'El cliente revisa este resumen y firma' }),
      el('ul', { clase: 'sc-resumen' }, resumenParaFirma(t).map(filaResumen)),
      nombre, zona, error,
      el('div', { clase: 'sc-botones' },
        el('button', { type: 'button', id: 'firma-limpiar', clase: 'sc-opcion', texto: 'Limpiar', onclick: () => lienzo.limpiar() }),
        el('button', { type: 'button', id: 'firma-guardar', clase: 'sc-opcion sc-ok-sel', texto: 'Guardar firma',
          onclick: () => {
            error.textContent = '';
            if (lienzo.estaVacio()) { error.textContent = 'Dibuja la firma antes de guardarla.'; return; }
            if (aplicar((x) => T.guardarFirma(x, { firmante: nombre.value, imagen: lienzo.aPng() }))) { panel.hidden = true; pintarEstado(); repintar(); }
            else { error.textContent = document.querySelector('.sc-guardado').textContent; mensaje(''); }
          } })));
    panel.hidden = false;
    const lienzo = crearLienzo(zona);
    panel.scrollIntoView({ block: 'nearest' });
  }

  pintarEstado();
  return el('section', { clase: 'sc-seccion' },
    el('h3', { texto: 'Firma del cliente' }), motivoBloqueo('FIRMA'), estado,
    el('button', { type: 'button', clase: 'sc-boton', disabled: !permitido, texto: 'Recoger firma', onclick: abrir }), panel);
}

// Firma del técnico: después de la del cliente, para revisar el resumen firmado antes de enviar la orden.
export function seccionFirmaTecnico({ actual, aplicar, motivoBloqueo, repintar, mensaje }) {
  const t0 = actual();
  if (!t0.orden.con_evidencias) return null;
  const estado = el('p');
  const panel = el('div', { clase: 'sc-panel-firma', hidden: true });

  function pintarEstado() {
    const t = actual();
    const hay = Boolean(t.local.firma_tecnico || t.base.firma_tecnico_resumen || t.base.firma_tecnico);
    if (hay && T.firmaTecnicoVigente(t)) { estado.textContent = '✓ Firma del técnico guardada en el teléfono'; estado.className = 'sc-ok'; }
    else if (hay) { estado.textContent = 'Tu firma ya no es válida: firma de nuevo.'; estado.className = 'sc-error'; }
    else { estado.textContent = 'Todavía no hay firma del técnico.'; estado.className = 'sc-suave'; }
  }

  const listo = () => { const t = actual(); return Boolean(t.local.firma || t.base.firma_resumen) && T.firmaVigente(t); };

  function abrir() {
    const t = actual();
    const zona = el('div');
    const error = el('p', { clase: 'sc-error', role: 'alert' });
    panel.replaceChildren(
      el('p', { clase: 'sc-titulo', texto: 'Revisa el resumen y firma como técnico' }),
      el('ul', { clase: 'sc-resumen' }, resumenParaFirma(t).map(filaResumen)),
      zona, error,
      el('div', { clase: 'sc-botones' },
        el('button', { type: 'button', id: 'tec-firma-limpiar', clase: 'sc-opcion', texto: 'Limpiar', onclick: () => lienzo.limpiar() }),
        el('button', { type: 'button', id: 'tec-firma-guardar', clase: 'sc-opcion sc-ok-sel', texto: 'Guardar firma del técnico',
          onclick: () => {
            error.textContent = '';
            if (lienzo.estaVacio()) { error.textContent = 'Dibuja la firma antes de guardarla.'; return; }
            if (aplicar((x) => T.guardarFirmaTecnico(x, { imagen: lienzo.aPng() }))) { panel.hidden = true; pintarEstado(); repintar(); }
            else { error.textContent = document.querySelector('.sc-guardado').textContent; mensaje(''); }
          } })));
    panel.hidden = false;
    const lienzo = crearLienzo(zona);
    panel.scrollIntoView({ block: 'nearest' });
  }

  pintarEstado();
  return el('section', { clase: 'sc-seccion' },
    el('h3', { texto: 'Firma del técnico' }), motivoBloqueo('FIRMA_TECNICO'), estado,
    listo() ? null : el('p', { clase: 'sc-suave', texto: 'Primero firma el cliente; después firmas tú.' }),
    el('button', { type: 'button', clase: 'sc-boton', disabled: !listo(), texto: 'Firmar como técnico', onclick: abrir }), panel);
}

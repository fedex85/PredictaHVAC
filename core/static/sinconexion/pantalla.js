// Pantalla de ejecución de una orden descargada. Cada cambio se aplica con funciones puras de trabajo.js,
// se escribe en el almacén y solo entonces se muestra «Guardado en el teléfono».
import { el } from './dom.js';
import * as T from './trabajo.js';
import { vista, medicionesEfectivas } from './vista.js';
import { encolar, sincronizando, sincronizarOrden } from './sync.js';
import { leerCookie } from './util.js';
import { descargarOrden } from './descarga.js';

const BLOQUES = { INSPECCION: 'Inspección', FUNCIONAMIENTO: 'Funcionamiento', REFRIGERANTE: 'Refrigerante' };
const GRAVEDADES = [['LEVE', 'Leve'], ['MEDIA', 'Media'], ['ALTA', 'Alta']];

let quitarEscucha = null;

export function abrirPantalla(raiz, { almacen, id, usuarioId, ahora = () => new Date(), extras = [] }) {
  let actual = null;
  const borradores = new Map(); // incidencias a la espera de gravedad
  const estado = el('p', { clase: 'sc-guardado', role: 'status', 'aria-live': 'polite' });
  const faltan = el('ul', { clase: 'sc-faltan' });
  const cabecera = el('div', { clase: 'sc-cabecera-orden' });
  const cuerpo = el('div');

  function mensaje(texto, error = false) {
    estado.textContent = texto;
    estado.className = 'sc-guardado' + (error ? ' sc-error' : '');
  }

  // Aplica el cambio en memoria al instante y encadena la escritura; devuelve true si se aceptó.
  function aplicar(cambio) {
    if (sincronizando(id)) { mensaje('Sincronizando… espera un momento y vuelve a intentarlo.', true); return false; }
    let siguiente;
    try { siguiente = cambio(actual); } catch (e) {
      if (e instanceof T.ErrorTrabajo) { mensaje(e.message, true); return false; }
      throw e;
    }
    actual = siguiente;
    const copia = actual;
    mensaje('Guardando…');
    encolar(() => almacen.guardar(copia))
      .then(() => { if (actual === copia) mensaje('Guardado en el teléfono'); })
      .catch(() => mensaje('No se pudo guardar en el teléfono. No cierres esta pantalla y avisa a gestión.', true));
    pintarResumenEstado();
    return true;
  }

  function pintarResumenEstado() {
    cabecera.replaceChildren(
      el('h2', { texto: actual.orden.codigo }),
      el('p', { texto: `${actual.equipo.codigo} · ${actual.equipo.nombre}` }),
      el('p', { clase: 'sc-suave', texto: actual.equipo.ubicacion || 'Sin ubicación' }),
      el('p', { clase: 'sc-suave', texto: actual.orden.descripcion || '' }),
      el('p', { clase: 'sc-estado', texto: T.estadoLegible(actual) }),
    );
    faltan.replaceChildren();
    if (!T.iniciada(actual)) return;
    const pendientes = T.faltantes(actual);
    if (!pendientes.length) {
      faltan.append(el('li', { clase: 'sc-ok', texto: 'Todo listo. Cuando haya señal se sincroniza y podrás enviarla a aprobación desde la orden.' }));
    } else {
      faltan.append(el('li', { clase: 'sc-titulo', texto: 'Falta para poder enviar' }), ...pendientes.map((p) => el('li', { texto: p })));
    }
  }

  function motivoBloqueo(bloque) {
    if (T.edicionPermitida(actual, bloque)) return null;
    const etiquetas = { CHECKLIST: 'Checklist', MEDICIONES: 'Mediciones', OBSERVACIONES: 'Observaciones', MATERIALES: 'Materiales', FOTOS: 'Fotos', FIRMA: 'Firma' };
    return el('p', { clase: 'sc-bloqueo', texto: `Bloqueado: esta subsanación solo permite editar ${etiquetas[actual.orden.subsanacion_bloque] || 'otro bloque'}.` });
  }

  // ------------------------------------------------------------ checklist
  function filaPunto(p) {
    const fila = el('li', { clase: 'sc-punto' });
    const permitido = T.edicionPermitida(actual, 'CHECKLIST');
    function pintar() {
      const v = vista(actual).puntos.find((x) => x.codigo === p.codigo);
      const borrador = borradores.get(p.codigo);
      const enIncidencia = v.resultado === 'INCIDENCIA' || Boolean(borrador);
      const gravedad = borrador !== undefined ? borrador : v.gravedad;
      fila.replaceChildren(...[
        el('p', { clase: 'sc-texto-punto', texto: p.texto }),
        el('div', { clase: 'sc-botones' },
          el('button', { type: 'button', clase: 'sc-opcion' + (v.resultado === 'OK' ? ' sc-ok-sel' : ''), disabled: !permitido,
            'aria-pressed': String(v.resultado === 'OK'), texto: 'OK',
            onclick: () => { borradores.delete(p.codigo); aplicar((t) => T.marcarPunto(t, p.codigo, { resultado: 'OK' })); pintar(); } }),
          el('button', { type: 'button', clase: 'sc-opcion' + (enIncidencia ? ' sc-inc-sel' : ''), disabled: !permitido,
            'aria-pressed': String(enIncidencia), texto: 'Incidencia',
            onclick: () => { if (v.resultado !== 'INCIDENCIA') borradores.set(p.codigo, ''); pintar(); } })),
        enIncidencia ? el('div', { clase: 'sc-incidencia' },
          el('p', { clase: 'sc-suave', texto: gravedad ? 'Gravedad' : 'Elige la gravedad' }),
          el('div', { clase: 'sc-botones' }, GRAVEDADES.map(([codigo, texto]) =>
            el('button', { type: 'button', clase: 'sc-opcion' + (gravedad === codigo ? ' sc-inc-sel' : ''), disabled: !permitido,
              'aria-pressed': String(gravedad === codigo), texto,
              onclick: () => {
                const notaActual = vista(actual).puntos.find((x) => x.codigo === p.codigo).nota;
                const ok = aplicar((t) => T.marcarPunto(t, p.codigo, { resultado: 'INCIDENCIA', gravedad: codigo, nota: notaActual }));
                if (ok) borradores.delete(p.codigo);
                pintar();
              } }))),
          el('textarea', { clase: 'sc-campo', rows: '2', maxlength: '255', placeholder: 'Nota (opcional)', 'aria-label': `Nota: ${p.texto}`,
            disabled: !permitido || !gravedad, value: null,
            onchange: (e) => aplicar((t) => T.marcarPunto(t, p.codigo, { resultado: 'INCIDENCIA', gravedad, nota: e.target.value })) })) : null,
      ].filter(Boolean));
      const nota = fila.querySelector('textarea');
      if (nota) nota.value = v.nota;
    }
    pintar();
    return fila;
  }

  function seccionChecklist() {
    const puntos = actual.catalogo.puntos;
    if (!puntos.length) return null;
    const bloques = [...new Set(puntos.map((p) => p.bloque))];
    return el('section', { clase: 'sc-seccion' },
      el('h3', { texto: 'Checklist' }), motivoBloqueo('CHECKLIST'),
      bloques.map((b) => el('div', {}, el('h4', { texto: BLOQUES[b] || b }),
        el('ul', { clase: 'sc-lista' }, puntos.filter((p) => p.bloque === b).map(filaPunto)))));
  }

  // ------------------------------------------------------------ mediciones
  function campoMedicion(m) {
    const permitido = T.edicionPermitida(actual, 'MEDICIONES');
    const error = el('p', { clase: 'sc-error', role: 'alert' });
    const rango = m.minimo != null ? ` (entre ${m.minimo} y ${m.maximo})` : '';
    const entrada = el('input', { type: 'text', inputmode: 'decimal', clase: 'sc-campo', autocomplete: 'off', disabled: !permitido,
      'aria-label': `${m.etiqueta} en ${m.unidad}`,
      onchange: (e) => {
        error.textContent = '';
        const ok = aplicar((t) => T.registrarMedicion(t, m.codigo, e.target.value));
        if (!ok) { error.textContent = estado.textContent; mensaje(''); }
      } });
    entrada.value = (vista(actual).mediciones.find((x) => x.codigo === m.codigo) || {}).valor ?? '';
    return el('li', { clase: 'sc-medicion' }, el('label', {}, el('span', { texto: `${m.etiqueta} (${m.unidad})${rango}` }), entrada), error);
  }

  function seccionMediciones() {
    const elegibles = actual.catalogo.mediciones_elegibles || [];
    const efectivas = medicionesEfectivas(actual);
    if (!efectivas.length && !elegibles.length) return null;
    const permitido = T.edicionPermitida(actual, 'MEDICIONES');
    const eleccion = elegibles.length ? el('div', { clase: 'sc-eleccion' }, el('p', { clase: 'sc-suave', texto: 'Elige qué mediciones vas a hacer' }),
      elegibles.map((m) => {
        const marcada = efectivas.some((x) => x.codigo === m.codigo);
        return el('label', { clase: 'sc-marca' },
          el('input', { type: 'checkbox', checked: marcada, disabled: !permitido,
            onchange: (e) => {
              const actuales = medicionesEfectivas(actual).map((x) => x.codigo).filter((c) => c !== m.codigo);
              const ok = aplicar((t) => T.elegirMediciones(t, e.target.checked ? [...actuales, m.codigo] : actuales));
              if (ok) repintarCuerpo(); else e.target.checked = !e.target.checked;
            } }),
          el('span', { texto: `${m.etiqueta} (${m.unidad})` }));
      })) : null;
    return el('section', { clase: 'sc-seccion' }, el('h3', { texto: 'Mediciones' }), motivoBloqueo('MEDICIONES'), eleccion,
      el('ul', { clase: 'sc-lista' }, efectivas.map(campoMedicion)));
  }

  // ------------------------------------------------------------ textos
  function seccionTextos() {
    const v = vista(actual);
    const obs = el('textarea', { clase: 'sc-campo', rows: '4', 'aria-label': 'Observaciones técnicas', disabled: !T.edicionPermitida(actual, 'OBSERVACIONES'),
      onchange: (e) => aplicar((t) => T.fijarTextos(t, { observaciones: e.target.value })) });
    obs.value = v.observaciones;
    const permitidoMat = T.edicionPermitida(actual, 'MATERIALES');
    const mat = el('textarea', { clase: 'sc-campo', rows: '3', 'aria-label': 'Materiales utilizados', disabled: !permitidoMat || v.sin_materiales,
      onchange: (e) => aplicar((t) => T.fijarTextos(t, { materiales: e.target.value })) });
    mat.value = v.materiales;
    const sin = el('input', { type: 'checkbox', checked: v.sin_materiales, disabled: !permitidoMat,
      onchange: (e) => {
        const ok = aplicar((t) => T.fijarTextos(t, { sin_materiales: e.target.checked }));
        if (!ok) { e.target.checked = !e.target.checked; return; }
        mat.disabled = e.target.checked;
        if (e.target.checked) mat.value = '';
      } });
    return el('section', { clase: 'sc-seccion' },
      el('h3', { texto: 'Observaciones' }), motivoBloqueo('OBSERVACIONES'), obs,
      el('h3', { texto: 'Materiales' }), motivoBloqueo('MATERIALES'),
      el('label', { clase: 'sc-marca' }, sin, el('span', { texto: 'Sin materiales' })), mat);
  }


  // ------------------------------------------------------------ sincronización
  function seccionSync() {
    const s = actual.sync || {};
    const hayPendiente = T.tieneTrabajoLocal(actual);
    const aviso = el('p');
    if (s.estado === 'error' || s.estado === 'sin_sesion') { aviso.className = 'sc-error'; aviso.textContent = s.mensaje || 'No se pudo sincronizar.'; }
    else if (hayPendiente) { aviso.className = 'sc-suave'; aviso.textContent = 'Tienes cambios guardados en el teléfono que aún no se han enviado.'; }
    else if (s.estado === 'sincronizada') { aviso.className = 'sc-ok'; aviso.textContent = 'Sincronizada con el servidor.'; }
    else { aviso.className = 'sc-suave'; aviso.textContent = 'Todavía no has hecho cambios que enviar.'; }
    const boton = el('button', { type: 'button', clase: 'sc-boton', disabled: !hayPendiente, texto: 'Sincronizar ahora',
      onclick: async () => {
        boton.disabled = true;
        mensaje('Sincronizando…');
        const r = await sincronizarOrden(id, { almacen, fetch: window.fetch.bind(window), csrf: leerCookie('csrftoken', document.cookie) });
        mensaje(r.mensaje, r.estado === 'error');
      } });
    const avisos = (s.avisos || []).map((a) => el('li', { clase: 'sc-error', texto: a }));
    const reprep = s.estado === 'error' ? el('button', { type: 'button', clase: 'sc-opcion', texto: 'Actualizar descarga desde el servidor',
      onclick: async () => {
        const r = await descargarOrden(id, { almacen, fetch: window.fetch.bind(window), csrf: leerCookie('csrftoken', document.cookie), usuarioId });
        mensaje(r.mensaje, !r.ok);
        recargar();
      } }) : null;
    const enviar = !hayPendiente && s.estado === 'sincronizada'
      ? el('a', { clase: 'sc-enlace', href: `/ordenes/${id}/`, texto: 'Abrir la orden (con señal) para enviarla a aprobación' }) : null;
    return el('section', { clase: 'sc-seccion' }, el('h3', { texto: 'Sincronización' }), aviso, boton, reprep, el('ul', { clase: 'sc-lista' }, avisos), enviar,
      el('p', { clase: 'sc-suave', texto: 'Se envía sola cuando vuelve la señal. El envío a aprobación se hace con conexión desde la orden.' }));
  }

  // ------------------------------------------------------------ cuerpo
  function repintarCuerpo() {
    const y = window.scrollY;
    if (!T.iniciada(actual)) {
      const aviso = el('p', { clase: 'sc-error', role: 'alert' });
      const sel = el('select', { id: 'sc-llegada', clase: 'sc-campo' },
        el('option', { value: '', texto: 'Selecciona…' }), ...T.LLEGADAS.map(([c, n]) => el('option', { value: c, texto: n })));
      const verCodigo = el('input', { id: 'sc-ver-codigo', type: 'text', maxlength: '300', clase: 'sc-campo', placeholder: `Código del equipo (${actual.equipo.codigo}) o contenido de su QR` });
      const verContinuar = el('input', { id: 'sc-ver-continuar', type: 'checkbox' });
      const verNota = el('input', { id: 'sc-ver-nota', type: 'text', maxlength: '200', clase: 'sc-campo', placeholder: 'Observación si el equipo no coincide' });
      const otro = el('input', { id: 'sc-llegada-texto', type: 'text', maxlength: '255', clase: 'sc-campo', placeholder: 'Describe el estado (si es «Otro»)' });
      cuerpo.replaceChildren(
        el('p', { texto: 'Cuando empieces la intervención, indica cómo encuentras el equipo y pulsa «Iniciar». Se guarda la hora del teléfono.' }),
        el('label', { for: 'sc-ver-codigo', texto: 'Identifica el equipo *' }), verCodigo,
        el('label', { for: 'sc-ver-continuar' }, verContinuar, ' Continuar y reportar incidencia (el equipo no coincide)'), verNota,
        el('label', { for: 'sc-llegada', texto: 'Estado de llegada *' }), sel, otro, aviso,
        el('button', { type: 'button', clase: 'sc-boton', texto: 'Iniciar intervención',
          onclick: () => {
            if (aplicar((t) => T.iniciar(t, ahora(), { estado: sel.value, texto: otro.value }, { codigo: verCodigo.value, continuar: verContinuar.checked, nota: verNota.value }))) repintarCuerpo();
            else { aviso.textContent = estado.textContent; mensaje(''); }
          } }));
    } else {
      cuerpo.replaceChildren(...[seccionChecklist(), seccionMediciones(), seccionTextos(), ...extras.filter((f) => actual.orden.con_evidencias).map((f) => f({ actual: () => actual, aplicar, motivoBloqueo, repintar: repintarCuerpo, mensaje })), seccionSync()].filter(Boolean));
    }
    pintarResumenEstado();
    window.scrollTo(0, y);
  }

  function recargar() {
    encolar(() => almacen.obtener(id)).then((t) => {
      if (!t) return;
      actual = t;
      const a = document.activeElement;
      // No se recrean los campos mientras se escribe en uno: se perdería el texto.
      if (a && cuerpo.contains(a) && /^(INPUT|TEXTAREA)$/.test(a.tagName)) pintarResumenEstado(); else repintarCuerpo();
    });
  }
  if (quitarEscucha) quitarEscucha();
  const alTerminar = (e) => { if (e.detail && e.detail.id !== id) return; if (document.body.contains(cuerpo)) recargar(); };
  window.addEventListener('sc-sync-fin', alTerminar);
  quitarEscucha = () => window.removeEventListener('sc-sync-fin', alTerminar);

  almacen.obtener(id).then((t) => {
    if (!t || t.usuario_id !== usuarioId) {
      raiz.replaceChildren(el('p', { clase: 'sc-vacio', texto: 'Esta orden no está descargada en este teléfono.' }), el('a', { clase: 'sc-volver', href: '#/', texto: '← Mis órdenes descargadas' }));
      return;
    }
    actual = t;
    raiz.replaceChildren(el('a', { clase: 'sc-volver', href: '#/', texto: '← Mis órdenes descargadas' }), cabecera, estado, cuerpo, faltan);
    repintarCuerpo();
  }).catch(() => raiz.replaceChildren(el('p', { clase: 'sc-error', texto: 'No se pudo abrir la orden en este teléfono.' })));
}

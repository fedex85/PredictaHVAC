// Pantalla del asistente IA. El texto del usuario siempre entra con textContent; la respuesta de la IA pasa por
// renderizar(), que escapa todo el HTML. Nada se guarda en el servidor: la conversación se conserva en el navegador
// del usuario (conversacion.js) hasta que pulsa «Nueva conversación».
import { renderizar } from './markdown.js';
import * as conversacion from './conversacion.js';

const caja = document.getElementById('chat-box');
const formulario = document.getElementById('chat-form');
const entrada = document.getElementById('user-input');
const boton = document.getElementById('btn-enviar');
const vacio = document.getElementById('chat-vacio');
const nueva = document.getElementById('btn-nueva');
const MAX_TURNOS = Number(formulario.dataset.maxTurnos) || 6;
const USUARIO = formulario.dataset.usuario;
const almacen = (() => { try { return window.localStorage; } catch (e) { return null; } })();

let historial = almacen ? conversacion.cargar(almacen, USUARIO) : [];
let ocupado = false;

function burbuja(clase, avatar, claseAvatar) {
  const fila = document.createElement('div');
  fila.className = 'flex items-start gap-3 ' + (clase === 'usuario' ? 'justify-end' : '');
  const av = document.createElement('div');
  av.className = 'w-8 h-8 rounded-lg flex items-center justify-center shrink-0 font-bold text-xs text-white ' + claseAvatar;
  av.textContent = avatar;
  const cuerpo = document.createElement('div');
  cuerpo.className = 'max-w-[85%] md:max-w-xl p-4 rounded-2xl text-sm break-words space-y-2 ' + {
    usuario: 'burbuja-usuario rounded-tr-none',
    ia: 'burbuja-ia bg-slate-900 border border-slate-800 text-slate-200 rounded-tl-none',
    error: 'bg-red-500/10 border border-red-500/30 text-red-300 rounded-tl-none',
  }[clase];
  if (clase === 'usuario') fila.append(cuerpo, av); else fila.append(av, cuerpo);
  caja.append(fila);
  return { fila, cuerpo };
}

// La página (no el cuadro) es la que hace scroll: se baja hasta el final, donde la barra de preguntas queda
// debajo del último mensaje y no lo tapa.
function bajar() {
  window.scrollTo({ top: document.documentElement.scrollHeight });
}

function mostrarUsuario(texto) {
  const { cuerpo } = burbuja('usuario', 'T', 'bg-slate-700');
  cuerpo.textContent = texto;
  cuerpo.classList.add('whitespace-pre-wrap');
}

function mostrarIA(texto) {
  const { cuerpo } = burbuja('ia', 'IA', 'bg-cyan-600');
  cuerpo.innerHTML = renderizar(texto);   // seguro: renderizar() escapa antes de añadir etiquetas
}

function mostrarError(texto) {
  const { cuerpo } = burbuja('error', '!', 'bg-red-600');
  cuerpo.textContent = texto;
}

function pensando() {
  const { fila, cuerpo } = burbuja('ia', 'IA', 'bg-cyan-600');
  cuerpo.textContent = 'Escribiendo respuesta…';
  cuerpo.classList.add('animate-pulse', 'text-slate-400');
  return fila;
}

function bloquear(valor) {
  ocupado = valor;
  boton.disabled = valor;
  boton.classList.toggle('opacity-50', valor);
}

async function enviar(mensaje) {
  if (!navigator.onLine) {
    mostrarError('Sin conexión: el asistente necesita internet. Vuelve a intentarlo cuando tengas señal.');
    return;
  }
  vacio.classList.add('hidden');
  mostrarUsuario(mensaje);
  bajar();
  const espera = pensando();
  bloquear(true);
  try {
    const cuerpo = new URLSearchParams({
      mensaje,
      historial: JSON.stringify(historial.slice(-MAX_TURNOS * 2)),
    });
    const r = await fetch(formulario.dataset.url, {
      method: 'POST',
      headers: { 'X-CSRFToken': formulario.querySelector('[name=csrfmiddlewaretoken]').value },
      body: cuerpo,
    });
    let datos = {};
    try { datos = await r.json(); } catch (e) { /* respuesta que no es JSON */ }
    espera.remove();
    if (r.ok && datos.respuesta) {
      mostrarIA(datos.respuesta);
      historial.push({ role: 'user', content: mensaje }, { role: 'assistant', content: datos.respuesta });
      if (almacen) conversacion.guardar(almacen, USUARIO, historial);
    } else {
      mostrarError(datos.error || 'No se pudo obtener respuesta. Inténtalo de nuevo.');
    }
  } catch (e) {
    espera.remove();
    mostrarError('No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.');
  } finally {
    bloquear(false);
    bajar();
    entrada.focus();
  }
}

formulario.addEventListener('submit', (e) => {
  e.preventDefault();
  const mensaje = entrada.value.trim();
  if (!mensaje || ocupado) return;
  entrada.value = '';
  enviar(mensaje);
});

// Las sugerencias del estado vacío rellenan la barra sin enviar nada.
vacio.addEventListener('click', (e) => {
  const chip = e.target.closest('.chip-sug');
  if (!chip) return;
  entrada.value = chip.dataset.texto || chip.textContent;
  entrada.focus();
});

nueva.addEventListener('click', () => {
  historial = [];
  if (almacen) conversacion.borrar(almacen, USUARIO);
  for (const nodo of [...caja.children]) if (nodo !== vacio) nodo.remove();
  vacio.classList.remove('hidden');
  entrada.focus();
});

// Al abrir la pantalla se vuelve a mostrar la conversación guardada.
if (historial.length) {
  vacio.classList.add('hidden');
  for (const m of historial) {
    if (m.role === 'user') mostrarUsuario(m.content); else mostrarIA(m.content);
  }
  bajar();
}

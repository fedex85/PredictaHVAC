// Convierte el texto de la IA en HTML seguro: primero se escapa TODO y luego se añaden solo etiquetas fijas.
// No genera enlaces ni imágenes, así que no hay forma de colar atributos ni scripts.

export function escapar(texto) {
  return String(texto).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function enLinea(t) {
  return t
    .replace(/`([^`]+)`/g, '<code class="px-1 rounded bg-slate-800 text-cyan-300">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold text-white">$1</strong>');
}

export function renderizar(texto) {
  const lineas = escapar(texto).replace(/\r\n?/g, '\n').split('\n');
  let html = '';
  let lista = null;
  const cerrar = () => { if (lista) { html += `</${lista}>`; lista = null; } };
  const abrir = (tipo) => {
    if (lista === tipo) return;
    cerrar();
    html += tipo === 'ul' ? '<ul class="list-disc pl-5 space-y-1">' : '<ol class="list-decimal pl-5 space-y-1">';
    lista = tipo;
  };
  for (const linea of lineas) {
    const t = linea.trim();
    let m;
    if (!t) { cerrar(); continue; }
    if ((m = t.match(/^[-*•]\s+(.*)$/))) { abrir('ul'); html += `<li>${enLinea(m[1])}</li>`; }
    else if ((m = t.match(/^\d+[.)]\s+(.*)$/))) { abrir('ol'); html += `<li>${enLinea(m[1])}</li>`; }
    else if ((m = t.match(/^#{1,4}\s+(.*)$/))) { cerrar(); html += `<p class="font-semibold text-white">${enLinea(m[1])}</p>`; }
    else { cerrar(); html += `<p>${enLinea(t)}</p>`; }
  }
  cerrar();
  return html;
}

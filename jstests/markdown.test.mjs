import test from 'node:test';
import assert from 'node:assert/strict';
import { escapar, renderizar } from '../core/static/asistente/markdown.js';

test('escapa HTML antes de dar formato', () => {
  const h = renderizar('<img src=x onerror=alert(1)> y <script>x</script>');
  assert.ok(!h.includes('<img') && !h.includes('<script'));
  assert.ok(h.includes('&lt;img'));
});

test('las comillas y atributos no pueden salir del texto', () => {
  assert.equal(escapar('"a" \'b\' & <c>'), '&quot;a&quot; &#39;b&#39; &amp; &lt;c&gt;');
});

test('negritas, código y listas', () => {
  const h = renderizar('**Causa:** fuga\n- uno\n- dos con `R410A`\n1. paso\n2. otro');
  assert.match(h, /<strong[^>]*>Causa:<\/strong> fuga/);
  assert.equal((h.match(/<li>/g) || []).length, 4);
  assert.match(h, /<ul[^>]*>.*<\/ul>/);
  assert.match(h, /<ol[^>]*>.*<\/ol>/);
  assert.match(h, /<code[^>]*>R410A<\/code>/);
});

test('encabezados y párrafos; líneas vacías cierran listas', () => {
  const h = renderizar('## Título\ntexto\n\n- a\n\nfin');
  assert.match(h, /<p class="font-semibold text-white">Título<\/p>/);
  assert.match(h, /<\/ul><p>fin<\/p>$/);
});

test('un enlace en markdown queda como texto, sin etiqueta a', () => {
  const h = renderizar('[x](javascript:alert(1))');
  assert.ok(!h.includes('<a '));
});

test('texto vacío no produce HTML', () => {
  assert.equal(renderizar(''), '');
});

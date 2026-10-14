// Comportamientos pequeños que antes eran atributos onclick/onchange en las plantillas.
// La política CSP no permite manejadores en línea, así que se activan con atributos data-*:
//   data-imprimir       -> abre el diálogo de impresión al pulsar
//   data-autoenviar     -> envía el formulario al cambiar el valor (selectores de filtro)
//   data-seleccionar    -> selecciona todo el texto al pulsar (enlaces/claves para copiar)
document.addEventListener('click', function (e) {
  var t = e.target.closest('[data-imprimir]');
  if (t) { window.print(); return; }
  t = e.target.closest('[data-seleccionar]');
  if (t) {
    if (typeof t.select === 'function') { t.select(); return; }
    var rango = document.createRange();
    rango.selectNodeContents(t);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(rango);
  }
});
document.addEventListener('change', function (e) {
  var t = e.target.closest('[data-autoenviar]');
  if (t && t.form) { t.form.submit(); }
});

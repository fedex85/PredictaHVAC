// Lienzo de firma táctil. La parte sin DOM (registro de trazos) se prueba con Node.
export function registroTrazos() {
  let trazos = [];
  let actual = null;
  return {
    iniciar(x, y) { actual = [[x, y]]; trazos.push(actual); },
    mover(x, y) { if (actual) actual.push([x, y]); },
    terminar() { actual = null; },
    limpiar() { trazos = []; actual = null; },
    // Un simple toque (un solo punto) no cuenta como firma.
    vacio() { return !trazos.some((t) => t.length >= 2); },
    trazos() { return trazos; },
  };
}

export function crearLienzo(contenedor) {
  const lienzo = document.createElement('canvas');
  lienzo.className = 'sc-lienzo';
  lienzo.setAttribute('aria-label', 'Zona para firmar con el dedo');
  contenedor.append(lienzo);
  const ctx = lienzo.getContext('2d');
  const registro = registroTrazos();

  function ajustar() {
    const ancho = Math.max(200, Math.round(lienzo.clientWidth || 300));
    lienzo.width = ancho;
    lienzo.height = Math.round(ancho * 0.45);
    ctx.lineWidth = 3;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = '#000';
  }
  function punto(e) {
    const r = lienzo.getBoundingClientRect();
    return [(e.clientX - r.left) * (lienzo.width / r.width), (e.clientY - r.top) * (lienzo.height / r.height)];
  }
  lienzo.addEventListener('pointerdown', (e) => {
    lienzo.setPointerCapture(e.pointerId);
    const [x, y] = punto(e);
    registro.iniciar(x, y);
    ctx.beginPath();
    ctx.moveTo(x, y);
    e.preventDefault();
  });
  lienzo.addEventListener('pointermove', (e) => {
    if (!(e.buttons || e.pressure)) return;
    const [x, y] = punto(e);
    registro.mover(x, y);
    ctx.lineTo(x, y);
    ctx.stroke();
    e.preventDefault();
  });
  const fin = () => registro.terminar();
  lienzo.addEventListener('pointerup', fin);
  lienzo.addEventListener('pointercancel', fin);
  ajustar();

  return {
    limpiar() { registro.limpiar(); ctx.clearRect(0, 0, lienzo.width, lienzo.height); },
    estaVacio: () => registro.vacio(),
    // PNG transparente con trazo negro, ancho máximo 600 px.
    aPng() {
      if (lienzo.width <= 600) return lienzo.toDataURL('image/png');
      const f = 600 / lienzo.width;
      const copia = document.createElement('canvas');
      copia.width = 600;
      copia.height = Math.round(lienzo.height * f);
      copia.getContext('2d').drawImage(lienzo, 0, 0, copia.width, copia.height);
      return copia.toDataURL('image/png');
    },
  };
}

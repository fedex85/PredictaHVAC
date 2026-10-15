// Service Worker de PredictaHVAC: deja disponible la pantalla sin conexión.
// Estrategia: red primero y caché de respaldo, solo para estas rutas. No toca POST ni /media/.
const CACHE = 'sinconexion-v11';
const PANTALLA = '/sin-conexion/';
const ARCHIVOS_PRECARGA = [
  '/sin-conexion/',
  '/manifest.webmanifest',
  '/static/sinconexion/sinconexion.css',
  '/static/css/predicta.css',
  '/static/css/tema.css',
  '/static/img/icono-app.png',
  '/static/sinconexion/app.js',
  '/static/sinconexion/almacen.js',
  '/static/sinconexion/trabajo.js',
  '/static/sinconexion/descarga.js',
  '/static/sinconexion/util.js',
  '/static/sinconexion/vista.js',
  '/static/sinconexion/resumen.js',
  '/static/sinconexion/resumen_numero.js',
  '/static/sinconexion/paquete.js',
  '/static/sinconexion/dom.js',
  '/static/sinconexion/sync.js',
  '/static/sinconexion/sesion.js',
  '/static/sinconexion/camara.js',
  '/static/sinconexion/firma.js',
  '/static/sinconexion/evidencias_ui.js',
  '/static/sinconexion/pantalla.js',
  '/static/sinconexion/arranque.js',
  '/static/sinconexion/iconos/icono-192.png',
  '/static/sinconexion/iconos/icono-512.png',
  '/static/sinconexion/iconos/icono-maskable-512.png',
];

async function guardar(cache, url, respuesta) {
  // Nunca se guardan redirecciones (p. ej. a la pantalla de acceso) ni errores.
  if (respuesta && respuesta.ok && !respuesta.redirected && respuesta.type !== 'opaqueredirect') {
    await cache.put(url, respuesta.clone());
  }
}

self.addEventListener('install', (evento) => {
  evento.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    const fallos = [];
    for (const url of ARCHIVOS_PRECARGA) {
      try {
        const r = await fetch(url, { credentials: 'same-origin', cache: 'reload' });
        if (!r.ok || r.redirected) throw new Error(url);
        await guardar(cache, url, r);
      } catch (e) { fallos.push(url); }
    }
    // Si algo falta la instalación falla y el navegador la reintenta en la siguiente página con señal.
    if (fallos.length) throw new Error('Precarga incompleta: ' + fallos.join(', '));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (evento) => {
  evento.waitUntil((async () => {
    for (const nombre of await caches.keys()) {
      if (nombre !== CACHE) await caches.delete(nombre);
    }
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (evento) => {
  const peticion = evento.request;
  if (peticion.method !== 'GET') return;
  const url = new URL(peticion.url);
  if (url.origin !== self.location.origin) return;
  const ruta = url.pathname;
  const precargada = ARCHIVOS_PRECARGA.includes(ruta);

  if (precargada) {
    evento.respondWith((async () => {
      const cache = await caches.open(CACHE);
      try {
        // 'no-cache' obliga a revalidar con el servidor: así una versión nueva nunca queda tapada por la caché HTTP del navegador.
        const r = await fetch(new Request(peticion, { cache: 'no-cache' }));
        await guardar(cache, ruta, r);
        return r;
      } catch (e) {
        const guardada = await cache.match(ruta);
        if (guardada) return guardada;
        throw e;
      }
    })());
    return;
  }

  if (peticion.mode === 'navigate') {
    evento.respondWith((async () => {
      try {
        return await fetch(peticion);
      } catch (e) {
        const cache = await caches.open(CACHE);
        return (await cache.match(PANTALLA)) || Response.error();
      }
    })());
  }
});

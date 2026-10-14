/** Tailwind 3 (misma generación que el CDN que se reemplaza). Escanea plantillas, JS del modo sin conexión y Python. */
module.exports = {
  content: [
    './templates/**/*.html',
    './core/templates/**/*.html',
    './core/static/sinconexion/**/*.js',
    './core/static/asistente/**/*.js',
    './core/**/*.py',
  ],
  theme: { extend: {} },
  plugins: [],
};

// Utilidades sin DOM. Se prueban con Node.

export function leerCookie(nombre, cookies) {
  const partes = String(cookies || '').split(';');
  for (const parte of partes) {
    const i = parte.indexOf('=');
    if (i < 0) continue;
    if (parte.slice(0, i).trim() === nombre) {
      try { return decodeURIComponent(parte.slice(i + 1).trim()); } catch (e) { return parte.slice(i + 1).trim(); }
    }
  }
  return null;
}

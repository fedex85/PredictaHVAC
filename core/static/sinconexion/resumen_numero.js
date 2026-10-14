// Equivale a Decimal(texto).normalize() formateado con 'f' (sin notación científica).
export function formatoNumero(texto) {
  let s = String(texto).trim().replace(',', '.');
  const m = /^([+-]?)(\d*)(?:\.(\d*))?$/.exec(s);
  if (!m || (m[2] === '' && !m[3])) return s;
  const signo = m[1] === '-' ? '-' : '';
  const entera = m[2].replace(/^0+(?=\d)/, '') || '0';
  const fraccion = (m[3] || '').replace(/0+$/, '');
  return signo + entera + (fraccion ? '.' + fraccion : '');
}

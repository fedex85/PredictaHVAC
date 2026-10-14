"""El CSS de Tailwind se compila en el repositorio: nada debe depender del CDN y el archivo debe estar al día."""
from pathlib import Path

from django.test import SimpleTestCase

RAIZ = Path(__file__).resolve().parent.parent
CSS = RAIZ / 'core' / 'static' / 'css' / 'predicta.css'
AYUDA = 'Falta o está vacío core/static/css/predicta.css: ejecuta `npm install` y `npm run css`.'


class CssCompiladoTests(SimpleTestCase):
    def test_ninguna_plantilla_usa_el_cdn(self):
        con_cdn = [str(p.relative_to(RAIZ)) for p in (RAIZ / 'templates').rglob('*.html')
                   if 'cdn.tailwindcss.com' in p.read_text(encoding='utf-8')]
        self.assertEqual(con_cdn, [])

    def test_el_css_compilado_existe_y_tiene_las_clases_clave(self):
        self.assertTrue(CSS.exists() and CSS.stat().st_size > 5000, AYUDA)
        texto = CSS.read_text(encoding='utf-8')
        for clase in ('.bg-slate-950', '.text-cyan-400', '.md\\:flex-row', '.hidden', '.rounded-xl'):
            self.assertIn(clase, texto, clase)

    def test_el_css_incluye_clases_que_solo_aparecen_en_el_js_sin_conexion(self):
        # arranque.js crea el contador con clases de Tailwind; si el escaneo omitiera los .js se perderían.
        texto = CSS.read_text(encoding='utf-8') if CSS.exists() else ''
        self.assertIn('.text-emerald-300', texto, AYUDA)
        self.assertIn('.space-y-3', texto, AYUDA)

    def test_todas_las_clases_de_los_templates_estan_compiladas(self):
        """Cada clase `bg-/text-/border-` con color escrita en una plantilla debe existir en el CSS."""
        import re
        texto = CSS.read_text(encoding='utf-8') if CSS.exists() else ''
        self.assertTrue(texto, AYUDA)
        usadas = set()
        for p in (RAIZ / 'templates').rglob('*.html'):
            html = re.sub(r'\{[{%].*?[}%]\}', ' ', p.read_text(encoding='utf-8'))
            usadas.update(re.findall(r'(?<![\w:/-])((?:bg|text|border)-(?:slate|cyan|emerald|amber|red|violet|white)(?:-\d{2,3})?)(?![\w/-])', html))
        faltan = sorted(c for c in usadas if '.' + c not in texto and '.' + c.replace('/', '\\/') not in texto)
        self.assertEqual(faltan, [], 'Clases usadas pero no compiladas; ejecuta `npm run css`.')

"""Opt-in: run the real pilot DOM program on fictitious theme fixtures in local Chromium.

No AEDB access. Pages are served by Playwright `route.fulfill` on the reserved
`.invalid` host; every other request is aborted. Headless, temporary context,
no persistent profile. Enable with CAMPUS_AI_BROWSER_SMOKE=1.
"""
import json
import os
import subprocess
import sys
import unittest

from campus_ai.pilot import resolve_title, kind_label

SCRIPT = r'''
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from campus_ai.pilot import SNAPSHOT_JS
URL = 'https://pilot.invalid/ava/course/view.php?id=42'
LATE = """<!doctype html><html><head><title></title></head><body class="course-42">
<nav class="navbar"><div class="usermenu"><a id="user-menu-toggle">U</a></div></nav><div id="slot"></div>
<script>setTimeout(() => { document.getElementById('slot').innerHTML =
 '<header id="page-header"><h1>Disciplina tardia fictícia</h1></header>'; }, 600);</script></body></html>"""
out = {}
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    try:
        context = browser.new_context(accept_downloads=False)
        context.route('**/*', lambda route: route.abort())
        body = {'html': ''}
        context.route('https://pilot.invalid/**', lambda route: route.fulfill(
            status=200, content_type='text/html; charset=utf-8', body=body['html']))
        page = context.new_page()
        opts = lambda sel: {'max_elements': 3000, 'timeout_ms': 5000, 'selection_only': sel}
        for name in ('aedb_theme_course', 'boost_course', 'ambiguous_course', 'empty_course', 'login_page'):
            body['html'] = Path('tests/fixtures/%s.html' % name).read_text(encoding='utf-8')
            page.goto(URL)
            if name == 'boost_course':
                # 4500+ drawer nodes before the header exhausted the old shared budget.
                page.evaluate("""() => { const s = document.getElementById('drawer-slot');
                  s.innerHTML = '<ul>' + '<li><a href="#"><span>Item</span></a></li>'.repeat(1500) + '</ul>'; }""")
            out[name] = {'select': page.evaluate(SNAPSHOT_JS, opts(True)), 'read': page.evaluate(SNAPSHOT_JS, opts(False))}
        body['html'] = LATE
        page.goto(URL)
        early = page.evaluate(SNAPSHOT_JS, opts(True))
        page.wait_for_timeout(1000)
        out['late'] = {'early': early, 'later': page.evaluate(SNAPSHOT_JS, opts(True))}
    finally:
        browser.close()
print('JSON' + json.dumps(out))
'''


@unittest.skipUnless(os.environ.get('CAMPUS_AI_BROWSER_SMOKE') == '1',
                     'Chromium local opt-in: CAMPUS_AI_BROWSER_SMOKE=1')
class PilotThemeDOMSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([sys.executable, '-c', SCRIPT], capture_output=True, text=True,
                                encoding='utf-8', timeout=60, env=dict(os.environ, PLAYWRIGHT_BROWSERS_PATH='0'))
        if result.returncode != 0:
            raise AssertionError(result.stderr[-2000:])
        cls.data = json.loads(result.stdout.split('JSON', 1)[1])

    def resolve(self, name, phase='select'):
        snap = self.data[name][phase]
        return snap, resolve_title(snap['title_candidates'], snap['doc_title'])

    def test_custom_theme_banner_breadcrumb_and_tab_title(self):
        snap, found = self.resolve('aedb_theme_course')
        self.assertTrue(snap['authenticated'])
        self.assertEqual(found.title, '4º P CURSO FICTÍCIO - Modelagem Fictícia')
        self.assertEqual(found.confidence, 'confirmado')
        self.assertEqual(set(found.sources), {'área destacada do curso', 'trilha de navegação', 'título da aba'})
        texts = str(snap['title_candidates'])
        for excluded in ('AVA Fictício', 'Outra disciplina', 'Disciplina do bloco', 'Rodapé', '35%'):
            self.assertNotIn(excluded, texts)
        self.assertEqual(snap['ids']['body'], '42')
        self.assertEqual(snap['rows'], [])

    def test_custom_theme_content_rows(self):
        snap = self.data['aedb_theme_course']['read']
        rows = {r['title']: r for r in snap['rows']}
        self.assertIn('Aula 1 — Introdução fictícia', rows)
        self.assertIn('Aula 2 — Recolhida fictícia', rows)
        self.assertEqual(rows['Slides fictícios']['due'], '')
        self.assertEqual(kind_label(rows['Slides fictícios']['kind']), 'Arquivo')
        self.assertEqual(rows['Exercício fictício']['due'], 'Vencimento: terça, 20 out 2026, 23:59')
        self.assertEqual(rows['Questionário fictício']['due'], 'Fecha: 25 out 2026, 18:00')
        self.assertEqual(kind_label(rows['Fórum restrito fictício']['kind']), 'Fórum')
        for absent in ('Oculto', 'Página recolhida', 'Texto de rótulo fictício', 'Item do índice'):
            self.assertNotIn(absent, rows)
        self.assertEqual([(s['name'], s['state']) for s in snap['sections']],
                         [('Aula 1 — Introdução fictícia', 'open'), ('Aula 2 — Recolhida fictícia', 'collapsed')])
        self.assertTrue(snap['recognized'])
        self.assertFalse(snap['truncated'])

    def test_large_drawer_no_longer_hides_header(self):
        snap, found = self.resolve('boost_course')
        self.assertEqual((found.title, found.confidence), ('Disciplina Boost fictícia', 'confirmado'))
        read = self.data['boost_course']['read']
        self.assertEqual([r['title'] for r in read['rows']], ['Geral fictício', 'Avisos fictícios'])
        self.assertFalse(read['truncated'])

    def test_ambiguous_titles(self):
        _, found = self.resolve('ambiguous_course')
        self.assertEqual(found.confidence, 'ambíguo')
        self.assertEqual(set(found.choices), {'Disciplina A fictícia', 'Disciplina B fictícia'})

    def test_empty_course_with_aria_hidden_heading(self):
        snap, found = self.resolve('empty_course')
        self.assertEqual(found.title, 'Disciplina vazia fictícia')
        self.assertTrue(snap['authenticated'])
        read = self.data['empty_course']['read']
        self.assertEqual([r['kind'] for r in read['rows']], ['Seção'])

    def test_expired_session_page(self):
        snap = self.data['login_page']['select']
        self.assertTrue(snap['login'])
        self.assertFalse(snap['authenticated'])

    def test_late_rendered_header(self):
        early, later = self.data['late']['early'], self.data['late']['later']
        self.assertIsNone(resolve_title(early['title_candidates'], early['doc_title']))
        self.assertEqual(resolve_title(later['title_candidates'], later['doc_title']).title,
                         'Disciplina tardia fictícia')


if __name__ == '__main__':
    unittest.main()

"""Opt-in: the real expansion programs in local Chromium against FICTITIOUS course HTML.

Same isolation as test_pilot_flow_chromium: every ead.aedb.br request is answered by
`route.fulfill`, everything else is aborted and Chromium uses a dead proxy. The fixtures
record each click in window.__clicks, so the tests prove which controls were activated.
Enable with CAMPUS_AI_BROWSER_SMOKE=1.
"""
import json
import os
import subprocess
import sys
import unittest

SCRIPT = r'''
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from campus_ai.authorized_courses import AuthorizedCourse
from campus_ai.pilot import PilotReader, PilotLimits

COURSE = AuthorizedCourse('42', 'Modelagem Fictícia')
HTML = {n: Path('tests/fixtures/%s.html' % n).read_text(encoding='utf-8')
        for n in ('collapsible_course', 'collapsible_mixed', 'aedb_theme_course')}
out = {}


def run(name, fixture):
    seen = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--proxy-server=http://127.0.0.1:9'])
        try:
            context = browser.new_context(accept_downloads=False)

            def handler(route):
                request = route.request
                seen.append([request.method, request.url])
                if request.url.startswith('https://ead.aedb.br/ava/course/view.php?id=42'):
                    route.fulfill(status=200, content_type='text/html; charset=utf-8', body=HTML[fixture])
                else:
                    route.abort()
            context.route('**/*', handler)
            page = context.new_page()
            cdp = context.new_cdp_session(page)
            cdp.send('Browser.setDownloadBehavior', {'behavior': 'deny'})
            page.goto('https://ead.aedb.br/ava/course/view.php?id=42', wait_until='domcontentloaded')
            reader = PilotReader(page, cdp, PilotLimits())
            selection = reader.identify(COURSE)
            states = []
            result = reader.read(selection, expand=True, progress=states.append)
            c = result.coverage
            out[name] = dict(
                clicks=page.evaluate('window.__clicks'), states=states, state=result.state,
                diagnostic=result.diagnostic, seen=seen,
                coverage=dict(total=c.sections_total, expanded=c.expanded, open=c.already_open,
                              inaccessible=c.inaccessible, materials=c.materials, activities=c.activities,
                              reasons=[list(r) for r in c.reasons]),
                rows=[[r.section, r.kind, r.title, r.due, r.url] for r in result.rows])
        finally:
            browser.close()


run('clean', 'collapsible_course')
run('mixed', 'collapsible_mixed')
run('old_theme', 'aedb_theme_course')
print('JSON' + json.dumps(out))
'''


@unittest.skipUnless(os.environ.get('CAMPUS_AI_BROWSER_SMOKE') == '1',
                     'Chromium local opt-in: CAMPUS_AI_BROWSER_SMOKE=1')
class ExpansionChromium(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([sys.executable, '-c', SCRIPT], capture_output=True, text=True,
                                encoding='utf-8', timeout=120, env=dict(os.environ, PLAYWRIGHT_BROWSERS_PATH='0'))
        if result.returncode != 0:
            raise AssertionError(result.stderr[-3000:])
        cls.data = json.loads(result.stdout.split('JSON', 1)[1])

    def titles(self, name):
        return {row[2]: row for row in self.data[name]['rows']}

    def test_av1_and_av2_are_expanded_and_read_without_user_help(self):
        d = self.data['clean']
        self.assertEqual(d['clicks'], ['AV1', 'AV2'])
        self.assertEqual(d['states'], ['explorando', 'expandindo', 'analisando'])
        self.assertEqual(d['state'], 'completa')
        c = d['coverage']
        self.assertEqual((c['total'], c['expanded'], c['open'], c['inaccessible']), (3, 2, 1, 0))
        self.assertEqual((c['materials'], c['activities']), (2, 3))
        t = self.titles('clean')
        self.assertEqual(t['Trabalho AV1 fictício'][0], 'AV1')
        self.assertEqual(t['Trabalho AV1 fictício'][3], 'Vencimento: terça, 20 out 2026, 23:59')
        self.assertEqual(t['Slides AV1 fictícios'][3], 'Não informado')
        self.assertEqual(t['Prova AV2 fictícia'][0], 'AV2', 'content loaded asynchronously after the click')
        self.assertEqual(t['Prova AV2 fictícia'][3], 'Fecha: 25 out 2026, 18:00')
        self.assertIn('Cobertura completa', d['diagnostic'])

    def test_only_section_expanders_are_activated(self):
        forbidden = {'concluir', 'enviar', 'baixar', 'menu-editar', 'excluir-secao'}
        for name in ('clean', 'mixed'):
            with self.subTest(fixture=name):
                self.assertFalse(forbidden & set(self.data[name]['clicks']), self.data[name]['clicks'])

    def test_no_download_no_submission_no_other_page(self):
        for name, d in self.data.items():
            with self.subTest(fixture=name):
                self.assertTrue(all(method == 'GET' for method, _ in d['seen']))
                self.assertEqual([u for _, u in d['seen'] if 'pluginfile' in u or '/mod/' in u], [])
                self.assertEqual({u for _, u in d['seen']}, {'https://ead.aedb.br/ava/course/view.php?id=42'})

    def test_ambiguous_unsafe_and_missing_expanders_stay_intact_and_partial(self):
        d = self.data['mixed']
        self.assertEqual(d['clicks'], ['AV1'])
        self.assertEqual(d['state'], 'parcial')
        c = d['coverage']
        self.assertEqual((c['total'], c['expanded'], c['open'], c['inaccessible']), (6, 1, 1, 4))
        reasons = dict(c['reasons'])
        self.assertIn('ambíguo', reasons['AV3 ambígua'])
        self.assertIn('verificável', reasons['AV4 download'])
        self.assertIn('nenhum controle', reasons['AV5 sem controle'])
        self.assertIn('verificável', reasons['AV6 formulário'])
        t = self.titles('mixed')
        self.assertIn('Slides AV1 fictícios', t)
        for hidden in ('Conteúdo A fictício', 'Conteúdo AV4 fictício', 'Conteúdo AV5 fictício', 'Conteúdo AV6 fictício'):
            self.assertNotIn(hidden, t)
        self.assertIn('Cobertura parcial', d['diagnostic'])

    def test_theme_with_hidden_section_and_no_control_is_partial_not_complete(self):
        d = self.data['old_theme']
        self.assertEqual(d['state'], 'parcial')
        self.assertEqual(d['clicks'] if 'clicks' in d and d['clicks'] else [], [])
        self.assertEqual(d['coverage']['inaccessible'], 1)
        self.assertIn('Aula 2', ' '.join(r[0] for r in d['coverage']['reasons']))


if __name__ == '__main__':
    unittest.main()

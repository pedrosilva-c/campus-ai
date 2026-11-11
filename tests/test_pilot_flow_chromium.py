"""Opt-in: the real direct-open flow in local Chromium against a FICTITIOUS portal.

Every request to ead.aedb.br is answered inside the browser by `route.fulfill`
(fixture HTML); everything else is aborted. Chromium also runs with a dead proxy
(`--proxy-server=http://127.0.0.1:9`), so a request that escaped interception would
fail to connect instead of reaching the real AEDB. Headless, temporary
non-persistent context, no profile, no credentials. The portal's HTTP 302 to the
login page is modelled as a client-side redirect because Playwright does not
re-intercept a fulfilled 302; reach_course only depends on `page.url`.
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
from campus_ai.pilot_flow import reach_course

COURSE = AuthorizedCourse('42', 'Modelagem Fictícia')
fixtures = lambda name: Path('tests/fixtures/%s.html' % name).read_text(encoding='utf-8')
NO_HEADER = ('<!doctype html><html><head><title></title></head><body class="path-course-view course-42">'
             '<div class="usermenu"><a id="user-menu-toggle">U</a></div><div id="region-main"><div role="main">'
             '<ul><li class="section" data-for="section"><h3>Seção fictícia</h3></li></ul></div></div></body></html>')
out = {}


def scenario(name, course_html, needs_login):
    state = {'logged_in': not needs_login, 'seen': []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--proxy-server=http://127.0.0.1:9'])
        try:
            context = browser.new_context(accept_downloads=False)

            def handler(route):
                url = route.request.url
                state['seen'].append(url)
                if url.startswith('https://ead.aedb.br/ava/course/view.php?id=42'):
                    if state['logged_in']:
                        route.fulfill(status=200, content_type='text/html; charset=utf-8', body=course_html)
                    else:
                        route.fulfill(status=200, content_type='text/html; charset=utf-8', body=(
                            '<!doctype html><html><body><script>'
                            "location.replace('https://ead.aedb.br/ava/login/index.php')</script></body></html>"))
                elif url.startswith('https://ead.aedb.br/ava/login/'):
                    route.fulfill(status=200, content_type='text/html; charset=utf-8', body=fixtures('login_page'))
                else:
                    route.abort()
            context.route('**/*', handler)
            page = context.new_page()
            starting_url = page.url
            cdp = context.new_cdp_session(page)
            cdp.send('Browser.setDownloadBehavior', {'behavior': 'deny'})
            reader = PilotReader(page, cdp, PilotLimits())
            states = []

            def progress(value):
                states.append(value)
                if value == 'login':
                    # Stands in for the student signing in by hand, then the portal returning to the course.
                    state['logged_in'] = True
                    page.goto('https://ead.aedb.br/ava/course/view.php?id=42', wait_until='domcontentloaded')
            reach_course(page, reader, COURSE, cancelled=lambda: False, progress=progress,
                         poll_ms=200, login_wait_s=20)
            selection = reader.identify(COURSE, cancelled=lambda: False)
            result = reader.read(selection, cancelled=lambda: False, expand=True)
            out[name] = dict(states=states, start=starting_url, final=page.url, seen=state['seen'],
                             title=selection.title, confidence=selection.confidence, state=result.state,
                             rows=[[r.kind, r.title, r.due] for r in result.rows], diagnostic=result.diagnostic)
        finally:
            browser.close()


scenario('login_flow', fixtures('aedb_theme_course'), needs_login=True)
scenario('logged_in', fixtures('aedb_theme_course'), needs_login=False)
scenario('no_header', NO_HEADER, needs_login=False)
print('JSON' + json.dumps(out))
'''


@unittest.skipUnless(os.environ.get('CAMPUS_AI_BROWSER_SMOKE') == '1',
                     'Chromium local opt-in: CAMPUS_AI_BROWSER_SMOKE=1')
class DirectOpenChromium(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([sys.executable, '-c', SCRIPT], capture_output=True, text=True,
                                encoding='utf-8', timeout=90, env=dict(os.environ, PLAYWRIGHT_BROWSERS_PATH='0'))
        if result.returncode != 0:
            raise AssertionError(result.stderr[-3000:])
        cls.data = json.loads(result.stdout.split('JSON', 1)[1])

    def test_manual_login_then_automatic_reading(self):
        d = self.data['login_flow']
        self.assertEqual(d['states'], ['abrindo', 'login', 'autenticado'])
        self.assertEqual(d['start'], 'about:blank')
        self.assertEqual(d['final'], 'https://ead.aedb.br/ava/course/view.php?id=42')
        self.assertEqual(d['title'], '4º P CURSO FICTÍCIO - Modelagem Fictícia')
        self.assertEqual(d['state'], 'parcial', 'one collapsed section keeps the result partial')
        self.assertIn('Cobertura parcial', d['diagnostic'])
        self.assertIn('Aula 2 — Recolhida fictícia: nenhum controle de expansão', d['diagnostic'])
        kinds = {title: (kind, due) for kind, title, due in d['rows']}
        self.assertEqual(kinds['Exercício fictício'], ('Tarefa', 'Vencimento: terça, 20 out 2026, 23:59'))
        self.assertEqual(kinds['Questionário fictício'], ('Questionário', 'Fecha: 25 out 2026, 18:00'))
        self.assertEqual(kinds['Slides fictícios'][1], 'Não informado', 'a missing deadline is never invented')

    def test_only_the_authorized_course_and_login_pages_are_requested(self):
        allowed = ('https://ead.aedb.br/ava/course/view.php?id=42', 'https://ead.aedb.br/ava/login/index.php')
        for name, d in self.data.items():
            with self.subTest(scenario=name):
                documents = [u for u in d['seen'] if u.startswith('https://ead.aedb.br/ava/')]
                self.assertTrue(documents)
                self.assertTrue(all(u in allowed for u in documents), documents)
                self.assertFalse([u for u in d['seen'] if not u.startswith('https://ead.aedb.br/')],
                                 'nothing outside the fictitious portal may be requested')

    def test_already_signed_in_opens_directly(self):
        d = self.data['logged_in']
        self.assertEqual(d['states'], ['abrindo', 'autenticado'])
        self.assertEqual(d['seen'][0], 'https://ead.aedb.br/ava/course/view.php?id=42')
        self.assertNotIn('https://ead.aedb.br/ava/login/index.php', d['seen'])

    def test_custom_header_not_recognized_does_not_block_reading(self):
        d = self.data['no_header']
        self.assertEqual((d['title'], d['confidence']), ('Modelagem Fictícia', 'id do curso'))
        self.assertEqual([r[1] for r in d['rows']], ['Seção fictícia'])


if __name__ == '__main__':
    unittest.main()

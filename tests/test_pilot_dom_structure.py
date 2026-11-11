"""Opt-in: academic-section recognition, scrolling and honest coverage in local Chromium.

Same isolation as test_pilot_dom_expand: every ead.aedb.br request is answered by `route.fulfill`
with FICTITIOUS HTML, everything else is aborted and Chromium uses a dead proxy. The fixtures
record each click in window.__clicks. Enable with CAMPUS_AI_BROWSER_SMOKE=1.
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
from campus_ai.pilot import PilotReader, PilotLimits, PilotRejected, PilotLoginRequired

COURSE = AuthorizedCourse('42', 'Modelagem Fictícia')
HTML = {n: Path('tests/fixtures/%s.html' % n).read_text(encoding='utf-8')
        for n in ('cards_course', 'cards_only', 'collapsible_course')}
out = {}


def run(name, scenario=None):
    seen = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--proxy-server=http://127.0.0.1:9'])
        try:
            context = browser.new_context(accept_downloads=False, viewport={'width': 1100, 'height': 700})

            def handler(route):
                request = route.request
                seen.append([request.method, request.url])
                if request.url.startswith('https://ead.aedb.br/ava/course/view.php?id=42'):
                    route.fulfill(status=200, content_type='text/html; charset=utf-8', body=HTML[name])
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
            if scenario in ('cancel', 'expired'):
                calls = [0]

                def cancelled():
                    calls[0] += 1
                    return scenario == 'cancel' and calls[0] > 6      # a few scroll steps in

                def progress(state):
                    states.append(state)
                    if scenario == 'expired' and state == 'explorando':
                        # the portal drops the session while the page is being scrolled
                        page.evaluate("document.querySelector('.usermenu').remove();"
                                      "document.body.classList.add('notloggedin')")
                try:
                    reader.read(selection, cancelled=cancelled, expand=True, progress=progress)
                    outcome = 'finished'
                except PilotLoginRequired:
                    outcome = 'login'
                except PilotRejected as exc:
                    outcome = 'rejected:' + str(exc)[:60]
                out[scenario] = dict(outcome=outcome, states=states, clicks=page.evaluate('window.__clicks'),
                                     closed=page.is_closed(), url=page.url,
                                     seen=[u for _, u in seen])
                return
            if scenario == 'timeout':
                reader = PilotReader(page, cdp, PilotLimits(scroll_ms=1))
            result = reader.read(selection, expand=True, progress=states.append)
            c = result.coverage
            out[scenario or name] = dict(
                clicks=page.evaluate('window.__clicks'), states=states, state=result.state,
                diagnostic=result.diagnostic, seen=seen, scroll_y=page.evaluate('window.scrollY'),
                coverage=dict(total=c.sections_total, expanded=c.expanded, open=c.already_open,
                              unknown=c.unknown, inaccessible=c.inaccessible, materials=c.materials,
                              activities=c.activities, candidates=c.candidates, layout=c.layout,
                              safe=c.safe_expanders, clicked=c.clicked, activity_elements=c.activity_elements,
                              scrolls=c.scrolls, nav_missing=c.nav_missing, orphan_links=c.orphan_links,
                              unnamed=c.unnamed, ignored=[list(x) for x in c.ignored],
                              reasons=[list(r) for r in c.reasons]),
                rows=[[r.section, r.kind, r.title, r.due, r.url] for r in result.rows])
        finally:
            browser.close()


for fixture in ('cards_course', 'cards_only', 'collapsible_course'):
    run(fixture)
for scenario in ('cancel', 'expired', 'timeout'):
    run('cards_course', scenario)
print('JSON' + json.dumps(out))
'''


@unittest.skipUnless(os.environ.get('CAMPUS_AI_BROWSER_SMOKE') == '1',
                     'Chromium local opt-in: CAMPUS_AI_BROWSER_SMOKE=1')
class StructureChromium(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([sys.executable, '-c', SCRIPT], capture_output=True, text=True,
                                encoding='utf-8', timeout=150, env=dict(os.environ, PLAYWRIGHT_BROWSERS_PATH='0'))
        if result.returncode != 0:
            raise AssertionError(result.stderr[-3000:])
        cls.data = json.loads(result.stdout.split('JSON', 1)[1])

    def titles(self, name):
        return {row[2]: row for row in self.data[name]['rows']}

    # --- the reported failure: cards before the sections, content below the fold
    def test_cards_that_look_like_sections_are_layout_not_academic(self):
        d = self.data['cards_course']
        names = [row[2] for row in d['rows'] if row[1] == 'Seção']
        self.assertEqual(names, ['AV1', 'AV2', 'AV3', 'AV4 vazia'])
        for card in ('Avisos', 'Currículo Lattes', 'Informações da Disciplina', 'Trilhas de Aprendizagem'):
            self.assertNotIn(card, names)
        c = d['coverage']
        self.assertEqual(c['total'], 4)
        self.assertGreaterEqual(c['layout'], 5)
        self.assertIn('layout', dict(c['ignored']))

    def test_cards_and_unrecognized_headers_are_never_clicked(self):
        d = self.data['cards_course']
        self.assertEqual(d['clicks'], ['AV1'], d['clicks'])
        self.assertEqual(self.data['cards_only']['clicks'], [])

    def test_content_below_the_fold_and_loaded_on_scroll_is_read(self):
        d = self.data['cards_course']
        self.assertIn('explorando', d['states'])
        self.assertGreaterEqual(d['coverage']['scrolls'], 2)
        t = self.titles('cards_course')
        self.assertEqual(t['Prova AV2 fictícia'][0], 'AV2')
        self.assertEqual(t['Prova AV2 fictícia'][3], 'Fecha: 25 out 2026, 18:00')
        self.assertEqual(t['Resumo AV2 fictício'][3], 'Não informado')
        self.assertEqual(d['scroll_y'], 0, 'the page is returned to the top after exploring')

    def test_open_collapsed_unrecognized_and_empty_sections_are_told_apart(self):
        d = self.data['cards_course']
        c = d['coverage']
        self.assertEqual((c['expanded'], c['open'], c['inaccessible'], c['unknown']), (1, 1, 1, 1))
        self.assertEqual((c['safe'], c['clicked']), (1, 1))
        reasons = dict(c['reasons'])
        self.assertIn('nenhum controle', reasons['AV3'])
        self.assertIn('div', reasons['AV3'], 'structural hint (tag names only) for the unrecognized header')
        self.assertIn('sem conteúdo visível', reasons['AV4 vazia'])
        self.assertEqual(d['state'], 'parcial')
        self.assertNotIn('Conteúdo AV3 fictício', self.titles('cards_course'))
        t = self.titles('cards_course')
        self.assertEqual(t['Slides AV1 fictícios'][3], 'Não informado')
        self.assertEqual(t['Trabalho AV1 fictício'][3], 'Vencimento: terça, 20 out 2026, 23:59')

    def test_navigation_to_other_pages_is_reported_not_followed(self):
        d = self.data['cards_course']
        self.assertEqual(d['coverage']['nav_missing'], 1)
        self.assertEqual(d['coverage']['orphan_links'], 1)
        self.assertIn('outra página', d['diagnostic'])
        self.assertEqual({u for _, u in d['seen']}, {'https://ead.aedb.br/ava/course/view.php?id=42'})
        self.assertTrue(all(m == 'GET' for m, _ in d['seen']))

    def test_reported_empty_page_is_not_validated_instead_of_complete(self):
        d = self.data['cards_only']
        self.assertEqual(d['state'], 'nao_validada')
        self.assertTrue(d['diagnostic'].startswith('Cobertura não validada'), d['diagnostic'])
        c = d['coverage']
        self.assertEqual((c['total'], c['unknown'], c['open'], c['materials'], c['activities']), (2, 2, 0, 0, 0))
        self.assertEqual(c['unnamed'], 2)
        self.assertEqual(d['rows'], [], 'no generic "Seção N" rows for unnamed blocks')
        self.assertEqual(c['nav_missing'], 2)
        self.assertNotIn('Cobertura completa', d['diagnostic'])

    def test_diagnostic_lists_the_structural_counts(self):
        text = self.data['cards_course']['diagnostic']
        for fragment in ('regiões candidatas', 'seções acadêmicas reconhecidas', 'expansores seguros',
                         'acionados', 'elementos de atividade', 'itens extraídos', 'rolagens', 'ignorados'):
            self.assertIn(fragment, text)

    def test_cancel_while_scrolling_clicks_nothing_and_keeps_the_page_open(self):
        d = self.data['cancel']
        self.assertTrue(d['outcome'].startswith('rejected:Análise cancelada'), d['outcome'])
        self.assertEqual(d['clicks'], [])
        self.assertFalse(d['closed'])
        self.assertEqual(d['url'], 'https://ead.aedb.br/ava/course/view.php?id=42')

    def test_session_lost_while_scrolling_discards_the_reading(self):
        d = self.data['expired']
        self.assertEqual(d['outcome'], 'login')
        self.assertEqual(d['clicks'], [])
        self.assertFalse(d['closed'])

    def test_scroll_timeout_is_partial_with_the_reason(self):
        d = self.data['timeout']
        self.assertEqual(d['state'], 'parcial')
        self.assertIn('rolagem incompleta', d['diagnostic'])
        self.assertLessEqual(d['coverage']['scrolls'], 2)

    def test_standard_collapsible_course_is_still_complete(self):
        d = self.data['collapsible_course']
        self.assertEqual(d['state'], 'completa')
        self.assertEqual(d['clicks'], ['AV1', 'AV2'])
        self.assertTrue(d['diagnostic'].startswith('Cobertura completa'))


if __name__ == '__main__':
    unittest.main()

"""Opt-in: card navigation in local Chromium against a FICTITIOUS portal.

Home (navigation cards) -> Atividades Avaliativas -> AV1/AV2 -> materials, then back to the home.
Every ead.aedb.br request is answered by `route.fulfill` with fixture HTML (or deliberately left
hanging for the timeout case); everything else is aborted and Chromium uses a dead proxy. The
fixtures record every click in window.__clicks and every request is logged, so the tests prove which
controls were activated and which addresses were requested. Enable with CAMPUS_AI_BROWSER_SMOKE=1.
"""
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

FIXTURES = Path(__file__).parent / 'fixtures'
HOME_URL = 'https://ead.aedb.br/ava/course/view.php?id=42'
DEST_URL = HOME_URL + '&section=3'


def link_card(href):
    return ('<div class="card"><h3 class="card-title">Atividades Avaliativas</h3>'
            f'<a href="{href}" onclick="window.__clicks.push(\'card:avaliativas\')">Abrir</a></div>')


def variants():
    dest = FIXTURES.joinpath('nav_avaliativas.html').read_text(encoding='utf-8')
    topics = re.search(r'<ul class="topics">.*?</ul>\s*</div></div>', dest, re.S).group(0).rsplit('</div></div>', 1)[0]
    handler = re.search(r'<script>\s*window\.__clicks = \[\];(.*?)</script>', dest, re.S).group(1)
    panel = f'<div id="panel-av" style="display:none">{topics}</div><script>{handler}</script>'
    return {
        'link': (link_card('/ava/course/view.php?id=42&amp;section=3'), ''),
        'attr': ('<div class="card" id="av" role="link" tabindex="0" data-href="/ava/course/view.php?id=42&amp;section=3">'
                 '<h3 class="card-title">Atividades Avaliativas</h3></div><script>'
                 'document.getElementById("av").addEventListener("click", e => {'
                 ' window.__clicks.push("card:avaliativas"); location.href = e.currentTarget.dataset.href; })</script>', ''),
        'onclick': ('<div class="card" role="link" tabindex="0" onclick="window.__clicks.push(\'card:avaliativas\'); '
                    'location.href=\'/ava/course/view.php?id=42&amp;section=3\'">'
                    '<h3 class="card-title">Atividades Avaliativas</h3></div>', ''),
        'tab': ('<div class="card"><button type="button" role="tab" id="tab-av" aria-controls="panel-av">'
                '<h3 class="card-title">Atividades Avaliativas</h3></button></div><script>'
                'document.getElementById("tab-av").addEventListener("click", () => {'
                ' window.__clicks.push("tab"); document.getElementById("panel-av").style.display = "block"; })</script>',
                panel),
        'js': ('<div class="card"><h3 class="card-title">Atividades Avaliativas</h3><button type="button" id="go">Entrar</button>'
               '</div><script>document.getElementById("go").addEventListener("click", () => {'
               ' window.__clicks.push("card:avaliativas"); const n = 1 + 2;'
               ' location.href = "/ava/course/view.php?id=42&section=" + n; })</script>', ''),
        'assign': (link_card('/ava/mod/assign/view.php?id=9'), ''),
        'other_course': (link_card('/ava/course/view.php?id=99&amp;section=3'), ''),
        'external': (link_card('https://other.example.invalid/ava/course/view.php?id=42&amp;section=3'), ''),
        'unknown': (link_card('/ava/local/aedb/aval.php?courseid=42'), ''),
        'extra': (link_card('/ava/course/view.php?id=42&amp;section=3&amp;sesskey=SECRET'), ''),
    }


SCRIPT = r'''
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
import campus_ai.pilot_nav as pilot_nav
from campus_ai.authorized_courses import AuthorizedCourse
from campus_ai.pilot import PilotReader, PilotLimits, PilotRejected, PilotLoginRequired, PilotSelection
from campus_ai.pilot_nav import CardNavigator, NavQuestion

VARIANTS = json.loads(sys.argv[1])
FX = Path('tests/fixtures')
HOME, DEST = 'https://ead.aedb.br/ava/course/view.php?id=42', 'https://ead.aedb.br/ava/course/view.php?id=42&section=3'
COURSE = AuthorizedCourse('42', 'Modelagem Fictícia')
HOME_HTML = (FX / 'nav_home.html').read_text(encoding='utf-8')
DEST_HTML = (FX / 'nav_avaliativas.html').read_text(encoding='utf-8')
LOGIN_HTML = (FX / 'login_page.html').read_text(encoding='utf-8')
out = {}


def run(browser, name, variant, *, mode='analyze', hang=False, expire=False):
    card, panel = VARIANTS[variant]
    home = HOME_HTML.replace('{{AV_CARD}}', card).replace('{{PANEL}}', panel)
    seen, states, samples, state, hung = [], [], {}, {'expired': expire}, []
    context = browser.new_context(accept_downloads=False, viewport={'width': 1100, 'height': 700})

    def handler(route):
        request = route.request
        seen.append([request.method, request.url])
        if request.url == HOME:
            route.fulfill(status=200, content_type='text/html; charset=utf-8', body=home)
        elif request.url == DEST:
            if hang:
                hung.append(route)                      # never answered: the navigation times out
                return
            body = LOGIN_HTML if state['expired'] else DEST_HTML
            route.fulfill(status=200, content_type='text/html; charset=utf-8', body=body)
        else:
            route.abort()
    context.route('**/*', handler)
    page = context.new_page()
    cdp = context.new_cdp_session(page)
    cdp.send('Browser.setDownloadBehavior', {'behavior': 'deny'})
    page.goto(HOME, wait_until='domcontentloaded')
    reader = PilotReader(page, cdp, PilotLimits())
    selection = reader.identify(COURSE)

    def progress(s):
        states.append(s)
        if s.startswith('acessando'):
            samples['before'] = page.evaluate('window.__clicks')
        if s == 'verificando':
            samples['at_destination'] = page.evaluate('window.__clicks')

    cancel = (lambda: DEST in page.url + '&' and 'section=3' in page.url) if mode == 'cancel' else None
    if mode == 'timeout':
        pilot_nav.NAV_TIMEOUT_MS = 1500
    record = dict(variant=variant, states=states)
    try:
        navigator = CardNavigator(reader)
        result = navigator.analyze(COURSE, selection, progress=progress, cancelled=cancel,
                                   inspect_only=(mode == 'inspect'))
        if isinstance(result, NavQuestion):
            record.update(outcome='question', question=dict(label=result.label, key=result.key),
                          clicks_after_question=page.evaluate('window.__clicks'), seen_after_question=len(seen))
            if mode in ('confirm', 'decline'):
                answer = {'confirmed' if mode == 'confirm' else 'declined': result.key}
                result = CardNavigator(PilotReader(page, cdp, PilotLimits())).analyze(
                    COURSE, selection, progress=progress, **answer)
        if not isinstance(result, NavQuestion):
            nav = result.navigation
            record.update(outcome='result', state=result.state, diagnostic=result.diagnostic,
                          rows=[[r.section, r.kind, r.title, r.due, r.url] for r in result.rows],
                          nav=None if nav is None else dict(method=nav.method, returned=nav.returned, pages=nav.pages,
                                                            unread=list(nav.unread), blocked=list(nav.blocked),
                                                            cards=[dict(c) for c in nav.cards]))
    except PilotLoginRequired:
        record['outcome'] = 'login'
    except PilotRejected as exc:
        record['outcome'] = 'rejected:' + str(exc)[:60]
    for pending in hung:                                # release the deliberately hanging request
        pending.abort()
    url, closed = page.url, page.is_closed()
    try:
        final_clicks = None if closed else page.evaluate('window.__clicks')
    except Exception:                                   # e.g. the page became an error page (timeout case)
        final_clicks = None
    record.update(samples=samples, seen=seen, url=url, closed=closed, final_clicks=final_clicks)
    out[name] = record
    context.close()


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--proxy-server=http://127.0.0.1:9'])
    try:
        for name in ('link', 'attr', 'onclick', 'tab', 'assign', 'other_course', 'external', 'unknown', 'extra'):
            run(browser, name, name)
        run(browser, 'js_ask', 'js')
        run(browser, 'js_confirm', 'js', mode='confirm')
        run(browser, 'js_decline', 'js', mode='decline')
        run(browser, 'inspect', 'link', mode='inspect')
        run(browser, 'expired', 'link', expire=True)
        run(browser, 'timeout', 'link', mode='timeout', hang=True)
        run(browser, 'cancel', 'link', mode='cancel')
    finally:
        browser.close()
print('JSON' + json.dumps(out))
'''

DANGEROUS = {'concluir', 'enviar', 'baixar', 'responder', 'card:feedback', 'card:professor', 'card:info',
             'card:trilhas', 'dest-card:trilhas'}


@unittest.skipUnless(os.environ.get('CAMPUS_AI_BROWSER_SMOKE') == '1',
                     'Chromium local opt-in: CAMPUS_AI_BROWSER_SMOKE=1')
class CardNavigationChromium(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([sys.executable, '-c', SCRIPT, json.dumps(variants())], capture_output=True,
                                text=True, encoding='utf-8', timeout=300,
                                env=dict(os.environ, PLAYWRIGHT_BROWSERS_PATH='0'))
        if result.returncode != 0:
            raise AssertionError(result.stderr[-3000:])
        cls.data = json.loads(result.stdout.split('JSON', 1)[1])

    def urls(self, name):
        return [u for _, u in self.data[name]['seen']]

    def titles(self, name):
        return {row[2]: row for row in self.data[name]['rows']}

    # --- the main path, for each way a card can navigate
    def test_link_attribute_and_script_cards_reach_av1_and_av2_and_return_home(self):
        for name in ('link', 'attr', 'onclick'):
            with self.subTest(card=name):
                d = self.data[name]
                self.assertEqual(d['outcome'], 'result', d)
                self.assertEqual(self.urls(name), [HOME_URL, DEST_URL, HOME_URL], 'home -> destination -> home, nothing else')
                self.assertEqual(d['nav']['method'], {'link': 'link', 'attr': 'attr-url', 'onclick': 'onclick-url'}[name])
                self.assertTrue(d['nav']['returned'])
                self.assertEqual(d['url'], HOME_URL)
                t = self.titles(name)
                self.assertEqual(t['Trabalho AV1 fictício'][0], 'AV1')
                self.assertEqual(t['Trabalho AV1 fictício'][3], 'Vencimento: terça, 20 out 2026, 23:59')
                self.assertEqual(t['Slides AV1 fictícios'][3], 'Não informado')
                self.assertEqual(t['Prova AV2 fictícia'][0], 'AV2')
                self.assertEqual(t['Prova AV2 fictícia'][3], 'Fecha: 25 out 2026, 18:00')
                for expected in ('acessando:Atividades Avaliativas', 'identificando:AV1', 'identificando:AV2', 'verificando'):
                    self.assertIn(expected, d['states'])

    def test_the_card_handler_never_runs_when_the_address_was_validated(self):
        for name in ('link', 'attr', 'onclick'):
            with self.subTest(card=name):
                d = self.data[name]
                self.assertEqual(d['samples']['before'], [], 'nothing was clicked on the home page')
                self.assertEqual(d['final_clicks'], [], 'and nothing on the restored home')

    def test_on_the_destination_only_the_section_expander_is_clicked(self):
        for name in ('link', 'attr', 'onclick'):
            with self.subTest(card=name):
                at = self.data[name]['samples']['at_destination']
                self.assertEqual(at, ['AV1'], at)

    def test_only_academic_cards_that_were_requested_are_ever_navigated(self):
        for name, d in self.data.items():
            with self.subTest(scenario=name):
                visited = set(self.urls(name))
                self.assertLessEqual(visited, {HOME_URL, DEST_URL})
                self.assertTrue(all(m == 'GET' for m, _ in d['seen']))
                if d['final_clicks'] is not None:
                    self.assertFalse(DANGEROUS & set(d['final_clicks'] or []), d['final_clicks'])
                self.assertFalse(DANGEROUS & set(d['samples'].get('at_destination') or []))

    def test_result_is_partial_because_the_study_card_was_not_read(self):
        d = self.data['link']
        self.assertEqual(d['state'], 'parcial')
        self.assertNotIn('seguir links', d['diagnostic'], 'section-navigation links of the destination page are not content')
        self.assertEqual(self.data['link']['nav']['unread'], ['Trilhas de Aprendizagem'], 'the only reason is the unread study card')
        self.assertIn('Trilhas de Aprendizagem', d['diagnostic'])
        self.assertEqual(d['nav']['unread'], ['Trilhas de Aprendizagem'])
        self.assertEqual(set(d['nav']['blocked']), {'Feedback das Aulas', 'Fale com o Professor'})

    def test_same_page_tab_is_clicked_once_and_read_in_place(self):
        d = self.data['tab']
        self.assertEqual(d['outcome'], 'result', d)
        self.assertEqual(self.urls('tab'), [HOME_URL])
        self.assertEqual(d['nav']['method'], 'tab')
        self.assertEqual(self.titles('tab')['Prova AV2 fictícia'][0], 'AV2')
        self.assertEqual(d['final_clicks'][0], 'tab')
        self.assertNotIn('card:avaliativas', d['final_clicks'])

    # --- ambiguity and confirmation
    def test_script_card_with_no_verifiable_destination_asks_and_touches_nothing(self):
        d = self.data['js_ask']
        self.assertEqual(d['outcome'], 'question')
        self.assertEqual(d['question']['label'], 'Atividades Avaliativas')
        self.assertEqual(d['clicks_after_question'], [])
        self.assertEqual(self.urls('js_ask'), [HOME_URL])

    def test_confirmed_card_is_clicked_once_verified_and_the_result_stays_partial(self):
        d = self.data['js_confirm']
        self.assertEqual(d['outcome'], 'result', d)
        self.assertEqual(d['nav']['method'], 'confirmed-click')
        self.assertEqual(d['state'], 'parcial')
        self.assertEqual(self.urls('js_confirm'), [HOME_URL, DEST_URL, HOME_URL])
        self.assertTrue(d['nav']['returned'])
        self.assertEqual(self.titles('js_confirm')['Prova AV2 fictícia'][0], 'AV2')

    def test_declined_card_is_never_touched(self):
        d = self.data['js_decline']
        self.assertEqual(d['outcome'], 'result')
        self.assertEqual(self.urls('js_decline'), [HOME_URL])
        self.assertEqual(d['final_clicks'], [])
        self.assertIn('não autorizado', d['diagnostic'])
        self.assertNotEqual(d['state'], 'completa')

    # --- destinations that must never be opened
    def test_dangerous_foreign_or_other_course_destinations_are_never_requested(self):
        for name in ('assign', 'other_course', 'external'):
            with self.subTest(destination=name):
                d = self.data[name]
                self.assertEqual(self.urls(name), [HOME_URL])
                self.assertEqual(d['final_clicks'], [])
                self.assertEqual(d['nav']['method'], 'blocked')
                self.assertIn('bloqueado', d['diagnostic'])
                self.assertNotEqual(d['state'], 'completa')

    def test_unknown_route_and_extra_parameters_ask_before_any_navigation(self):
        for name in ('unknown', 'extra'):
            with self.subTest(destination=name):
                d = self.data[name]
                self.assertEqual(d['outcome'], 'question')
                self.assertEqual(self.urls(name), [HOME_URL])
                self.assertEqual(d['clicks_after_question'], [])

    # --- failures
    def test_session_lost_on_the_destination_stops_the_run(self):
        d = self.data['expired']
        self.assertEqual(d['outcome'], 'login')
        self.assertEqual(self.urls('expired'), [HOME_URL, DEST_URL])
        self.assertFalse(d['closed'])

    def test_navigation_timeout_is_explained_and_the_browser_is_kept(self):
        d = self.data['timeout']
        self.assertTrue(d['outcome'].startswith('rejected:Tempo esgotado'), d['outcome'])
        self.assertFalse(d['closed'])
        self.assertEqual(self.urls('timeout'), [HOME_URL, DEST_URL])

    def test_cancel_after_arriving_keeps_the_browser_and_navigates_no_further(self):
        d = self.data['cancel']
        self.assertTrue(d['outcome'].startswith('rejected:Análise cancelada'), d['outcome'])
        self.assertFalse(d['closed'])
        self.assertEqual(self.urls('cancel'), [HOME_URL, DEST_URL])
        self.assertEqual(d['url'], DEST_URL)

    # --- inspection (structure only)
    def test_inspection_mode_reports_structure_and_navigates_nowhere(self):
        d = self.data['inspect']
        self.assertEqual(self.urls('inspect'), [HOME_URL])
        self.assertEqual(d['final_clicks'], [])
        self.assertEqual(d['state'], 'nao_validada')
        text = d['diagnostic']
        for fragment in ('Modo de inspeção', 'cartões 5', 'link 4', 'onclick-url 1', 'href=sim', 'alvo Atividades Avaliativas via link',
                         '/ava/course/view.php?id&section', 'navegaria (link validado)'):
            self.assertIn(fragment, text)
        for private in ('section=', 'sesskey', 'id=42', 'http', '?id=42'):
            self.assertNotIn(private, text)
        rows = d['nav']['cards']
        target = next(c for c in rows if c['role'] == 'target')
        self.assertEqual((target['tag'], target['kind'], target['has_href'], target['host']),
                         ('a', 'link', True, 'ead.aedb.br'))


if __name__ == '__main__':
    unittest.main()

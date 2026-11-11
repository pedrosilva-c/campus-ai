"""Companion in local Chromium (opt-in: CAMPUS_AI_BROWSER_SMOKE=1). No real site, no credentials.

* DomScenarioTests: dom_tiles.js runs in a real Chromium on synthetic pages served from memory under the
  AEDB addresses (every other request is aborted), in both ways a format-tiles section is shown: its own
  page (section.php) and a panel opened inside the course home (view.php, URL unchanged), plus the
  dangerous variants (panel closed, other section open, two panels, unrelated dialog, panel in a modal,
  panel without attribute link, ambiguous tile). The projections are then fed to the REAL preview logic
  (companion/src/preview.js, via Node) so the decision shown to the student is tested end to end.
* LoadedExtensionTests: the unpacked extension is loaded in a real Chromium and its popup page is opened.
  What this proves: the manifest and CSP are accepted, the popup renders, the extension has no storage,
  cookies or Native Messaging API, the CSP blocks the network, hostile text is rendered as text, and
  without the user's toolbar click the extension cannot even see the tab address (it fails closed).
  What it cannot prove: the activeTab grant itself, which only a real click on the toolbar icon gives,
  nor the real markup of the AEDB panel, which was not observed.
"""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / 'companion'
FIXTURES = ROOT / 'tests' / 'fixtures' / 'companion'
SECTION_URL = 'https://ead.aedb.br/ava/course/section.php?id=4242'
HOME_URL = 'https://ead.aedb.br/ava/course/view.php?id=7653'
NODE = shutil.which('node')
OPT_IN = unittest.skipUnless(os.environ.get('CAMPUS_AI_BROWSER_SMOKE') == '1',
                             'Chromium local opt-in: CAMPUS_AI_BROWSER_SMOKE=1')


def scratch():
    path = ROOT / '.tmp-campus-ai'
    path.mkdir(exist_ok=True)
    return path


def run_chromium(code, *args):
    with tempfile.TemporaryDirectory(dir=scratch()) as profile:
        proc = subprocess.run([sys.executable, '-c', code, profile, *map(str, args)], capture_output=True,
                              text=True, encoding='utf-8', timeout=180, cwd=ROOT,
                              env=dict(os.environ, PLAYWRIGHT_BROWSERS_PATH='0'))
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def extension_id():
    der = base64.b64decode(json.loads((EXT / 'manifest.json').read_text('utf-8'))['key'])
    return ''.join(chr(ord('a') + int(c, 16)) for c in hashlib.sha256(der).hexdigest()[:32])


# --- Scenarios (DOM changes applied to the synthetic home before the extension reads it) ----------------
OPEN = "document.getElementById('section-3').classList.add('aberta');"
CLONE = ("{ const c = document.getElementById('section-3').cloneNode(true); c.removeAttribute('id');"
         " document.getElementById('sections').append(c); }")
IN_MODAL = ("{ const m = document.createElement('div'); m.className = 'modal show'; m.setAttribute('role', 'dialog');"
            " m.setAttribute('aria-modal', 'true'); m.setAttribute('data-section', '3');"
            " m.append(...document.getElementById('section-3').childNodes); document.body.append(m);"
            " document.getElementById('region-main').setAttribute('aria-hidden', 'true'); }")
UNLINKED = OPEN + ("{ const s = document.getElementById('section-3'); s.removeAttribute('data-section');"
                   " s.removeAttribute('id'); }")
TWO_TILES = OPEN + ("{ const t = document.getElementById('tile-3').cloneNode(true); t.id = 'tile-3b';"
                    " document.getElementById('multi_section_tiles').append(t); }")
SHOW_PREF = ("{ const m = document.getElementById('preferencia-dados'); m.classList.add('show');"
             " m.setAttribute('aria-hidden', 'false'); }")
SCENARIOS = {
    'secao_pagina': (SECTION_URL, 'tiles_section.html', ''),
    'inicio_sem_painel': (HOME_URL, 'tiles_home.html', ''),
    'painel_aberto': (HOME_URL, 'tiles_home.html', OPEN),
    'outra_secao_aberta': (HOME_URL, 'tiles_home.html', "document.getElementById('section-2').classList.add('aberta');"),
    'dois_paineis_um_visivel': (HOME_URL, 'tiles_home.html', CLONE + OPEN),
    'dois_paineis_visiveis': (HOME_URL, 'tiles_home.html', OPEN + CLONE),
    'dialogo_alheio_aberto': (HOME_URL, 'tiles_home.html', OPEN + "document.getElementById('dialogo-alheio').classList.add('show');"),
    'painel_em_modal': (HOME_URL, 'tiles_home.html', IN_MODAL),
    'painel_sem_vinculo': (HOME_URL, 'tiles_home.html', UNLINKED),
    'cartao_ambiguo': (HOME_URL, 'tiles_home.html', TWO_TILES),
    # v0.5.2: the "Preferência dos dados" window over the open panel, and an unknown dialog without any panel
    'preferencia_aberta': (HOME_URL, 'tiles_home.html', OPEN + SHOW_PREF),
    'dialogo_sem_painel': (HOME_URL, 'tiles_home.html', "document.getElementById('dialogo-alheio').classList.add('show');"),
}
# What the student must see for each scenario: (state, message key, rows).
EXPECTED = {
    'secao_pagina': ('ok', '', 7),
    'inicio_sem_painel': ('recusado', 'painel_fechado', 0),
    'painel_aberto': ('ok', '', 7),
    'outra_secao_aberta': ('recusado', 'painel_fechado', 0),
    'dois_paineis_um_visivel': ('ok', '', 7),
    'dois_paineis_visiveis': ('recusado', 'paineis_multiplos', 0),
    'dialogo_alheio_aberto': ('recusado', 'dialogo_bloqueia', 0),
    'painel_em_modal': ('ok', '', 7),
    'painel_sem_vinculo': ('recusado', 'painel_sem_vinculo', 0),
    'cartao_ambiguo': ('recusado', 'tile_ambiguo', 0),
    'preferencia_aberta': ('recusado', 'dialogo_preferencia', 0),
    'dialogo_sem_painel': ('recusado', 'dialogo_bloqueia', 0),
}
PRIVATE = ('IGNORE TODAS', 'separador sintético', '(fundo)', 'armadilha', 'Oculto sintético', 'Recolhido sintético',
           'Estudante fictício', 'Evento sintético', 'Diálogo sintético', '66666', '88888', '91001', '92001', '94001',
           'Texto sintético da janela')

DOM_SCRIPT = r'''
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
profile, jobs_path, dom_js = sys.argv[1:4]
jobs = json.loads(Path(jobs_path).read_text(encoding='utf-8'))
dom_src = Path(dom_js).read_text(encoding='utf-8')
current, seen = {}, []
def handler(route):
    seen.append(route.request.url)
    if route.request.url == current.get('url'):
        route.fulfill(status=200, content_type='text/html; charset=utf-8', body=current['html'])
    else:
        route.abort()
READ = "(o) => ({ href: location.href, projection: CampusAiDomTiles.project(document, location, o) })"
with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(profile, headless=True, accept_downloads=False)
    try:
        context.route('**/*', handler)
        results = {}
        for job in jobs:
            current.update(url=job['url'], html=Path(job['html']).read_text(encoding='utf-8'))
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(job['url'])
            if job['mutate']:
                page.evaluate(job['mutate'])
            page.add_script_tag(content=dom_src)
            page.add_script_tag(content=dom_src)     # a second click injects it again: must be harmless
            before = page.evaluate('document.documentElement.outerHTML')
            label = 'Atividades Avaliativas'
            identity = page.evaluate(READ, {'withEntries': False, 'sectionLabel': label})
            full = page.evaluate(READ, {'withEntries': True, 'sectionLabel': label})
            results[job['name']] = {
                'url': job['url'], 'identity': identity, 'full': full,
                'unchanged': before == page.evaluate('document.documentElement.outerHTML'),
                'clicks': page.evaluate('window.__clicks'), 'url_after': page.url, 'errors': errors,
                'frozen': page.evaluate('Object.isFrozen(CampusAiDomTiles)'),
            }
            page.close()
        print(json.dumps({'results': results, 'requests': seen}))
    finally:
        context.close()
'''


@OPT_IN
@unittest.skipUnless(NODE, 'Node.js não encontrado')
class DomScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        jobs = [{'name': name, 'url': url, 'html': str(FIXTURES / html), 'mutate': mutate}
                for name, (url, html, mutate) in SCENARIOS.items()]
        with tempfile.TemporaryDirectory(dir=scratch()) as tmp:
            jobs_path = Path(tmp) / 'jobs.json'
            jobs_path.write_text(json.dumps(jobs), encoding='utf-8')
            out = run_chromium(DOM_SCRIPT, jobs_path, EXT / 'src' / 'dom_tiles.js')
            cls.results, cls.requests = out['results'], out['requests']
            replay = {name: {'url': r['url'], 'identity': r['identity'], 'full': r['full']} for name, r in cls.results.items()}
            replay_path = Path(tmp) / 'replay.json'
            replay_path.write_text(json.dumps(replay), encoding='utf-8')
            proc = subprocess.run([NODE, str(EXT / 'test' / 'emit_preview.mjs'), str(replay_path)], capture_output=True,
                                  text=True, encoding='utf-8', timeout=60, cwd=ROOT)
        assert proc.returncode == 0, proc.stderr[-3000:]
        cls.models = json.loads(proc.stdout)
        cls.golden = json.loads((FIXTURES / 'tiles_projection.json').read_text(encoding='utf-8'))

    def test_what_the_student_sees_in_each_scenario(self):
        for name, (state, key, rows) in EXPECTED.items():
            model = self.models[name]
            self.assertEqual((model['state'], model['messageKey'], len(model['rows'])), (state, key, rows), name)
            if state == 'ok':
                self.assertEqual(model['issues'], 0, name)
                self.assertEqual(model['labels'], 3, name)
                self.assertTrue(model['matches'], name)
                self.assertNotEqual(model['coverage']['state'], 'completa', name)

    def test_both_ways_of_showing_the_section_give_the_same_seven_modules(self):
        expected = [[e['cmid'], e['modtype']] for e in self.golden['entries'] if not e.get('label')]
        for name in ('secao_pagina', 'painel_aberto', 'dois_paineis_um_visivel', 'painel_em_modal'):
            self.assertEqual([[r[0], r[1]] for r in self.models[name]['rows']], expected, name)
        self.assertEqual(self.models['secao_pagina']['mode'], 'secao_pagina')
        self.assertEqual(self.models['painel_aberto']['mode'], 'painel')
        self.assertEqual(self.results['secao_pagina']['full']['projection'], self.golden)
        self.assertEqual(self.results['painel_aberto']['full']['projection']['entries'], self.golden['entries'])

    def test_panel_reads_only_rendered_items_of_the_linked_panel(self):
        diag = self.results['painel_aberto']['full']['projection']['diagnostic']
        self.assertEqual((diag['tiles'], diag['tilesMatched'], diag['candidates'], diag['visibleCandidates']), (5, 1, 1, 1))
        self.assertEqual(diag['hiddenActivities'], 2)          # the hidden and the collapsed item
        self.assertEqual(diag['visibleActivitiesOutside'], 0)
        self.assertIn('2 item(ns) oculto(s) na seção não foram lidos.', self.models['painel_aberto']['coverage']['reasons'])

    def test_the_diagnostic_tells_dialogs_and_section_apart_and_agrees_with_the_reason(self):
        keys = ('reason', 'sectionVisible', 'openDialogs', 'dataPreferenceDialogs', 'unknownDialogs', 'hiddenDialogs')
        expected = {                                   # the home has 2 dialogs: one unrelated, the preference window
            'painel_aberto': ('', 1, 0, 0, 0, 2),                      # hidden dialogs never block
            'inicio_sem_painel': ('painel_fechado', 0, 0, 0, 0, 2),    # section not identified
            'preferencia_aberta': ('dialogo_preferencia', 1, 1, 1, 0, 1),   # window recognised, section behind it
            'dialogo_alheio_aberto': ('dialogo_bloqueia', 1, 1, 0, 1, 1),   # unknown dialog
            'dialogo_sem_painel': ('dialogo_bloqueia', 0, 1, 0, 1, 1),      # unknown dialog, no section: says so
            'painel_em_modal': ('', 1, 1, 0, 0, 2),                    # the panel's own dialog is not "another" one
        }
        for name, values in expected.items():
            diag = self.results[name]['full']['projection']['diagnostic']
            self.assertEqual(tuple(diag[k] for k in keys), values, name)
            self.assertEqual(tuple(self.models[name]['diagnostic'][k] for k in keys), values, name)   # survives cleaning

    def test_identity_reads_carry_no_item_data(self):
        for name, result in self.results.items():
            self.assertEqual(result['identity']['projection']['entries'], [], name)
            identity, full = result['identity']['projection'], result['full']['projection']
            self.assertEqual({k: v for k, v in identity.items() if k != 'entries'},
                             {k: v for k, v in full.items() if k != 'entries'}, name)

    def test_refused_scenarios_read_no_item_and_explain_the_structure(self):
        for name, (state, _key, _rows) in EXPECTED.items():
            if state == 'ok':
                continue
            self.assertEqual(self.results[name]['full']['projection']['entries'], [], name)
            self.assertIsNotNone(self.models[name]['diagnostic'], name)
        other = self.models['outra_secao_aberta']['diagnostic']['containers']
        self.assertEqual(len(other), 1)
        self.assertEqual(other[0]['activities'], 2)
        self.assertIn('data-section', other[0]['attrs'])

    def test_page_is_left_untouched_and_nothing_is_clicked(self):
        for name, result in self.results.items():
            self.assertTrue(result['unchanged'], name)
            self.assertEqual(result['clicks'], [], name)
            self.assertEqual(result['url_after'], result['url'], name)
            self.assertTrue(result['frozen'], name)
            self.assertEqual(result['errors'], [], name)          # the second injection did not throw

    def test_background_modules_labels_index_and_dialogs_are_never_read(self):
        dumped = json.dumps(self.results, ensure_ascii=False) + json.dumps(self.models, ensure_ascii=False)
        for private in PRIVATE:
            self.assertNotIn(private, dumped)

    def test_no_request_left_the_fictitious_host(self):
        self.assertLessEqual(set(self.requests), {SECTION_URL, HOME_URL, 'https://ead.aedb.br/favicon.ico'})


EXTENSION_SCRIPT = r'''
import json, sys
from playwright.sync_api import sync_playwright
profile, ext_dir, ext_id = sys.argv[1:4]
HOSTILE = '<img src=x onerror="window.__pwn=1"><script>window.__pwn=2</script>'
with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        profile, channel='chromium', headless=True,
        args=[f'--disable-extensions-except={ext_dir}', f'--load-extension={ext_dir}'])
    try:
        page = context.new_page()
        page.goto(f'chrome-extension://{ext_id}/src/popup.html')
        out = {'title': page.title(), 'url': page.url}
        out['api'] = page.evaluate("""() => ({
            id: chrome.runtime.id, tabs: typeof chrome.tabs, scripting: typeof chrome.scripting,
            storage: typeof chrome.storage, cookies: typeof chrome.cookies, webRequest: typeof chrome.webRequest,
            connectNative: typeof chrome.runtime.connectNative,
            sendNativeMessage: typeof chrome.runtime.sendNativeMessage })""")
        page.click('#read')
        page.wait_for_selector('#result [role=alert]', timeout=10000)
        out['unclicked'] = {'text': page.inner_text('#result'), 'tables': page.locator('#result table').count(),
                            'worker': len(context.service_workers)}
        out['csp'] = page.evaluate("""() => new Promise((resolve) => {
            document.addEventListener('securitypolicyviolation', (e) => resolve(e.violatedDirective));
            fetch('https://ead.aedb.br/ava/x').catch(() => {});
            setTimeout(() => resolve('no-violation'), 2000); })""")
        out['hostile'] = page.evaluate("""async (evil) => {
            const { renderPreview } = await import('./render.js');
            const root = document.getElementById('result');
            const check = [{ id: 'dominio', label: evil, ok: true }];
            renderPreview(root, { state: 'ok', message: '', checks: check, section: evil, labels: 0,
              rows: [{ position: 1, cmid: evil, modtype: evil, kind: 'assign', classe: 'atividade', title: evil,
                       assessment: 'AV1', basis: 'titulo', hasUrl: false }],
              issues: [{ position: 2, code: 'sem_tipo', modtype: evil, cmid: evil }],
              byModtype: [{ modtype: evil, kind: 'assign', label: evil, classe: 'atividade', count: 1 }],
              comparison: { reference: { date: evil, total: 7, byKind: { assign: 5 } }, found: { total: 1, byKind: {} },
                            matches: false, differences: [{ kind: 'assign', label: evil, expected: 5, found: 1 }],
                            notes: [evil] },
              coverage: { state: 'parcial', reasons: [evil] } });
            await new Promise((r) => setTimeout(r, 300));
            return { injected: root.querySelectorAll('img, script, iframe').length, pwn: window.__pwn === undefined,
                     literal: root.textContent.includes(evil), tables: root.querySelectorAll('table').length };
        }""", HOSTILE)
        out['hostile_sync'] = page.evaluate("""async (evil) => {
            const { renderSyncOutcome } = await import('./render.js');
            const progress = document.getElementById('progress');
            const result = document.getElementById('result');
            renderSyncOutcome(progress, result, { state: 'lido_nao_salvo', message: evil, model: null,
              steps: [{ id: 'x', label: evil, status: 'falhou', note: evil }], saved: { saved: false, code: evil } }, {});
            await new Promise((r) => setTimeout(r, 300));
            return { injected: progress.querySelectorAll('img, script, iframe').length, pwn: window.__pwn === undefined,
                     literal: progress.textContent.includes(evil), buttons: document.querySelectorAll('#sync, #read, #cancel').length };
        }""", HOSTILE)
        # Never exercise the save path where a REAL host may be registered: the test would reach it and write
        # a failure row into the user's real live.db (it did once). Only the preview build (no nativeMessaging,
        # so no native port exists) is exercised.
        out['save'] = page.evaluate("""async () => {
            if (typeof chrome.runtime.connectNative === 'function') return null;
            const { saveSnapshot } = await import('./save.js');
            return saveSnapshot(chrome, { kind: 'curso_inicio', route: '/ava/course/view.php?id' },
                                { schema: 'campus-ai.academic/1' }, { timeoutMs: 8000 });
        }""")
        print(json.dumps(out))
    finally:
        context.close()
'''



@OPT_IN
class LoadedExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.id = extension_id()
        cls.out = run_chromium(EXTENSION_SCRIPT, EXT, cls.id)

    def test_manifest_is_accepted_and_the_stable_id_matches_the_key(self):
        self.assertEqual(self.out['title'], 'Campus AI Companion')
        self.assertEqual(self.out['api']['id'], self.id)

    def test_extension_has_no_storage_cookies_or_native_messaging(self):
        api = self.out['api']
        self.assertEqual((api['tabs'], api['scripting']), ('object', 'object'))
        for name in ('storage', 'cookies', 'webRequest', 'connectNative', 'sendNativeMessage'):
            self.assertEqual(api[name], 'undefined', name)

    def test_without_the_toolbar_click_the_extension_fails_closed(self):
        result = self.out['unclicked']
        self.assertEqual(result['tables'], 0)
        self.assertIn('não tem acesso a esta aba', result['text'])
        self.assertIn('Não avaliado', result['text'])
        self.assertEqual(result['worker'], 0)               # no background worker at all

    def test_the_csp_blocks_every_network_request(self):
        self.assertEqual(self.out['csp'], 'connect-src')

    def test_hostile_page_text_is_rendered_as_text(self):
        hostile = self.out['hostile']
        self.assertEqual(hostile['injected'], 0)
        self.assertTrue(hostile['pwn'])
        self.assertTrue(hostile['literal'])
        self.assertGreaterEqual(hostile['tables'], 3)

    def test_hostile_text_in_the_progress_and_outcome_is_rendered_as_text(self):
        hostile = self.out['hostile_sync']
        self.assertEqual(hostile['injected'], 0)
        self.assertTrue(hostile['pwn'] and hostile['literal'])
        self.assertEqual(hostile['buttons'], 3)                 # sync, manual read and cancel exist, nothing extra

    def test_preview_build_says_local_integration_is_unavailable(self):
        self.assertEqual(self.out['save'], {'saved': False, 'code': 'indisponivel_nesta_versao'})


@OPT_IN
class IntegrationBuildTests(unittest.TestCase):
    """The integration build (preview + nativeMessaging) in a real Chromium, with NO host registered."""

    @classmethod
    def setUpClass(cls):
        from campus_ai.companion_build import build
        cls.tmp = tempfile.TemporaryDirectory(dir=scratch())
        cls.dest = build(Path(cls.tmp.name) / 'companion-integracao')
        cls.out = run_chromium(EXTENSION_SCRIPT, cls.dest, extension_id())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_same_id_and_native_messaging_is_the_only_addition(self):
        api = self.out['api']
        self.assertEqual(api['id'], extension_id())
        self.assertEqual(api['connectNative'], 'function')
        for name in ('storage', 'cookies', 'webRequest'):
            self.assertEqual(api[name], 'undefined', name)
        self.assertEqual(self.out['csp'], 'connect-src')

    def test_the_save_path_is_never_exercised_against_a_possibly_registered_host(self):
        self.assertIsNone(self.out['save'])      # the outcomes are covered with a fake port in save.test.mjs


if __name__ == '__main__':
    unittest.main()

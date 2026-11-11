"""'Sincronizar disciplina' end to end in a real Chromium, on FICTITIOUS pages served from memory.

The page is the synthetic course home (tests/fixtures/companion/tiles_home.html) plus a stand-in for the Tiles
click behaviour. The REAL extension modules (sync.js, preview.js, open_panel.js, dom_tiles.js, save.js,
classify.js, tiles_adapter.js) are served under a fake path of the fake host and run INSIDE the page, with a thin
shim for the two Chrome calls they use and a fake native port that answers like the host. Every other request is
aborted. No real site, no real host, no database: nothing outside this temporary browser is touched.

What it cannot show: the activeTab grant itself, the real Tiles plugin and the real AEDB markup.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT_SRC = ROOT / 'companion' / 'src'
FIXTURES = ROOT / 'tests' / 'fixtures' / 'companion'
HOME = 'https://ead.aedb.br/ava/course/view.php?id=7653'
SECTION = 'https://ead.aedb.br/ava/course/section.php?id=4242'
OPT_IN = unittest.skipUnless(os.environ.get('CAMPUS_AI_BROWSER_SMOKE') == '1',
                             'Chromium local opt-in: CAMPUS_AI_BROWSER_SMOKE=1')

OPEN = "document.getElementById('section-3').classList.add('aberta');"
UNLINKED = "document.getElementById('tilelink-3').setAttribute('href', '/ava/course/section.php?id=9999');"
BLANK = "document.getElementById('tilelink-3').setAttribute('target', '_blank');"
DANGEROUS = ("{ const l = document.getElementById('tilelink-3'); l.setAttribute('aria-label', 'Atividades Avaliativas — Enviar');"
             " document.getElementById('tile-3').append(' Enviar'); }")
HIDDEN = "document.getElementById('tile-3').style.display = 'none';"
NOT_CLICKABLE = "document.getElementById('tile-3').classList.remove('tile-clickable');"
OFFSITE = "document.getElementById('tilelink-3').setAttribute('href', 'https://example.org/ava/course/section.php?id=4242');"
TWO_TILES = ("{ const t = document.getElementById('tile-3').cloneNode(true); t.id = 'tile-3b';"
             " document.getElementById('multi_section_tiles').append(t); }")
OTHER_COURSE = "document.body.className = document.body.className.replace('course-7653', 'course-9999');"
NO_TILES = "document.body.classList.remove('format-tiles');"
# v0.5.2: the "Preferência dos dados" window (fixture hypothesis of Moodle's modal) and look-alikes that must NOT be closed.
SHOW_PREF = 'window.__showPref();'
OTHER_DIALOG = "document.getElementById('dialogo-alheio').classList.add('show');"
PREF_EXTRA_BUTTON = ("{ const b = document.createElement('button'); b.type = 'button'; b.dataset.pref = 'outro'; b.textContent = 'Mais opções';"
                     " document.querySelector('#preferencia-dados .modal-footer').append(b); }")
PREF_OTHER_TITLE = "document.getElementById('preferencia-dados-titulo').textContent = 'Preferências de notificação';"
PREF_X_IN_BODY = ("document.querySelector('#preferencia-dados .modal-body')"
                  ".append(document.querySelector('#preferencia-dados [data-pref=\"x\"]'));")
PREF_WITH_LINK = ("{ const a = document.createElement('a'); a.href = '/ava/user/preferences.php'; a.textContent = 'detalhes';"
                  " document.querySelector('#preferencia-dados .modal-body').append(a); }")

# name: (page url, html fixture, click-behaviour variant, mutation, expected state, expected message key or '')
SCENARIOS = {
    'fechado_abre': (HOME, 'tiles_home.html', 'ok', '', 'salvo', ''),
    'fechado_abre_devagar': (HOME, 'tiles_home.html', 'slow', '', 'salvo', ''),
    'ja_aberto': (HOME, 'tiles_home.html', 'ok', OPEN, 'salvo', ''),
    'pagina_da_secao': (SECTION, 'tiles_section.html', 'ok', '', 'salvo', ''),
    'nunca_abre': (HOME, 'tiles_home.html', 'never', '', 'recusado', 'painel_nao_abriu'),
    'abre_outro_painel': (HOME, 'tiles_home.html', 'wrong_panel', '', 'recusado', 'painel_nao_abriu'),
    'dois_paineis': (HOME, 'tiles_home.html', 'two_panels', '', 'recusado', 'paineis_multiplos'),
    'dialogo_junto_do_painel': (HOME, 'tiles_home.html', 'dialog', '', 'recusado', 'dialogo_bloqueia'),
    # v0.5.2: dialogs are counted on every read, so an unknown dialog without the panel now says so (until v0.5.1 it
    # was reported as "o painel não apareceu" after the timeout while the counts showed no dialog)
    'dialogo_sem_painel': (HOME, 'tiles_home.html', 'dialog_only', '', 'recusado', 'dialogo_bloqueia'),
    'dialogo_ja_aberto': (HOME, 'tiles_home.html', 'ok', "document.getElementById('dialogo-alheio').classList.add('show');", 'recusado', 'dialogo_bloqueia'),
    'cartao_duplicado': (HOME, 'tiles_home.html', 'ok', TWO_TILES, 'recusado', 'tile_ambiguo'),
    'cartao_desvinculado': (HOME, 'tiles_home.html', 'ok', UNLINKED, 'recusado', 'tile_sem_vinculo'),
    'cartao_fora_do_dominio': (HOME, 'tiles_home.html', 'ok', OFFSITE, 'recusado', 'tile_sem_vinculo'),
    'cartao_nova_aba': (HOME, 'tiles_home.html', 'ok', BLANK, 'recusado', 'tile_perigoso'),
    'cartao_perigoso': (HOME, 'tiles_home.html', 'ok', DANGEROUS, 'recusado', 'tile_perigoso'),
    'cartao_oculto': (HOME, 'tiles_home.html', 'ok', HIDDEN, 'recusado', 'tile_oculto'),
    'cartao_nao_clicavel': (HOME, 'tiles_home.html', 'ok', NOT_CLICKABLE, 'recusado', 'tile_nao_clicavel'),
    'outra_disciplina': (HOME, 'tiles_home.html', 'ok', OTHER_COURSE, 'recusado', 'curso_diferente'),
    'sem_tiles': (HOME, 'tiles_home.html', 'ok', NO_TILES, 'recusado', 'formato'),
    # --- v0.5.2: "Preferência dos dados" ---
    'pref_apos_clique': (HOME, 'tiles_home.html', 'pref', '', 'salvo', ''),
    'pref_com_painel_aberto': (HOME, 'tiles_home.html', 'ok', OPEN + SHOW_PREF, 'salvo', ''),
    'pref_antes_do_clique': (HOME, 'tiles_home.html', 'ok', SHOW_PREF, 'salvo', ''),
    'pref_salvar_manual': (HOME, 'tiles_home.html', 'pref', '', 'lido', 'lido'),
    'pref_fecha_e_some_a_secao': (HOME, 'tiles_home.html', 'pref_closes_panel', '', 'recusado', 'secao_indisponivel'),
    'pref_nao_fecha': (HOME, 'tiles_home.html', 'pref_sticky', '', 'recusado', 'dialogo_nao_fechou'),
    'pref_reaparece': (HOME, 'tiles_home.html', 'pref_reappears', '', 'recusado', 'dialogo_reapareceu'),
    'pref_botao_extra': (HOME, 'tiles_home.html', 'pref', PREF_EXTRA_BUTTON, 'recusado', 'dialogo_bloqueia'),
    'pref_outro_titulo': (HOME, 'tiles_home.html', 'pref', PREF_OTHER_TITLE, 'recusado', 'dialogo_bloqueia'),
    'pref_x_fora_do_cabecalho': (HOME, 'tiles_home.html', 'pref', PREF_X_IN_BODY, 'recusado', 'dialogo_bloqueia'),
    'pref_com_link': (HOME, 'tiles_home.html', 'pref', PREF_WITH_LINK, 'recusado', 'dialogo_bloqueia'),
    'pref_e_outro_dialogo': (HOME, 'tiles_home.html', 'ok', OPEN + SHOW_PREF + OTHER_DIALOG, 'recusado', 'dialogo_bloqueia'),
}
CLICKED_ONCE = {'fechado_abre', 'fechado_abre_devagar', 'nunca_abre', 'abre_outro_painel', 'dois_paineis',
                'dialogo_junto_do_painel', 'dialogo_sem_painel', 'pref_botao_extra', 'pref_outro_titulo',
                'pref_x_fora_do_cabecalho', 'pref_com_link'}
# Exact page interactions of the "Preferência dos dados" scenarios, in order ("pref:x" = its X).
CLICKS = {
    'pref_apos_clique': ['tile:3', 'pref:x'], 'pref_com_painel_aberto': ['pref:x'], 'pref_antes_do_clique': ['pref:x', 'tile:3'],
    'pref_salvar_manual': ['tile:3', 'pref:x'], 'pref_fecha_e_some_a_secao': ['tile:3', 'pref:x'],
    'pref_nao_fecha': ['tile:3', 'pref:x'], 'pref_reaparece': ['tile:3', 'pref:x', 'pref:x'], 'pref_e_outro_dialogo': [],
}
MANUAL = {'pref_salvar_manual'}                      # runs like the popup: autoSave false
SHORT = {'nunca_abre', 'abre_outro_painel', 'dialogo_sem_painel', 'pref_fecha_e_some_a_secao', 'pref_nao_fecha'}
FORBIDDEN_CLICKS = ('concluir-90001', 'enviar-90005', 'baixar-90004', 'pref:sim', 'pref:cancelar', 'pref:outro')

SCRIPT = r'''
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
profile, jobs_path, src_dir, fixtures_dir = sys.argv[1:5]
jobs = json.loads(Path(jobs_path).read_text(encoding='utf-8'))
SRC, FIX = Path(src_dir), Path(fixtures_dir)
BEHAVIOR = (FIX / 'tiles_live_behavior.js').read_text(encoding='utf-8')
ALLOWED = {p.name for p in SRC.glob('*.js')}
current, seen = {}, []

def handler(route):
    url = route.request.url
    seen.append(url)
    if url == current.get('url'):
        html = (FIX / current['html']).read_text(encoding='utf-8').replace('</body>', '<script>' + BEHAVIOR + '</script></body>')
        route.fulfill(status=200, content_type='text/html; charset=utf-8', body=html)
    elif url.startswith('https://ead.aedb.br/__ext/src/') and url.rsplit('/', 1)[1] in ALLOWED:
        route.fulfill(status=200, content_type='application/javascript', body=(SRC / url.rsplit('/', 1)[1]).read_text(encoding='utf-8'))
    else:
        route.abort()

RUN = """async (cfg) => {
  const { runSync } = await import('/__ext/src/sync.js');
  const sent = [];
  const port = () => {
    const listeners = { m: [], d: [] };
    return {
      onMessage: { addListener: (f) => listeners.m.push(f) }, onDisconnect: { addListener: (f) => listeners.d.push(f) },
      disconnect() {},
      postMessage(msg) {
        setTimeout(() => {
          const reply = (body) => listeners.m.forEach((f) => f({ protocol: 'campus-ai.companion/1', request_id: msg.request_id, ...body }));
          if (msg.type === 'hello') reply({ type: 'welcome', session: 'a'.repeat(32) });
          else {
            sent.push({ page: msg.payload.page, ids: [...msg.payload.snapshot.materials, ...msg.payload.snapshot.activities].map((r) => r.uid),
                        coverage: msg.payload.snapshot.coverage.state, routes: [...new Set(msg.payload.snapshot.activities.map((a) => a.provenance.route))] });
            reply({ type: 'ack', saved: true, result: { run: 4, itens: 7, novos: 0, alterados: 0, ausentes: 0, reaparecidos: 0, inalterados: 7 } });
          }
        }, 0);
      },
    };
  };
  const api = {
    tabs: { query: async () => [{ id: 1, url: location.href }] },
    scripting: { executeScript: async (o) => {
      if (o.files) { for (const f of o.files) await import('/__ext/' + f); return [{}]; }
      return [{ result: o.func(...(o.args || [])) }];
    } },
    runtime: { connectNative: () => port(), lastError: null },
  };
  const { SYNC_MESSAGES } = await import('/__ext/src/sync.js');
  const { MESSAGES } = await import('/__ext/src/preview.js');
  const started = performance.now();
  const outcome = await runSync(api, { timeoutMs: cfg.timeoutMs, pollMs: 100, settleMs: 450, autoSave: cfg.autoSave });
  return {
    state: outcome.state, message: outcome.message, steps: outcome.steps.map((s) => s.id + ':' + s.status),
    dialogsClosed: outcome.dialogsClosed,
    savedFlag: outcome.saved ? outcome.saved.saved : null, rows: outcome.model && outcome.model.rows ? outcome.model.rows.length : 0,
    issues: outcome.model && outcome.model.issues ? outcome.model.issues.length : 0, sent,
    elapsedMs: Math.round(performance.now() - started), messages: { ...MESSAGES, ...SYNC_MESSAGES },
  };
}"""

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(profile, headless=True, accept_downloads=False)
    try:
        context.route('**/*', handler)
        results = {}
        for job in jobs:
            current.update(url=job['url'], html=job['html'])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.add_init_script('window.__variant = ' + json.dumps(job['variant']))
            page.goto(job['url'])
            if job['mutate']:
                page.evaluate(job['mutate'])
            before_url = page.url
            outcome = page.evaluate(RUN, {'timeoutMs': 2500 if job['short'] else 8000, 'autoSave': job['autoSave']})
            outcome.update(clicks=page.evaluate('window.__clicks'), url_after=page.url, url_before=before_url, errors=errors)
            results[job['name']] = outcome
            page.close()
        print(json.dumps({'results': results, 'requests': seen}))
    finally:
        context.close()
'''


@OPT_IN
class SyncInChromiumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        jobs = [{'name': name, 'url': url, 'html': html, 'variant': variant, 'mutate': mutate, 'short': name in SHORT,
                 'autoSave': name not in MANUAL}
                for name, (url, html, variant, mutate, _state, _key) in SCENARIOS.items()]
        scratch = ROOT / '.tmp-campus-ai'
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as tmp:
            jobs_path = Path(tmp) / 'jobs.json'
            jobs_path.write_text(json.dumps(jobs), encoding='utf-8')
            proc = subprocess.run([sys.executable, '-c', SCRIPT, str(Path(tmp) / 'profile'), str(jobs_path), str(EXT_SRC),
                                   str(FIXTURES)], capture_output=True, text=True, encoding='utf-8', timeout=300,
                                  cwd=ROOT, env=dict(os.environ, PLAYWRIGHT_BROWSERS_PATH='0'))
        assert proc.returncode == 0, proc.stderr[-3000:]
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        cls.results, cls.requests = out['results'], out['requests']

    def test_each_scenario_ends_as_expected(self):
        for name, (_u, _h, _v, _m, state, key) in SCENARIOS.items():
            r = self.results[name]
            self.assertEqual(r['state'], state, f"{name}: {r['message']}")
            if key:                                                       # the exact text the student would read
                self.assertEqual(r['message'], r['messages'][key], name)
            else:
                self.assertEqual(r['message'], 'Sincronizado e salvo no Campus AI.', name)

    def test_one_click_saves_the_seven_modules_whether_the_panel_is_closed_open_or_a_page(self):
        for name in ('fechado_abre', 'fechado_abre_devagar', 'ja_aberto', 'pagina_da_secao'):
            r = self.results[name]
            self.assertEqual((r['state'], r['savedFlag'], r['rows'], r['issues']), ('salvo', True, 7, 0), name)
            self.assertEqual(len(r['sent']), 1, name)                     # exactly one report to the host
            self.assertEqual(len(r['sent'][0]['ids']), 7, name)           # never a partial panel
            self.assertEqual(sorted(r['sent'][0]['ids']), [f'moodle:course:7653:module:9000{i}' for i in range(1, 8)])
            self.assertEqual(r['sent'][0]['coverage'], 'parcial', name)
            self.assertTrue(all(step.endswith(('ok', 'pulado')) for step in r['steps']), (name, r['steps']))
        self.assertEqual(self.results['fechado_abre']['steps'],
                         ['verificar:ok', 'abrir:ok', 'fechar:pulado', 'aguardar:ok', 'ler:ok', 'detalhar:pulado', 'salvar:ok'])
        self.assertEqual(self.results['ja_aberto']['steps'],
                         ['verificar:ok', 'abrir:pulado', 'fechar:pulado', 'aguardar:pulado', 'ler:ok', 'detalhar:pulado', 'salvar:ok'])

    def test_the_tile_is_clicked_at_most_once_and_only_when_it_was_needed(self):
        for name, result in self.results.items():
            expected = CLICKS.get(name, ['tile:3'] if name in CLICKED_ONCE else [])
            self.assertEqual(result['clicks'], expected, name)
            self.assertLessEqual(result['clicks'].count('tile:3'), 1, name)       # never a second click on the tile

    def test_the_preference_window_is_closed_by_its_x_and_the_seven_modules_are_read(self):
        for name in ('pref_apos_clique', 'pref_com_painel_aberto', 'pref_antes_do_clique'):
            r = self.results[name]
            self.assertEqual((r['state'], r['savedFlag'], r['rows'], r['issues'], r['dialogsClosed']), ('salvo', True, 7, 0, 1), name)
            self.assertEqual(sorted(r['sent'][0]['ids']), [f'moodle:course:7653:module:9000{i}' for i in range(1, 8)], name)
            self.assertIn('fechar:ok', r['steps'], name)
        self.assertEqual(self.results['pref_apos_clique']['steps'],
                         ['verificar:ok', 'abrir:ok', 'fechar:ok', 'aguardar:ok', 'ler:ok', 'detalhar:pulado', 'salvar:ok'])
        self.assertEqual(self.results['pref_com_painel_aberto']['steps'],
                         ['verificar:ok', 'abrir:pulado', 'fechar:ok', 'aguardar:pulado', 'ler:ok', 'detalhar:pulado', 'salvar:ok'])

    def test_sim_cancelar_and_look_alike_dialogs_are_never_clicked(self):
        for name, result in self.results.items():
            self.assertEqual([c for c in result['clicks'] if c.startswith('pref:') and c != 'pref:x'], [], name)
        for name in ('pref_botao_extra', 'pref_outro_titulo', 'pref_x_fora_do_cabecalho', 'pref_com_link', 'pref_e_outro_dialogo'):
            self.assertNotIn('pref:x', self.results[name]['clicks'], name)               # not recognised: left open
            self.assertEqual(self.results[name]['dialogsClosed'], 0, name)

    def test_the_popup_mode_reads_and_waits_for_the_save_button(self):
        r = self.results['pref_salvar_manual']
        self.assertEqual((r['state'], r['sent'], r['savedFlag'], r['rows'], r['dialogsClosed']), ('lido', [], None, 7, 1))
        self.assertEqual(r['steps'][-1], 'salvar:aguardando')

    def test_no_activity_completion_submission_or_download_control_is_ever_triggered(self):
        for name, result in self.results.items():
            for trap in FORBIDDEN_CLICKS:
                self.assertNotIn(trap, result['clicks'], name)
            self.assertEqual(result['url_after'], result['url_before'], name)    # nothing navigated, no link followed
            self.assertEqual(result['errors'], [], name)

    def test_the_slow_panel_is_read_only_after_it_finished_loading(self):
        slow = self.results['fechado_abre_devagar']
        self.assertEqual(len(slow['sent'][0]['ids']), 7)
        self.assertGreater(slow['elapsedMs'], 700)                    # it really waited for the batches (last at ~870 ms)

    def test_unsafe_or_ambiguous_situations_read_and_save_nothing(self):
        for name, (_u, _h, _v, _m, state, _key) in SCENARIOS.items():
            if state in ('salvo', 'lido'):
                continue
            r = self.results[name]
            self.assertEqual((r['sent'], r['savedFlag'], r['rows']), ([], None, 0), name)
            self.assertNotIn('salvar:ok', r['steps'], name)
            self.assertNotIn('Sincronizado', r['message'], name)

    def test_the_manual_page_kind_matches_the_real_page(self):
        self.assertEqual(self.results['fechado_abre']['sent'][0]['page']['kind'], 'curso_inicio')
        self.assertEqual(self.results['pagina_da_secao']['sent'][0]['page']['kind'], 'curso_bloco')

    def test_no_request_left_the_fictitious_host(self):
        extension_files = {f'https://ead.aedb.br/__ext/src/{p.name}' for p in EXT_SRC.glob('*.js')}
        allowed = {HOME, SECTION, 'https://ead.aedb.br/favicon.ico'} | extension_files
        self.assertLessEqual(set(self.requests), allowed)


if __name__ == '__main__':
    unittest.main()

"""'Sincronizar seções autorizadas' (experimental) in a real Chromium, on FICTITIOUS pages served from memory.

Same harness as test_companion_sync.py: the REAL extension modules run inside the synthetic course home, with a
stand-in for the Tiles click behaviour, a shim for the two Chrome calls and a fake native port. The demonstration
authorizes a SECOND fictitious section (Trilhas de Aprendizagem) through a test-only argument; the production
popup never passes it (static test), so in the real extension only Atividades Avaliativas is authorized.
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
BOTH = ['atividades avaliativas', 'trilhas de aprendizagem']
DUPLICATE = ("document.querySelector('#section-2 ul').append("
             "document.querySelector('#section-3 li[data-cmid=\"90001\"]').cloneNode(true));")
EXTERNAL = "document.getElementById('tilelink-2').setAttribute('href', 'https://example.org/trilhas');"

# name: (url, html, variant, mutation, authorized override or None, expected state, expected tile clicks)
SCENARIOS = {
    'producao': (HOME, 'tiles_home.html', 'ok', '', None, 'salvo', ['tile:3']),
    'duas_secoes': (HOME, 'tiles_home.html', 'ok', '', BOTH, 'salvo', ['tile:3', 'tile:2']),
    'trilhas_falha': (HOME, 'tiles_home.html', 'never_2', '', BOTH, 'parcial', ['tile:3', 'tile:2']),
    'modulo_repetido': (HOME, 'tiles_home.html', 'ok', DUPLICATE, BOTH, 'salvo', ['tile:3', 'tile:2']),
    'trilhas_link_externo': (HOME, 'tiles_home.html', 'ok', EXTERNAL, BOTH, 'salvo', ['tile:3']),
    'comeca_na_secao': (SECTION, 'tiles_section.html', 'ok', '', BOTH, 'recusado', []),
    'aa_recusada_modulo_repetido': (HOME, 'tiles_home.html', 'ok', DUPLICATE, BOTH, 'parcial', ['tile:3', 'tile:2']),
    # v0.5.3: read, never click "Salvar", close the page (= the popup closing)
    'leitura_sem_confirmar': (HOME, 'tiles_home.html', 'ok', '', BOTH, 'lido', ['tile:3', 'tile:2']),
    # v0.5.2 preserved in the course mode: the "Preferência dos dados" window shows up with Atividades Avaliativas
    'preferencia_na_leitura': (HOME, 'tiles_home.html', 'pref', '', BOTH, 'salvo', ['tile:3', 'pref:x', 'tile:2']),
}
# Scenarios whose save of a section is REFUSED by the fake app (the host answers `rejected`): nothing is written.
REJECT = {'aa_recusada_modulo_repetido': 'Atividades Avaliativas'}
NO_CONFIRM = {'leitura_sem_confirmar'}
AA_IDS = [f'moodle:course:7653:module:9000{i}' for i in range(1, 8)]
TR_IDS = ['moodle:course:7653:module:92001', 'moodle:course:7653:module:92002']

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
  const { runCourseSync, createCourseSaver } = await import('/__ext/src/course_sync.js');
  const sent = [];
  let run = 4;
  let connects = 0;
  const port = () => {
    connects += 1;
    const listeners = { m: [] };
    return {
      onMessage: { addListener: (f) => listeners.m.push(f) }, onDisconnect: { addListener: () => {} }, disconnect() {},
      postMessage(msg) {
        setTimeout(() => {
          const reply = (body) => listeners.m.forEach((f) => f({ protocol: 'campus-ai.companion/1', request_id: msg.request_id, ...body }));
          if (msg.type === 'hello') { reply({ type: 'welcome', session: 'a'.repeat(32) }); return; }
          const s = msg.payload.snapshot;
          const records = [...s.materials, ...s.activities];
          const refused = cfg.reject === s.sections[0].name;
          sent.push({ section: s.sections[0].uid, name: s.sections[0].name, ids: records.map((r) => r.uid).sort(),
                      owners: [...new Set(records.map((r) => r.section_uid))], reasons: s.coverage.reasons, saved: !refused });
          if (refused) { reply({ type: 'rejected', code: 'erro_ao_salvar' }); return; }
          run += 1;
          reply({ type: 'ack', saved: true, result: { run, itens: records.length, novos: 0, alterados: 0, ausentes: 0, reaparecidos: 0, inalterados: records.length } });
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
  const options = { syncOptions: { timeoutMs: cfg.timeoutMs, pollMs: 100, settleMs: 450 } };
  if (cfg.authorized) options.authorizedSections = cfg.authorized;
  const outcome = await runCourseSync(api, options);
  const connectsBeforeConfirm = connects;                    // must be 0: reading never opens a native port
  // The explicit click on "Salvar no Campus AI" (skipped for NO_CONFIRM scenarios).
  const notRead = outcome.sections.length - outcome.readings.length;
  const saved = cfg.confirm && outcome.readings.length ? await createCourseSaver(api, outcome.readings, { notRead })() : null;
  const sections = outcome.sections.map((s) => {
    const done = saved && saved.sections.find((x) => x.key === s.key);
    return [s.label, done ? done.state : s.state, s.rows, done ? done.omitted : 0];
  });
  return { state: saved ? saved.state : outcome.state, message: saved ? saved.message : outcome.message, sent,
    readState: outcome.state, readings: outcome.readings.length, connectsBeforeConfirm, connects,
    plan: outcome.plan ? outcome.plan.entries.map((e) => [e.label, e.decision]) : null,
    sections, coverage: outcome.coverage ? { ...outcome.coverage, salvas: saved ? saved.saved : 0 } : null };
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
            before = page.url
            out = page.evaluate(RUN, {'timeoutMs': 2500 if job['variant'].startswith('never') else 8000, 'authorized': job['authorized'],
                                      'reject': job['reject'], 'confirm': job['confirm']})
            out.update(clicks=page.evaluate('window.__clicks'), url_before=before, url_after=page.url, errors=errors)
            page.close()                                       # the popup closing: in-memory readings are gone
            out['closed'] = page.is_closed()
            results[job['name']] = out
        print(json.dumps({'results': results, 'requests': seen}))
    finally:
        context.close()
'''


@OPT_IN
class CourseSyncInChromiumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        jobs = [{'name': n, 'url': u, 'html': h, 'variant': v, 'mutate': m, 'authorized': a, 'reject': REJECT.get(n, ''),
                 'confirm': n not in NO_CONFIRM}
                for n, (u, h, v, m, a, _s, _c) in SCENARIOS.items()]
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

    def test_each_scenario_ends_as_expected_and_clicks_only_what_it_reads(self):
        for name, (_u, _h, _v, _m, _a, state, clicks) in SCENARIOS.items():
            r = self.results[name]
            self.assertEqual(r['state'], state, f"{name}: {r['message']} {r['sections']}")
            self.assertEqual(r['clicks'], clicks, name)                  # never tiles 1, 4, 5; never twice
            self.assertEqual(r['url_after'], r['url_before'], name)
            self.assertEqual(r['errors'], [], name)
            for trap in ('concluir-90001', 'enviar-90005', 'baixar-90004'):
                self.assertNotIn(trap, r['clicks'], name)

    def test_production_reads_only_atividades_avaliativas_and_lists_the_rest(self):
        r = self.results['producao']
        self.assertEqual(r['plan'], [['Informações da Disciplina', 'ignorada'], ['Trilhas de Aprendizagem', 'nao_autorizada'],
                                     ['Atividades Avaliativas', 'ler'], ['Feedback das Aulas', 'bloqueada'],
                                     ['Fale com o Professor', 'bloqueada']])
        self.assertEqual([s['ids'] for s in r['sent']], [AA_IDS])
        self.assertEqual(r['coverage']['naoAutorizadas'], ['Trilhas de Aprendizagem'])

    def test_two_fictitious_sections_are_saved_separately_with_their_origin(self):
        r = self.results['duas_secoes']
        self.assertEqual([(s['name'], s['ids']) for s in r['sent']],
                         [('Atividades Avaliativas', AA_IDS), ('Trilhas de Aprendizagem', TR_IDS)])
        for report in r['sent']:
            self.assertEqual(report['owners'], [report['section']])     # every module carries its own section
        self.assertEqual(r['sections'], [['Atividades Avaliativas', 'salvo', 7, 0], ['Trilhas de Aprendizagem', 'salvo', 2, 0]])
        self.assertEqual((r['coverage']['salvas'], r['coverage']['autorizadas'], r['coverage']['state']), (2, 2, 'parcial'))

    def test_partial_failure_saves_the_good_section_and_writes_nothing_for_the_failed_one(self):
        r = self.results['trilhas_falha']
        self.assertEqual([s['name'] for s in r['sent']], ['Atividades Avaliativas'])
        self.assertEqual(r['sections'][1][:3], ['Trilhas de Aprendizagem', 'recusado', 0])
        self.assertEqual(r['coverage']['salvas'], 1)

    def test_a_module_in_two_sections_is_saved_only_once(self):
        r = self.results['modulo_repetido']
        self.assertEqual(r['sent'][0]['ids'], AA_IDS)
        self.assertEqual(r['sent'][1]['ids'], TR_IDS)                    # 90001 left out of Trilhas
        self.assertEqual(r['sections'][1], ['Trilhas de Aprendizagem', 'salvo', 3, 1])
        self.assertTrue(any('já lido(s) em outra seção' in reason for reason in r['sent'][1]['reasons']))

    def test_a_refused_section_does_not_keep_a_shared_module_from_the_next_section(self):
        r = self.results['aa_recusada_modulo_repetido']
        self.assertEqual([(s['name'], s['saved']) for s in r['sent']],
                         [('Atividades Avaliativas', False), ('Trilhas de Aprendizagem', True)])
        self.assertEqual(r['sent'][0]['ids'], AA_IDS)                    # sent, refused: nothing written
        self.assertEqual(r['sent'][1]['ids'], sorted(TR_IDS + [AA_IDS[0]]))  # 90001 goes with Trilhas instead
        self.assertEqual(r['sent'][1]['owners'], [r['sent'][1]['section']])
        self.assertFalse(any('já lido(s) em outra seção' in reason for reason in r['sent'][1]['reasons']))
        self.assertEqual(r['sections'], [['Atividades Avaliativas', 'falhou', 7, 0],
                                         ['Trilhas de Aprendizagem', 'salvo', 3, 0]])
        self.assertEqual(r['coverage']['salvas'], 1)
        self.assertEqual(r['state'], 'parcial')                         # never "all saved" with a failed section

    def test_nothing_is_sent_before_the_explicit_click_in_any_scenario(self):
        for name, r in self.results.items():
            self.assertEqual(r['connectsBeforeConfirm'], 0, name)       # reading never opened a native port

    def test_reading_without_confirming_and_closing_discards_everything(self):
        r = self.results['leitura_sem_confirmar']
        self.assertEqual((r['readState'], r['readings'], r['sent'], r['connects'], r['closed']), ('lido', 2, [], 0, True))
        self.assertEqual([s[:3] for s in r['sections']], [['Atividades Avaliativas', 'lido', 7], ['Trilhas de Aprendizagem', 'lido', 2]])

    def test_the_preference_window_is_still_closed_by_its_x_in_the_course_mode(self):
        r = self.results['preferencia_na_leitura']
        self.assertEqual([(s['name'], len(s['ids'])) for s in r['sent']], [('Atividades Avaliativas', 7), ('Trilhas de Aprendizagem', 2)])
        self.assertNotIn('pref:sim', r['clicks'])
        self.assertNotIn('pref:cancelar', r['clicks'])

    def test_an_external_link_is_never_opened_even_when_authorized(self):
        r = self.results['trilhas_link_externo']
        self.assertIn(['Trilhas de Aprendizagem', 'bloqueada'], r['plan'])
        self.assertEqual([s['name'] for s in r['sent']], ['Atividades Avaliativas'])

    def test_it_must_start_from_the_course_home(self):
        r = self.results['comeca_na_secao']
        self.assertEqual((r['sent'], r['clicks'], r['plan']), ([], [], None))

    def test_no_request_left_the_fictitious_host(self):
        files = {f'https://ead.aedb.br/__ext/src/{p.name}' for p in EXT_SRC.glob('*.js')}
        # v0.5.4: the pages of the assignments of the sections read (aborted by this harness: "não verificado")
        pages = {f'https://ead.aedb.br/ava/mod/assign/view.php?id={c}' for c in ('90001', '90002', '90003', '90005', '90007', '92002')}
        self.assertLessEqual(set(self.requests), {HOME, SECTION, 'https://ead.aedb.br/favicon.ico'} | files | pages)
        for address in self.requests:                       # never a material, a group choice, a file or an attempt
            self.assertNotRegex(address, r'90004|90006|92001|pluginfile|startattempt|groupselect')


if __name__ == '__main__':
    unittest.main()

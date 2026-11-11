"""v0.5.4 — deadlines and delivery read from each activity's page, END TO END in a real Chromium, FICTITIOUS pages.

The synthetic course home (panel open) runs the REAL extension modules (sync.js, preview.js, dom_tiles.js,
details.js, deadlines.js, save.js...). Every activity page is served from memory by this test (Moodle 4 markup
hypothesis: tests/fixtures/companion/mod_*.html); every other request is aborted. The reading is done like the
popup does it (autoSave: false, details: true); then, as the explicit click, the snapshot is handed to a fake native
port and the Python side validates it (contract), stores it in a TEMPORARY database and builds the app's view.

What it cannot show: the real AEDB markup of these pages, and the real Moodle session.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from campus_ai import companion_store as cs  # noqa: E402
from campus_ai import companion_view as cv  # noqa: E402
from campus_ai import contract  # noqa: E402

EXT_SRC = ROOT / 'companion' / 'src'
FIXTURES = ROOT / 'tests' / 'fixtures' / 'companion'
HOME = 'https://ead.aedb.br/ava/course/view.php?id=7653'
OPT_IN = unittest.skipUnless(os.environ.get('CAMPUS_AI_BROWSER_SMOKE') == '1',
                             'Chromium local opt-in: CAMPUS_AI_BROWSER_SMOKE=1')
OPEN = "document.getElementById('section-3').classList.add('aberta');"
AS_QUIZ = ("for (const c of ['90003', '90005']) { const li = document.querySelector(`#section-3 li[data-cmid='${c}']`);"
           " li.dataset.modtype = 'quiz'; li.querySelectorAll('a.aalink').forEach((a) => a.setAttribute('href', `/ava/mod/quiz/view.php?id=${c}`)); }")
ASSIGN = (FIXTURES / 'mod_assign.html').read_text(encoding='utf-8')
QUIZ = (FIXTURES / 'mod_quiz.html').read_text(encoding='utf-8')
PRIVATE = ('SEGREDO-SESSKEY', 'Comentário sintético privado', '8,00', 'texto sintético do status')


def dates(*lines):
    body = ''.join(f'<div><strong>{label}:</strong> {value}</div>' for label, value in lines)
    return f'<div data-region="activity-dates" class="activity-dates">{body}</div>'


def status(submission, grading='submissionnotgraded', extra_rows=''):
    return ('<div class="submissionstatustable"><h3>Status de envio</h3><table class="generaltable"><tbody>'
            f'<tr><th class="cell c0">Status de envio</th><td class="{submission} cell c1">texto sintético do status</td></tr>'
            f'<tr><th class="cell c0">Status da avaliação</th><td class="{grading} cell c1">texto sintético do status</td></tr>'
            f'{extra_rows}<tr><th class="cell c0">Comentários do envio</th><td class="cell c1">Comentário sintético privado</td></tr>'
            '</tbody></table></div>')


def assign(cmid, dates_html='', status_html='', body_cmid=None):
    page = ASSIGN.replace('{{DATES}}', dates_html).replace('{{STATUS}}', status_html)
    return {'status': 200, 'type': 'text/html; charset=utf-8', 'body': page.replace('{{CMID}}', body_cmid or cmid)}


def quiz(cmid, dates_html, attempts):
    rows = ''.join(attempts)
    table = ('<table class="generaltable quizattemptsummary"><thead><tr><th>Tentativa</th><th>Estado</th><th>Nota</th>'
             f'<th>Revisão</th></tr></thead><tbody>{rows}</tbody></table>') if rows else ''
    page = QUIZ.replace('{{DATES}}', dates_html).replace('{{ATTEMPTS}}', table).replace('{{CMID}}', cmid)
    return {'status': 200, 'type': 'text/html; charset=utf-8', 'body': page}


FUTURE = ('Vencimento', 'quarta-feira, 31 dez. 2098, 23:59')
PAST = ('Vencimento', 'sexta-feira, 10 jan. 2020, 23:59')
OPENED = ('Aberto', 'segunda-feira, 3 nov. 2025, 00:00')
LOGIN = {'status': 200, 'type': 'text/html', 'body': '<!doctype html><html><body id="page-login-index" class="pagelayout-login">'
         '<form method="post" action="/ava/login/index.php"><input name="username"><input name="password" type="password"></form>'
         '</body></html>'}


def url(cmid, kind='assign'):
    return f'https://ead.aedb.br/ava/mod/{kind}/view.php?id={cmid}'


JOBS = {
    'variedade': ('', {
        url('90001'): assign('90001', dates(OPENED, FUTURE), status('submissionstatus_new')),
        url('90002'): assign('90002', dates(PAST), status('submissionstatussubmitted')),
        url('90003'): assign('90003', dates(FUTURE), status('submissionstatusdraft')),
        url('90005'): assign('90005', dates(PAST), status('submissionstatussubmitted', 'submissiongraded')),
        url('90007'): assign('90007', dates(PAST), status('submissionstatus_new', extra_rows=
                             '<tr><th class="cell c0">Data limite</th><td class="cell c1">segunda-feira, 13 jan. 2020, 23:59</td></tr>')),
    }),
    'falhas': ('', {
        url('90001'): assign('90001', dates(OPENED), status('submissionstatus_new')),                 # sem prazo
        url('90002'): assign('90002', dates(('Vencimento', 'a definir pelo professor')), status('submissionstatus_new')),
        url('90003'): {'status': 404, 'type': 'text/html', 'body': '<html><body>Não encontrado</body></html>'},
        url('90005'): assign('90005', dates(FUTURE), status('submissionstatus_new'), body_cmid='99999'),  # another page
        url('90007'): assign('90007', '', ''),                                                        # unknown structure
    }),
    'carregamento': ('', {
        url('90001'): 'abort',                                                                        # network failure
        url('90002'): {'status': 500, 'type': 'text/html', 'body': 'erro'},
        url('90003'): assign('90003', dates(FUTURE), status('submissionstatusdraft')),
        url('90005'): {'status': 303, 'type': 'text/html', 'body': '', 'location': '/ava/login/index.php'},   # session
        url('90007'): assign('90007', dates(FUTURE), status('submissionstatus_new')),                 # never requested
    }),
    'login_na_resposta': ('', {url('90001'): LOGIN}),
    'questionarios': (AS_QUIZ, {
        url('90001'): assign('90001', dates(FUTURE), status('submissionstatus_new')),
        url('90002'): assign('90002', dates(FUTURE), status('submissionstatus_new')),
        url('90003', 'quiz'): quiz('90003', dates(('Abre', 'segunda-feira, 3 nov. 2025, 00:00'), ('Fecha', 'quarta-feira, 31 dez. 2098, 23:59')),
                                   ['<tr><td>1</td><td>Em andamento</td><td></td><td></td></tr>']),
        url('90005', 'quiz'): quiz('90005', dates(('Fecha', 'sexta-feira, 10 jan. 2020, 23:59')),
                                   ['<tr><td>1</td><td>Finalizada<br>Enviada sexta, 7 nov 2025</td><td>8,00</td>'
                                    '<td><a href="/ava/mod/quiz/review.php?attempt=55">Revisão</a></td></tr>']),
        url('90007'): assign('90007', dates(FUTURE), status('submissionstatus_new')),
    }),
}

SCRIPT = r'''
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
profile, jobs_path, src_dir, fixtures_dir = sys.argv[1:5]
jobs = json.loads(Path(jobs_path).read_text(encoding='utf-8'))
SRC, FIX = Path(src_dir), Path(fixtures_dir)
BEHAVIOR = (FIX / 'tiles_live_behavior.js').read_text(encoding='utf-8')
ALLOWED = {p.name for p in SRC.glob('*.js')}
HOME = 'https://ead.aedb.br/ava/course/view.php?id=7653'
current, seen = {}, []

def handler(route):
    request = route.request
    seen.append([request.method, request.url, current.get('name')])
    pages = current.get('pages', {})
    if request.url == HOME:
        html = (FIX / 'tiles_home.html').read_text(encoding='utf-8').replace('</body>', '<script>' + BEHAVIOR + '</script></body>')
        route.fulfill(status=200, content_type='text/html; charset=utf-8', body=html)
    elif request.url.startswith('https://ead.aedb.br/__ext/src/') and request.url.rsplit('/', 1)[1] in ALLOWED:
        route.fulfill(status=200, content_type='application/javascript', body=(SRC / request.url.rsplit('/', 1)[1]).read_text(encoding='utf-8'))
    elif request.url in pages and pages[request.url] != 'abort':
        spec = pages[request.url]
        headers = {'content-type': spec['type']}
        if spec.get('location'):
            headers['location'] = spec['location']
        route.fulfill(status=spec['status'], headers=headers, body=spec['body'])
    else:
        route.abort()

RUN = """async () => {
  const { runSync } = await import('/__ext/src/sync.js');
  const { saveSnapshot } = await import('/__ext/src/save.js');
  let connects = 0;
  const sent = [];
  const port = () => {
    connects += 1;
    const listeners = { m: [] };
    return {
      onMessage: { addListener: (f) => listeners.m.push(f) }, onDisconnect: { addListener: () => {} }, disconnect() {},
      postMessage(msg) {
        setTimeout(() => {
          const reply = (body) => listeners.m.forEach((f) => f({ protocol: 'campus-ai.companion/1', request_id: msg.request_id, ...body }));
          if (msg.type === 'hello') { reply({ type: 'welcome', session: 'a'.repeat(32) }); return; }
          sent.push(msg.payload.snapshot);
          reply({ type: 'ack', saved: true, result: { run: 1, itens: 7, novos: 7, alterados: 0, ausentes: 0, reaparecidos: 0, inalterados: 0 } });
        }, 0);
      },
    };
  };
  const api = {
    tabs: { query: async () => [{ id: 1, url: location.href }] },
    scripting: { executeScript: async (o) => {
      if (o.files) { for (const f of o.files) await import('/__ext/' + f); return [{}]; }
      return [{ result: await o.func(...(o.args || [])) }];
    } },
    runtime: { connectNative: () => port(), lastError: null },
  };
  const outcome = await runSync(api, { autoSave: false, details: true, detailPauseMs: 50, timeoutMs: 6000, pollMs: 100, settleMs: 300 });
  const connectsBeforeClick = connects;
  // the explicit click on "Salvar no Campus AI"
  const saved = outcome.model && outcome.model.state === 'ok' ? await saveSnapshot(api, outcome.model.page, outcome.model.snapshot) : null;
  return { state: outcome.state, steps: outcome.steps.map((s) => s.id + ':' + s.status), connectsBeforeClick,
    details: outcome.model && outcome.model.details ? outcome.model.details.map((d) => ({ cmid: d.uid.split(':').pop(), kind: d.kind,
      result: d.detail.result, situation: d.situation, submission: d.detail.submission_state, grading: d.detail.grading_state,
      attempt: d.detail.attempt_state, due_state: d.detail.due_state, deadlines: d.deadlines })) : null,
    saved: saved ? saved.saved : null, sent };
}"""

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(profile, headless=True, accept_downloads=False)
    try:
        context.route('**/*', handler)
        results = {}
        for job in jobs:
            current.update(name=job['name'], pages=job['pages'])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.add_init_script('window.__variant = "ok"')
            page.goto(HOME)
            page.evaluate(job['mutate'])
            out = page.evaluate(RUN)
            out.update(clicks=page.evaluate('window.__clicks'), url_after=page.url, errors=errors)
            results[job['name']] = out
            page.close()
        print(json.dumps({'results': results, 'requests': seen}))
    finally:
        context.close()
'''


@OPT_IN
class DetailsInChromiumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        jobs = [{'name': name, 'mutate': OPEN + mutate, 'pages': pages} for name, (mutate, pages) in JOBS.items()]
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

    def by_cmid(self, name):
        return {d['cmid']: d for d in self.results[name]['details']}

    def test_assignment_states_and_deadlines_are_read_from_the_page(self):
        d = self.by_cmid('variedade')
        self.assertEqual({c: (x['submission'], x['grading'], x['situation']) for c, x in d.items()}, {
            '90001': ('sem_envio', 'nao_avaliado', 'pendente'),            # não enviada, prazo futuro
            '90002': ('enviado', 'nao_avaliado', 'aguardando_avaliacao'),  # enviada, aguardando avaliação
            '90003': ('rascunho', 'nao_avaliado', 'pendente'),             # rascunho
            '90005': ('enviado', 'avaliado', 'concluida'),                 # avaliada
            '90007': ('sem_envio', 'nao_avaliado', 'atrasada'),            # prazo expirado
        })
        self.assertEqual([(x['kind'], x['at']) for x in d['90001']['deadlines']], [('abertura', '2025-11-03T00:00'), ('entrega', '2098-12-31T23:59')])
        self.assertEqual([(x['kind'], x['at']) for x in d['90007']['deadlines']], [('entrega', '2020-01-10T23:59'), ('limite', '2020-01-13T23:59')])
        self.assertTrue(all(x['due_state'] == 'definido' for x in d.values()))
        self.assertIn('detalhar:ok', self.results['variedade']['steps'])

    def test_no_deadline_unreadable_deadline_and_unrecognised_pages(self):
        d = self.by_cmid('falhas')
        self.assertEqual((d['90001']['due_state'], d['90001']['situation']), ('sem_prazo', 'pendente'))       # sem prazo
        self.assertEqual((d['90002']['due_state'], d['90002']['deadlines'][0]['at'], d['90002']['deadlines'][0]['raw']),
                         ('nao_interpretado', '', 'a definir pelo professor'))                                # indisponível
        self.assertEqual((d['90003']['result'], d['90003']['situation']), ('inacessivel', 'nao_verificado'))  # 404
        self.assertEqual(d['90005']['result'], 'pagina_nao_reconhecida')                                       # other cmid
        self.assertEqual(d['90007']['result'], 'estrutura_desconhecida')
        self.assertIn('detalhar:parcial', self.results['falhas']['steps'])

    def test_load_failures_and_an_expired_session_stop_safely(self):
        d = self.by_cmid('carregamento')
        self.assertEqual({c: x['result'] for c, x in d.items()}, {
            '90001': 'falha_rede', '90002': 'falha_http', '90003': 'ok', '90005': 'redirecionado', '90007': 'nao_consultada'})
        self.assertEqual(self.results['carregamento']['state'], 'lido')       # the section reading itself is kept
        asked = [u for m, u, job in self.requests if job == 'carregamento' and '/mod/' in u]
        self.assertNotIn(url('90007'), asked)                                 # nothing after the redirect
        self.assertNotIn('https://ead.aedb.br/ava/login/index.php', [u for _m, u, _j in self.requests])   # never followed
        login = self.by_cmid('login_na_resposta')
        self.assertEqual(login['90001']['result'], 'sessao_expirada')
        self.assertEqual({x['result'] for c, x in login.items() if c != '90001'}, {'nao_consultada'})

    def test_quiz_in_progress_and_finished(self):
        d = self.by_cmid('questionarios')
        self.assertEqual((d['90003']['kind'], d['90003']['attempt'], d['90003']['situation']), ('quiz', 'em_andamento', 'verificar_tentativa'))
        self.assertEqual((d['90005']['attempt'], d['90005']['situation']), ('finalizada', 'concluida'))
        self.assertEqual([x['kind'] for x in d['90003']['deadlines']], ['abertura', 'fechamento'])

    def test_only_get_requests_to_the_authorized_activities_and_nothing_is_triggered(self):
        allowed_pages = set()
        for _mutate, pages in JOBS.values():
            allowed_pages |= set(pages)
        for method, address, job in self.requests:
            self.assertEqual(method, 'GET', address)
            if '/mod/' in address:
                self.assertIn(address, allowed_pages, address)
                self.assertNotRegex(address, r'90004|90006|startattempt|review\.php|attempt\.php|pluginfile')
        for name, r in self.results.items():
            self.assertEqual(r['clicks'], [], name)                          # no tile click (panel open), no button
            self.assertEqual(r['url_after'], HOME, name)
            self.assertEqual(r['errors'], [], name)
            dumped = json.dumps(r, ensure_ascii=False)
            for private in PRIVATE:
                self.assertNotIn(private, dumped, (name, private))

    def test_nothing_is_sent_before_the_explicit_click_and_the_app_stores_what_was_read(self):
        for name, r in self.results.items():
            self.assertEqual(r['connectsBeforeClick'], 0, name)
            self.assertEqual(len(r['sent']), 1, name)                         # one report, after the click
        with tempfile.TemporaryDirectory() as tmp:
            store = cs.SnapshotStore(Path(tmp) / 'live.db', allowed_courses=['7653'])
            for name in ('variedade', 'questionarios'):
                snap = contract.parse_snapshot(self.results[name]['sent'][0])    # the extension's output passes the contract
                store.save(snap)
            view = cv.load_view(Path(tmp) / 'live.db', now=datetime.now(timezone.utc))
            by = {r.cmid: r for r in view.rows}
            self.assertEqual(by['90003'].situation, 'verificar_tentativa')     # last reading: questionarios
            self.assertEqual(by['90005'].situation, 'concluida')
            self.assertEqual(by['90001'].due_text, '31/12/2098 23:59')
            self.assertEqual(by['90006'].situation, 'nao_se_aplica')           # groupselect
            self.assertEqual(by['90004'].category, 'material')                 # resource_pdf
            # 90003/90005 turned from assign into quiz with the SAME uid: updated in place, never a second row
            self.assertEqual(len(store.details()), 5)
            self.assertEqual(store.details('moodle:course:7653:module:90003')['kind'], 'quiz')
            self.assertEqual(len(store.detail_history('moodle:course:7653:module:90003')), 2)


if __name__ == '__main__':
    unittest.main()

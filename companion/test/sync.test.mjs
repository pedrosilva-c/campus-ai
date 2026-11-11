import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { MESSAGES } from '../src/preview.js';
import { DEFAULTS, MAX_DIALOG_CLOSES, STEPS, SYNC_MESSAGES, runSync } from '../src/sync.js';

const golden = JSON.parse(readFileSync(new URL('../../tests/fixtures/companion/tiles_projection.json', import.meta.url), 'utf8'));
const HOME = 'https://ead.aedb.br/ava/course/view.php?id=7653';
const SECTION = 'https://ead.aedb.br/ava/course/section.php?id=4242';
const LOGIN = 'https://ead.aedb.br/ava/login/index.php';
const PAGE = { ...golden, docTitle: 'Bloco: Atividades Avaliativas | 4º P CURSO FICTÍCIO - Modelagem Fictícia | AVA' };
const PANEL = {
  ...golden, mode: 'painel', sectionPage: false, sectionName: 'Atividades Avaliativas', panelKey: 'painel:4242:3:10',
  docTitle: 'Curso: 4º P CURSO FICTÍCIO - Modelagem Fictícia | AVA',
};
const noItems = (p) => ({ ...p, entries: [] });
const closed = (reason = 'painel_fechado', extra = {}) => ({
  ...noItems(PANEL), mode: 'nenhum', sectionId: '', sectionName: '', panelKey: 'nenhum:::0',
  diagnostic: { ...golden.diagnostic, tiles: 5, tilesMatched: 1, candidates: 1, reason, ...extra },
});
const CLOSED = closed();
const NOW = new Date('2026-11-06T12:00:00Z');
const FAST = { pollMs: 100, settleMs: 300, timeoutMs: 3000, sleep: async () => {}, now: NOW };

function strict(object) {
  return new Proxy(object, {
    get(target, key) {
      if (!(key in target)) throw new Error(`API não permitida: ${String(key)}`);
      return target[key];
    },
  });
}

// A fake Chrome + Tiles page. Before the click the page shows `initial`; after it, `afterClick(n, withEntries)`.
function world({ url = HOME, initial = CLOSED, afterClick, clickResult = { clicked: true }, tabs, details } = {}) {
  const log = [];
  const state = { clicked: false, n: 0 };
  const open = (n, withEntries) => ({ href: HOME, projection: withEntries ? PANEL : noItems(PANEL) });
  const after = afterClick || open;
  const api = {
    tabs: strict({ query: async () => { log.push('query'); return tabs ?? [{ id: 11, url }]; } }),
    scripting: strict({
      executeScript: async (options) => {
        assert.equal(options.target.tabId, 11);
        if (options.files) { log.push(`inject:${options.files[0].split('/').pop()}`); return [{}]; }
        const source = String(options.func);
        assert.ok(!/MESSAGES|AUTHORIZED|SYNC_MESSAGES|import/.test(source), 'page-side function must be self-contained');
        if (source.includes('CampusAiDetails')) {           // v0.5.4: one activity page
          const { cmid, kind, courseId } = options.args[0];
          log.push(`detail:${kind}:${cmid}`);
          assert.equal(courseId, '7653');
          if (!details) throw new Error('no details expected');
          return [{ result: details(cmid, kind) }];
        }
        if (source.includes('CampusAiOpenPanel')) {
          log.push('click');
          state.clicked = true;
          return [{ result: typeof clickResult === 'function' ? clickResult() : clickResult }];
        }
        const { withEntries } = options.args[0];
        log.push(withEntries ? 'read-items' : 'read-id');
        const page = state.clicked ? after(state.n++, withEntries) : { href: url, projection: withEntries ? { ...initial, entries: PANEL.entries } : noItems(initial) };
        return [{ result: page }];
      },
    }),
  };
  return { api: strict(api), log, state };
}

function saver(log, outcome = { saved: true, code: 'salvo', result: { run: 4, itens: 7, novos: 0, alterados: 0, ausentes: 0, reaparecidos: 0, inalterados: 7 } }) {
  const calls = [];
  const save = async (api, page, snapshot) => { log.push('save'); calls.push({ page, snapshot }); return typeof outcome === 'function' ? outcome() : outcome; };
  return { save, calls };
}

async function sync(w, options = {}, outcome) {
  const s = saver(w.log, outcome);
  const progress = [];
  const result = await runSync(w.api, { ...FAST, save: s.save, onProgress: (steps) => progress.push(steps.map((x) => `${x.id}:${x.status}`).join(' ')), ...options });
  return { result, progress, saves: s.calls };
}
const statuses = (result) => Object.fromEntries(result.steps.map((s) => [s.id, s.status]));
const grows = (limit = 10) => (n, withEntries) => ({
  href: HOME, projection: { ...(withEntries ? PANEL : noItems(PANEL)), panelKey: `painel:4242:3:${Math.min(2 + n, limit)}` },
});

test('panel already open: no click at all; read, validate and save', async () => {
  const w = world({ initial: PANEL });
  const { result, saves } = await sync(w);
  assert.equal(result.state, 'salvo');
  assert.ok(!w.log.includes('click') && !w.log.includes('inject:open_panel.js'));
  assert.deepEqual(statuses(result), { verificar: 'ok', abrir: 'pulado', fechar: 'pulado', aguardar: 'pulado', ler: 'ok', detalhar: 'pulado', salvar: 'ok' });
  assert.equal(saves.length, 1);
  assert.equal(saves[0].page.kind, 'curso_inicio');
  assert.equal(saves[0].snapshot.materials.length + saves[0].snapshot.activities.length, 7);
  assert.match(result.message, /salvo/i);
});

test('closed panel: one click, wait until stable, then read once and save once, in this order', async () => {
  const w = world({ afterClick: grows(10) });
  const { result, progress, saves } = await sync(w);
  assert.equal(result.state, 'salvo');
  assert.equal(w.log.filter((x) => x === 'click').length, 1);
  assert.equal(w.log.filter((x) => x === 'read-items').length, 1);           // items are read exactly once, at the end
  assert.ok(w.log.indexOf('click') < w.log.indexOf('read-items'));
  assert.ok(w.log.indexOf('inject:open_panel.js') < w.log.indexOf('click'));
  assert.ok(w.log.lastIndexOf('read-items') < w.log.indexOf('save'));
  assert.equal(w.log.filter((x) => x === 'save').length, 1);
  assert.equal(w.log.at(-1), 'save');
  // no item data was read before the click (the pre-click reads are identity-only)
  assert.deepEqual(w.log.slice(0, w.log.indexOf('click')).filter((x) => x === 'read-items'), []);
  assert.equal(saves[0].snapshot.activities.length + saves[0].snapshot.materials.length, 7);
  assert.deepEqual(statuses(result), { verificar: 'ok', abrir: 'ok', fechar: 'pulado', aguardar: 'ok', ler: 'ok', detalhar: 'pulado', salvar: 'ok' });
  for (const id of STEPS.map(([step]) => step).filter((step) => !['fechar', 'detalhar'].includes(step))) {   // each step is announced before it ends
    const begin = progress.findIndex((line) => line.includes(`${id}:andamento`));
    const end = progress.findIndex((line) => line.includes(`${id}:ok`));
    assert.ok(begin >= 0 && end > begin, id);
  }
});

test('a panel that fills gradually is not read until its item count is stable', async () => {
  // the item count grows 2,3,4,5,6,7 and then stays: the run keeps polling and only reads once it is stable
  const w = world({ afterClick: grows(7) });
  const { result, saves } = await sync(w, { settleMs: 300 });
  assert.equal(result.state, 'salvo');
  assert.equal(saves.length, 1);
  assert.ok(w.log.indexOf('read-items') > w.log.indexOf('click') + 6, 'no items read while the panel was still growing');
  assert.equal(w.log.filter((x) => x === 'read-items').length, 1);

  // a panel that never stops changing is never read
  const unstable = world({ afterClick: grows(Infinity) });
  const failed = await sync(unstable);
  assert.deepEqual([failed.result.state, failed.result.message], ['recusado', SYNC_MESSAGES.painel_nao_abriu]);
  assert.ok(!unstable.log.includes('read-items'));
  assert.equal(failed.saves.length, 0);
});

test('the save outcome decides the message: no ACK, no "saved"', async () => {
  for (const code of ['host_nao_instalado', 'tempo_esgotado', 'desconectado', 'sem_confirmacao', 'falha_persistencia']) {
    const w = world({ initial: PANEL });
    const { result } = await sync(w, {}, { saved: false, code });
    assert.equal(result.state, 'lido_nao_salvo', code);
    assert.equal(result.steps.find((s) => s.id === 'salvar').status, 'falhou');
    assert.equal(result.saved.saved, false);
    assert.match(result.message, /NÃO há confirmação/);
    assert.doesNotMatch(result.message, /^Sincronizado/);
    assert.equal(result.model.state, 'ok');                                 // the manual "Salvar" can still be offered
  }
  const odd = world({ initial: PANEL });
  assert.equal((await sync(odd, {}, null)).result.saved.code, 'sem_confirmacao');
  const lying = world({ initial: PANEL });
  assert.equal((await sync(lying, {}, { saved: 'yes' })).result.state, 'lido_nao_salvo');
  const throwing = world({ initial: PANEL });
  const { result } = await sync(throwing, {}, () => { throw new Error('boom'); });
  assert.equal(result.state, 'erro');
  assert.equal(result.saved, null);
});

test('refusals before any click: other course, no Tiles, login, other domain, ambiguity, dialog, two panels', async () => {
  const cases = [
    [HOME, closed('tile_ambiguo'), MESSAGES.tile_ambiguo],
    [HOME, closed('painel_sem_vinculo'), MESSAGES.painel_sem_vinculo],
    [HOME, closed('dialogo_bloqueia'), MESSAGES.dialogo_bloqueia],
    [HOME, closed('paineis_multiplos'), MESSAGES.paineis_multiplos],
    [HOME, closed('tile_nao_encontrado'), MESSAGES.tile_nao_encontrado],
    [HOME, closed('tile_sem_vinculo'), MESSAGES.tile_sem_vinculo],
    [HOME, { ...CLOSED, courseId: '8888' }, MESSAGES.curso_diferente],
    [HOME, { ...CLOSED, formatTiles: false }, MESSAGES.formato],
    [LOGIN, CLOSED, MESSAGES.login],
    ['https://example.org/ava/course/view.php?id=7653', CLOSED, MESSAGES.dominio],
    ['https://ead.aedb.br/ava/course/view.php?id=9999', CLOSED, MESSAGES.curso_diferente],
    ['https://ead.aedb.br/ava/mod/assign/view.php?id=1', CLOSED, MESSAGES.modulo],
  ];
  for (const [url, initial, message] of cases) {
    const w = world({ url, initial });
    const { result, saves } = await sync(w);
    assert.equal(result.state, 'recusado', message);
    assert.equal(result.message, message);
    assert.ok(!w.log.includes('click') && !w.log.includes('inject:open_panel.js'), message);
    assert.equal(saves.length, 0);
    assert.equal(result.steps.find((s) => s.id === 'verificar').status, 'falhou');
  }
});

test('the page refuses the click (unverifiable tile): nothing is waited for, read or saved', async () => {
  const reasons = { tile_ambiguo: MESSAGES.tile_ambiguo, tile_sem_vinculo: MESSAGES.tile_sem_vinculo,
    dialogo_bloqueia: MESSAGES.dialogo_bloqueia, tile_perigoso: SYNC_MESSAGES.tile_perigoso,
    tile_oculto: SYNC_MESSAGES.tile_oculto, tile_nao_clicavel: SYNC_MESSAGES.tile_nao_clicavel,
    curso_diferente: MESSAGES.curso_diferente, '<b>x</b>': SYNC_MESSAGES.clique_recusado, '': SYNC_MESSAGES.clique_recusado };
  for (const [reason, message] of Object.entries(reasons)) {
    const w = world({ clickResult: { clicked: false, reason } });
    const { result, saves } = await sync(w);
    assert.equal(result.state, 'recusado', reason);
    assert.equal(result.message, message, reason);
    assert.equal(statuses(result).abrir, 'falhou');
    assert.equal(statuses(result).aguardar, 'pendente');
    assert.deepEqual(w.log.slice(w.log.indexOf('click') + 1), [], 'no reads after a refused click');
    assert.equal(saves.length, 0);
  }
  for (const odd of [undefined, null, 'x', { clicked: 'true' }, { reason: 'tile_oculto' }]) {
    const w = world({ clickResult: () => odd });          // (a function: a plain undefined would use the default)
    const { result, saves } = await sync(w);
    assert.equal(result.state, 'recusado', String(odd));
    assert.equal(saves.length, 0);
    assert.deepEqual(w.log.slice(w.log.indexOf('click') + 1), []);
  }
});

test('the panel never appears (or stays empty): timeout, no items read, nothing saved', async () => {
  for (const afterClick of [() => ({ href: HOME, projection: CLOSED }),
    (n, withEntries) => ({ href: HOME, projection: { ...(withEntries ? PANEL : noItems(PANEL)), panelKey: 'painel:4242:3:0' } })]) {
    const w = world({ afterClick });
    const { result, saves } = await sync(w);
    assert.equal(result.state, 'recusado');
    assert.equal(result.message, SYNC_MESSAGES.painel_nao_abriu);
    assert.equal(w.log.filter((x) => x === 'click').length, 1);              // never clicks twice
    assert.ok(!w.log.slice(w.log.indexOf('click')).includes('read-items'));
    assert.equal(statuses(result).aguardar, 'falhou');
    assert.equal(saves.length, 0);
  }
});

test('access lost when the page navigates (activeTab ends), session expired, left the domain', async () => {
  let w = world({ afterClick: () => { throw new Error('Cannot access contents of the page'); } });
  let r = await sync(w);
  assert.deepEqual([r.result.state, r.result.message], ['recusado', SYNC_MESSAGES.acesso_perdido]);
  assert.equal(r.saves.length, 0);
  w = world({ afterClick: () => ({ href: LOGIN, projection: CLOSED }) });
  r = await sync(w);
  assert.equal(r.result.message, SYNC_MESSAGES.sessao_expirada);
  w = world({ afterClick: () => ({ href: 'https://example.org/', projection: CLOSED }) });
  assert.equal((await sync(w)).result.message, SYNC_MESSAGES.saiu_do_dominio);
  w = world({ afterClick: () => ({ href: HOME, projection: 'lixo' }) });
  assert.equal((await sync(w)).result.message, SYNC_MESSAGES.acesso_perdido);
  for (const w2 of [w]) assert.ok(!w2.log.includes('read-items') || w2.log.indexOf('read-items') < w2.log.indexOf('click'));
});

test('ambiguity or a dialog appearing while waiting stops the run before any item is read', async () => {
  for (const reason of ['paineis_multiplos', 'dialogo_bloqueia', 'painel_sem_vinculo', 'tile_ambiguo']) {
    const w = world({ afterClick: (n, withEntries) => (n < 1 ? { href: HOME, projection: closed() } : { href: HOME, projection: closed(reason) }) });
    const { result, saves } = await sync(w);
    assert.equal(result.state, 'recusado', reason);
    assert.equal(result.message, MESSAGES[reason], reason);
    assert.ok(!w.log.slice(w.log.indexOf('click')).includes('read-items'));
    assert.equal(saves.length, 0);
  }
});

test('the panel changing between the wait and the read: refused, not saved', async () => {
  const w = world({ afterClick: (n, withEntries) => (withEntries ? { href: HOME, projection: { ...PANEL, panelKey: 'painel:4242:3:11' } }
    : { href: HOME, projection: noItems(PANEL) }) });
  const { result, saves } = await sync(w);
  assert.equal(result.state, 'recusado');
  assert.equal(result.message, MESSAGES.mudou);
  assert.equal(statuses(result).ler, 'falhou');
  assert.equal(saves.length, 0);
});

test('cancel: before the click, while waiting, and before saving', async () => {
  let w = world();
  let r = await sync(w, { isCancelled: () => true });
  assert.equal(r.result.state, 'cancelado');
  assert.ok(!w.log.includes('click'));
  assert.equal(r.saves.length, 0);

  let polls = 0;
  w = world({ afterClick: () => ({ href: HOME, projection: CLOSED }) });
  r = await sync(w, { isCancelled: () => w.log.includes('click') && ++polls > 2 });
  assert.equal(r.result.state, 'cancelado');
  assert.equal(w.log.filter((x) => x === 'click').length, 1);
  assert.ok(!w.log.slice(w.log.indexOf('click')).includes('read-items'));
  assert.equal(r.saves.length, 0);

  w = world({ initial: PANEL });
  r = await sync(w, { isCancelled: () => w.log.filter((x) => x === 'read-items').length >= 1 && !w.log.includes('save') });
  assert.equal(r.result.state, 'cancelado');
  assert.equal(r.saves.length, 0);
});

test('panel mode on the section page: no click; the manual page kind is reported', async () => {
  const w = world({ url: SECTION, initial: PAGE, afterClick: () => assert.fail('must not click') });
  const { result, saves } = await sync(w);
  assert.equal(result.state, 'salvo');
  assert.ok(!w.log.includes('click'));
  assert.equal(saves[0].page.kind, 'curso_bloco');
  assert.equal(result.steps.find((s) => s.id === 'abrir').note, 'Página própria da seção.');
});

test('failures and a broken progress display never break the run or claim success', async () => {
  const noTab = world({ tabs: [] });
  assert.equal((await sync(noTab)).result.state, 'recusado');
  const brokenDisplay = world({ initial: PANEL });
  const s = saver(brokenDisplay.log);
  const result = await runSync(brokenDisplay.api, { ...FAST, save: s.save, onProgress: () => { throw new Error('ui'); } });
  assert.equal(result.state, 'salvo');
  assert.deepEqual(STEPS.map(([id]) => id), ['verificar', 'abrir', 'fechar', 'aguardar', 'ler', 'detalhar', 'salvar']);
  assert.ok(DEFAULTS.timeoutMs >= 5000 && DEFAULTS.settleMs >= 2 * DEFAULTS.pollMs);
});

// --- v0.5.2: Moodle's "Preferência dos dados" window ------------------------------------------------------------
// A fake page with that window. `s.dialog` = the window is rendered; `s.unknown` = another dialog is rendered;
// `s.panel` = the section is visible. The tile click and the X apply `onClick` / `onClose` to the page state.
// What happens INSIDE the page (which button is the X, never "Sim"/"Cancelar") is tested in Chromium.
const pref = (extra = {}) => closed('dialogo_preferencia', extra);
function prefWorld({ dialog = false, panel = false, unknown = false, onClick = { panel: true, dialog: true },
  onClose = { dialog: false }, closeResult = { clicked: true }, reappear = false } = {}) {
  const log = [];
  const s = { dialog, panel, unknown, quiet: 0 };
  const view = () => (s.unknown ? closed('dialogo_bloqueia', { unknownDialogs: 1, openDialogs: 1 })
    : s.dialog ? pref({ dataPreferenceDialogs: 1, openDialogs: 1 }) : s.panel ? PANEL : CLOSED);
  const api = {
    tabs: strict({ query: async () => { log.push('query'); return [{ id: 11, url: HOME }]; } }),
    scripting: strict({
      executeScript: async (options) => {
        if (options.files) { log.push(`inject:${options.files[0].split('/').pop()}`); return [{}]; }
        const source = String(options.func);
        assert.ok(!/MESSAGES|AUTHORIZED|SYNC_MESSAGES|import/.test(source), 'page-side function must be self-contained');
        if (source.includes('closeDataPreference')) {
          log.push('close-x');
          const result = typeof closeResult === 'function' ? closeResult() : closeResult;
          if (result && result.clicked === true) Object.assign(s, onClose);
          return [{ result }];
        }
        if (source.includes('CampusAiOpenPanel')) { log.push('click'); Object.assign(s, onClick); return [{ result: { clicked: true } }]; }
        const { withEntries } = options.args[0];
        log.push(withEntries ? 'read-items' : 'read-id');
        if (reappear && !s.dialog && log.includes('close-x') && ++s.quiet > 2) { s.dialog = true; s.quiet = 0; }
        const projection = view();
        return [{ result: { href: HOME, projection: withEntries && projection === PANEL ? PANEL : noItems(projection) } }];
      },
    }),
  };
  return { api: strict(api), log, s };
}
const count = (log, entry) => log.filter((x) => x === entry).length;

test('pref 1/6: the window appears after the tile click: closed by its X only, then the 7 modules are read', async () => {
  const w = prefWorld();
  const { result, saves } = await sync(w);
  assert.equal(result.state, 'salvo');
  assert.deepEqual([count(w.log, 'click'), count(w.log, 'close-x'), count(w.log, 'read-items')], [1, 1, 1]);
  assert.ok(w.log.indexOf('click') < w.log.indexOf('close-x') && w.log.indexOf('close-x') < w.log.indexOf('read-items'));
  assert.deepEqual(w.log.slice(0, w.log.indexOf('close-x')).filter((x) => x === 'read-items'), [], 'nothing read behind it');
  assert.equal(saves[0].snapshot.materials.length + saves[0].snapshot.activities.length, 7);
  assert.deepEqual(statuses(result), { verificar: 'ok', abrir: 'ok', fechar: 'ok', aguardar: 'ok', ler: 'ok', detalhar: 'pulado', salvar: 'ok' });
  assert.equal(result.dialogsClosed, 1);
  assert.match(result.steps.find((x) => x.id === 'fechar').note, /fechada pelo X/);
  assert.match(result.steps.find((x) => x.id === 'aguardar').note, /revalidada/);
});

test('pref 7: section already open behind the window: the X only, no click on the tile', async () => {
  const w = prefWorld({ dialog: true, panel: true });
  const { result } = await sync(w);
  assert.equal(result.state, 'salvo');
  assert.deepEqual([count(w.log, 'click'), count(w.log, 'close-x'), count(w.log, 'read-items')], [0, 1, 1]);
  assert.equal(statuses(result).abrir, 'pulado');
  // the window open over a CLOSED panel at the start: X first, then the single tile click
  const before = prefWorld({ dialog: true, onClick: { panel: true } });
  const r2 = await sync(before);
  assert.equal(r2.result.state, 'salvo');
  assert.deepEqual(before.log.filter((x) => x === 'click' || x === 'close-x'), ['close-x', 'click']);
});

test('pref 4: an unknown dialog (before or after the click) stays open and blocks: no X, nothing read', async () => {
  for (const w of [prefWorld({ unknown: true, panel: true }), prefWorld({ onClick: { panel: true, unknown: true } })]) {
    const { result, saves } = await sync(w);
    assert.equal(result.state, 'recusado');
    assert.equal(result.message, MESSAGES.dialogo_bloqueia);
    assert.equal(count(w.log, 'close-x'), 0);
    assert.ok(!w.log.includes('read-items'));
    assert.equal(saves.length, 0);
  }
});

test('pref 8: the window goes away but the section is not there: blocked, the tile is NOT clicked again', async () => {
  const w = prefWorld({ onClose: { dialog: false, panel: false } });
  const { result, saves } = await sync(w);
  assert.equal(result.state, 'recusado');
  assert.equal(result.message, SYNC_MESSAGES.secao_indisponivel);
  assert.equal(count(w.log, 'click'), 1);
  assert.ok(!w.log.includes('read-items'));
  assert.equal(saves.length, 0);
});

test('pref 9: closing fails or is refused by the page: nothing is read or saved', async () => {
  const refusals = { dialogo_nao_identificado: SYNC_MESSAGES.dialogo_nao_identificado, curso_diferente: MESSAGES.curso_diferente,
    '<b>x</b>': SYNC_MESSAGES.dialogo_nao_identificado, '': SYNC_MESSAGES.dialogo_nao_identificado };
  for (const [reason, message] of Object.entries(refusals)) {
    const w = prefWorld({ closeResult: { clicked: false, reason } });
    const { result, saves } = await sync(w);
    assert.deepEqual([result.state, result.message], ['recusado', message], reason);
    assert.equal(statuses(result).fechar, 'falhou');
    assert.ok(!w.log.includes('read-items'));
    assert.equal(saves.length, 0);
  }
  for (const odd of [undefined, null, { clicked: 'true' }]) {
    const w = prefWorld({ closeResult: () => odd });
    const { result, saves } = await sync(w);
    assert.equal(result.state, 'recusado', String(odd));
    assert.equal(saves.length, 0);
  }
  // the X was clicked but the window stays: stops after the timeout, the X is not clicked again
  const sticky = prefWorld({ onClose: {} });
  const { result, saves } = await sync(sticky);
  assert.deepEqual([result.state, result.message], ['recusado', SYNC_MESSAGES.dialogo_nao_fechou]);
  assert.equal(count(sticky.log, 'close-x'), 1);
  assert.ok(!sticky.log.includes('read-items'));
  assert.equal(saves.length, 0);
});

test('pref: the window keeps coming back: at most MAX_DIALOG_CLOSES closes, then stop', async () => {
  const w = prefWorld({ reappear: true });
  const { result, saves } = await sync(w);
  assert.deepEqual([result.state, result.message], ['recusado', SYNC_MESSAGES.dialogo_reapareceu]);
  assert.equal(count(w.log, 'close-x'), MAX_DIALOG_CLOSES);
  assert.equal(count(w.log, 'click'), 1);
  assert.ok(!w.log.includes('read-items'));
  assert.equal(saves.length, 0);
  // the window vanished by itself before the X: nothing is clicked in it and the run goes on
  const gone = prefWorld({ closeResult: () => { gone.s.dialog = false; return { clicked: false, reason: 'dialogo_ausente' }; } });
  const r2 = await sync(gone);
  assert.equal(r2.result.state, 'salvo');
  assert.equal(r2.result.dialogsClosed, 0);
});

test('pref 11: autoSave false (the popup): read, validated, NOT saved; the student saves with the button', async () => {
  for (const w of [prefWorld(), world({ initial: PANEL })]) {
    const { result, saves } = await sync(w, { autoSave: false });
    assert.equal(result.state, 'lido');
    assert.equal(result.message, SYNC_MESSAGES.lido);
    assert.equal(saves.length, 0);
    assert.ok(!w.log.includes('save'));
    assert.equal(statuses(result).salvar, 'aguardando');
    assert.equal(result.model.state, 'ok');
    assert.equal(result.model.rows.length, 7);                              // pref 10: the 7 modules
    assert.equal(result.model.snapshot.materials.length + result.model.snapshot.activities.length, 7);
  }
});

// --- v0.5.4: deadlines and delivery from each activity's page -----------------------------------------------------
const ASSIGNS = ['90001', '90002', '90003', '90005', '90007'];           // the 5 assign of the panel (not 90004, 90006)
const okFacts = (submission, due = '2098-12-31T23:59', grading = 'nao_avaliado') => ({ result: 'ok', facts: {
  structure: true, dates: due ? [{ kind: 'entrega', at: due, raw: 'quarta-feira, 31 dez. 2098, 23:59' }] : [],
  submission, grading, attempt: 'nao_se_aplica' } });
const VARIETY = { 90001: okFacts('sem_envio'), 90002: okFacts('enviado'), 90003: okFacts('rascunho'),
  90005: okFacts('enviado', '2020-01-10T23:59', 'avaliado'), 90007: okFacts('sem_envio', '2020-01-10T23:59') };
const detailLog = (log) => log.filter((x) => x.startsWith('detail:'));
const DETAIL_FAST = { ...FAST, detailPauseMs: 0, clock: () => new Date('2026-11-10T12:00:00Z') };

test('details are off unless asked: no page of any activity is requested', async () => {
  const w = world({ initial: PANEL });
  const { result } = await sync(w, { autoSave: false });
  assert.deepEqual(detailLog(w.log), []);
  assert.equal(statuses(result).detalhar, 'pulado');
  assert.equal(result.model.details, undefined);
});

test('details: one page per assignment, in order, after the read; never materials or group selections; nothing saved', async () => {
  const w = world({ initial: PANEL, details: (cmid) => VARIETY[cmid] });
  const { result, saves } = await sync(w, { ...DETAIL_FAST, autoSave: false, details: true });
  assert.equal(result.state, 'lido');
  assert.equal(saves.length, 0);                                            // still waits for "Salvar no Campus AI"
  assert.deepEqual(detailLog(w.log), ASSIGNS.map((c) => `detail:assign:${c}`));
  assert.ok(w.log.indexOf('inject:details.js') > w.log.lastIndexOf('read-items'), 'details only after the validated read');
  assert.equal(statuses(result).detalhar, 'ok');
  const by = Object.fromEntries(result.model.details.map((d) => [d.uid.split(':').pop(), d.situation]));
  assert.deepEqual(by, { 90001: 'pendente', 90002: 'aguardando_avaliacao', 90003: 'pendente', 90005: 'concluida', 90007: 'atrasada' });
  const acts = Object.fromEntries(result.model.snapshot.activities.map((a) => [a.uid.split(':').pop(), a]));
  assert.equal(acts['90002'].submission, 'enviado');
  assert.equal(acts['90007'].submission, 'nao_enviado');
  assert.equal(acts['90007'].detail.checked_at, '2026-11-10T12:00:00Z');
  assert.deepEqual(acts['90001'].deadlines, [{ kind: 'entrega', at: '2098-12-31T23:59', timezone_explicit: false, raw: 'quarta-feira, 31 dez. 2098, 23:59' }]);
  assert.equal(acts['90006'].detail, undefined);                            // groupselect: never a pending task
  assert.equal(acts['90006'].submission, 'desconhecido');
  assert.ok(!result.model.snapshot.materials.some((m) => 'detail' in m));    // resource_pdf stays a material
  assert.ok(result.model.snapshot.coverage.reasons.some((r) => r.includes('5 de 5 atividade(s)')));
});

test('details: one page fails, the others are read; a session problem stops the rest (not verified, never "no deadline")', async () => {
  const answers = { ...VARIETY, 90002: { result: 'inacessivel' }, 90005: { result: 'redirecionado' } };
  const w = world({ initial: PANEL, details: (cmid) => answers[cmid] });
  const { result, saves } = await sync(w, { ...DETAIL_FAST, autoSave: false, details: true });
  assert.equal(result.state, 'lido');                                       // a failed page never fails the reading
  assert.equal(saves.length, 0);
  assert.deepEqual(detailLog(w.log), ['detail:assign:90001', 'detail:assign:90002', 'detail:assign:90003', 'detail:assign:90005']);
  assert.equal(statuses(result).detalhar, 'parcial');
  const by = Object.fromEntries(result.model.details.map((d) => [d.uid.split(':').pop(), [d.detail.result, d.situation, d.deadlines.length]]));
  assert.deepEqual(by['90002'], ['inacessivel', 'nao_verificado', 0]);
  assert.deepEqual(by['90005'], ['redirecionado', 'nao_verificado', 0]);
  assert.deepEqual(by['90007'], ['nao_consultada', 'nao_verificado', 0]);  // not requested after the redirect
  assert.deepEqual(by['90001'], ['ok', 'pendente', 1]);
  // the tab is gone (activeTab ended): every remaining page is "not consulted"
  const lost = world({ initial: PANEL, details: () => { throw new Error('Cannot access contents of the page'); } });
  const r2 = await sync(lost, { ...DETAIL_FAST, autoSave: false, details: true });
  assert.equal(r2.result.state, 'lido');
  assert.equal(detailLog(lost.log).length, 1);
  assert.ok(r2.result.model.details.every((d) => d.situation === 'nao_verificado'));
});

test('details: cancelling while the pages are consulted ends the run with nothing saved', async () => {
  const w = world({ initial: PANEL, details: (cmid) => VARIETY[cmid] });
  const { result, saves } = await sync(w, { ...DETAIL_FAST, details: true, isCancelled: () => detailLog(w.log).length >= 2 });
  assert.equal(result.state, 'cancelado');
  assert.equal(saves.length, 0);
  assert.equal(detailLog(w.log).length, 2);
  assert.equal(statuses(result).detalhar, 'falhou');
});

test('messages never echo page content', async () => {
  const secret = 'Segredo-ZZZ-8888';
  const w = world({ initial: { ...CLOSED, courseId: '8888', docTitle: `Bloco: ${secret} | ${secret} | AVA` } });
  const { result } = await sync(w);
  assert.ok(!JSON.stringify(result).includes('ZZZ'));
  assert.ok(!JSON.stringify(result).includes('8888'));
});

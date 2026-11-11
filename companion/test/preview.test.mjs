import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { MESSAGES, SECTION_LABEL, runPreview } from '../src/preview.js';

const golden = JSON.parse(readFileSync(new URL('../../tests/fixtures/companion/tiles_projection.json', import.meta.url), 'utf8'));
const URL_SECTION = 'https://ead.aedb.br/ava/course/section.php?id=4242';
const URL_HOME = 'https://ead.aedb.br/ava/course/view.php?id=7653';
// Section page (section.php) and panel (view.php) projections, as dom_tiles.js returns them.
const PAGE = { ...golden, docTitle: 'Bloco: Atividades Avaliativas | 4º P CURSO FICTÍCIO - Modelagem Fictícia | AVA' };
const PANEL = {
  ...golden, mode: 'painel', sectionPage: false, sectionName: 'Atividades Avaliativas', panelKey: 'painel:4242:3:10',
  docTitle: 'Curso: 4º P CURSO FICTÍCIO - Modelagem Fictícia | AVA',
  diagnostic: { ...golden.diagnostic, tiles: 5, tilesMatched: 1, candidates: 1, visibleCandidates: 1, hiddenActivities: 2 },
};
const NOW = new Date('2026-11-05T20:00:00Z');
const noItems = (p) => ({ ...p, entries: [] });
const closed = (reason) => ({ ...noItems(PANEL), mode: 'nenhum', sectionId: '', sectionName: '', panelKey: 'nenhum:::0',
  diagnostic: { ...PANEL.diagnostic, reason, visibleCandidates: 0 } });

const mod = (cmid, title, modtype = 'assign') => ({
  modtype, cmid: String(cmid), title, hrefs: [`https://ead.aedb.br/ava/mod/${modtype.split('_')[0]}/view.php?id=${cmid}`],
});

// Strict fake of the Chrome API: touching anything other than tabs.query / scripting.executeScript throws.
function strict(object) {
  return new Proxy(object, {
    get(target, key) {
      if (!(key in target)) throw new Error(`API não permitida: ${String(key)}`);
      return target[key];
    },
  });
}

function fakeApi({ url = URL_SECTION, projection = PAGE, tabs, identity, items, after, failFiles = false } = {}) {
  const calls = [];
  let identityReads = 0;
  const api = {
    tabs: strict({
      query: async (q) => {
        calls.push('query');
        assert.deepEqual(q, { active: true, currentWindow: true });
        if (tabs instanceof Error) throw tabs;
        return tabs ?? [{ id: 11, url }];
      },
    }),
    scripting: strict({
      executeScript: async (options) => {
        assert.equal(options.target.tabId, 11);
        if (options.files) {
          calls.push('inject');
          assert.deepEqual(options.files, ['src/dom_tiles.js']);
          if (failFiles) throw new Error('boom');
          return [{ result: undefined }];
        }
        assert.equal(typeof options.func, 'function');
        // runs inside the page: must not depend on anything from this module
        assert.ok(!/MESSAGES|AUTHORIZED|REFERENCE|KIND_LABELS|import/.test(String(options.func)));
        const { withEntries, sectionLabel } = options.args[0];
        assert.equal(sectionLabel, SECTION_LABEL);
        calls.push(withEntries ? 'read-items' : 'read-identity');
        let wanted = items;
        if (!withEntries) wanted = (identityReads++ === 0 ? identity : after ?? identity);
        const value = typeof wanted === 'function' ? wanted() : wanted;
        if (value !== undefined) return [{ result: value }];
        return [{ result: { href: url, projection: withEntries ? projection : noItems(projection) } }];
      },
    }),
  };
  return { api: strict(api), calls };
}

const run = (options) => {
  const { api, calls } = fakeApi(options);
  return runPreview(api, { now: NOW }).then((model) => ({ model, calls }));
};
const states = (model) => Object.fromEntries(model.checks.map((c) => [c.id, c.ok]));
const ALL_OK = { dominio: true, pagina: true, curso: true, formato: true, secao: true };
const FULL_FLOW = ['query', 'inject', 'read-identity', 'read-items', 'read-identity'];

function assertSevenModules(model) {
  assert.equal(model.state, 'ok');
  assert.deepEqual(states(model), ALL_OK);
  assert.equal(model.section, 'Atividades Avaliativas');
  assert.equal(model.rows.length, 7);
  assert.equal(model.labels, 3);
  assert.deepEqual(model.byModtype.map((g) => [g.modtype, g.kind, g.classe, g.label, g.count]), [
    ['assign', 'assign', 'atividade', 'Tarefa', 5],
    ['groupselect', 'groupselect', 'atividade', 'Escolha de grupo', 1],
    ['resource_pdf', 'resource', 'material', 'Arquivo', 1],
  ]);
  assert.deepEqual(model.issues, []);
  assert.equal(model.comparison.matches, true);
  assert.equal(model.coverage.state, 'parcial');
}

test('section page (section.php): seven modules; identity read before and after the items', async () => {
  const { model, calls } = await run();
  assertSevenModules(model);
  assert.equal(model.mode, 'secao_pagina');
  assert.deepEqual(calls, FULL_FLOW);
  // what "Salvar" would send (kept in memory only): the validated snapshot and the reportable page
  assert.deepEqual(model.page, { kind: 'curso_bloco', route: '/ava/course/section.php?id' });
  assert.equal(model.snapshot.schema, 'campus-ai.academic/1');
  assert.equal(model.snapshot.materials.length + model.snapshot.activities.length, 7);
});

test('panel inside the course home (view.php, URL unchanged): seven modules', async () => {
  const { model, calls } = await run({ url: URL_HOME, projection: PANEL });
  assertSevenModules(model);
  assert.equal(model.mode, 'painel');
  assert.deepEqual(calls, FULL_FLOW);
  assert.deepEqual(model.page, { kind: 'curso_inicio', route: '/ava/course/view.php?id' });
  assert.equal(model.snapshot.activities[0].provenance.route, '/ava/course/view.php?id');
  assert.ok(model.coverage.reasons.some((r) => r.includes('painel aberto')));
  assert.ok(model.coverage.reasons.some((r) => r.includes('2 item(ns) oculto(s)')));
});

test('unauthorized address: nothing is injected', async () => {
  const urls = [
    'http://ead.aedb.br/ava/course/section.php?id=4242', 'https://ead.aedb.br.evil.test/ava/course/view.php?id=7653',
    'https://user@ead.aedb.br/ava/course/view.php?id=7653', 'https://ead.aedb.br:8443/ava/course/section.php?id=4242',
    'https://mail.google.com/mail/u/0/', 'chrome-extension://abcdefghijklmnopabcdefghijklmnop/src/popup.html', 'about:blank',
  ];
  for (const url of urls) {
    const { model, calls } = await run({ url });
    assert.equal(model.state, 'recusado', url);
    assert.equal(model.checks.find((c) => c.id === 'dominio').ok, false, url);
    assert.deepEqual(calls, ['query'], url);
    assert.equal(model.message, MESSAGES.dominio);
  }
});

test('wrong AEDB pages, another course in the URL and missing tab access: nothing is injected', async () => {
  const pages = {
    'https://ead.aedb.br/ava/login/index.php': MESSAGES.login,
    'https://ead.aedb.br/ava/course/view.php?id=9999': MESSAGES.curso_diferente,
    'https://ead.aedb.br/ava/mod/assign/view.php?id=90001': MESSAGES.modulo,
    'https://ead.aedb.br/ava/mod/groupselect/view.php?id=90006': MESSAGES.modulo,
    'https://ead.aedb.br/ava/calendar/view.php?view=month': MESSAGES.pagina,
    'https://ead.aedb.br/ava/course/section.php?id=4242&sesskey=x': MESSAGES.pagina,
    'https://ead.aedb.br/ava/course/view.php?id=7653&sesskey=x': MESSAGES.pagina,
  };
  for (const [url, message] of Object.entries(pages)) {
    const { model, calls } = await run({ url });
    assert.deepEqual([model.state, model.message, calls], ['recusado', message, ['query']], url);
  }
  for (const tabs of [[], [{}], [{ id: 11 }], new Error('x')]) {
    const { model, calls } = await run({ tabs });
    assert.equal(model.state, 'recusado');
    assert.deepEqual(calls, ['query']);
  }
  assert.equal((await run({ tabs: [{ id: 11 }] })).model.message, MESSAGES.sem_acesso);
});

test('identity refused before any item is read: course, Tiles, section, panel, dialog, coherence', async () => {
  const cases = [
    [URL_SECTION, { ...PAGE, courseId: '8888' }, 'curso', MESSAGES.curso_diferente],
    [URL_SECTION, { ...PAGE, courseId: '' }, 'curso', MESSAGES.curso_nao_confirmado],
    [URL_HOME, { ...PANEL, courseId: '8888' }, 'curso', MESSAGES.curso_diferente],
    [URL_SECTION, { ...PAGE, formatTiles: false }, 'formato', MESSAGES.formato],
    [URL_HOME, { ...PANEL, formatTiles: false }, 'formato', MESSAGES.formato],
    [URL_SECTION, { ...PAGE, sectionPage: false }, 'secao', MESSAGES.secao],
    [URL_SECTION, { ...PAGE, docTitle: 'Bloco: Trilhas de Aprendizagem | Curso | AVA' }, 'secao', MESSAGES.secao],
    [URL_SECTION, { ...PAGE, docTitle: 'AVA' }, 'secao', MESSAGES.secao],
    [URL_HOME, { ...PANEL, sectionName: 'Trilhas de Aprendizagem' }, 'secao', MESSAGES.secao],
    [URL_HOME, { ...PANEL, sectionId: '' }, 'secao', MESSAGES.secao],
    [URL_HOME, PAGE, 'secao', MESSAGES.modo_incoerente],          // view.php address, section-page structure
    [URL_SECTION, PANEL, 'secao', MESSAGES.modo_incoerente],      // section.php address, panel structure
    [URL_HOME, closed('painel_fechado'), 'secao', MESSAGES.painel_fechado],
    [URL_HOME, closed('tile_nao_encontrado'), 'secao', MESSAGES.tile_nao_encontrado],
    [URL_HOME, closed('tile_ambiguo'), 'secao', MESSAGES.tile_ambiguo],
    [URL_HOME, closed('tile_sem_vinculo'), 'secao', MESSAGES.tile_sem_vinculo],
    [URL_HOME, closed('paineis_multiplos'), 'secao', MESSAGES.paineis_multiplos],
    [URL_HOME, closed('painel_sem_vinculo'), 'secao', MESSAGES.painel_sem_vinculo],
    [URL_HOME, closed('dialogo_bloqueia'), 'secao', MESSAGES.dialogo_bloqueia],
    [URL_HOME, closed('motivo-inventado'), 'secao', MESSAGES.secao],
  ];
  for (const [url, projection, failed, message] of cases) {
    const { model, calls } = await run({ url, identity: { href: url, projection } });
    assert.equal(model.state, 'recusado', message);
    assert.equal(model.checks.find((c) => c.id === failed).ok, false, `${failed}: ${message}`);
    assert.equal(model.message, message);
    assert.deepEqual(calls, ['query', 'inject', 'read-identity'], 'items must not be read');
    assert.deepEqual(model.rows, []);
  }
  const { model } = await run({ url: URL_HOME, identity: { href: URL_HOME, projection: closed('painel_fechado') } });
  assert.equal(model.diagnostic.reason, 'painel_fechado');
  assert.equal(model.diagnostic.tiles, 5);
  // accents and case in the section name are tolerated
  const odd = { ...PAGE, docTitle: 'Bloco: ATIVIDADES  avaliativas | C | AVA' };
  assert.equal((await run({ projection: odd })).model.state, 'ok');
});

test('refusals and diagnostics never echo page content', async () => {
  const secret = 'Segredo-ZZZ-8888';
  let { model } = await run({ identity: { href: URL_SECTION, projection: { ...PAGE, courseId: '8888', docTitle: `Bloco: ${secret} | ${secret} | AVA` } } });
  assert.ok(!JSON.stringify(model).includes('ZZZ'));
  assert.ok(!JSON.stringify(model).includes('8888'));
  const hostile = closed('painel_fechado');
  hostile.diagnostic = { ...hostile.diagnostic, reason: '<img src=x>', tiles: 1e9, containers: [
    { tag: 'li<script>', classes: ['ok-token', '<b>x</b>', secret + ' x'], attrs: ['data-section', 'on error'], activities: 3, inDialog: 'yes' },
  ] };
  ({ model } = await run({ url: URL_HOME, identity: { href: URL_HOME, projection: hostile } }));
  assert.deepEqual(model.diagnostic.containers, [{ tag: '?', classes: ['ok-token'], attrs: ['data-section'], activities: 3, inDialog: false }]);
  assert.equal(model.diagnostic.reason, '');
  assert.equal(model.diagnostic.tiles, 9999);
});

test('the page or the panel changing during the read is detected', async () => {
  const login = 'https://ead.aedb.br/ava/login/index.php';
  let r = await run({ identity: { href: login, projection: PAGE } });
  assert.deepEqual([r.model.state, r.calls], ['recusado', ['query', 'inject', 'read-identity']]);
  r = await run({ items: { href: login, projection: PAGE } });
  assert.deepEqual([r.model.state, r.model.message, r.model.rows], ['recusado', MESSAGES.mudou, []]);
  r = await run({ items: { href: URL_SECTION, projection: { ...PAGE, courseId: '8888' } } });
  assert.equal(r.model.message, MESSAGES.mudou);
  // another panel (or more items) appeared between the reads
  r = await run({ url: URL_HOME, projection: PANEL, after: { href: URL_HOME, projection: noItems({ ...PANEL, panelKey: 'painel:4242:3:11' }) } });
  assert.deepEqual([r.model.state, r.model.message], ['recusado', MESSAGES.mudou]);
  r = await run({ url: URL_HOME, projection: PANEL, items: { href: URL_HOME, projection: { ...PANEL, panelKey: 'painel:9999:7:10' } } });
  assert.equal(r.model.message, MESSAGES.mudou);
  r = await run({ url: URL_HOME, projection: PANEL, after: { href: URL_HOME, projection: closed('painel_fechado') } });
  assert.equal(r.model.message, MESSAGES.mudou);
});

test('failures degrade to a fixed message', async () => {
  assert.equal((await run({ failFiles: true })).model.message, MESSAGES.leitura_falhou);
  assert.equal((await run({ identity: () => { throw new Error('x'); } })).model.message, MESSAGES.leitura_falhou);
  for (const bad of [null, 'x', { href: 7 }, { projection: PAGE }]) {
    const r = await run({ identity: bad });
    assert.equal(r.model.state, 'recusado');
    assert.equal(r.model.rows.length, 0);
  }
  assert.equal((await run({ items: { href: URL_SECTION, projection: 'x' } })).model.state, 'recusado');
});

test('labels ignored; duplicated ids, missing titles/ids and unknown types are reported, never converted', async () => {
  const entries = [
    { label: true }, mod(1, 'Tarefa A'), mod(1, 'Tarefa A repetida'), { label: true },
    { modtype: 'assign', cmid: '2', title: '   ', hrefs: [] },
    { modtype: 'assign', cmid: '', title: 'Sem id', hrefs: [] },
    { modtype: 'script', cmid: '3', title: 'Tipo desconhecido', hrefs: [] },
    mod(4, 'Arquivo', 'resource_pdf'), mod(5, 'Grupo', 'groupselect'), { label: true },
  ];
  const { model } = await run({ items: { href: URL_SECTION, projection: { ...PAGE, entries } } });
  assert.equal(model.state, 'ok');
  assert.equal(model.labels, 3);
  assert.deepEqual(model.rows.map((r) => r.cmid), ['1', '4', '5']);
  assert.deepEqual(model.issues.map((i) => [i.position, i.code, i.modtype, i.cmid]), [
    [2, 'repetido', 'assign', '1'], [3, 'sem_titulo', 'assign', '2'], [4, 'sem_id', 'assign', ''],
    [5, 'sem_tipo', 'script', '3'],
  ]);
  assert.ok(model.issues.every((i) => !('title' in i)));
  assert.equal(model.comparison.matches, false);
  assert.ok(model.comparison.notes.some((n) => n.includes('3 válido(s) e 4 com problema')));
  assert.notEqual(model.coverage.state, 'completa');
});

test('a different count is reported as a difference, without guessing the cause', async () => {
  const entries = PAGE.entries.filter((e) => e.cmid !== '90003');
  const { model } = await run({ items: { href: URL_SECTION, projection: { ...PAGE, entries } } });
  assert.equal(model.rows.length, 6);
  assert.deepEqual(model.comparison.differences, [{ kind: 'assign', label: 'Tarefa', expected: 5, found: 4 }]);
  assert.equal(model.comparison.matches, false);
  assert.ok(model.comparison.notes.some((n) => n.includes('não tem como determinar a causa')));
});

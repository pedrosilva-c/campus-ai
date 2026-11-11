import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  MAX_ENTRIES, PROJECTION_ID, buildTilesSnapshot, canonicalUrl, kindOf, titleTag,
} from '../src/tiles_adapter.js';

const golden = JSON.parse(readFileSync(new URL('../../tests/fixtures/companion/tiles_projection.json', import.meta.url), 'utf8'));
const NOW = new Date('2026-11-05T20:00:00.123Z');

const item = (cmid, title, modtype = 'assign', hrefs) => ({
  modtype, cmid: String(cmid), title,
  hrefs: hrefs ?? [`https://ead.aedb.br/ava/mod/${modtype.split('_')[0]}/view.php?id=${cmid}`],
});
const LABEL = { label: true };
const proj = (entries, over = {}) => ({ ...golden, entries, ...over });
const build = (p, now = NOW) => buildTilesSnapshot(p, { now });
const byCmid = (snap) => Object.fromEntries([...snap.materials, ...snap.activities].map((r) => [r.uid.split(':').pop(), r]));

test('golden projection builds the expected snapshot', () => {
  const out = build(golden);
  assert.equal(out.ok, true);
  const s = out.snapshot;
  assert.equal(s.schema, 'campus-ai.academic/1');
  assert.equal(s.generated_at, '2026-11-05T20:00:00Z');
  assert.deepEqual(s.scope, ['moodle:course:7653']);
  assert.equal(s.courses[0].name, '4º P CURSO FICTÍCIO - Modelagem Fictícia');
  assert.equal(s.sections[0].name, 'Atividades Avaliativas');
  assert.equal(s.sections[0].uid, 'moodle:course:7653:section:id-4242');
  assert.equal(s.materials.length, 1);
  assert.equal(s.activities.length, 6);
  assert.deepEqual(out.summary, { materials: 1, activities: 6, labels: 3, inferred: 4, skipped: { sem_tipo: 0, sem_id: 0, sem_titulo: 0, repetido: 0, truncado: 0 } });
  assert.equal(s.coverage.state, 'parcial');
  assert.deepEqual(s.events, []);
  assert.deepEqual(s.announcements, []);
});

test('uids reuse the scheme of the existing connectors', () => {
  const s = build(golden).snapshot;
  for (const record of [...s.materials, ...s.activities]) {
    assert.match(record.uid, /^moodle:course:7653:module:[1-9][0-9]*$/);
  }
});

test('resource subtype is a material; groupselect is an activity; labels are never rows', () => {
  const rows = byCmid(build(golden).snapshot);
  assert.equal(rows['90004'].kind, 'resource');
  assert.equal(rows['90006'].kind, 'groupselect');
  assert.equal(Object.keys(rows).length, 7);
  assert.equal(kindOf('resource_pdf'), 'resource');
  assert.equal(kindOf('resource'), 'resource');
  for (const bad of ['resource_', 'resource_PDF', 'resourceX', 'label', '', 'assign_x', 'script', null, undefined, 7]) {
    assert.equal(kindOf(bad), '', String(bad));
  }
});

test('AV groups: stated in the title, else inherited from the block (and marked as such)', () => {
  const rows = byCmid(build(golden).snapshot);
  const view = (id) => [rows[id].assessment, rows[id].assessment_basis, rows[id].confidence];
  assert.deepEqual(view('90001'), ['AV1', 'posicao', 'media']);
  assert.deepEqual(view('90002'), ['AV1', 'posicao', 'media']);
  assert.deepEqual(view('90003'), ['AV1', 'posicao', 'media']);
  assert.deepEqual(view('90004'), ['AV1', 'titulo', 'alta']);
  assert.deepEqual(view('90005'), ['AV1', 'titulo', 'alta']);
  assert.deepEqual(view('90006'), ['AV2', 'titulo', 'alta']);
  assert.deepEqual(view('90007'), ['AV2', 'posicao', 'media']);
});

test('ambiguous blocks and titles stay ungrouped', () => {
  const mixed = build(proj([item(1, 'AV1 - parte'), item(2, 'AV2 - parte'), item(3, 'Sem marca')])).snapshot;
  const rows = byCmid(mixed);
  assert.deepEqual([rows['1'].assessment, rows['2'].assessment, rows['3'].assessment, rows['3'].assessment_basis],
    ['AV1', 'AV2', '', '']);
  const both = byCmid(build(proj([item(1, 'Substitutiva de AV1 e AV2'), item(2, 'Outra')])).snapshot);
  assert.deepEqual([both['1'].assessment, both['2'].assessment], ['', '']);
  const none = byCmid(build(proj([item(1, 'Exercício'), LABEL, item(2, 'Outro')])).snapshot);
  assert.deepEqual([none['1'].assessment_basis, none['2'].assessment_basis], ['', '']);
});

test('inference never crosses a label separator', () => {
  const rows = byCmid(build(proj([item(1, 'AV1 - prova'), LABEL, item(2, 'Sem marca')])).snapshot);
  assert.equal(rows['2'].assessment, '');
});

test('AV tag recognition', () => {
  const cases = {
    'AV1-Disciplina-9999 - Resumo': 'AV1', 'av 2': 'AV2', 'Material AV 3 revisado': 'AV3', 'Prova_AV2.pdf': 'AV2',
    'Trabalho de AV-1': 'AV1', 'AV10': '', 'CAV1': '', 'AVALIAÇÃO 1': '', 'Gravação 1': '', 'AV0': '', 'AV1 e AV2': '',
  };
  for (const [title, expected] of Object.entries(cases)) assert.equal(titleTag(title), expected, title);
});

test('addresses are rebuilt from parts and must match module and id', () => {
  const ok = 'https://ead.aedb.br/ava/mod/assign/view.php?id=7';
  assert.equal(canonicalUrl([ok + '&forceview=1#x'], 'assign', '7'), ok);
  assert.equal(canonicalUrl(['https://ead.aedb.br/ava/mod/forum/view.php?id=7', ok], 'assign', '7'), ok);
  const rejected = [
    'http://ead.aedb.br/ava/mod/assign/view.php?id=7', 'https://ead.aedb.br.evil.test/ava/mod/assign/view.php?id=7',
    'https://u:p@ead.aedb.br/ava/mod/assign/view.php?id=7', 'https://ead.aedb.br:8443/ava/mod/assign/view.php?id=7',
    'https://ead.aedb.br/ava/mod/assign/view.php?id=8', 'https://ead.aedb.br/ava/mod/assign/view.php?id=7&id=8',
    'https://ead.aedb.br/ava/mod/quiz/view.php?id=7', 'https://ead.aedb.br/ava/mod/assign/view.php',
    'https://ead.aedb.br/ava/pluginfile.php/1/mod_resource/content/1/x.pdf', 'javascript:alert(1)', '', null,
  ];
  for (const raw of rejected) assert.equal(canonicalUrl([raw], 'assign', '7'), '', String(raw));
  assert.equal(canonicalUrl('not-a-list', 'assign', '7'), '');
  assert.equal(build(golden).snapshot.activities.find((a) => a.uid.endsWith(':90003')).url, '');
  assert.equal(build(golden).snapshot.activities.find((a) => a.uid.endsWith(':90002')).url,
    'https://ead.aedb.br/ava/mod/assign/view.php?id=90002');
});

test('refuses what it cannot confirm and sends nothing', () => {
  const refusals = [
    [null, 'projecao_invalida'], ['x', 'projecao_invalida'], [{}, 'projecao_invalida'],
    [{ ...golden, projection: 'outro' }, 'projecao_invalida'],
    [{ ...golden, entries: 'x' }, 'projecao_invalida'],
    [{ ...golden, entries: new Array(MAX_ENTRIES + 1).fill(LABEL) }, 'projecao_invalida'],
    [{ ...golden, courseId: '' }, 'identidade_nao_confirmada'],
    [{ ...golden, courseId: '0' }, 'identidade_nao_confirmada'],
    [{ ...golden, courseId: 7653 }, 'identidade_nao_confirmada'],
    [{ ...golden, formatTiles: false }, 'formato_nao_suportado'],
    [{ ...golden, sectionPage: 'true' }, 'formato_nao_suportado'],
    [{ ...golden, sectionId: '' }, 'secao_sem_id'],
    [{ ...golden, sectionId: '12a' }, 'secao_sem_id'],
  ];
  for (const [input, code] of refusals) assert.deepEqual(build(input), { ok: false, code }, code);
  assert.equal(PROJECTION_ID, golden.projection);
});

test('malformed entries are skipped and counted, never converted', () => {
  const out = build(proj([
    item(1, 'Bom'), item(1, 'Repetido'), null, 'x', [], { modtype: 'script', cmid: '2', title: 'T' },
    { modtype: 'assign', cmid: 'abc', title: 'T' }, { modtype: 'assign', cmid: '0', title: 'T' },
    { modtype: 'assign', cmid: 3, title: 'T' }, { modtype: 'assign', cmid: '4', title: '  \u0000 ' },
    { modtype: 'assign', cmid: '5' },
  ]));
  assert.equal(out.snapshot.activities.length, 1);
  assert.deepEqual(out.summary.skipped, { sem_tipo: 4, sem_id: 3, sem_titulo: 2, repetido: 1, truncado: 0 });
});

test('titles are cleaned and bounded', () => {
  const out = build(proj([item(1, 'Com\u0000controle\u0007 e\n\tespaços   múltiplos'), item(2, 'x'.repeat(900))]));
  const rows = byCmid(out.snapshot);
  assert.equal(rows['1'].title, 'Com controle e espaços múltiplos');
  assert.equal(rows['2'].title.length, 400);
  assert.equal(out.summary.skipped.truncado, 1);
});

test('degenerate pages never become "completa"', () => {
  const out = build(proj([LABEL, LABEL]));
  assert.equal(out.snapshot.coverage.state, 'nao_validada');
  assert.equal(out.snapshot.sources[0].status, 'nao_verificado');
  assert.ok(out.snapshot.coverage.reasons.some((r) => r.includes('não validada')));
  for (const entries of [golden.entries, [item(1, 'AV1')]]) {
    assert.notEqual(build(proj(entries)).snapshot.coverage.state, 'completa');
  }
});

test('items carry no invented facts', () => {
  const s = build(golden).snapshot;
  for (const a of s.activities) {
    assert.equal(a.submission, 'desconhecido');
    assert.deepEqual(a.deadlines, []);
    assert.equal(a.verification, 'confirmado');
    assert.equal(a.provenance.source, 'companion');
    assert.equal(a.provenance.route, '/ava/course/section.php?id');
  }
});

test('reasons never repeat page text', () => {
  const secret = 'Título-sigiloso-ZZZ';
  const out = build(proj([item(1, secret), { modtype: 'script', cmid: '2', title: secret }], { docTitle: `Bloco: ${secret} | ${secret} | AVA` }));
  assert.ok(!JSON.stringify(out.snapshot.coverage.reasons).includes('sigiloso'));
  assert.ok(!JSON.stringify(out.snapshot.sources).includes('sigiloso'));
});

test('panel mode: name from the tile, route of the course home, hidden items noted; other modes refused', () => {
  const panel = { ...golden, mode: 'painel', sectionPage: false, sectionName: 'Atividades Avaliativas',
    docTitle: 'Curso: 4º P CURSO FICTÍCIO - Modelagem Fictícia | AVA', diagnostic: { ...golden.diagnostic, hiddenActivities: 2 } };
  const out = build(panel);
  assert.equal(out.ok, true);
  const s = out.snapshot;
  assert.equal(s.sections[0].name, 'Atividades Avaliativas');
  assert.equal(s.courses[0].name, '4º P CURSO FICTÍCIO - Modelagem Fictícia');
  assert.equal(s.activities[0].provenance.route, '/ava/course/view.php?id');
  // same records (and uids) whichever way the section was shown: deduplication works across modes
  const uids = (snap) => [...snap.materials, ...snap.activities].map((r) => r.uid).sort();
  assert.deepEqual(uids(s), uids(build(golden).snapshot));
  assert.equal(s.sections[0].uid, build(golden).snapshot.sections[0].uid);
  assert.equal(out.rows.length, 7);
  assert.ok(s.coverage.reasons.some((r) => r.includes('painel aberto')));
  assert.ok(s.coverage.reasons.some((r) => r.includes('2 item(ns) oculto(s)')));
  for (const mode of ['nenhum', '', undefined, 'outro']) {
    assert.deepEqual(build({ ...golden, mode }), { ok: false, code: 'formato_nao_suportado' }, String(mode));
  }
});

test('missing or odd page title degrades honestly', () => {
  const s = build(proj(golden.entries, { docTitle: 'AVA' })).snapshot;
  assert.equal(s.sections[0].name, 'Seção sem nome');
  assert.equal(s.sections[0].verification, 'parcial');
  assert.equal(s.sections[0].confidence, 'baixa');
  assert.equal(s.courses[0].name, 'Disciplina 7653');
  assert.ok(s.coverage.reasons.some((r) => r.includes('nome da seção')));
});

test('truncated projections are flagged', () => {
  assert.ok(build(proj(golden.entries, { truncated: true })).snapshot.coverage.reasons.some((r) => r.includes('limite')));
});

test('output is plain JSON-safe data and does not mutate the input', () => {
  const copy = structuredClone(golden);
  const out = build(golden);
  assert.deepEqual(golden, copy);
  assert.deepEqual(JSON.parse(JSON.stringify(out.snapshot)), out.snapshot);
});

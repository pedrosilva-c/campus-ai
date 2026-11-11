import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { detailRecord, dueStateOf, situationOf, submissionOf, wallToEpoch } from '../src/deadlines.js';

const shared = JSON.parse(readFileSync(new URL('../../tests/fixtures/companion/situations.json', import.meta.url), 'utf8'));
const NOW = new Date(shared.now);

test('the shared situation cases (same file as the Python mirror)', () => {
  for (const c of shared.cases) assert.equal(situationOf(c.kind, c.detail, c.deadlines, NOW), c.expected, c.name);
});

test('wall time is America/Sao_Paulo (UTC-03:00); a date alone ends at 23:59', () => {
  assert.equal(wallToEpoch('2026-11-10T09:00'), Date.parse('2026-11-10T12:00:00Z'));
  assert.equal(wallToEpoch('2026-11-10'), Date.parse('2026-11-11T02:59:00Z'));
  for (const bad of ['', '10/11/2026', '2026-11-10T09:00Z', '2026-11-10T09:00:00', null]) assert.ok(Number.isNaN(wallToEpoch(bad)), String(bad));
});

test('a page that failed never states anything: unknown stays unknown', () => {
  for (const result of ['inacessivel', 'redirecionado', 'tempo_esgotado', 'falha_rede', 'pagina_nao_reconhecida', 'nao_consultada']) {
    const r = detailRecord('assign', { result }, '2026-11-10T12:00:00Z');
    assert.deepEqual(r.deadlines, []);
    assert.equal(r.submission, 'desconhecido');
    assert.deepEqual([r.detail.result, r.detail.submission_state, r.detail.grading_state, r.detail.attempt_state, r.detail.due_state],
      [result, 'desconhecido', 'desconhecido', 'desconhecido', 'nao_verificado'], result);
  }
  const junk = detailRecord('assign', { result: '<b>x</b>' }, '2026-11-10T12:00:00Z');
  assert.equal(junk.detail.result, 'falha_rede');
  const okWithoutFacts = detailRecord('assign', { result: 'ok' }, '2026-11-10T12:00:00Z');
  assert.equal(okWithoutFacts.detail.result, 'estrutura_desconhecida');
});

test('due state: a date, an unreadable date, explicitly no date, or not verified', () => {
  const facts = (dates, structure = true) => ({ structure, dates, submission: 'sem_envio', grading: 'nao_avaliado', attempt: 'nao_se_aplica' });
  assert.equal(dueStateOf('assign', facts([{ kind: 'entrega', at: '2026-11-12T23:59', raw: 'x' }])), 'definido');
  assert.equal(dueStateOf('assign', facts([{ kind: 'entrega', at: '', raw: 'quando o professor avisar' }])), 'nao_interpretado');
  assert.equal(dueStateOf('assign', facts([{ kind: 'abertura', at: '2026-11-01T00:00', raw: 'x' }])), 'sem_prazo');
  assert.equal(dueStateOf('assign', facts([], false)), 'nao_verificado');
  assert.equal(dueStateOf('quiz', facts([{ kind: 'entrega', at: '2026-11-12T23:59', raw: 'x' }])), 'sem_prazo');   // quiz: closing date
  const record = detailRecord('assign', { result: 'ok', facts: facts([{ kind: 'entrega', at: '2026-11-12T23:59', raw: 'quinta-feira, 12 nov. 2026, 23:59' },
    { kind: 'limite', at: '2026-11-14T23:59', raw: 'sábado, 14 nov. 2026, 23:59' }, { kind: 'invalido', at: '2026-01-01', raw: 'x' }]) }, '2026-11-10T12:00:00Z');
  assert.deepEqual(record.deadlines.map((d) => [d.kind, d.at, d.timezone_explicit]), [['entrega', '2026-11-12T23:59', false], ['limite', '2026-11-14T23:59', false]]);
  assert.equal(record.detail.timezone, 'America/Sao_Paulo');
  assert.equal(record.submission, 'nao_enviado');
});

test('the coarse contract field follows the page', () => {
  const d = (over) => ({ result: 'ok', submission_state: 'desconhecido', grading_state: 'desconhecido', attempt_state: 'nao_se_aplica', ...over });
  assert.equal(submissionOf(d({ submission_state: 'enviado', grading_state: 'avaliado' })), 'avaliado');
  assert.equal(submissionOf(d({ submission_state: 'enviado' })), 'enviado');
  assert.equal(submissionOf(d({ submission_state: 'rascunho' })), 'nao_enviado');
  assert.equal(submissionOf(d({ attempt_state: 'finalizada' })), 'enviado');
  assert.equal(submissionOf(d({ attempt_state: 'em_andamento' })), 'nao_enviado');
  assert.equal(submissionOf(d({})), 'desconhecido');
  assert.equal(submissionOf({ ...d({ submission_state: 'enviado' }), result: 'inacessivel' }), 'desconhecido');
});

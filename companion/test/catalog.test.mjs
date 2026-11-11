import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ACADEMIC_ORDER, buildPlan, classifyTile, roleOf } from '../src/catalog.js';
import { AUTHORIZED_SECTIONS } from '../src/preview.js';

const tile = (label, over = {}) => ({ label, linkKind: 'secao', links: 1, sameTab: true, clickable: true, visible: true,
  sectionId: '4242', number: '3', ...over });
const COURSE = ['Informações da Disciplina', 'Trilhas de Aprendizagem', 'Atividades Avaliativas', 'Feedback das Aulas',
  'Fale com o Professor'].map((label, i) => tile(label, { position: i + 1, sectionId: String(4240 + i), number: String(i + 1) }));
const BOTH = ['atividades avaliativas', 'trilhas de aprendizagem'];

test('only Atividades Avaliativas is authorized in this version', () => {
  assert.deepEqual([...AUTHORIZED_SECTIONS], ['atividades avaliativas']);
});

test('the five real tiles are classified as expected (production authorization)', () => {
  const plan = buildPlan({ tiles: COURSE });
  assert.deepEqual(plan.entries.map((e) => [e.label, e.role, e.decision]), [
    ['Informações da Disciplina', 'informativa', 'ignorada'],
    ['Trilhas de Aprendizagem', 'academica', 'nao_autorizada'],
    ['Atividades Avaliativas', 'academica', 'ler'],
    ['Feedback das Aulas', 'comunicacao', 'bloqueada'],
    ['Fale com o Professor', 'comunicacao', 'bloqueada'],
  ]);
  assert.deepEqual(plan.toRead.map((e) => e.display), ['Atividades Avaliativas']);
});

test('with Trilhas authorized the order is fixed: Atividades Avaliativas first, then Trilhas', () => {
  const reversed = buildPlan({ tiles: [...COURSE].reverse() }, BOTH);
  assert.deepEqual(reversed.toRead.map((e) => e.display), ['Atividades Avaliativas', 'Trilhas de Aprendizagem']);
  assert.deepEqual(ACADEMIC_ORDER, ['atividades avaliativas', 'trilhas de aprendizagem']);
});

test('communication, dangerous wording, external links and unusable tiles are never opened', () => {
  const blocked = [
    tile('Fale com o Professor'), tile('Feedback das Aulas'),
    tile('Trilhas de Aprendizagem — Enviar trabalho'), tile('Trilhas de Aprendizagem', { linkKind: 'externo' }),
    tile('Trilhas de Aprendizagem', { linkKind: 'outro' }), tile('Trilhas de Aprendizagem', { linkKind: 'nenhum' }),
    tile('Trilhas de Aprendizagem', { sameTab: false }), tile('Trilhas de Aprendizagem', { clickable: false }),
    tile('Trilhas de Aprendizagem', { visible: false }), tile('Trilhas de Aprendizagem', { links: 2 }),
    tile('Trilhas de Aprendizagem', { sectionId: '' }),
  ];
  for (const t of blocked) assert.equal(classifyTile(t, BOTH).decision, 'bloqueada', JSON.stringify(t));
  assert.equal(classifyTile(tile('Avisos'), BOTH).decision, 'ignorada');
  assert.equal(classifyTile(tile('Glossário da turma'), BOTH).decision, 'desconhecida');
  assert.equal(roleOf('Atividades Avaliativas e Trilhas de Aprendizagem').role, 'desconhecida');   // two names: ambiguous
});

test('two tiles claiming the same section are both blocked', () => {
  const plan = buildPlan({ tiles: [tile('Atividades Avaliativas'), tile('Atividades Avaliativas (cópia)')] }, BOTH);
  assert.deepEqual(plan.entries.map((e) => [e.decision, e.reason]), [['bloqueada', 'duplicado'], ['bloqueada', 'duplicado']]);
  assert.deepEqual(plan.toRead, []);
});

test('malformed catalogs give an empty plan', () => {
  for (const bad of [null, {}, { tiles: 'x' }, { tiles: [null, 7, 'x'] }]) assert.deepEqual(buildPlan(bad).toRead, []);
});

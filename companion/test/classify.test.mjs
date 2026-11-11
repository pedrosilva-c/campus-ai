import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { classifyPage } from '../src/classify.js';

const cases = JSON.parse(readFileSync(new URL('../../tests/fixtures/companion/page_cases.json', import.meta.url), 'utf8'));

test('shared page cases (same fixture as the Python host)', () => {
  for (const c of cases) {
    const got = classifyPage(c.url);
    assert.deepEqual({ kind: got.kind, route: got.route, moodle_id: got.moodleId },
      { kind: c.kind, route: c.route, moodle_id: c.moodle_id }, c.url);
  }
});

test('route never carries values', () => {
  const got = classifyPage('https://ead.aedb.br/ava/calendar/export_execute.php?userid=1&authtoken=SEGREDO');
  assert.ok(!got.route.includes('SEGREDO'));
  assert.ok(!/[0-9]/.test(got.route));
});

test('result is frozen', () => {
  assert.ok(Object.isFrozen(classifyPage('https://ead.aedb.br/ava/my/')));
});

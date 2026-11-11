import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  MAX_MESSAGE_BYTES, PROTOCOL_ID, buildHello, buildPageReport, isReportable, readReply,
} from '../src/protocol.js';

const PAGE = { kind: 'curso_inicio', route: '/ava/course/view.php?id' };
const SESSION = 'f'.repeat(32);

test('hello envelope', () => {
  const hello = buildHello('req-00000001');
  assert.deepEqual(Object.keys(hello).sort(), ['payload', 'protocol', 'request_id', 'session', 'type']);
  assert.equal(hello.protocol, PROTOCOL_ID);
  assert.deepEqual(hello.payload.capabilities, ['page_report']);
});

test('request ids are unique and well formed', () => {
  const a = buildHello().request_id;
  const b = buildHello().request_id;
  assert.notEqual(a, b);
  assert.match(a, /^[A-Za-z0-9-]{8,64}$/);
});

test('only course pages are reportable', () => {
  assert.ok(isReportable(PAGE));
  assert.ok(!isReportable({ kind: 'modulo_atividade', route: '/ava/mod/assign/view.php?id' }));
  assert.ok(!isReportable({ kind: 'curso_inicio', route: '/ava/mod/assign/view.php?id' }));
  assert.ok(!isReportable({ kind: '__proto__', route: undefined }));
  assert.throws(() => buildPageReport(SESSION, { kind: 'login', route: '/ava/login/index.php' }, {}));
});

test('session token is required', () => {
  assert.throws(() => buildPageReport('', PAGE, {}), /sessao_invalida/);
  assert.throws(() => buildPageReport('x'.repeat(32), PAGE, {}), /sessao_invalida/);
});

test('size cap', () => {
  assert.throws(() => buildPageReport(SESSION, PAGE, { blob: 'x'.repeat(MAX_MESSAGE_BYTES) }), RangeError);
});

test('host replies are validated', () => {
  assert.equal(readReply(null).type, 'rejected');
  assert.equal(readReply({ protocol: 'other', type: 'ack' }).type, 'rejected');
  assert.equal(readReply({ protocol: PROTOCOL_ID, type: 'execute' }).type, 'rejected');
  assert.equal(readReply({ protocol: PROTOCOL_ID, type: 'welcome', session: 'bad' }).type, 'rejected');
  assert.equal(readReply({ protocol: PROTOCOL_ID, type: 'welcome', session: SESSION }).type, 'welcome');
});

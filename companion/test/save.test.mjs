import { test } from 'node:test';
import assert from 'node:assert/strict';
import { HOST_NAME, PROTOCOL_ID } from '../src/protocol.js';
import { saveSnapshot } from '../src/save.js';

const PAGE = { kind: 'curso_inicio', route: '/ava/course/view.php?id' };
const SNAPSHOT = { schema: 'campus-ai.academic/1' };
const SESSION = 'e'.repeat(32);
const RESULT = { run: 3, itens: 7, novos: 1, alterados: 0, ausentes: 0, reaparecidos: 0, inalterados: 6 };

// A fake native port driven by `script(message, port)`; records what the extension sent.
function fakeApi(script, { lastError = null, connectThrows = false } = {}) {
  const sent = [];
  const listeners = { message: [], disconnect: [] };
  const state = { disconnected: false, names: [] };
  const port = {
    onMessage: { addListener: (f) => listeners.message.push(f) },
    onDisconnect: { addListener: (f) => listeners.disconnect.push(f) },
    postMessage: (m) => { sent.push(m); queueMicrotask(() => script(m, port)); },
    disconnect: () => { state.disconnected = true; },
    reply: (m) => listeners.message.forEach((f) => f(m)),
    drop: () => listeners.disconnect.forEach((f) => f()),
  };
  const api = {
    runtime: {
      get lastError() { return lastError; },
      connectNative: (name) => { state.names.push(name); if (connectThrows) throw new Error('x'); return port; },
    },
  };
  return { api, sent, state };
}

const welcome = (m, port) => port.reply({ protocol: PROTOCOL_ID, type: 'welcome', request_id: m.request_id, session: SESSION });
const honestHost = (m, port) => {
  if (m.type === 'hello') return welcome(m, port);
  return port.reply({ protocol: PROTOCOL_ID, type: 'ack', request_id: m.request_id, saved: true, result: RESULT });
};
const save = (api, opts) => saveSnapshot(api, PAGE, SNAPSHOT, { timeoutMs: 200, ...opts });

test('saved only after the host acknowledges this exact report with saved:true', async () => {
  const { api, sent, state } = fakeApi(honestHost);
  const outcome = await save(api);
  assert.deepEqual(outcome, { saved: true, code: 'salvo', result: RESULT });
  assert.deepEqual(state.names, [HOST_NAME]);
  assert.deepEqual(sent.map((m) => m.type), ['hello', 'page_report']);
  assert.equal(sent[1].session, SESSION);
  assert.deepEqual(sent[1].payload, { page: PAGE, snapshot: SNAPSHOT });
  assert.equal(state.disconnected, true);
});

test('preview build (no nativeMessaging) says the local integration is unavailable', async () => {
  for (const api of [{}, { runtime: {} }, null, undefined]) {
    assert.deepEqual(await saveSnapshot(api, PAGE, SNAPSHOT), { saved: false, code: 'indisponivel_nesta_versao' });
  }
});

test('host not installed, not answering, dropping or slow: never "saved"', async () => {
  const notFound = fakeApi((m, port) => port.drop(), { lastError: { message: 'Specified native messaging host not found.' } });
  assert.deepEqual(await save(notFound.api), { saved: false, code: 'host_nao_instalado' });
  const exited = fakeApi((m, port) => port.drop(), { lastError: { message: 'Native host has exited.' } });
  assert.deepEqual(await save(exited.api), { saved: false, code: 'host_indisponivel' });
  const dropsAfterReport = fakeApi((m, port) => (m.type === 'hello' ? welcome(m, port) : port.drop()));
  assert.deepEqual(await save(dropsAfterReport.api), { saved: false, code: 'desconectado' });
  const silent = fakeApi(() => {});
  assert.deepEqual(await save(silent.api), { saved: false, code: 'tempo_esgotado' });
  assert.equal(silent.state.disconnected, true);
  assert.deepEqual(await save(fakeApi(() => {}, { connectThrows: true }).api), { saved: false, code: 'host_indisponivel' });
});

test('rejections keep the host code (sanitized) and claim nothing', async () => {
  for (const [code, expected] of [['falha_persistencia', 'falha_persistencia'], ['sem_permissao', 'sem_permissao'],
    ['disciplina_nao_autorizada', 'disciplina_nao_autorizada'], ['<b>x</b>', 'recusado']]) {
    const { api } = fakeApi((m, port) => (m.type === 'hello' ? welcome(m, port)
      : port.reply({ protocol: PROTOCOL_ID, type: 'rejected', request_id: m.request_id, code })));
    assert.deepEqual(await save(api), { saved: false, code: expected });
  }
});

test('an ack that does not prove persistence is not accepted', async () => {
  const acks = [
    (m) => ({ protocol: PROTOCOL_ID, type: 'ack', request_id: m.request_id, saved: false }),
    (m) => ({ protocol: PROTOCOL_ID, type: 'ack', request_id: m.request_id, saved: true }),
    (m) => ({ protocol: PROTOCOL_ID, type: 'ack', request_id: m.request_id, saved: true, result: { ...RESULT, novos: -1 } }),
    (m) => ({ protocol: PROTOCOL_ID, type: 'ack', request_id: m.request_id, saved: true, result: { ...RESULT, run: '3' } }),
  ];
  for (const ack of acks) {
    const { api } = fakeApi((m, port) => (m.type === 'hello' ? welcome(m, port) : port.reply(ack(m))));
    assert.deepEqual(await save(api), { saved: false, code: 'sem_confirmacao' });
  }
  const wrongId = fakeApi((m, port) => (m.type === 'hello' ? welcome(m, port)
    : port.reply({ protocol: PROTOCOL_ID, type: 'ack', request_id: 'req-outro-id', saved: true, result: RESULT })));
  assert.deepEqual(await save(wrongId.api), { saved: false, code: 'resposta_invalida' });
  const early = fakeApi((m, port) => port.reply({ protocol: PROTOCOL_ID, type: 'ack', request_id: m.request_id, saved: true, result: RESULT }));
  assert.deepEqual(await save(early.api), { saved: false, code: 'resposta_invalida' });   // ack before any report
  const foreign = fakeApi((m, port) => port.reply({ protocol: 'outro', type: 'welcome', session: SESSION }));
  assert.deepEqual(await save(foreign.api), { saved: false, code: 'resposta_invalida' });
});

test('a page that is not reportable or a snapshot too big is never sent', async () => {
  const bad = fakeApi(honestHost);
  const outcome = await saveSnapshot(bad.api, { kind: 'modulo_atividade', route: '/ava/mod/assign/view.php?id' }, SNAPSHOT, { timeoutMs: 200 });
  assert.deepEqual(outcome, { saved: false, code: 'pagina_nao_reportavel' });
  assert.deepEqual(bad.sent.map((m) => m.type), ['hello']);
  const big = fakeApi(honestHost);
  const huge = await saveSnapshot(big.api, PAGE, { blob: 'x'.repeat(600 * 1024) }, { timeoutMs: 200 });
  assert.deepEqual(huge, { saved: false, code: 'grande_demais' });
});

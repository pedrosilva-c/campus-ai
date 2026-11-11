// Campus AI Companion — "Salvar no Campus AI": sends ONE already-previewed snapshot to the local Windows
// app through Chrome Native Messaging, and only after the student clicks the button.
//
// This is the only file that opens a native port. It needs the `nativeMessaging` permission, which exists
// only in the integration build (python -m campus_ai.companion_build); the preview build reports that the
// local integration is not available. `saved: true` is returned ONLY when the host acknowledges this exact
// report with `saved: true` and well-formed numbers, which the host sends after its SQLite COMMIT.
// Nothing is retried, stored or logged here.
import { HOST_NAME, buildHello, buildPageReport, readReply } from './protocol.js';

export const SAVE_TIMEOUT_MS = 15000;
const CODE = /^[a-z_]{1,40}$/;
const RESULT_KEYS = ['run', 'itens', 'novos', 'alterados', 'ausentes', 'reaparecidos', 'inalterados'];

function parseResult(reply) {
  const result = reply.result;
  if (reply.saved !== true || !result || typeof result !== 'object') return null;
  const out = {};
  for (const key of RESULT_KEYS) {
    if (!Number.isInteger(result[key]) || result[key] < 0) return null;
    out[key] = result[key];
  }
  return out;
}

export function saveSnapshot(api, page, snapshot, { timeoutMs = SAVE_TIMEOUT_MS, setTimer = setTimeout,
  clearTimer = clearTimeout } = {}) {
  if (!api || !api.runtime || typeof api.runtime.connectNative !== 'function') {
    return Promise.resolve({ saved: false, code: 'indisponivel_nesta_versao' });
  }
  return new Promise((resolve) => {
    let port = null;
    let stage = 'hello';
    let reportId = '';
    let done = false;
    let timer = null;
    const finish = (result) => {
      if (done) return;
      done = true;
      if (timer !== null) clearTimer(timer);
      try { if (port) port.disconnect(); } catch { /* already closed */ }
      resolve(result);
    };
    try {
      port = api.runtime.connectNative(HOST_NAME);
    } catch {
      resolve({ saved: false, code: 'host_indisponivel' });
      return;
    }
    timer = setTimer(() => finish({ saved: false, code: 'tempo_esgotado' }), timeoutMs);
    port.onDisconnect.addListener(() => {
      // Reading lastError is what Chrome expects; only a fixed comparison is made, nothing is shown.
      const error = api.runtime.lastError;
      const missing = Boolean(error && /not found/i.test(String(error.message)));
      if (stage === 'hello') finish({ saved: false, code: missing ? 'host_nao_instalado' : 'host_indisponivel' });
      else finish({ saved: false, code: 'desconectado' });
    });
    port.onMessage.addListener((raw) => {
      const reply = readReply(raw);
      if (reply.type === 'rejected') {
        finish({ saved: false, code: CODE.test(String(reply.code)) ? reply.code : 'recusado' });
        return;
      }
      if (stage === 'hello' && reply.type === 'welcome') {
        let report;
        try {
          report = buildPageReport(reply.session, page, snapshot);
        } catch (error) {
          finish({ saved: false, code: error instanceof RangeError ? 'grande_demais' : 'pagina_nao_reportavel' });
          return;
        }
        reportId = report.request_id;
        stage = 'report';
        port.postMessage(report);
        return;
      }
      if (stage === 'report' && reply.type === 'ack' && reply.request_id === reportId) {
        const result = parseResult(reply);
        finish(result ? { saved: true, code: 'salvo', result } : { saved: false, code: 'sem_confirmacao' });
        return;
      }
      finish({ saved: false, code: 'resposta_invalida' });
    });
    try {
      port.postMessage(buildHello());
    } catch {
      finish({ saved: false, code: 'host_indisponivel' });
    }
  });
}

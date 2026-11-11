// Messages the extension may send to the local Campus AI host (Chrome Native Messaging).
// Mirror of campus_ai/companion_protocol.py. The extension can only REPORT: there is no message type
// that asks the host to run, open, fetch, write, delete or submit anything.

export const PROTOCOL_ID = 'campus-ai.companion/1';
export const HOST_NAME = 'br.campus_ai.companion';
export const MAX_MESSAGE_BYTES = 512 * 1024;
export const EXTENSION_VERSION = '0.0.1';
const REPORTABLE_PAGES = Object.freeze({
  curso_inicio: '/ava/course/view.php?id',
  curso_secao: '/ava/course/view.php?id&section',
  curso_bloco: '/ava/course/section.php?id',
});
const SESSION = /^[0-9a-f]{32}$/;
const REPLY_TYPES = new Set(['welcome', 'ack', 'rejected']);

export function newRequestId() {
  return crypto.randomUUID();
}

export function isReportable(page) {
  return Boolean(page) && Object.hasOwn(REPORTABLE_PAGES, page.kind) && REPORTABLE_PAGES[page.kind] === page.route;
}

export function encodedSize(message) {
  return new TextEncoder().encode(JSON.stringify(message)).length;
}

function checked(message) {
  if (encodedSize(message) > MAX_MESSAGE_BYTES) throw new RangeError('grande_demais');
  return message;
}

export function buildHello(requestId = newRequestId()) {
  return checked({
    protocol: PROTOCOL_ID, type: 'hello', request_id: requestId, session: '',
    payload: { extension_version: EXTENSION_VERSION, capabilities: ['page_report'] },
  });
}

export function buildPageReport(session, page, snapshot, requestId = newRequestId()) {
  if (!SESSION.test(String(session))) throw new TypeError('sessao_invalida');
  if (!isReportable(page)) throw new TypeError('pagina_nao_reportavel');
  return checked({
    protocol: PROTOCOL_ID, type: 'page_report', request_id: requestId, session,
    payload: { page: { kind: page.kind, route: page.route }, snapshot },
  });
}

// Replies are data from the host, validated before use. Anything unexpected is treated as rejection.
export function readReply(reply) {
  if (!reply || typeof reply !== 'object' || reply.protocol !== PROTOCOL_ID || !REPLY_TYPES.has(reply.type)) {
    return { type: 'rejected', code: 'resposta_invalida' };
  }
  if (reply.type === 'welcome' && !SESSION.test(String(reply.session))) {
    return { type: 'rejected', code: 'resposta_invalida' };
  }
  return reply;
}

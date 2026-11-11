// Campus AI Companion — what the activity pages said, as data for the snapshot, and the situation it supports.
// Pure (no DOM, no network). Mirror of campus_ai/deadlines.py: both are checked against the same cases
// (tests/fixtures/companion/situations.json), so the popup and the app never disagree.
//
// Rules (only what the page said; never an inference from absence):
//   assignment  graded -> concluida; submitted -> aguardando_avaliacao (not graded) / enviada (grading unknown);
//               no submission, draft or reopened -> atrasada if its due date passed, else pendente;
//   quiz        attempt in progress -> verificar_tentativa (atrasada if closed); finished -> concluida;
//               no attempt -> atrasada if closed, else pendente;
//   anything not read, failed or not recognised -> nao_verificado. Other kinds -> nao_se_aplica.
// Dates are the wall time Moodle shows, in America/Sao_Paulo (UTC-03:00, no daylight saving since 2019).
export const TIMEZONE = 'America/Sao_Paulo';
export const OFFSET = '-03:00';
export const DETAIL_KINDS = Object.freeze(['assign', 'quiz']);
export const SITUATIONS = Object.freeze(['atrasada', 'pendente', 'verificar_tentativa', 'nao_verificado',
  'aguardando_avaliacao', 'enviada', 'concluida', 'nao_se_aplica']);           // also the urgency order
export const SITUATION_TEXT = Object.freeze({
  atrasada: 'Atrasada', pendente: 'Pendente', verificar_tentativa: 'Tentativa em andamento — verificar',
  nao_verificado: 'Não verificado', aguardando_avaliacao: 'Enviada — aguardando avaliação', enviada: 'Enviada',
  concluida: 'Concluída', nao_se_aplica: '—',
});
export const RESULTS = Object.freeze(['ok', 'nao_consultada', 'parametros_invalidos', 'fora_do_dominio', 'curso_diferente',
  'redirecionado', 'inacessivel', 'falha_http', 'nao_html', 'tempo_esgotado', 'falha_rede', 'grande_demais',
  'sessao_expirada', 'pagina_nao_reconhecida', 'estrutura_desconhecida', 'acesso_perdido']);
const SUBMISSION_STATES = new Set(['desconhecido', 'sem_envio', 'rascunho', 'enviado', 'reaberto', 'nao_se_aplica']);
const GRADING_STATES = new Set(['desconhecido', 'avaliado', 'nao_avaliado', 'nao_se_aplica']);
const ATTEMPT_STATES = new Set(['desconhecido', 'nenhuma', 'em_andamento', 'finalizada', 'nao_se_aplica']);
const DATE_KINDS = new Set(['abertura', 'entrega', 'limite', 'fechamento']);
const WALL = /^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$/;

const pick = (value, allowed, fallback) => (allowed.has(value) ? value : fallback);

// The main deadline: the due date of an assignment, the closing date of a quiz.
export const mainKind = (kind) => (kind === 'quiz' ? 'fechamento' : 'entrega');

// Wall time 'YYYY-MM-DD[THH:MM]' in America/Sao_Paulo -> epoch ms. A date without time ends at 23:59.
export function wallToEpoch(at) {
  if (typeof at !== 'string' || !WALL.test(at)) return NaN;
  const full = at.length === 10 ? `${at}T23:59` : at;
  return Date.parse(`${full}:00${OFFSET}`);
}

// due_state: 'definido' (a date was read), 'nao_interpretado' (a label was there, the date could not be read),
// 'sem_prazo' (the dates of the page were recognised and there is no such date) or 'nao_verificado'.
export function dueStateOf(kind, facts) {
  if (!facts) return 'nao_verificado';
  const main = facts.dates.find((d) => d.kind === mainKind(kind));
  if (main) return main.at ? 'definido' : 'nao_interpretado';
  return facts.structure ? 'sem_prazo' : 'nao_verificado';
}

// The page's answer (details.js) -> the snapshot's deadlines/submission/detail of one activity. Unknown stays unknown.
export function detailRecord(kind, answer, checkedAt) {
  const result = answer && RESULTS.includes(answer.result) ? answer.result : 'falha_rede';
  const facts = result === 'ok' && answer.facts && Array.isArray(answer.facts.dates) ? answer.facts : null;
  const dates = facts ? facts.dates.filter((d) => DATE_KINDS.has(d.kind) && (d.at === '' || WALL.test(d.at))).slice(0, 4) : [];
  const detail = {
    checked_at: checkedAt, result: facts ? 'ok' : (result === 'ok' ? 'estrutura_desconhecida' : result),
    submission_state: facts ? pick(facts.submission, SUBMISSION_STATES, 'desconhecido') : 'desconhecido',
    grading_state: facts ? pick(facts.grading, GRADING_STATES, 'desconhecido') : 'desconhecido',
    attempt_state: facts ? pick(facts.attempt, ATTEMPT_STATES, 'desconhecido') : 'desconhecido',
    due_state: dueStateOf(kind, facts ? { ...facts, dates } : null),
    timezone: TIMEZONE,
  };
  const deadlines = dates.filter((d) => d.at || d.raw).map((d) => ({
    kind: d.kind, at: d.at, timezone_explicit: false, raw: String(d.raw || '').slice(0, 160) }));
  return { deadlines, submission: submissionOf(detail), detail };
}

// The contract's coarse field (what the source said about delivery), for older readers of the data.
export function submissionOf(detail) {
  if (!detail || detail.result !== 'ok') return 'desconhecido';
  if (detail.grading_state === 'avaliado') return 'avaliado';
  if (detail.submission_state === 'enviado' || detail.attempt_state === 'finalizada') return 'enviado';
  if (['sem_envio', 'rascunho', 'reaberto'].includes(detail.submission_state) || ['nenhuma', 'em_andamento'].includes(detail.attempt_state)) {
    return 'nao_enviado';
  }
  return 'desconhecido';
}

export function situationOf(kind, detail, deadlines, now = new Date()) {
  if (!DETAIL_KINDS.includes(kind)) return 'nao_se_aplica';
  if (!detail || detail.result !== 'ok') return 'nao_verificado';
  const main = (deadlines || []).find((d) => d.kind === mainKind(kind) && d.at);
  const expired = main ? wallToEpoch(main.at) < now.getTime() : false;
  if (kind === 'assign') {
    if (detail.grading_state === 'avaliado') return 'concluida';
    if (detail.submission_state === 'enviado') return detail.grading_state === 'nao_avaliado' ? 'aguardando_avaliacao' : 'enviada';
    if (['sem_envio', 'rascunho', 'reaberto'].includes(detail.submission_state)) return expired ? 'atrasada' : 'pendente';
    return 'nao_verificado';
  }
  if (detail.attempt_state === 'em_andamento') return expired ? 'atrasada' : 'verificar_tentativa';
  if (detail.attempt_state === 'finalizada') return 'concluida';
  if (detail.attempt_state === 'nenhuma') return expired ? 'atrasada' : 'pendente';
  return 'nao_verificado';
}

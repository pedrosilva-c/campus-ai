// Campus AI Companion — "Sincronizar disciplina": one click from the course home to saved modules.
//
// It orchestrates pieces that were already validated on the real AEDB and adds nothing to what is read:
//   1. runPreview (preview.js)  : address, course, Tiles, section identity, then items, then identity again;
//   2. open_panel.js            : ONLY if the section panel is closed, one verified click on its tile;
//   3. a wait that ends when the panel is visible AND its item count stayed the same for `settleMs`;
//   4. runPreview again         : the very same read/validation as the manual mode;
//   5. saveSnapshot (save.js)   : sent to the local app; "saved" is claimed only for the host's ACK.
// The student's click on "Sincronizar disciplina" is the consent for steps 2 and 5. Nothing runs in the
// background: it lives and dies with the popup (closing it stops the run; nothing is saved without the ACK).
// Not touched here: links of activities or files, completion/submission controls, downloads, other courses.
//
// v0.5.2:
//   * if Moodle's "Preferência dos dados" window is open (before or after the tile click), it is closed by ITS X
//     (open_panel.js closeDataPreference; authorized by the student on 09/11/2026), the run waits until it is gone
//     and then revalidates the section. At most MAX_DIALOG_CLOSES closes per run; any other dialog stops the run.
//   * the tile is clicked AT MOST ONCE per run: never again after the window was closed. If the section is not
//     there after closing, the run stops ("secao_indisponivel") without reading anything.
//   * `autoSave: false` (what the popup's "Sincronizar disciplina" uses) stops after the read: the student saves
//     with the "Salvar no Campus AI" button. The course sync keeps `autoSave: true` (one save per section, v0.5.1).
//
// v0.5.4: `details: true` (both popup buttons) adds step "detalhar" after the read: for each assignment/quiz of the
// section just read (at most MAX_DETAILS), details.js fetches ITS page (same-origin GET, nothing followed, nothing
// clicked) and the deadlines and delivery state found are attached to the reading. A failed page never fails the
// reading: that activity stays "não verificado". Still nothing is saved before the student's click.
import { classifyPage } from './classify.js';
import { DETAIL_KINDS, detailRecord, situationOf } from './deadlines.js';
import { AUTHORIZED_COURSES, AUTHORIZED_SECTIONS, MESSAGES, SECTION_LABEL, runPreview } from './preview.js';
import { saveSnapshot } from './save.js';

export const MAX_DETAILS = 20;
export const DETAIL_PAUSE_MS = 400;
const MODULE_UID = /^moodle:course:([1-9][0-9]{0,9}):module:([1-9][0-9]{0,9})$/;
// After one of these, the following pages would fail the same way: they are not requested.
const STOP_DETAILS = new Set(['acesso_perdido', 'redirecionado', 'sessao_expirada', 'fora_do_dominio', 'curso_diferente']);

export const STEPS = Object.freeze([
  ['verificar', 'Verificar página, disciplina e formato'],
  ['abrir', 'Abrir o cartão Atividades Avaliativas'],
  ['fechar', 'Fechar a janela "Preferência dos dados" (só se aparecer)'],
  ['aguardar', 'Aguardar o carregamento do painel'],
  ['ler', 'Ler e validar os módulos'],
  ['detalhar', 'Consultar prazos e entregas nas páginas das atividades'],
  ['salvar', 'Salvar no Campus AI'],
]);

export const DEFAULTS = Object.freeze({ timeoutMs: 12000, pollMs: 300, settleMs: 900 });
export const MAX_DIALOG_CLOSES = 2;

export const SYNC_MESSAGES = Object.freeze({
  pagina_invalida: 'Abra a página inicial da disciplina (ou a seção) no Chrome e tente de novo. Nada foi acionado.',
  parametros_invalidos: 'Parâmetros inválidos para abrir o cartão. Nada foi acionado.',
  tile_perigoso: 'O cartão tem um comportamento ou rótulo que a extensão não aciona. Nada foi acionado.',
  tile_nao_clicavel: 'O cartão não está marcado como clicável. Nada foi acionado.',
  tile_oculto: 'O cartão Atividades Avaliativas não está visível na tela. Nada foi acionado.',
  clique_recusado: 'A página recusou a abertura do cartão. Nada foi acionado.',
  painel_nao_abriu: 'O cartão foi acionado, mas o painel não apareceu ou não estabilizou a tempo. Nenhum item foi '
    + 'lido. Abra o cartão manualmente e use "Ler esta página".',
  acesso_perdido: 'A página mudou ao abrir o cartão e a extensão perdeu o acesso (a permissão vale só até a página '
    + 'mudar). Nada foi lido. Abra a seção e clique no ícone de novo (modo manual).',
  sessao_expirada: 'A sessão do AVA expirou durante a sincronização. Entre manualmente e tente de novo. Nada foi salvo.',
  saiu_do_dominio: 'A aba saiu do domínio autorizado durante a sincronização. Nada foi lido nem salvo.',
  cancelado: 'Sincronização cancelada. Nada foi salvo.',
  erro: 'Erro inesperado durante a sincronização. Nada foi salvo.',
  dialogo_nao_identificado: 'Há uma janela aberta que não pôde ser identificada com segurança como "Preferência dos '
    + 'dados". Ela não foi fechada e nada foi acionado. Nenhum item foi lido.',
  dialogo_nao_fechou: 'A janela "Preferência dos dados" foi fechada pelo X, mas continuou na tela. Nada mais foi '
    + 'acionado. Nenhum item foi lido.',
  dialogo_reapareceu: 'A janela "Preferência dos dados" reapareceu depois de fechada. A sincronização parou sem '
    + 'acionar mais nada. Nenhum item foi lido.',
  secao_indisponivel: 'A janela "Preferência dos dados" foi fechada, mas a seção não ficou disponível. O cartão não '
    + 'é acionado de novo. Nenhum item foi lido.',
  lido: 'Lido e validado. Nada foi salvo ainda: confira o resultado e clique em "Salvar no Campus AI".',
});
const CLOSED_NOTE = 'Janela "Preferência dos dados" fechada pelo X (autorizado). Nada mais foi acionado nela.';

// Reasons the page can report while we wait that mean "do not go on".
const STOPPING = new Set(['paineis_multiplos', 'dialogo_bloqueia', 'painel_sem_vinculo', 'tile_ambiguo',
  'tile_sem_vinculo', 'tile_nao_encontrado']);
const REASON = /^[a-z_]{1,40}$/;

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

// Run inside the page (serialized by executeScript): they must not reference anything outside themselves.
function openPanelInPage(options) {
  return globalThis.CampusAiOpenPanel.open(document, location, options);
}

function closeDataPreferenceInPage(options) {
  return globalThis.CampusAiOpenPanel.closeDataPreference(document, location, options);
}

function readDetailInPage(options) {
  return globalThis.CampusAiDetails.read(document, location, options);
}

const isoSeconds = (date) => date.toISOString().replace(/\.\d{3}Z$/, 'Z');

// Step "detalhar": one page per assignment/quiz, one after the other, read only. Returns the reading with the
// deadlines/delivery attached, plus a per-activity summary for the popup. Never saves.
async function readDetails(api, model, { isCancelled, sleep, pauseMs, clock, onItem }) {
  const activities = model.snapshot.activities;
  const targets = activities.filter((a) => DETAIL_KINDS.includes(a.kind) && MODULE_UID.test(a.uid)).slice(0, MAX_DETAILS);
  if (!targets.length) return { skipped: true, model };
  const courseId = model.snapshot.courses[0] && model.snapshot.courses[0].moodle_id;
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  const answers = new Map();
  let stopped = '';
  if (!isObject(tab) || !Number.isInteger(tab.id) || !AUTHORIZED_COURSES.includes(courseId)) {
    stopped = 'acesso_perdido';
  } else {
    try {
      await api.scripting.executeScript({ target: { tabId: tab.id }, files: ['src/details.js'] });
    } catch {
      stopped = 'acesso_perdido';
    }
  }
  for (const [index, activity] of targets.entries()) {
    if (stopped) break;
    if (isCancelled()) return { code: 'cancelado' };
    if (index) await sleep(pauseMs);
    let answer;
    try {
      const [first] = await api.scripting.executeScript({
        target: { tabId: tab.id }, func: readDetailInPage,
        args: [{ cmid: MODULE_UID.exec(activity.uid)[2], kind: activity.kind, courseId }],
      });
      answer = first && first.result;
    } catch {
      answer = { result: 'acesso_perdido' };     // the tab changed or closed: activeTab is gone
    }
    answers.set(activity.uid, answer);
    if (isObject(answer) && STOP_DETAILS.has(answer.result)) stopped = answer.result;
    onItem(index + 1, targets.length);
  }
  if (isCancelled()) return { code: 'cancelado' };

  const checkedAt = isoSeconds(clock());
  const now = clock();
  const summary = [];
  const enriched = activities.map((activity) => {
    if (!targets.includes(activity)) return activity;
    const record = detailRecord(activity.kind, answers.get(activity.uid) || { result: 'nao_consultada' }, checkedAt);
    summary.push({ uid: activity.uid, title: activity.title, kind: activity.kind, ...record,
      situation: situationOf(activity.kind, record.detail, record.deadlines, now) });
    return { ...activity, ...record };
  });
  const ok = summary.filter((s) => s.detail.result === 'ok').length;
  const reasons = [...model.snapshot.coverage.reasons,
    `Prazos e entregas consultados nas páginas de ${ok} de ${targets.length} atividade(s) (tarefas e questionários).`];
  if (activities.filter((a) => DETAIL_KINDS.includes(a.kind)).length > targets.length) {
    reasons.push(`Só as primeiras ${MAX_DETAILS} atividades foram consultadas.`);
  }
  const snapshot = { ...model.snapshot, activities: enriched, coverage: { ...model.snapshot.coverage, reasons } };
  return { model: { ...model, snapshot, details: summary }, ok, total: targets.length, stopped };
}

function readIdentityInPage(options) {
  return { href: location.href, projection: globalThis.CampusAiDomTiles.project(document, location, options) };
}

function messageFor(code) {
  return MESSAGES[code] || SYNC_MESSAGES[code] || SYNC_MESSAGES.clique_recusado;
}

async function activeCourseTab(api) {
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  if (!isObject(tab) || !Number.isInteger(tab.id) || typeof tab.url !== 'string') return null;
  const page = classifyPage(tab.url);
  const home = page.kind === 'curso_inicio' || page.kind === 'curso_secao';
  return home && AUTHORIZED_COURSES.includes(page.moodleId) ? { id: tab.id, courseId: page.moodleId } : null;
}

// One literal for the injection of the only file that interacts with the page.
async function injectOpenPanel(api, tab) {
  await api.scripting.executeScript({ target: { tabId: tab.id }, files: ['src/open_panel.js'] });
}

function interaction(result, fallback) {
  if (isObject(result) && result.clicked === true) return { ok: true };
  const reason = isObject(result) && typeof result.reason === 'string' && REASON.test(result.reason) ? result.reason : '';
  return { ok: false, code: reason || fallback };
}

async function clickTile(api, tab, sectionLabel) {
  await injectOpenPanel(api, tab);
  const [first] = await api.scripting.executeScript({
    target: { tabId: tab.id }, func: openPanelInPage, args: [{ label: sectionLabel, courseId: tab.courseId }],
  });
  return interaction(first && first.result, 'clique_recusado');
}

// The X of the "Preferência dos dados" window, and nothing else (every gate is in open_panel.js, same call).
async function closeDialog(api, tab) {
  await injectOpenPanel(api, tab);
  const [first] = await api.scripting.executeScript({
    target: { tabId: tab.id }, func: closeDataPreferenceInPage, args: [{ courseId: tab.courseId }],
  });
  return interaction(first && first.result, 'dialogo_nao_identificado');
}

// One identity read (no item data) while waiting: the page must still be the course, in the domain, reachable.
async function peek(api, tab, sectionLabel) {
  let result;
  try {
    const [first] = await api.scripting.executeScript({
      target: { tabId: tab.id }, func: readIdentityInPage, args: [{ withEntries: false, sectionLabel }],
    });
    result = first && first.result;
  } catch {
    return { code: 'acesso_perdido' };             // activeTab ends when the document is replaced
  }
  if (!isObject(result) || typeof result.href !== 'string' || !isObject(result.projection)) return { code: 'acesso_perdido' };
  const page = classifyPage(result.href);
  if (page.kind === 'login') return { code: 'sessao_expirada' };
  if (page.kind === 'externa' || page.kind === 'invalida') return { code: 'saiu_do_dominio' };
  return { projection: result.projection, diagnostic: isObject(result.projection.diagnostic) ? result.projection.diagnostic : {} };
}

const count = (diagnostic, key) => (Number.isInteger(diagnostic[key]) ? diagnostic[key] : 0);
const preferenceOpen = (d) => d.reason === 'dialogo_preferencia' || count(d, 'dataPreferenceDialogs') > 0;
const unknownOpen = (d) => d.reason === 'dialogo_bloqueia' || count(d, 'unknownDialogs') > 0;

// After the X: ends when the window is no longer rendered. Another dialog stops the run.
async function waitForDialogGone(api, tab, { timeoutMs, pollMs, sleep, isCancelled, sectionLabel }) {
  for (let elapsed = 0; elapsed <= timeoutMs; elapsed += pollMs) {
    if (isCancelled()) return { code: 'cancelado' };
    const seen = await peek(api, tab, sectionLabel);
    if (seen.code) return seen;
    if (unknownOpen(seen.diagnostic)) return { code: 'dialogo_bloqueia' };
    if (!preferenceOpen(seen.diagnostic)) return { ok: true };
    await sleep(pollMs);
  }
  return { code: 'dialogo_nao_fechou' };
}

// Ends when the panel (or section page) is visible and its item count did not change for `settleMs`, or when the
// "Preferência dos dados" window shows up (code 'dialogo_preferencia': the caller decides whether to close it).
async function waitForPanel(api, tab, { timeoutMs, pollMs, settleMs, sleep, isCancelled, sectionLabel }) {
  let last = '';
  let stable = 0;
  for (let elapsed = 0; elapsed <= timeoutMs; elapsed += pollMs) {
    if (isCancelled()) return { code: 'cancelado' };
    const seen = await peek(api, tab, sectionLabel);
    if (seen.code) return seen;
    const { diagnostic } = seen;
    const result = { projection: seen.projection };
    if (STOPPING.has(diagnostic.reason)) return { code: diagnostic.reason };
    if (diagnostic.reason === 'dialogo_preferencia') return { code: 'dialogo_preferencia' };
    const key = typeof result.projection.panelKey === 'string' && result.projection.mode !== 'nenhum'
      ? result.projection.panelKey : '';
    const items = Number(key.split(':').pop());
    stable = key && items > 0 && key === last ? stable + pollMs : 0;
    last = key;
    if (key && stable >= settleMs) return { ok: true };
    await sleep(pollMs);
  }
  return { code: 'painel_nao_abriu' };
}

export async function runSync(api, {
  onProgress = () => {}, isCancelled = () => false, save = saveSnapshot, now = new Date(),
  timeoutMs = DEFAULTS.timeoutMs, pollMs = DEFAULTS.pollMs, settleMs = DEFAULTS.settleMs,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  sectionLabel = SECTION_LABEL, authorizedSections = AUTHORIZED_SECTIONS, autoSave = true,
  details = false, detailPauseMs = DETAIL_PAUSE_MS, clock = () => new Date(),
} = {}) {
  // sectionLabel/authorizedSections: used by the course sync; without them this is the validated v0.4 flow.
  const steps = STEPS.map(([id, label]) => ({
    id, label: id === 'abrir' ? `Abrir o cartão ${sectionLabel}` : label, status: 'pendente', note: '' }));
  const scope = { now, sectionLabel, authorizedSections };
  let closes = 0;                                   // times the "Preferência dos dados" window was closed by its X
  const mark = (id, status, note = '') => {
    const step = steps.find((s) => s.id === id);
    step.status = status;
    step.note = note;
    try { onProgress(steps.map((s) => ({ ...s }))); } catch { /* the display must never break the run */ }
  };
  const done = (state, message, extra = {}) => ({
    state, message, steps: steps.map((s) => ({ ...s })), model: null, saved: null, dialogsClosed: closes, ...extra,
  });
  const stop = (state, stepId, message, extra) => {
    mark(stepId, 'falhou', message);
    return done(state, message, extra);
  };
  const statusOf = (id) => steps.find((s) => s.id === id).status;

  try {
    mark('verificar', 'andamento');
    let model = await runPreview(api, scope);
    if (isCancelled()) return done('cancelado', SYNC_MESSAGES.cancelado);

    // What can be fixed without the student: the panel is closed (one tile click) or the authorized window is open
    // (its X). Only when address, course and Tiles were confirmed; anything else is refused before any interaction.
    const RECOVERABLE = ['painel_fechado', 'dialogo_preferencia'];
    const basics = (m) => ['dominio', 'pagina', 'curso', 'formato'].every((id) => m.checks.find((c) => c.id === id).ok === true);
    const blockedBy = (m) => (m.state !== 'ok' && basics(m) && isObject(m.diagnostic) ? m.diagnostic.reason : '');
    if (model.state !== 'ok' && !RECOVERABLE.includes(blockedBy(model))) return stop('recusado', 'verificar', model.message, { model });
    mark('verificar', 'ok', model.state === 'ok' ? 'Disciplina, formato e seção confirmados.'
      : blockedBy(model) === 'painel_fechado' ? 'Disciplina e formato Tiles confirmados; painel fechado.'
        : 'Disciplina e formato Tiles confirmados; janela "Preferência dos dados" aberta.');

    let tab = null;
    let clicked = false;                            // the tile is clicked AT MOST once per run
    let stage = 'ler';
    // Bounded: one tile click, at most MAX_DIALOG_CLOSES closes, and a hard cap on rounds.
    for (let round = 0; model.state !== 'ok'; round += 1) {
      const reason = blockedBy(model);
      if (!RECOVERABLE.includes(reason) || round > MAX_DIALOG_CLOSES + 2) return stop('recusado', stage, model.message, { model });
      if (reason === 'painel_fechado' && clicked) {   // never a second click on the tile
        return stop('recusado', stage, closes ? SYNC_MESSAGES.secao_indisponivel : model.message, { model });
      }
      const next = reason === 'dialogo_preferencia' ? 'fechar' : 'abrir';
      tab = tab || await activeCourseTab(api);
      if (!tab) return stop('recusado', next, SYNC_MESSAGES.pagina_invalida, { model });

      if (next === 'fechar') {
        if (closes >= MAX_DIALOG_CLOSES) return stop('recusado', 'fechar', SYNC_MESSAGES.dialogo_reapareceu, { model });
        mark('fechar', 'andamento');
        const closed = await closeDialog(api, tab);
        if (!closed.ok && closed.code !== 'dialogo_ausente') return stop('recusado', 'fechar', messageFor(closed.code), { model });
        if (closed.ok) {
          closes += 1;
          const gone = await waitForDialogGone(api, tab, { timeoutMs, pollMs, sleep, isCancelled, sectionLabel });
          if (gone.code === 'cancelado') return stop('cancelado', 'fechar', SYNC_MESSAGES.cancelado);
          if (!gone.ok) return stop('recusado', 'fechar', messageFor(gone.code), { model });
        }
        mark('fechar', 'ok', closes ? CLOSED_NOTE : 'A janela já tinha sido fechada; nada foi acionado.');
      } else {
        mark('abrir', 'andamento');
        const tile = await clickTile(api, tab, sectionLabel);
        if (!tile.ok) return stop('recusado', 'abrir', messageFor(tile.code), { model });
        clicked = true;
        mark('abrir', 'ok', 'Cartão acionado uma vez.');
      }

      if (clicked) {                                  // wait until the section is visible and stable
        mark('aguardar', 'andamento');
        stage = 'aguardar';
        const waited = await waitForPanel(api, tab, { timeoutMs, pollMs, settleMs, sleep, isCancelled, sectionLabel });
        if (waited.code === 'cancelado') return stop('cancelado', 'aguardar', SYNC_MESSAGES.cancelado);
        if (!waited.ok && waited.code !== 'dialogo_preferencia') {   // the window: next round closes it
          const message = closes && waited.code === 'painel_nao_abriu' ? SYNC_MESSAGES.secao_indisponivel : messageFor(waited.code);
          return stop('recusado', 'aguardar', message, { model });
        }
        if (waited.ok) mark('aguardar', 'ok', closes ? 'Painel visível e estável; seção revalidada depois de fechar a janela.'
          : 'Painel visível e estável.');
      }

      // the same read and validation as the manual mode (it is also the revalidation after the window closed)
      mark('ler', 'andamento');
      stage = 'ler';
      model = await runPreview(api, scope);
      if (isCancelled()) return stop('cancelado', 'ler', SYNC_MESSAGES.cancelado);
    }

    if (!clicked) mark('abrir', 'pulado', model.mode === 'painel' ? 'O painel já estava aberto.' : 'Página própria da seção.');
    if (statusOf('fechar') === 'pendente') mark('fechar', 'pulado');
    if (!clicked) mark('aguardar', 'pulado');
    if (statusOf('ler') !== 'andamento') mark('ler', 'andamento');
    mark('ler', 'ok', `${model.rows.length} módulo(s) válido(s) e ${model.issues.length} problema(s).`
      + (closes ? ' Seção revalidada depois de fechar a janela "Preferência dos dados".' : ''));

    if (isCancelled()) return done('cancelado', SYNC_MESSAGES.cancelado, { model });

    // v0.5.4: deadlines and delivery, from each activity's own page (read only)
    if (!details) {
      mark('detalhar', 'pulado', 'Não solicitado neste modo.');
    } else {
      mark('detalhar', 'andamento');
      const found = await readDetails(api, model, {
        isCancelled, sleep, pauseMs: detailPauseMs, clock,
        onItem: (n, total) => mark('detalhar', 'andamento', `${n} de ${total} página(s) consultada(s).`),
      });
      if (found.code === 'cancelado') return stop('cancelado', 'detalhar', SYNC_MESSAGES.cancelado);
      if (found.skipped) {
        mark('detalhar', 'pulado', 'Nenhuma tarefa ou questionário nesta seção.');
      } else {
        model = found.model;
        const failed = found.total - found.ok;
        const note = `${found.ok} de ${found.total} atividade(s) com prazo e entrega lidos na própria página`
          + (failed ? `; ${failed} não verificada(s)${found.stopped ? ` (parou em: ${found.stopped})` : ''}.` : '.');
        mark('detalhar', failed ? 'parcial' : 'ok', note);
      }
    }
    if (isCancelled()) return done('cancelado', SYNC_MESSAGES.cancelado, { model });
    if (!autoSave) {                                // the student saves with "Salvar no Campus AI"
      mark('salvar', 'aguardando', 'Aguardando o seu clique em "Salvar no Campus AI".');
      return done('lido', SYNC_MESSAGES.lido, { model });
    }

    // 5. save: only the host's ACK makes it "saved"
    mark('salvar', 'andamento');
    const outcome = await save(api, model.page, model.snapshot);
    if (outcome && outcome.saved === true) {
      mark('salvar', 'ok', 'Confirmado pelo aplicativo Campus AI.');
      return done('salvo', 'Sincronizado e salvo no Campus AI.', { model, saved: outcome });
    }
    const code = outcome && typeof outcome.code === 'string' && REASON.test(outcome.code) ? outcome.code : 'sem_confirmacao';
    mark('salvar', 'falhou', code);
    return done('lido_nao_salvo', 'Os módulos foram lidos, mas NÃO há confirmação de que foram salvos.',
      { model, saved: { saved: false, code } });
  } catch {
    const pending = steps.find((s) => s.status === 'andamento');
    if (pending) mark(pending.id, 'falhou', SYNC_MESSAGES.erro);
    return done('erro', SYNC_MESSAGES.erro);
  }
}

// Campus AI Companion — "Sincronizar seções autorizadas" (experimental): one click reads every AUTHORIZED academic
// section of the course, one after the other; a SECOND, explicit click saves them (v0.5.3).
//
// Phase 1, runCourseSync (reading, nothing is saved):
//   1. the active tab must be the course home of an authorized course;
//   2. tiles_catalog.js describes the tiles (labels and attributes only) and catalog.js decides what each one is;
//   3. for each section to read, in a fixed order, the validated flow runs (runSync with autoSave: false: verify,
//      one verified click if the panel is closed, the X of "Preferência dos dados" if it shows up, wait, read,
//      validate). The readings are kept ONLY in the popup's memory: closing the popup discards them.
// Phase 2, createCourseSaver(...)() — only from the "Salvar no Campus AI" button:
//   4. the readings are saved in the same fixed order, one report per section, each one confirmed by the host's ACK;
//   5. a module already SAVED (saved: true exactly) by an earlier section of this save is left out of the later
//      section's snapshot (one owner per module) and the omission is recorded in that section's coverage; a section
//      whose save failed claims nothing, so a later section may still save the module (v0.5.1);
//   6. a section that fails is simply not saved: what the app already has for it is kept as it was.
//   The saver runs at most once: a second click while (or after) it runs gets the same result, nothing is re-sent.
// Never opens communication/feedback tiles, informative tiles, unknown tiles, external links or sections that are
// not in AUTHORIZED_SECTIONS. Lives and dies with the popup.
import { classifyPage } from './classify.js';
import { buildPlan } from './catalog.js';
import { AUTHORIZED_COURSES, AUTHORIZED_SECTIONS, MESSAGES } from './preview.js';
import { saveSnapshot } from './save.js';
import { runSync } from './sync.js';

export const COURSE_MESSAGES = Object.freeze({
  pagina_invalida: 'Abra a página inicial da disciplina (Modelagem UML) no Chrome e tente de novo. Nada foi acionado.',
  catalogo_invalido: 'Não foi possível descrever os cartões desta página. Nada foi acionado.',
  nenhuma_secao: 'Nenhuma seção acadêmica autorizada foi encontrada nesta página. Nada foi acionado.',
  todas_lidas: 'Todas as seções autorizadas foram lidas e validadas. Nada foi salvo ainda: confira o resumo e clique '
    + 'em "Salvar no Campus AI".',
  parte_lida: 'Parte das seções autorizadas foi lida; as que falharam não serão salvas. Nada foi salvo ainda: confira '
    + 'o resumo e clique em "Salvar no Campus AI".',
  nenhuma_lida: 'Nenhuma seção autorizada pôde ser lida. Nada foi salvo.',
  cancelado: 'Sincronização cancelada. Nada foi salvo.',
  todas_salvas: 'Todas as seções autorizadas foram lidas e salvas no Campus AI.',
  lidas_salvas_faltou_leitura: 'As seções lidas foram salvas, mas parte das seções autorizadas FALHOU na leitura e não '
    + 'foi salva; o que o Campus AI já tinha delas foi preservado.',
  parcial: 'Parte das seções foi salva e parte FALHOU: as que falharam não foram gravadas e o que o Campus AI já tinha '
    + 'delas foi preservado.',
  nenhuma_salva: 'Nenhuma seção foi salva. O que o Campus AI já tinha foi preservado.',
});

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

// Runs inside the page (serialized by executeScript): must not reference anything outside itself.
function describeInPage() {
  return globalThis.CampusAiTilesCatalog.describe(document, location);
}

function refuse(message, extra = {}) {
  return { state: 'recusado', message, plan: null, sections: [], coverage: null, readings: [], ...extra };
}

function coverageOf(plan, read, saved) {
  return {
    // Never "completa": non-academic tiles are not read and deadlines/delivery are not on these pages.
    state: 'parcial',
    academicas: plan.entries.filter((e) => e.role === 'academica').length,
    autorizadas: plan.toRead.length,
    lidas: read,
    salvas: saved,
    naoAutorizadas: plan.entries.filter((e) => e.decision === 'nao_autorizada').map((e) => e.label),
    bloqueadas: plan.entries.filter((e) => e.decision === 'bloqueada').map((e) => e.label),
    ignoradas: plan.entries.filter((e) => e.decision === 'ignorada' || e.decision === 'desconhecida').map((e) => e.label),
  };
}

// Phase 1. Reads; never saves (there is no save function here at all).
export async function runCourseSync(api, {
  authorizedSections = AUTHORIZED_SECTIONS, onProgress = () => {}, isCancelled = () => false, syncOptions = {},
} = {}) {
  const report = (event) => { try { onProgress(event); } catch { /* the display must never break the run */ } };

  // 1. the course home of an authorized course
  let tab;
  try {
    [tab] = await api.tabs.query({ active: true, currentWindow: true });
  } catch {
    return refuse(MESSAGES.sem_aba);
  }
  if (!isObject(tab) || !Number.isInteger(tab.id)) return refuse(MESSAGES.sem_aba);
  if (typeof tab.url !== 'string' || !tab.url) return refuse(MESSAGES.sem_acesso);
  const page = classifyPage(tab.url);
  if (page.kind === 'externa' || page.kind === 'invalida') return refuse(MESSAGES.dominio);
  if (page.kind !== 'curso_inicio' && page.kind !== 'curso_secao') return refuse(COURSE_MESSAGES.pagina_invalida);
  if (!AUTHORIZED_COURSES.includes(page.moodleId)) return refuse(MESSAGES.curso_diferente);

  // 2. describe and classify the tiles (no click, no content)
  let catalog;
  try {
    await api.scripting.executeScript({ target: { tabId: tab.id }, files: ['src/tiles_catalog.js'] });
    const [first] = await api.scripting.executeScript({ target: { tabId: tab.id }, func: describeInPage });
    catalog = first && first.result;
  } catch {
    return refuse(MESSAGES.leitura_falhou);
  }
  if (!isObject(catalog) || !Array.isArray(catalog.tiles)) return refuse(COURSE_MESSAGES.catalogo_invalido);
  if (catalog.courseId !== page.moodleId) return refuse(catalog.courseId ? MESSAGES.curso_diferente : MESSAGES.curso_nao_confirmado);
  if (catalog.formatTiles !== true) return refuse(MESSAGES.formato);
  const plan = buildPlan(catalog, authorizedSections);
  report({ phase: 'plano', plan });
  if (!plan.toRead.length) return refuse(COURSE_MESSAGES.nenhuma_secao, { plan });

  // 3. one section after the other, read only
  const sections = [];
  const readings = [];
  for (const [index, entry] of plan.toRead.entries()) {
    const result = { key: entry.key, label: entry.display, state: 'pendente', message: '', rows: 0, coverage: '',
      dialogsClosed: 0 };
    sections.push(result);
    if (isCancelled()) {
      Object.assign(result, { state: 'cancelado', message: COURSE_MESSAGES.cancelado });
      continue;
    }
    report({ phase: 'secao', index, total: plan.toRead.length, label: entry.display, steps: [] });
    const outcome = await runSync(api, {
      ...syncOptions, sectionLabel: entry.display, authorizedSections, isCancelled, autoSave: false, details: true,
      onProgress: (steps) => report({ phase: 'secao', index, total: plan.toRead.length, label: entry.display, steps }),
    });
    const model = outcome.model;
    Object.assign(result, {
      state: outcome.state, message: outcome.message, dialogsClosed: outcome.dialogsClosed || 0,
      rows: model && Array.isArray(model.rows) ? model.rows.length : 0,
      coverage: model && model.coverage ? model.coverage.state : '',
    });
    if (outcome.state === 'lido' && model && model.state === 'ok') {
      readings.push({ key: entry.key, label: entry.display, page: model.page, snapshot: model.snapshot });
      result.details = Array.isArray(model.details) ? model.details : [];
    }
  }

  const cancelled = sections.some((s) => s.state === 'cancelado');
  const read = readings.length;
  const state = cancelled ? 'cancelado' : read === sections.length ? 'lido' : read ? 'parcial' : 'recusado';
  const message = { lido: COURSE_MESSAGES.todas_lidas, parcial: COURSE_MESSAGES.parte_lida, cancelado: COURSE_MESSAGES.cancelado,
    recusado: COURSE_MESSAGES.nenhuma_lida }[state];
  // A cancelled run offers nothing to save: what was read is dropped with it.
  return { state, message, plan, sections, coverage: coverageOf(plan, read, 0), readings: cancelled ? [] : readings };
}

// Phase 2. Returns the function the "Salvar no Campus AI" button calls. It runs once (single flight).
// `notRead`: authorized sections whose READING failed; with any, the result is never "everything saved".
export function createCourseSaver(api, readings, { save = saveSnapshot, notRead = 0 } = {}) {
  const list = Array.isArray(readings) ? readings.filter((r) => isObject(r) && isObject(r.snapshot)) : [];
  let running = null;

  async function commit() {
    const owned = new Set();
    const sections = [];
    for (const reading of list) {
      const { snapshot } = reading;
      const result = { key: reading.key, label: reading.label, state: 'pendente', message: '', omitted: 0, saved: null };
      sections.push(result);
      const keep = (record) => !owned.has(record.uid);
      const materials = snapshot.materials.filter(keep);
      const activities = snapshot.activities.filter(keep);
      result.omitted = snapshot.materials.length + snapshot.activities.length - materials.length - activities.length;
      if (!materials.length && !activities.length) {          // every module already saved by an earlier section
        Object.assign(result, { state: 'repetida', message: 'Todos os módulos já foram salvos por outra seção: nada a enviar.' });
        continue;
      }
      const reasons = result.omitted
        ? [...snapshot.coverage.reasons, `${result.omitted} módulo(s) já lido(s) em outra seção nesta sincronização foram omitidos aqui.`]
        : snapshot.coverage.reasons;
      let outcome;
      try {
        outcome = await save(api, reading.page, { ...snapshot, materials, activities, coverage: { ...snapshot.coverage, reasons } });
      } catch {
        outcome = { saved: false, code: 'erro' };
      }
      if (outcome && outcome.saved === true) {
        for (const record of [...materials, ...activities]) owned.add(record.uid);   // only now: v0.5.1 rule
        Object.assign(result, { state: 'salvo', saved: outcome });
      } else {
        const code = outcome && typeof outcome.code === 'string' && /^[a-z_]{1,40}$/.test(outcome.code) ? outcome.code : 'sem_confirmacao';
        Object.assign(result, { state: 'falhou', saved: { saved: false, code } });
      }
    }
    const savedCount = sections.filter((s) => s.state === 'salvo').length;
    const failed = sections.filter((s) => s.state === 'falhou').length;
    const missing = Number.isInteger(notRead) && notRead > 0;
    const state = !list.length || (!savedCount && failed) ? 'nenhuma_salva' : failed || missing ? 'parcial' : 'salvo';
    const message = state === 'parcial' && !failed ? COURSE_MESSAGES.lidas_salvas_faltou_leitura
      : { salvo: COURSE_MESSAGES.todas_salvas, parcial: COURSE_MESSAGES.parcial, nenhuma_salva: COURSE_MESSAGES.nenhuma_salva }[state];
    return { state, message, sections, saved: savedCount, failed };
  }

  return () => {
    if (!running) running = commit();
    return running;
  };
}

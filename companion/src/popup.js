// Campus AI Companion — popup.
//  * "Sincronizar disciplina": one click from the course home; opens the section tile (one verified click),
//    closes the "Preferência dos dados" window by its X if it shows up, reads and validates. It does NOT save:
//    the student saves with "Salvar no Campus AI" (v0.5.2). Lives only while this popup is open.
//  * "Ler esta página" / "Salvar no Campus AI": the manual mode, unchanged.
import { runPreview } from './preview.js';
import { renderBusy, renderCourseOutcome, renderCourseProgress, renderPreview, renderSyncOutcome, renderSteps } from './render.js';
import { saveSnapshot } from './save.js';
import { runSync, STEPS } from './sync.js';
import { createCourseSaver, runCourseSync } from './course_sync.js';

const progress = document.getElementById('progress');
const result = document.getElementById('result');
const readButton = document.getElementById('read');
const syncButton = document.getElementById('sync');
const courseButton = document.getElementById('sync-course');
const cancelButton = document.getElementById('cancel');
let cancelled = false;

function setBusy(busy) {
  readButton.disabled = busy;
  syncButton.disabled = busy;
  courseButton.disabled = busy;
  cancelButton.hidden = !busy || !running;
  if (busy) cancelButton.disabled = false;     // a new run can be cancelled again
}
let running = false;

readButton.addEventListener('click', async () => {
  setBusy(true);
  progress.replaceChildren();
  renderBusy(result);
  let model;
  try {
    model = await runPreview(chrome);
  } catch {
    model = { state: 'recusado', message: 'Erro inesperado ao ler a página. Nada foi exibido.', checks: [] };
  }
  const onSave = model.state === 'ok' ? () => saveSnapshot(chrome, model.page, model.snapshot) : undefined;
  renderPreview(result, model, { onSave });
  setBusy(false);
});

syncButton.addEventListener('click', async () => {
  cancelled = false;
  running = true;
  setBusy(true);
  result.replaceChildren();
  renderSteps(progress, STEPS.map(([id, label]) => ({ id, label, status: 'pendente', note: '' })));
  let outcome;
  try {
    outcome = await runSync(chrome, {
      autoSave: false, details: true, onProgress: (steps) => renderSteps(progress, steps), isCancelled: () => cancelled,
    });
  } catch {
    outcome = { state: 'erro', message: 'Erro inesperado durante a sincronização. Nada foi salvo.', steps: [], model: null, saved: null };
  }
  const model = outcome.model;
  const onSave = model && model.state === 'ok' ? () => saveSnapshot(chrome, model.page, model.snapshot) : undefined;
  renderSyncOutcome(progress, result, outcome, { onSave });
  running = false;
  setBusy(false);
});

// Experimental: every AUTHORIZED academic section, one after the other (today only Atividades Avaliativas is
// authorized, so this reads the same section as "Sincronizar disciplina" and lists the others as not read).
// v0.5.3: reads only; saving is a separate, explicit click (createCourseSaver, called by the button).
courseButton.addEventListener('click', async () => {
  cancelled = false;
  running = true;
  setBusy(true);
  result.replaceChildren();
  progress.replaceChildren();
  let plan = null;
  let outcome;
  try {
    outcome = await runCourseSync(chrome, {
      isCancelled: () => cancelled,
      onProgress: (event) => {
        if (event.phase === 'plano') plan = event.plan;
        renderCourseProgress(progress, event, plan);
      },
    });
  } catch {
    outcome = { state: 'erro', message: 'Erro inesperado durante a sincronização. Nada foi salvo.', plan, sections: [],
      coverage: null, readings: [] };
  }
  // Nothing was saved while reading. The readings stay in this popup's memory until the student clicks
  // "Salvar no Campus AI" (or closes the popup, which discards them).
  const readings = outcome.readings || [];
  const onSave = readings.length
    ? createCourseSaver(chrome, readings, { notRead: outcome.sections.length - readings.length }) : undefined;
  renderCourseOutcome(progress, result, outcome, { onSave });
  running = false;
  setBusy(false);
});

cancelButton.addEventListener('click', () => {
  cancelled = true;            // checked between steps; a save already sent still needs the host's ACK to count
  cancelButton.disabled = true;
});

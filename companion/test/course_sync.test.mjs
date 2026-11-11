import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { COURSE_MESSAGES, createCourseSaver, runCourseSync } from '../src/course_sync.js';
import { MESSAGES } from '../src/preview.js';
import { SYNC_MESSAGES, runSync } from '../src/sync.js';

const golden = JSON.parse(readFileSync(new URL('../../tests/fixtures/companion/tiles_projection.json', import.meta.url), 'utf8'));
const HOME = 'https://ead.aedb.br/ava/course/view.php?id=7653';
const AA = 'Atividades Avaliativas';
const TR = 'Trilhas de Aprendizagem';
const BOTH = ['atividades avaliativas', 'trilhas de aprendizagem'];
const FAST = { pollMs: 100, settleMs: 300, timeoutMs: 2000, sleep: async () => {}, now: new Date('2026-11-06T12:00:00Z') };
const mod = (cmid, title, modtype = 'assign') => ({ modtype, cmid, title,
  hrefs: [`https://ead.aedb.br/ava/mod/${modtype.split('_')[0]}/view.php?id=${cmid}`] });

const PANELS = {
  [AA]: { ...golden, mode: 'painel', sectionPage: false, sectionName: AA, panelKey: 'painel:4242:3:10',
    docTitle: 'Curso: 4º P CURSO FICTÍCIO - Modelagem Fictícia | AVA' },
  [TR]: { ...golden, mode: 'painel', sectionPage: false, sectionName: TR, sectionId: '4241', panelKey: 'painel:4241:2:2',
    docTitle: 'Curso: 4º P CURSO FICTÍCIO - Modelagem Fictícia | AVA',
    entries: [mod('92001', 'Material sintético das trilhas', 'resource_pdf'), mod('92002', 'Exercício sintético das trilhas')] },
};
const closed = (label) => ({ ...PANELS[label], mode: 'nenhum', sectionId: '', sectionName: '', panelKey: 'nenhum:::0', entries: [],
  diagnostic: { ...golden.diagnostic, tiles: 5, tilesMatched: 1, candidates: 1, reason: 'painel_fechado' } });
const noItems = (p) => ({ ...p, entries: [] });

const tile = (position, label, sectionId, over = {}) => ({ position, label, number: String(position), sectionId, links: 1,
  linkKind: 'secao', sameTab: true, clickable: true, visible: true, ...over });
const CATALOG = { catalog: 'campus-ai-tiles-catalog/1', courseId: '7653', formatTiles: true, path: '/ava/course/view.php', tiles: [
  tile(1, 'Informações da Disciplina', '4240'), tile(2, TR, '4241'), tile(3, AA, '4242'),
  tile(4, 'Feedback das Aulas', '4243'), tile(5, 'Fale com o Professor', '4244')] };

// A fake Chrome + Tiles course home: a tile click opens its section (and closes the other, like Tiles).
function world({ url = HOME, catalog = CATALOG, panels = PANELS, opens = { [AA]: true, [TR]: true } } = {}) {
  const log = [];
  let open = '';
  const api = {
    tabs: { query: async () => { log.push('query'); return [{ id: 7, url }]; } },
    scripting: {
      executeScript: async (o) => {
        if (o.files) { log.push(`inject:${o.files[0].split('/').pop()}`); return [{}]; }
        const source = String(o.func);
        if (source.includes('CampusAiDetails')) {         // v0.5.4: an activity page, always "not submitted, due 2098"
          log.push(`detail:${o.args[0].cmid}`);
          return [{ result: { result: 'ok', facts: { structure: true, submission: 'sem_envio', grading: 'nao_avaliado',
            attempt: 'nao_se_aplica', dates: [{ kind: 'entrega', at: '2098-12-31T23:59', raw: '31 dez. 2098, 23:59' }] } } }];
        }
        if (source.includes('CampusAiTilesCatalog')) { log.push('describe'); return [{ result: typeof catalog === 'function' ? catalog() : catalog }]; }
        if (source.includes('CampusAiOpenPanel')) {
          const { label } = o.args[0];
          log.push(`click:${label}`);
          if (opens[label]) open = label;
          return [{ result: { clicked: true } }];
        }
        const { withEntries, sectionLabel } = o.args[0];
        log.push(`${withEntries ? 'items' : 'id'}:${sectionLabel}`);
        const projection = open === sectionLabel ? panels[sectionLabel] : closed(sectionLabel);
        return [{ result: { href: HOME, projection: withEntries ? projection : noItems(projection) } }];
      },
    },
  };
  return { api, log };
}

function saver(log) {
  const calls = [];
  return {
    calls,
    save: async (api, page, snapshot) => {
      log.push(`save:${snapshot.sections[0].name}`);
      calls.push({ page, snapshot });
      const n = snapshot.materials.length + snapshot.activities.length;
      return { saved: true, code: 'salvo', result: { run: calls.length + 4, itens: n, novos: 0, alterados: 0, ausentes: 0, reaparecidos: 0, inalterados: n } };
    },
  };
}

// v0.5.3: reading (runCourseSync) never saves; the explicit click calls createCourseSaver(...)(). `run` does both, in
// that order, like the student reading and then clicking "Salvar no Campus AI" (commit: false = never clicks).
async function run(w, { commit = true, ...options } = {}) {
  const s = saver(w.log);
  const events = [];
  const read = await runCourseSync(w.api, { syncOptions: FAST, onProgress: (e) => events.push(e), ...options });
  const savesDuringRead = s.calls.length;
  assert.equal(savesDuringRead, 0, 'nothing is saved while reading');
  const notRead = read.sections.length - read.readings.length;
  const saved = commit && read.readings.length ? await createCourseSaver(w.api, read.readings, { save: s.save, notRead })() : null;
  // `outcome` keeps the shape the older tests use: the read result plus the save result per section.
  const outcome = { ...read, saveResult: saved, state: saved ? saved.state : read.state, message: saved ? saved.message : read.message,
    sections: read.sections.map((section) => {
      const done = saved && saved.sections.find((x) => x.key === section.key);
      return done ? { ...section, readState: section.state, ...done } : section;
    }) };
  return { outcome, read, saved, saves: s.calls, savesDuringRead, events };
}
const uids = (snapshot) => [...snapshot.materials, ...snapshot.activities].map((r) => r.uid).sort();
const clicks = (log) => log.filter((x) => x.startsWith('click:'));

test('production authorization: only Atividades Avaliativas is read; Trilhas is listed, never opened', async () => {
  const w = world();
  const { outcome, saves } = await run(w);
  assert.equal(outcome.state, 'salvo');
  assert.deepEqual(clicks(w.log), [`click:${AA}`]);
  assert.ok(!w.log.some((x) => x.endsWith(`:${TR}`)), 'nothing about Trilhas is read');
  assert.equal(saves.length, 1);
  assert.equal(uids(saves[0].snapshot).length, 7);
  assert.deepEqual(outcome.coverage.naoAutorizadas, [TR]);
  assert.deepEqual(outcome.coverage.bloqueadas, ['Feedback das Aulas', 'Fale com o Professor']);
  assert.deepEqual(outcome.coverage.ignoradas, ['Informações da Disciplina']);
  assert.equal(outcome.coverage.state, 'parcial');
});

test('two authorized sections (demonstration): read and saved one after the other, each as its own section', async () => {
  const w = world();
  const { outcome, saves, events } = await run(w, { authorizedSections: BOTH });
  assert.equal(outcome.state, 'salvo');
  assert.deepEqual(clicks(w.log), [`click:${AA}`, `click:${TR}`]);
  assert.deepEqual(w.log.filter((x) => x.startsWith('save:')), [`save:${AA}`, `save:${TR}`]);
  assert.deepEqual(saves.map((s) => s.snapshot.sections[0].uid),
    ['moodle:course:7653:section:id-4242', 'moodle:course:7653:section:id-4241']);
  assert.deepEqual(uids(saves[1].snapshot), ['moodle:course:7653:module:92001', 'moodle:course:7653:module:92002']);
  for (const { snapshot } of saves) {                       // every module records the section it came from
    for (const record of [...snapshot.materials, ...snapshot.activities]) assert.equal(record.section_uid, snapshot.sections[0].uid);
  }
  assert.equal(outcome.coverage.lidas, 2);
  assert.equal(outcome.saveResult.saved, 2);
  assert.equal(outcome.message, COURSE_MESSAGES.todas_salvas);
  assert.equal(outcome.coverage.state, 'parcial');            // never "completa"
  assert.equal(events[0].phase, 'plano');
  assert.deepEqual([...new Set(events.filter((e) => e.phase === 'secao').map((e) => e.index))], [0, 1]);
  assert.ok(!w.log.some((x) => /Feedback|Fale com|Informações/.test(x)));
});

test('one section fails (its panel never opens): the other is saved, the failed one is not written', async () => {
  const w = world({ opens: { [AA]: true, [TR]: false } });
  const { outcome, read, saves } = await run(w, { authorizedSections: BOTH });
  assert.deepEqual([read.state, read.message], ['parcial', COURSE_MESSAGES.parte_lida]);
  assert.equal(outcome.state, 'parcial');                     // never "everything saved" with a failed section
  assert.equal(outcome.message, COURSE_MESSAGES.lidas_salvas_faltou_leitura);
  assert.equal(saves.length, 1);
  assert.equal(saves[0].snapshot.sections[0].name, AA);
  const failed = outcome.sections.find((s) => s.label === TR);
  assert.deepEqual([failed.state, failed.message, failed.rows], ['recusado', SYNC_MESSAGES.painel_nao_abriu, 0]);
  assert.equal(clicks(w.log).filter((x) => x === `click:${TR}`).length, 1);       // never clicked twice

  const other = world({ opens: { [AA]: false, [TR]: true } });
  const second = await run(other, { authorizedSections: BOTH });
  assert.equal(second.outcome.state, 'parcial');
  assert.deepEqual(second.saves.map((s) => s.snapshot.sections[0].name), [TR]);
});

test('a module that appears in two sections is saved once, in the first section of the fixed order', async () => {
  const panels = { ...PANELS, [TR]: { ...PANELS[TR], panelKey: 'painel:4241:2:3',
    entries: [...PANELS[TR].entries, mod('90001', 'Exercício sintético A')] } };
  const w = world({ panels });
  const { outcome, saves } = await run(w, { authorizedSections: BOTH });
  assert.equal(outcome.state, 'salvo');
  assert.ok(uids(saves[0].snapshot).includes('moodle:course:7653:module:90001'));
  assert.ok(!uids(saves[1].snapshot).includes('moodle:course:7653:module:90001'));
  assert.equal(outcome.sections[1].omitted, 1);
  assert.ok(saves[1].snapshot.coverage.reasons.some((r) => r.includes('1 módulo(s) já lido(s) em outra seção')));

  const onlyRepeated = { ...PANELS, [TR]: { ...PANELS[TR], panelKey: 'painel:4241:2:1', entries: [mod('90001', 'Exercício sintético A')] } };
  const w2 = world({ panels: onlyRepeated });
  const r2 = await run(w2, { authorizedSections: BOTH });
  assert.equal(r2.saves.length, 1);                                   // an empty section snapshot is never sent
  assert.equal(r2.outcome.sections[1].state, 'repetida');
  assert.equal(r2.outcome.state, 'salvo');                            // nothing failed: every module is saved once
});

test('refusals before anything is clicked or saved', async () => {
  const cases = [
    [{ url: 'https://ead.aedb.br/ava/course/section.php?id=4242' }, COURSE_MESSAGES.pagina_invalida],
    [{ url: 'https://ead.aedb.br/ava/course/view.php?id=9999' }, MESSAGES.curso_diferente],
    [{ url: 'https://example.org/' }, MESSAGES.dominio],
    [{ url: 'https://ead.aedb.br/ava/login/index.php' }, COURSE_MESSAGES.pagina_invalida],
    [{ catalog: { ...CATALOG, courseId: '8888' } }, MESSAGES.curso_diferente],
    [{ catalog: { ...CATALOG, courseId: '' } }, MESSAGES.curso_nao_confirmado],
    [{ catalog: { ...CATALOG, formatTiles: false } }, MESSAGES.formato],
    [{ catalog: 'lixo' }, COURSE_MESSAGES.catalogo_invalido],
    [{ catalog: { ...CATALOG, tiles: CATALOG.tiles.filter((t) => t.label !== AA) } }, COURSE_MESSAGES.nenhuma_secao],
    [{ catalog: () => { throw new Error('x'); } }, MESSAGES.leitura_falhou],
  ];
  for (const [over, message] of cases) {
    const w = world(over);
    const { outcome, saves } = await run(w);
    assert.equal(outcome.state, 'recusado', message);
    assert.equal(outcome.message, message);
    assert.deepEqual(clicks(w.log), []);
    assert.equal(saves.length, 0);
  }
});

test('cancel while reading: nothing is saved, nothing is offered to save, the rest is not run', async () => {
  const w = world();
  const { outcome, saves } = await run(w, { authorizedSections: BOTH, isCancelled: () => w.log.includes(`items:${AA}`) });
  assert.equal(outcome.state, 'cancelado');
  assert.equal(outcome.message, COURSE_MESSAGES.cancelado);
  assert.deepEqual(outcome.readings, []);                         // what was read is dropped with the run
  assert.equal(saves.length, 0);
  assert.equal(outcome.sections[1].state, 'cancelado');
  assert.deepEqual(clicks(w.log), [`click:${AA}`]);
});

// --- ownership of a module shared by two sections (v0.5.1) -----------------------------------------------------
// A fake local app with the guarantees of the real host (companion_store): ONE row per module uid (a later reading
// of another section moves it, never duplicates it) and a reading is all or nothing (a failed save writes nothing).
// `host.fail[sectionName]` = a code to refuse that section's save, or 'throw' to make save itself throw.
const AA_SEC = 'moodle:course:7653:section:id-4242';
const TR_SEC = 'moodle:course:7653:section:id-4241';
const M = (cmid) => `moodle:course:7653:module:${cmid}`;

function fakeHost() {
  const host = { items: new Map(), attempts: [], fail: {}, runs: 0 };
  host.save = async (api, page, snapshot) => {
    const name = snapshot.sections[0].name;
    const ids = uids(snapshot);
    host.attempts.push({ name, ids, reasons: snapshot.coverage.reasons });
    const mode = host.fail[name];
    if (mode === 'throw') throw new Error('falha sintética do salvamento');
    if (mode) return { saved: false, code: mode };
    for (const id of ids) host.items.set(id, snapshot.sections[0].uid);
    host.runs += 1;
    return { saved: true, code: 'salvo', result: { run: host.runs, itens: ids.length, novos: 0, alterados: 0, ausentes: 0,
      reaparecidos: 0, inalterados: ids.length } };
  };
  return host;
}

// Trilhas (fictitious) also lists some Atividades Avaliativas modules.
function sharedPanels(cmids) {
  const extra = cmids.map((cmid) => mod(cmid, `Repetido sintético ${cmid}`));
  const entries = [...PANELS[TR].entries, ...extra];
  return { ...PANELS, [TR]: { ...PANELS[TR], entries, panelKey: `painel:4241:2:${entries.length}` } };
}

async function syncWith(host, panels, options = {}) {
  const w = world({ panels });
  const before = host.attempts.length;
  const read = await runCourseSync(w.api, { syncOptions: FAST, authorizedSections: BOTH, ...options });
  assert.equal(host.attempts.length, before, 'nothing is sent while reading');
  const saved = await createCourseSaver(w.api, read.readings, { save: host.save })();
  const outcome = { ...read, state: saved.state, message: saved.message,
    sections: read.sections.map((s) => ({ ...s, readState: s.state, ...(saved.sections.find((x) => x.key === s.key) || {}) })) };
  return { outcome, read, saved, log: w.log };
}
const attemptsOf = (host, name) => host.attempts.filter((a) => a.name === name);
const lastAttempt = (host, name) => attemptsOf(host, name).at(-1);
const AA_ONLY = ['90002', '90003', '90004', '90005', '90006', '90007'].map(M);

test('ownership 1: A saves, B lists the same module: A stays the owner and nothing is duplicated', async () => {
  const host = fakeHost();
  const { outcome } = await syncWith(host, sharedPanels(['90001']));
  assert.equal(outcome.state, 'salvo');
  assert.ok(lastAttempt(host, AA).ids.includes(M('90001')));
  assert.ok(!lastAttempt(host, TR).ids.includes(M('90001')));
  assert.equal(host.items.get(M('90001')), AA_SEC);
  assert.equal(host.items.size, 9);                                    // 7 + 2, no second row for 90001
  assert.equal(outcome.sections[1].omitted, 1);
});

test('ownership 2: A fails to save, B lists the same module: B may save it', async () => {
  const host = fakeHost();
  host.fail[AA] = 'sem_confirmacao';
  const { outcome } = await syncWith(host, sharedPanels(['90001']));
  assert.equal(outcome.state, 'parcial');
  assert.equal(outcome.message, COURSE_MESSAGES.parcial);
  assert.equal(outcome.sections[0].state, 'falhou');
  assert.ok(lastAttempt(host, TR).ids.includes(M('90001')), 'the module must not be left out of B');
  assert.equal(outcome.sections[1].omitted, 0);
  assert.ok(!lastAttempt(host, TR).reasons.some((r) => r.includes('já lido(s) em outra seção')));
  assert.equal(host.items.get(M('90001')), TR_SEC);
  for (const id of AA_ONLY) assert.ok(!host.items.has(id), 'nothing of the failed section is written');
});

test('ownership 3: A fails and no other section has its modules: what the app had is preserved', async () => {
  const host = fakeHost();
  await syncWith(host, PANELS, { authorizedSections: undefined });     // production list: earlier good reading
  const before = new Map(host.items);
  assert.equal(before.size, 7);
  for (const failure of ['sem_confirmacao', 'desconectado', 'throw']) {
    host.fail[AA] = failure;
    const { outcome } = await syncWith(host, PANELS, { authorizedSections: undefined });
    assert.equal(outcome.state, 'nenhuma_salva', failure);
    assert.equal(outcome.message, COURSE_MESSAGES.nenhuma_salva);
    assert.deepEqual(host.items, before, failure);
  }
});

test('ownership 4: A fails and B saves; on the next sync A saves: one row, one owner, no duplication', async () => {
  const host = fakeHost();
  const panels = sharedPanels(['90001']);
  host.fail[AA] = 'desconectado';
  const first = await syncWith(host, panels);
  assert.equal(first.outcome.state, 'parcial');
  assert.equal(host.items.get(M('90001')), TR_SEC);

  host.fail = {};
  const second = await syncWith(host, panels);
  assert.equal(second.outcome.state, 'salvo');
  assert.ok(lastAttempt(host, AA).ids.includes(M('90001')));
  assert.ok(!lastAttempt(host, TR).ids.includes(M('90001')));        // the fixed order decides again: A owns it
  assert.equal(second.outcome.sections[1].omitted, 1);
  assert.equal(host.items.get(M('90001')), AA_SEC);
  assert.equal(host.items.size, 9);
  const third = await syncWith(host, panels);                          // stable from now on
  assert.deepEqual(third.outcome.sections.map((s) => [s.state, s.omitted]), [['salvo', 0], ['salvo', 1]]);
  assert.equal(host.items.get(M('90001')), AA_SEC);
});

test('ownership 5: several modules in both sections: each one is sent by exactly one section', async () => {
  const shared = ['90001', '90002', '90005'];
  const host = fakeHost();
  const { outcome } = await syncWith(host, sharedPanels(shared));
  assert.equal(outcome.state, 'salvo');
  const sent = host.attempts.flatMap((a) => a.ids);
  assert.equal(sent.length, new Set(sent).size, 'no module is sent twice in one sync');
  assert.deepEqual(lastAttempt(host, TR).ids, [M('92001'), M('92002')]);
  assert.equal(outcome.sections[1].omitted, 3);
  for (const cmid of shared) assert.equal(host.items.get(M(cmid)), AA_SEC);

  const failing = fakeHost();
  failing.fail[AA] = 'tempo_esgotado';
  const second = await syncWith(failing, sharedPanels(shared));
  assert.deepEqual(lastAttempt(failing, TR).ids, [...shared.map(M), M('92001'), M('92002')].sort());
  assert.equal(second.outcome.sections[1].omitted, 0);
  for (const cmid of shared) assert.equal(failing.items.get(M(cmid)), TR_SEC);
  assert.equal(failing.items.size, 5);
});

test('ownership 6: a failed save leaves no orphan ownership (refused, thrown or not confirmed)', async () => {
  for (const failure of ['throw', 'sem_confirmacao', 'resposta_invalida']) {
    const host = fakeHost();
    host.fail[AA] = failure;
    const { outcome } = await syncWith(host, sharedPanels(['90001', '90002']));
    assert.equal(outcome.sections[0].state, 'falhou', failure);
    assert.equal(outcome.sections[0].saved.code, failure === 'throw' ? 'erro' : failure, failure);
    assert.equal(outcome.sections[1].state, 'salvo', failure);
    assert.equal(outcome.sections[1].omitted, 0, failure);
    assert.ok(lastAttempt(host, TR).ids.includes(M('90001')) && lastAttempt(host, TR).ids.includes(M('90002')), failure);
  }
  // an answer that is not exactly `saved: true` is not a confirmation either
  const host = fakeHost();
  const w = world({ panels: sharedPanels(['90001']) });
  const vague = async (api, page, snapshot) => (snapshot.sections[0].name === AA ? { saved: 'true' } : host.save(api, page, snapshot));
  const read = await runCourseSync(w.api, { syncOptions: FAST, authorizedSections: BOTH });
  const { sections } = await createCourseSaver(w.api, read.readings, { save: vague })();
  assert.equal(sections[0].state, 'falhou');
  assert.equal(sections[1].omitted, 0);
  assert.ok(lastAttempt(host, TR).ids.includes(M('90001')));
});

// --- v0.5.3: nothing is saved before the explicit click --------------------------------------------------------
test('confirm 1: reading every authorized section saves nothing; the readings wait in memory, in the fixed order', async () => {
  const host = fakeHost();
  const w = world({ panels: sharedPanels(['90001']) });
  const read = await runCourseSync(w.api, { syncOptions: FAST, authorizedSections: BOTH });
  assert.equal(read.state, 'lido');
  assert.equal(read.message, COURSE_MESSAGES.todas_lidas);
  assert.equal(host.attempts.length, 0);
  assert.ok(!w.log.some((x) => x.startsWith('save:')));
  assert.deepEqual(read.readings.map((r) => r.label), [AA, TR]);
  assert.deepEqual(read.sections.map((s) => [s.label, s.state, s.rows]), [[AA, 'lido', 7], [TR, 'lido', 3]]);
  assert.equal(read.coverage.salvas, 0);
  // the API object handed to the read phase is never asked for a native port
  assert.ok(!('runtime' in w.api));
});

test('confirm 2: closing the popup before the click discards everything (no save is ever started)', async () => {
  const host = fakeHost();
  const w = world({ panels: sharedPanels(['90001']) });
  let read = await runCourseSync(w.api, { syncOptions: FAST, authorizedSections: BOTH });
  const saver = createCourseSaver(w.api, read.readings, { save: host.save });   // what the popup holds
  assert.equal(typeof saver, 'function');
  read = null;                                                       // the popup closes: memory gone, saver never called
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(host.attempts.length, 0);
  assert.equal(host.items.size, 0);
});

test('confirm 3: one click saves in order; repeated clicks while (or after) saving send nothing twice', async () => {
  const host = fakeHost();
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const slow = async (...args) => { await gate; return host.save(...args); };
  const w = world({ panels: sharedPanels(['90001']) });
  const read = await runCourseSync(w.api, { syncOptions: FAST, authorizedSections: BOTH });
  const click = createCourseSaver(w.api, read.readings, { save: slow });
  const first = click();
  const second = click();                                            // clicked again while the first is running
  assert.strictEqual(first, second);
  release();
  const [a, b] = await Promise.all([first, second]);
  assert.strictEqual(a, b);
  assert.deepEqual(host.attempts.map((x) => x.name), [AA, TR]);     // one report per section, in the fixed order
  assert.strictEqual(await click(), a);                              // and after it ended
  assert.equal(host.attempts.length, 2);
  assert.equal(a.state, 'salvo');
  assert.deepEqual(a.sections.map((s) => [s.label, s.state, s.omitted]), [[AA, 'salvo', 0], [TR, 'salvo', 1]]);
});

test('confirm 4: partial failure at save time: each section reported, never "everything saved"', async () => {
  const host = fakeHost();
  host.fail[TR] = 'desconectado';
  const w = world({ panels: sharedPanels(['90001']) });
  const read = await runCourseSync(w.api, { syncOptions: FAST, authorizedSections: BOTH });
  const result = await createCourseSaver(w.api, read.readings, { save: host.save })();
  assert.equal(result.state, 'parcial');
  assert.equal(result.message, COURSE_MESSAGES.parcial);
  assert.notEqual(result.message, COURSE_MESSAGES.todas_salvas);
  assert.deepEqual(result.sections.map((s) => [s.label, s.state]), [[AA, 'salvo'], [TR, 'falhou']]);
  assert.deepEqual([result.saved, result.failed], [1, 1]);
  assert.equal(result.sections[1].saved.code, 'desconectado');
  assert.equal(host.items.get(M('90001')), AA_SEC);                   // A saved it; B's failure changes nothing
  assert.ok(!host.items.has(M('92001')));
  // nothing to save at all
  const empty = await createCourseSaver(w.api, [], { save: host.save })();
  assert.equal(empty.state, 'nenhuma_salva');
});

test('v0.5.4: details in the course mode: read before the click, a shared module keeps one owner with its deadline', async () => {
  const host = fakeHost();
  const w = world({ panels: sharedPanels(['90001']) });
  const read = await runCourseSync(w.api, { syncOptions: { ...FAST, detailPauseMs: 0 }, authorizedSections: BOTH });
  assert.equal(host.attempts.length, 0);                                     // pages read, nothing saved
  assert.ok(w.log.filter((x) => x.startsWith('detail:')).length >= 6);       // 5 assign of AA + the assign of TR (+ repeated)
  assert.ok(!w.log.some((x) => /^detail:(90004|90006|92001)$/.test(x)));   // never the material, the group choice
  assert.ok(read.sections.every((s) => s.details.length > 0));
  const saved = await createCourseSaver(w.api, read.readings, { save: host.save })();
  assert.equal(saved.state, 'salvo');
  assert.equal(host.items.get(M('90001')), AA_SEC);
  const aa = host.attempts.find((a) => a.name === AA);
  assert.ok(aa.ids.includes(M('90001')) && !lastAttempt(host, TR).ids.includes(M('90001')));
});

test('an unauthorized section is never opened: by the plan, and by the section flow itself', async () => {
  const w = world({ catalog: { ...CATALOG, tiles: [tile(2, TR, '4241')] } });
  const { outcome } = await run(w);                                // production list: Trilhas not authorized
  assert.equal(outcome.message, COURSE_MESSAGES.nenhuma_secao);
  assert.deepEqual(clicks(w.log), []);
  // defence in depth: even called directly, the validated section flow refuses before touching the tab
  const direct = world();
  const result = await runSync(direct.api, { ...FAST, sectionLabel: TR, save: async () => assert.fail('no save') });
  assert.equal(result.state, 'recusado');
  assert.equal(result.message, MESSAGES.secao);
  assert.deepEqual(direct.log, []);
});

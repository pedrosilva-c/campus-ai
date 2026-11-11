// Campus AI Companion — local preview logic (no DOM, no storage, no network, no Native Messaging).
//
// `runPreview(api)` is called from the popup after the student clicked the extension button, which is
// what grants `activeTab` for the current tab. `api` is the Chrome extension API object; this module
// touches exactly two functions of it: api.tabs.query and api.scripting.executeScript (a test pins that).
//
// The authorized section can be shown in two ways (format-tiles):
//   * its own page  /ava/course/section.php?id=<section>             -> mode 'secao_pagina'
//   * a panel opened inside /ava/course/view.php?id=7653 (same URL)  -> mode 'painel'
//
// Order of work, so that nothing is read from a page or panel that is not the authorized one:
//   1. address of the active tab              -> domain, page type, course in the URL (nothing injected)
//   2. inject dom_tiles.js, IDENTITY read      -> course in the page, Tiles, mode, section (no item data)
//   3. ITEMS read                              -> only now are data-title / data-modtype / data-cmid read
//   4. IDENTITY read again                     -> the same page, mode, section and panel, or nothing is shown
// The returned model is plain data kept in memory by the popup; messages are fixed texts.
import { classifyPage } from './classify.js';
import { buildTilesSnapshot, sectionNameOf } from './tiles_adapter.js';

export const AUTHORIZED_COURSES = Object.freeze(['7653']);
export const SECTION_LABEL = 'Atividades Avaliativas';
// THE authorization list. A section is read only if its folded name is here. Adding one (e.g.
// 'trilhas de aprendizagem') requires the student's explicit authorization and a new build.
export const AUTHORIZED_SECTIONS = Object.freeze(['atividades avaliativas']);   // compared without accents/case

// Structure observed on the real site on 05/11/2026 (counts only; docs/poc/RESULTADO_ESTRUTURAL_7653.md).
export const REFERENCE = Object.freeze({
  date: '05/11/2026',
  total: 7,
  byKind: Object.freeze({ assign: 5, resource: 1, groupselect: 1 }),
});

export const KIND_LABELS = Object.freeze({
  assign: 'Tarefa', resource: 'Arquivo', groupselect: 'Escolha de grupo', quiz: 'Questionário', forum: 'Fórum',
  attendance: 'Presença', msteams: 'Reunião (Teams)', url: 'Link', page: 'Página', folder: 'Pasta', book: 'Livro',
  imscp: 'Pacote de conteúdo', feedback: 'Pesquisa', lesson: 'Lição', choice: 'Escolha', glossary: 'Glossário',
  wiki: 'Wiki', workshop: 'Laboratório de avaliação', scorm: 'Pacote SCORM', h5pactivity: 'H5P',
  lti: 'Ferramenta externa', data: 'Base de dados', bigbluebuttonbn: 'Webconferência', chat: 'Chat',
  survey: 'Questionário de avaliação',
});

export const MODE_LABELS = Object.freeze({
  secao_pagina: 'página própria da seção (section.php)',
  painel: 'painel aberto dentro da página da disciplina (view.php)',
});

export const MESSAGES = Object.freeze({
  sem_aba: 'Não foi possível identificar a aba ativa. Abra a página da AEDB e clique no ícone da extensão.',
  sem_acesso: 'A extensão não tem acesso a esta aba. Clique no ícone da extensão com a aba da AEDB ativa.',
  dominio: 'Esta aba não está no domínio autorizado (ead.aedb.br, HTTPS). Nada foi lido.',
  login: 'Esta é uma página de login. Entre manualmente no AVA e abra a seção. Nada foi lido.',
  modulo: 'Esta é a página de uma atividade ou material. A extensão só lê a seção. Nada foi lido.',
  pagina: 'Esta página da AEDB não é a página da disciplina nem de uma seção. Nada foi lido.',
  curso_diferente: 'A disciplina desta página é diferente da autorizada. Nenhum item foi lido.',
  curso_nao_confirmado: 'A página não confirma a disciplina. Nenhum item foi lido.',
  formato: 'Esta página não usa o formato Moodle Tiles esperado. Nenhum item foi lido.',
  secao: 'Esta não é a seção Atividades Avaliativas (ou o nome da seção não pôde ser confirmado). Nenhum item foi lido.',
  painel_fechado: 'O painel da seção Atividades Avaliativas não está aberto (ou está oculto). Clique no cartão '
    + 'Atividades Avaliativas e tente de novo. Nenhum item foi lido.',
  tile_nao_encontrado: 'O cartão Atividades Avaliativas não foi encontrado nesta página. Nenhum item foi lido.',
  tile_ambiguo: 'Mais de um cartão corresponde a Atividades Avaliativas. Leitura bloqueada.',
  tile_sem_vinculo: 'O cartão Atividades Avaliativas não traz o vínculo esperado com a seção. Leitura bloqueada.',
  paineis_multiplos: 'Há mais de um painel aberto ligado à seção. Leitura bloqueada para não misturar conteúdos.',
  painel_sem_vinculo: 'Há conteúdo aberto, mas ele não pôde ser ligado com segurança ao cartão Atividades '
    + 'Avaliativas. Leitura bloqueada; veja o diagnóstico.',
  dialogo_bloqueia: 'Há uma janela (diálogo) aberta que não é a seção. Feche-a e tente de novo. Nenhum item foi lido.',
  dialogo_preferencia: 'A janela "Preferência dos dados" do AVA está aberta sobre a página. Feche-a pelo X e tente de '
    + 'novo ("Sincronizar disciplina" fecha essa janela sozinho). Nenhum item foi lido.',
  modo_incoerente: 'A estrutura da página não corresponde ao endereço. Leitura bloqueada.',
  mudou: 'A página ou o painel mudou durante a leitura. Nada foi exibido; tente de novo.',
  leitura_falhou: 'Não foi possível ler a página. Recarregue-a e clique no ícone da extensão de novo.',
  projecao_invalida: 'A página devolveu dados em formato inesperado. Nada foi exibido.',
});

const DEFAULT_SECTION = Object.freeze({ label: SECTION_LABEL, authorized: AUTHORIZED_SECTIONS });

const CHECK_LABELS = [
  ['dominio', 'Domínio autorizado (ead.aedb.br, HTTPS)'],
  ['pagina', 'Página da disciplina ou da seção na AEDB'],
  ['curso', 'Disciplina autorizada (7653)'],
  ['formato', 'Formato Moodle Tiles'],
  ['secao', 'Seção Atividades Avaliativas aberta e identificada'],
];
const VIEW_KINDS = new Set(['curso_inicio', 'curso_secao']);
const DIAG_NUMBERS = ['tiles', 'tilesMatched', 'candidates', 'visibleCandidates', 'openDialogs', 'hiddenDialogs',
  'dataPreferenceDialogs', 'unknownDialogs', 'sectionVisible', 'hiddenActivities', 'visibleActivitiesOutside'];
const TOKEN = /^[a-z][a-z0-9_:-]{0,40}$/i;

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const fold = (text) => String(text ?? '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
  .replace(/\s+/g, ' ').trim();

// Runs in the page (serialized by executeScript): must not reference anything outside itself.
function readPage(options) {
  return { href: location.href, projection: globalThis.CampusAiDomTiles.project(document, location, options) };
}

// Structural diagnostic from the page, re-validated: numbers, a reason code, tag/class/attribute names.
function cleanDiagnostic(raw) {
  if (!isObject(raw)) return null;
  const out = { reason: typeof raw.reason === 'string' && /^[a-z_]{0,40}$/.test(raw.reason) ? raw.reason : '' };
  for (const key of DIAG_NUMBERS) out[key] = Number.isInteger(raw[key]) && raw[key] >= 0 ? Math.min(raw[key], 9999) : 0;
  const list = (value) => (Array.isArray(value) ? value.filter((t) => typeof t === 'string' && TOKEN.test(t)).slice(0, 10) : []);
  out.containers = (Array.isArray(raw.containers) ? raw.containers : []).filter(isObject).slice(0, 5).map((c) => ({
    tag: typeof c.tag === 'string' && /^[a-z][a-z0-9-]{0,20}$/.test(c.tag) ? c.tag : '?',
    classes: list(c.classes), attrs: list(c.attrs),
    activities: Number.isInteger(c.activities) ? Math.min(c.activities, 9999) : 0, inDialog: c.inDialog === true,
  }));
  return out;
}

function refusal(checks, message, diagnostic = null) {
  return {
    state: 'recusado', message, checks, mode: '', section: '', rows: [], issues: [], labels: 0, byModtype: [],
    comparison: null, coverage: null, diagnostic,
  };
}

function setter(checks) {
  return (id, ok) => { checks.find((c) => c.id === id).ok = ok; };
}

function gateAddress(checks, href) {
  const set = setter(checks);
  const page = classifyPage(href);
  const inDomain = page.kind !== 'externa' && page.kind !== 'invalida';
  set('dominio', inDomain);
  if (!inDomain) return { message: MESSAGES.dominio, page };
  const usable = page.kind === 'curso_bloco' || VIEW_KINDS.has(page.kind);
  set('pagina', usable);
  if (!usable) {
    if (page.kind === 'login') return { message: MESSAGES.login, page };
    if (page.kind.startsWith('modulo_')) return { message: MESSAGES.modulo, page };
    return { message: MESSAGES.pagina, page };
  }
  if (VIEW_KINDS.has(page.kind) && !AUTHORIZED_COURSES.includes(page.moodleId)) {
    set('curso', false);
    return { message: MESSAGES.curso_diferente, page };
  }
  return { message: '', page };
}

// `section` = { label, authorized }: defaults to the validated Atividades Avaliativas section.
function gateIdentity(checks, projection, page, section = DEFAULT_SECTION) {
  const set = setter(checks);
  if (!isObject(projection)) return MESSAGES.projecao_invalida;
  const course = typeof projection.courseId === 'string' ? projection.courseId : '';
  const urlCourse = page.moodleId || '';
  const courseOk = AUTHORIZED_COURSES.includes(course) && (!VIEW_KINDS.has(page.kind) || urlCourse === course);
  set('curso', courseOk);
  if (!courseOk) return course ? MESSAGES.curso_diferente : MESSAGES.curso_nao_confirmado;
  set('formato', projection.formatTiles === true);
  if (projection.formatTiles !== true) return MESSAGES.formato;

  const expected = page.kind === 'curso_bloco' ? 'secao_pagina' : 'painel';
  if (projection.mode === 'nenhum') {
    set('secao', false);
    const reason = isObject(projection.diagnostic) ? projection.diagnostic.reason : '';
    return Object.hasOwn(MESSAGES, reason) ? MESSAGES[reason] : MESSAGES.secao;
  }
  if (projection.mode !== expected) {
    set('secao', false);
    return MESSAGES.modo_incoerente;
  }
  const name = expected === 'painel' ? projection.sectionName : sectionNameOf(projection.docTitle);
  const sectionOk = section.authorized.includes(fold(name)) && fold(name) === fold(section.label)
    && typeof projection.sectionId === 'string'
    && /^[1-9][0-9]{0,9}$/.test(projection.sectionId) && (expected !== 'secao_pagina' || projection.sectionPage === true);
  set('secao', sectionOk);
  return sectionOk ? '' : MESSAGES.secao;
}

// Address + identity of one read. Returns '' when the read is acceptable, otherwise a fixed message.
function gate(checks, result, section = DEFAULT_SECTION) {
  const address = gateAddress(checks, result.href);
  return address.message || gateIdentity(checks, result.projection, address.page, section);
}

async function read(api, tabId, withEntries, sectionLabel = SECTION_LABEL) {
  const [first] = await api.scripting.executeScript({
    target: { tabId }, func: readPage, args: [{ withEntries, sectionLabel }],
  });
  const result = first && first.result;
  if (!isObject(result) || typeof result.href !== 'string') return null;
  return result;
}

const same = (a, b) => a.href === b.href && isObject(a.projection) && isObject(b.projection)
  && a.projection.panelKey === b.projection.panelKey && a.projection.mode === b.projection.mode
  && a.projection.sectionId === b.projection.sectionId;

function compareWithReference(rows, issues) {
  const found = {};
  for (const row of rows) found[row.kind] = (found[row.kind] || 0) + 1;
  const kinds = new Set([...Object.keys(REFERENCE.byKind), ...Object.keys(found)]);
  const differences = [...kinds]
    .filter((kind) => (REFERENCE.byKind[kind] || 0) !== (found[kind] || 0))
    .map((kind) => ({ kind, label: KIND_LABELS[kind] || kind, expected: REFERENCE.byKind[kind] || 0, found: found[kind] || 0 }));
  const matches = !differences.length && !issues.length && rows.length === REFERENCE.total;
  const notes = [];
  if (!matches) {
    notes.push(`A seção tem ${rows.length + issues.length} item(ns) de módulo visíveis (sem contar rótulos): `
      + `${rows.length} válido(s) e ${issues.length} com problema.`);
    if (!issues.length) {
      notes.push('Nenhum item foi descartado pela extensão: a diferença está no conteúdo da página lida. '
        + 'A extensão não tem como determinar a causa.');
    } else {
      notes.push('Itens com problema não entram na contagem por tipo; veja a lista de problemas.');
    }
  }
  return {
    reference: { date: REFERENCE.date, total: REFERENCE.total, byKind: { ...REFERENCE.byKind } },
    found: { total: rows.length, byKind: found },
    matches, differences, notes,
  };
}

function groupByModtype(rows) {
  const groups = new Map();
  for (const row of rows) {
    const entry = groups.get(row.modtype) || {
      modtype: row.modtype, kind: row.kind, label: KIND_LABELS[row.kind] || row.kind, classe: row.classe, count: 0,
    };
    entry.count += 1;
    groups.set(row.modtype, entry);
  }
  return [...groups.values()].sort((a, b) => b.count - a.count || a.modtype.localeCompare(b.modtype));
}

// `sectionLabel` / `authorizedSections` exist for the course sync (one section at a time). Without them the
// behaviour is exactly the validated one. A label that is not authorized is refused before the tab is touched.
export async function runPreview(api, { now = new Date(), sectionLabel = SECTION_LABEL,
  authorizedSections = AUTHORIZED_SECTIONS } = {}) {
  const section = { label: sectionLabel, authorized: authorizedSections };
  const checks = CHECK_LABELS.map(([id, label]) => ({
    id, label: id === 'secao' ? `Seção ${sectionLabel} aberta e identificada` : label, ok: null }));
  if (!authorizedSections.includes(fold(sectionLabel))) return refusal(checks, MESSAGES.secao);

  let tab;
  try {
    [tab] = await api.tabs.query({ active: true, currentWindow: true });
  } catch {
    return refusal(checks, MESSAGES.sem_aba);
  }
  if (!isObject(tab) || !Number.isInteger(tab.id)) return refusal(checks, MESSAGES.sem_aba);
  if (typeof tab.url !== 'string' || !tab.url) return refusal(checks, MESSAGES.sem_acesso);

  const address = gateAddress(checks, tab.url);
  if (address.message) return refusal(checks, address.message);

  let identity;
  let full;
  let after;
  try {
    await api.scripting.executeScript({ target: { tabId: tab.id }, files: ['src/dom_tiles.js'] });
    identity = await read(api, tab.id, false, sectionLabel);
    if (!identity) return refusal(checks, MESSAGES.projecao_invalida);
    const message = gate(checks, identity, section);
    if (message) return refusal(checks, message, cleanDiagnostic(identity.projection && identity.projection.diagnostic));

    full = await read(api, tab.id, true, sectionLabel);        // only now are the items read
    after = full && await read(api, tab.id, false, sectionLabel);
  } catch {
    return refusal(checks, MESSAGES.leitura_falhou);
  }
  if (!full || !after) return refusal(checks, MESSAGES.projecao_invalida);
  if (gate(checks, full, section) || gate(checks, after, section) || !same(identity, full) || !same(identity, after)) {
    return refusal(checks, MESSAGES.mudou);
  }

  const built = buildTilesSnapshot(full.projection, { now });
  if (!built.ok) return refusal(checks, MESSAGES.projecao_invalida);

  return {
    state: 'ok',
    message: '',
    checks,
    mode: full.projection.mode,
    section: full.projection.mode === 'painel' ? full.projection.sectionName : sectionNameOf(full.projection.docTitle),
    rows: built.rows,
    issues: built.issues,
    labels: built.summary.labels,
    byModtype: groupByModtype(built.rows),
    comparison: compareWithReference(built.rows, built.issues),
    coverage: { state: built.snapshot.coverage.state, reasons: [...built.snapshot.coverage.reasons] },
    diagnostic: cleanDiagnostic(full.projection.diagnostic),
    // Kept in the popup's memory only; sent to the local app only if the student clicks "Salvar".
    snapshot: built.snapshot,
    page: (({ kind, route }) => ({ kind, route }))(classifyPage(full.href)),
  };
}

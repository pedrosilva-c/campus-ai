// Deterministic adapter for Moodle "format-tiles" section pages (AEDB), campus-ai.academic/1.
//
// Pure: no DOM, no extension APIs, no network, no storage. Input is a small PROJECTION of the page made by
// dom_tiles.js (attributes only). The projection is untrusted data: everything is re-validated here and
// again by the Python host (campus_ai/contract.py), which is the authority.
//
// Shape observed on the real site on 05/11/2026 (docs/poc/RESULTADO_ESTRUTURAL_7653.md):
//   body.format-tiles.path-course-view-section, URL /ava/course/section.php?id=<SECTION id>,
//   li.activity[data-cmid][data-modtype][data-title], `label` items used as separators,
//   data-modtype can carry a subtype (resource_pdf), AV1/AV2 are activities named in the title, not sections.
//
// Honesty rules: one section page is never a complete course; dates and delivery state are not on this
// page, so deadlines stay empty and submission stays "desconhecido"; an AV group inferred from position
// is marked as such; zero items is never "completa".

export const SCHEMA_ID = 'campus-ai.academic/1';
export const PROJECTION_ID = 'campus-ai-tiles/1';
export const MAX_ENTRIES = 500;
const MAX_TITLE = 400;
const MAX_NAME = 200;
const ROUTES = Object.freeze({ secao_pagina: '/ava/course/section.php?id', painel: '/ava/course/view.php?id' });

// Kept equal to campus_ai/contract.py (tests/test_companion_tiles.py compares them).
export const MATERIAL_KINDS = new Set(['resource', 'page', 'url', 'folder', 'book', 'imscp']);
export const ACTIVITY_KINDS = new Set(['assign', 'quiz', 'forum', 'lesson', 'choice', 'feedback', 'glossary',
  'wiki', 'workshop', 'scorm', 'h5pactivity', 'lti', 'data', 'bigbluebuttonbn', 'chat', 'survey',
  'attendance', 'groupselect', 'msteams']);

const ID = /^[1-9][0-9]{0,9}$/;
const CONTROL = /[\u0000-\u001f\u007f]/g;
const AV_TAG = /(?:^|[^A-Za-z0-9])AV\s*-?\s*([1-9])(?![0-9])/gi;

const clean = (value) => String(value ?? '').replace(CONTROL, ' ').replace(/\s+/g, ' ').trim();
const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

// data-modtype may carry a subtype ("resource_pdf"); anything else must match a known module exactly.
export function kindOf(modtype) {
  const value = String(modtype ?? '');
  if (/^resource(_[a-z0-9]{1,20})?$/.test(value)) return 'resource';
  return MATERIAL_KINDS.has(value) || ACTIVITY_KINDS.has(value) ? value : '';
}

export function titleTag(title) {
  const tags = new Set();
  for (const match of String(title).matchAll(AV_TAG)) tags.add('AV' + match[1]);
  return tags.size === 1 ? [...tags][0] : '';   // two different AV tags in one title = ambiguous
}

// Only an address of this exact module and id is kept, rebuilt from parts (query and fragment dropped).
export function canonicalUrl(hrefs, kind, cmid) {
  for (const raw of Array.isArray(hrefs) ? hrefs.slice(0, 8) : []) {
    let url;
    try { url = new URL(String(raw)); } catch { continue; }
    if (url.protocol !== 'https:' || url.hostname !== 'ead.aedb.br' || url.port || url.username || url.password) continue;
    const module = /^\/ava\/mod\/([a-z0-9]+)\/view\.php$/.exec(url.pathname);
    const ids = url.searchParams.getAll('id');
    if (module && module[1] === kind && ids.length === 1 && ids[0] === cmid) {
      return `https://ead.aedb.br/ava/mod/${kind}/view.php?id=${cmid}`;
    }
  }
  return '';
}

function parseDocTitle(docTitle) {
  const parts = String(docTitle ?? '').split('|').map(clean).filter(Boolean);
  if (parts.length === 2) {           // course home: "Curso: <course> | AVA"
    const course = /^Curso:\s*(.+)$/i.exec(parts[0]);
    return { section: '', course: course ? course[1].slice(0, MAX_NAME) : '' };
  }
  if (parts.length < 3) return { section: '', course: '' };
  const named = /^Bloco:\s*(.+)$/i.exec(parts[0]);
  return { section: named ? named[1].slice(0, MAX_NAME) : '', course: parts[parts.length - 2].slice(0, MAX_NAME) };
}

// Section name as written in the tab title ("Bloco: <name> | <course> | AVA"); '' when it cannot be read.
export function sectionNameOf(docTitle) {
  return parseDocTitle(docTitle).section;
}

function refuse(code) {
  return { ok: false, code };
}

export function buildTilesSnapshot(projection, { now = new Date() } = {}) {
  if (!isObject(projection) || projection.projection !== PROJECTION_ID || !Array.isArray(projection.entries)) {
    return refuse('projecao_invalida');
  }
  if (projection.entries.length > MAX_ENTRIES) return refuse('projecao_invalida');
  if (typeof projection.courseId !== 'string' || !ID.test(projection.courseId)) return refuse('identidade_nao_confirmada');
  // Two supported ways to show a section: its own page (section.php) or a panel opened in view.php.
  const mode = projection.mode;
  const pageOk = mode === 'secao_pagina' && projection.sectionPage === true;
  if (projection.formatTiles !== true || !(pageOk || mode === 'painel')) return refuse('formato_nao_suportado');
  if (typeof projection.sectionId !== 'string' || !ID.test(projection.sectionId)) return refuse('secao_sem_id');

  const cid = projection.courseId;
  const courseUid = `moodle:course:${cid}`;
  const sectionUid = `${courseUid}:section:id-${projection.sectionId}`;
  const observed = now.toISOString().replace(/\.\d{3}Z$/, 'Z');
  const provenance = () => ({ source: 'companion', observed_at: observed, method: 'dom', route: ROUTES[mode] });
  const names = parseDocTitle(projection.docTitle);
  if (mode === 'painel') names.section = clean(projection.sectionName).slice(0, MAX_NAME);
  const hidden = isObject(projection.diagnostic) && Number.isInteger(projection.diagnostic.hiddenActivities)
    ? projection.diagnostic.hiddenActivities : 0;

  // 1. Entries -> rows, split into blocks at label separators (the label TEXT is never carried here).
  const skipped = { sem_tipo: 0, sem_id: 0, sem_titulo: 0, repetido: 0, truncado: 0 };
  const seen = new Set();
  const blocks = [[]];
  const issues = [];     // for the local preview: why an entry was not converted (no titles)
  let labels = 0;
  let position = 0;      // 1-based position among the non-label entries
  const problem = (code, entry) => {
    skipped[code] += 1;
    issues.push({
      position, code,
      modtype: isObject(entry) ? clean(entry.modtype).slice(0, 40) : '',
      cmid: isObject(entry) && typeof entry.cmid === 'string' ? clean(entry.cmid).slice(0, 12) : '',
    });
  };
  for (const entry of projection.entries) {
    if (isObject(entry) && entry.label === true) {
      labels += 1;
      if (blocks[blocks.length - 1].length) blocks.push([]);
      continue;
    }
    position += 1;
    if (!isObject(entry)) { problem('sem_tipo', entry); continue; }
    const kind = kindOf(entry.modtype);
    const cmid = typeof entry.cmid === 'string' ? entry.cmid : '';
    let title = clean(entry.title);
    if (!kind) { problem('sem_tipo', entry); continue; }
    if (!ID.test(cmid)) { problem('sem_id', entry); continue; }
    if (!title) { problem('sem_titulo', entry); continue; }
    if (seen.has(cmid)) { problem('repetido', entry); continue; }
    seen.add(cmid);
    if (title.length > MAX_TITLE) { title = title.slice(0, MAX_TITLE); skipped.truncado += 1; }
    blocks[blocks.length - 1].push({
      position, modtype: clean(entry.modtype).slice(0, 40), kind, cmid, title,
      url: canonicalUrl(entry.hrefs, kind, cmid), tag: titleTag(title), basis: '',
    });
  }

  // 2. AV groups: stated in the title ('titulo'), else inherited from the block when the block carries
  //    exactly one AV tag ('posicao', lower confidence). Ambiguous blocks stay ungrouped.
  let inferred = 0;
  for (const block of blocks) {
    const stated = new Set(block.filter((row) => row.tag).map((row) => row.tag));
    const only = stated.size === 1 ? [...stated][0] : '';
    for (const row of block) {
      if (row.tag) row.basis = 'titulo';
      else if (only) { row.tag = only; row.basis = 'posicao'; inferred += 1; }
    }
  }

  // 3. Records.
  const materials = [];
  const activities = [];
  for (const row of blocks.flat()) {
    const common = {
      uid: `${courseUid}:module:${row.cmid}`, course_uid: courseUid, section_uid: sectionUid,
      title: row.title, kind: row.kind, url: row.url, provenance: provenance(), verification: 'confirmado',
      confidence: row.basis === 'posicao' ? 'media' : 'alta', assessment: row.tag, assessment_basis: row.basis,
    };
    if (MATERIAL_KINDS.has(row.kind)) materials.push(common);
    else activities.push({ ...common, deadlines: [], submission: 'desconhecido' });
  }

  const total = materials.length + activities.length;
  const reasons = [
    'Somente esta seção foi lida; as demais seções do curso não foram examinadas.',
    'Prazos e estado de entrega não aparecem nesta página: ficam desconhecidos, não ausentes.',
  ];
  if (inferred) reasons.push(`${inferred} item(ns) foram agrupados em AV pela posição entre rótulos, não pelo título.`);
  if (skipped.sem_tipo) reasons.push(`${skipped.sem_tipo} item(ns) de tipo não reconhecido não foram convertidos.`);
  if (skipped.sem_id) reasons.push(`${skipped.sem_id} item(ns) sem identificador válido não foram convertidos.`);
  if (skipped.sem_titulo) reasons.push(`${skipped.sem_titulo} item(ns) sem título não foram convertidos.`);
  if (skipped.repetido) reasons.push(`${skipped.repetido} item(ns) repetido(s) foram ignorados.`);
  if (skipped.truncado) reasons.push(`${skipped.truncado} título(s) acima do limite foram cortados.`);
  if (projection.truncated === true) reasons.push('A lista da página excedeu o limite e foi cortada.');
  if (!names.section) reasons.push('O nome da seção não pôde ser lido do título da página.');
  if (mode === 'painel') reasons.push('Lida a partir do painel aberto na página da disciplina (endereço sem mudança).');
  if (hidden > 0) reasons.push(`${hidden} item(ns) oculto(s) na seção não foram lidos.`);
  if (!total) reasons.push('Nenhum material ou atividade foi extraído: cobertura não validada.');

  const state = total ? 'parcial' : 'nao_validada';
  const snapshot = {
    schema: SCHEMA_ID,
    generated_at: observed,
    scope: [courseUid],
    coverage: { state, reasons },
    sources: [{
      source: 'companion', last_attempt: observed, last_success: observed,
      status: total ? 'parcial' : 'nao_verificado', message: '',
    }],
    courses: [{
      uid: courseUid, moodle_id: cid, name: names.course || `Disciplina ${cid}`,
      url: `https://ead.aedb.br/ava/course/view.php?id=${cid}`, provenance: provenance(),
      verification: 'confirmado', confidence: 'alta',
    }],
    sections: [{
      uid: sectionUid, course_uid: courseUid, name: names.section || 'Seção sem nome', position: null,
      state: 'aberta', provenance: provenance(), verification: names.section ? 'confirmado' : 'parcial',
      confidence: names.section ? 'alta' : 'baixa',
    }],
    materials,
    activities,
    events: [],
    announcements: [],
  };
  // `rows` and `issues` are for the in-browser preview only (they keep the raw data-modtype and the
  // reason an entry was left out). They are not part of the snapshot and never leave the browser.
  const rows = blocks.flat().map((row) => ({
    position: row.position, cmid: row.cmid, modtype: row.modtype, kind: row.kind,
    classe: MATERIAL_KINDS.has(row.kind) ? 'material' : 'atividade', title: row.title,
    assessment: row.tag, basis: row.basis, hasUrl: Boolean(row.url),
  }));
  return {
    ok: true,
    snapshot,
    summary: { materials: materials.length, activities: activities.length, labels, inferred, skipped },
    rows,
    issues,
  };
}

// Campus AI Companion — what each tile of the course is, and whether the course sync may read it. Pure.
//
// Decisions (strictest wins):
//   bloqueada     communication/feedback tiles, dangerous wording, links that are not a same-site section link,
//                 tiles that are not clickable/visible/same-tab, or two tiles claiming the same section;
//   ignorada      informative tiles (not academic content);
//   desconhecida  labels this version does not know: never opened;
//   nao_autorizada an academic section the student has not authorized yet (e.g. Trilhas de Aprendizagem);
//   ler           an academic section in AUTHORIZED_SECTIONS (preview.js), read in ACADEMIC_ORDER.
import { AUTHORIZED_SECTIONS } from './preview.js';

export const ROLE_BY_LABEL = Object.freeze({
  'atividades avaliativas': 'academica',
  'trilhas de aprendizagem': 'academica',
  'informacoes da disciplina': 'informativa',
  'avisos': 'informativa',
  'curriculo lattes': 'informativa',
  'feedback das aulas': 'comunicacao',
  'fale com o professor': 'comunicacao',
});
export const DISPLAY = Object.freeze({
  'atividades avaliativas': 'Atividades Avaliativas',
  'trilhas de aprendizagem': 'Trilhas de Aprendizagem',
});
export const ACADEMIC_ORDER = Object.freeze(['atividades avaliativas', 'trilhas de aprendizagem']);
export const ROLE_TEXT = Object.freeze({
  academica: 'Seção acadêmica', informativa: 'Informativo', comunicacao: 'Comunicação/avaliação', desconhecida: 'Desconhecido',
});
export const DECISION_TEXT = Object.freeze({
  ler: 'Será lida', nao_autorizada: 'Acadêmica — ainda não autorizada (não é aberta)', bloqueada: 'Bloqueada — nunca é aberta',
  ignorada: 'Não acadêmica — não é lida', desconhecida: 'Desconhecida — não é aberta',
});
// Same list as open_panel.js and the desktop pilot.
const DANGEROUS = ['feedback', 'fale com', 'enviar', 'finalizar', 'concluir', 'responder', 'excluir', 'editar',
  'baixar', 'download', 'submeter', 'marcar como', 'tentativa'];

const fold = (text) => String(text ?? '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
  .replace(/\s+/g, ' ').trim();
const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

export function roleOf(label) {
  const folded = fold(label);
  const keys = Object.keys(ROLE_BY_LABEL).filter((key) => folded.includes(key));
  return keys.length === 1 ? { key: keys[0], role: ROLE_BY_LABEL[keys[0]] } : { key: '', role: 'desconhecida' };
}

export function classifyTile(tile, authorized = AUTHORIZED_SECTIONS) {
  const { key, role } = roleOf(tile.label);
  const folded = fold(tile.label);
  const out = (decision, reason = '') => ({ key, role, decision, reason });
  if (role === 'comunicacao') return out('bloqueada', 'comunicacao');
  if (DANGEROUS.some((word) => folded.includes(word))) return out('bloqueada', 'rotulo_perigoso');
  if (role === 'informativa') return out('ignorada', 'informativo');
  if (role === 'desconhecida') return out('desconhecida', 'rotulo_desconhecido');
  if (tile.linkKind !== 'secao') return out('bloqueada', `link_${tile.linkKind}`);
  if (tile.links !== 1 || tile.sameTab !== true || tile.clickable !== true || tile.visible !== true || !tile.sectionId) {
    return out('bloqueada', 'nao_clicavel');
  }
  if (!authorized.includes(key)) return out('nao_autorizada', 'nao_autorizada');
  return out('ler');
}

// The order is fixed (ACADEMIC_ORDER), so a module that appears in two sections always belongs to the same one.
export function buildPlan(catalog, authorized = AUTHORIZED_SECTIONS) {
  const tiles = isObject(catalog) && Array.isArray(catalog.tiles) ? catalog.tiles.filter(isObject).slice(0, 30) : [];
  const entries = tiles.map((tile) => ({
    position: Number.isInteger(tile.position) ? tile.position : 0,
    label: typeof tile.label === 'string' ? tile.label.slice(0, 120) : '',
    ...classifyTile({ ...tile, label: typeof tile.label === 'string' ? tile.label : '' }, authorized),
  }));
  const counts = {};
  for (const entry of entries) if (entry.key) counts[entry.key] = (counts[entry.key] || 0) + 1;
  for (const entry of entries) {
    if (entry.key && counts[entry.key] > 1 && entry.decision !== 'bloqueada') Object.assign(entry, { decision: 'bloqueada', reason: 'duplicado' });
  }
  const toRead = ACADEMIC_ORDER
    .map((key) => entries.find((entry) => entry.key === key && entry.decision === 'ler'))
    .filter(Boolean)
    .map((entry) => ({ ...entry, display: DISPLAY[entry.key] }));
  return { entries, toRead };
}

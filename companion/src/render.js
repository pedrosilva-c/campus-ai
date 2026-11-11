// Campus AI Companion — renders a preview model into the popup.
// Every string, including titles and ids that come from the page, is inserted with createTextNode /
// textContent. No HTML is ever parsed from page data, and attributes are only fixed names with fixed values.
import { SITUATION_TEXT } from './deadlines.js';

const STATE_TEXT = { true: 'Confirmado', false: 'Não confirmado', null: 'Não avaliado' };
const STATE_MARK = { true: '✓', false: '✗', null: '—' };
const STATE_CLASS = { true: 'ok', false: 'no', null: 'na' };
const COVERAGE_TEXT = {
  parcial: 'Cobertura parcial', completa: 'Cobertura completa', nao_validada: 'Cobertura não validada',
  falhou: 'Leitura falhou',
};
const ISSUE_TEXT = {
  sem_tipo: 'tipo não reconhecido', sem_id: 'identificador (cmid) ausente ou inválido',
  sem_titulo: 'título ausente', repetido: 'identificador repetido (ignorado)',
};
const BASIS_TEXT = { titulo: 'pelo título', posicao: 'pela posição (inferido)' };

function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(props)) {
    if (name === 'class') node.className = value;
    else node.setAttribute(name, value);           // only called with literal names/values from this file
  }
  for (const child of children) {
    if (child === null || child === undefined) continue;
    node.append(typeof child === 'string' ? document.createTextNode(child) : child);
  }
  return node;
}

function table(caption, headings, bodyRows) {
  const head = h('tr', {}, ...headings.map((text) => h('th', { scope: 'col' }, text)));
  const body = bodyRows.map((cells) => h('tr', {}, ...cells.map((cell) => h('td', {}, String(cell)))));
  return h('table', {}, h('caption', {}, caption), h('thead', {}, head), h('tbody', {}, ...body));
}

function checksList(checks) {
  return h('ul', { class: 'checks', 'aria-label': 'Verificações de segurança' }, ...checks.map((check) => {
    const key = String(check.ok);
    return h('li', { class: STATE_CLASS[key] },
      h('span', { class: 'mark', 'aria-hidden': 'true' }, STATE_MARK[key]), h('span', {}, check.label),
      h('span', { class: 'state' }, STATE_TEXT[key]));
  }));
}

function comparisonBlock(comparison) {
  const ref = comparison.reference;
  const refText = Object.entries(ref.byKind).map(([kind, count]) => `${count} ${kind}`).join(', ');
  const block = h('section', { class: 'block' }, h('h2', {}, 'Comparação com a referência'),
    h('p', {}, `Referência de ${ref.date}: ${ref.total} módulos não rotulados (${refText}).`),
    h('p', { class: comparison.matches ? 'verdict ok' : 'verdict no' },
      comparison.matches ? 'Confere: mesma quantidade e mesmos tipos.' : 'Difere da referência.'));
  if (comparison.differences.length) {
    block.append(table('Diferenças por tipo', ['Tipo', 'Esperado', 'Encontrado'],
      comparison.differences.map((d) => [d.label, d.expected, d.found])));
  }
  if (comparison.notes.length) block.append(h('ul', {}, ...comparison.notes.map((note) => h('li', {}, note))));
  return block;
}

const MODE_TEXT = {
  secao_pagina: 'página própria da seção (section.php)',
  painel: 'painel aberto dentro da página da disciplina (view.php)',
};
const DIAG_TEXT = [
  ['tiles', 'cartões (tiles) com link'], ['tilesMatched', 'cartões que correspondem à seção'],
  ['candidates', 'regiões ligadas ao cartão por atributo'], ['visibleCandidates', 'dessas, visíveis'],
  ['sectionVisible', 'seção visível e identificada (1 = sim, 0 = não identificada)'],
  ['openDialogs', 'diálogos abertos'], ['dataPreferenceDialogs', 'janela "Preferência dos dados" identificada'],
  ['unknownDialogs', 'diálogos desconhecidos (bloqueiam a leitura)'], ['hiddenDialogs', 'diálogos ocultos (não bloqueiam)'],
  ['hiddenActivities', 'itens ocultos ignorados'], ['visibleActivitiesOutside', 'itens visíveis fora da seção (ignorados)'],
];

// Structure only: counts, tag names, class tokens and attribute names. Useful to adapt the reader to the
// real page without sending anything anywhere.
function diagnosticBlock(diagnostic) {
  const block = h('section', { class: 'block' }, h('h2', {}, 'Diagnóstico estrutural (sem conteúdo)'));
  if (diagnostic.reason) block.append(h('p', {}, `Motivo técnico: ${diagnostic.reason}`));
  block.append(table('Contagens', ['Medida', 'Valor'], DIAG_TEXT.map(([key, text]) => [text, diagnostic[key]])));
  if (diagnostic.containers.length) {
    block.append(table('Regiões com itens visíveis', ['Tag', 'Classes', 'Atributos', 'Itens', 'Em diálogo'],
      diagnostic.containers.map((c) => [c.tag, c.classes.join(' ') || '—', c.attrs.join(' ') || '—', c.activities,
        c.inDialog ? 'sim' : 'não'])));
  }
  return block;
}

export function renderBusy(root) {
  root.replaceChildren(h('p', { role: 'status' }, 'Lendo a página…'));
}

// Fixed texts for the outcome of "Salvar no Campus AI". Saved is claimed only for code 'salvo'.
export const SAVE_TEXT = {
  indisponivel_nesta_versao: 'Integração local não disponível: esta é a versão só de pré-visualização da extensão.',
  host_nao_instalado: 'Integração local não disponível: o aplicativo Campus AI não está registrado neste Windows.',
  host_indisponivel: 'O aplicativo Campus AI não respondeu. Nada foi salvo.',
  desconectado: 'A conexão com o aplicativo caiu antes da confirmação. Não há confirmação de que algo foi salvo.',
  tempo_esgotado: 'O aplicativo não confirmou a tempo. Não há confirmação de que algo foi salvo.',
  sem_confirmacao: 'O aplicativo recebeu a leitura, mas não confirmou o salvamento.',
  falha_persistencia: 'O aplicativo não conseguiu gravar a leitura (nada foi gravado).',
  sem_permissao: 'O aplicativo não tem permissão para gravar no banco local (nada foi gravado).',
  banco_indisponivel: 'O banco local do aplicativo não está disponível (nada foi gravado).',
  disciplina_nao_autorizada: 'O aplicativo recusou: disciplina não autorizada.',
  esquema_invalido: 'O aplicativo recusou: dados fora do contrato.',
  grande_demais: 'A leitura é grande demais para ser enviada.',
};

export function savedText(r) {
  return `Salvo no Campus AI (leitura nº ${r.run}): ${r.novos} novo(s), ${r.alterados} alterado(s), `
    + `${r.ausentes} ausente(s) nesta leitura, ${r.reaparecidos} reaparecido(s), ${r.inalterados} sem mudança.`;
}

// The ONLY place where a reading is sent: the click handler of this button. The button is disabled before the save
// starts, so repeated clicks cannot send twice. `report(outcome, status)` describes the result and returns true
// when the button may be used again (one section, refused before anything was saved).
function reportOne(outcome, status) {
  if (outcome.saved) {
    status.textContent = savedText(outcome.result);
    return false;                                 // stays disabled: one save per reading
  }
  status.textContent = SAVE_TEXT[outcome.code] || `Não salvo (${outcome.code}).`;
  return true;
}

function saveBlock(onSave, { intro = 'Envia esta leitura somente ao aplicativo Campus AI deste computador.', report = reportOne } = {}) {
  const status = h('p', { role: 'status' }, 'Nada foi enviado. O envio só acontece se você clicar no botão.');
  const button = h('button', { type: 'button', class: 'secondary' }, 'Salvar no Campus AI');
  const details = h('div', {});
  button.addEventListener('click', async () => {
    if (button.disabled) return;
    button.disabled = true;
    status.textContent = 'Enviando ao aplicativo Campus AI deste computador…';
    let outcome;
    try {
      outcome = await onSave();
    } catch {
      outcome = { saved: false, code: 'erro' };
    }
    if (report(outcome, status, details)) button.disabled = false;
  });
  return h('section', { class: 'block' }, h('h2', {}, 'Salvar no Campus AI'), h('p', {}, intro), button, status, details);
}

export function renderPreview(root, model, { onSave } = {}) {
  const nodes = [h('section', { class: 'block' }, h('h2', {}, 'Verificações'), checksList(model.checks))];

  if (model.state !== 'ok') {
    nodes.push(h('p', { class: 'verdict no', role: 'alert' }, model.message));
    if (model.diagnostic) nodes.push(diagnosticBlock(model.diagnostic));
    root.replaceChildren(...nodes);
    return;
  }

  const total = model.rows.length;
  nodes.push(h('section', { class: 'block' }, h('h2', {}, 'Resultado'),
    h('p', {}, `Seção: ${model.section}`),
    h('p', {}, `Modo: ${MODE_TEXT[model.mode] || model.mode}`),
    h('p', { class: 'big' }, `${total} módulo(s) não rotulado(s) válido(s)`),
    h('p', {}, `${model.labels} rótulo(s) ignorado(s) (o texto dos rótulos não é lido).`),
    table('Módulos por tipo', ['Tipo (data-modtype)', 'Classificação', 'Quantidade'],
      model.byModtype.map((g) => [g.modtype, `${g.classe === 'material' ? 'Material' : 'Atividade'} — ${g.label}`, g.count]))));

  nodes.push(comparisonBlock(model.comparison));
  const details = detailsBlock(model.details);
  if (details) nodes.push(details);

  nodes.push(h('section', { class: 'block' }, h('h2', {}, 'Módulos encontrados'),
    total ? table('Módulos na ordem da página',
      ['#', 'Tipo', 'Classe', 'cmid', 'Título', 'Grupo AV', 'Link'],
      model.rows.map((r) => [r.position, r.modtype, r.classe === 'material' ? 'Material' : 'Atividade', r.cmid, r.title,
        r.assessment ? `${r.assessment} (${BASIS_TEXT[r.basis] || r.basis})` : '—', r.hasUrl ? 'sim' : 'não']))
      : h('p', {}, 'Nenhum módulo válido.')));

  if (model.issues.length) {
    nodes.push(h('section', { class: 'block' }, h('h2', {}, 'Problemas encontrados'),
      table('Itens não convertidos', ['#', 'Motivo', 'Tipo informado', 'cmid informado'],
        model.issues.map((i) => [i.position, ISSUE_TEXT[i.code] || i.code, i.modtype || '—', i.cmid || '—']))));
  } else {
    nodes.push(h('section', { class: 'block' }, h('h2', {}, 'Problemas encontrados'),
      h('p', {}, 'Nenhum: sem duplicações, títulos ausentes, identificadores ausentes ou tipos desconhecidos.')));
  }

  nodes.push(h('section', { class: 'block' }, h('h2', {}, 'Cobertura e limitações'),
    h('p', { class: 'big' }, COVERAGE_TEXT[model.coverage.state] || model.coverage.state),
    h('ul', {}, ...model.coverage.reasons.map((reason) => h('li', {}, reason)))));

  if (onSave) nodes.push(saveBlock(onSave));
  nodes.push(h('p', { class: 'foot' }, 'Este resultado existe só na memória desta janela. Nada é escrito no Moodle. '
    + 'Fechar o popup descarta tudo o que não foi salvo.'));
  root.replaceChildren(...nodes);
}

// --- "Sincronizar disciplina": progress, outcome ---------------------------------------------------------------
const STEP_MARK = { pendente: '○', andamento: '…', ok: '✓', falhou: '✗', pulado: '–', aguardando: '○', parcial: '!' };
const STEP_TEXT = { pendente: 'Aguardando', andamento: 'Em andamento', ok: 'Concluído', falhou: 'Falhou', pulado: 'Não foi preciso',
  aguardando: 'Aguardando você', parcial: 'Parcial' };

// --- v0.5.4: deadlines and delivery read from each activity's page -------------------------------------------
const SUBMISSION_TEXT = { sem_envio: 'Nenhum envio', rascunho: 'Rascunho (não enviado)', enviado: 'Enviado para avaliação',
  reaberto: 'Reaberto (precisa reenviar)', desconhecido: 'Não verificado', nao_se_aplica: '—' };
const GRADING_TEXT = { avaliado: 'avaliado', nao_avaliado: 'não avaliado', desconhecido: '', nao_se_aplica: '' };
const ATTEMPT_TEXT = { nenhuma: 'Nenhuma tentativa', em_andamento: 'Tentativa em andamento', finalizada: 'Tentativa finalizada',
  desconhecido: 'Não verificado', nao_se_aplica: '—' };
const RESULT_TEXT = { ok: '', nao_consultada: 'não consultada', redirecionado: 'a página redirecionou (sessão expirada ou acesso negado)',
  sessao_expirada: 'sessão expirada', inacessivel: 'página inacessível', tempo_esgotado: 'tempo esgotado',
  falha_rede: 'falha de carregamento', falha_http: 'erro do servidor', pagina_nao_reconhecida: 'página não reconhecida',
  estrutura_desconhecida: 'estrutura desconhecida', acesso_perdido: 'acesso à aba perdido', nao_html: 'resposta inesperada',
  grande_demais: 'página grande demais', curso_diferente: 'disciplina diferente', fora_do_dominio: 'fora do domínio',
  parametros_invalidos: 'parâmetros inválidos' };

function wallText(at) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?$/.exec(at || '');
  return m ? `${m[3]}/${m[2]}/${m[1]}${m[4] ? ` ${m[4]}:${m[5]}` : ''}` : '';
}

function dateCell(item, kind) {
  const d = item.deadlines.find((x) => x.kind === kind);
  if (!d) return item.detail.result === 'ok' ? (kind === (item.kind === 'quiz' ? 'fechamento' : 'entrega') && item.detail.due_state === 'sem_prazo'
    ? 'sem prazo definido' : '—') : 'não verificado';
  return wallText(d.at) || `não interpretado ("${d.raw}")`;
}

function detailsBlock(details) {
  if (!details || !details.length) return null;
  const rows = details.map((item) => {
    const d = item.detail;
    const delivery = item.kind === 'quiz' ? ATTEMPT_TEXT[d.attempt_state] || d.attempt_state
      : [SUBMISSION_TEXT[d.submission_state] || d.submission_state, GRADING_TEXT[d.grading_state]].filter(Boolean).join(', ');
    return [item.title, item.kind === 'quiz' ? 'Questionário' : 'Tarefa', dateCell(item, 'abertura'),
      dateCell(item, item.kind === 'quiz' ? 'fechamento' : 'entrega'), item.kind === 'quiz' ? '—' : dateCell(item, 'limite'),
      d.result === 'ok' ? delivery : `Não verificado (${RESULT_TEXT[d.result] || d.result})`,
      SITUATION_TEXT[item.situation] || item.situation];
  });
  return h('section', { class: 'block' }, h('h2', {}, 'Prazos e entregas (lidos nas páginas das atividades)'),
    table('Uma linha por tarefa ou questionário', ['Atividade', 'Tipo', 'Abertura', 'Entrega / fechamento', 'Data limite',
      'Estado', 'Situação'], rows),
    h('p', {}, 'Horários como o Moodle os mostra (America/Sao_Paulo). "Não verificado" nunca significa "sem prazo" nem '
      + '"sem pendência". Nada foi enviado, iniciado ou alterado no Moodle; abrir a página de uma atividade é registrado '
      + 'pelo Moodle como uma visualização, como se você a abrisse.'));
}

function stepsList(steps) {
  return h('ol', { class: 'steps', 'aria-label': 'Etapas da sincronização' }, ...steps.map((step) =>
    h('li', { class: `step ${step.status}` },
      h('span', { class: 'mark', 'aria-hidden': 'true' }, STEP_MARK[step.status] || '○'),
      h('span', {}, step.label),
      h('span', { class: 'state' }, STEP_TEXT[step.status] || step.status),
      step.note ? h('span', { class: 'note' }, step.note) : null)));
}

export function renderSteps(root, steps) {
  root.replaceChildren(h('section', { class: 'block' }, h('h2', {}, 'Sincronização'), stepsList(steps)));
}

// Final line + the usual preview tables. `onSave` (manual button) is offered only when nothing was saved.
export function renderSyncOutcome(progressRoot, resultRoot, outcome, { onSave } = {}) {
  renderSteps(progressRoot, outcome.steps);
  const saved = outcome.state === 'salvo';
  const good = saved || outcome.state === 'lido';                 // 'lido': read and validated, waiting for "Salvar"
  const line = saved ? `${outcome.message} ${savedText(outcome.saved.result)}` : outcome.message;
  progressRoot.append(h('p', { class: good ? 'verdict ok' : 'verdict no', role: good ? 'status' : 'alert' }, line));
  if (outcome.dialogsClosed > 0) {
    progressRoot.append(h('p', {}, 'A janela "Preferência dos dados" foi fechada automaticamente pelo X (como você '
      + 'autorizou); "Sim" e "Cancelar" não foram acionados. A seção foi revalidada antes da leitura.'));
  }
  if (outcome.saved && !outcome.saved.saved) {
    progressRoot.append(h('p', {}, SAVE_TEXT[outcome.saved.code] || `Não salvo (${outcome.saved.code}).`));
  }
  if (outcome.model && outcome.model.state === 'ok') {
    renderPreview(resultRoot, outcome.model, saved ? {} : { onSave });
  } else if (outcome.model) {
    renderPreview(resultRoot, outcome.model);
  } else {
    resultRoot.replaceChildren();
  }
}

// --- "Sincronizar seções autorizadas" (experimental): plan, progress, one summary for the course ---------------
const ROLE_TEXT = { academica: 'Seção acadêmica', informativa: 'Informativo', comunicacao: 'Comunicação/avaliação',
  desconhecida: 'Desconhecido' };
const DECISION_TEXT = { ler: 'Será lida', nao_autorizada: 'Acadêmica — ainda não autorizada (não é aberta)',
  bloqueada: 'Bloqueada — nunca é aberta', ignorada: 'Não acadêmica — não é lida', desconhecida: 'Desconhecida — não é aberta' };
// Reading phase (nothing saved yet) and saving phase (after the click), per section.
const READ_STATE_TEXT = { lido: 'Lida e validada (ainda não salva)', recusado: 'Falhou na leitura (não será salva)',
  cancelado: 'Cancelada', erro: 'Erro na leitura (não será salva)', pendente: 'Não executada' };
const SAVE_STATE_TEXT = { salvo: 'Salva', falhou: 'FALHOU (não gravada)', repetida: 'Nada a enviar (módulos já salvos por outra seção)',
  pendente: 'Não enviada' };

function planBlock(plan) {
  return h('section', { class: 'block' }, h('h2', {}, 'Cartões da disciplina'),
    table('O que cada cartão é e se será lido', ['Cartão', 'Tipo', 'Decisão'],
      plan.entries.map((e) => [e.label || '—', ROLE_TEXT[e.role] || e.role, DECISION_TEXT[e.decision] || e.decision])));
}

export function renderCourseProgress(root, event, plan) {
  const nodes = [];
  if (plan) nodes.push(planBlock(plan));
  if (event && event.phase === 'secao') {
    nodes.push(h('section', { class: 'block' }, h('h2', {}, `Seção ${event.index + 1} de ${event.total}: ${event.label}`),
      stepsList(event.steps || [])));
  }
  root.replaceChildren(...nodes);
}

// Result of the single save of the course readings: one line per section, never "all saved" with a failure.
function reportCourse(outcome, status, details) {
  const ok = outcome.state === 'salvo';
  status.textContent = outcome.message || 'Nada foi salvo.';
  status.className = ok ? 'verdict ok' : 'verdict no';
  const rows = (outcome.sections || []).map((s) => [s.label, SAVE_STATE_TEXT[s.state] || s.state,
    s.state === 'salvo' && s.saved && s.saved.result ? savedText(s.saved.result)
      : s.state === 'falhou' && s.saved ? (SAVE_TEXT[s.saved.code] || `Não salvo (${s.saved.code}).`) : (s.message || '—'),
    s.omitted ? `${s.omitted} (já salvos por outra seção)` : '0']);
  details.replaceChildren(table('Resultado do salvamento, na ordem das seções', ['Seção', 'Resultado', 'Detalhe', 'Omitidos'], rows));
  return false;                                   // one save per reading: to try again, synchronize again
}

export function renderCourseOutcome(progressRoot, resultRoot, outcome, { onSave } = {}) {
  const nodes = [];
  if (outcome.plan) nodes.push(planBlock(outcome.plan));
  const ok = outcome.state === 'lido';
  nodes.push(h('p', { class: ok ? 'verdict ok' : 'verdict no', role: ok ? 'status' : 'alert' }, outcome.message));
  progressRoot.replaceChildren(...nodes);
  if (!outcome.sections || !outcome.sections.length) {
    resultRoot.replaceChildren();
    return;
  }
  const rows = outcome.sections.map((s) => [s.label, READ_STATE_TEXT[s.state] || s.state,
    s.state === 'lido' ? `${s.rows} módulo(s) válido(s)` : (s.message || '—'),
    s.dialogsClosed ? 'sim (pelo X)' : 'não']);
  const c = outcome.coverage;
  const blocks = [h('section', { class: 'block' }, h('h2', {}, 'Resumo da disciplina (nada foi salvo ainda)'),
    table('Uma linha por seção autorizada', ['Seção', 'Leitura', 'Detalhe', 'Janela "Preferência dos dados" fechada'], rows),
    h('p', { class: 'big' }, `Cobertura da disciplina: parcial — ${c.lidas} de ${c.autorizadas} seção(ões) autorizada(s) lida(s); `
      + `${c.academicas} seção(ões) acadêmica(s) encontrada(s).`),
    h('ul', {},
      h('li', {}, `Acadêmicas ainda não autorizadas (não abertas): ${c.naoAutorizadas.join(', ') || 'nenhuma'}.`),
      h('li', {}, `Bloqueadas (nunca abertas): ${c.bloqueadas.join(', ') || 'nenhum'}.`),
      h('li', {}, `Não acadêmicas ou desconhecidas (não lidas): ${c.ignoradas.join(', ') || 'nenhum'}.`),
      h('li', {}, 'Prazos e entregas vêm da página de cada tarefa ou questionário; o que não pôde ser lido aparece '
        + 'como "não verificado".')))];
  for (const section of outcome.sections) {
    const block = detailsBlock(section.details);
    if (block) {
      block.prepend(h('p', { class: 'big' }, section.label));
      blocks.push(block);
    }
  }
  if (onSave) {
    blocks.push(saveBlock(onSave, { report: reportCourse,
      intro: 'Envia as seções lidas ao aplicativo Campus AI deste computador, uma após a outra, na ordem acima. '
        + 'Um módulo repetido fica com a primeira seção cujo salvamento for confirmado.' }));
  }
  blocks.push(h('p', { class: 'foot' }, 'As leituras existem só na memória desta janela. Fechar o popup antes de salvar '
    + 'descarta tudo o que não foi salvo.'));
  resultRoot.replaceChildren(...blocks);
}

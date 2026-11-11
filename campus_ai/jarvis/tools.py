"""The assistant's tools. Each one does real work on real local data and says how each fact is known.

Allowed without asking: reading local data (read-only), creating files in the delivery folder, memory, reminders.
Needs confirmation: deleting anything (memory). Not available at all (refused with the reason): sending e-mail,
submitting or starting anything in the Moodle, sharing, paying — those are not tools of this assistant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import deadlines as dl
from . import academic, documents
from .store import JarvisStore

KNOWLEDGE_TEXT = {'confirmado': 'confirmado na página da atividade', 'desatualizado': 'verificado há mais de 24 h',
                  'nao_verificado': 'não verificado'}
WEEKDAY = ('segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo')
SCOPE_NOTE = ('Cobertura parcial: só a seção Atividades Avaliativas da disciplina 7653 é lida pelo Companion; '
              'outras seções e disciplinas não são examinadas.')


class Cancelled(Exception):
    """The student pressed "Interromper"."""


@dataclass
class Context:
    store: JarvisStore
    live_db: Path
    output_dir: Path
    now: datetime                                   # aware
    cancelled: callable = lambda: False
    obsidian_vault: str = ''

    def check(self):
        if self.cancelled():
            raise Cancelled()

    @property
    def local_now(self) -> datetime:
        return self.now.astimezone()


@dataclass
class Result:
    text: str
    files: list = field(default_factory=list)
    status: str = 'ok'                              # ok | falhou | aguardando_confirmacao | recusado | cancelado
    offer: list = field(default_factory=list)       # uids offered for "escolher"
    focus: str = ''                                 # uid now meant by "essa atividade"


def local_text(moment: datetime) -> str:
    local = moment.astimezone()
    return f'{WEEKDAY[local.weekday()]}, {local:%d/%m} às {local:%H:%M}'


def _line(act: academic.Activity, with_state=True) -> str:
    due = act.due_text if act.due_at or act.due_text not in ('', 'não verificado') else 'prazo não verificado'
    parts = [f'{act.title} — {due}']
    if act.time_left:
        parts.append(act.time_left)
    if with_state:
        parts.append(act.situation_text if act.knowledge != 'nao_verificado' else 'entrega não verificada')
    if act.knowledge == 'desatualizado':
        parts.append('verificação com mais de 24 h')
    return ' • '.join(parts)


def _no_reading() -> Result:
    return Result('Ainda não tenho nenhuma leitura do Moodle. Abra a disciplina Modelagem UML (7653) no Chrome, '
                  'use "Sincronizar disciplina" no Campus AI Companion e clique em "Salvar no Campus AI". '
                  'Sem isso eu não sei quais são suas atividades e não vou inventar.', status='falhou')


def _header(snap: academic.Snapshot) -> str:
    text = f'Com base na última leitura do Companion ({snap.reading_local}, {snap.course}):'
    if snap.stale_reading:
        text += ' atenção, essa leitura tem mais de 24 h.'
    return text


def _unverified_note(acts) -> str:
    unknown = [a for a in acts if a.knowledge == 'nao_verificado']
    if not unknown:
        return ''
    return (f'{len(unknown)} tarefa(s)/questionário(s) ainda sem prazo e entrega verificados (isso não quer dizer que '
            'estejam em dia): ' + '; '.join(a.title for a in unknown[:6]) + ('…' if len(unknown) > 6 else '') + '. '
            'Para verificar, sincronize com o Companion 0.5.4 e salve.')


# --- academic questions ---------------------------------------------------------------------------------------------
def today(ctx: Context) -> Result:
    snap = academic.load(ctx.live_db, ctx.now)
    if not snap.available:
        return _no_reading()
    start, end = academic.local_day_bounds(ctx.now)
    acts = snap.activities
    late = [a for a in acts if a.situation == 'atrasada']
    due_today = [a for a in acts if a.situation in academic.ACTION_SITUATIONS and a.due_moment()
                 and start <= a.due_moment() < end and a not in late]
    week = [a for a in acts if a.situation in ('pendente', 'verificar_tentativa') and a.due_moment()
            and end <= a.due_moment() < end + timedelta(days=7)]
    open_no_due = [a for a in acts if a.situation == 'pendente' and not a.due_moment()]
    attempts = [a for a in acts if a.situation == 'verificar_tentativa' and a not in due_today and a not in week]
    lines = [_header(snap)]
    blocks = (('Atrasadas', late), ('Vencem hoje', due_today), ('Nos próximos 7 dias', week),
              ('Pendentes sem prazo definido', open_no_due), ('Tentativa de questionário em andamento', attempts))
    for title, group in blocks:
        if group:
            lines.append(f'\n{title}:')
            lines += [f'  {i}. {_line(a)}' for i, a in enumerate(group, 1)]
    actionable = [a for _t, g in blocks for a in g]
    if not actionable:
        confirmed = [a for a in acts if a.knowledge != 'nao_verificado']
        lines.append('\nNenhuma pendência comprovada para hoje.' if confirmed else
                     '\nNão consigo dizer o que você tem para hoje: nenhuma página de atividade foi verificada ainda.')
    else:
        lines.append(f'\nSugestão: comece por "{actionable[0].title}". Diga "prepare essa atividade" e eu monto o '
                     'material de trabalho.')
    note = _unverified_note(acts)
    if note:
        lines.append('\n' + note)
    waiting = sum(a.situation == 'aguardando_avaliacao' for a in acts)
    done = sum(a.situation == 'concluida' for a in acts)
    if waiting or done:
        lines.append(f'Aguardando avaliação: {waiting} • Concluídas: {done}.')
    lines.append(SCOPE_NOTE)
    return Result('\n'.join(lines), offer=[a.uid for a in actionable], focus=actionable[0].uid if actionable else '')


def next_deadlines(ctx: Context) -> Result:
    snap = academic.load(ctx.live_db, ctx.now)
    if not snap.available:
        return _no_reading()
    dated = sorted((a for a in snap.activities if a.due_moment() and a.due_moment() >= ctx.now
                    and a.situation not in ('concluida',)), key=lambda a: a.due_moment())
    lines = [_header(snap)]
    if dated:
        lines.append('\nPróximos prazos:')
        lines += [f'  {i}. {_line(a)}' for i, a in enumerate(dated[:10], 1)]
    else:
        lines.append('\nNenhum prazo futuro verificado.')
    note = _unverified_note(snap.activities)
    if note:
        lines.append('\n' + note)
    lines.append(SCOPE_NOTE)
    return Result('\n'.join(lines), offer=[a.uid for a in dated[:10]], focus=dated[0].uid if dated else '')


def not_delivered(ctx: Context) -> Result:
    snap = academic.load(ctx.live_db, ctx.now)
    if not snap.available:
        return _no_reading()
    open_ = [a for a in snap.activities if a.situation in academic.ACTION_SITUATIONS]
    lines = [_header(snap)]
    if open_:
        lines.append('\nNão entregues (comprovado pela página da atividade):')
        lines += [f'  {i}. {_line(a)}' for i, a in enumerate(open_, 1)]
    else:
        lines.append('\nNenhuma atividade não entregue foi comprovada.')
    note = _unverified_note(snap.activities)
    if note:
        lines.append('\n' + note)
    lines.append(SCOPE_NOTE)
    return Result('\n'.join(lines), offer=[a.uid for a in open_], focus=open_[0].uid if open_ else '')


def late(ctx: Context) -> Result:
    snap = academic.load(ctx.live_db, ctx.now)
    if not snap.available:
        return _no_reading()
    overdue = [a for a in snap.activities if a.situation == 'atrasada']
    lines = [_header(snap)]
    if overdue:
        lines.append(f'\nSim: {len(overdue)} atividade(s) atrasada(s) (prazo vencido sem entrega, segundo a página da atividade):')
        lines += [f'  {i}. {_line(a)}' for i, a in enumerate(overdue, 1)]
    elif any(a.knowledge != 'nao_verificado' for a in snap.activities):
        lines.append('\nNenhuma atividade atrasada entre as verificadas.')
    else:
        lines.append('\nNão sei dizer: nenhum prazo foi verificado ainda, então não dá para afirmar que nada está atrasado.')
    note = _unverified_note(snap.activities)
    if note:
        lines.append('\n' + note)
    lines.append(SCOPE_NOTE)
    return Result('\n'.join(lines), offer=[a.uid for a in overdue], focus=overdue[0].uid if overdue else '')


def overview(ctx: Context) -> Result:
    """What is pending and what is done, each with how it is known."""
    snap = academic.load(ctx.live_db, ctx.now)
    if not snap.available:
        return _no_reading()
    groups = [('Pendentes (comprovado)', [a for a in snap.activities if a.situation in academic.ACTION_SITUATIONS]),
              ('Enviadas, aguardando avaliação', [a for a in snap.activities if a.situation in ('aguardando_avaliacao', 'enviada')]),
              ('Concluídas (avaliadas ou tentativa finalizada)', [a for a in snap.activities if a.situation == 'concluida']),
              ('Sem informação de entrega (não verificadas)', [a for a in snap.activities if a.knowledge == 'nao_verificado'])]
    lines = [_header(snap)]
    for title, group in groups:
        lines.append(f'\n{title}: {len(group)}')
        lines += [f'  • {_line(a, with_state=title.startswith("Pend"))}' for a in group]
    lines.append(f'\nAlém disso: {snap.materials} material(is) e {snap.others} módulo(s) que não são tarefas (ex.: escolha de grupo).')
    if all(a.knowledge == 'nao_verificado' for a in snap.activities):
        lines.append('Nenhuma entrega foi verificada ainda: não dá para dizer o que está concluído. Sincronize com o '
                     'Companion 0.5.4 e salve para eu ler prazos e entregas.')
    lines.append(SCOPE_NOTE)
    pending = groups[0][1]
    return Result('\n'.join(lines), offer=[a.uid for a in pending], focus=pending[0].uid if pending else '')


def search_conversation(ctx: Context, about: str) -> Result:
    import re
    from .store import fold
    words = [w for w in re.findall(r'[a-z0-9]+', fold(about)) if len(w) > 2]
    about = ' '.join(about.strip(' ?!.').split())
    if not words:
        return Result('Sobre o que devo procurar nas conversas? Ex.: "o que eu disse sobre a AV2?".', status='falhou')
    past = ctx.store.messages(2000)[:-1]                       # not the question being asked now
    found = [m for m in past if m['role'] == 'user' and all(w in re.findall(r'[a-z0-9]+', fold(m['text'])) for w in words)]
    memories = ctx.store.memories(' '.join(words))
    if not found and not memories:
        return Result(f'Não encontrei nada sobre "{about}" nas conversas nem na memória.', status='falhou')
    lines = []
    if memories:
        lines.append('Na memória:')
        lines += [f'  nº {m.id} {m.text}' for m in memories[:5]]
    if found:
        lines.append('Você disse:')
        lines += [f'  {m["at"][:16].replace("T", " ")} UTC — {m["text"][:200]}' for m in found[-8:]]
    return Result('\n'.join(lines))


def delivered(ctx: Context) -> Result:
    snap = academic.load(ctx.live_db, ctx.now)
    if not snap.available:
        return _no_reading()
    sent = [a for a in snap.activities if a.situation in ('aguardando_avaliacao', 'enviada', 'concluida')]
    lines = [_header(snap)]
    if sent:
        lines.append('\nEnviadas ou concluídas:')
        lines += [f'  {i}. {_line(a)}' for i, a in enumerate(sent, 1)]
    else:
        lines.append('\nNenhuma entrega confirmada.')
    note = _unverified_note(snap.activities)
    if note:
        lines.append('\n' + note)
    return Result('\n'.join(lines), offer=[a.uid for a in sent])


# --- production -----------------------------------------------------------------------------------------------------
def _schedule(act: academic.Activity, now: datetime):
    """Work steps with dates counted back from the deadline (suggestions, not facts)."""
    due = act.due_moment()
    if act.kind == 'quiz':
        steps = [('Revisar o conteúdo cobrado e anotar dúvidas', 0.0), ('Resolver exercícios de fixação', 0.4),
                 ('Reservar um horário contínuo para responder (tempo e tentativas conferidos na página)', 0.8)]
    else:
        steps = [('Ler o enunciado completo e os critérios de avaliação no Moodle', 0.0),
                 ('Levantar o que é pedido e montar um esboço', 0.2), ('Desenvolver a primeira versão', 0.5),
                 ('Revisar, conferir formato e nome do arquivo', 0.8), ('Enviar no Moodle (você, manualmente)', 0.9)]
    if not due or due <= now:
        return [(step, '') for step, _f in steps], bool(due and due <= now)
    span = due - now
    return [(step, local_text(now + span * fraction) if fraction else 'hoje') for step, fraction in steps], False


def _analysis(act: academic.Activity, now: datetime) -> list:
    """What can be said from the verified facts only (inferences are labelled as such)."""
    if act.knowledge == 'nao_verificado':
        return ['Sem prazo e estado de entrega verificados, não é possível avaliar urgência nem risco desta atividade.']
    notes = []
    due = act.due_moment()
    if act.situation == 'atrasada':
        notes.append('O prazo de entrega já passou e não há envio registrado na página da atividade.')
    elif due:
        hours = (due - now).total_seconds() / 3600
        notes.append(f'Faltam cerca de {int(hours // 24)} dia(s) e {int(hours % 24)} h para o prazo.' if hours >= 24 else
                     f'Faltam menos de {max(1, int(hours) + 1)} h para o prazo: prioridade máxima.')
    if act.situation in ('aguardando_avaliacao', 'enviada', 'concluida'):
        notes.append('A atividade já consta como enviada ou concluída; este material serve só para revisão.')
    if act.knowledge == 'desatualizado':
        notes.append('A verificação tem mais de 24 h: confira no Moodle se algo mudou.')
    return notes or ['Nada a acrescentar além dos dados acima.']


def prepare(ctx: Context, act: academic.Activity, intro: str = '') -> Result:
    ctx.check()
    doc = documents.Document(f'Preparação — {act.title}')
    doc.paragraph(f'Gerado pelo Campus AI (Jarvis) em {local_text(ctx.now)}. Material de trabalho para você revisar: '
                  'nada foi enviado ou alterado no Moodle.')
    doc.heading('1. Informações fornecidas pelo professor')
    doc.paragraph('Enunciado, critérios de avaliação e formato de entrega: NÃO DISPONÍVEIS no Campus AI. O Companion '
                  'lê apenas a lista da seção, datas e estados — o Campus AI não lê o texto das atividades. '
                  'Nada nesta seção foi inventado; copie o enunciado do Moodle para a seção 6.')
    doc.heading('2. Dados verificados pelo Campus AI')
    doc.table(['Campo', 'Valor', 'Como sei'], [
        ['Atividade', act.title, 'lista da seção (Companion)'],
        ['Disciplina', f'{act.course} › {act.section}' if act.section else act.course, 'lista da seção (Companion)'],
        ['Tipo', act.kind_label, 'lista da seção (Companion)'],
        ['Prazo', act.due_text, KNOWLEDGE_TEXT[act.knowledge]],
        ['Tempo restante', act.time_left or '—', 'calculado a partir do prazo' if act.time_left else '—'],
        ['Situação', act.situation_text if act.knowledge != 'nao_verificado' else 'não verificada', KNOWLEDGE_TEXT[act.knowledge]],
        ['Estado da entrega', act.delivery, KNOWLEDGE_TEXT[act.knowledge]],
        ['Última verificação', act.verified or 'nunca', ''],
        ['Endereço no Moodle', act.url or '—', ''],
    ])
    if act.note:
        doc.paragraph(f'Observação: {act.note}')
    ctx.check()
    doc.heading('3. Análise do Campus AI (a partir dos dados acima)')
    doc.bullets(_analysis(act, ctx.now))
    unknown = ['O enunciado, os critérios de avaliação e o formato de entrega: o Campus AI não lê o texto das '
               'atividades (só datas e estados). Copie o enunciado para a seção 6.']
    if act.knowledge == 'nao_verificado':
        unknown.append('O prazo e o estado da entrega: a página desta atividade ainda não foi verificada pelo Companion 0.5.4.')
    if act.kind == 'quiz':
        unknown.append('Número de tentativas, tempo limite e método de avaliação (confira na página do questionário).')
    unknown.append('Referências bibliográficas: nenhuma foi fornecida; não indico fontes que não foram verificadas.')
    steps, late = _schedule(act, ctx.now)
    doc.heading('4. Instruções e plano de trabalho (sugestão do Campus AI)')
    if late:
        doc.paragraph('O prazo já passou. Confira no Moodle se ainda é possível enviar (data limite) e, se for o caso, '
                      'fale com o professor.')
    if act.due_moment() and not late:
        doc.paragraph(f'Distribuído até o prazo ({act.due_text}).')
    elif not act.due_moment():
        doc.paragraph('Sem prazo verificado: as etapas estão sem datas.')
    doc.table(['Etapa', 'Quando'], [[step, when or '—'] for step, when in steps])
    doc.heading('5. Checklist antes de enviar (sugestão)')
    doc.bullets(['Atendi a tudo o que o enunciado pede?', 'O arquivo está no formato pedido e abre corretamente?',
                 'Nome do arquivo e identificação (nome, turma) conferidos?', 'Referências e fontes citadas?',
                 'Enviei como "enviar para avaliação" (não só rascunho), se a tarefa exigir?'] if act.kind != 'quiz' else
                ['Conteúdo revisado?', 'Horário reservado sem interrupções?', 'Conexão estável?',
                 'Sei quantas tentativas tenho e até quando o questionário fica aberto?'])
    doc.heading('6. Conteúdo preparado (rascunho para você completar)')
    for part in ('Enunciado (cole aqui)', 'O que é pedido, em tópicos', 'Ideias e esboço', 'Desenvolvimento', 'Referências'):
        doc.heading(part, 3)
        doc.paragraph('…')
    doc.heading('7. Informações ausentes')
    doc.bullets(unknown)
    doc.heading('Avisos')
    doc.bullets(['Datas, estados e o link vêm do Companion; análise, plano e checklist são sugestões do Campus AI, não '
                 'informações do professor.',
                 'O Campus AI nunca envia, submete ou inicia tentativas por você.'])
    ctx.check()
    stem = f'{ctx.local_now:%Y-%m-%d}-preparacao-{documents.slug(act.title)}'
    files = documents.write(doc, ctx.output_dir / 'Atividades', stem)
    known = f'prazo {act.due_text}' if act.due_at else 'prazo não verificado'
    missing = len(unknown)
    return Result((intro + '\n\n' if intro else '') +
                  f'Pronto. Montei o material de trabalho para "{act.title}" ({known}). Ele separa: o que o professor '
                  'forneceu (o enunciado não está armazenado), os dados verificados com a origem de cada um, uma análise, '
                  f'um plano até o prazo, um checklist, um rascunho e {missing} informação(ões) ausente(s).',
                  files=files, focus=act.uid)


def most_urgent(snap: academic.Snapshot):
    """(activity, reason) — the action item with the earliest verified deadline (late ones first), or (None, why)."""
    actionable = [a for a in snap.activities if a.situation in academic.ACTION_SITUATIONS and a.due_moment()]
    if actionable:
        best = min(actionable, key=lambda a: (a.situation != 'atrasada', a.due_moment()))
        return best, ('está atrasada' if best.situation == 'atrasada' else f'é a que vence primeiro ({best.due_text})')
    if any(a.situation in academic.ACTION_SITUATIONS for a in snap.activities):
        return None, 'há pendências comprovadas, mas nenhuma com prazo verificado'
    if all(a.knowledge == 'nao_verificado' for a in snap.activities):
        return None, 'nenhum prazo foi verificado ainda'
    return None, 'não há pendência comprovada'


def week_plan(ctx: Context) -> Result:
    snap = academic.load(ctx.live_db, ctx.now)
    if not snap.available:
        return _no_reading()
    start, _end = academic.local_day_bounds(ctx.now)
    days = [start + timedelta(days=i) for i in range(7)]
    doc = documents.Document(f'Plano da semana — {local_text(ctx.now)[:-9]} a {days[-1].astimezone():%d/%m}')
    doc.paragraph(f'Gerado pelo Campus AI (Jarvis) com a leitura do Companion de {snap.reading_local}. {SCOPE_NOTE}')
    rows = []
    for day in days:
        nxt = day + timedelta(days=1)
        due = [a for a in snap.activities if a.due_moment() and day <= a.due_moment() < nxt
               and a.situation in academic.ACTION_SITUATIONS]
        rows.append([f'{WEEKDAY[day.astimezone().weekday()]} {day.astimezone():%d/%m}',
                     '; '.join(f'{a.title} (prazo {a.due_text[-5:]})' for a in due) or '—'])
    doc.heading('Prazos da semana')
    doc.table(['Dia', 'Vence'], rows)
    late = [a for a in snap.activities if a.situation == 'atrasada']
    open_ = [a for a in snap.activities if a.situation in ('pendente', 'verificar_tentativa')]
    doc.heading('Prioridades (sugestão)')
    order = late + open_
    doc.bullets([f'{i}. {_line(a)}' for i, a in enumerate(order, 1)] or ['Nenhuma pendência comprovada.'])
    unknown = [a for a in snap.activities if a.knowledge == 'nao_verificado']
    if unknown:
        doc.heading('Ainda não verificadas (podem ter prazo nesta semana)')
        doc.bullets([a.title for a in unknown])
    files = documents.write(doc, ctx.output_dir / 'Planos', f'{ctx.local_now:%Y-%m-%d}-plano-da-semana')
    summary = (f'Montei o plano da semana: {len(order)} pendência(s) comprovada(s), {len(late)} atrasada(s)'
               + (f' e {len(unknown)} atividade(s) ainda não verificada(s)' if unknown else '') + '.')
    return Result(summary, files=files, offer=[a.uid for a in order])


# --- integrations status ----------------------------------------------------------------------------------------------
def integrations(ctx: Context) -> Result:
    snap = academic.load(ctx.live_db, ctx.now)
    lines = ['O que está conectado ao Jarvis agora:',
             f'• Moodle (via Campus AI Companion): {"conectado — última leitura " + snap.reading_local if snap.available else "nenhuma leitura salva ainda"}.',
             '  Prazos e entregas: lidos na página de cada atividade pela extensão 0.5.4 (somente leitura; o Moodle '
             'registra a visualização da atividade).',
             f'• Obsidian: {"pasta configurada (" + ctx.obsidian_vault + ")" if ctx.obsidian_vault else "pasta do cofre não configurada"}; '
             'o Jarvis ainda não escreve notas por conta própria.',
             '• Gmail institucional: não conectado ao Jarvis. Falta: autorizar o acesso OAuth somente leitura com a '
             'conta da faculdade (Configurações) e a política da instituição permitir.',
             '• Google Calendar: não conectado. Falta: um cliente OAuth com escopo de calendário e sua autorização.',
             '• Modelo de linguagem (resumos, pesquisa, textos): não conectado. Falta: escolher um provedor (local, '
             'como Ollama, ou por API) e autorizar o envio de conteúdo a ele.',
             '• Voz: ainda não implementada (próxima etapa).']
    return Result('\n'.join(lines))


UNSUPPORTED = {
    'resum': 'resumir uma matéria exige um modelo de linguagem, que ainda não está conectado',
    'pesquis': 'pesquisar na internet exige uma ferramenta de busca, que ainda não está conectada',
    'busque': 'pesquisar na internet exige uma ferramenta de busca, que ainda não está conectada',
    'abra': 'abrir e analisar projetos ou pastas ainda não é uma ferramenta do Jarvis',
    'abrir': 'abrir e analisar projetos ou pastas ainda não é uma ferramenta do Jarvis',
    'envi': 'enviar e-mails ou atividades não é algo que eu faça por você; exigiria sua confirmação e uma integração que não existe',
    'submet': 'submeter atividades no Moodle não é algo que eu faça por você',
    'entregue': 'entregar atividades no Moodle não é algo que eu faça por você',
    'questionario': 'iniciar ou responder questionários não é algo que eu faça por você',
    'apresentac': 'apresentações ainda não são geradas (próxima etapa); hoje gero documentos Word e Markdown',
    'planilha': 'planilhas ainda não são geradas (próxima etapa); hoje gero documentos Word e Markdown',
    'pdf': 'PDF ainda não é gerado (próxima etapa); hoje gero documentos Word e Markdown',
}


def unsupported(text: str) -> Result:
    reason = next((why for key, why in UNSUPPORTED.items() if key in text), 'isso ainda não é uma ferramenta do Jarvis')
    return Result(f'Ainda não consigo fazer isso de verdade: {reason}. Não vou simular. ' + HELP_SHORT, status='recusado')


HELP_SHORT = ('Hoje eu consigo: dizer o que você tem para hoje, os próximos prazos, o que falta entregar e o que já foi '
              'enviado; preparar o material de trabalho de uma atividade (Word + Markdown); montar o plano da semana; '
              'criar lembretes; guardar, mostrar, corrigir e apagar memórias.')

HELP = '\n'.join([
    'Exemplos do que eu faço de verdade:',
    '• "O que tenho para fazer hoje?"  • "Quais atividades vencem primeiro?"  • "O que ainda não entreguei?"',
    '• "O que já entreguei?"  • "Prepare essa atividade" / "Prepare a atividade Tarefa em grupo"',
    '• "Organize minha semana"  • "Me avise amanhã às 18h sobre essa entrega"  • "Me avise um dia antes do prazo"',
    '• "Quais são meus lembretes?"  • "Cancele o lembrete 2"',
    '• "Lembre que eu prefiro estudar à noite"  • "O que você sabe sobre mim?"  • "Corrija a memória 3 para ..."',
    '• "Apague a memória 3" (peço confirmação)  • "O que está conectado?"  • "O que você fez?"',
    'O que eu não faço: enviar e-mails, entregar ou submeter atividades, iniciar questionários, compartilhar ou apagar '
    'arquivos. Resumos, pesquisa, PDF, planilhas, apresentações e voz ainda não estão disponíveis.',
])

"""Jarvis: from a sentence to a tool, with memory, short-term context, confirmation and an operation log.

``Jarvis.handle(text)`` is synchronous and safe to run in a worker thread; ``cancelled`` is polled by the tools.
Every tool call is logged in jarvis.db (operations). Context kept between messages:
* ``focus``   the activity meant by "essa atividade" (set by the last answer that pointed to one);
* ``offer``   the numbered list of the last answer, for "a segunda" / "2";
* ``pending`` an action waiting for "sim"/"não" (only destructive local actions: deleting a memory).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import academic, nlu, tools
from .store import JarvisStore, SecretRefused, looks_secret

URGENT = re.compile(r'\b(mais urgente|vence primeiro|vencem primeiro|que vence antes|mais proxim[ao]|prazo mais (curto|proximo)|'
                    r'primeira a vencer|vence mais cedo)\b')


@dataclass
class Reply:
    text: str
    intent: str
    files: list = field(default_factory=list)
    status: str = 'ok'
    source: str = 'regras'          # who understood the request: 'regras' | 'ia_local:<model>'
    note: str = ''                  # e.g. why the local model could not help


class Jarvis:
    def __init__(self, store: JarvisStore, *, live_db: Path, output_dir: Path, clock=lambda: datetime.now(timezone.utc),
                 obsidian_vault: str = '', router=None):
        self.store = store
        self.live_db = Path(live_db)
        self.output_dir = Path(output_dir)
        self.clock = clock
        self.obsidian_vault = obsidian_vault
        self.router = router                    # llm.IntentRouter or None: the rules work alone
        store.recover_interrupted()

    # --- entry point ----------------------------------------------------------------------------------------------
    def handle(self, text: str, cancelled=lambda: False) -> Reply:
        text = str(text or '').strip()
        if not text:
            return Reply('Diga ou digite o que você precisa. ' + tools.HELP_SHORT, 'vazio')
        self.store.add_message('user', text)
        intent = nlu.parse(text)
        source, note = 'regras', ''
        # The local model only helps when the rules did not understand, or matched a weak "not supported" word.
        # 'recusar_acao' (send, submit, start a quiz, pay, delete files) is final: the model is never asked.
        if intent.name in ('desconhecido', 'nao_suportado') and self.router is not None and not looks_secret(text):
            asked, source, note = self._ask_local_model(intent, cancelled)
            if asked.name not in ('desconhecido', 'nao_suportado') or intent.name == 'desconhecido' or note == 'cancelado':
                intent = asked
            elif source.startswith('ia_local'):
                source = 'regras'                               # the model agreed there was nothing to do: rules' answer
        ctx = tools.Context(self.store, self.live_db, self.output_dir, self.clock(), cancelled, self.obsidian_vault)
        pending = self.store.context('pending')
        if pending and intent.name not in ('confirmar', 'cancelar_pendente'):
            self.store.set_context('pending', None)            # a new request drops an unanswered confirmation
            pending = None
        op = self.store.start_operation(intent.name, {'texto': text, 'interpretado_por': source})
        try:
            if note == 'cancelado':
                raise tools.Cancelled()
            result = self._route(intent, ctx, pending)
        except tools.Cancelled:
            result = tools.Result('Execução interrompida a seu pedido. Nada foi concluído nesta operação.', status='cancelado')
        except Exception as exc:                                # never pretend: say it failed, keep running
            result = tools.Result(f'Não consegui concluir: erro interno ({exc.__class__.__name__}). Nada foi alterado '
                                  'fora da pasta de entregas.', status='falhou')
        if intent.name == 'desconhecido' and note and note != 'cancelado':
            result.text += f'\n(A IA local não pôde ajudar agora: {note}. As funções por regras continuam disponíveis.)'
        if result.offer:
            self.store.set_context('offer', result.offer)
        if result.focus:
            self.store.set_context('focus', result.focus)
        self.store.finish_operation(op, result.status, result.text[:300], result.files)
        reply = Reply(result.text, intent.name, [str(f) for f in result.files], result.status, source, note)
        self.store.add_message('jarvis', reply.text, intent=intent.name, files=reply.files)
        return reply

    def _ask_local_model(self, intent, cancelled):
        """The rules did not understand: the local model picks one allowed intent (validated in llm.validate)."""
        from . import llm
        try:
            routed = self.router.route(intent.original, cancelled)
        except llm.Cancelled:
            return intent, 'regras', 'cancelado'
        except llm.LocalModelError as exc:
            return intent, 'regras', {'ia_local_indisponivel': 'IA local desligada', 'modelo_ausente': 'modelo não instalado',
                                      'tempo_esgotado': 'tempo esgotado'}.get(exc.code, exc.code)
        except Exception as exc:
            return intent, 'regras', exc.__class__.__name__
        if routed is None:
            return intent, f'ia_local:{self.router.model}', ''
        return (nlu.Intent(routed.name, intent.text, intent.original, dict(routed.slots)),
                f'ia_local:{self.router.model}', '')

    # --- routing --------------------------------------------------------------------------------------------------
    def _route(self, intent: nlu.Intent, ctx: tools.Context, pending):
        name = intent.name
        if name == 'confirmar':
            return self._confirm(ctx, pending)
        if name == 'cancelar_pendente':
            if pending:
                self.store.set_context('pending', None)
                return tools.Result('Certo, não fiz nada.')
            return tools.Result('Não há nada aguardando confirmação.')
        if name == 'escolher':
            return self._choose(ctx, intent.slots.get('indice', 0))
        simple = {'hoje': tools.today, 'proximos_prazos': tools.next_deadlines, 'nao_entregues': tools.not_delivered,
                  'pendencias': tools.not_delivered, 'atrasadas': tools.late, 'panorama': tools.overview,
                  'entregues': tools.delivered, 'planejar_semana': tools.week_plan, 'integracoes': tools.integrations}
        if name in simple:
            return simple[name](ctx)
        if name == 'buscar_conversa':
            return tools.search_conversation(ctx, intent.slots.get('sobre', ''))
        if name == 'preparar_atividade':
            return self._prepare(ctx, intent)
        if name == 'lembrete_criar':
            return self._remind(ctx, intent)
        if name == 'lembrete_listar':
            return self._list_reminders()
        if name == 'lembrete_cancelar':
            done = self.store.cancel_reminder(int(intent.slots['id']))
            return tools.Result(f'Lembrete {intent.slots["id"]} cancelado.' if done else
                                f'Não encontrei um lembrete pendente com o número {intent.slots["id"]}.',
                                status='ok' if done else 'falhou')
        if name.startswith('memoria_'):
            return self._memory(ctx, intent)
        if name == 'historico':
            return self._history()
        if name == 'ajuda':
            return tools.Result(tools.HELP)
        if name in ('nao_suportado', 'recusar_acao'):
            return tools.unsupported(intent.text)
        return tools.Result('Não entendi esse pedido e prefiro não adivinhar. ' + tools.HELP_SHORT + ' Diga "ajuda" para '
                            'ver exemplos.', status='recusado')

    def _activities(self, ctx):
        return academic.load(ctx.live_db, ctx.now)

    def _by_uid(self, snap, uid):
        return next((a for a in snap.activities if a.uid == uid), None)

    def _resolve(self, ctx, intent):
        """(activity, None) or (None, Result asking which one)."""
        snap = self._activities(ctx)
        if not snap.available:
            return None, tools._no_reading()
        matches = academic.find(snap, intent.original)
        if len(matches) == 1:
            return matches[0], None
        focus = self._by_uid(snap, self.store.context('focus', ''))
        if not matches and focus is not None and (nlu.refers_back(intent.text) or len(intent.text.split()) <= 4):
            return focus, None
        options = matches or [a for a in snap.activities if a.situation in academic.ACTION_SITUATIONS] or list(snap.activities)
        if not options:
            return None, tools.Result('Não encontrei tarefas ou questionários na última leitura.', status='falhou')
        self.store.set_context('choice', {'purpose': 'preparar'})
        lines = ['Qual atividade? Responda com o número:']
        lines += [f'  {i}. {tools._line(a)}' for i, a in enumerate(options[:9], 1)]
        return None, tools.Result('\n'.join(lines), offer=[a.uid for a in options[:9]], status='aguardando_confirmacao')

    def _prepare(self, ctx, intent):
        if intent.slots.get('alvo') == 'mais_urgente' or URGENT.search(intent.text):
            return self._prepare_most_urgent(ctx)
        if intent.slots.get('referencia'):                     # the model gave the student's own words for it
            intent = nlu.Intent(intent.name, nlu.fold(intent.slots['referencia']), intent.slots['referencia'], intent.slots)
        act, ask = self._resolve(ctx, intent)
        return ask if act is None else tools.prepare(ctx, act)

    def _prepare_most_urgent(self, ctx):
        """Deterministic: the earliest verified deadline among the pending ones (late ones first). Never a guess."""
        snap = self._activities(ctx)
        if not snap.available:
            return tools._no_reading()
        act, reason = tools.most_urgent(snap)
        nxt = sorted((a for a in snap.activities if a.due_moment() and a.situation in academic.ACTION_SITUATIONS),
                     key=lambda a: a.due_moment())[:3]
        if act is None:
            options = [a for a in snap.activities if a.situation in academic.ACTION_SITUATIONS] or list(snap.activities)
            self.store.set_context('choice', {'purpose': 'preparar'})
            lines = [f'Não consigo identificar a atividade mais urgente: {reason}. Não vou escolher no chute.']
            if options:
                lines.append('Se quiser, escolha uma pelo número e eu preparo o material:')
                lines += [f'  {i}. {tools._line(a)}' for i, a in enumerate(options[:9], 1)]
            lines.append(tools._unverified_note(snap.activities))
            return tools.Result('\n'.join(line for line in lines if line), offer=[a.uid for a in options[:9]],
                                status='aguardando_confirmacao')
        intro = 'Próximas atividades com prazo verificado:\n' + '\n'.join(f'  {i}. {tools._line(a)}' for i, a in
                                                                          enumerate(nxt, 1))
        intro += f'\nA mais urgente é "{act.title}": {reason}.'
        return tools.prepare(ctx, act, intro=intro)

    def _choose(self, ctx, index):
        offer = self.store.context('offer') or []
        if not offer:
            return tools.Result('Não há uma lista para escolher agora. Pergunte, por exemplo, "o que tenho para hoje?".',
                                status='falhou')
        if index == -1:
            index = len(offer)
        if not 1 <= index <= len(offer):
            return tools.Result(f'Escolha um número de 1 a {len(offer)}.', status='falhou')
        snap = self._activities(ctx)
        act = self._by_uid(snap, offer[index - 1])
        if act is None:
            return tools.Result('Essa atividade não está mais na última leitura.', status='falhou')
        self.store.set_context('focus', act.uid)
        choice = self.store.context('choice') or {}
        self.store.set_context('choice', None)
        if choice.get('purpose') == 'lembrete':
            return self._create_reminder(ctx, act, choice.get('texto', ''))
        if choice.get('purpose') == 'preparar':
            return tools.prepare(ctx, act)
        return tools.Result(f'Certo: "{act.title}" — {tools._line(act)}. Diga "prepare essa atividade" ou '
                            '"me avise um dia antes do prazo".', focus=act.uid)

    # --- reminders ------------------------------------------------------------------------------------------------
    def _remind(self, ctx, intent):
        snap = self._activities(ctx)
        act = None
        if snap.available:
            matches = academic.find(snap, intent.original)
            act = matches[0] if len(matches) == 1 else None
            if act is None and nlu.refers_back(intent.text):
                act = self._by_uid(snap, self.store.context('focus', ''))
        return self._create_reminder(ctx, act, intent.original, intent.text)

    def _create_reminder(self, ctx, act, original, folded=None):
        folded = folded if folded is not None else nlu.fold(original)
        due = act.due_moment() if act is not None else None
        moment = nlu.parse_when(folded, ctx.local_now, due)
        if moment is None:
            hint = (' Para uma atividade sem prazo verificado não consigo contar "antes do prazo".'
                    if act is not None and due is None and 'antes' in folded else '')
            return tools.Result('Quando devo avisar? Por exemplo: "amanhã às 18h", "daqui a 2 horas", "sexta às 9h" '
                                'ou "um dia antes do prazo".' + hint, status='falhou')
        if act is not None:
            text = f'{act.title} — prazo {act.due_text}' if act.due_at else f'{act.title} (prazo não verificado)'
        else:
            text = original
        reminder = self.store.add_reminder(moment, text, act.uid if act else '')
        return tools.Result(f'Combinado: vou avisar {tools.local_text(moment)} (lembrete nº {reminder.id}): {text}. '
                            'O aviso aparece na bandeja do Windows enquanto o Campus AI estiver aberto ou em segundo plano.',
                            focus=act.uid if act else '')

    def _list_reminders(self):
        items = self.store.pending_reminders()
        if not items:
            return tools.Result('Nenhum lembrete pendente.')
        lines = ['Lembretes pendentes:']
        lines += [f'  nº {r.id} — {tools.local_text(datetime.fromisoformat(r.due_at))}: {r.text}' for r in items]
        return tools.Result('\n'.join(lines))

    # --- memory ---------------------------------------------------------------------------------------------------
    def _memory(self, ctx, intent):
        name = intent.name
        if name == 'memoria_adicionar':
            try:
                memory = self.store.remember(intent.slots.get('texto', ''), kind=_kind_of(intent.text))
            except SecretRefused:
                return tools.Result('Não guardo isso: parece uma senha, token ou outro dado sigiloso. Senhas e '
                                    'credenciais nunca ficam na memória do Campus AI.', status='recusado')
            except ValueError:
                return tools.Result('O que devo lembrar? Ex.: "lembre que eu prefiro estudar à noite".', status='falhou')
            return tools.Result(f'Guardado na memória (nº {memory.id}, {memory.kind}): "{memory.text}".')
        if name == 'memoria_listar':
            about = intent.slots.get('sobre', '').strip(' ?.!')
            about = '' if about in ('mim', 'me', 'eu', 'voce', 'mim mesmo') else about    # "sobre mim" = everything
            items = self.store.memories(about)
            if not items:
                return tools.Result('Não tenho nada guardado' + (' sobre isso.' if about else
                                    '. Diga "lembre que ..." para eu guardar algo.'))
            lines = ['O que eu sei (só o que você me disse):']
            lines += [f'  nº {m.id} [{m.kind}] {m.text}' for m in items]
            lines.append('Para corrigir: "corrija a memória 2 para ...". Para apagar: "apague a memória 2".')
            return tools.Result('\n'.join(lines))
        if name == 'memoria_corrigir':
            try:
                memory = self.store.correct(int(intent.slots['id']), intent.slots['texto'])
            except SecretRefused:
                return tools.Result('Não guardo isso: parece um dado sigiloso.', status='recusado')
            return (tools.Result(f'Memória nº {memory.id} corrigida: "{memory.text}".') if memory else
                    tools.Result(f'Não encontrei a memória nº {intent.slots["id"]}.', status='falhou'))
        memory = self.store.memory(int(intent.slots['id']))
        if memory is None:
            return tools.Result(f'Não encontrei a memória nº {intent.slots["id"]}.', status='falhou')
        self.store.set_context('pending', {'action': 'apagar_memoria', 'id': memory.id})
        return tools.Result(f'Confirma apagar a memória nº {memory.id}: "{memory.text}"? Isso não pode ser desfeito. '
                            'Responda "sim" ou "não".', status='aguardando_confirmacao')

    def _confirm(self, ctx, pending):
        if not pending:
            return tools.Result('Não há nada aguardando confirmação.')
        self.store.set_context('pending', None)
        if pending.get('action') == 'apagar_memoria':
            done = self.store.forget(int(pending['id']))
            return tools.Result(f'Memória nº {pending["id"]} apagada.' if done else 'Essa memória já não existia.',
                                status='ok' if done else 'falhou')
        return tools.Result('Ação desconhecida: nada foi feito.', status='falhou')

    def _history(self):
        ops = [o for o in self.store.operations(15) if o['tool'] not in ('historico',)]
        if not ops:
            return tools.Result('Ainda não executei nada.')
        lines = ['Últimas operações:']
        for o in ops[:10]:
            files = f' → {len(o["files"])} arquivo(s)' if o['files'] else ''
            lines.append(f'  {o["started_at"][:16].replace("T", " ")} UTC • {o["tool"]} • {o["status"]}{files}')
        return tools.Result('\n'.join(lines))


def _kind_of(text: str) -> str:
    if any(w in text for w in ('prefiro', 'gosto', 'nao gosto', 'costumo', 'melhor horario')):
        return 'preferencia'
    if any(w in text for w in ('projeto', 'repositorio', 'app ')):
        return 'projeto'
    if any(w in text for w in ('meta', 'objetivo', 'quero ', 'pretendo')):
        return 'objetivo'
    if any(w in text for w in ('disciplina', 'materia', 'professor', 'aula')):
        return 'disciplina'
    if any(w in text for w in ('decidi', 'decisao', 'combinamos')):
        return 'decisao'
    return 'nota'

"""Understanding what the student said (Portuguese), without any external model.

Rule-based on purpose: every intent maps to a real tool, nothing is "answered" without one. The text is folded
(accents/case), the wake word "Jarvis" is ignored, and slots are extracted (activity reference, time, numbers).
Anything not recognised is ``desconhecido``: the assistant then says so and shows what it can do — it never makes
something up. A generative model can later be plugged in as a fallback interpreter, with consent (intelligence.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .store import fold

ORDINALS = {'primeira': 1, 'primeiro': 1, 'segunda': 2, 'segundo': 2, 'terceira': 3, 'terceiro': 3, 'quarta': 4,
            'quarto': 4, 'quinta': 5, 'quinto': 5, 'ultima': -1, 'ultimo': -1}
NUMBERS = {'um': 1, 'uma': 1, 'dois': 2, 'duas': 2, 'tres': 3, 'quatro': 4, 'cinco': 5, 'seis': 6, 'sete': 7,
           'oito': 8, 'nove': 9, 'dez': 10, 'meia': 30}
WEEKDAYS = {'segunda': 0, 'terca': 1, 'quarta': 2, 'quinta': 3, 'sexta': 4, 'sabado': 5, 'domingo': 6}
WAKE = re.compile(r'^\s*(ei|ok|oi|ola|hey)?\s*,?\s*jarvis\s*[,:!.-]*\s*')
REFERS_BACK = re.compile(r'\b(essa|esta|dessa|desta|nessa|ela|aquela|daquela|isso|ela mesma)\b')


@dataclass
class Intent:
    name: str
    text: str                       # folded text without the wake word
    original: str
    slots: dict = field(default_factory=dict)


# (name, pattern) in priority order. The first match wins.
_RULES = [
    ('confirmar', r'^(sim|confirmo|confirmar|confirma|pode( apagar| excluir| remover| cancelar)?|ok,? pode)\b'),
    ('cancelar_pendente', r'^(nao|cancela|cancelar|deixa|deixa pra la|nao precisa)\s*[.!]?$'),
    ('escolher', r'^(a |o |opcao |numero |item )?(\d{1,2}|primeir[ao]|segund[ao]|terceir[ao]|quart[ao]|quint[ao]|ultim[ao])\s*[.!]?$'),
    ('ajuda', r'\b(ajuda|o que voce (sabe fazer|faz|consegue)|quais (sao os )?comandos|como (voce )?funciona)\b'),
    ('memoria_adicionar', r'^(lembre(-se)? (de )?que|lembra que|anot[ae] (ai )?que|guard[ae] (ai )?que|memorize que|'
                          r'grave que|saiba que|registre que)\s+(?P<texto>.+)'),
    ('memoria_corrigir', r'\b(corrij[ae]|altere|atualize|mude)\s+(a )?(memoria|anotacao|lembranca)\s*#?\s*(?P<id>\d+)\s+'
                         r'(para|por|:)\s*(?P<texto>.+)'),
    ('memoria_apagar', r'\b(esqueca|apague|remova|exclua|delete)\b.*?(memoria|anotacao|lembranca)\s*#?\s*(?P<id>\d+)'),
    ('memoria_listar', r'\b(o que voce (sabe|lembra|guardou)|minhas? (memorias?|anotacoes)|suas anotacoes|'
                       r'o que (esta|ta) na (sua )?memoria)\b(?: sobre (?P<sobre>.+))?'),
    ('buscar_conversa', r'\b(o que (eu )?(te )?(disse|falei)|procur[ae]r? (na|nas|em) (nossa |nossas )?conversas?|'
                        r'ja conversamos|busque (na|nas) conversas?)\b(?:.*?\bsobre (?P<sobre>.+))?'),
    ('lembrete_cancelar', r'\b(cancel[ae]r?|apague|remova)\s+(o )?lembrete\s*#?\s*(?P<id>\d+)'),
    ('lembrete_listar', r'\b(quais|meus|liste|listar|mostre)\s+(os )?(meus )?lembretes\b'),
    ('lembrete_criar', r'\b(me avis[ae]|me lembr[ae]|lembre-me|me lembra|cri[ae]r? (um )?lembrete|lembrete)\b'),
    ('historico', r'\b(o que voce fez|historico|ultimas (acoes|operacoes)|operacoes recentes)\b'),
    # Overview of pending vs done (before the refusals below: "resumo geral" is an overview, not "resuma a matéria").
    ('panorama', r'\b(o que (esta|ta|estiver) pendente e o que|pendentes? e (o que|as que) (ja )?(foi|foram|esta|estao)? ?'
                 r'conclu|conclu\w* e (o que )?(esta|ta)? ?pendente|situacao geral|panorama|resumo geral|como (eu )?estou)\b'),
    # Before every other request: actions this assistant NEVER takes. Final: the local model cannot override it.
    # (After memory and reminders, so "lembre que preciso enviar..." / "me lembre de enviar..." still work.)
    ('recusar_acao', r'\b(envie|mande|submet[ae]r?|entregue (a|o|as|os|minha|meu|essa|esta|isso)|'
                     r'inici[ae]r? (o |a )?(questionario|tentativa)|responda (o |a )?(questionario|prova)|'
                     r'(enviar|mandar) (um |uma |o |a )?(e-?mails?|mensagem|atividade|tarefa|trabalho)|'
                     r'pague|compre|apague (o |os |meus? )?arquivos?)\b'),
    # Abilities it does not have yet. Not final: with the local model available, it may read the sentence again
    # (e.g. "esqueci de mandar algo?" is a question about pending work, not a request to send).
    ('nao_suportado', r'\b(enviar|mandar|pesquis[ae]r?|busque na internet|resum[aoi]r?|abra|abrir|apresentac\w*|'
                      r'planilhas?|pdf)\b'),
    ('preparar_atividade', r'\b(prepar[ae]r?|me ajud[ae] (a fazer|com)|ajude-me com|mont[ae]r? (um |o )?(material|roteiro)|'
                           r'organiz[ae]r? (a |minha |essa )atividade)\b'),
    ('planejar_semana', r'\b(organiz[ae]r?|planej[ae]r?|plano|monte)\b.*\b(semana|estudos)\b|\bplano de estudos?\b'),
    ('atrasadas', r'\b(atrasad[ao]s?|em atraso|vencid[ao]s?|passou do prazo|passaram do prazo|ja venceu|ja venceram)\b'),
    ('nao_entregues', r'\b(nao (entreguei|enviei|fiz)|ainda (nao )?(entreguei|enviei)|nao entregues?|nao enviad[ao]s?)\b'),
    ('entregues', r'\b(ja (entreguei|enviei)|enviad[ao]s|entregues|(foi|foram|ja) (entregue|enviad[ao])s?|'
                  r'aguardando (avaliacao|correcao|nota)|conclu[ii]d[ao]s|ja conclui)\b'),
    ('proximos_prazos', r'\b(vence(m)?( primeiro)?|proxim[oa]s? (prazos?|entregas?|atividades?)|quais (sao os )?prazos|'
                        r'o que vence|quando vence|prazos?)\b'),
    ('hoje', r'\b(hoje|agenda do dia|meu dia)\b'),
    ('pendencias', r'\b(o que (eu )?(tenho|preciso|devo) (pra |para |de )?(fazer|entregar)|minhas atividades|resolver minhas|'
                   r'o que falta|pendentes|pendencias|falta(m)? (entregar|fazer)|tenho algo|devendo)\b'),
    ('integracoes', r'\b(integrac(ao|oes)|gmail|e-?mails?|calendario|google calendar|agenda do google|obsidian|'
                    r'o que (esta|ta) conectado|status)\b'),
]
_COMPILED = [(name, re.compile(pattern)) for name, pattern in _RULES]


def _fold_with_map(original: str):
    """Folded text plus, for each folded character, the index of the original character it came from."""
    out, where = [], []
    for i, ch in enumerate(original):
        for piece in fold(ch):
            out.append(piece)
            where.append(i)
    return ''.join(out), where


def parse(text: str) -> Intent:
    original = ' '.join(str(text or '').split())
    full, where = _fold_with_map(original)
    wake = WAKE.match(full)
    offset = wake.end() if wake else 0
    folded = full[offset:]
    for name, rx in _COMPILED:
        match = rx.search(folded)
        if match:
            slots = {k: v for k, v in match.groupdict().items() if v}
            if name == 'memoria_adicionar' and match.start('texto') >= 0:    # keep the student's own wording
                slots['texto'] = original[where[offset + match.start('texto')]:].strip()
            if name == 'escolher':
                slots['indice'] = _index(match.group(2))
            return Intent(name, folded, original, slots)
    return Intent('desconhecido', folded, original)


def _index(token: str) -> int:
    if token.isdigit():
        return int(token)
    for word, value in ORDINALS.items():
        if token.startswith(word[:-1]):
            return value
    return 0


def refers_back(text: str) -> bool:
    return bool(REFERS_BACK.search(fold(text)))


# --- time expressions for reminders --------------------------------------------------------------------------------
_TIME = r'(?:as|a|ao|para as|pelas)?\s*(?P<h>\d{1,2})(?:\s*(?:h|:|horas?)\s*(?P<m>\d{2})?)?\s*(?P<mer>da manha|da tarde|da noite)?'


def _clock(match, default=(9, 0)):
    if not match or match.group('h') is None:
        return default
    hour, minute = int(match.group('h')), int(match.group('m') or 0)
    mer = match.group('mer')
    if mer in ('da tarde', 'da noite') and hour < 12:
        hour += 12
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def parse_when(text: str, now: datetime, due: datetime | None = None):
    """A future local datetime from Portuguese, or None. ``now`` must be aware (local time zone)."""
    t = fold(text)
    # "daqui a 2 horas" / "em 30 minutos" / "em meia hora"
    m = re.search(r'\b(?:daqui a|daqui|em|dentro de)\s+(?P<n>\d+|' + '|'.join(NUMBERS) + r')\s*(?P<u>minutos?|min|horas?|h|dias?)\b', t)
    if m:
        n = int(m.group('n')) if m.group('n').isdigit() else NUMBERS[m.group('n')]
        unit = m.group('u')
        delta = timedelta(minutes=n) if unit.startswith('min') else timedelta(days=n) if unit.startswith('dia') else timedelta(hours=n)
        return now + delta
    if re.search(r'\b(?:em|daqui a)\s+meia hora\b', t):
        return now + timedelta(minutes=30)
    # "um dia antes do prazo" / "2 horas antes da entrega"
    m = re.search(r'\b(?P<n>\d+|' + '|'.join(NUMBERS) + r')\s*(?P<u>horas?|h|dias?)\s+antes\b', t)
    if m and due is not None:
        n = int(m.group('n')) if m.group('n').isdigit() else NUMBERS[m.group('n')]
        moment = due - (timedelta(days=n) if m.group('u').startswith('dia') else timedelta(hours=n))
        return moment if moment > now else None
    if re.search(r'\bno dia (do prazo|da entrega)\b', t) and due is not None:
        moment = due.astimezone(now.tzinfo).replace(hour=9, minute=0, second=0, microsecond=0)
        return moment if moment > now else None
    clock_match = re.search(r'\b' + _TIME + r'(?=\s|$|[.,!?])', re.sub(r'\bdia \d{1,2}\b', '', t))
    explicit_clock = bool(clock_match and re.search(r'\d{1,2}\s*(h|:|horas?)|\b(as|pelas|para as)\s+\d', t))
    clock = _clock(clock_match if explicit_clock else None)
    if clock is None:
        return None
    base = None
    if re.search(r'\bdepois de amanha\b', t):
        base = now + timedelta(days=2)
    elif re.search(r'\bamanha\b', t):
        base = now + timedelta(days=1)
    elif re.search(r'\bhoje\b', t):
        base = now
    else:
        m = re.search(r'\bdia (?P<d>\d{1,2})\b', t)
        if m:
            day = int(m.group('d'))
            year, month = now.year, now.month
            for _ in range(2):
                try:
                    candidate = now.replace(year=year, month=month, day=day, hour=clock[0], minute=clock[1], second=0, microsecond=0)
                except ValueError:
                    candidate = None
                if candidate and candidate > now:
                    return candidate
                month, year = (1, year + 1) if month == 12 else (month + 1, year)
            return None
        for name, weekday in WEEKDAYS.items():
            if re.search(rf'\b(na |no |nesta |neste |proxima |proximo )?{name}(-feira)?\b', t):
                ahead = (weekday - now.weekday()) % 7 or 7
                base = now + timedelta(days=ahead)
                break
    if base is None:
        if not explicit_clock:
            return None
        base = now                                                     # "às 18h": today, or tomorrow if passed
        candidate = base.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
        return candidate if candidate > now else candidate + timedelta(days=1)
    candidate = base.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
    return candidate if candidate > now else None

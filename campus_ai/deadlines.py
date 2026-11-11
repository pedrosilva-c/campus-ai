"""Situation of an activity from what its own Moodle page said (Companion v0.5.4). Pure: no I/O.

Mirror of ``companion/src/deadlines.js``; both are checked against ``tests/fixtures/companion/situations.json``.
Only observed facts count: a page that was not read, failed or was not recognised is ``nao_verificado`` — never
"no deadline" and never "nothing pending".

Dates are the wall time Moodle shows the student, interpreted in America/Sao_Paulo. Brazil has had no daylight
saving time since 2019, so the fixed offset UTC-03:00 is used (this Windows Python has no tz database, and
installing one is not needed for this rule).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

TIMEZONE = 'America/Sao_Paulo'
SAO_PAULO = timezone(timedelta(hours=-3), TIMEZONE)
DETAIL_KINDS = ('assign', 'quiz')
# Also the urgency order of the main table (most urgent first).
SITUATIONS = ('atrasada', 'pendente', 'verificar_tentativa', 'nao_verificado', 'aguardando_avaliacao', 'enviada',
              'concluida', 'nao_se_aplica')
SITUATION_TEXT = {
    'atrasada': 'Atrasada', 'pendente': 'Pendente', 'verificar_tentativa': 'Tentativa em andamento — verificar',
    'nao_verificado': 'Não verificado', 'aguardando_avaliacao': 'Enviada — aguardando avaliação', 'enviada': 'Enviada',
    'concluida': 'Concluída', 'nao_se_aplica': '—',
}
# Situations that are an action the student still has to take, proven by the page.
PENDING = frozenset(('atrasada', 'pendente'))
SOON = timedelta(hours=72)
_WALL = re.compile(r'\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?')


def main_kind(kind: str) -> str:
    """The main deadline: due date of an assignment, closing date of a quiz."""
    return 'fechamento' if kind == 'quiz' else 'entrega'


def wall_to_utc(at: str) -> datetime | None:
    """'YYYY-MM-DD[THH:MM]' in America/Sao_Paulo -> aware UTC datetime. A date without a time ends at 23:59."""
    if not isinstance(at, str) or not _WALL.fullmatch(at):
        return None
    try:
        local = datetime.fromisoformat(at if 'T' in at else at + 'T23:59')
    except ValueError:
        return None
    return local.replace(tzinfo=SAO_PAULO).astimezone(timezone.utc)


def situation(kind: str, detail: dict | None, deadlines, now: datetime) -> str:
    """``detail``/``deadlines`` as plain dicts (snapshot JSON or database row)."""
    if kind not in DETAIL_KINDS:
        return 'nao_se_aplica'
    if not detail or detail.get('result') != 'ok':
        return 'nao_verificado'
    main = next((d for d in deadlines or () if d.get('kind') == main_kind(kind) and d.get('at')), None)
    moment = wall_to_utc(main['at']) if main else None
    expired = bool(moment and moment < now)
    if kind == 'assign':
        if detail.get('grading_state') == 'avaliado':
            return 'concluida'
        if detail.get('submission_state') == 'enviado':
            return 'aguardando_avaliacao' if detail.get('grading_state') == 'nao_avaliado' else 'enviada'
        if detail.get('submission_state') in ('sem_envio', 'rascunho', 'reaberto'):
            return 'atrasada' if expired else 'pendente'
        return 'nao_verificado'
    attempt = detail.get('attempt_state')
    if attempt == 'em_andamento':
        return 'atrasada' if expired else 'verificar_tentativa'
    if attempt == 'finalizada':
        return 'concluida'
    if attempt == 'nenhuma':
        return 'atrasada' if expired else 'pendente'
    return 'nao_verificado'


def time_left(at: str, now: datetime) -> str:
    """'faltam 2 dias e 3 h' / 'venceu há 5 h' / '' (no readable date)."""
    moment = wall_to_utc(at)
    if moment is None:
        return ''
    delta = moment - now
    past = delta.total_seconds() < 0
    seconds = abs(int(delta.total_seconds()))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        text = f'{days} dia(s)' + (f' e {hours} h' if hours else '')
    elif hours:
        text = f'{hours} h' + (f' e {minutes} min' if minutes else '')
    else:
        text = f'{minutes} min'
    return f'venceu há {text}' if past else f'faltam {text}'


def due_soon(at: str, now: datetime) -> bool:
    moment = wall_to_utc(at)
    return bool(moment and now <= moment <= now + SOON)


def wall_text(at: str) -> str:
    """'2098-12-31T23:59' -> '31/12/2098 23:59'."""
    m = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?', at or '')
    if not m:
        return ''
    return f'{m[3]}/{m[2]}/{m[1]}' + (f' {m[4]}:{m[5]}' if m[4] else '')

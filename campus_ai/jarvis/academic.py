"""What the assistant knows about the student's activities: ONLY what the Campus AI Companion saved in live.db.

Read-only (companion_view opens the database with mode=ro). Every statement is tagged with how it is known:
* ``confirmado``      the activity's own Moodle page was read (deadline / delivery state), verification < 24 h;
* ``desatualizado``   it was read, but more than 24 h ago;
* ``nao_verificado``  the module is known (listed in the section) but its page was never read, or the read failed.
Nothing is inferred from absence: "não verificado" is never "no deadline" and never "nothing to do".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import deadlines as dl
from ..companion_view import load_view
from .store import fold

ACTION_SITUATIONS = ('atrasada', 'pendente', 'verificar_tentativa')


@dataclass(frozen=True)
class Activity:
    uid: str
    title: str
    kind: str
    kind_label: str
    course: str
    section: str
    situation: str
    due_at: str            # wall time America/Sao_Paulo ('' = none read)
    due_text: str
    time_left: str
    delivery: str
    verified: str          # local time of the last successful verification ('' = never)
    knowledge: str         # 'confirmado' | 'desatualizado' | 'nao_verificado'
    url: str
    note: str

    @property
    def situation_text(self) -> str:
        return dl.SITUATION_TEXT.get(self.situation, self.situation)

    def due_moment(self):
        return dl.wall_to_utc(self.due_at) if self.due_at else None


@dataclass(frozen=True)
class Snapshot:
    available: bool        # a Companion reading exists
    reading_local: str
    course: str
    activities: tuple      # assignments/quizzes (the ones that can have deadlines)
    materials: int
    others: int            # group choice, attendance... (never "pending work")
    stale_reading: bool


def load(db_path: Path, now: datetime | None = None) -> Snapshot:
    now = now or datetime.now(timezone.utc)
    try:
        view = load_view(db_path, now=now)
    except Exception:                         # locked or damaged: say so instead of guessing
        view = None
    if view is None or not view.has_reading:
        return Snapshot(False, '', '', (), 0, 0, False)
    acts, materials, others = [], 0, 0
    for row in view.rows:
        if not row.present:
            continue
        if row.category == 'material':
            materials += 1
            continue
        if row.kind not in dl.DETAIL_KINDS:
            others += 1
            continue
        knowledge = ('confirmado' if row.verified_local and row.fresh else
                     'desatualizado' if row.verified_local else 'nao_verificado')
        acts.append(Activity(row.uid, row.title, row.kind, row.kind_label, row.course_name, row.section_name,
                             row.situation, row.due_at, row.due_text or 'não verificado', row.time_left,
                             row.delivery_text or 'não verificado', row.verified_local, knowledge, row.url, row.check_note))
    acts.sort(key=_urgency)
    return Snapshot(True, view.received_local, view.course_name, tuple(acts), materials, others, view.stale)


def _urgency(act: Activity):
    rank = dl.SITUATIONS.index(act.situation) if act.situation in dl.SITUATIONS else len(dl.SITUATIONS)
    moment = act.due_moment()
    return (rank, moment.timestamp() if moment else float('inf'), fold(act.title))


def local_day_bounds(now: datetime):
    """[start, end) of 'today' in America/Sao_Paulo, as UTC datetimes."""
    local = now.astimezone(dl.SAO_PAULO)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def find(snapshot: Snapshot, reference: str) -> list[Activity]:
    """Activities whose title (or course) matches the words of ``reference``; best matches first."""
    words = [w for w in _tokens(reference) if len(w) > 2 and w not in _STOP]
    if not words:
        return []
    scored = []
    for act in snapshot.activities:
        title = _tokens(act.title)
        # Whole words only ("pro" must not match "Prova"); a long word may differ at the end (caso/casos, uso/usos).
        hits = sum(any(t == w or (len(w) >= 5 and t.startswith(w[:-1])) for t in title) for w in words)
        course = sum(w in _tokens(act.course) for w in words)
        if hits or course:                    # only the course named: every activity of it (the caller asks which)
            scored.append((hits * 2 + (1 if course else 0), act))
    scored.sort(key=lambda pair: (-pair[0], _urgency(pair[1])))
    best = scored[0][0] if scored else 0
    return [act for score, act in scored if score == best]


def _tokens(text: str) -> list:
    import re
    return re.findall(r'[a-z0-9]+', fold(text))


_STOP = {'atividade', 'tarefa', 'essa', 'esta', 'aquela', 'para', 'mim', 'prepare', 'preparar', 'ajude', 'com', 'uma',
         'que', 'minha', 'meu', 'sobre', 'disciplina', 'materia', 'jarvis', 'por', 'favor', 'faca', 'fazer', 'dessa',
         'desta', 'monte', 'montar', 'material', 'organize', 'organizar', 'trabalho', 'questionario', 'pro', 'pra', 'bora',
         'aquele', 'trampo', 'doc', 'documento', 'roteiro', 'vamos', 'quero', 'preciso', 'atividades', 'tarefas', 'dos',
         'das', 'nas', 'nos', 'uns', 'umas'}

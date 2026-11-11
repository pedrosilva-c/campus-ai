"""What the main window shows about the readings received from the Campus AI Companion (Chrome).

Pure and read-only: it opens ``live.db`` with ``mode=ro`` and derives everything from the existing
``companion_*`` tables (no second copy of the data, no writes, no migration). It never contacts the
network and never opens a link by itself: ``url`` is a validated address the window opens only after a
user action (double click).

Honesty rules:
* the FIRST reading of a section is a baseline, not news: it is shown as "registrado", never as "novo";
* "novo"/"alterado"/"ausente" are relative to the LAST reading of that section only;
* "ausente" means "not in the last (partial) reading", never "removido";
* deadlines and delivery come only from the activity's own page (Companion v0.5.4, table companion_details);
  without such a reading they are "não verificado" — never "sem prazo" and never "sem pendência";
* a "pendência" is counted only when that page said "not submitted" (or a quiz has no finished attempt) in a
  verification of the last 24 h; an older verification is shown, flagged, but not counted.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import contract
from . import deadlines as dl

SOURCE_LABEL = 'Companion (Chrome)'
KIND_LABELS = {
    'assign': 'Tarefa', 'resource': 'Arquivo', 'groupselect': 'Escolha de grupo', 'quiz': 'Questionário',
    'forum': 'Fórum', 'attendance': 'Presença', 'msteams': 'Reunião (Teams)', 'url': 'Link', 'page': 'Página',
    'folder': 'Pasta', 'book': 'Livro', 'imscp': 'Pacote de conteúdo', 'feedback': 'Pesquisa', 'lesson': 'Lição',
    'choice': 'Escolha', 'glossary': 'Glossário', 'wiki': 'Wiki', 'workshop': 'Laboratório de avaliação',
    'scorm': 'Pacote SCORM', 'h5pactivity': 'H5P', 'lti': 'Ferramenta externa', 'data': 'Base de dados',
    'bigbluebuttonbn': 'Webconferência', 'chat': 'Chat', 'survey': 'Questionário de avaliação',
}
COVERAGE_TEXT = {'parcial': 'parcial', 'completa': 'completa', 'nao_validada': 'não validada', 'falhou': 'falhou'}
STATE_TEXT = {'novo': 'novo', 'alterado': 'alterado', 'ausente': 'ausente nesta leitura',
              'reapareceu': 'reapareceu', 'linha_de_base': 'registrado', 'sem_mudanca': ''}
_MODULE_UID = re.compile(r'moodle:course:[1-9][0-9]{0,9}:module:([1-9][0-9]{0,9})')
_ALTERED = {'titulo', 'tipo', 'grupo', 'secao'}


@dataclass(frozen=True)
class ModuleRow:
    uid: str
    cmid: str
    kind: str
    kind_label: str
    category: str          # 'material' | 'atividade'
    title: str
    assessment: str
    submission: str        # as stored: 'desconhecido' unless a source proved otherwise
    state: str             # STATE_TEXT key, relative to the last reading of its section
    present: bool
    last_seen_local: str
    course_name: str
    section_name: str
    url: str               # validated module address, opened only on a user action ('' if not derivable)
    # v0.5.4 — from the activity's own page (companion_details); defaults = never verified
    situation: str = 'nao_se_aplica'   # deadlines.SITUATIONS
    due_text: str = ''                 # what the "Prazo" column says ('não verificado' when unknown)
    due_at: str = ''                   # main deadline, wall time America/Sao_Paulo ('' = none read)
    time_left: str = ''
    delivery_text: str = ''
    verified_local: str = ''           # last successful verification (local time) — "última verificação"
    check_note: str = ''               # e.g. the most recent consultation failed (older values are kept)
    soon: bool = False                 # main deadline within 72 h
    fresh: bool = False                # verified in the last 24 h


@dataclass(frozen=True)
class CompanionView:
    has_reading: bool
    run_id: int
    received_local: str
    stale: bool
    course_name: str
    section_name: str
    coverage: str
    baseline: bool
    rows: tuple
    modules: int
    activities: int
    materials: int
    novos: int
    alterados: int
    ausentes: int
    reaparecidos: int
    confirmed_pending: int
    unknown_delivery: int
    errors: int
    last_error_code: str
    last_error_local: str
    signature: tuple
    sections: tuple = ()       # SectionSummary per section with an ok reading, in order of first reading
    # v0.5.4 — counts of activities whose own page was read (unknown is never counted as zero of anything)
    verified_activities: int = 0
    detail_candidates: int = 0     # present assignments/quizzes
    overdue: int = 0
    pending_soon: int = 0
    awaiting: int = 0
    submitted: int = 0
    done: int = 0
    in_progress: int = 0
    last_verified_local: str = ''


@dataclass(frozen=True)
class SectionSummary:
    name: str
    run_id: int
    received_local: str
    modules: int               # present modules of this section
    baseline: bool             # its last reading is its first one
    novos: int
    alterados: int
    ausentes: int
    reaparecidos: int
    coverage: str


def to_local(iso_utc: str) -> str:
    """'2026-11-06T02:31:00+00:00' -> '05/11/2026 23:31' in the computer's time zone ('' if unreadable)."""
    try:
        moment = datetime.fromisoformat(str(iso_utc).replace('Z', '+00:00'))
    except ValueError:
        return ''
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime('%d/%m/%Y %H:%M')


def module_url(uid: str, kind: str) -> str:
    """Canonical module address rebuilt from the stored id and kind, or '' when it does not validate."""
    match = _MODULE_UID.fullmatch(uid)
    if not match or kind not in contract.MODULES:
        return ''
    url = f'https://ead.aedb.br/ava/mod/{kind}/view.php?id={match.group(1)}'
    try:
        return contract._url(url, 'url')
    except contract.ContractError:
        return ''


def _age_ok(iso_utc: str, now: datetime) -> bool:
    try:
        moment = datetime.fromisoformat(str(iso_utc).replace('Z', '+00:00'))
    except ValueError:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return now - moment <= contract.DEFAULT_MAX_AGE


SUBMISSION_TEXT = {'sem_envio': 'Nenhum envio', 'rascunho': 'Rascunho (não enviado)', 'enviado': 'Enviado para avaliação',
                   'reaberto': 'Reaberto (precisa reenviar)'}
GRADING_TEXT = {'avaliado': 'avaliado', 'nao_avaliado': 'não avaliado'}
ATTEMPT_TEXT = {'nenhuma': 'Nenhuma tentativa', 'em_andamento': 'Tentativa em andamento', 'finalizada': 'Tentativa finalizada'}
CHECK_TEXT = {'redirecionado': 'a página redirecionou (sessão expirada ou acesso negado)', 'sessao_expirada': 'sessão expirada',
              'inacessivel': 'página inacessível', 'tempo_esgotado': 'tempo esgotado', 'falha_rede': 'falha de carregamento',
              'falha_http': 'erro do servidor', 'pagina_nao_reconhecida': 'página não reconhecida',
              'estrutura_desconhecida': 'estrutura da página desconhecida', 'acesso_perdido': 'acesso à aba perdido',
              'nao_consultada': 'não consultada'}


def _detail_fields(item, detail, now):
    """Situation, deadline and delivery texts of one module from its companion_details row (or None)."""
    kind = item['kind']
    if kind not in dl.DETAIL_KINDS:
        return dict(situation='nao_se_aplica')
    if detail is None or not detail['verified_at']:
        note = (f'Última consulta da página: {CHECK_TEXT.get(detail["last_check_result"], detail["last_check_result"])} '
                f'em {to_local(detail["last_check_at"])}.' if detail is not None and detail['last_check_result'] else '')
        legacy = item['submission'] == 'nao_enviado' and _age_ok(item['last_seen_at'], now)
        return dict(situation='pendente' if legacy else 'nao_verificado', due_text='não verificado', check_note=note,
                    fresh=legacy)
    deadlines = [{'kind': k, 'at': detail[f]} for k, f in (('abertura', 'open_at'), ('entrega', 'due_at'),
                                                           ('limite', 'cutoff_at'), ('fechamento', 'close_at')) if detail[f]]
    facts = {'result': 'ok', 'submission_state': detail['submission_state'], 'grading_state': detail['grading_state'],
             'attempt_state': detail['attempt_state']}
    situation = dl.situation(kind, facts, deadlines, now)
    main = detail['close_at' if kind == 'quiz' else 'due_at']
    due_text = (dl.wall_text(main) if main else
                'sem prazo definido' if detail['due_state'] == 'sem_prazo' else
                f'não interpretado ("{detail["due_raw"]}")' if detail['due_state'] == 'nao_interpretado' else 'não verificado')
    if kind == 'quiz':
        delivery = ATTEMPT_TEXT.get(detail['attempt_state'], 'não verificado')
    else:
        delivery = ', '.join(filter(None, (SUBMISSION_TEXT.get(detail['submission_state'], 'não verificado'),
                                           GRADING_TEXT.get(detail['grading_state'], ''))))
    if detail['cutoff_at'] and kind == 'assign':
        delivery += f' • data limite {dl.wall_text(detail["cutoff_at"])}'
    note = ''
    if detail['last_check_result'] and detail['last_check_result'] != 'ok':
        note = (f'A consulta mais recente ({to_local(detail["last_check_at"])}) falhou: '
                f'{CHECK_TEXT.get(detail["last_check_result"], detail["last_check_result"])}; valores da última verificação.')
    fresh = _age_ok(detail['verified_at'], now)
    if not fresh:
        note = (note + ' ' if note else '') + 'Verificação com mais de 24 h: pode estar desatualizada.'
    return dict(situation=situation, due_text=due_text, due_at=main,
                time_left=dl.time_left(main, now) if situation not in ('concluida', 'enviada', 'aguardando_avaliacao') else '',
                delivery_text=delivery, verified_local=to_local(detail['verified_at']), check_note=note,
                soon=situation in dl.PENDING and dl.due_soon(main, now), fresh=fresh)


def urgency(row: ModuleRow):
    """Sort key: most urgent first (late, then pending by deadline, ...), materials last."""
    moment = dl.wall_to_utc(row.due_at) if row.due_at else None
    rank = dl.SITUATIONS.index(row.situation) if row.situation in dl.SITUATIONS else len(dl.SITUATIONS)
    return (rank, moment.timestamp() if moment else float('inf'))


def load_view(path, *, now: datetime | None = None) -> CompanionView | None:
    """None when there is no database or the Companion tables do not exist yet.

    Raises sqlite3.Error if the database is locked/damaged: the caller keeps what it already shows.
    """
    path = Path(path)
    if not path.is_file():
        return None
    now = now or datetime.now(timezone.utc)
    with closing(sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True, timeout=3)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'companion_runs'").fetchone():
            return None
        return _build(db, now)


def _build(db, now: datetime) -> CompanionView:
    max_run = db.execute('SELECT COALESCE(MAX(id), 0) FROM companion_runs').fetchone()[0]
    errors = db.execute("SELECT COUNT(*) FROM companion_runs WHERE status = 'erro'").fetchone()[0]
    last_error = db.execute("SELECT received_at, error FROM companion_runs WHERE status = 'erro' "
                            'ORDER BY id DESC LIMIT 1').fetchone()
    last = db.execute("SELECT * FROM companion_runs WHERE status = 'ok' ORDER BY id DESC LIMIT 1").fetchone()
    n_items, n_present = db.execute(
        'SELECT COUNT(*), COALESCE(SUM(present = 1), 0) FROM companion_items').fetchone()
    signature = (max_run, n_items, n_present)
    error_fields = dict(errors=errors, last_error_code=last_error['error'] if last_error else '',
                        last_error_local=to_local(last_error['received_at']) if last_error else '')
    if not last:
        return CompanionView(False, 0, '', False, '', '', '', False, (), 0, 0, 0, 0, 0, 0, 0, 0, 0,
                             signature=signature, **error_fields)

    section_last = {r['section_uid']: r for r in db.execute(
        '''SELECT r.* FROM companion_runs r JOIN (SELECT section_uid, MAX(id) AS mid FROM companion_runs
           WHERE status = 'ok' GROUP BY section_uid) m ON r.id = m.mid''')}
    section_first = {r['section_uid']: r['mid'] for r in db.execute(
        "SELECT section_uid, MIN(id) AS mid FROM companion_runs WHERE status = 'ok' GROUP BY section_uid")}
    run_ids = [r['id'] for r in section_last.values()]
    changes: dict[tuple, set] = {}
    if run_ids:
        marks = ','.join('?' * len(run_ids))
        for row in db.execute(f'SELECT run, uid, change FROM companion_changes WHERE run IN ({marks})', run_ids):
            changes.setdefault((row['run'], row['uid']), set()).add(row['change'])

    details = {}
    if db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'companion_details'").fetchone():
        details = {r['uid']: r for r in db.execute('SELECT * FROM companion_details')}
    rows = []
    pending = 0
    present_by_section: dict[str, int] = {}
    for item in db.execute('SELECT * FROM companion_items ORDER BY section_uid, CAST(substr(uid, '
                           "instr(uid, ':module:') + 8) AS INTEGER)"):
        run = section_last.get(item['section_uid'])
        baseline_run = run is not None and run['id'] == section_first.get(item['section_uid'])
        seen = changes.get((run['id'], item['uid']), set()) if run is not None else set()
        if not item['present']:
            state = 'ausente'
        elif 'novo' in seen:
            state = 'linha_de_base' if baseline_run else 'novo'
        elif seen & _ALTERED:
            state = 'alterado'
        elif 'reapareceu' in seen:
            state = 'reapareceu'
        else:
            state = 'sem_mudanca'
        match = _MODULE_UID.fullmatch(item['uid'])
        extra = _detail_fields(item, details.get(item['uid']), now)
        if item['present'] and extra['situation'] in dl.PENDING and extra.get('fresh'):
            pending += 1          # proven by the activity's page (or a source said "not submitted") in the last 24 h
        if item['present']:
            present_by_section[item['section_uid']] = present_by_section.get(item['section_uid'], 0) + 1
        rows.append(ModuleRow(
            uid=item['uid'], cmid=match.group(1) if match else '', kind=item['kind'],
            kind_label=KIND_LABELS.get(item['kind'], item['kind']),
            category='material' if item['kind'] in contract.MATERIAL_KINDS else 'atividade',
            title=item['title'], assessment=item['assessment'], submission=item['submission'], state=state,
            present=bool(item['present']), last_seen_local=to_local(item['last_seen_at']),
            course_name=run['course_name'] if run is not None else '',
            section_name=run['section_name'] if run is not None else '',
            url=module_url(item['uid'], item['kind']), **extra))

    shown = [r for r in rows if r.present]
    checked = [r for r in shown if r.verified_local]
    verified_times = [d['verified_at'] for uid, d in details.items() if d['verified_at']]
    count = lambda *names: sum(r.situation in names for r in shown)       # noqa: E731
    sections = []
    for uid in sorted(section_last, key=lambda u: section_first.get(u, 0)):
        run = section_last[uid]
        base = run['id'] == section_first.get(uid)
        sections.append(SectionSummary(
            name=run['section_name'], run_id=run['id'], received_local=to_local(run['received_at']),
            modules=present_by_section.get(uid, 0), baseline=base, novos=0 if base else run['novos'],
            alterados=0 if base else run['alterados'], ausentes=run['ausentes'], reaparecidos=run['reaparecidos'],
            coverage=run['coverage']))
    baseline = last['id'] == section_first.get(last['section_uid'])
    return CompanionView(
        has_reading=True, run_id=last['id'], received_local=to_local(last['received_at']),
        stale=not _age_ok(last['received_at'], now), course_name=last['course_name'],
        section_name=last['section_name'], coverage=last['coverage'], baseline=baseline, rows=tuple(rows),
        modules=len(shown), activities=sum(r.category == 'atividade' for r in shown),
        materials=sum(r.category == 'material' for r in shown),
        novos=0 if baseline else last['novos'], alterados=0 if baseline else last['alterados'],
        ausentes=last['ausentes'], reaparecidos=last['reaparecidos'], confirmed_pending=pending,
        unknown_delivery=sum(r.category == 'atividade' and r.submission == 'desconhecido' for r in shown),
        signature=signature, sections=tuple(sections),
        verified_activities=len(checked), detail_candidates=sum(r.kind in dl.DETAIL_KINDS for r in shown),
        overdue=count('atrasada'), pending_soon=sum(r.soon for r in shown), awaiting=count('aguardando_avaliacao'),
        submitted=count('enviada'), done=count('concluida'), in_progress=count('verificar_tentativa'),
        last_verified_local=to_local(max(verified_times)) if verified_times else '', **error_fields)


def status_text(view: CompanionView | None) -> str:
    """Plain text for the Companion box of the main window (says only what was verified)."""
    if view is None or not view.has_reading:
        lines = ['Nenhuma leitura do Campus AI Companion foi recebida ainda. Abra a seção no Chrome e use '
                 '"Salvar no Campus AI".']
    else:
        lines = [
            f'Última leitura: {view.received_local} (horário local) • leitura nº {view.run_id}'
            + (' • ATENÇÃO: há mais de 24 h, os dados podem estar desatualizados' if view.stale else ''),
            (f'Disciplina: {view.course_name} — seção {view.section_name}' if len(view.sections) <= 1 else
             f'Disciplina: {view.course_name} — {len(view.sections)} seções com leitura: '
             + ', '.join(sec.name for sec in view.sections)),
            (f'Cobertura: {COVERAGE_TEXT.get(view.coverage, view.coverage)} — somente a seção lida foi examinada; '
             'as demais seções não.' if len(view.sections) <= 1 else
             'Cobertura da disciplina: parcial — somente as seções listadas foram examinadas; as demais não.'),
            f'Módulos: {view.modules} ({view.activities} atividade(s), {view.materials} material(is)) • '
            f'Pendências confirmadas: {view.confirmed_pending}',
        ]
        if len(view.sections) > 1:
            for sec in view.sections:
                news = ('primeira leitura (linha de base), não são novidades' if sec.baseline else
                        f'{sec.novos} novo(s), {sec.alterados} alterado(s), {sec.reaparecidos} reapareceu(ram), '
                        f'{sec.ausentes} ausente(s) nesta leitura')
                lines.append(f'• {sec.name}: {sec.modules} módulo(s) • leitura nº {sec.run_id} em {sec.received_local} '
                             f'• {news}')
            lines.append('Ausente não significa removido. Uma seção que falhou mantém os dados da última leitura salva.')
        elif view.baseline:
            lines.append(f'Primeira leitura desta seção: {view.modules} módulo(s) registrados como linha de base. '
                         'Não são novidades.')
        else:
            lines.append(f'Novidades desta leitura: {view.novos} novo(s), {view.alterados} alterado(s), '
                         f'{view.reaparecidos} reapareceu(ram), {view.ausentes} ausente(s) nesta leitura '
                         '(ausente não significa removido).')
        if not view.verified_activities:
            lines.append(f'Prazos: não verificados • Entrega: desconhecida em {view.unknown_delivery} atividade(s) '
                         '(nenhuma página de atividade foi lida ainda).')
        else:
            lines.append(
                f'Prazos e entregas lidos nas páginas de {view.verified_activities} de {view.detail_candidates} '
                f'tarefa(s)/questionário(s) • última verificação: {view.last_verified_local}')
            lines.append(
                f'Atrasadas: {view.overdue} • Pendentes: '
                f'{sum(r.present and r.situation == "pendente" for r in view.rows)}'
                f' (vencendo em até 72 h: {view.pending_soon}) • Tentativa em andamento: {view.in_progress} • '
                f'Aguardando avaliação: {view.awaiting} • Enviadas: {view.submitted} • Concluídas: {view.done} • '
                f'Não verificadas: {view.detail_candidates - view.verified_activities}')
    if view is not None and view.errors:
        lines.append(f'Erros de sincronização: {view.errors} (último: {view.last_error_code} em '
                     f'{view.last_error_local})')
    else:
        lines.append('Erros de sincronização: nenhum.')
    return '\n'.join(lines)

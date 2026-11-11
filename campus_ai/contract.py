"""Versioned academic data contract: ``campus-ai.academic/1``.

One model for every source (browser pilot, future Companion extension, Moodle API, iCal, Gmail).
Pure and local: no network, filesystem, database or AI. Parsing is strict on purpose: unknown fields,
unknown enum values, foreign URLs, private query parameters and dangling references are rejected,
because snapshots may come from a browser extension that reads untrusted pages.

Two independent axes are kept apart:

* ``verification`` (per record): how much this record's own data was observed.
  ``confirmado`` / ``parcial`` / ``nao_verificado`` / ``desatualizado`` / ``erro_integracao``.
* ``coverage`` (per snapshot): whether the SET of records is complete for the scope.
  ``completa`` / ``parcial`` / ``nao_validada`` / ``falhou``. Zero items is never ``completa``.

A published activity is not a pending activity: ``submission`` defaults to ``desconhecido`` and
``pending_state`` only answers ``pendente`` when the source explicitly said "not submitted" in a
confirmed, fresh observation. A failed or partial source never proves absence.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import MISSING, asdict, dataclass, fields, replace  # noqa: F401  (replace re-exported)
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit

SCHEMA_ID = 'campus-ai.academic/1'

VERIFICATION = ('confirmado', 'parcial', 'nao_verificado', 'desatualizado', 'erro_integracao')
COVERAGE = ('completa', 'parcial', 'nao_validada', 'falhou')
CONFIDENCE = ('alta', 'media', 'baixa')
SUBMISSION = ('desconhecido', 'nao_enviado', 'enviado', 'avaliado')
SOURCES = ('moodle_navegador', 'moodle_api', 'companion', 'claude_chrome_poc', 'ical', 'gmail', 'manual', 'demo')
METHODS = ('dom', 'api', 'ical', 'email', 'manual', 'fixture')
SECTION_STATES = ('aberta', 'recolhida', 'desconhecida')
DEADLINE_KINDS = ('entrega', 'abertura', 'fechamento', 'evento', 'limite')   # 'limite' = cut-off date (v0.5.4)
# v0.5.4 — what an activity's OWN page said (Companion step "detalhar"). Mirror of companion/src/deadlines.js.
DETAIL_TIMEZONE = 'America/Sao_Paulo'
DETAIL_RESULTS = ('ok', 'nao_consultada', 'parametros_invalidos', 'fora_do_dominio', 'curso_diferente', 'redirecionado',
                  'inacessivel', 'falha_http', 'nao_html', 'tempo_esgotado', 'falha_rede', 'grande_demais',
                  'sessao_expirada', 'pagina_nao_reconhecida', 'estrutura_desconhecida', 'acesso_perdido')
SUBMISSION_STATES = ('desconhecido', 'sem_envio', 'rascunho', 'enviado', 'reaberto', 'nao_se_aplica')
GRADING_STATES = ('desconhecido', 'avaliado', 'nao_avaliado', 'nao_se_aplica')
ATTEMPT_STATES = ('desconhecido', 'nenhuma', 'em_andamento', 'finalizada', 'nao_se_aplica')
DUE_STATES = ('nao_verificado', 'definido', 'sem_prazo', 'nao_interpretado')
ASSESSMENT_BASIS = ('', 'titulo', 'posicao')   # how an AV group was decided; '' = not grouped
CHANNELS = ('forum', 'gmail', 'outro')

MODULES = ('resource', 'assign', 'quiz', 'page', 'url', 'folder', 'book', 'forum', 'lesson',
           'choice', 'feedback', 'glossary', 'wiki', 'workshop', 'scorm', 'h5pactivity', 'lti',
           'data', 'bigbluebuttonbn', 'chat', 'survey', 'imscp',
           # Seen on the real AEDB course index/section page (05/11/2026); not in the pilot's list.
           'attendance', 'groupselect', 'msteams')
MATERIAL_KINDS = frozenset(('resource', 'page', 'url', 'folder', 'book', 'imscp'))
ACTIVITY_KINDS = frozenset(MODULES) - MATERIAL_KINDS

MAX_TITLE = 400
MAX_NAME = 200
MAX_URL = 2048
MAX_RAW = 160
MAX_MESSAGE = 300
MAX_ROUTE = 200
MAX_RECORDS = 2000
MAX_REASONS = 50
MAX_DEADLINES = 5
MAX_SCOPE = 50
DEFAULT_MAX_AGE = timedelta(hours=24)

AEDB_HOST = 'ead.aedb.br'
_UID = re.compile(r'(moodle|ical|gmail|demo):[a-z0-9][a-z0-9:_-]{0,150}')
_COURSE_UID = re.compile(r'moodle:course:([1-9][0-9]{0,9})')
_ROUTE = re.compile(r'[/A-Za-z_.N-]*(\?[A-Za-z_&]*)?')   # digits are always hidden as N
_ISO = re.compile(r'\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?([+-]\d{2}:\d{2}|Z)?)?')
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')


class ContractError(ValueError):
    """The data does not satisfy campus-ai.academic/1. Messages never echo field values."""


# --- Records ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Provenance:
    source: str
    observed_at: str      # ISO-8601 with timezone: "última verificação" of this record
    method: str
    route: str = ''       # route pattern only (digits hidden, query keys without values)


@dataclass(frozen=True)
class Deadline:
    kind: str
    at: str               # 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM[:SS]' (+offset only if timezone_explicit) or ''
    timezone_explicit: bool
    raw: str = ''         # the visible deadline text, bounded; kept when the date cannot be parsed


@dataclass(frozen=True)
class Course:
    uid: str
    moodle_id: str
    name: str
    url: str
    provenance: Provenance
    verification: str
    confidence: str


@dataclass(frozen=True)
class Section:
    uid: str
    course_uid: str
    name: str
    position: int | None
    state: str
    provenance: Provenance
    verification: str
    confidence: str


@dataclass(frozen=True)
class Material:
    uid: str
    course_uid: str
    section_uid: str
    title: str
    kind: str
    url: str
    provenance: Provenance
    verification: str
    confidence: str
    assessment: str = ''          # 'AV1'..'AV9' or ''; derived, never read from a field of the source
    assessment_basis: str = ''    # 'titulo' (stated in the title) | 'posicao' (inferred from layout)


@dataclass(frozen=True)
class ActivityDetail:
    """What the activity's own page said (v0.5.4). Absent (None) = its page was not consulted."""
    checked_at: str       # ISO-8601 with timezone: when that page was read
    result: str           # DETAIL_RESULTS; anything but 'ok' means nothing below was observed
    submission_state: str
    grading_state: str
    attempt_state: str
    due_state: str        # 'sem_prazo' only when the page's dates were recognised and had no such date
    timezone: str         # the time zone of the deadlines' wall times


@dataclass(frozen=True)
class Activity:
    uid: str
    course_uid: str
    section_uid: str
    title: str
    kind: str
    url: str
    deadlines: tuple
    submission: str       # what the SOURCE said about delivery; never inferred
    provenance: Provenance
    verification: str
    confidence: str
    assessment: str = ''
    assessment_basis: str = ''
    detail: ActivityDetail | None = None


@dataclass(frozen=True)
class CalendarEvent:
    uid: str
    course_uid: str
    title: str
    start: str
    end: str
    kind: str
    activity_uid: str
    provenance: Provenance
    verification: str
    confidence: str


@dataclass(frozen=True)
class Announcement:
    uid: str
    course_uid: str
    title: str
    posted_at: str
    channel: str
    url: str
    provenance: Provenance
    verification: str
    confidence: str


@dataclass(frozen=True)
class SourceStatus:
    source: str
    last_attempt: str
    last_success: str
    status: str           # one of VERIFICATION
    message: str = ''


@dataclass(frozen=True)
class CoverageInfo:
    state: str
    reasons: tuple = ()


@dataclass(frozen=True)
class Snapshot:
    schema: str
    generated_at: str
    scope: tuple
    coverage: CoverageInfo
    sources: tuple
    courses: tuple
    sections: tuple
    materials: tuple
    activities: tuple
    events: tuple
    announcements: tuple


# --- Field validators --------------------------------------------------------------------------------

def _fail(path, why):
    raise ContractError(f'{path}: {why}')


def _text(limit, *, required=True):
    def check(value, path):
        if not isinstance(value, str):
            _fail(path, 'texto esperado')
        if required and not value.strip():
            _fail(path, 'texto vazio')
        if len(value) > limit:
            _fail(path, f'texto acima de {limit} caracteres')
        if _CONTROL.search(value):
            _fail(path, 'caracteres de controle')
        return value
    return check


def _enum(options):
    def check(value, path):
        if value not in options:
            _fail(path, 'valor fora do vocabulário')
        return value
    return check


def _uid(value, path):
    if not isinstance(value, str) or not _UID.fullmatch(value):
        _fail(path, 'identificador inválido')
    return value


def _optional_uid(value, path):
    return '' if value == '' else _uid(value, path)


def _bool(value, path):
    if not isinstance(value, bool):
        _fail(path, 'booleano esperado')
    return value


def _position(value, path):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10000:
        _fail(path, 'posição inválida')
    return value


def _iso(value, path, *, aware=None, optional=False):
    if optional and value == '':
        return value
    if not isinstance(value, str) or not _ISO.fullmatch(value):
        _fail(path, 'data ISO-8601 esperada')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        _fail(path, 'data inexistente')
    has_tz = 'T' in value and parsed.tzinfo is not None
    if aware is True and not has_tz:
        _fail(path, 'fuso horário obrigatório')
    if aware is False and has_tz:
        _fail(path, 'fuso declarado como implícito')
    return value


def _aware(value, path):
    return _iso(value, path, aware=True)


def _optional_aware(value, path):
    return _iso(value, path, aware=True, optional=True)


def _loose_date(value, path):
    return _iso(value, path, optional=True)


def _route(value, path):
    if not isinstance(value, str) or len(value) > MAX_ROUTE or not _ROUTE.fullmatch(value):
        _fail(path, 'padrão de rota inválido (sem valores nem números)')
    return value


def _url(value, path, *, gmail=False):
    if value == '':
        return value
    if not isinstance(value, str) or len(value) > MAX_URL or _CONTROL.search(value):
        _fail(path, 'URL inválida')
    try:
        p = urlsplit(value)
    except ValueError:
        _fail(path, 'URL inválida')
    if gmail and p.scheme == 'https' and p.netloc == 'mail.google.com':
        if p.path.startswith('/mail/') and not p.query:
            return value
        _fail(path, 'URL Gmail fora do formato permitido')
    if p.scheme != 'https' or p.netloc != AEDB_HOST or not p.path.startswith('/ava/') or p.fragment:
        _fail(path, 'URL fora da AEDB ou insegura')
    query = parse_qs(p.query, keep_blank_values=True)
    if not set(query) <= {'id', 'section'} or any(len(v) != 1 or not v[0].isdigit() for v in query.values()):
        _fail(path, 'parâmetros de URL não permitidos')
    return value


def _gmail_url(value, path):
    return _url(value, path, gmail=True)


def _assessment(value, path):
    if value != '' and not (isinstance(value, str) and re.fullmatch(r'AV[1-9]', value)):
        _fail(path, 'grupo de avaliação inválido')
    return value


def _record(cls, validators):
    flds = fields(cls)
    names = [f.name for f in flds]
    required = {f.name for f in flds if f.default is MISSING and f.default_factory is MISSING}
    assert set(names) == set(validators), cls

    def parse(data, path):
        if not isinstance(data, dict):
            _fail(path, 'objeto esperado')
        extra = set(data) - set(names)
        if extra:
            _fail(path, 'campo desconhecido')
        missing = required - set(data)
        if missing:
            _fail(path, 'campo ausente: ' + ', '.join(sorted(missing)))
        return cls(**{n: validators[n](data[n], f'{path}.{n}') for n in names if n in data})
    return parse


def _list(item, limit):
    def check(value, path):
        if not isinstance(value, (list, tuple)):
            _fail(path, 'lista esperada')
        if len(value) > limit:
            _fail(path, f'mais de {limit} elementos')
        return tuple(item(v, f'{path}[{i}]') for i, v in enumerate(value))
    return check


_provenance = _record(Provenance, dict(source=_enum(SOURCES), observed_at=_aware, method=_enum(METHODS),
                                       route=_route))


def _deadline(data, path):
    d = _record(Deadline, dict(kind=_enum(DEADLINE_KINDS), at=lambda v, p: v, timezone_explicit=_bool,
                               raw=_text(MAX_RAW, required=False)))(data, path)
    _iso(d.at, path + '.at', aware=d.timezone_explicit, optional=True)
    if not d.at and not d.raw:
        _fail(path, 'prazo sem data nem texto')
    return d


_QUALITY = dict(provenance=_provenance, verification=_enum(VERIFICATION), confidence=_enum(CONFIDENCE))

_course = _record(Course, dict(uid=_uid, moodle_id=_text(10), name=_text(MAX_NAME), url=_url, **_QUALITY))
_section = _record(Section, dict(uid=_uid, course_uid=_uid, name=_text(MAX_NAME), position=_position,
                                 state=_enum(SECTION_STATES), **_QUALITY))
_AV = dict(assessment=_assessment, assessment_basis=_enum(ASSESSMENT_BASIS))
_material = _record(Material, dict(uid=_uid, course_uid=_uid, section_uid=_optional_uid, title=_text(MAX_TITLE),
                                   kind=_enum(MATERIAL_KINDS), url=_url, **_QUALITY, **_AV))
_detail_record = _record(ActivityDetail, dict(
    checked_at=_aware, result=_enum(DETAIL_RESULTS), submission_state=_enum(SUBMISSION_STATES),
    grading_state=_enum(GRADING_STATES), attempt_state=_enum(ATTEMPT_STATES), due_state=_enum(DUE_STATES),
    timezone=lambda v, p: v if v == DETAIL_TIMEZONE else _fail(p, 'fuso não suportado')))


def _detail(value, path):
    if value is None:
        return None
    detail = _detail_record(value, path)
    if detail.result != 'ok' and (detail.submission_state, detail.grading_state, detail.attempt_state,
                                  detail.due_state) != ('desconhecido', 'desconhecido', 'desconhecido', 'nao_verificado'):
        _fail(path, 'estado declarado sem leitura da página')      # a failed page never states anything
    return detail


_activity = _record(Activity, dict(uid=_uid, course_uid=_uid, section_uid=_optional_uid, title=_text(MAX_TITLE),
                                   kind=_enum(ACTIVITY_KINDS), url=_url,
                                   deadlines=_list(_deadline, MAX_DEADLINES), submission=_enum(SUBMISSION),
                                   **_QUALITY, **_AV, detail=_detail))
_event = _record(CalendarEvent, dict(uid=_uid, course_uid=_optional_uid, title=_text(MAX_TITLE), start=_loose_date,
                                     end=_loose_date, kind=_enum(DEADLINE_KINDS), activity_uid=_optional_uid,
                                     **_QUALITY))
_announcement = _record(Announcement, dict(uid=_uid, course_uid=_optional_uid, title=_text(MAX_TITLE),
                                           posted_at=_loose_date, channel=_enum(CHANNELS), url=_gmail_url,
                                           **_QUALITY))
_source = _record(SourceStatus, dict(source=_enum(SOURCES), last_attempt=_aware, last_success=_optional_aware,
                                     status=_enum(VERIFICATION), message=_text(MAX_MESSAGE, required=False)))
_coverage = _record(CoverageInfo, dict(state=_enum(COVERAGE),
                                       reasons=_list(_text(MAX_MESSAGE), MAX_REASONS)))


def _scope_uid(value, path):
    if not isinstance(value, str) or not _COURSE_UID.fullmatch(value):
        _fail(path, 'escopo deve listar disciplinas Moodle')
    return value


_snapshot = _record(Snapshot, dict(
    schema=lambda v, p: v if v == SCHEMA_ID else _fail(p, 'esquema ou versão não suportados'),
    generated_at=_aware, scope=_list(_scope_uid, MAX_SCOPE), coverage=_coverage,
    sources=_list(_source, len(SOURCES)), courses=_list(_course, MAX_SCOPE),
    sections=_list(_section, MAX_RECORDS), materials=_list(_material, MAX_RECORDS),
    activities=_list(_activity, MAX_RECORDS), events=_list(_event, MAX_RECORDS),
    announcements=_list(_announcement, MAX_RECORDS)))


def _check_references(s: Snapshot) -> None:
    if not s.scope:
        _fail('scope', 'vazio')
    courses = {}
    for i, course in enumerate(s.courses):
        if course.uid in courses or course.uid not in s.scope or course.uid != 'moodle:course:' + course.moodle_id:
            _fail(f'courses[{i}]', 'referência de disciplina inválida ou repetida')
        courses[course.uid] = course
    sections = {}
    for i, sec in enumerate(s.sections):
        if sec.course_uid not in courses or not sec.uid.startswith(sec.course_uid + ':section:'):
            _fail(f'sections[{i}]', 'referência de disciplina inválida')
        if sec.uid in sections:
            _fail(f'sections[{i}]', 'identificador repetido')
        sections[sec.uid] = sec
    seen = set()
    for table, records in (('materials', s.materials), ('activities', s.activities)):
        for i, rec in enumerate(records):
            path = f'{table}[{i}]'
            if rec.course_uid not in courses or not rec.uid.startswith(rec.course_uid + ':'):
                _fail(path, 'referência de disciplina inválida')
            if rec.section_uid and (rec.section_uid not in sections
                                    or sections[rec.section_uid].course_uid != rec.course_uid):
                _fail(path, 'referência de seção inválida')
            if rec.uid in seen:
                _fail(path, 'identificador repetido')
            seen.add(rec.uid)
            if bool(rec.assessment) != bool(rec.assessment_basis):
                _fail(path, 'grupo de avaliação e sua base devem vir juntos')
    activities = {a.uid for a in s.activities}
    for table, records in (('events', s.events), ('announcements', s.announcements)):
        for i, rec in enumerate(records):
            if rec.course_uid and rec.course_uid not in courses:
                _fail(f'{table}[{i}]', 'referência de disciplina inválida')
            if getattr(rec, 'activity_uid', '') and rec.activity_uid not in activities:
                _fail(f'{table}[{i}]', 'referência de atividade inválida')
            if rec.uid in seen:
                _fail(f'{table}[{i}]', 'identificador repetido')
            seen.add(rec.uid)
    if len({src.source for src in s.sources}) != len(s.sources):
        _fail('sources', 'fonte repetida')
    if s.coverage.state == 'completa' and not (s.materials or s.activities):
        _fail('coverage', 'zero itens nunca é cobertura completa')


def parse_snapshot(data) -> Snapshot:
    """Validate an untrusted dict (e.g. decoded JSON) and return an immutable Snapshot."""
    snap = _snapshot(data, 'snapshot')
    _check_references(snap)
    return snap


def snapshot_to_dict(snapshot: Snapshot) -> dict:
    return asdict(snapshot)


# --- Semantics -------------------------------------------------------------------------------------

def _parse_aware(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def effective_verification(record, *, now=None, max_age=DEFAULT_MAX_AGE) -> str:
    """The record's verification, downgraded to 'desatualizado' when its observation is too old."""
    now = now or datetime.now(timezone.utc)
    if record.verification in ('confirmado', 'parcial'):
        if now - _parse_aware(record.provenance.observed_at) > max_age:
            return 'desatualizado'
    return record.verification


def pending_state(activity: Activity, *, now=None, max_age=DEFAULT_MAX_AGE) -> str:
    """'pendente' | 'nao_pendente' | 'desconhecido'. Published is never the same as pending."""
    if activity.submission in ('enviado', 'avaliado'):
        return 'nao_pendente'
    if activity.submission == 'nao_enviado' and \
            effective_verification(activity, now=now, max_age=max_age) == 'confirmado':
        return 'pendente'
    return 'desconhecido'


def source_proves_absence(status: SourceStatus, coverage: str | None = None) -> bool:
    """Only a confirmed source with complete coverage can say "nothing there". Errors never can."""
    return status.status == 'confirmado' and coverage == 'completa'


# --- Visible deadline text (pt-BR Moodle) ----------------------------------------------------------

_MONTHS = {'jan': 1, 'janeiro': 1, 'fev': 2, 'fevereiro': 2, 'mar': 3, 'marco': 3, 'abr': 4, 'abril': 4,
           'mai': 5, 'maio': 5, 'jun': 6, 'junho': 6, 'jul': 7, 'julho': 7, 'ago': 8, 'agosto': 8,
           'set': 9, 'setembro': 9, 'out': 10, 'outubro': 10, 'nov': 11, 'novembro': 11,
           'dez': 12, 'dezembro': 12}
_DATE_TEXT = re.compile(r'(\d{1,2})\s+(?:de\s+)?([a-z]+)\.?\s+(?:de\s+)?(\d{4})'
                        r'(?:\s*,?\s*(?:as\s*)?(\d{1,2}):(\d{2}))?')
_KIND_TEXT = (('abertura', re.compile(r'^(abre|abertura|aberto|disponivel a partir|opens?)\b')),
              ('fechamento', re.compile(r'^(fecha|fechamento|encerra|encerramento|closes?)\b')),
              ('entrega', re.compile(r'^(vencimento|prazo|data limite|data de entrega|entrega|due)\b')))


def _fold(text: str) -> str:
    return ''.join(ch for ch in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(ch))


def deadline_from_text(text) -> Deadline | None:
    """Turn visible deadline text into a Deadline. Never invents a date: unparseable stays raw."""
    raw = ' '.join(str(text or '').split())[:MAX_RAW]
    folded = _fold(raw)
    if not raw or folded in ('nao informado', 'nao informada', '-'):
        return None
    kind = next((k for k, rx in _KIND_TEXT if rx.search(folded)), 'evento')
    at = ''
    m = _DATE_TEXT.search(folded)
    if m and m.group(2) in _MONTHS:
        try:
            day = date(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
            at = day.isoformat()
            if m.group(4) is not None:
                hour, minute = int(m.group(4)), int(m.group(5))
                if hour < 24 and minute < 60:
                    at += f'T{hour:02d}:{minute:02d}'
        except ValueError:
            at = ''
    return Deadline(kind, at, False, raw)


# --- Stable identifiers ----------------------------------------------------------------------------

def course_uid(moodle_id: str) -> str:
    return f'moodle:course:{moodle_id}'


def module_uid(moodle_id: str, cmid: str) -> str:
    """Same identifier the existing connectors use, so SQLite history and note names stay stable."""
    return f'moodle:course:{moodle_id}:module:{cmid}'


def section_uid(moodle_id: str, name: str) -> str:
    return f'moodle:course:{moodle_id}:section:s-' + sha256(_fold(name).encode()).hexdigest()[:10]


def item_uid(moodle_id: str, section: str, kind: str, title: str) -> str:
    """Fallback without a module id: fragile (title changes create a new id), so confidence is low."""
    key = '\0'.join((_fold(section), kind, _fold(title)))
    return f'moodle:course:{moodle_id}:item:' + sha256(key.encode()).hexdigest()[:16]


# --- Bridges to the existing code ------------------------------------------------------------------

_MODULE_PATH = re.compile(r'^/ava/mod/([a-z0-9]+)/view\.php$')
_PILOT_ROUTE = '/ava/course/view.php?id'


def _kind_of(row, label_to_kind) -> str:
    if row.url:
        m = _MODULE_PATH.match(urlsplit(row.url).path)
        if m and m.group(1) in MODULES:
            return m.group(1)
    return label_to_kind.get(row.kind, '')


def from_pilot_result(result, course, *, observed_at=None, source='moodle_navegador') -> Snapshot:
    """Map an in-memory ``PilotResult`` of one authorized course to a validated Snapshot."""
    from .pilot import KIND_LABELS
    label_to_kind = {label: kind for kind, label in KIND_LABELS.items() if kind != 'Seção'}
    observed = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec='seconds')
    cid = course.course_id
    cuid = course_uid(cid)
    state = result.state if result.state in COVERAGE else 'falhou'
    reasons = [' '.join(str(n).split())[:MAX_MESSAGE] for n in (result.notes or ())]
    cov = getattr(result, 'coverage', None)
    for name, why in (getattr(cov, 'reasons', ()) or ()):
        reasons.append(' '.join(f'{name}: {why}'.split())[:MAX_MESSAGE])

    sections, materials, activities, seen, skipped = {}, [], [], set(), 0

    def section_ref(name, quality):
        name = ' '.join(str(name or '').split())[:MAX_NAME]
        if not name:
            return ''
        uid = section_uid(cid, name)
        if uid not in sections:
            sections[uid] = Section(uid, cuid, name, len(sections) + 1, 'desconhecida',
                                    Provenance(source, observed, 'dom', _PILOT_ROUTE), quality, 'media')
        return uid

    record_quality = {'completa': 'confirmado', 'parcial': 'confirmado',
                      'nao_validada': 'nao_verificado'}.get(state, 'erro_integracao')
    for row in result.rows:
        title = ' '.join(str(row.title).split())[:MAX_TITLE]
        if row.kind == 'Seção':
            section_ref(title, record_quality)
            continue
        kind = _kind_of(row, label_to_kind)
        if not title or not kind:
            skipped += 1
            continue
        sec = section_ref(row.section, record_quality)
        module_id = row.module_id if str(row.module_id).isdigit() else ''
        uid = module_uid(cid, module_id) if module_id else item_uid(cid, row.section, kind, title)
        if uid in seen:
            continue
        seen.add(uid)
        url = row.url if module_id else ''
        prov = Provenance(source, observed, 'dom', _PILOT_ROUTE)
        confidence = 'alta' if module_id else 'baixa'
        if kind in MATERIAL_KINDS:
            materials.append(Material(uid, cuid, sec, title, kind, url, prov, record_quality, confidence))
        else:
            deadline = deadline_from_text(row.due)
            activities.append(Activity(uid, cuid, sec, title, kind, url, (deadline,) if deadline else (),
                                       'desconhecido', prov, record_quality, confidence))
    if skipped:
        reasons.append(f'{skipped} item(ns) sem tipo reconhecido não convertido(s)')
    if state == 'completa' and not (materials or activities):
        state, record_quality = 'nao_validada', 'nao_verificado'
        reasons.append('Nenhum material ou atividade extraído: cobertura não validada')
        sections = {k: replace(v, verification='nao_verificado') for k, v in sections.items()}
    source_status = {'completa': 'confirmado', 'parcial': 'parcial',
                     'nao_validada': 'nao_verificado'}.get(state, 'erro_integracao')
    snap = Snapshot(
        SCHEMA_ID, observed, (cuid,), CoverageInfo(state, tuple(reasons[:MAX_REASONS])),
        (SourceStatus(source, observed, observed if state != 'falhou' else '', source_status,
                      {'falhou': 'leitura falhou'}.get(state, '')),),
        (Course(cuid, cid, course.name, course.url, Provenance(source, observed, 'dom', _PILOT_ROUTE),
                'confirmado' if state != 'falhou' else 'nao_verificado', 'alta' if state != 'falhou' else 'baixa'),),
        tuple(sections.values()), tuple(materials), tuple(activities), (), ())
    return parse_snapshot(snapshot_to_dict(snap))


def to_academic_items(snapshot: Snapshot):
    """Adapter to the current engine/Obsidian model. Only stable fields enter ``meta`` (fingerprint)."""
    from .models import AcademicItem
    names = {c.uid: c.name for c in snapshot.courses}
    now = _parse_aware(snapshot.generated_at)

    def base_meta(rec, kind):
        m = _MODULE_UID.fullmatch(rec.uid)
        meta = {'courseid': int(rec.course_uid.rsplit(':', 1)[1]), 'type': kind}
        meta['moduleid'] = int(m.group(1)) if m else None
        return meta

    items = []
    for mat in snapshot.materials:
        items.append(AcademicItem(mat.uid, 'moodle', 'material', mat.title, names.get(mat.course_uid, 'Geral'),
                                  '', mat.url, meta=base_meta(mat, mat.kind)))
    for act in snapshot.activities:
        due = next((d.at for d in act.deadlines if d.at and d.kind in ('entrega', 'fechamento')), '')
        status = {'pendente': 'pending', 'nao_pendente': 'submitted'}.get(pending_state(act, now=now), 'unknown')
        # Same split as moodle.py / moodle_browser.py: only assign/quiz are assignments, so a group
        # selection, attendance sheet or meeting link is never listed as "pending work".
        category = ('assignment' if act.kind in ('assign', 'quiz')
                    else 'announcement' if act.kind == 'forum' else 'material')
        items.append(AcademicItem(act.uid, 'moodle', category, act.title, names.get(act.course_uid, 'Geral'),
                                  '', act.url, due_iso=due, status=status, meta=base_meta(act, act.kind)))
    for ann in snapshot.announcements:
        source = 'gmail' if ann.channel == 'gmail' else 'moodle'
        items.append(AcademicItem(ann.uid, source, 'announcement', ann.title,
                                  names.get(ann.course_uid, 'Geral'), '', ann.url,
                                  meta={'courseid': int(ann.course_uid.rsplit(':', 1)[1]) if ann.course_uid else None,
                                        'type': ann.channel, 'moduleid': None}))
    return items


_MODULE_UID = re.compile(r'moodle:course:[0-9]+:module:([0-9]+)')

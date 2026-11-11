"""Local persistence and comparison of Companion snapshots (campus-ai.academic/1).

Uses the SAME SQLite file as ``state.History`` (``live.db`` under the app data folder), in its own
``companion_*`` tables with a versioned migration, so no parallel database or academic model is created.
Item ids are the existing ``moodle:course:<id>:module:<cmid>``.

Honesty rules:
* a Companion snapshot covers one section and is always partial: an item missing from a new reading of the
  same section is marked "ausente nesta leitura" (``present = 0``), never deleted or called removed;
* items of other sections are never touched by a reading of this section;
* delivery state is stored as the source gave it (``desconhecido`` unless proven);
* each reading is applied in ONE transaction; on any error everything is rolled back and nothing is
  reported as saved. Failures are recorded separately with a code only (no page content, no traceback).
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import contract

SCHEMA_VERSION = 2
# v0.5.4: what each activity's own page said. Current values in companion_details (one row per module, updated in
# place: never a second row) and every distinct observation in companion_detail_history (append only).
# Dates are Moodle's wall time in ``timezone`` (America/Sao_Paulo); '' = not read (see due_state for why).
DETAIL_FIELDS = ('open_at', 'due_at', 'cutoff_at', 'close_at', 'due_raw', 'due_state', 'submission_state',
                 'grading_state', 'attempt_state')
_MODULE_UID = re.compile(r'moodle:course:([1-9][0-9]{0,9}):module:([1-9][0-9]{0,9})')
_CODE = re.compile(r'[a-z_]{1,40}')

MIGRATIONS = {
    1: (
        '''CREATE TABLE companion_runs (
            id INTEGER PRIMARY KEY,
            received_at TEXT NOT NULL,
            generated_at TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'companion',
            course_uid TEXT NOT NULL DEFAULT '',
            course_name TEXT NOT NULL DEFAULT '',
            section_uid TEXT NOT NULL DEFAULT '',
            section_name TEXT NOT NULL DEFAULT '',
            route TEXT NOT NULL DEFAULT '',
            coverage TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL CHECK (status IN ('ok', 'erro')),
            items INTEGER NOT NULL DEFAULT 0,
            novos INTEGER NOT NULL DEFAULT 0,
            alterados INTEGER NOT NULL DEFAULT 0,
            ausentes INTEGER NOT NULL DEFAULT 0,
            reaparecidos INTEGER NOT NULL DEFAULT 0,
            inalterados INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT ''
        )''',
        '''CREATE TABLE companion_items (
            uid TEXT PRIMARY KEY,
            course_uid TEXT NOT NULL,
            section_uid TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            assessment TEXT NOT NULL DEFAULT '',
            submission TEXT NOT NULL DEFAULT 'desconhecido',
            first_run INTEGER NOT NULL REFERENCES companion_runs(id),
            last_seen_run INTEGER NOT NULL REFERENCES companion_runs(id),
            last_seen_at TEXT NOT NULL,
            present INTEGER NOT NULL DEFAULT 1,
            missing_since_run INTEGER
        )''',
        '''CREATE TABLE companion_changes (
            id INTEGER PRIMARY KEY,
            run INTEGER NOT NULL REFERENCES companion_runs(id),
            uid TEXT NOT NULL,
            change TEXT NOT NULL CHECK (change IN ('novo', 'titulo', 'tipo', 'grupo', 'secao', 'ausente', 'reapareceu')),
            old TEXT NOT NULL DEFAULT '',
            new TEXT NOT NULL DEFAULT ''
        )''',
        'CREATE INDEX companion_items_section ON companion_items(section_uid, present)',
        'CREATE INDEX companion_changes_run ON companion_changes(run)',
    ),
    2: (
        '''CREATE TABLE companion_details (
            uid TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            verified_at TEXT NOT NULL DEFAULT '',          -- last SUCCESSFUL reading of the page ('' = never)
            verified_run INTEGER REFERENCES companion_runs(id),
            open_at TEXT NOT NULL DEFAULT '',
            due_at TEXT NOT NULL DEFAULT '',
            cutoff_at TEXT NOT NULL DEFAULT '',
            close_at TEXT NOT NULL DEFAULT '',
            due_raw TEXT NOT NULL DEFAULT '',              -- visible text when the main date could not be interpreted
            due_state TEXT NOT NULL DEFAULT 'nao_verificado',
            submission_state TEXT NOT NULL DEFAULT 'desconhecido',
            grading_state TEXT NOT NULL DEFAULT 'desconhecido',
            attempt_state TEXT NOT NULL DEFAULT 'desconhecido',
            timezone TEXT NOT NULL DEFAULT 'America/Sao_Paulo',
            last_check_at TEXT NOT NULL DEFAULT '',        -- last attempt, successful or not
            last_check_run INTEGER REFERENCES companion_runs(id),
            last_check_result TEXT NOT NULL DEFAULT ''
        )''',
        '''CREATE TABLE companion_detail_history (
            id INTEGER PRIMARY KEY,
            run INTEGER NOT NULL REFERENCES companion_runs(id),
            uid TEXT NOT NULL,
            verified_at TEXT NOT NULL,
            open_at TEXT NOT NULL DEFAULT '',
            due_at TEXT NOT NULL DEFAULT '',
            cutoff_at TEXT NOT NULL DEFAULT '',
            close_at TEXT NOT NULL DEFAULT '',
            due_raw TEXT NOT NULL DEFAULT '',
            due_state TEXT NOT NULL DEFAULT 'nao_verificado',
            submission_state TEXT NOT NULL DEFAULT 'desconhecido',
            grading_state TEXT NOT NULL DEFAULT 'desconhecido',
            attempt_state TEXT NOT NULL DEFAULT 'desconhecido'
        )''',
        'CREATE INDEX companion_detail_history_uid ON companion_detail_history(uid, id)',
    ),
}


def _detail_values(record) -> dict:
    """The stored fields of one successfully read activity page."""
    from .deadlines import main_kind
    by_kind = {}
    for deadline in record.deadlines:
        by_kind.setdefault(deadline.kind, deadline)
    at = lambda kind: by_kind[kind].at if kind in by_kind else ''       # noqa: E731
    main = by_kind.get(main_kind(record.kind))
    d = record.detail
    return dict(open_at=at('abertura'), due_at=at('entrega'), cutoff_at=at('limite'), close_at=at('fechamento'),
                due_raw=main.raw if main is not None and not main.at else '', due_state=d.due_state,
                submission_state=d.submission_state, grading_state=d.grading_state, attempt_state=d.attempt_state)


class StoreError(RuntimeError):
    """A reading could not be stored. ``code`` is a fixed identifier; nothing from the page."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SaveResult:
    run: int
    itens: int
    novos: int
    alterados: int
    ausentes: int
    reaparecidos: int
    inalterados: int

    def as_reply(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class SnapshotStore:
    def __init__(self, path, *, allowed_courses, connect=None, backup_before_upgrade=None):
        self.path = Path(path)
        self.allowed = {contract.course_uid(str(c)) for c in allowed_courses}
        self._connect = connect or (lambda: sqlite3.connect(self.path, timeout=20, isolation_level=None))
        self.backup_folder = Path(backup_before_upgrade) if backup_before_upgrade else None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    # --- schema ---------------------------------------------------------------------------------------
    def _stored_version(self) -> int:
        if not self.path.is_file():
            return 0
        with closing(sqlite3.connect(f'{self.path.resolve().as_uri()}?mode=ro', uri=True, timeout=20)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'companion_meta'").fetchone():
                return 0
            row = db.execute("SELECT value FROM companion_meta WHERE key = 'schema_version'").fetchone()
            return int(row[0]) if row else 0

    def migrate(self) -> int:
        # An EXISTING Companion schema older than this code is copied (verified backup) before it is upgraded; if
        # the copy fails, nothing is migrated. A new database (version 0) has nothing to protect.
        if self.backup_folder is not None and 0 < self._stored_version() < SCHEMA_VERSION:
            try:
                backup_database(self.path, self.backup_folder)
            except (StoreError, sqlite3.Error, OSError):
                raise StoreError('backup_antes_da_migracao_falhou') from None
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute('CREATE TABLE IF NOT EXISTS companion_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                row = db.execute("SELECT value FROM companion_meta WHERE key = 'schema_version'").fetchone()
                version = int(row[0]) if row else 0
                if version > SCHEMA_VERSION:
                    raise StoreError('versao_banco_futura')     # never downgrade a newer schema
                for target in range(version + 1, SCHEMA_VERSION + 1):
                    for statement in MIGRATIONS[target]:
                        db.execute(statement)
                db.execute("INSERT OR REPLACE INTO companion_meta(key, value) VALUES ('schema_version', ?)",
                           (str(SCHEMA_VERSION),))
                db.execute('COMMIT')
            except BaseException:
                db.execute('ROLLBACK')
                raise
        return SCHEMA_VERSION

    # --- validation -----------------------------------------------------------------------------------
    def _check(self, snapshot):
        if not isinstance(snapshot, contract.Snapshot):
            raise StoreError('snapshot_invalido')
        if len(snapshot.courses) != 1 or snapshot.courses[0].uid not in self.allowed:
            raise StoreError('disciplina_nao_autorizada')
        course = snapshot.courses[0]
        if len(snapshot.sections) != 1:
            raise StoreError('secao_ambigua')          # a Companion reading is exactly one section
        section = snapshot.sections[0]
        items = [*snapshot.materials, *snapshot.activities]
        for record in items:
            match = _MODULE_UID.fullmatch(record.uid)
            if (not match or match.group(1) != course.moodle_id or record.course_uid != course.uid
                    or record.section_uid != section.uid or not record.title.strip()):
                raise StoreError('identificador_invalido')
        return course, section, items

    # --- writes ---------------------------------------------------------------------------------------
    def save(self, snapshot, *, received_at: str | None = None) -> SaveResult:
        """Store one reading and compare it with what is known. All or nothing."""
        course, section, items = self._check(snapshot)
        received = received_at or _now()
        route = items[0].provenance.route if items else section.provenance.route
        counts = dict(novos=0, alterados=0, ausentes=0, reaparecidos=0, inalterados=0)
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                run = db.execute(
                    '''INSERT INTO companion_runs(received_at, generated_at, source, course_uid, course_name,
                       section_uid, section_name, route, coverage, status, items)
                       VALUES (?, ?, 'companion', ?, ?, ?, ?, ?, ?, 'ok', ?)''',
                    (received, snapshot.generated_at, course.uid, course.name, section.uid, section.name, route,
                     snapshot.coverage.state, len(items))).lastrowid

                def change(uid, kind, old='', new=''):
                    db.execute('INSERT INTO companion_changes(run, uid, change, old, new) VALUES (?, ?, ?, ?, ?)',
                               (run, uid, kind, old, new))

                seen = set()
                for record in items:
                    seen.add(record.uid)
                    submission = getattr(record, 'submission', 'desconhecido')
                    detail = getattr(record, 'detail', None)
                    self._store_detail(db, run, record, detail)
                    previous = db.execute(
                        '''SELECT kind, title, assessment, section_uid, present, submission FROM companion_items
                           WHERE uid = ?''', (record.uid,)).fetchone()
                    if previous is None:
                        db.execute(
                            '''INSERT INTO companion_items(uid, course_uid, section_uid, kind, title, assessment,
                               submission, first_run, last_seen_run, last_seen_at, present)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)''',
                            (record.uid, course.uid, section.uid, record.kind, record.title, record.assessment,
                             submission, run, run, received))
                        change(record.uid, 'novo', '', record.title)
                        counts['novos'] += 1
                        continue
                    old_kind, old_title, old_group, old_section, present, old_submission = previous
                    if detail is None or detail.result != 'ok':
                        submission = old_submission    # a page not read (or failed) never erases what was known
                    diffs = [(name, old, new) for name, old, new in (
                        ('titulo', old_title, record.title), ('tipo', old_kind, record.kind),
                        ('grupo', old_group, record.assessment), ('secao', old_section, section.uid)) if old != new]
                    for name, old, new in diffs:
                        change(record.uid, name, old, new)
                    if not present:
                        change(record.uid, 'reapareceu')
                        counts['reaparecidos'] += 1
                    if diffs:
                        counts['alterados'] += 1
                    elif present:
                        counts['inalterados'] += 1
                    db.execute(
                        '''UPDATE companion_items SET section_uid = ?, kind = ?, title = ?, assessment = ?,
                           submission = ?, last_seen_run = ?, last_seen_at = ?, present = 1, missing_since_run = NULL
                           WHERE uid = ?''',
                        (section.uid, record.kind, record.title, record.assessment, submission, run, received,
                         record.uid))

                # Known items of THIS section that were not in this reading: absent here, not deleted.
                for (uid,) in db.execute('SELECT uid FROM companion_items WHERE section_uid = ? AND present = 1',
                                         (section.uid,)).fetchall():
                    if uid not in seen:
                        db.execute('UPDATE companion_items SET present = 0, missing_since_run = ? WHERE uid = ?',
                                   (run, uid))
                        change(uid, 'ausente')
                        counts['ausentes'] += 1

                db.execute('''UPDATE companion_runs SET novos = ?, alterados = ?, ausentes = ?, reaparecidos = ?,
                              inalterados = ? WHERE id = ?''',
                           (counts['novos'], counts['alterados'], counts['ausentes'], counts['reaparecidos'],
                            counts['inalterados'], run))
                db.execute('COMMIT')
            except BaseException:
                db.execute('ROLLBACK')
                raise
        return SaveResult(run=run, itens=len(items), **counts)

    @staticmethod
    def _store_detail(db, run, record, detail) -> None:
        """Inside the reading's transaction. A failed page only records the attempt: known values are kept."""
        if detail is None:
            return
        current = db.execute(f'SELECT {", ".join(DETAIL_FIELDS)}, verified_at FROM companion_details WHERE uid = ?',
                             (record.uid,)).fetchone()
        if detail.result != 'ok':
            if current is None:
                db.execute('''INSERT INTO companion_details(uid, kind, timezone, last_check_at, last_check_run,
                              last_check_result) VALUES (?, ?, ?, ?, ?, ?)''',
                           (record.uid, record.kind, detail.timezone, detail.checked_at, run, detail.result))
            else:
                db.execute('''UPDATE companion_details SET last_check_at = ?, last_check_run = ?, last_check_result = ?
                              WHERE uid = ?''', (detail.checked_at, run, detail.result, record.uid))
            return
        values = _detail_values(record)
        known = current is not None and current[-1] != ''
        if not known or tuple(current[:-1]) != tuple(values[f] for f in DETAIL_FIELDS):
            db.execute(f'''INSERT INTO companion_detail_history(run, uid, verified_at, {", ".join(DETAIL_FIELDS)})
                           VALUES (?, ?, ?, {", ".join("?" * len(DETAIL_FIELDS))})''',
                       (run, record.uid, detail.checked_at, *(values[f] for f in DETAIL_FIELDS)))
        assignments = ', '.join(f'{f} = ?' for f in DETAIL_FIELDS)
        params = (*(values[f] for f in DETAIL_FIELDS), detail.checked_at, run, detail.timezone, detail.checked_at, run)
        if current is None:
            db.execute(f'''INSERT INTO companion_details(uid, kind, {", ".join(DETAIL_FIELDS)}, verified_at, verified_run,
                           timezone, last_check_at, last_check_run, last_check_result)
                           VALUES (?, ?, {", ".join("?" * len(DETAIL_FIELDS))}, ?, ?, ?, ?, ?, 'ok')''',
                       (record.uid, record.kind, *params))
        else:
            db.execute(f'''UPDATE companion_details SET {assignments}, verified_at = ?, verified_run = ?, timezone = ?,
                           last_check_at = ?, last_check_run = ?, last_check_result = 'ok', kind = ? WHERE uid = ?''',
                       (*params, record.kind, record.uid))

    def details(self, uid: str | None = None):
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            if uid:
                row = db.execute('SELECT * FROM companion_details WHERE uid = ?', (uid,)).fetchone()
                return dict(row) if row else None
            return [dict(r) for r in db.execute('SELECT * FROM companion_details ORDER BY uid')]

    def detail_history(self, uid: str):
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute('SELECT * FROM companion_detail_history WHERE uid = ? ORDER BY id', (uid,))]

    def record_failure(self, code: str, *, received_at: str | None = None) -> bool:
        """Best effort: a failed sync is listed with a fixed code only. Returns False if even this fails."""
        code = code if isinstance(code, str) and _CODE.fullmatch(code) else 'erro_desconhecido'
        try:
            with closing(self._connect()) as db:
                db.execute("INSERT INTO companion_runs(received_at, status, error) VALUES (?, 'erro', ?)",
                           (received_at or _now(), code))
            return True
        except (sqlite3.Error, OSError):
            return False

    # --- reads ----------------------------------------------------------------------------------------
    def changes(self, run: int):
        with closing(self._connect()) as db:
            return db.execute('SELECT uid, change, old, new FROM companion_changes WHERE run = ? ORDER BY id',
                              (run,)).fetchall()

    def items(self, section_uid: str | None = None):
        query = 'SELECT uid, kind, title, assessment, submission, present FROM companion_items'
        with closing(self._connect()) as db:
            if section_uid:
                return db.execute(query + ' WHERE section_uid = ? ORDER BY uid', (section_uid,)).fetchall()
            return db.execute(query + ' ORDER BY uid').fetchall()

    def summary(self) -> dict:
        with closing(self._connect()) as db:
            return _summary(db)


def _summary(db) -> dict:
    db.row_factory = sqlite3.Row
    last = db.execute("SELECT * FROM companion_runs WHERE status = 'ok' ORDER BY id DESC LIMIT 1").fetchone()
    error = db.execute("SELECT received_at, error FROM companion_runs WHERE status = 'erro' "
                       'ORDER BY id DESC LIMIT 1').fetchone()
    errors = db.execute("SELECT COUNT(*) FROM companion_runs WHERE status = 'erro'").fetchone()[0]
    present = absent = 0
    if last:
        present, absent = db.execute(
            'SELECT COALESCE(SUM(present = 1), 0), COALESCE(SUM(present = 0), 0) FROM companion_items '
            'WHERE section_uid = ?', (last['section_uid'],)).fetchone()
    return {'last': dict(last) if last else None, 'present': present, 'absent': absent,
            'last_error': dict(error) if error else None, 'errors': errors}


def read_summary(path) -> dict | None:
    """Read-only view for the Windows app (opened with mode=ro: the GUI never writes the database).

    None when there is no database or the Companion tables were never created (no reading received yet).
    """
    path = Path(path)
    if not path.is_file():
        return None
    with closing(sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True, timeout=5)) as db:
        has = db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'companion_runs'").fetchone()
        return _summary(db) if has else None


def backup_database(source, folder, *, now=None) -> Path:
    """Consistent copy of an SQLite file (sqlite3 backup API, source opened read-only), verified with
    ``PRAGMA integrity_check``. Never overwrites an existing backup. Used before the host is activated."""
    source = Path(source)
    folder = Path(folder)
    if not source.is_file():
        raise StoreError('banco_inexistente')
    folder.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(timezone.utc)).strftime('%Y%m%dT%H%M%SZ')
    dest = folder / f'{source.stem}-{stamp}.db'
    if dest.exists():
        raise StoreError('backup_existente')
    with closing(sqlite3.connect(f'{source.resolve().as_uri()}?mode=ro', uri=True, timeout=20)) as src, \
            closing(sqlite3.connect(dest)) as dst:
        src.backup(dst)
    with closing(sqlite3.connect(f'{dest.resolve().as_uri()}?mode=ro', uri=True)) as check:
        if check.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise StoreError('backup_invalido')
    return dest


COVERAGE_TEXT = {'parcial': 'parcial', 'completa': 'completa', 'nao_validada': 'não validada', 'falhou': 'falhou'}


def summary_text(summary: dict | None) -> str:
    """Plain-text summary for the Windows app (no claims beyond what was stored)."""
    summary = summary or {}
    lines = []
    last = summary.get('last')
    if not last:
        lines.append('Nenhuma leitura do Campus AI Companion foi recebida ainda.')
    else:
        lines += [
            f"Última leitura recebida: {last['received_at']} (leitura nº {last['id']})",
            f"Disciplina: {last['course_name']} — seção {last['section_name']}",
            f"Módulos nesta leitura: {last['items']}",
            f"Novos: {last['novos']} · Alterados: {last['alterados']} · Sem mudança: {last['inalterados']}"
            f" · Reapareceram: {last['reaparecidos']}",
            f"Ausentes nesta leitura: {last['ausentes']} (não são considerados removidos: a leitura é parcial)",
            f"Cobertura: {COVERAGE_TEXT.get(last['coverage'], last['coverage'])}",
            'Situação de entrega: desconhecida (não é lida pela extensão).',
        ]
    if summary.get('errors'):
        error = summary['last_error']
        lines.append(f"Erros de sincronização: {summary['errors']} (último: {error['error']} em {error['received_at']})")
    else:
        lines.append('Erros de sincronização: nenhum.')
    return '\n'.join(lines)


def _cli(argv=None) -> int:
    """``python -m campus_ai.companion_store backup <folder>``: back up live.db (read-only on the source)."""
    import sys
    from .config import app_dir
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 2 or args[0] != 'backup':
        print('uso: python -m campus_ai.companion_store backup <pasta-de-destino>', file=sys.stderr)
        return 2
    try:
        dest = backup_database(app_dir() / 'live.db', Path(args[1]))
    except (StoreError, sqlite3.Error, OSError) as exc:
        print(f'backup falhou: {getattr(exc, "code", exc.__class__.__name__)}', file=sys.stderr)
        return 1
    print(dest)
    return 0


if __name__ == '__main__':
    raise SystemExit(_cli())

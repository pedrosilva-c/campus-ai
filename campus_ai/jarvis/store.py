"""Jarvis local memory, conversation history, operation log and reminders.

Its own SQLite file (``jarvis.db`` in the app data folder), separate from ``live.db``: the assistant never writes
academic data. Every write is one short transaction. Nothing here talks to the network.

Privacy: a memory that looks like a secret (password, token, cookie, API key, long random string) is refused, and
the conversation never stores such text either (it is replaced by a fixed marker).
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
MAX_TEXT = 2000
KINDS = ('preferencia', 'disciplina', 'projeto', 'objetivo', 'tarefa', 'decisao', 'nota')
_SECRET_WORDS = re.compile(r'\b(senha|password|passwd|token|cookie|sesskey|chave de api|api[ _-]?key|segredo|'
                           r'secret|credencia(l|is)|pin do cartao|cvv)\b')
_SECRET_SHAPES = re.compile(r'(?<![\w/.-])[A-Za-z0-9_+/=-]{32,}(?![\w/.-])|\b\d{13,19}\b')

MIGRATIONS = {
    1: (
        '''CREATE TABLE messages (
            id INTEGER PRIMARY KEY, at TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('user', 'jarvis')),
            text TEXT NOT NULL, intent TEXT NOT NULL DEFAULT '', files TEXT NOT NULL DEFAULT '[]')''',
        '''CREATE TABLE memories (
            id INTEGER PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'usuario',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''',
        '''CREATE TABLE operations (
            id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT NOT NULL DEFAULT '', tool TEXT NOT NULL,
            arguments TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL CHECK (status IN ('executando', 'ok', 'falhou',
            'cancelado', 'aguardando_confirmacao', 'recusado')), summary TEXT NOT NULL DEFAULT '',
            files TEXT NOT NULL DEFAULT '[]')''',
        '''CREATE TABLE reminders (
            id INTEGER PRIMARY KEY, due_at TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL,
            delivered_at TEXT NOT NULL DEFAULT '', cancelled INTEGER NOT NULL DEFAULT 0, activity_uid TEXT NOT NULL DEFAULT '')''',
        '''CREATE TABLE context (key TEXT PRIMARY KEY, value TEXT NOT NULL)''',
        'CREATE INDEX reminders_due ON reminders(delivered_at, cancelled, due_at)',
    ),
}


def fold(text) -> str:
    return ''.join(ch for ch in unicodedata.normalize('NFKD', str(text or '').casefold())
                   if not unicodedata.combining(ch))


def looks_secret(text: str) -> bool:
    """True for anything that may be a credential. Conservative on purpose."""
    return bool(_SECRET_WORDS.search(fold(text)) or _SECRET_SHAPES.search(str(text or '')))


def redact(text: str) -> str:
    return '[conteúdo omitido: parecia um dado sigiloso]' if looks_secret(text) else text


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@dataclass(frozen=True)
class Memory:
    id: int
    kind: str
    text: str
    source: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Reminder:
    id: int
    due_at: str          # aware ISO (UTC)
    text: str
    activity_uid: str


class SecretRefused(ValueError):
    """The text looks like a credential: it is not stored."""


class JarvisStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                row = db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
                version = int(row[0]) if row else 0
                if version > SCHEMA_VERSION:
                    raise RuntimeError('versao_banco_futura')
                for target in range(version + 1, SCHEMA_VERSION + 1):
                    for statement in MIGRATIONS[target]:
                        db.execute(statement)
                db.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
                db.execute('COMMIT')
            except BaseException:
                db.execute('ROLLBACK')
                raise

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def _write(self, sql, params=()):
        with closing(self._connect()) as db:
            return db.execute(sql, params).lastrowid

    # --- conversation ---------------------------------------------------------------------------------------------
    def add_message(self, role: str, text: str, *, intent: str = '', files=()) -> int:
        return self._write('INSERT INTO messages(at, role, text, intent, files) VALUES (?, ?, ?, ?, ?)',
                           (now_iso(), role, redact(str(text))[:MAX_TEXT * 4], intent, json.dumps([str(f) for f in files])))

    def messages(self, limit: int = 200):
        with closing(self._connect()) as db:
            rows = db.execute('SELECT * FROM messages ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [dict(r, files=json.loads(r['files'])) for r in reversed(rows)]

    # --- memory ---------------------------------------------------------------------------------------------------
    def remember(self, text: str, kind: str = 'nota', source: str = 'usuario') -> Memory:
        text = ' '.join(str(text or '').split())[:MAX_TEXT]
        if not text:
            raise ValueError('vazio')
        if looks_secret(text):
            raise SecretRefused('sigiloso')
        kind = kind if kind in KINDS else 'nota'
        stamp = now_iso()
        new_id = self._write('INSERT INTO memories(kind, text, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
                             (kind, text, source, stamp, stamp))
        return self.memory(new_id)

    def memory(self, memory_id: int) -> Memory | None:
        with closing(self._connect()) as db:
            row = db.execute('SELECT * FROM memories WHERE id = ?', (memory_id,)).fetchone()
        return Memory(**dict(row)) if row else None

    def memories(self, query: str = '') -> list[Memory]:
        with closing(self._connect()) as db:
            rows = [Memory(**dict(r)) for r in db.execute('SELECT * FROM memories ORDER BY id')]
        words = [w for w in fold(query).split() if len(w) > 2]
        if not words:
            return rows
        return [m for m in rows if any(w in fold(m.text) for w in words)]

    def correct(self, memory_id: int, text: str) -> Memory | None:
        text = ' '.join(str(text or '').split())[:MAX_TEXT]
        if looks_secret(text):
            raise SecretRefused('sigiloso')
        with closing(self._connect()) as db:
            changed = db.execute('UPDATE memories SET text = ?, updated_at = ? WHERE id = ?',
                                 (text, now_iso(), memory_id)).rowcount
        return self.memory(memory_id) if changed else None

    def forget(self, memory_id: int) -> bool:
        with closing(self._connect()) as db:
            return db.execute('DELETE FROM memories WHERE id = ?', (memory_id,)).rowcount == 1

    # --- operations log -------------------------------------------------------------------------------------------
    def start_operation(self, tool: str, arguments: dict) -> int:
        safe = {k: redact(str(v))[:300] for k, v in (arguments or {}).items()}
        return self._write("INSERT INTO operations(started_at, tool, arguments, status) VALUES (?, ?, ?, 'executando')",
                           (now_iso(), tool, json.dumps(safe, ensure_ascii=False)))

    def finish_operation(self, op_id: int, status: str, summary: str = '', files=()) -> None:
        self._write('UPDATE operations SET finished_at = ?, status = ?, summary = ?, files = ? WHERE id = ?',
                    (now_iso(), status, redact(summary)[:MAX_TEXT], json.dumps([str(f) for f in files]), op_id))

    def operations(self, limit: int = 50):
        with closing(self._connect()) as db:
            rows = db.execute('SELECT * FROM operations ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [dict(r, files=json.loads(r['files']), arguments=json.loads(r['arguments'])) for r in rows]

    def recover_interrupted(self) -> int:
        """After a crash, operations left 'executando' are marked as failed (never silently 'ok')."""
        with closing(self._connect()) as db:
            return db.execute("UPDATE operations SET status = 'falhou', finished_at = ?, summary = "
                              "'interrompida (o aplicativo foi fechado durante a execução)' WHERE status = 'executando'",
                              (now_iso(),)).rowcount

    # --- reminders ------------------------------------------------------------------------------------------------
    def add_reminder(self, due: datetime, text: str, activity_uid: str = '') -> Reminder:
        if due.tzinfo is None:
            raise ValueError('horário sem fuso')
        text = redact(' '.join(str(text).split()))[:300]
        due_iso = due.astimezone(timezone.utc).isoformat(timespec='seconds')
        rid = self._write('INSERT INTO reminders(due_at, text, created_at, activity_uid) VALUES (?, ?, ?, ?)',
                          (due_iso, text, now_iso(), activity_uid))
        return Reminder(rid, due_iso, text, activity_uid)

    def pending_reminders(self):
        with closing(self._connect()) as db:
            rows = db.execute("SELECT id, due_at, text, activity_uid FROM reminders WHERE delivered_at = '' AND cancelled = 0 "
                              'ORDER BY due_at').fetchall()
        return [Reminder(**dict(r)) for r in rows]

    def due_reminders(self, now: datetime):
        return [r for r in self.pending_reminders() if datetime.fromisoformat(r.due_at) <= now]

    def mark_delivered(self, reminder_id: int) -> None:
        self._write('UPDATE reminders SET delivered_at = ? WHERE id = ?', (now_iso(), reminder_id))

    def cancel_reminder(self, reminder_id: int) -> bool:
        with closing(self._connect()) as db:
            return db.execute("UPDATE reminders SET cancelled = 1 WHERE id = ? AND delivered_at = ''",
                              (reminder_id,)).rowcount == 1

    # --- short-term context (e.g. "essa atividade") ---------------------------------------------------------------
    def set_context(self, key: str, value) -> None:
        self._write('INSERT OR REPLACE INTO context(key, value) VALUES (?, ?)', (key, json.dumps(value, ensure_ascii=False)))

    def context(self, key: str, default=None):
        with closing(self._connect()) as db:
            row = db.execute('SELECT value FROM context WHERE key = ?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

"""SQLite idempotent scan history; no credential content."""
from __future__ import annotations
import sqlite3
from contextlib import closing
from pathlib import Path
from .models import AcademicItem


class History:
    def __init__(self, filename: Path):
        self.filename = filename
        filename.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn:
            with conn:
                conn.execute('''CREATE TABLE IF NOT EXISTS items (
                    uid TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                    last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )''')
                conn.execute('''CREATE TABLE IF NOT EXISTS alerts (
                    uid TEXT PRIMARY KEY, first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )''')
                conn.execute('''CREATE TABLE IF NOT EXISTS scan_runs (
                    id INTEGER PRIMARY KEY, scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    item_count INTEGER NOT NULL, changed_count INTEGER NOT NULL,
                    warning_count INTEGER NOT NULL
                )''')
                conn.execute('''CREATE TABLE IF NOT EXISTS moodle_scans (
                    id INTEGER PRIMARY KEY, scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    complete INTEGER NOT NULL, item_count INTEGER NOT NULL
                )''')
                conn.execute('''CREATE TABLE IF NOT EXISTS notification_history (
                    event_key TEXT PRIMARY KEY, kind TEXT NOT NULL, message TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )''')

    def connect(self):
        return sqlite3.connect(self.filename, timeout=20)

    def changed(self, item: AcademicItem) -> bool:
        with closing(self.connect()) as db:
            row = db.execute('SELECT fingerprint FROM items WHERE uid=?', (item.uid,)).fetchone()
        return row is None or row[0] != item.fingerprint()

    def has_uid(self, uid: str) -> bool:
        with closing(self.connect()) as db:
            return db.execute('SELECT 1 FROM items WHERE uid=?', (uid,)).fetchone() is not None

    def remember(self, item: AcademicItem):
        with closing(self.connect()) as db:
            with db:
                db.execute('''INSERT INTO items(uid, fingerprint) VALUES (?, ?)
                    ON CONFLICT(uid) DO UPDATE SET fingerprint=excluded.fingerprint,
                    last_seen=CURRENT_TIMESTAMP''', (item.uid, item.fingerprint()))

    def alert_seen(self, uid: str) -> bool:
        with closing(self.connect()) as db:
            return db.execute('SELECT 1 FROM alerts WHERE uid=?', (uid,)).fetchone() is not None

    def remember_alert(self, uid: str) -> None:
        with closing(self.connect()) as db:
            with db:
                db.execute('INSERT OR IGNORE INTO alerts(uid) VALUES (?)', (uid,))

    def record_scan(self, item_count: int, changed_count: int, warning_count: int) -> None:
        with closing(self.connect()) as db:
            with db:
                db.execute('''INSERT INTO scan_runs(item_count, changed_count, warning_count)
                              VALUES (?, ?, ?)''', (item_count, changed_count, warning_count))

    def last_scan_at(self) -> str:
        with closing(self.connect()) as db:
            row = db.execute('SELECT scanned_at FROM scan_runs ORDER BY id DESC LIMIT 1').fetchone()
        return row[0] if row else ''

    def record_moodle_scan(self, complete: bool, item_count: int) -> None:
        with closing(self.connect()) as db:
            with db:
                db.execute('INSERT INTO moodle_scans(complete, item_count) VALUES (?, ?)',
                           (int(complete), item_count))

    def last_moodle_scan(self) -> tuple[str, bool] | None:
        with closing(self.connect()) as db:
            row = db.execute('SELECT scanned_at, complete FROM moodle_scans ORDER BY id DESC LIMIT 1').fetchone()
        return (row[0], bool(row[1])) if row else None

    def add_alert(self, event_key: str, kind: str, message: str) -> bool:
        with closing(self.connect()) as db:
            with db:
                cursor = db.execute('''INSERT OR IGNORE INTO notification_history(event_key, kind, message)
                                       VALUES (?, ?, ?)''', (event_key, kind, message[:1000]))
                return cursor.rowcount == 1

    def recent_alerts(self, limit=30):
        with closing(self.connect()) as db:
            return db.execute('''SELECT created_at, kind, message FROM notification_history
                                 ORDER BY rowid DESC LIMIT ?''', (int(limit),)).fetchall()

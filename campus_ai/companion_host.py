"""Chrome Native Messaging host of the Campus AI Companion: ``python -m campus_ai.companion_host``.

NOT registered in Windows yet (HKCU untouched). Chrome would start it as the current user when the popup's
"Salvar no Campus AI" opens a port; it serves one hello and one report, then exits.

* The caller origin is checked BEFORE anything else (including the database): only the Companion id.
* Courses come from the local authorized list (today only 7653).
* A report is acknowledged as saved only after the SQLite COMMIT (companion_store.SnapshotStore).
* stdout carries protocol frames only; nothing is printed or logged (no titles, ids or snapshots).
* A watchdog ends the process if Chrome keeps the pipe open without finishing (timeout).
"""
from __future__ import annotations

import os
import sqlite3
import sys
import threading
from pathlib import Path

from . import authorized_courses
from .companion_protocol import COMPANION_EXTENSION_ID, ProtocolError, caller_origin, run_host
from .companion_store import SnapshotStore, StoreError
from .config import app_dir

MAX_LIFETIME_S = 60
EXIT_TIMEOUT = 4


REGISTRY_KEY = r'Software\Google\Chrome\NativeMessagingHosts\br.campus_ai.companion'


def registration_status() -> str:
    """'registrado' | 'nao_registrado' | 'indisponivel' — READ-ONLY look at HKCU (never writes)."""
    try:
        import winreg
    except ImportError:
        return 'indisponivel'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, winreg.KEY_READ):
            return 'registrado'
    except FileNotFoundError:
        return 'nao_registrado'
    except OSError:
        return 'indisponivel'


def _binary_stdio():
    """Native Messaging frames are binary: make sure Windows never translates CR/LF or stops at Ctrl-Z.
    (Python 3 already uses binary buffers; this is a defensive, explicit no-op elsewhere.)"""
    if sys.platform != 'win32':
        return
    import msvcrt
    for stream in (sys.stdin, sys.stdout):
        try:
            msvcrt.setmode(stream.fileno(), os.O_BINARY)
        except (OSError, ValueError, AttributeError):
            pass


def _hard_exit():
    os._exit(EXIT_TIMEOUT)      # the pipe is stuck: leave without touching stdout


def main(argv=None, stdin=None, stdout=None, *, db_path=None, courses=None, timer=threading.Timer,
         token_factory=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if stdin is None or stdout is None:
        _binary_stdio()
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer
    try:
        caller_origin(argv, {COMPANION_EXTENSION_ID})
    except ProtocolError:
        return 1                                   # unknown caller: nothing opened, nothing read
    watchdog = timer(MAX_LIFETIME_S, _hard_exit)
    watchdog.daemon = True
    watchdog.start()
    try:
        allowed = list(courses) if courses is not None else [c.course_id for c in authorized_courses.load()]
        try:
            # v0.5.4: an older schema is backed up (verified) next to the installer's backups before it is upgraded.
            local = os.environ.get('LOCALAPPDATA', '')
            backups = Path(local) / 'CampusAI-Companion' / 'backup' if local and not db_path else None
            store = SnapshotStore(db_path or (app_dir() / 'live.db'), allowed_courses=allowed,
                                  backup_before_upgrade=backups)
        except (StoreError, sqlite3.Error, OSError):
            store = None

        def sink(snapshot):
            if store is None:
                raise StoreError('banco_indisponivel')
            try:
                return store.save(snapshot)
            except StoreError:
                raise
            except PermissionError:
                raise StoreError('sem_permissao') from None
            except (sqlite3.Error, OSError):
                raise StoreError('falha_persistencia') from None

        def on_reject(code):
            if store is not None:
                store.record_failure(code)

        return run_host(argv, stdin, stdout, allowed_extension_ids={COMPANION_EXTENSION_ID},
                        allowed_courses=allowed, sink=sink, on_reject=on_reject, token_factory=token_factory)
    finally:
        watchdog.cancel()


if __name__ == '__main__':
    sys.exit(main())

"""Test isolation: automated tests must never read, write or reach the student's REAL Campus AI data.

Why: on 06/11/2026 a test sent a fake snapshot through the registered Native Messaging host and the host
wrote an error row into the real live.db. Layers now in place:

1. ``install()`` points LOCALAPPDATA at a throw-away folder BEFORE any test runs (imported by
   tests/__init__.py for ``python -m unittest tests.x`` and by test_000_isolation.py for
   ``unittest discover -s tests``). Everything that resolves the data folder at call time
   (config.app_dir, the instance lock, the host, the store) and every child process (Chromium, node, cmd,
   a host started by a browser) inherits it, so even a registered host would write into the throw-away copy.
2. The signature of the real files/registry value is recorded at that moment and test_zzz_real_data_untouched.py
   (last module) fails the run if anything changed.
3. test_000_isolation.py checks the redirection, the host's default database path, forbids tests from naming
   the real folder, from running PowerShell scripts, and keeps the regression guard of the incident.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

REAL = 'CAMPUS_AI_TESTS_REAL_LOCALAPPDATA'
FAKE = 'CAMPUS_AI_TESTS_FAKE_LOCALAPPDATA'
SIGNATURE = 'CAMPUS_AI_TESTS_REAL_SIGNATURE'
HOST_KEY = r'Software\Google\Chrome\NativeMessagingHosts\br.campus_ai.companion'
WATCHED = ('CampusAI/live.db', 'CampusAI/demo.db', 'CampusAI/config.json', 'CampusAI/authorized_courses.json')


def real_local_appdata() -> str:
    """The student's real LOCALAPPDATA as it was before the redirection ('' if install() never ran)."""
    return os.environ.get(REAL, '')


def _file(path: Path):
    try:
        data = path.read_bytes()
        return [len(data), path.stat().st_mtime_ns, hashlib.sha256(data).hexdigest()]
    except OSError:
        return None


def real_signature() -> dict:
    """Read-only fingerprint of the real data that tests must never change."""
    base = Path(real_local_appdata()) if real_local_appdata() else None
    out = {rel: (_file(base / rel) if base else None) for rel in WATCHED}
    host = base / 'CampusAI-Companion' if base else None
    out['CampusAI-Companion'] = sorted(
        [str(p.relative_to(host)), p.stat().st_size, p.stat().st_mtime_ns] for p in host.rglob('*') if p.is_file()
    ) if host and host.is_dir() else None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, HOST_KEY, 0, winreg.KEY_READ) as key:
            out['HKCU-host'] = winreg.QueryValueEx(key, '')[0]
    except (ImportError, OSError):
        out['HKCU-host'] = None
    return out


def install() -> None:
    """Idempotent: redirect LOCALAPPDATA once, record the real signature first."""
    real = os.environ.get(REAL) or os.environ.get('LOCALAPPDATA', '')
    os.environ[REAL] = real
    if os.environ.get('LOCALAPPDATA', '') != real:
        return                                          # already redirected (another import of this module)
    os.environ[SIGNATURE] = json.dumps(real_signature(), sort_keys=True)
    fake = tempfile.mkdtemp(prefix='campusai-tests-')
    os.environ[FAKE] = fake
    os.environ['LOCALAPPDATA'] = fake
    atexit.register(shutil.rmtree, fake, ignore_errors=True)


def recorded_signature() -> dict:
    return json.loads(os.environ.get(SIGNATURE, 'null') or 'null')

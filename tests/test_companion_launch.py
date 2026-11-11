"""Windows launch of the host EXACTLY as the install script would configure it, without installing it.

The .cmd launcher is generated from the template inside scripts/instalar_companion_host.ps1 and started the
way Chrome starts a .cmd host (cmd.exe /d /c "<launcher>" <origin> --parent-window=0), with binary pipes and
an interactive hello -> welcome(token) -> page_report -> ack conversation. LOCALAPPDATA points to a temporary
folder, so the real live.db is never touched; nothing is registered. Also: live.db backup before activation.
"""
import json
import os
import re
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolation  # noqa: E402
from companion_snapshots import snapshot, snapshot_dict  # noqa: E402

from campus_ai import companion_protocol as cp  # noqa: E402
from campus_ai.companion_store import SnapshotStore, StoreError, backup_database  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / 'scripts' / 'instalar_companion_host.ps1'
PYTHON = ROOT / '.venv' / 'Scripts' / 'python.exe'
ORIGIN = f'chrome-extension://{cp.COMPANION_EXTENSION_ID}/'


def launcher_text() -> str:
    """The $LauncherText template of the install script, with PowerShell escapes and variables resolved."""
    script = INSTALL.read_text(encoding='utf-8-sig')
    template = re.search(r'^\$LauncherText = "(.*)"$', script, re.M).group(1)
    text = template.replace('`r`n', '\r\n').replace('`"', '"')
    return text.replace('$Project', str(ROOT)).replace('$Python', str(PYTHON))


def frame(obj) -> bytes:
    raw = json.dumps(obj).encode('utf-8')
    return struct.pack('<I', len(raw)) + raw


def read_frame(stream):
    header = stream.read(4)
    if len(header) < 4:
        return None
    return json.loads(stream.read(struct.unpack('<I', header)[0]))


@unittest.skipUnless(sys.platform == 'win32' and PYTHON.is_file(), 'Lançamento real só no Windows com a .venv')
class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / '.tmp-campus-ai')
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / 'LocalAppData'
        self.data.mkdir()
        self.launcher = Path(self.tmp.name) / 'campus_ai_companion_host.cmd'
        self.launcher.write_bytes(launcher_text().encode('ascii'))
        self.real_db = Path(_isolation.real_local_appdata()) / 'CampusAI' / 'live.db'
        self.real_mtime = self.real_db.stat().st_mtime_ns if self.real_db.is_file() else None

    def tearDown(self):
        if self.real_mtime is not None:
            self.assertEqual(self.real_db.stat().st_mtime_ns, self.real_mtime, 'the real live.db was touched')

    def start(self, origin=ORIGIN):
        env = dict(os.environ, LOCALAPPDATA=str(self.data))
        command = f'cmd.exe /d /c ""{self.launcher}" {origin} --parent-window=0"'
        return subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=env, cwd=self.tmp.name)

    def test_launcher_template_is_what_chrome_would_start(self):
        text = launcher_text()
        self.assertTrue(text.startswith('@echo off\r\ncd /d "'))
        self.assertIn(f'"{PYTHON}" -E -s -m campus_ai.companion_host %*', text)

    def test_full_conversation_through_cmd_and_binary_pipes(self):
        process = self.start()
        try:
            process.stdin.write(frame({'protocol': cp.PROTOCOL_ID, 'type': 'hello', 'request_id': 'req-00000001',
                                       'session': '', 'payload': {'extension_version': '0.3.0',
                                                                  'capabilities': ['page_report']}}))
            process.stdin.flush()
            welcome = read_frame(process.stdout)
            self.assertEqual(welcome['type'], 'welcome')
            self.assertRegex(welcome['session'], r'^[0-9a-f]{32}$')        # real random token
            process.stdin.write(frame({'protocol': cp.PROTOCOL_ID, 'type': 'page_report', 'request_id': 'req-00000002',
                                       'session': welcome['session'],
                                       'payload': {'page': {'kind': 'curso_inicio', 'route': '/ava/course/view.php?id'},
                                                   'snapshot': snapshot_dict()}}))
            process.stdin.flush()
            ack = read_frame(process.stdout)
            self.assertEqual(read_frame(process.stdout), None)               # nothing else on stdout
            process.stdin.close()
            self.assertEqual(process.wait(timeout=60), 0)
        finally:
            process.kill()
            process.stdout.close()
            process.stderr.close()
        self.assertEqual((ack['type'], ack['saved'], ack['result']['novos']), ('ack', True, 7))
        db = self.data / 'CampusAI' / 'live.db'                           # the TEMPORARY app data folder
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM companion_items').fetchone()[0], 7)

    def test_unknown_origin_through_cmd_is_refused_before_any_file_is_created(self):
        process = self.start('chrome-extension://' + 'b' * 32 + '/')
        out, _ = process.communicate(timeout=60)
        self.assertEqual((process.returncode, out), (1, b''))
        self.assertFalse((self.data / 'CampusAI' / 'live.db').exists())


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'live.db'

    def test_backup_is_a_consistent_verified_copy_and_never_overwrites(self):
        SnapshotStore(self.db, allowed_courses=['7653']).save(snapshot())
        before = self.db.read_bytes()
        copy = backup_database(self.db, Path(self.tmp.name) / 'backup')
        self.assertEqual(self.db.read_bytes(), before)                   # the source is only read
        with closing(sqlite3.connect(copy)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM companion_items').fetchone()[0], 7)
        with self.assertRaises(StoreError) as ctx:
            from datetime import datetime, timezone
            stamp = datetime.strptime(copy.stem.split('-')[-1], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
            backup_database(self.db, copy.parent, now=stamp)
        self.assertEqual(ctx.exception.code, 'backup_existente')
        with self.assertRaises(StoreError) as ctx:
            backup_database(Path(self.tmp.name) / 'nao-existe.db', copy.parent)
        self.assertEqual(ctx.exception.code, 'banco_inexistente')

    def test_install_script_backs_up_before_any_change_and_stops_on_failure(self):
        script = INSTALL.read_text(encoding='utf-8-sig')
        code = re.sub(r'<#.*?#>', '', script, flags=re.S)
        backup = code.index('-m campus_ai.companion_store backup $BackupDir')
        self.assertGreater(backup, code.index('if (-not $Aplicar)'))
        for change in ('New-Item', 'WriteAllText', 'Set-ItemProperty'):
            self.assertGreater(code.index(change), backup, change)
        self.assertIn("throw 'Backup do live.db falhou; nada foi registrado.'", code)
        self.assertNotRegex(code, r'Remove-Item[^\n]*LiveDb')

    def test_scripts_are_utf8_with_bom_for_windows_powershell(self):
        for name in ('instalar_companion_host.ps1', 'remover_companion_host.ps1'):
            self.assertEqual((ROOT / 'scripts' / name).read_bytes()[:3], b'\xef\xbb\xbf', name)


if __name__ == '__main__':
    unittest.main()

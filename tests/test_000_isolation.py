"""First test module imported: installs the isolation, then proves it and guards against the 06/11 incident."""
import io
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolation  # noqa: E402

_isolation.install()                   # runs at import time, before any test of any module executes

from campus_ai import companion_host, config  # noqa: E402
from campus_ai.companion_protocol import COMPANION_EXTENSION_ID  # noqa: E402

TESTS = Path(__file__).resolve().parent
ALLOWED_TO_NAME_THE_REAL_FOLDER = {'_isolation.py', 'test_000_isolation.py', 'test_zzz_real_data_untouched.py'}


class IsolationTests(unittest.TestCase):
    def test_the_data_folder_is_a_throw_away_one(self):
        real = _isolation.real_local_appdata()
        fake = os.environ[_isolation.FAKE]
        self.assertTrue(real)
        self.assertNotEqual(os.environ['LOCALAPPDATA'], real)
        self.assertEqual(os.environ['LOCALAPPDATA'], fake)
        data = config.app_dir()
        self.assertTrue(Path(data).resolve().is_relative_to(Path(fake).resolve()))
        self.assertFalse(Path(data).resolve().is_relative_to(Path(real).resolve()))

    def test_the_production_host_would_open_the_throw_away_database(self):
        seen = {}

        class Spy:
            def __init__(self, path, **kwargs):
                seen['path'] = Path(path)
                raise OSError('stop here: only the path matters')

        with patch.object(companion_host, 'SnapshotStore', Spy):
            code = companion_host.main([f'chrome-extension://{COMPANION_EXTENSION_ID}/'], io.BytesIO(b''), io.BytesIO(),
                                       timer=lambda *a: type('T', (), {'start': lambda s: None, 'cancel': lambda s: None,
                                                                       'daemon': True})())
        self.assertEqual(code, 0)
        self.assertTrue(seen['path'].resolve().is_relative_to(Path(os.environ[_isolation.FAKE]).resolve()))
        self.assertEqual(seen['path'].name, 'live.db')

    def test_a_child_process_inherits_the_redirection(self):
        import subprocess
        out = subprocess.run([sys.executable, '-c', 'import os; print(os.environ["LOCALAPPDATA"])'],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        self.assertEqual(out, os.environ[_isolation.FAKE])

    def test_no_test_names_the_real_folder_or_runs_powershell_scripts(self):
        for path in sorted(TESTS.glob('*.py')):
            code = path.read_text(encoding='utf-8')
            if path.name not in ALLOWED_TO_NAME_THE_REAL_FOLDER:
                self.assertIsNone(re.search(r"environ(\.get\(|\[)\s*['\"]LOCALAPPDATA", code),
                                  f'{path.name}: use _isolation.real_local_appdata() or the redirected folder')
                if 'winreg' in code:        # the real registry may only appear behind a mock (test_startup.py)
                    self.assertIsNotNone(re.search(r"patch\.dict\(sys\.modules,\s*\{'winreg':\s*\w+\}", code),
                                         f'{path.name}: winreg must be replaced by a mock, never used for real')
            if path.name != 'test_000_isolation.py':
                self.assertIsNone(re.search(r"subprocess[^\n]*\.ps1|['\"]powershell(\.exe)?['\"]|-Aplicar\s*['\"\]]", code),
                                  f'{path.name}: tests must never execute the install/remove scripts')

    def test_regression_guard_save_is_never_exercised_where_a_real_host_may_answer(self):
        chromium = (TESTS / 'test_companion_chromium.py').read_text(encoding='utf-8')
        self.assertIn("if (typeof chrome.runtime.connectNative === 'function') return null;", chromium)
        self.assertNotIn("host_nao_instalado'})", chromium)         # the old assertion that reached the real host

    def test_the_runner_script_exists_and_is_utf8_with_bom(self):
        runner = TESTS.parent / 'scripts' / 'executar_testes.ps1'
        self.assertEqual(runner.read_bytes()[:3], b'\xef\xbb\xbf')


if __name__ == '__main__':
    unittest.main()

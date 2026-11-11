"""Integration build, install/remove scripts (static review only: they are NEVER executed here) and the
read-only summary tab of the Windows app."""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from companion_snapshots import snapshot  # noqa: E402

from campus_ai import companion_build, companion_protocol as cp  # noqa: E402
from campus_ai.companion_store import SnapshotStore  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / 'scripts'


class IntegrationBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / '.tmp-campus-ai')
        self.addCleanup(self.tmp.cleanup)
        self.dest = Path(self.tmp.name) / 'build'

    def test_adds_only_native_messaging_and_keeps_the_same_id(self):
        out = companion_build.build(self.dest)
        preview = json.loads((ROOT / 'companion' / 'manifest.json').read_text('utf-8'))
        built = json.loads((out / 'manifest.json').read_text('utf-8'))
        self.assertEqual(built['permissions'], ['activeTab', 'scripting', 'nativeMessaging'])
        self.assertEqual(built['key'], preview['key'])
        self.assertEqual(built['content_security_policy'], preview['content_security_policy'])
        self.assertEqual({k: v for k, v in built.items() if k not in ('permissions', 'name', 'description')},
                         {k: v for k, v in preview.items() if k not in ('permissions', 'name', 'description')})
        source = sorted(p.name for p in (ROOT / 'companion' / 'src').iterdir())
        self.assertEqual(sorted(p.name for p in (out / 'src').iterdir()), source)
        for name in source:
            self.assertEqual((out / 'src' / name).read_bytes(), (ROOT / 'companion' / 'src' / name).read_bytes())
        self.assertEqual(sorted(p.name for p in out.iterdir()), ['manifest.json', 'src'])   # no tests, no package.json

    def test_rebuild_replaces_only_a_previous_build(self):
        companion_build.build(self.dest)
        companion_build.build(self.dest)
        other = Path(self.tmp.name) / 'outra'
        other.mkdir()
        (other / 'pessoal.txt').write_text('não apagar', encoding='utf-8')
        with self.assertRaises(ValueError):
            companion_build.build(other)
        self.assertTrue((other / 'pessoal.txt').exists())
        with self.assertRaises(ValueError):
            companion_build.build(ROOT / 'companion' / 'x')

    def test_refuses_a_preview_manifest_that_already_has_native_messaging(self):
        with self.assertRaises(ValueError):
            companion_build.integration_manifest({'permissions': ['nativeMessaging']})


class InstallScriptTests(unittest.TestCase):
    def setUp(self):
        self.install = (SCRIPTS / 'instalar_companion_host.ps1').read_text(encoding='utf-8')
        self.remove = (SCRIPTS / 'remover_companion_host.ps1').read_text(encoding='utf-8')

    def test_nothing_is_changed_without_the_explicit_switch(self):
        for script in (self.install, self.remove):
            self.assertIn('param([switch]$Aplicar)', script)
            gate = script.index('if (-not $Aplicar)')
            for write in ('New-Item', 'Set-ItemProperty', 'Remove-Item', 'WriteAllText', 'Set-Content'):
                for match in re.finditer(re.escape(write), script):
                    self.assertGreater(match.start(), gate, f'{write} before the -Aplicar gate')

    def test_scope_is_the_current_user_and_one_registry_key(self):
        key = r'HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName'
        for full in (self.install, self.remove):
            script = re.sub(r'<#.*?#>', '', full, flags=re.S)     # code only (the help text explains what it avoids)
            self.assertIn(f'$HostName = \'{cp.HOST_NAME}\'', script)
            self.assertIn(key, script)
            self.assertEqual(re.findall(r'HK[A-Z]{2}:', script), ['HKCU:'] * len(re.findall(r'HK[A-Z]{2}:', script)))
            for forbidden in ('HKLM', 'Set-Acl', 'icacls', 'Start-Process', 'Invoke-WebRequest', 'RunAs',
                              'Invoke-Expression', 'iex ', 'DownloadString', 'browser_profile'):
                self.assertNotIn(forbidden, script)
            self.assertIn("'CampusAI-Companion'", script)      # NOT inside %LOCALAPPDATA%\CampusAI
        # live.db: the installer only READS it (backup, see test_companion_launch); the remover never names it
        self.assertNotIn('live.db', re.sub(r'<#.*?#>', '', self.remove, flags=re.S))

    def test_host_manifest_allows_only_the_companion(self):
        self.assertIn(f"$ExtensionId = '{cp.COMPANION_EXTENSION_ID}'", self.install)
        self.assertIn('allowed_origins = @("chrome-extension://$ExtensionId/")', self.install)
        self.assertIn("type            = 'stdio'", self.install)
        self.assertIn('-E -s -m campus_ai.companion_host %*', self.install)


class AppSummaryTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def window(self, data_dir):
        from campus_ai.config import Settings
        from campus_ai.ui import MainWindow
        with patch('campus_ai.ui.app_dir', return_value=Path(data_dir)), \
             patch('campus_ai.ui.Settings.load', return_value=Settings()), \
             patch('campus_ai.ui.QSystemTrayIcon.isSystemTrayAvailable', return_value=False), \
             patch('campus_ai.companion_host.registration_status', return_value='nao_registrado'):
            window = MainWindow()
            self.addCleanup(window.deleteLater)
            return window

    def test_tab_shows_no_reading_yet_and_the_host_state(self):
        with tempfile.TemporaryDirectory() as data:
            window = self.window(data)
            self.assertEqual(window.tabs.tabText(window.companion_tab), 'Companion (Chrome)')
            text = window.companion_view.toPlainText()
            self.assertIn('Nenhuma leitura do Campus AI Companion', text)
            self.assertIn('não registrado neste Windows', text)
            self.assertTrue(window.companion_view.isReadOnly())

    def test_tab_shows_the_last_reading_received(self):
        with tempfile.TemporaryDirectory() as data:
            store = SnapshotStore(Path(data) / 'live.db', allowed_courses=['7653'])
            store.save(snapshot())
            store.record_failure('falha_persistencia')
            window = self.window(data)
            text = window.companion_view.toPlainText()
            for expected in ('Disciplina fictícia', 'Módulos nesta leitura: 7', 'Novos: 7', 'Cobertura: parcial',
                             'Erros de sincronização: 1 (último: falha_persistencia'):
                self.assertIn(expected, text)


if __name__ == '__main__':
    unittest.main()

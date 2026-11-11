"""Startup integration tested with a fake registry; never registers this app."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from campus_ai import startup


class StartupTests(unittest.TestCase):
    def test_enable_uses_only_current_user_and_migrates_legacy_shortcut(self):
        registry = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shortcut = root / 'Campus AI.lnk'
            shortcut.write_text('old fixture')
            with patch.dict(sys.modules, {'winreg': registry}), \
                 patch('campus_ai.startup.sys.platform', 'win32'), \
                 patch('campus_ai.startup.command', return_value='"C:\\My App\\pythonw.exe" "C:\\My App\\run_app.pyw" --startup'), \
                 patch('campus_ai.startup.legacy_shortcut', return_value=shortcut):
                startup.configure(True)
                self.assertFalse(shortcut.exists())
                self.assertEqual(registry.CreateKeyEx.call_args.args[0], registry.HKEY_CURRENT_USER)
                self.assertTrue(registry.SetValueEx.call_args.args[-1].endswith('--startup'))
                startup.configure(False)
                registry.DeleteValue.assert_called_once()

    def test_command_preserves_absolute_paths_with_spaces(self):
        with patch('campus_ai.startup.sys.executable', 'C:/My Campus/.venv/Scripts/python.exe'), \
             patch('campus_ai.startup.Path.is_file', return_value=True):
            command = startup.command()
        self.assertIn('pythonw.exe"', command)
        self.assertIn('--startup', command)
        self.assertNotIn('--scan', command)

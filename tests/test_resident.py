"""Offline resident behavior; no account, startup registration or browser access."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication

from campus_ai.config import Settings
from campus_ai.ui import MainWindow


class ResidentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = patch('campus_ai.ui.app_dir', return_value=Path(self.tmp.name))
        data.start()
        self.addCleanup(data.stop)
        with patch('campus_ai.ui.Settings.load', return_value=Settings()), \
             patch('campus_ai.ui.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
            self.window = MainWindow()
        self.addCleanup(self.dispose)

    def dispose(self):
        self.window.reminder.stop()
        self.window.tray.hide()
        self.window._quitting = True
        self.window.close()

    def test_close_hides_window_and_keeps_agent_alive(self):
        self.window.show()
        self.window.close()
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.window._quitting)

    def test_hiding_does_not_stop_browser_but_quit_waits_for_worker(self):
        from unittest.mock import Mock
        worker = Mock()
        worker.isRunning.return_value = True
        self.window.browser_worker = worker
        self.window.close()
        worker.stop_safely.assert_not_called()
        self.window.quit_agent()
        worker.stop_safely.assert_called_once()
        self.assertTrue(self.window._close_pending)
        self.assertTrue(self.window._quitting)
        # Simulate the thread's finished signal without a real browser.
        worker.isRunning.return_value = False
        self.window._browser_stopped()
        self.assertIsNone(self.window.browser_worker)

    def test_remind_and_ignore_never_scan(self):
        with patch.object(self.window, 'start_scan') as scan:
            self.window.remind_later()
            self.assertTrue(self.window.reminder.isActive())
            self.window.ignore_offer()
            self.assertFalse(self.window.reminder.isActive())
            scan.assert_not_called()

    def test_startup_offer_never_scans(self):
        with patch.object(self.window, 'start_scan') as scan, \
             patch.object(self.window.tray, 'showMessage') as notify:
            self.window.ask_on_start()
            notify.assert_called_once()
            scan.assert_not_called()

    def test_tray_actions_present(self):
        labels = [a.text() for a in self.window.tray.contextMenu().actions()]
        for label in ('Analisar agora', 'Lembrar mais tarde', 'Ignorar', 'Abrir Campus AI', 'Encerrar Campus AI'):
            self.assertIn(label, labels)

    def test_periodic_disabled_and_busy_never_scan(self):
        with patch.object(self.window, 'start_scan') as scan:
            self.window._periodic_scan()
            self.window.settings.periodic_enabled = True
            self.window._browser_busy = True
            self.window._periodic_scan()
            scan.assert_not_called()

    def test_periodic_opt_in_waits_interval_and_can_be_disabled(self):
        self.window.settings.periodic_enabled = True
        self.window.settings.periodic_minutes = 30
        with patch.object(self.window, 'start_scan') as scan:
            self.window._configure_periodic()
            self.assertEqual(self.window.periodic_timer.interval(), 1800000)
            scan.assert_not_called()
            self.window.settings.vault_path = self.tmp.name
            self.window._periodic_scan()
            scan.assert_called_once()
            self.window.settings.periodic_enabled = False
            self.window._configure_periodic()
            self.assertFalse(self.window.periodic_timer.isActive())

    def test_live_browser_scan_uses_worker(self):
        from unittest.mock import Mock
        self.window.settings = Settings(mode='live', moodle_method='browser', vault_path=self.tmp.name)
        worker = Mock()
        with patch.object(self.window, '_ensure_browser_worker', return_value=worker), \
             patch('campus_ai.ui.run_scan') as scan:
            self.window.start_scan()
        worker.request.assert_called_once()
        self.assertEqual(worker.request.call_args.args[0], 'scan')
        scan.assert_not_called()


class InstanceTests(unittest.TestCase):
    def test_second_owner_refused_then_released(self):
        from campus_ai.instance import InstanceGuard
        with tempfile.TemporaryDirectory() as directory:
            first = InstanceGuard(Path(directory))
            second = InstanceGuard(Path(directory))
            self.assertTrue(first.acquire())
            try:
                self.assertFalse(second.acquire())
            finally:
                first.release()
                second.release()
            self.assertTrue(second.acquire())
            second.release()


class ConsentSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_declining_periodic_consent_does_not_save_or_register(self):
        from campus_ai.ui import SettingsDialog
        from PySide6.QtWidgets import QMessageBox
        with patch('campus_ai.ui.get_secret', return_value=None), \
             patch('campus_ai.ui.SettingsDialog._safe_gmail_connected', return_value=False), \
             patch('campus_ai.startup.enabled', return_value=False), \
             patch('campus_ai.startup.configure') as register, \
             patch('campus_ai.config.Settings.save') as save, \
             patch('campus_ai.ui.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
            dialog = SettingsDialog(Settings())
            dialog.periodic.setChecked(True)
            dialog._save()
            save.assert_not_called()
            register.assert_not_called()
            dialog.close()

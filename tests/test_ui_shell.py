"""The redesigned main window: sidebar + pages, Jarvis first, every feature still reachable, nothing invented.

Fictitious data in a temporary folder only (app_dir and the home folder are patched); no network, no real data.
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent))
from companion_snapshots import snapshot, snapshot_dict  # noqa: E402

from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from campus_ai import contract  # noqa: E402
from campus_ai.companion_store import SnapshotStore  # noqa: E402

T1 = '2026-11-06T02:31:00+00:00'
PAGES = ('jarvis', 'overview', 'activities', 'materials', 'history', 'integrations', 'settings')


class ShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.db = self.data / 'live.db'

    def window(self):
        from campus_ai.config import Settings
        from campus_ai.ui import MainWindow
        for target, kwargs in (('campus_ai.ui.app_dir', {'return_value': self.data}),
                               ('campus_ai.ui_pages.Path.home', {'return_value': self.data}),
                               ('campus_ai.companion_host.registration_status', {'return_value': 'registrado'})):
            p = patch(target, **kwargs)
            p.start()
            self.addCleanup(p.stop)
        with patch('campus_ai.ui.Settings.load', return_value=Settings()), \
             patch('campus_ai.ui.QSystemTrayIcon.isSystemTrayAvailable', return_value=False):
            window = MainWindow()                         # Path.home is patched above: Documents\Campus AI is temporary
        self.assertEqual(window.jarvis_panel.output_dir, self.data / 'Documents' / 'Campus AI')
        self.addCleanup(self._dispose, window)
        return window

    @staticmethod
    def _dispose(window):
        window._quitting = True
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()

    # --- structure ------------------------------------------------------------------------------------------------
    def test_jarvis_is_the_first_page_and_every_page_has_a_sidebar_item(self):
        window = self.window()
        self.assertEqual(window.page_names, PAGES)
        self.assertEqual(window.current_page, 'jarvis')
        self.assertIs(window.stack.currentWidget(), window.jarvis_panel)
        self.assertEqual(set(window.sidebar.buttons), set(PAGES))
        self.assertTrue(window.sidebar.buttons['jarvis'].isChecked())
        for name in PAGES:
            window.sidebar.buttons[name].click()
            self.assertEqual(window.current_page, name)
            self.assertIs(window.stack.currentWidget(), window.pages[name])
            self.assertTrue(window.sidebar.buttons[name].isChecked())

    def test_every_existing_feature_has_a_place(self):
        window = self.window()
        place = {
            'jarvis': [window.jarvis_panel],
            'overview': [window.run_button, window.info, window.overview, *window.labels.values()],
            'activities': [window.table],
            'history': [window.recent],
            'integrations': [window.companion_box, window.companion_status, window.obsidian_button],
            'settings': [window.settings_button, window.ask_button, window.mode_label, window.tabs, window.moodle_group,
                         window.companion_view, window.pilot_panel, *window.moodle_buttons, window.moodle_status,
                         window.last_sync],
        }
        for name, widgets in place.items():
            for widget in widgets:
                self.assertTrue(window.pages[name].isAncestorOf(widget), f'{widget!r} should be on {name}')
        self.assertEqual([window.tabs.tabText(i) for i in range(window.tabs.count())],
                         ['Leitor antigo', 'Companion (Chrome)', 'Teste piloto — Uma disciplina'])
        self.assertEqual([b.text() for b in window.moodle_buttons],
                         ['Conectar conta AEDB', 'Verificar sessão', 'Abrir navegador', 'Desconectar sessão'])

    def test_there_is_a_single_analysis_button(self):
        window = self.window()
        texts = [b.text() for b in window.findChildren(QPushButton)]
        self.assertEqual(sum('análise' in t.casefold() for t in texts), 1, texts)
        self.assertEqual(window.run_button.text(), 'Executar análise')

    def test_ctrl_j_and_the_numbers_navigate(self):
        # The offscreen platform never activates a window, so the shortcut objects are triggered directly.
        from PySide6.QtGui import QShortcut
        window = self.window()
        shortcuts = {s.key().toString(): s for s in window.findChildren(QShortcut)}
        window.navigate('settings')
        shortcuts['Ctrl+J'].activated.emit()
        self.assertEqual(window.current_page, 'jarvis')
        shortcuts['Ctrl+3'].activated.emit()
        self.assertEqual(window.current_page, 'activities')
        self.assertEqual({f'Ctrl+{i}' for i in range(1, 8)} - set(shortcuts), set())

    def test_the_pilot_locks_the_other_pages_and_releases_them_on_exit(self):
        window = self.window()
        window.tabs.setCurrentIndex(window.pilot_tab)
        self.assertEqual(window.current_page, 'settings')
        self.assertTrue(window._pilot_active)
        window.navigate('jarvis')
        self.assertEqual(window.current_page, 'settings')
        self.assertFalse(window.sidebar.buttons['jarvis'].isEnabled())
        self.assertTrue(window.sidebar.buttons['settings'].isEnabled())
        window.tabs.setCurrentIndex(window.reader_tab)
        self.assertFalse(window._pilot_active)
        self.assertTrue(all(b.isEnabled() for b in window.sidebar.buttons.values()))
        window.navigate('jarvis')
        self.assertEqual(window.current_page, 'jarvis')

    # --- honesty of the summaries ---------------------------------------------------------------------------------
    def test_without_a_reading_nothing_is_counted_or_listed(self):
        window = self.window()
        window.navigate('overview')
        self.assertEqual(window.labels['late'].text(), '—')
        text = ' '.join(w.text() for w in window.overview_deadlines.findChildren(type(window.info)))
        self.assertIn('Nenhuma leitura ainda', text)
        self.assertIn('Aguardando a primeira leitura', window.integration_lines['companion'].state.text())

    def test_unverified_deadlines_are_never_shown_as_deadlines(self):
        SnapshotStore(self.db, allowed_courses=['7653']).save(snapshot(), received_at=T1)   # no details read
        window = self.window()
        window.navigate('overview')
        texts = [w.text() for w in window.overview_deadlines.findChildren(type(window.info))]
        self.assertTrue(any('sem prazo verificado' in t for t in texts), texts)
        self.assertFalse(any(t in ('Pendente', 'Atrasada') for t in texts))
        self.assertEqual(window.labels['late'].text(), '0')
        state = window.integration_lines['companion'].state.text()
        self.assertIn('nº 1', state)
        self.assertIn('antiga', state)                    # T1 is days old: said, not hidden

    def test_verified_deadlines_are_listed_most_urgent_first(self):
        from test_companion_deadlines import VARIETY, with_details
        now = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        data = with_details(snapshot_dict(generated=now),
                            {k: (v[0], v[1], {**v[2], 'checked_at': now}) for k, v in VARIETY.items()})
        SnapshotStore(self.db, allowed_courses=['7653']).save(contract.parse_snapshot(data), received_at=now)
        window = self.window()
        window.navigate('overview')
        texts = [w.text() for w in window.overview_deadlines.findChildren(type(window.info))]
        self.assertIn('Atrasada', texts)
        self.assertLess(texts.index('Atrasada'), texts.index('Pendente'))
        self.assertNotIn('Concluída', texts)                     # done work is not an upcoming deadline
        self.assertEqual(window.labels['late'].text(), '1')

    def test_the_activity_filter_and_search_only_hide_rows(self):
        SnapshotStore(self.db, allowed_courses=['7653']).save(snapshot(), received_at=T1)
        window = self.window()
        visible = lambda: [r for r in range(window.table.rowCount()) if not window.table.isRowHidden(r)]
        self.assertEqual(len(visible()), 7)
        window.activity_filter.setCurrentIndex([t for t, _ in __import__('campus_ai.ui_pages', fromlist=['x']).FILTERS]
                                               .index('Materiais'))
        self.assertEqual([window.table.item(r, 2).text().split(' • ')[1] for r in visible()], ['Material'])
        window.activity_filter.setCurrentIndex(0)
        window.activity_search.setText('gabarito')
        self.assertEqual(len(visible()), 1)
        window.activity_search.clear()
        self.assertEqual(window.table.rowCount(), 7)
        self.assertEqual(len(visible()), 7)

    def test_materials_page_lists_only_materials(self):
        SnapshotStore(self.db, allowed_courses=['7653']).save(snapshot(), received_at=T1)
        window = self.window()
        self.assertEqual(window.materials_table.rowCount(), 1)
        self.assertIn('Gabarito', window.materials_table.item(0, 0).text())


class ComposerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_enter_sends_and_shift_enter_breaks_the_line(self):
        from campus_ai.jarvis_chat import ChatInput
        box = ChatInput()
        self.addCleanup(box.deleteLater)
        sent = []
        box.submitted.connect(lambda: sent.append(box.text()))
        box.show()
        QTest.keyClicks(box, 'linha um')
        QTest.keyClick(box, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        QTest.keyClicks(box, 'linha dois')
        self.assertEqual(sent, [])
        self.assertEqual(box.text(), 'linha um\nlinha dois')
        QTest.keyClick(box, Qt.Key.Key_Return)
        self.assertEqual(sent, ['linha um\nlinha dois'])
        box.hide()

    def test_the_input_grows_up_to_six_lines(self):
        from campus_ai.jarvis_chat import ChatInput
        box = ChatInput()
        self.addCleanup(box.deleteLater)
        one = box.height()
        box.setText('\n'.join('x' * 3 for _ in range(3)))
        three = box.height()
        box.setText('\n'.join('x' * 3 for _ in range(20)))
        many = box.height()
        self.assertLess(one, three)
        self.assertLess(three, many)
        box.setText('\n'.join('x' * 3 for _ in range(40)))
        self.assertEqual(box.height(), many)

    def test_bubbles_show_markup_as_text(self):
        from campus_ai.jarvis_chat import ChatView
        view = ChatView()
        self.addCleanup(view.deleteLater)
        view.add('jarvis', 'Jarvis', '<b>negrito</b> <a href="file:///c:/x">x</a>')
        self.assertIn('&lt;b&gt;negrito&lt;/b&gt;', view.toHtml())
        self.assertNotIn('<b>negrito', view.toHtml())
        self.assertIn('<b>negrito</b>', view.toPlainText())


class PanelLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def panel(self):
        from campus_ai.jarvis_ui import JarvisPanel
        panel = JarvisPanel(store_path=self.dir / 'jarvis.db', live_db=self.dir / 'live.db', output_dir=self.dir / 'out',
                            reminder_interval_ms=3600000)

        def destroy():
            panel.shutdown()
            panel.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            QCoreApplication.processEvents()
        self.addCleanup(destroy)
        return panel

    def test_a_new_conversation_starts_on_the_welcome_screen_with_suggestions(self):
        panel = self.panel()
        self.assertIsNot(panel.views.currentWidget(), panel.transcript)
        self.assertEqual([s.text() for s in panel.suggestions][:1], ['O que tenho para fazer hoje?'])
        self.assertFalse(panel.send_button.isEnabled())              # nothing typed yet
        panel.input.setText('ajuda')
        self.assertTrue(panel.send_button.isEnabled())
        panel.suggestions[0].click()
        self.assertTrue(panel.wait_idle())
        self.assertIs(panel.views.currentWidget(), panel.transcript)
        self.assertIn('O que tenho para fazer hoje?', panel.transcript.toPlainText())

    def test_stop_is_offered_only_while_a_request_runs(self):
        panel = self.panel()
        panel.show()
        self.assertTrue(panel.stop_button.isHidden())
        panel.send('ajuda')
        self.assertFalse(panel.stop_button.isHidden())
        self.assertTrue(panel.send_button.isHidden())
        self.assertTrue(panel.wait_idle())
        self.assertTrue(panel.stop_button.isHidden())
        self.assertFalse(panel.send_button.isHidden())
        self.assertTrue(panel.transcript.typing.isHidden())
        panel.hide()

    def test_the_ai_state_is_a_short_chip_with_the_full_text_in_the_tooltip(self):
        from campus_ai.jarvis.llm import Status
        panel = self.panel()
        seen = []
        panel.ai_display.connect(lambda *args: seen.append(args))
        panel._show_ai_status(Status(server=True, model_present=True, version='0.40.15'))
        self.assertEqual(panel.ai_label.text(), 'IA local · qwen3.5:4b')
        self.assertIn('somente neste computador', panel.ai_label.toolTip())
        self.assertEqual(seen[-1][1], 'ok')
        panel._show_ai_status(Status())
        self.assertEqual(seen[-1][1], 'muted')


if __name__ == '__main__':
    unittest.main()

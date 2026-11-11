"""The Companion readings in the main window: table, summary, live refresh, links, no false alerts."""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from companion_snapshots import ITEMS, snapshot  # noqa: E402

from campus_ai.companion_store import SnapshotStore  # noqa: E402
from campus_ai.engine import ScanResult  # noqa: E402
from campus_ai.models import AcademicItem  # noqa: E402

T1 = '2026-11-06T02:31:00+00:00'
T2 = '2026-11-06T03:10:00+00:00'


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.db = self.data / 'live.db'

    def store(self):
        return SnapshotStore(self.db, allowed_courses=['7653'])

    def window(self):
        from campus_ai.config import Settings
        from campus_ai.ui import MainWindow
        with patch('campus_ai.ui.app_dir', return_value=self.data), \
             patch('campus_ai.ui.Settings.load', return_value=Settings()), \
             patch('campus_ai.ui.QSystemTrayIcon.isSystemTrayAvailable', return_value=False), \
             patch('campus_ai.companion_host.registration_status', return_value='registrado'):
            window = MainWindow()
        self.addCleanup(window.deleteLater)
        self.patches = [patch('campus_ai.ui.app_dir', return_value=self.data),
                        patch('campus_ai.companion_host.registration_status', return_value='registrado')]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        return window

    def column(self, window, col):
        return [window.table.item(r, col).text() for r in range(window.table.rowCount())]

    def test_nothing_received_yet(self):
        window = self.window()
        self.assertEqual(window.table.rowCount(), 0)
        self.assertIn('Nenhuma leitura do Campus AI Companion', window.companion_status.text())
        self.assertEqual(window.labels['total'].text(), '—')
        self.assertFalse(self.db.exists())                      # opening the app never creates the database

    def test_saved_readings_are_visible_as_soon_as_the_app_opens(self):
        self.store().save(snapshot(), received_at=T1)
        window = self.window()
        self.assertEqual(window.table.rowCount(), 7)
        self.assertEqual(set(self.column(window, 0)), {'Companion (Chrome)'})
        self.assertEqual(set(self.column(window, 4)), {'não verificado'})          # deadlines unknown
        kinds = self.column(window, 2)
        self.assertEqual(sum(k.startswith('Tarefa • Atividade') for k in kinds), 5)
        self.assertEqual(sum(k.startswith('Arquivo • Material') for k in kinds), 1)
        self.assertEqual(sum(k.startswith('Escolha de grupo • Atividade') for k in kinds), 1)
        self.assertTrue(all(k.endswith('registrado') for k in kinds))             # baseline, not "novo"
        self.assertFalse(any('novo' in k.split(' • ') for k in kinds))
        self.assertEqual([window.labels[k].text() for k in ('total', 'new', 'pending')], ['7', '0', '0'])
        status = window.companion_status.text()
        for expected in ('Disciplina fictícia', 'Atividades Avaliativas', 'Módulos: 7 (6 atividade(s), 1 material(is))',
                         'Pendências confirmadas: 0', 'linha de base', 'Cobertura: parcial', 'Prazos: não verificados',
                         'Erros de sincronização: nenhum'):
            self.assertIn(expected, status)
        self.assertIn('Disciplina fictícia', window.overview.text())
        self.assertIn('registrado para este usuário', window.companion_view.toPlainText())   # diagnostic tab kept
        self.assertEqual(window.tabs.tabText(window.companion_tab), 'Companion (Chrome)')

    def test_the_old_reader_is_named_apart_from_the_companion(self):
        window = self.window()
        self.assertIn('Companion', window.companion_box.title())
        self.assertIn('Leitor antigo', window.moodle_group.title())
        self.assertIn('independente do Companion', window.moodle_group.title())
        self.assertTrue(window.last_sync.text().startswith('Leitor antigo'))
        self.assertIn('Leitor antigo', window.moodle_status.text())

    def test_a_new_reading_appears_without_restarting_and_without_notifications(self):
        store = self.store()
        store.save(snapshot(), received_at=T1)
        window = self.window()
        self.assertTrue(window.companion_timer.isActive())
        self.assertEqual(window.companion_timer.interval(), 2000)
        with patch.object(window, '_notify') as notify, patch.object(window.tray, 'showMessage') as toast:
            changed = [(c, k, 'Título alterado' if c == '90001' else t) for c, k, t in ITEMS]
            store.save(snapshot(changed + [('90010', 'assign', 'Módulo novo')]), received_at=T2)   # what the host does
            window._poll_companion()
            self.assertEqual(window.table.rowCount(), 8)
            by_title = {window.table.item(r, 3).text(): window.table.item(r, 2).text() for r in range(8)}
            self.assertTrue(by_title['Módulo novo'].endswith('• novo'))
            self.assertTrue(by_title['Título alterado'].endswith('• alterado'))
            self.assertEqual(window.labels['new'].text(), '2')
            self.assertIn('1 novo(s), 1 alterado(s)', window.companion_status.text())
            self.assertNotIn('linha de base', window.companion_status.text())
            self.assertIn('leitura nº 2', window.companion_status.text())
            notify.assert_not_called()
            toast.assert_not_called()

    def test_polling_reads_the_database_only_when_it_changed(self):
        store = self.store()
        store.save(snapshot(), received_at=T1)
        window = self.window()
        import campus_ai.companion_view as cv
        with patch.object(cv, 'load_view', wraps=cv.load_view) as load:
            window._poll_companion()
            window._poll_companion()
            self.assertEqual(load.call_count, 0)
            store.save(snapshot(), received_at=T2)
            window._poll_companion()
            self.assertEqual(load.call_count, 1)
            window._poll_companion()
            self.assertEqual(load.call_count, 1)

    def test_a_locked_or_damaged_database_keeps_what_is_shown(self):
        store = self.store()
        store.save(snapshot(), received_at=T1)
        window = self.window()
        before = (self.column(window, 3), window.companion_status.text())
        store.save(snapshot(), received_at=T2)
        with patch('campus_ai.companion_view.load_view', side_effect=sqlite3.OperationalError('database is locked')):
            window._poll_companion()
        self.assertEqual((self.column(window, 3), window.companion_status.text()), before)
        window._poll_companion()                                   # the next tick recovers
        self.assertIn('leitura nº 2', window.companion_status.text())

    def test_the_original_link_opens_only_after_a_double_click(self):
        self.store().save(snapshot(), received_at=T1)
        with patch('campus_ai.ui.QDesktopServices.openUrl') as opener:
            window = self.window()
            window._poll_companion()
            window._refresh_companion(force=True)
            opener.assert_not_called()                              # showing the data never opens anything
            row = self.column(window, 3).index('AV1 - Gabarito sintético')
            window.open_item(row, 3)
            opener.assert_called_once()
            self.assertEqual(opener.call_args[0][0].toString(), 'https://ead.aedb.br/ava/mod/resource/view.php?id=90004')
            tooltip = window.table.item(row, 3).toolTip()
            self.assertIn('Duplo clique abre o módulo', tooltip)
            self.assertIn('não verificados', tooltip)

    def test_markup_in_titles_is_plain_text(self):
        self.store().save(snapshot([('90001', 'assign', '<b>negrito</b> & <script>x</script>')]), received_at=T1)
        window = self.window()
        self.assertEqual(self.column(window, 3), ['<b>negrito</b> & <script>x</script>'])
        self.assertNotIn('<b>', window.table.item(0, 3).toolTip())

    def test_companion_rows_coexist_with_a_regular_scan(self):
        self.store().save(snapshot(), received_at=T1)
        window = self.window()
        scan_items = [AcademicItem('moodle:course:1:module:1', 'moodle', 'assignment', 'Trabalho do leitor antigo',
                                   'Outra disciplina', due_iso='2026-12-01T10:00:00', status='pending'),
                      AcademicItem('gmail:1', 'gmail', 'message', 'Aviso', 'E-mail Institucional')]
        result = ScanResult(scan_items, scan_items[:1], [], 2, [])
        with patch.object(window, '_notify'):
            window._scan_ok(result)
        self.assertEqual(window.table.rowCount(), 9)
        self.assertEqual(self.column(window, 0)[:2], ['moodle', 'gmail'])           # scan items first, as before
        self.assertEqual(self.column(window, 0)[2:], ['Companion (Chrome)'] * 7)
        self.assertEqual([window.labels[k].text() for k in ('total', 'new', 'pending')], ['9', '1', '1'])
        self.assertIn('Disciplina fictícia', window.overview.text())
        self.assertIn('Outra disciplina', window.overview.text())
        window._poll_companion()                                                   # a refresh keeps the scan rows
        self.assertEqual(window.table.rowCount(), 9)

    def test_two_sections_appear_together_each_with_its_section(self):
        store = self.store()
        store.save(snapshot(), received_at=T1)
        store.save(snapshot([('92001', 'resource', 'Material sintético das trilhas')], section='4241',
                            section_name='Trilhas de Aprendizagem'), received_at=T2)
        window = self.window()
        self.assertEqual(window.table.rowCount(), 8)
        places = self.column(window, 1)
        self.assertEqual(places.count('Disciplina fictícia › Atividades Avaliativas'), 7)
        self.assertEqual(places.count('Disciplina fictícia › Trilhas de Aprendizagem'), 1)
        self.assertEqual(window.labels['total'].text(), '8')
        self.assertEqual(window.labels['new'].text(), '0')            # a new section's first reading is not "news"
        self.assertIn('2 seções com leitura', window.companion_status.text())

    def test_failures_are_visible_and_never_called_a_reading(self):
        store = self.store()
        store.record_failure('falha_persistencia', received_at=T1)
        window = self.window()
        self.assertEqual(window.table.rowCount(), 0)
        self.assertIn('Erros de sincronização: 1 (último: falha_persistencia', window.companion_status.text())
        self.assertIn('Nenhuma leitura', window.companion_status.text())

    def test_the_companion_box_is_hidden_with_the_other_panels_in_the_pilot_tab(self):
        # Since the redesign the Companion card lives on the "Integrações" page; the pilot is in Configurações ›
        # Avançado and, while it runs, no other page can be shown.
        window = self.window()
        window.show()
        window.navigate('integrations')
        self.assertTrue(window.companion_box.isVisible())
        window.tabs.setCurrentIndex(window.pilot_tab)
        self.assertFalse(window.companion_box.isVisible())
        window.navigate('integrations')
        self.assertFalse(window.companion_box.isVisible())
        window._quitting = True
        window.close()


if __name__ == '__main__':
    unittest.main()

"""No account, persistence, real browser or network: Qt pilot workflow."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication, QMessageBox
from campus_ai.authorized_courses import AuthorizedCourse
from campus_ai.config import Settings
from campus_ai.ui import MainWindow
from campus_ai.pilot import PilotSelection, PilotResult, PilotRow, PilotLimits, Coverage
from campus_ai.pilot_nav import NavQuestion

COURSE = AuthorizedCourse('7653', 'Modelagem UML')
URL = COURSE.url


def pending():
    return PilotSelection(URL, COURSE.name, (COURSE.name,), 'manual', ())


class PilotUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, value in (('campus_ai.ui.app_dir', Path(self.tmp.name)),
                              ('campus_ai.ui.Settings.load', Settings(periodic_enabled=True)),
                              ('campus_ai.ui.QSystemTrayIcon.isSystemTrayAvailable', False)):
            p = patch(target, return_value=value); p.start(); self.addCleanup(p.stop)
        self.window = MainWindow(pilot=True)
        self.panel = self.window.pilot_panel
        self.addCleanup(self.dispose)

    def dispose(self):
        self.window.browser_worker = None
        self.window._quitting = True
        self.window.close()

    def worker(self):
        worker = Mock()
        worker.isRunning.return_value = True
        self.window.browser_worker = worker
        return worker

    def test_pilot_entry_stops_periodic_and_blocks_full_scan(self):
        self.assertFalse(self.window.periodic_timer.isActive())
        with patch('campus_ai.ui.run_scan') as scan, patch.object(self.window, '_browser_task') as task:
            self.window.start_scan()
            self.window._periodic_scan()
            scan.assert_not_called(); task.assert_not_called()
        self.assertFalse(self.window.tray_scan.isEnabled())

    def test_single_button_flow_no_tab_selection_or_confirmation_buttons(self):
        self.assertEqual(self.panel.analyze_button.text(), 'Analisar disciplina')
        for removed in ('select_button', 'read_button', 'open_button', 'elements', 'timeout', 'total'):
            self.assertFalse(hasattr(self.panel, removed), removed)
        self.assertEqual(self.panel.combo.count(), 1)
        self.assertIn('Modelagem UML', self.panel.combo.itemText(0))

    def test_analyze_starts_the_worker_and_requests_the_authorized_course_once(self):
        worker = Mock()
        with patch.object(self.window, '_ensure_browser_worker', return_value=worker) as ensure:
            self.panel.analyze_button.click()
        ensure.assert_called_once()
        worker.request.assert_called_once()
        operation, payload = worker.request.call_args.args
        self.assertEqual((operation, payload[0]), ('pilot_analyze', COURSE))
        self.assertIsInstance(payload[1], PilotLimits)
        self.assertEqual(payload[2], {'inspect_only': False})
        self.assertFalse(self.panel.analyze_button.isEnabled())
        self.assertTrue(self.panel.cancel_button.isEnabled())
        self.assertIn('Abrindo', self.panel.status.text())

    def test_inspection_checkbox_asks_for_a_read_only_look_at_the_cards(self):
        worker = Mock()
        self.panel.inspect_check.setChecked(True)
        with patch.object(self.window, '_ensure_browser_worker', return_value=worker):
            self.panel.analyze_button.click()
        operation, payload = worker.request.call_args.args
        self.assertEqual((operation, payload[2]), ('pilot_analyze', {'inspect_only': True}))

    def test_progress_states_are_clear(self):
        expected = {'abrindo': 'Abrindo', 'login': 'Login necessário', 'autenticado': 'Autenticado',
                    'explorando': 'Rolando a página', 'expandindo': 'Expandindo seções',
                    'analisando': 'Extraindo materiais'}
        for state, text in expected.items():
            with self.subTest(state=state):
                self.window._browser_progress('pilot_analyze', state)
                self.assertIn(text, self.panel.status.text())
        details = {'acessando:Atividades Avaliativas': 'Acessando Atividades Avaliativas',
                   'identificando:AV1': 'Identificando AV1', 'identificando:AV2': 'Identificando AV2',
                   'verificando': 'Verificando cobertura'}
        for state, text in details.items():
            with self.subTest(state=state):
                self.window._browser_progress('pilot_analyze', state)
                self.assertIn(text, self.panel.status.text())
        self.window._browser_progress('pilot_analyze', 'analisando')
        self.assertIn('Extraindo materiais', self.panel.status.text())
        self.window._browser_progress('connect', 'login')  # Not a pilot operation: ignored.
        self.assertIn('Extraindo materiais', self.panel.status.text())

    def test_complete_result_needs_no_dialog(self):
        rows = [PilotRow(COURSE.name, 'Seção', 'AV1', 'Não informado', '', 'AV1'),
                PilotRow(COURSE.name, 'Tarefa', 'Exercício fictício', 'Vencimento: 20/10/2026', '', 'AV1', '8')]
        selection = PilotSelection(URL, '4º P - Modelagem UML', (), 'confirmado', ('trilha de navegação',))
        coverage = Coverage(1, 1, 0, 0, 0, 1)
        self.window._browser_busy = True
        with patch('PySide6.QtWidgets.QMessageBox.exec') as box, patch('campus_ai.pilot_ui.QInputDialog.getItem') as ask:
            self.window._browser_done('pilot_analyze', PilotResult(
                rows, 'completa', 'Cobertura completa: 1 seção identificada.', selection, coverage))
        box.assert_not_called(); ask.assert_not_called()
        self.assertEqual(self.panel.table.rowCount(), 2)
        self.assertEqual(self.panel.table.item(1, 1).text(), 'AV1', 'section column')
        status = self.panel.status.text()
        self.assertIn('cobertura completa', status)
        self.assertIn('Itens: 1', status, 'section rows are not counted as items')
        self.assertNotIn('concluído', status, 'complete coverage must not be shown as a bare "concluído"')
        self.assertIn('4º P - Modelagem UML', self.panel.course.text())
        self.assertTrue(self.panel.analyze_button.isEnabled())
        self.assertFalse(self.window._browser_busy)

    def test_partial_and_error_states_are_labelled(self):
        self.window._browser_done('pilot_analyze', PilotResult([], 'parcial', 'Cobertura parcial: 1 não acessível'))
        self.assertIn('cobertura parcial', self.panel.status.text())
        self.assertNotIn('completa', self.panel.status.text())
        self.window._browser_done('pilot_analyze', PilotResult([], 'falhou', 'Login não concluído em 3 min.'))
        self.assertIn('erro', self.panel.status.text())
        self.assertIn('Login não concluído', self.panel.status.text())
        self.assertIn('Análise não concluída', self.panel.course.text())
        self.assertNotIn('Seleção invalidada', self.panel.course.text())
        self.assertTrue(self.panel.analyze_button.isEnabled())

    def test_not_validated_is_neither_complete_nor_an_error(self):
        selection = PilotSelection(URL, 'Modelagem UML', (), 'id do curso', ('id do curso',))
        self.window._browser_done('pilot_analyze', PilotResult(
            [], 'nao_validada', 'Cobertura não validada: 6 seções acadêmicas reconhecidas, ...', selection))
        status = self.panel.status.text()
        self.assertIn('cobertura não validada', status)
        self.assertNotIn('cobertura completa', status)
        self.assertNotIn('erro', status)
        self.assertIn('Modelagem UML', self.panel.course.text(), 'the identified course stays visible')
        self.assertNotIn('Análise não concluída', self.panel.course.text())
        self.assertTrue(self.panel.analyze_button.isEnabled())

    def test_inspection_result_is_labelled_as_such_not_as_a_failed_validation(self):
        self.window._browser_done('pilot_analyze', PilotResult(
            [], 'nao_validada', 'Modo de inspeção: nada foi navegado, clicado nem lido. Navegação: cartões 5'))
        status = self.panel.status.text()
        self.assertIn('inspeção estrutural', status)
        self.assertNotIn('cobertura não validada', status)

    def test_unverifiable_card_asks_the_student_and_a_yes_continues_with_the_same_question(self):
        worker = self.worker()
        question = NavQuestion('k2', 'Atividades Avaliativas', 'o comportamento do controle não pode ser verificado')
        self.window._browser_busy = True
        with patch('PySide6.QtWidgets.QMessageBox.exec', return_value=QMessageBox.StandardButton.Yes) as box:
            self.window._browser_done('pilot_analyze', question)
        box.assert_called_once()
        operation, (asked, accept, limits) = worker.request.call_args.args
        self.assertEqual((operation, asked, accept), ('pilot_continue', question, True))
        self.assertIsInstance(limits, PilotLimits)
        self.assertFalse(self.panel.analyze_button.isEnabled(), 'still working: no second run can start')

    def test_a_no_is_sent_too_so_the_home_is_read_without_touching_the_card(self):
        worker = self.worker()
        question = NavQuestion('k2', 'Atividades Avaliativas', 'rota desconhecida na AEDB')
        self.window._browser_busy = True
        with patch('PySide6.QtWidgets.QMessageBox.exec', return_value=QMessageBox.StandardButton.No):
            self.window._browser_done('pilot_analyze', question)
        operation, (asked, accept, _limits) = worker.request.call_args.args
        self.assertEqual((operation, asked, accept), ('pilot_continue', question, False))

    def test_the_dialog_defaults_to_no_and_explains_the_consequence(self):
        self.worker()
        question = NavQuestion('k2', 'Atividades Avaliativas', 'rota desconhecida na AEDB')
        seen = {}
        def capture(box):
            seen.update(text=box.text(), default=box.defaultButton().text() if box.defaultButton() else '')
            return QMessageBox.StandardButton.No
        self.window._browser_busy = True
        with patch.object(QMessageBox, 'exec', new=lambda box: capture(box)):
            self.window._browser_done('pilot_analyze', question)
        self.assertIn('Atividades Avaliativas', seen['text'])
        self.assertIn('parcial', seen['text'])
        self.assertIn('No', seen['default'].replace('&', '').replace('Não', 'No'))

    def test_browser_ready_state(self):
        self.window._browser_done('pilot_open', PilotResult([], 'aberta', 'Disciplina autorizada aberta.'))
        self.assertIn('navegador pronto', self.panel.status.text())

    def test_unrecognized_name_asks_once_then_reads_without_extra_confirmation(self):
        worker = self.worker()
        self.window._browser_busy = True
        with patch('campus_ai.pilot_ui.QInputDialog.getItem', return_value=('Modelagem UML', True)) as ask, \
             patch('PySide6.QtWidgets.QMessageBox.exec') as box:
            self.window._browser_done('pilot_analyze', pending())
        ask.assert_called_once(); box.assert_not_called()
        self.assertIs(ask.call_args.args[-1], True, 'a pending manual name must be editable')
        operation, (chosen, limits) = worker.request.call_args.args
        self.assertEqual(operation, 'pilot_read')
        self.assertEqual((chosen.title, chosen.confidence), ('Modelagem UML', 'nome informado'))
        self.assertTrue(pending().accepts(chosen))
        self.assertFalse(self.panel.analyze_button.isEnabled())

    def test_declining_to_name_the_course_reads_nothing(self):
        worker = self.worker()
        with patch('campus_ai.pilot_ui.QInputDialog.getItem', return_value=('', False)):
            self.window._browser_done('pilot_analyze', pending())
        worker.request.assert_not_called()
        self.assertEqual(self.panel.table.rowCount(), 0)
        self.assertIn('Nenhuma leitura', self.panel.status.text())
        self.assertTrue(self.panel.analyze_button.isEnabled())

    def test_cancel_keeps_the_session_and_discards_a_late_result(self):
        worker = self.worker()
        self.window._browser_busy, self.window._browser_op = True, 'pilot_analyze'
        self.panel.cancel_read()
        worker.cancel_connection.assert_called_once()
        for forbidden in ('stop_safely', 'request'):
            getattr(worker, forbidden).assert_not_called()
        self.panel.complete('pilot_analyze', PilotResult([PilotRow('F', 'Item', 'X', '', '')], 'completa', ''))
        self.assertEqual(self.panel.table.rowCount(), 0)
        self.assertIn('Cancelada', self.panel.status.text())
        self.assertIn('sessão', self.panel.status.text())

    def test_cancel_also_works_after_answering_a_card_question(self):
        worker = self.worker()
        self.window._browser_busy, self.window._browser_op = True, 'pilot_continue'
        self.panel.cancel_read()
        worker.cancel_connection.assert_called_once()
        worker.stop_safely.assert_not_called()

    def test_continuing_needs_a_running_worker_and_never_launches_one(self):
        with patch.object(self.window, '_ensure_browser_worker') as create:
            self.window._pilot_request('pilot_continue', (NavQuestion('k', 'X', 'y'), True, PilotLimits()))
        create.assert_not_called()

    def test_read_without_a_running_worker_never_launches_one(self):
        with patch.object(self.window, '_ensure_browser_worker') as create:
            self.window._pilot_request('pilot_read', (PilotSelection(URL, 'X'), PilotLimits()))
        create.assert_not_called()
        self.assertIn('Analise', self.panel.status.text())

    def test_browser_failure_unlocks_and_explains(self):
        self.window._browser_busy = True
        self.window._browser_failed('pilot_analyze', 'BrowserUnavailable')
        self.assertIn('BrowserUnavailable', self.panel.status.text())
        self.assertTrue(self.panel.analyze_button.isEnabled())
        self.assertFalse(self.window._browser_busy)

    def test_browser_closed_during_pilot_prompts_a_new_analysis(self):
        self.window._browser_closed()
        self.assertIn('Analisar', self.panel.status.text())

    def test_no_authorized_course_disables_analysis(self):
        from campus_ai.pilot_ui import PilotPanel
        panel = PilotPanel(self.window, [])
        self.assertFalse(panel.analyze_button.isEnabled())

    def test_result_is_separate_and_does_not_update_history(self):
        row = PilotRow('Fixture', 'resource', 'Título', 'Não informado', '')
        with patch.object(self.window, '_scan_ok') as full, patch('campus_ai.ui.History') as history:
            self.window._browser_done('pilot_read', PilotResult([row], 'completa', 'Fixture'))
        self.assertEqual(self.panel.table.rowCount(), 1)
        self.assertEqual(self.window.table.rowCount(), 0)
        self.assertEqual(self.window._items, [])
        full.assert_not_called(); history.assert_not_called()

    def test_exit_clears_temporary_data_without_resuming_schedule(self):
        self.panel.selection = PilotSelection('x', 'Fixture')
        self.window.tabs.setCurrentIndex(0)
        self.assertIsNone(self.panel.selection)
        self.assertFalse(self.window.periodic_timer.isActive())
        with patch.object(self.window, 'start_scan') as scan:
            self.window._periodic_scan()  # Also ignore a previously queued timeout.
            scan.assert_not_called()


if __name__ == '__main__':
    unittest.main()

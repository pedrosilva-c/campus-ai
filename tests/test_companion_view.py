"""What the main window derives from the existing companion_* tables. Fictitious data, temporary database."""
import re
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from companion_snapshots import ITEMS, snapshot, snapshot_dict  # noqa: E402

from campus_ai import companion_view as cv  # noqa: E402
from campus_ai import contract  # noqa: E402
from campus_ai.companion_store import SnapshotStore  # noqa: E402
from campus_ai.state import History  # noqa: E402

T1 = '2026-11-06T02:31:00+00:00'
T2 = '2026-11-06T03:10:00+00:00'
T3 = '2026-11-06T04:00:00+00:00'
NOW = datetime(2026, 11, 6, 5, 0, tzinfo=timezone.utc)


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'live.db'
        self.store = SnapshotStore(self.db, allowed_courses=['7653'])

    def save(self, items=ITEMS, at=T1, **kwargs):
        return self.store.save(snapshot(items, **kwargs), received_at=at)

    def load(self, now=NOW):
        return cv.load_view(self.db, now=now)

    def states(self, view):
        return {r.cmid: r.state for r in view.rows}

    def test_first_reading_is_a_baseline_not_seven_alerts(self):
        self.save()
        view = self.load()
        self.assertTrue(view.has_reading and view.baseline)
        self.assertEqual((view.modules, view.activities, view.materials), (7, 6, 1))
        self.assertEqual((view.novos, view.alterados, view.ausentes), (0, 0, 0))
        self.assertEqual({r.state for r in view.rows}, {'linha_de_base'})
        self.assertEqual({cv.STATE_TEXT[r.state] for r in view.rows}, {'registrado'})
        text = cv.status_text(view)
        self.assertIn('linha de base', text)
        self.assertIn('Não são novidades', text)
        self.assertNotIn('Novidades desta leitura', text)

    def test_second_reading_without_changes(self):
        self.save()
        self.save(at=T2)
        view = self.load()
        self.assertFalse(view.baseline)
        self.assertEqual({r.state for r in view.rows}, {'sem_mudanca'})
        self.assertEqual((view.novos, view.alterados, view.reaparecidos, view.ausentes), (0, 0, 0, 0))
        self.assertIn('0 novo(s), 0 alterado(s)', cv.status_text(view))
        self.assertEqual(view.run_id, 2)

    def test_new_changed_and_absent_are_relative_to_the_last_reading_only(self):
        self.save()
        changed = [(c, k, 'Título novo' if c == '90001' else t) for c, k, t in ITEMS[:-1]]
        self.save(changed + [('90010', 'assign', 'Módulo novo')], at=T2)
        view = self.load()
        self.assertEqual(self.states(view), {'90001': 'alterado', '90002': 'sem_mudanca', '90003': 'sem_mudanca',
                                             '90004': 'sem_mudanca', '90005': 'sem_mudanca', '90006': 'sem_mudanca',
                                             '90007': 'ausente', '90010': 'novo'})
        self.assertEqual((view.novos, view.alterados, view.ausentes), (1, 1, 1))
        self.assertEqual(view.modules, 7)                    # the absent one is not counted as present
        self.assertIn('ausente não significa removido', cv.status_text(view))
        self.save(changed + [('90010', 'assign', 'Módulo novo')], at=T3)      # nothing new: news disappear
        later = self.load()
        self.assertEqual(self.states(later)['90010'], 'sem_mudanca')
        self.assertEqual(self.states(later)['90001'], 'sem_mudanca')
        self.assertEqual(self.states(later)['90007'], 'ausente')               # still not in the page
        self.save(ITEMS + [('90010', 'assign', 'Módulo novo')], at='2026-11-06T05:00:00+00:00')
        self.assertEqual(self.states(self.load())['90007'], 'reapareceu')

    def test_each_section_has_its_own_baseline(self):
        self.save()
        self.save(at=T2)
        self.save([('95001', 'assign', 'Outra seção')], section='4243', section_name='Outra', at=T3)
        view = self.load()
        self.assertTrue(view.baseline)                       # the newest reading is the first of ITS section
        rows = {r.cmid: r for r in view.rows}
        self.assertEqual(rows['95001'].state, 'linha_de_base')
        self.assertEqual(rows['90001'].state, 'sem_mudanca')
        self.assertEqual(rows['95001'].section_name, 'Outra')
        self.assertEqual(rows['90001'].section_name, 'Atividades Avaliativas')

    def test_classification_links_and_unknown_delivery(self):
        self.save()
        view = self.load()
        rows = {r.cmid: r for r in view.rows}
        self.assertEqual((rows['90004'].kind, rows['90004'].category, rows['90004'].kind_label), ('resource', 'material', 'Arquivo'))
        self.assertEqual((rows['90006'].category, rows['90006'].kind_label), ('atividade', 'Escolha de grupo'))
        self.assertEqual(rows['90001'].kind_label, 'Tarefa')
        self.assertEqual(rows['90001'].url, 'https://ead.aedb.br/ava/mod/assign/view.php?id=90001')
        self.assertEqual(rows['90004'].url, 'https://ead.aedb.br/ava/mod/resource/view.php?id=90004')
        self.assertEqual(rows['90006'].url, 'https://ead.aedb.br/ava/mod/groupselect/view.php?id=90006')
        self.assertTrue(all(r.submission == 'desconhecido' for r in view.rows))
        self.assertEqual((view.unknown_delivery, view.confirmed_pending), (6, 0))     # published is not pending
        self.assertIn('Prazos: não verificados', cv.status_text(view))
        self.assertIn('Entrega: desconhecida em 6', cv.status_text(view))

    def test_module_url_only_for_valid_ids_and_kinds(self):
        good = 'moodle:course:7653:module:90001'
        self.assertEqual(cv.module_url(good, 'quiz'), 'https://ead.aedb.br/ava/mod/quiz/view.php?id=90001')
        for uid, kind in ((good, 'script'), (good, '../x'), ('moodle:course:7653:item:abc', 'assign'),
                          ('moodle:course:7653:module:0', 'assign'), ('x', 'assign'), ('', '')):
            self.assertEqual(cv.module_url(uid, kind), '', (uid, kind))

    def test_a_pending_item_needs_a_recent_not_submitted_reading(self):
        data = snapshot_dict()
        data['activities'][0]['submission'] = 'nao_enviado'
        self.store.save(contract.parse_snapshot(data), received_at=T1)
        self.assertEqual(self.load().confirmed_pending, 1)
        view = self.load(now=NOW + timedelta(days=2))
        self.assertEqual(view.confirmed_pending, 0)
        self.assertTrue(view.stale)
        self.assertIn('desatualizados', cv.status_text(view))

    def test_local_time_not_utc_text(self):
        self.assertRegex(cv.to_local(T1), r'^\d{2}/\d{2}/\d{4} \d{2}:\d{2}$')
        expected = datetime(2026, 11, 6, 2, 31, tzinfo=timezone.utc).astimezone().strftime('%d/%m/%Y %H:%M')
        self.assertEqual(cv.to_local(T1), expected)
        self.assertEqual(cv.to_local('2026-11-06T02:31:00Z'), expected)
        self.assertEqual(cv.to_local('lixo'), '')
        self.save()
        self.assertIn(expected, cv.status_text(self.load()))
        self.assertNotIn('UTC', cv.status_text(self.load()))

    def test_errors_without_any_reading_and_with_one(self):
        self.store.record_failure('esquema_invalido', received_at=T1)
        view = self.load()
        self.assertFalse(view.has_reading)
        self.assertEqual((view.errors, view.last_error_code), (1, 'esquema_invalido'))
        text = cv.status_text(view)
        self.assertIn('Nenhuma leitura', text)
        self.assertIn('Erros de sincronização: 1 (último: esquema_invalido', text)
        self.save(at=T2)
        self.assertIn('Erros de sincronização: 1', cv.status_text(self.load()))
        self.assertIn('Erros de sincronização: nenhum', cv.status_text(cv.load_view(self._clean_db())))

    def _clean_db(self):
        path = Path(self.tmp.name) / 'limpo.db'
        SnapshotStore(path, allowed_courses=['7653']).save(snapshot(), received_at=T1)
        return path

    def test_missing_database_or_tables_mean_no_data_and_nothing_is_created(self):
        missing = Path(self.tmp.name) / 'nao-existe.db'
        self.assertIsNone(cv.load_view(missing))
        self.assertFalse(missing.exists())
        bare = Path(self.tmp.name) / 'historico.db'
        History(bare)
        self.assertIsNone(cv.load_view(bare))
        self.assertIn('Nenhuma leitura', cv.status_text(None))

    def test_damaged_database_raises_so_the_window_keeps_what_it_shows(self):
        broken = Path(self.tmp.name) / 'quebrado.db'
        broken.write_bytes(b'isto nao e um banco sqlite' * 100)
        with self.assertRaises(sqlite3.Error):
            cv.load_view(broken)

    def test_reading_never_writes(self):
        self.save()
        before = (self.db.stat().st_mtime_ns, self.db.stat().st_size, self.db.read_bytes())
        self.load()
        self.assertEqual((self.db.stat().st_mtime_ns, self.db.stat().st_size, self.db.read_bytes()), before)

    def test_one_summary_for_the_course_with_a_line_per_section(self):
        self.save()                                                          # Atividades Avaliativas, baseline
        self.save(at=T2)                                                     # Atividades Avaliativas, unchanged
        trilhas = [('92001', 'resource', 'Material sintético das trilhas'), ('92002', 'assign', 'Exercício sintético')]
        self.save(trilhas, section='4241', section_name='Trilhas de Aprendizagem', at=T3)
        view = self.load()
        self.assertEqual([(s.name, s.run_id, s.modules, s.baseline) for s in view.sections],
                         [('Atividades Avaliativas', 2, 7, False), ('Trilhas de Aprendizagem', 3, 2, True)])
        self.assertEqual((view.modules, view.activities, view.materials), (9, 7, 2))
        text = cv.status_text(view)
        self.assertIn('2 seções com leitura: Atividades Avaliativas, Trilhas de Aprendizagem', text)
        self.assertIn('• Atividades Avaliativas: 7 módulo(s) • leitura nº 2', text)
        self.assertIn('0 novo(s), 0 alterado(s)', text)
        self.assertIn('• Trilhas de Aprendizagem: 2 módulo(s) • leitura nº 3', text)
        self.assertIn('primeira leitura (linha de base), não são novidades', text)
        self.assertIn('Cobertura da disciplina: parcial', text)
        self.assertEqual({r.section_name for r in view.rows}, {'Atividades Avaliativas', 'Trilhas de Aprendizagem'})

    def test_a_failed_section_keeps_its_last_saved_data(self):
        self.save()
        trilhas = [('92001', 'resource', 'Material sintético'), ('92002', 'assign', 'Exercício sintético')]
        self.save(trilhas, section='4241', section_name='Trilhas de Aprendizagem', at=T2)
        self.store.record_failure('painel_nao_abriu', received_at=T3)       # Trilhas failed later: nothing written
        view = self.load()
        self.assertEqual([(s.name, s.modules) for s in view.sections],
                         [('Atividades Avaliativas', 7), ('Trilhas de Aprendizagem', 2)])
        self.assertTrue(all(r.present for r in view.rows))
        self.assertIn('Erros de sincronização: 1 (último: painel_nao_abriu', cv.status_text(view))

    def test_single_section_text_is_unchanged(self):
        self.save()
        text = cv.status_text(self.load())
        self.assertIn('Disciplina: Disciplina fictícia — seção Atividades Avaliativas', text)
        self.assertNotIn('seções com leitura', text)

    def test_signature_changes_only_when_something_was_saved(self):
        self.save()
        first = self.load().signature
        self.assertEqual(self.load().signature, first)
        self.save(at=T2)
        self.assertNotEqual(self.load().signature, first)


if __name__ == '__main__':
    unittest.main()

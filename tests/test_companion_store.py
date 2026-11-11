"""Persistence and comparison of Companion snapshots in the existing SQLite file. Fictitious data only."""
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from companion_snapshots import ITEMS, snapshot  # noqa: E402

from campus_ai import companion_store as cs  # noqa: E402
from campus_ai.state import History  # noqa: E402
from campus_ai.models import AcademicItem  # noqa: E402

AT = '2026-11-05T20:00:00+00:00'


class FailingConnection:
    """Wraps a real connection and fails on the first statement containing `needle`."""

    def __init__(self, conn, needle):
        self.conn, self.needle = conn, needle

    def execute(self, sql, *args):
        if self.needle in sql:
            raise sqlite3.OperationalError('falha simulada')
        return self.conn.execute(sql, *args)

    def close(self):
        self.conn.close()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'live.db'
        self.store = cs.SnapshotStore(self.path, allowed_courses=['7653'])

    def save(self, items=ITEMS, **kwargs):
        return self.store.save(snapshot(items, **kwargs), received_at=AT)

    def table(self, name):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(f'SELECT * FROM {name}').fetchall()

    def test_first_sync_registers_every_module_as_new(self):
        result = self.save()
        self.assertEqual((result.run, result.itens, result.novos, result.alterados, result.ausentes), (1, 7, 7, 0, 0))
        items = self.store.items()
        self.assertEqual([uid for uid, *_ in items], [f'moodle:course:7653:module:9000{i}' for i in range(1, 8)])
        self.assertTrue(all(row[4] == 'desconhecido' for row in items))       # delivery state stays unknown
        self.assertEqual({c[1] for c in self.store.changes(1)}, {'novo'})
        run = self.table('companion_runs')[0]
        self.assertIn('companion', run)
        self.assertIn('parcial', run)
        self.assertIn(AT, run)

    def test_second_sync_without_changes(self):
        self.save()
        result = self.save()
        self.assertEqual((result.novos, result.alterados, result.ausentes, result.inalterados), (0, 0, 0, 7))
        self.assertEqual(self.store.changes(result.run), [])

    def test_new_module_and_changed_title_and_type(self):
        self.save()
        changed = [(c, 'quiz' if c == '90003' else k, 'Título novo' if c == '90001' else t) for c, k, t in ITEMS]
        result = self.save(changed + [('90010', 'assign', 'Exercício sintético novo')])
        self.assertEqual((result.novos, result.alterados, result.inalterados), (1, 2, 5))
        changes = self.store.changes(result.run)
        self.assertIn(('moodle:course:7653:module:90001', 'titulo', 'Exercício sintético A', 'Título novo'), changes)
        self.assertIn(('moodle:course:7653:module:90003', 'tipo', 'assign', 'quiz'), changes)
        self.assertIn(('moodle:course:7653:module:90010', 'novo', '', 'Exercício sintético novo'), changes)

    def test_missing_item_in_a_partial_reading_is_absent_not_deleted(self):
        self.save()
        result = self.save(ITEMS[:-1])
        self.assertEqual((result.ausentes, result.inalterados), (1, 6))
        rows = {uid: present for uid, _k, _t, _a, _s, present in self.store.items()}
        self.assertEqual(len(rows), 7)                                  # nothing deleted
        self.assertEqual(rows['moodle:course:7653:module:90007'], 0)
        text = cs.summary_text(self.store.summary())
        self.assertIn('Ausentes nesta leitura: 1', text)
        self.assertIn('não são considerados removidos', text)
        back = self.save()
        self.assertEqual((back.reaparecidos, back.ausentes, back.inalterados), (1, 0, 6))

    def test_a_reading_of_one_section_never_touches_another_section(self):
        self.save()
        other = self.save([('95001', 'assign', 'Outra seção sintética')], section='4243', section_name='Outra')
        self.assertEqual(other.ausentes, 0)                     # section 4242 items are not "absent"
        rows = {uid: present for uid, _k, _t, _a, _s, present in self.store.items()}
        self.assertTrue(all(rows[f'moodle:course:7653:module:9000{i}'] for i in range(1, 8)))

    def test_a_module_saved_by_another_section_after_a_failure_keeps_one_row_and_one_owner(self):
        # What the v0.5.1 course sync sends: sync 1, Atividades Avaliativas (4242) failed (nothing reached the store)
        # so Trilhas (4241) saved the shared module 90001; sync 2, 4242 saves it and 4241 leaves it out.
        x = 'moodle:course:7653:module:90001'
        trilhas = [ITEMS[0], ('92001', 'assign', 'Exercício sintético das trilhas')]
        first = self.save(trilhas, section='4241', section_name='Trilhas de Aprendizagem')
        self.assertEqual(first.novos, 2)

        def owner(uid):
            with closing(sqlite3.connect(self.path)) as db:
                return db.execute('SELECT section_uid, present FROM companion_items WHERE uid = ?', (uid,)).fetchall()

        self.assertEqual(owner(x), [('moodle:course:7653:section:id-4241', 1)])
        aa = self.save()                                                       # sync 2, section 4242 first
        self.assertEqual((aa.novos, aa.alterados), (6, 1))
        self.assertIn((x, 'secao', 'moodle:course:7653:section:id-4241', 'moodle:course:7653:section:id-4242'),
                      self.store.changes(aa.run))
        tr = self.save(trilhas[1:], section='4241', section_name='Trilhas de Aprendizagem')
        self.assertEqual((tr.ausentes, tr.inalterados), (0, 1))                # 90001 moved, it is not "absent" in 4241
        self.assertEqual(owner(x), [('moodle:course:7653:section:id-4242', 1)])
        self.assertEqual(len(self.table('companion_items')), 8)                # 7 + 92001: never a second row
        again = [self.save(), self.save(trilhas[1:], section='4241', section_name='Trilhas de Aprendizagem')]
        self.assertEqual([(r.novos, r.alterados, r.ausentes) for r in again], [(0, 0, 0), (0, 0, 0)])
        self.assertEqual(owner(x), [('moodle:course:7653:section:id-4242', 1)])

    def test_course_and_identifiers_are_checked_and_nothing_is_written_on_refusal(self):
        cases = [
            (dict(course='9999'), 'disciplina_nao_autorizada'),
            (dict(extra_sections=['4243']), 'secao_ambigua'),
        ]
        for kwargs, code in cases:
            with self.assertRaises(cs.StoreError) as ctx:
                self.save(**kwargs)
            self.assertEqual(ctx.exception.code, code)
        with self.assertRaises(cs.StoreError) as ctx:
            self.save([('x', 'assign', 'Sem cmid', 'moodle:course:7653:item:abcdef0123456789')])
        self.assertEqual(ctx.exception.code, 'identificador_invalido')
        with self.assertRaises(cs.StoreError):
            self.store.save({'schema': 'campus-ai.academic/1'})
        self.assertEqual(self.table('companion_runs'), [])
        self.assertEqual(self.table('companion_items'), [])

    def test_sqlite_error_rolls_back_the_whole_reading(self):
        self.save()
        failing = cs.SnapshotStore(self.path, allowed_courses=['7653'],
                                   connect=lambda: FailingConnection(sqlite3.connect(self.path, isolation_level=None),
                                                                     'UPDATE companion_runs SET novos'))
        with self.assertRaises(sqlite3.OperationalError):
            failing.save(snapshot(ITEMS[:3] + [('90010', 'assign', 'Novo')]), received_at=AT)
        self.assertEqual(len(self.table('companion_runs')), 1)          # only the first, successful run
        self.assertEqual(len(self.table('companion_changes')), 7)
        self.assertNotIn('moodle:course:7653:module:90010', [r[0] for r in self.store.items()])
        self.assertTrue(all(r[5] == 1 for r in self.store.items()))   # no item was marked absent

    def test_failures_are_recorded_with_a_code_only(self):
        self.assertTrue(self.store.record_failure('esquema_invalido', received_at=AT))
        self.assertTrue(self.store.record_failure('<script>texto da página</script>', received_at=AT))
        errors = [row for row in self.table('companion_runs') if 'erro' in row]
        self.assertEqual([row[-1] for row in errors], ['esquema_invalido', 'erro_desconhecido'])
        text = cs.summary_text(self.store.summary())
        self.assertIn('Nenhuma leitura do Campus AI Companion', text)
        self.assertIn('Erros de sincronização: 2', text)

    def test_shares_the_existing_database_with_history(self):
        history = History(self.path)
        item = AcademicItem('moodle:course:7653:module:1', 'moodle', 'material', 'x')
        history.remember(item)
        self.save()
        self.assertTrue(history.has_uid(item.uid))
        with closing(sqlite3.connect(self.path)) as db:
            names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertLessEqual({'items', 'scan_runs', 'companion_runs', 'companion_items', 'companion_changes'}, names)

    def test_migrations_are_idempotent_and_never_downgrade(self):
        self.save()
        again = cs.SnapshotStore(self.path, allowed_courses=['7653'])
        self.assertEqual(again.summary()['last']['items'], 7)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE companion_meta SET value = '99' WHERE key = 'schema_version'")
            db.commit()
        with self.assertRaises(cs.StoreError) as ctx:
            cs.SnapshotStore(self.path, allowed_courses=['7653'])
        self.assertEqual(ctx.exception.code, 'versao_banco_futura')

    def test_read_only_summary_for_the_app(self):
        missing = Path(self.tmp.name) / 'nao-existe.db'
        self.assertIsNone(cs.read_summary(missing))
        self.assertFalse(missing.exists())                     # the app never creates the database
        bare = Path(self.tmp.name) / 'outro.db'
        History(bare)
        self.assertIsNone(cs.read_summary(bare))
        self.save()
        self.save(ITEMS[:-1] + [('90010', 'assign', 'Novo')])
        before = self.path.stat().st_mtime_ns
        summary = cs.read_summary(self.path)
        self.assertEqual(self.path.stat().st_mtime_ns, before)
        text = cs.summary_text(summary)
        for expected in ('Última leitura recebida', 'Disciplina fictícia', 'Atividades Avaliativas',
                         'Módulos nesta leitura: 7', 'Novos: 1', 'Ausentes nesta leitura: 1', 'Cobertura: parcial',
                         'Situação de entrega: desconhecida', 'Erros de sincronização: nenhum'):
            self.assertIn(expected, text)
        self.assertIn('Nenhuma leitura', cs.summary_text(None))


if __name__ == '__main__':
    unittest.main()

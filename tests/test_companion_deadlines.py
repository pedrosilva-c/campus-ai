"""v0.5.4 — deadlines and delivery state from each activity's own page: contract, persistence, view, situations.

FICTITIOUS data only, temporary databases only (the suite's isolation also redirects LOCALAPPDATA).
"""
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from companion_snapshots import ITEMS, snapshot_dict  # noqa: E402

from campus_ai import companion_store as cs  # noqa: E402
from campus_ai import companion_view as cv  # noqa: E402
from campus_ai import contract  # noqa: E402
from campus_ai import deadlines as dl  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'companion'
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)            # 09:00 in America/Sao_Paulo
CHECKED = '2026-11-10T11:30:00Z'
M = lambda cmid: f'moodle:course:7653:module:{cmid}'                  # noqa: E731


def detail(result='ok', submission='sem_envio', grading='nao_avaliado', attempt='nao_se_aplica', due_state='definido',
           checked=CHECKED):
    if result != 'ok':
        submission = grading = attempt = 'desconhecido'
        due_state = 'nao_verificado'
    return {'checked_at': checked, 'result': result, 'submission_state': submission, 'grading_state': grading,
            'attempt_state': attempt, 'due_state': due_state, 'timezone': 'America/Sao_Paulo'}


def with_details(data, per_cmid):
    """Attach v0.5.4 fields to the fictitious snapshot's activities: {cmid: (deadlines, submission, detail)}."""
    for act in data['activities']:
        cmid = act['uid'].rsplit(':', 1)[1]
        if cmid in per_cmid:
            act['deadlines'], act['submission'], act['detail'] = per_cmid[cmid]
    return data


def due(at, kind='entrega', raw='31 dez. 2098, 23:59'):
    return {'kind': kind, 'at': at, 'timezone_explicit': False, 'raw': raw}


VARIETY = {
    '90001': ([due('2098-12-31T23:59')], 'nao_enviado', detail()),                                   # pendente
    '90002': ([due('2020-01-10T23:59')], 'enviado', detail(submission='enviado')),                   # aguardando
    '90003': ([due('2026-11-11T23:59')], 'nao_enviado', detail(submission='rascunho')),              # pendente, <72 h
    '90005': ([due('2020-01-10T23:59')], 'avaliado', detail(submission='enviado', grading='avaliado')),  # concluída
    '90007': ([due('2026-11-01T23:59'), due('2026-11-03T23:59', 'limite')], 'nao_enviado', detail()),  # atrasada
}


class SharedSituationTests(unittest.TestCase):
    def test_the_same_cases_as_the_extension(self):
        shared = json.loads((FIXTURES / 'situations.json').read_text(encoding='utf-8'))
        now = datetime.fromisoformat(shared['now'].replace('Z', '+00:00'))
        for case in shared['cases']:
            self.assertEqual(dl.situation(case['kind'], case['detail'], case['deadlines'], now), case['expected'],
                             case['name'])

    def test_wall_time_and_remaining_time(self):
        self.assertEqual(dl.wall_to_utc('2026-11-10T09:00'), NOW)
        self.assertEqual(dl.wall_to_utc('2026-11-10').isoformat(), '2026-11-11T02:59:00+00:00')
        self.assertIsNone(dl.wall_to_utc('10/11/2026'))
        self.assertEqual(dl.time_left('2026-11-12T09:00', NOW), 'faltam 2 dia(s)')
        self.assertEqual(dl.time_left('2026-11-10T04:00', NOW), 'venceu há 5 h')
        self.assertEqual(dl.time_left('', NOW), '')
        self.assertTrue(dl.due_soon('2026-11-11T23:59', NOW))
        self.assertFalse(dl.due_soon('2026-11-20T23:59', NOW))


class ContractTests(unittest.TestCase):
    def test_details_are_accepted_and_old_snapshots_still_valid(self):
        snap = contract.parse_snapshot(with_details(snapshot_dict(), VARIETY))
        act = next(a for a in snap.activities if a.uid == M('90007'))
        self.assertEqual((act.detail.result, act.detail.due_state, act.submission), ('ok', 'definido', 'nao_enviado'))
        self.assertEqual([d.kind for d in act.deadlines], ['entrega', 'limite'])
        self.assertIsNone(contract.parse_snapshot(snapshot_dict()).activities[0].detail)   # v0.5.3 shape
        again = contract.parse_snapshot(contract.snapshot_to_dict(snap))
        self.assertEqual(again, snap)

    def test_a_failed_page_cannot_state_anything_and_unknown_values_are_refused(self):
        bad = detail('inacessivel')
        bad['submission_state'] = 'enviado'
        for broken in (bad, {**detail(), 'timezone': 'UTC'}, {**detail(), 'result': 'talvez'},
                       {**detail(), 'submission_state': 'quase'}, {**detail(), 'checked_at': '2026-11-10T11:30:00'},
                       {**detail(), 'nota': '10'}):
            with self.assertRaises(contract.ContractError):
                contract.parse_snapshot(with_details(snapshot_dict(), {'90001': ([], 'desconhecido', broken)}))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'live.db'

    def store(self):
        return cs.SnapshotStore(self.path, allowed_courses=['7653'])

    def save(self, store, per_cmid, items=ITEMS, generated='2026-11-10T11:30:00Z'):
        data = with_details(snapshot_dict(items, generated=generated), per_cmid)
        return store.save(contract.parse_snapshot(data), received_at=generated)

    def test_migration_from_v1_keeps_every_existing_row(self):
        with closing(sqlite3.connect(self.path, isolation_level=None)) as db:       # a v0.5.3 database
            db.execute('CREATE TABLE companion_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            for statement in cs.MIGRATIONS[1]:
                db.execute(statement)
            db.execute("INSERT INTO companion_meta VALUES ('schema_version', '1')")
            db.execute("INSERT INTO companion_runs(received_at, status) VALUES ('2026-11-06T02:31:48+00:00', 'ok')")
            db.execute("INSERT INTO companion_items(uid, course_uid, section_uid, kind, title, first_run, last_seen_run, "
                       "last_seen_at) VALUES (?, 'moodle:course:7653', 's', 'assign', 'Antigo', 1, 1, 'x')", (M('90001'),))
        store = self.store()
        with closing(sqlite3.connect(self.path)) as db:
            version = db.execute("SELECT value FROM companion_meta WHERE key = 'schema_version'").fetchone()[0]
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            kept = db.execute('SELECT title FROM companion_items').fetchall()
            runs = db.execute('SELECT COUNT(*) FROM companion_runs').fetchone()[0]
        self.assertEqual(version, '2')
        self.assertLessEqual({'companion_details', 'companion_detail_history'}, tables)
        self.assertEqual((kept, runs), ([('Antigo',)], 1))
        self.assertEqual(store.migrate(), 2)                                         # idempotent

    def v1_database(self):
        with closing(sqlite3.connect(self.path, isolation_level=None)) as db:
            db.execute('CREATE TABLE companion_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            for statement in cs.MIGRATIONS[1]:
                db.execute(statement)
            db.execute("INSERT INTO companion_meta VALUES ('schema_version', '1')")
            db.execute("INSERT INTO companion_runs(received_at, status) VALUES ('2026-11-06T02:31:48+00:00', 'ok')")

    def test_an_older_schema_is_backed_up_and_verified_before_the_upgrade(self):
        self.v1_database()
        folder = Path(self.tmp.name) / 'backup'
        cs.SnapshotStore(self.path, allowed_courses=['7653'], backup_before_upgrade=folder)
        copies = list(folder.glob('live-*.db'))
        self.assertEqual(len(copies), 1)
        with closing(sqlite3.connect(copies[0])) as db:                  # the copy is the v1 database, intact
            self.assertEqual(db.execute("SELECT value FROM companion_meta WHERE key = 'schema_version'").fetchone()[0], '1')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM companion_runs').fetchone()[0], 1)
        cs.SnapshotStore(self.path, allowed_courses=['7653'], backup_before_upgrade=folder)
        self.assertEqual(len(list(folder.glob('live-*.db'))), 1)        # already v2: no new copy
        fresh = Path(self.tmp.name) / 'novo.db'
        cs.SnapshotStore(fresh, allowed_courses=['7653'], backup_before_upgrade=Path(self.tmp.name) / 'b2')
        self.assertFalse((Path(self.tmp.name) / 'b2').exists())          # a new database has nothing to protect

    def test_no_backup_no_upgrade(self):
        self.v1_database()
        blocker = Path(self.tmp.name) / 'arquivo'
        blocker.write_text('x', encoding='utf-8')                        # the backup folder cannot be created
        with self.assertRaises(cs.StoreError) as raised:
            cs.SnapshotStore(self.path, allowed_courses=['7653'], backup_before_upgrade=blocker / 'backup')
        self.assertEqual(raised.exception.code, 'backup_antes_da_migracao_falhou')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT value FROM companion_meta WHERE key = 'schema_version'").fetchone()[0], '1')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertNotIn('companion_details', tables)

    def test_details_are_stored_once_updated_in_place_and_their_history_kept(self):
        store = self.store()
        self.save(store, VARIETY)
        row = store.details(M('90007'))
        self.assertEqual((row['due_at'], row['cutoff_at'], row['submission_state'], row['verified_at'], row['timezone']),
                         ('2026-11-01T23:59', '2026-11-03T23:59', 'sem_envio', CHECKED, 'America/Sao_Paulo'))
        self.assertEqual(len(store.details()), 5)                                     # groupselect/material: none
        self.assertEqual(len(store.detail_history(M('90007'))), 1)
        self.save(store, VARIETY, generated='2026-11-10T11:40:00Z')                   # same facts: no new history
        self.assertEqual(len(store.detail_history(M('90007'))), 1)
        self.assertEqual(store.details(M('90007'))['verified_at'], CHECKED)           # checked_at comes from the page
        changed = dict(VARIETY)
        changed['90007'] = ([due('2026-11-20T23:59')], 'enviado', detail(submission='enviado', checked='2026-11-10T11:50:00Z'))
        self.save(store, changed, generated='2026-11-10T11:50:00Z')
        history = store.detail_history(M('90007'))
        self.assertEqual([h['due_at'] for h in history], ['2026-11-01T23:59', '2026-11-20T23:59'])
        self.assertEqual(store.details(M('90007'))['submission_state'], 'enviado')
        self.assertEqual(len(store.details()), 5)                                     # updated, never duplicated
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT submission FROM companion_items WHERE uid = ?', (M('90007'),)).fetchone()[0],
                             'enviado')

    def test_a_failed_page_keeps_what_was_known_and_records_the_attempt(self):
        store = self.store()
        self.save(store, VARIETY)
        failed = dict(VARIETY)
        failed['90001'] = ([], 'desconhecido', detail('inacessivel', checked='2026-11-10T12:30:00Z'))
        self.save(store, failed, generated='2026-11-10T12:30:00Z')
        row = store.details(M('90001'))
        self.assertEqual((row['due_at'], row['submission_state'], row['verified_at']), ('2098-12-31T23:59', 'sem_envio', CHECKED))
        self.assertEqual((row['last_check_result'], row['last_check_at']), ('inacessivel', '2026-11-10T12:30:00Z'))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT submission FROM companion_items WHERE uid = ?', (M('90001'),)).fetchone()[0],
                             'nao_enviado')                                          # not erased by the failure
        other = Path(self.tmp.name) / 'outro.db'                                       # a page that never worked
        first_fail = cs.SnapshotStore(other, allowed_courses=['7653'])
        data = with_details(snapshot_dict(), {'90001': ([], 'desconhecido', detail('tempo_esgotado'))})
        first_fail.save(contract.parse_snapshot(data), received_at=CHECKED)
        row = first_fail.details(M('90001'))
        self.assertEqual((row['verified_at'], row['due_state'], row['submission_state']), ('', 'nao_verificado', 'desconhecido'))

    def test_an_error_rolls_back_details_too(self):
        failing = cs.SnapshotStore(self.path, allowed_courses=['7653'])
        real_connect = failing._connect

        class Failing:
            def __init__(self, conn):
                self.conn = conn

            def execute(self, sql, *args):
                if 'UPDATE companion_runs SET novos' in sql:
                    raise sqlite3.OperationalError('falha simulada')
                return self.conn.execute(sql, *args)

            def close(self):
                self.conn.close()

        failing._connect = lambda: Failing(real_connect())
        with self.assertRaises(sqlite3.OperationalError):
            self.save(failing, VARIETY)
        self.assertEqual(self.store().details(), [])


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'live.db'
        self.store = cs.SnapshotStore(self.path, allowed_courses=['7653'])

    def view(self, now=NOW):
        return cv.load_view(self.path, now=now)

    def test_situations_order_and_counts_come_only_from_verified_pages(self):
        self.store.save(contract.parse_snapshot(with_details(snapshot_dict(generated=CHECKED), VARIETY)), received_at=CHECKED)
        view = self.view()
        by = {r.cmid: r for r in view.rows}
        self.assertEqual({c: by[c].situation for c in VARIETY},
                         {'90001': 'pendente', '90002': 'aguardando_avaliacao', '90003': 'pendente', '90005': 'concluida',
                          '90007': 'atrasada'})
        self.assertEqual((by['90006'].situation, by['90004'].situation), ('nao_se_aplica', 'nao_se_aplica'))
        self.assertEqual(by['90006'].due_text, '')                     # groupselect: shown as "não verificado" by the UI
        self.assertEqual((by['90007'].due_text, by['90007'].time_left), ('01/11/2026 23:59', 'venceu há 8 dia(s) e 9 h'))
        # 01/11 23:59 in São Paulo = 02/11 02:59 UTC; until 10/11 12:00 UTC = 8 days and 9 hours
        self.assertIn('data limite 03/11/2026 23:59', by['90007'].delivery_text)
        self.assertTrue(by['90003'].soon)
        self.assertEqual(by['90002'].delivery_text, 'Enviado para avaliação, não avaliado')
        self.assertEqual(by['90001'].verified_local, cv.to_local(CHECKED))
        self.assertEqual(view.confirmed_pending, 3)                    # 90001, 90003 pending + 90007 late
        self.assertEqual((view.overdue, view.awaiting, view.done, view.pending_soon), (1, 1, 1, 1))
        self.assertEqual((view.verified_activities, view.detail_candidates), (5, 5))
        order = [r.cmid for r in sorted(view.rows, key=cv.urgency)]
        self.assertEqual(order[:5], ['90007', '90003', '90001', '90002', '90005'])  # late, then by deadline, ..., done
        text = cv.status_text(view)
        self.assertIn('Prazos e entregas lidos nas páginas de 5 de 5', text)
        self.assertIn('Atrasadas: 1 • Pendentes: 2', text)

    def test_unknown_is_never_counted_as_zero_or_as_no_deadline(self):
        failed = {'90001': ([], 'desconhecido', detail('inacessivel')),
                  '90002': ([], 'nao_enviado', detail(due_state='sem_prazo'))}
        self.store.save(contract.parse_snapshot(with_details(snapshot_dict(generated=CHECKED), failed)), received_at=CHECKED)
        view = self.view()
        by = {r.cmid: r for r in view.rows}
        self.assertEqual((by['90001'].situation, by['90001'].due_text), ('nao_verificado', 'não verificado'))
        self.assertIn('página inacessível', by['90001'].check_note)
        self.assertEqual((by['90002'].situation, by['90002'].due_text, by['90002'].time_left), ('pendente', 'sem prazo definido', ''))
        self.assertEqual((by['90003'].situation, by['90003'].due_text), ('nao_verificado', 'não verificado'))
        self.assertEqual(view.confirmed_pending, 1)
        self.assertEqual((view.verified_activities, view.detail_candidates), (1, 5))
        self.assertIn('Não verificadas: 4', cv.status_text(view))

    def test_an_old_verification_is_shown_but_not_counted(self):
        self.store.save(contract.parse_snapshot(with_details(snapshot_dict(generated=CHECKED), VARIETY)), received_at=CHECKED)
        later = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
        view = self.view(later)
        by = {r.cmid: r for r in view.rows}
        self.assertEqual(by['90001'].situation, 'pendente')
        self.assertFalse(by['90001'].fresh)
        self.assertIn('mais de 24 h', by['90001'].check_note)
        self.assertEqual(view.confirmed_pending, 0)

    def test_a_database_without_the_new_tables_still_loads(self):
        legacy = Path(self.tmp.name) / 'v1.db'
        with closing(sqlite3.connect(legacy, isolation_level=None)) as db:
            for statement in cs.MIGRATIONS[1]:
                db.execute(statement)
            db.execute("INSERT INTO companion_runs(received_at, status, section_name, course_name) "
                       "VALUES ('2026-11-10T11:00:00Z', 'ok', 'Atividades Avaliativas', 'X')")
            db.execute("INSERT INTO companion_items(uid, course_uid, section_uid, kind, title, first_run, last_seen_run, "
                       "last_seen_at) VALUES (?, 'moodle:course:7653', '', 'assign', 'Antigo', 1, 1, '2026-11-10T11:00:00Z')",
                       (M('90001'),))
        view = cv.load_view(legacy, now=NOW)
        self.assertEqual((view.rows[0].situation, view.verified_activities), ('nao_verificado', 0))
        self.assertIn('Prazos: não verificados', cv.status_text(view))


if __name__ == '__main__':
    unittest.main()

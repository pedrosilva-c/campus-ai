"""Versioned academic data contract (campus-ai.academic/1). Fixtures are fictitious."""
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from campus_ai import contract as c
from campus_ai.authorized_courses import AuthorizedCourse
from campus_ai.pilot import PilotResult, PilotRow, MATERIAL_KINDS, ACTIVITY_KINDS

FIXTURE = Path(__file__).parent / 'fixtures' / 'contract' / 'snapshot_ficticio.json'
NOW = datetime(2026, 11, 5, 20, 0, tzinfo=timezone.utc)


def sample():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


class ParseSnapshotTests(unittest.TestCase):
    def test_fixture_round_trips(self):
        snap = c.parse_snapshot(sample())
        self.assertEqual(snap.schema, c.SCHEMA_ID)
        self.assertEqual(len(snap.courses), 1)
        self.assertEqual(snap.courses[0].uid, 'moodle:course:7653')
        again = c.parse_snapshot(json.loads(json.dumps(c.snapshot_to_dict(snap))))
        self.assertEqual(again, snap)

    def test_unknown_top_level_key_rejected(self):
        data = sample()
        data['command'] = 'run'
        with self.assertRaisesRegex(c.ContractError, 'campo desconhecido'):
            c.parse_snapshot(data)

    def test_unknown_record_key_rejected(self):
        data = sample()
        data['activities'][0]['script'] = 'alert(1)'
        with self.assertRaises(c.ContractError):
            c.parse_snapshot(data)

    def test_future_or_foreign_schema_rejected(self):
        for schema in ('campus-ai.academic/2', 'other/1', ''):
            data = sample()
            data['schema'] = schema
            with self.assertRaises(c.ContractError, msg=schema):
                c.parse_snapshot(data)

    def test_enums_are_closed(self):
        cases = [('activities', 'submission', 'pendente'), ('activities', 'verification', 'ok'),
                 ('materials', 'confidence', 'total'), ('courses', 'verification', 'completo')]
        for table, key, value in cases:
            data = sample()
            data[table][0][key] = value
            with self.assertRaises(c.ContractError, msg=(table, key, value)):
                c.parse_snapshot(data)

    def test_urls_restricted_to_aedb_without_private_query(self):
        bad = ['http://ead.aedb.br/ava/mod/assign/view.php?id=1',
               'https://ead.aedb.br.evil.test/ava/mod/assign/view.php?id=1',
               'https://user:pw@ead.aedb.br/ava/mod/assign/view.php?id=1',
               'https://ead.aedb.br:8443/ava/mod/assign/view.php?id=1',
               'https://ead.aedb.br/ava/mod/assign/view.php?id=1&sesskey=abc',
               'https://ead.aedb.br/ava/calendar/export_execute.php?userid=1&authtoken=x',
               'javascript:alert(1)']
        for url in bad:
            data = sample()
            data['activities'][0]['url'] = url
            with self.assertRaises(c.ContractError, msg=url):
                c.parse_snapshot(data)

    def test_uid_format_enforced(self):
        data = sample()
        data['materials'][0]['uid'] = '../../etc'
        with self.assertRaises(c.ContractError):
            c.parse_snapshot(data)

    def test_dangling_references_rejected(self):
        data = sample()
        data['activities'][0]['section_uid'] = 'moodle:course:7653:section:s-naoexiste'
        with self.assertRaisesRegex(c.ContractError, 'referência'):
            c.parse_snapshot(data)

    def test_record_outside_scope_rejected(self):
        data = sample()
        data['materials'][0]['course_uid'] = 'moodle:course:9999'
        with self.assertRaises(c.ContractError):
            c.parse_snapshot(data)

    def test_size_limits(self):
        data = sample()
        data['activities'][0]['title'] = 'x' * (c.MAX_TITLE + 1)
        with self.assertRaises(c.ContractError):
            c.parse_snapshot(data)
        data = sample()
        data['materials'] = [copy.deepcopy(data['materials'][0]) for _ in range(c.MAX_RECORDS + 1)]
        with self.assertRaises(c.ContractError):
            c.parse_snapshot(data)

    def test_dates_must_be_iso_and_aware_when_flagged(self):
        data = sample()
        data['activities'][0]['deadlines'][0]['at'] = '10/11/2026'
        with self.assertRaises(c.ContractError):
            c.parse_snapshot(data)
        data = sample()
        data['generated_at'] = '2026-11-05T20:00:00'  # observation times need a timezone
        with self.assertRaises(c.ContractError):
            c.parse_snapshot(data)

    def test_complete_coverage_with_zero_items_rejected(self):
        data = sample()
        data['materials'], data['activities'], data['events'] = [], [], []
        data['coverage']['state'] = 'completa'
        with self.assertRaisesRegex(c.ContractError, 'zero itens'):
            c.parse_snapshot(data)

    def test_non_object_rejected(self):
        for value in (None, [], 'x', 3):
            with self.assertRaises(c.ContractError):
                c.parse_snapshot(value)


class AssessmentFieldTests(unittest.TestCase):
    def test_old_snapshots_without_the_optional_fields_still_parse(self):
        snap = c.parse_snapshot(sample())
        self.assertEqual({a.assessment for a in snap.activities}, {''})
        self.assertIn('assessment', c.snapshot_to_dict(snap)['activities'][0])

    def test_group_and_basis_travel_together(self):
        for group, basis in (('AV1', ''), ('', 'titulo')):
            data = sample()
            data['activities'][0].update(assessment=group, assessment_basis=basis)
            with self.assertRaises(c.ContractError, msg=(group, basis)):
                c.parse_snapshot(data)
        data = sample()
        data['materials'][0].update(assessment='AV2', assessment_basis='posicao')
        self.assertEqual(c.parse_snapshot(data).materials[0].assessment, 'AV2')

    def test_group_vocabulary_is_closed(self):
        for bad in ('av1', 'AV0', 'AV10', 'Prova', ' AV1', 7):
            data = sample()
            data['activities'][0].update(assessment=bad, assessment_basis='titulo')
            with self.assertRaises(c.ContractError, msg=bad):
                c.parse_snapshot(data)
        data = sample()
        data['activities'][0].update(assessment='AV1', assessment_basis='adivinhado')
        with self.assertRaises(c.ContractError):
            c.parse_snapshot(data)

    def test_new_module_kinds_are_activities_and_not_assignments(self):
        data = sample()
        data['activities'][1].update(kind='groupselect',
                                     url='https://ead.aedb.br/ava/mod/groupselect/view.php?id=9003')
        item = next(i for i in c.to_academic_items(c.parse_snapshot(data)) if i.uid.endswith(':9003'))
        self.assertEqual(item.category, 'material')


class SemanticsTests(unittest.TestCase):
    def test_published_activity_is_not_pending(self):
        snap = c.parse_snapshot(sample())
        unknown = next(a for a in snap.activities if a.submission == 'desconhecido')
        self.assertEqual(c.pending_state(unknown, now=NOW), 'desconhecido')

    def test_pending_requires_explicit_not_submitted_and_confirmation(self):
        snap = c.parse_snapshot(sample())
        act = next(a for a in snap.activities if a.submission == 'nao_enviado')
        self.assertEqual(c.pending_state(act, now=NOW), 'pendente')
        partial = c.replace(act, verification='parcial')
        self.assertEqual(c.pending_state(partial, now=NOW), 'desconhecido')
        sent = c.replace(act, submission='enviado')
        self.assertEqual(c.pending_state(sent, now=NOW), 'nao_pendente')

    def test_stale_observation(self):
        snap = c.parse_snapshot(sample())
        act = next(a for a in snap.activities if a.submission == 'nao_enviado')
        later = NOW + c.DEFAULT_MAX_AGE + timedelta(minutes=1)
        self.assertEqual(c.effective_verification(act, now=later), 'desatualizado')
        self.assertEqual(c.pending_state(act, now=later), 'desconhecido')
        self.assertEqual(c.effective_verification(act, now=NOW), 'confirmado')

    def test_integration_error_is_not_absence(self):
        status = c.SourceStatus('gmail', '2026-11-05T19:00:00+00:00', '', 'erro_integracao', 'sem autorização')
        self.assertFalse(c.source_proves_absence(status))
        ok = c.SourceStatus('moodle_navegador', '2026-11-05T19:00:00+00:00', '2026-11-05T19:00:00+00:00',
                            'confirmado', '')
        self.assertFalse(c.source_proves_absence(ok, coverage='parcial'))
        self.assertTrue(c.source_proves_absence(ok, coverage='completa'))

    def test_kind_lists_extend_the_pilot_only_with_kinds_seen_on_the_real_site(self):
        self.assertEqual(c.MATERIAL_KINDS, MATERIAL_KINDS)
        self.assertTrue(ACTIVITY_KINDS <= c.ACTIVITY_KINDS)
        self.assertEqual(c.ACTIVITY_KINDS - ACTIVITY_KINDS, {'attendance', 'groupselect', 'msteams'})


class DateParsingTests(unittest.TestCase):
    def test_moodle_portuguese_dates(self):
        cases = {
            'Vencimento: segunda-feira, 10 nov. 2026, 23:59': ('2026-11-10T23:59', 'entrega'),
            'Prazo: 3 de dezembro de 2026, 08:00': ('2026-12-03T08:00', 'entrega'),
            'Fecha em: sexta, 7 nov 2026, 18:30': ('2026-11-07T18:30', 'fechamento'),
            'Abre: 1 out 2026': ('2026-10-01', 'abertura'),
        }
        for text, (iso, kind) in cases.items():
            d = c.deadline_from_text(text)
            self.assertEqual((d.at, d.kind, d.timezone_explicit), (iso, kind, False), text)

    def test_unparseable_kept_raw_without_date(self):
        d = c.deadline_from_text('Vencimento: em breve')
        self.assertEqual(d.at, '')
        self.assertEqual(d.raw, 'Vencimento: em breve')
        self.assertIsNone(c.deadline_from_text('Não informado'))
        self.assertIsNone(c.deadline_from_text(''))

    def test_invalid_calendar_date_not_invented(self):
        self.assertEqual(c.deadline_from_text('Vencimento: 31 fev 2026').at, '')


class PilotBridgeTests(unittest.TestCase):
    course = AuthorizedCourse('7653', 'Modelagem UML')

    def result(self, state='parcial', rows=None):
        rows = rows if rows is not None else [
            PilotRow('Modelagem UML', 'Seção', 'AV1', '', '', 'AV1'),
            PilotRow('Modelagem UML', 'Tarefa', 'Diagrama de casos de uso (fictício)',
                     'Vencimento: 10 nov 2026, 23:59', 'https://ead.aedb.br/ava/mod/assign/view.php?id=111',
                     'AV1', '111'),
            PilotRow('Modelagem UML', 'Arquivo', 'Apostila (fictícia)', 'Não informado',
                     'https://ead.aedb.br/ava/mod/resource/view.php?id=112', 'AV1', '112'),
            PilotRow('Modelagem UML', 'Questionário', 'Quiz sem link (fictício)', 'Não informado', '', 'AV2', ''),
        ]
        return PilotResult(rows, state, 'diagnóstico', notes=('Trilhas de Aprendizagem não examinada',))

    def test_maps_rows_to_contract(self):
        snap = c.from_pilot_result(self.result(), self.course, observed_at=NOW)
        self.assertEqual(snap.coverage.state, 'parcial')
        self.assertEqual([s.name for s in snap.sections], ['AV1', 'AV2'])
        act = next(a for a in snap.activities if a.title.startswith('Diagrama'))
        self.assertEqual(act.uid, 'moodle:course:7653:module:111')
        self.assertEqual(act.kind, 'assign')
        self.assertEqual(act.submission, 'desconhecido')  # the pilot never reads delivery state
        self.assertEqual(act.deadlines[0].at, '2026-11-10T23:59')
        self.assertEqual(snap.materials[0].kind, 'resource')
        nolink = next(a for a in snap.activities if a.kind == 'quiz')
        self.assertTrue(nolink.uid.startswith('moodle:course:7653:item:'))
        self.assertEqual(nolink.confidence, 'baixa')
        self.assertEqual(c.parse_snapshot(c.snapshot_to_dict(snap)), snap)

    def test_state_mapping(self):
        expected = {'completa': 'confirmado', 'parcial': 'confirmado', 'nao_validada': 'nao_verificado'}
        for state, verification in expected.items():
            snap = c.from_pilot_result(self.result(state), self.course, observed_at=NOW)
            self.assertEqual(snap.coverage.state, state)
            self.assertEqual(snap.activities[0].verification, verification, state)
        failed = c.from_pilot_result(PilotResult([], 'falhou', 'x'), self.course, observed_at=NOW)
        self.assertEqual(failed.coverage.state, 'falhou')
        self.assertEqual(failed.sources[0].status, 'erro_integracao')

    def test_empty_complete_pilot_downgraded(self):
        snap = c.from_pilot_result(self.result('completa', rows=[]), self.course, observed_at=NOW)
        self.assertEqual(snap.coverage.state, 'nao_validada')

    def test_to_academic_items_keeps_existing_uids(self):
        snap = c.from_pilot_result(self.result(), self.course, observed_at=NOW)
        items = {i.uid: i for i in c.to_academic_items(snap)}
        item = items['moodle:course:7653:module:111']
        self.assertEqual(item.category, 'assignment')
        self.assertEqual(item.status, 'unknown')
        self.assertEqual(item.due_iso, '2026-11-10T23:59')
        self.assertEqual(items['moodle:course:7653:module:112'].category, 'material')
        # Volatile facts (time of observation, coverage) must not enter the fingerprint, or every scan
        # would rewrite notes and re-alert "alterada".
        self.assertEqual(set(item.meta), {'courseid', 'moduleid', 'type'})
        later = c.from_pilot_result(self.result('completa'), self.course, observed_at=NOW + timedelta(hours=3))
        again = {i.uid: i for i in c.to_academic_items(later)}
        self.assertEqual(again[item.uid].fingerprint(), item.fingerprint())

    def test_to_academic_items_marks_pending_only_when_confirmed(self):
        snap = c.parse_snapshot(sample())
        items = {i.uid: i for i in c.to_academic_items(snap)}
        self.assertEqual(items['moodle:course:7653:module:9003'].status, 'pending')
        self.assertEqual(items['moodle:course:7653:module:9002'].status, 'unknown')
        self.assertEqual(items['moodle:course:7653:forum:9004'].category, 'announcement')


if __name__ == '__main__':
    unittest.main()

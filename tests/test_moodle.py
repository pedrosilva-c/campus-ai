import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from unittest.mock import patch
import requests

from campus_ai.config import Settings
from campus_ai.engine import run_scan
from campus_ai.moodle import MoodleClient
from campus_ai.obsidian import ObsidianWriter


class FakeResponse:
    is_redirect = False

    def __init__(self, value):
        self.value = value

    def raise_for_status(self):
        pass

    def json(self):
        return self.value


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def post(self, url, data, timeout, allow_redirects):
        self.calls.append((url, data, timeout, allow_redirects))
        value = self.responses[data['wsfunction']]
        if isinstance(value, Exception):
            raise value
        return FakeResponse(value)


class MoodleClientTests(unittest.TestCase):
    def test_valid_authorized_token_probe_reports_declared_functions(self):
        session = FakeSession({'core_webservice_get_site_info': {
            'userid': 7,
            'functions': [{'name': 'core_webservice_get_site_info'},
                          {'name': 'core_enrol_get_users_courses'}],
        }})
        client = MoodleClient('https://ead.aedb.br/ava/', 'fake-token', session)
        self.assertTrue(hasattr(client, 'probe'))
        access = client.probe()
        self.assertEqual(access.user_id, 7)
        self.assertIn('core_enrol_get_users_courses', access.available_functions)
        self.assertIn('core_course_get_contents', access.missing_functions)
        self.assertFalse(access.complete)
        self.assertEqual(len(session.calls), 1)

    def test_invalid_token_is_reported_without_echoing_it(self):
        session = FakeSession({'core_webservice_get_site_info': {
            'exception': 'moodle_exception', 'errorcode': 'invalidtoken',
            'message': 'fake-token',
        }})
        with self.assertRaises(RuntimeError) as error:
            MoodleClient('https://ead.aedb.br/ava', 'fake-token', session).probe()
        self.assertEqual(type(error.exception).__name__, 'MoodleAuthenticationError')
        self.assertNotIn('fake-token', str(error.exception))

    def test_unavailable_course_contents_marks_scan_partial(self):
        session = FakeSession({
            'core_webservice_get_site_info': {'userid': 7},
            'core_enrol_get_users_courses': [{'id': 12, 'fullname': 'Banco de Dados'}],
            'core_course_get_contents': {'exception': 'webservice_access_exception',
                                         'errorcode': 'accessexception'},
            'mod_assign_get_assignments': {'courses': []},
        })
        result = MoodleClient('https://ead.aedb.br/ava', 'fake-token', session).scan()
        self.assertFalse(result.complete)
        self.assertEqual(result.items, [])
        self.assertTrue(result.warnings)

    def test_course_without_activities_is_complete(self):
        session = FakeSession({
            'core_webservice_get_site_info': {'userid': 7},
            'core_enrol_get_users_courses': [{'id': 12, 'fullname': 'Banco de Dados'}],
            'core_course_get_contents': [{'modules': []}],
            'mod_assign_get_assignments': {'courses': []},
        })
        result = MoodleClient('https://ead.aedb.br/ava', 'fake-token', session).scan()
        self.assertTrue(result.complete)
        self.assertEqual(result.items, [])

    def test_section_without_modules_field_is_partial(self):
        session = FakeSession({
            'core_webservice_get_site_info': {'userid': 7},
            'core_enrol_get_users_courses': [{'id': 12, 'fullname': 'Banco de Dados'}],
            'core_course_get_contents': [{'name': 'Seção incompleta'}],
            'mod_assign_get_assignments': {'courses': []},
        })
        result = MoodleClient('https://ead.aedb.br/ava', 'fake-token', session).scan()
        self.assertFalse(result.complete)
        self.assertTrue(result.warnings)

    def test_recent_material_keeps_source_added_time(self):
        added = int((datetime.now(timezone.utc) - timedelta(hours=2)).timestamp())
        session = FakeSession({
            'core_webservice_get_site_info': {'userid': 7},
            'core_enrol_get_users_courses': [{'id': 12, 'fullname': 'Banco de Dados'}],
            'core_course_get_contents': [{'modules': [
                {'id': 31, 'modname': 'resource', 'name': 'Material novo', 'added': added},
            ]}],
            'mod_assign_get_assignments': {'courses': []},
        })
        result = MoodleClient('https://ead.aedb.br/ava', 'fake-token', session).scan()
        self.assertTrue(result.complete)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].uid, 'moodle:course:12:module:31')
        self.assertTrue(result.items[0].meta['source_added_iso'])

    def test_assignment_due_soon_keeps_deadline(self):
        due = int((datetime.now(timezone.utc) + timedelta(hours=36)).timestamp())
        session = FakeSession({
            'core_webservice_get_site_info': {'userid': 7},
            'core_enrol_get_users_courses': [{'id': 12, 'fullname': 'Banco de Dados'}],
            'core_course_get_contents': [{'modules': []}],
            'mod_assign_get_assignments': {'courses': [{'id': 12, 'assignments': [
                {'id': 42, 'cmid': 32, 'name': 'Prazo próximo', 'duedate': due},
            ]}]},
            'mod_assign_get_submission_status': {'lastattempt': {'submission': {'status': 'draft'}}},
        })
        result = MoodleClient('https://ead.aedb.br/ava', 'fake-token', session).scan()
        self.assertTrue(result.complete)
        self.assertEqual(result.items[0].status, 'pending')
        remaining = datetime.fromisoformat(result.items[0].due_iso) - datetime.now().astimezone()
        self.assertLess(remaining, timedelta(days=2))
        self.assertGreater(remaining, timedelta(days=1))

    def test_transient_connection_failure_is_sanitized(self):
        session = FakeSession({'core_webservice_get_site_info':
                               requests.ConnectionError('fake-token connection details')})
        with self.assertRaises(RuntimeError) as error:
            MoodleClient('https://ead.aedb.br/ava', 'fake-token', session).probe()
        self.assertEqual(type(error.exception).__name__, 'MoodleConnectionError')
        self.assertNotIn('fake-token', str(error.exception))

    def test_partial_scan_preserves_previous_note_and_dashboard(self):
        common = {
            'core_webservice_get_site_info': {'userid': 7},
            'core_enrol_get_users_courses': [{'id': 12, 'fullname': 'Banco de Dados'}],
        }
        full = FakeSession({**common,
            'core_course_get_contents': [{'modules': [
                {'id': 32, 'modname': 'assign', 'name': 'Trabalho', 'description': 'Texto completo'},
            ]}],
            'mod_assign_get_assignments': {'courses': [{'id': 12, 'assignments': [
                {'id': 42, 'cmid': 32, 'name': 'Trabalho', 'intro': 'Texto completo',
                 'duedate': 1760000000},
            ]}]},
            'mod_assign_get_submission_status': {'lastattempt': {'submission': {'status': 'submitted'}}},
        })
        partial = FakeSession({**common,
            'core_course_get_contents': [{'modules': [
                {'id': 32, 'modname': 'assign', 'name': 'Trabalho', 'description': 'Texto truncado'},
                {'id': 33, 'modname': 'resource', 'name': 'Novo material'},
            ]}],
            'mod_assign_get_assignments': RuntimeError('function unavailable'),
        })
        clients = [MoodleClient('https://ead.aedb.br/ava', 'fake-token', full),
                   MoodleClient('https://ead.aedb.br/ava', 'fake-token', partial)]
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(mode='live', vault_path=directory)
            with patch('campus_ai.engine.app_dir', return_value=Path(directory)), \
                 patch('campus_ai.security.get_secret', return_value='fake-token'), \
                 patch('campus_ai.gmail.gmail_enabled', return_value=False), \
                 patch('campus_ai.moodle.MoodleClient', side_effect=clients):
                first = run_scan(settings)
                writer = ObsidianWriter(directory)
                old_note = writer.filename_for(first.items[0])
                original_note = old_note.read_text(encoding='utf8')
                dashboard = writer.root / 'Painel Acadêmico.md'
                original_dashboard = dashboard.read_text(encoding='utf8')
                second = run_scan(settings)
            self.assertTrue(any('Prazos/entregas' in w for w in second.warnings))
            self.assertEqual(old_note.read_text(encoding='utf8'), original_note)
            self.assertEqual(dashboard.read_text(encoding='utf8'), original_dashboard)
            self.assertEqual(len(second.new_items), 1)
            self.assertEqual(second.new_items[0].uid, 'moodle:course:12:module:33')

    def test_courses_materials_deadlines_and_submission_from_mock_api(self):
        session = FakeSession({
            'core_webservice_get_site_info': {'userid': 7},
            'core_enrol_get_users_courses': [{'id': 12, 'fullname': 'Banco de Dados'}],
            'core_course_get_contents': [{'modules': [
                {'id': 31, 'modname': 'resource', 'name': 'Aula 1',
                 'contents': [{'filename': 'roteiro.pdf'}]},
                {'id': 32, 'modname': 'assign', 'name': 'Trabalho'},
            ]}],
            'mod_assign_get_assignments': {'courses': [{'id': 12, 'assignments': [
                {'id': 42, 'cmid': 32, 'name': 'Trabalho', 'duedate': 1760000000},
            ]}]},
            'mod_assign_get_submission_status': {'lastattempt': {'submission': {'status': 'submitted'}}},
        })
        result = MoodleClient('https://ead.aedb.br/ava', 'fake-token', session).scan()
        self.assertEqual(result.warnings, [])
        self.assertEqual(len(result.items), 2)
        material = next(i for i in result.items if i.category == 'material')
        assignment = next(i for i in result.items if i.category == 'assignment')
        self.assertIn('roteiro.pdf', material.description)
        self.assertEqual(assignment.status, 'submitted')
        self.assertTrue(assignment.due_iso)
        self.assertEqual(assignment.uid, 'moodle:course:12:module:32')
        self.assertTrue(all(c[3] is False for c in session.calls))
        self.assertTrue(all(c[0].startswith('https://ead.aedb.br/ava/webservice/') for c in session.calls))

    def test_partial_assignment_failure_keeps_materials(self):
        session = FakeSession({
            'core_webservice_get_site_info': {'userid': 7},
            'core_enrol_get_users_courses': [{'id': 12, 'fullname': 'Banco de Dados'}],
            'core_course_get_contents': [{'modules': [
                {'id': 31, 'modname': 'resource', 'name': 'Aula 1'},
            ]}],
            'mod_assign_get_assignments': RuntimeError('not permitted'),
        })
        result = MoodleClient('https://ead.aedb.br/ava', 'fake-token', session).scan()
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].status, 'unknown')
        self.assertEqual(len(result.warnings), 1)
        self.assertIn('confirme no AVA', result.warnings[0])

    def test_invalid_url_and_api_error_do_not_disclose_token(self):
        with self.assertRaises(ValueError):
            MoodleClient('http://ead.aedb.br/ava', 'fake-token')
        session = FakeSession({'core_webservice_get_site_info': {'exception': 'fake-token'}})
        with self.assertRaises(RuntimeError) as error:
            MoodleClient('https://ead.aedb.br/ava', 'fake-token', session).scan()
        self.assertNotIn('fake-token', str(error.exception))


if __name__ == '__main__':
    unittest.main()

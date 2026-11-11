import tempfile
import sqlite3
from contextlib import closing
import unittest
from pathlib import Path
from unittest.mock import patch

from campus_ai.config import Settings
from campus_ai.engine import run_scan
from campus_ai.gmail import GMAIL_SCOPE, is_important, scan_gmail


class FakeRequest:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeMessages:
    def __init__(self):
        self.snippet = 'Confira o calendário atualizado.'
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(('list', kwargs))
        return FakeRequest({'messages': [{'id': 'mail-1', 'threadId': 'thread-1'}]})

    def get(self, **kwargs):
        self.calls.append(('get', kwargs))
        return FakeRequest({'payload': {'headers': [
            {'name': 'Subject', 'value': 'Comunicado: prazo de matrícula'},
            {'name': 'From', 'value': 'secretaria@example.invalid'},
        ]}, 'snippet': self.snippet})


class FakeGmailService:
    def __init__(self):
        self.api = FakeMessages()

    def users(self):
        return self

    def messages(self):
        return self.api


class GmailTests(unittest.TestCase):
    def test_readonly_scope_and_metadata_request(self):
        self.assertEqual(GMAIL_SCOPE, ['https://www.googleapis.com/auth/gmail.readonly'])
        service = FakeGmailService()
        items = scan_gmail('newer_than:14d', service=service)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].meta['important'])
        self.assertEqual(service.api.calls[0][1]['q'], 'newer_than:14d')
        self.assertEqual(service.api.calls[1][1]['format'], 'metadata')
        self.assertFalse(is_important('Mensagem comum'))
        self.assertTrue(is_important('Mensagem comum', ['IMPORTANT']))

    def test_important_message_alerts_only_once_even_if_preview_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            service = FakeGmailService()
            settings = Settings(mode='live', vault_path=directory)
            with patch('campus_ai.config.app_dir', return_value=Path(directory)), \
                 patch('campus_ai.engine.app_dir', return_value=Path(directory)), \
                 patch('campus_ai.security.get_secret', return_value=None), \
                 patch('campus_ai.gmail.gmail_enabled', return_value=True), \
                 patch('campus_ai.gmail.scan_gmail', side_effect=lambda *args: scan_gmail(*args, service=service)):
                first = run_scan(settings)
                second = run_scan(settings)
                service.api.snippet = 'Prévia atualizada.'
                third = run_scan(settings)
            self.assertEqual(len(first.important_items), 1)
            self.assertEqual(len(second.important_items), 0)
            self.assertEqual(len(third.important_items), 0)
            self.assertEqual(len(third.new_items), 1)
            self.assertTrue((Path(directory) / 'Campus AI' / 'Emails' /
                             'E-mail-Institucional').is_dir())
            with closing(sqlite3.connect(Path(directory) / 'live.db')) as db:
                runs = db.execute('SELECT item_count, changed_count FROM scan_runs ORDER BY id').fetchall()
            self.assertEqual(runs, [(1, 1), (1, 0), (1, 1)])


if __name__ == '__main__':
    unittest.main()

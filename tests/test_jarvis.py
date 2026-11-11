import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

# The pilot tests reuse test_moodle_browser's fixtures; make them importable also when this module runs alone
# (python -m unittest tests.test_jarvis), not only under "discover -s tests". Same pattern as the other modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from campus_ai.config import Settings
from campus_ai.models import AcademicItem
from campus_ai.engine import ScanResult
from campus_ai.state import History


class JarvisTests(unittest.TestCase):
    def test_notifications_deduplicate_across_restart_and_track_changes(self):
        from campus_ai.notifications import collect_alerts
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.db'
            now = datetime.now(timezone.utc)
            item = AcademicItem('x', 'moodle', 'assignment', 'Trabalho', due_iso=(now + timedelta(hours=4)).isoformat())
            result = ScanResult([item], [item], [], 1, [])
            self.assertEqual(len(collect_alerts(History(path), result, now=now)), 2)
            self.assertEqual(collect_alerts(History(path), result, now=now), [])
            item.title = 'Trabalho alterado'
            self.assertEqual(len(collect_alerts(History(path), result, now=now)), 1)
            self.assertEqual(len(History(path).recent_alerts()), 3)

    def test_submitted_or_invalid_deadline_has_no_due_alert(self):
        from campus_ai.notifications import collect_alerts
        with tempfile.TemporaryDirectory() as directory:
            items = [AcademicItem('1', 'moodle', 'assignment', 'Enviado', status='submitted', due_iso=datetime.now(timezone.utc).isoformat()),
                     AcademicItem('2', 'moodle', 'assignment', 'Inválido', due_iso='?')]
            self.assertEqual(collect_alerts(History(Path(directory) / 'state.db'), ScanResult(items, [], [], 0, [])), [])

    def test_ai_requires_per_request_consent_and_never_persists(self):
        from campus_ai.intelligence import StudyAssistant, Consent, StudyRequest
        provider = Mock(name='provider')
        provider.name = 'approved-provider'
        provider.generate.return_value = 'Resposta simulada'
        service = StudyAssistant(provider)
        request = StudyRequest('Explique', 'Conteúdo de fixture')
        with self.assertRaises(PermissionError):
            service.generate(request, None)
        provider.generate.assert_not_called()
        consent = Consent(provider.name, request.digest())
        response = service.generate(request, consent)
        self.assertIn('revisão', response.lower())
        with self.assertRaises(PermissionError):
            service.generate(StudyRequest('Outra pergunta', 'Outro documento'), consent)

    def test_periodic_defaults_off_and_interval_validated(self):
        self.assertFalse(Settings().periodic_enabled)
        with tempfile.TemporaryDirectory() as directory, patch('campus_ai.config.app_dir', return_value=Path(directory)):
            with self.assertRaises(ValueError):
                Settings(periodic_minutes=0).save()

    def test_pilot_reads_one_course_and_preserves_partial_semantics(self):
        from test_moodle_browser import FakePage, BASE, HOME, COURSE, EMPTY
        from campus_ai.moodle_browser import MoodleBrowserClient
        page = FakePage({BASE + '/my/': HOME, BASE + '/course/view.php?id=10': COURSE,
                         BASE + '/course/view.php?id=20': EMPTY})
        result = MoodleBrowserClient(BASE, page=page).scan(max_courses=1)
        self.assertFalse(result.complete)
        self.assertEqual(len(result.items), 2)
        self.assertNotIn(BASE + '/course/view.php?id=20', page.visited)

    def test_cancelled_scan_does_not_navigate(self):
        from campus_ai.moodle_browser import MoodleBrowserClient
        page = Mock()
        result = MoodleBrowserClient('https://example.test/ava', page=page).scan(cancelled=lambda: True)
        self.assertFalse(result.complete)
        page.goto.assert_not_called()

    def test_pilot_cannot_follow_pagination_into_another_course(self):
        from test_moodle_browser import FakePage, BASE, HOME, COURSE
        from campus_ai.moodle_browser import MoodleBrowserClient
        course = COURSE + '<a rel="next" href="/ava/course/view.php?id=20">Outra</a>'
        page = FakePage({BASE + '/my/': HOME, BASE + '/course/view.php?id=10': course})
        MoodleBrowserClient(BASE, page=page).scan(max_courses=1)
        self.assertNotIn(BASE + '/course/view.php?id=20', page.visited)

    def test_notes_include_metadata_and_preserve_legacy_path(self):
        from campus_ai.obsidian import ObsidianWriter
        with tempfile.TemporaryDirectory() as directory:
            item = AcademicItem('x', 'moodle', 'material', 'Aula', 'Disciplina', 'Conteúdo',
                                meta={'teacher': 'Docente de fixture', 'source_added_iso': '2026-10-14'})
            writer = ObsidianWriter(directory)
            path = writer.sync_item(item)
            self.assertEqual(path.parent.name, 'Materiais')
            self.assertIn('Docente de fixture', path.read_text(encoding='utf-8'))
            legacy = path.parent.parent / path.name
            path.rename(legacy)
            item.title = 'Aula renomeada'
            self.assertEqual(writer.sync_item(item), legacy)

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from campus_ai.moodle_browser import MoodleBrowserClient, SessionExpired, BrowserScan, PortalBlocked
from campus_ai.config import Settings
from campus_ai.engine import run_scan
from campus_ai.models import AcademicItem
from campus_ai.obsidian import ObsidianWriter


BASE = 'https://ead.aedb.br/ava'
HOME = '<html><nav class="usermenu"><a href="/ava/login/logout.php">Sair</a></nav><a href="/ava/course/view.php?id=10">Banco de Dados</a><a href="/ava/course/view.php?id=20">Vazia</a></html>'
COURSE = '''<html><nav class="usermenu">Aluno</nav><section class="section" data-sectionid="3"><h3>Semana 1</h3>
<div class="activity" data-cmid="81"><a href="/ava/mod/resource/view.php?id=81">Slides</a><time datetime="2026-10-12T10:00:00-03:00"></time></div>
<div class="activity" data-cmid="82"><a href="/ava/mod/assign/view.php?id=82">Trabalho</a><time datetime="2026-10-15T23:59:00-03:00"></time><span>Não enviado</span></div>
</section></html>'''
EMPTY = '<html><nav class="usermenu">Aluno</nav><section class="section"><h3>Introdução</h3></section></html>'
LOGIN = '<html><form id="login"><input name="username"><input type="password"></form></html>'


class FakePage:
    def __init__(self, pages):
        self.pages = pages
        self.url = ''
        self.visited = []

    def goto(self, url, **kwargs):
        self.url = url
        self.visited.append(url)
        value = self.pages.get(url)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise TimeoutError('simulated timeout')
        self.html = value

    def content(self):
        return self.html


class LoggedInPage(FakePage):
    def goto(self, url, **kwargs):
        super().goto(url, **kwargs)
        self.url = BASE + '/my/'
        self.html = HOME


class BrowserTests(unittest.TestCase):
    def client(self, pages):
        return MoodleBrowserClient(BASE, page=FakePage(pages), delay_seconds=0)

    def test_valid_session_and_academic_items(self):
        client = self.client({BASE + '/my/': HOME, BASE + '/course/view.php?id=10': COURSE,
                              BASE + '/course/view.php?id=20': EMPTY})
        self.assertTrue(client.check_session())
        result = client.scan()
        self.assertTrue(result.complete)
        self.assertEqual({i.uid for i in result.items}, {'moodle:course:10:module:81', 'moodle:course:10:module:82'})
        task = next(i for i in result.items if i.category == 'assignment')
        self.assertEqual(task.status, 'pending')
        self.assertEqual(task.due_iso, '2026-10-15T23:59:00-03:00')
        material = next(i for i in result.items if i.category == 'material')
        self.assertEqual(material.meta['source_added_iso'], '2026-10-12T10:00:00-03:00')
        self.assertIn(BASE + '/course/view.php?id=20', client.page.visited)

    def test_login_required(self):
        client = self.client({BASE + '/my/': LOGIN})
        self.assertFalse(client.check_session())
        with self.assertRaises(SessionExpired):
            client.scan()

    def test_manual_login_detects_authenticated_page(self):
        page = LoggedInPage({BASE + '/my/': HOME})
        client = MoodleBrowserClient(BASE, page=page, delay_seconds=0)
        self.assertTrue(client.connect(wait_seconds=1))
        self.assertEqual(page.visited, [BASE + '/my/'])

    def test_navigation_interrupted_is_partial(self):
        client = self.client({BASE + '/my/': HOME, BASE + '/course/view.php?id=10': COURSE,
                              BASE + '/course/view.php?id=20': TimeoutError()})
        result = client.scan()
        self.assertFalse(result.complete)
        self.assertEqual(len(result.items), 2)
        self.assertTrue(result.warnings)

    def test_pagination_and_sensitive_query_removed(self):
        first = COURSE.replace('</section>', '</section><a rel="next" href="/ava/course/view.php?id=10&page=2&sesskey=SECRET">Próxima</a>')
        second = '<html><nav class="usermenu">Aluno</nav><section class="section"><div class="activity" data-cmid="83"><a href="/ava/mod/page/view.php?id=83&sesskey=SECRET">Texto</a></div></section></html>'
        client = self.client({BASE + '/my/': HOME.replace('<a href="/ava/course/view.php?id=20">Vazia</a>', ''),
                              BASE + '/course/view.php?id=10': first,
                              BASE + '/course/view.php?id=10&page=2': second})
        result = client.scan()
        self.assertTrue(result.complete)
        self.assertEqual(len(result.items), 3)
        self.assertNotIn('SECRET', str(result))
        self.assertNotIn('SECRET', str(client.page.visited))

    def test_unrecognized_course_structure_is_partial(self):
        client = self.client({BASE + '/my/': HOME, BASE + '/course/view.php?id=10': '<nav class="usermenu">Aluno</nav>',
                              BASE + '/course/view.php?id=20': EMPTY})
        self.assertFalse(client.scan().complete)

    def test_explicit_portal_block_stops_scan(self):
        client = self.client({BASE + '/my/': HOME, BASE + '/course/view.php?id=10':
                              '<html><p>Acesso automatizado bloqueado</p></html>'})
        with self.assertRaises(PortalBlocked):
            client.scan()

    def test_profile_defaults_outside_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            from unittest.mock import patch
            with patch('campus_ai.moodle_browser.app_dir', return_value=Path(directory)):
                client = MoodleBrowserClient(BASE)
            self.assertEqual(client.profile_dir, Path(directory) / 'browser_profile')

    def test_disconnect_removes_only_dedicated_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / 'browser_profile'
            profile.mkdir()
            (profile / 'session').write_text('fixture', encoding='utf-8')
            (root / 'keep.txt').write_text('keep', encoding='utf-8')
            with patch('campus_ai.moodle_browser.app_dir', return_value=root):
                MoodleBrowserClient(BASE, profile_dir=profile).disconnect()
            self.assertFalse(profile.exists())
            self.assertTrue((root / 'keep.txt').exists())

    def test_partial_scan_preserves_previous_note(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(mode='live', moodle_method='browser', vault_path=directory)
            item = AcademicItem('moodle:course:10:module:81', 'moodle', 'material', 'Slides', 'Banco de Dados')
            partial = AcademicItem(item.uid, 'moodle', 'material', 'Slides', 'Banco de Dados', 'Resposta incompleta')
            with patch('campus_ai.engine.app_dir', return_value=Path(directory)), \
                 patch('campus_ai.moodle_browser.MoodleBrowserClient.scan', side_effect=[
                     BrowserScan([item], [], True), BrowserScan([partial], ['Falha de navegação'], False)]), \
                 patch('campus_ai.gmail.gmail_enabled', return_value=False):
                first = run_scan(settings)
                note = ObsidianWriter(directory).filename_for(item)
                before = note.read_text(encoding='utf-8')
                second = run_scan(settings)
            self.assertEqual(len(first.new_items), 1)
            self.assertFalse(second.new_items)
            self.assertEqual(note.read_text(encoding='utf-8'), before)
            self.assertTrue(any('parcial' in warning.lower() for warning in second.warnings))


if __name__ == '__main__':
    unittest.main()

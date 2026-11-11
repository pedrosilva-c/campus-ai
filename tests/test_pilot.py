"""Pilot contract tests with synthetic projections, no accounts or network."""
import unittest
from unittest.mock import Mock, patch
from campus_ai.pilot import PilotReader, PilotLimits, PilotRejected, course_url

URL = 'https://ead.aedb.br/ava/course/view.php?id=42'

def snapshot(title='Disciplina fictícia', **changes):
    value = dict(url=URL, doc_title='', title_candidates=[dict(source='header_h1', text=title)],
                 sections=[dict(key='0:s', name='Aula fictícia', state='open', items=2)],
                 ids=dict(body='42', cfg='42'), diag=dict(ready='complete'),
                 authenticated=True, blocked=False,
                 login=False, recognized=True, truncated=False, rows=[
                     dict(kind='Seção', title='Aula fictícia', due='', url=''),
                     dict(kind='resource', title='Slides fictícios', due='', url='/ava/mod/resource/view.php?id=7&sesskey=SECRET'),
                     dict(kind='assign', title='Exercício fictício', due='Vencimento: 20/10/2026, 23:59', url='/ava/mod/assign/view.php?id=8')])
    value.update(changes)
    return value

class PilotTests(unittest.TestCase):
    def setUp(self):
        self.page = Mock()
        self.page.url = URL
        self.page.is_closed.return_value = False
        self.cdp = Mock()
        self.cdp.send.return_value = {'result': {'value': snapshot()}}
        self.reader = PilotReader(self.page, self.cdp)

    def test_manual_selection_and_read_preserve_page(self):
        chosen = self.reader.select()
        result = self.reader.read(chosen)
        self.assertEqual(chosen.title, 'Disciplina fictícia')
        self.assertEqual(result.state, 'completa')
        self.assertEqual(result.rows[1].due, 'Não informado')
        self.assertEqual(result.rows[2].due, 'Vencimento: 20/10/2026, 23:59')
        self.assertNotIn('SECRET', str(result))
        self.page.goto.assert_not_called()
        self.page.click.assert_not_called()
        self.page.close.assert_not_called()
        self.page.content.assert_not_called()

    def test_fixture_html_projected_fields_are_transformed(self):
        # The transport is a fake projection, not a real DOM/visibility test.
        # Actual selector coverage lives in the opt-in test_pilot_dom_smoke.
        from pathlib import Path
        from campus_ai.moodle_browser import Document
        html = Path('tests/fixtures/pilot_course.html').read_text(encoding='utf-8')
        root = Document(html).root
        title = next(n.text() for n in root.nodes() if n.tag == 'h1')
        data = snapshot(title=title)
        self.cdp.send.return_value = {'result': {'value': data}}
        result = self.reader.read(self.reader.select())
        self.assertEqual(result.rows[0].course, title)
        self.assertEqual(result.rows[1].title, 'Slides fictícios')

    def test_failure_during_read_discards_data(self):
        selected = self.reader.select()
        self.cdp.send.side_effect = RuntimeError('Target closed with SECRET')
        with self.assertRaises(PilotRejected) as caught:
            self.reader.read(selected)
        self.assertNotIn('SECRET', str(caught.exception))

    def test_total_timeout_discards_data(self):
        with patch('campus_ai.pilot.time.monotonic', side_effect=[0, 100]):
            with self.assertRaises(PilotRejected):
                self.reader.select()

    def test_domains_and_unexpected_urls_rejected(self):
        for url in ('https://evil.test/ava/course/view.php?id=42',
                    'https://ead.aedb.br.evil.test/ava/course/view.php?id=42',
                    'http://ead.aedb.br/ava/course/view.php?id=42',
                    'https://ead.aedb.br/other/course/view.php?id=42',
                    URL + '&id=43', URL + '&redirect=https://evil.test',
                    'https://user@ead.aedb.br/ava/course/view.php?id=42',
                    'https://ead.aedb.br/ava/mod/assign/view.php?id=42'):
            with self.subTest(url=url), self.assertRaises(PilotRejected):
                course_url(url)

    def test_clean_course_url(self):
        self.assertEqual(course_url(URL + '&sesskey=SECRET#section-1'), URL)

    def test_course_changed_after_confirmation(self):
        chosen = self.reader.select()
        self.page.url = URL.replace('42', '43')
        with self.assertRaises(PilotRejected):
            self.reader.read(chosen)

    def test_snapshot_navigation_race_discarded(self):
        chosen = self.reader.select()
        self.cdp.send.return_value = {'result': {'value': snapshot(url=URL.replace('42', '43'))}}
        with self.assertRaises(PilotRejected):
            self.reader.read(chosen)

    def test_empty_recognized_course(self):
        self.cdp.send.return_value = {'result': {'value': snapshot(rows=[])}}
        result = self.reader.read(self.reader.select())
        # An open section with nothing extracted is not proof of an empty course.
        self.assertEqual((result.state, result.rows), ('nao_validada', []))

    def test_unrecognized_structure_is_partial(self):
        chosen = self.reader.select()
        self.cdp.send.return_value = {'result': {'value': snapshot(recognized=False, rows=[])}}
        self.assertEqual(self.reader.read(chosen).state, 'nao_validada')

    def test_expired_login_and_block_stop_without_details(self):
        for values in (dict(login=True), dict(authenticated=False), dict(blocked=True)):
            self.cdp.send.return_value = {'result': {'value': snapshot(**values)}}
            with self.assertRaises(PilotRejected):
                self.reader.select()

    def test_closed_browser(self):
        self.page.is_closed.return_value = True
        with self.assertRaises(PilotRejected):
            self.reader.select()
        self.cdp.send.assert_not_called()

    def test_timeout(self):
        self.cdp.send.side_effect = TimeoutError('SECRET URL')
        with self.assertRaises(PilotRejected) as caught:
            self.reader.select()
        self.assertNotIn('SECRET', str(caught.exception))

    def test_cancel_before_and_after_snapshot(self):
        with self.assertRaises(PilotRejected):
            self.reader.select(cancelled=lambda: True)
        self.cdp.send.assert_not_called()
        checks = iter((False, True))
        with self.assertRaises(PilotRejected):
            self.reader.select(cancelled=lambda: next(checks))

    def test_element_limit_partial(self):
        self.cdp.send.return_value = {'result': {'value': snapshot(truncated=True)}}
        self.assertEqual(self.reader.read(self.reader.select()).state, 'parcial')

    def test_no_external_reference(self):
        self.cdp.send.return_value = {'result': {'value': snapshot(rows=[dict(kind='resource', title='X', due='', url='https://evil.test/file.pdf')])}}
        self.assertEqual(self.reader.read(self.reader.select()).rows[0].url, '')

    def test_limits_are_conservative(self):
        with self.assertRaises(ValueError):
            PilotLimits(max_elements=10000000)

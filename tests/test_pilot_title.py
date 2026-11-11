"""Course-title recognition across Moodle themes. Synthetic projections only."""
import unittest
from unittest.mock import Mock, patch
from campus_ai.pilot import (PilotReader, PilotLimits, PilotRejected, PilotSelection,
                             resolve_title, clean_title, kind_label)

URL = 'https://ead.aedb.br/ava/course/view.php?id=42'
COURSE = '4º P CURSO FICTÍCIO - Modelagem Fictícia'


def c(source, text):
    return {'source': source, 'text': text}


def snap(candidates, doc_title='', **changes):
    value = dict(url=URL, doc_title=doc_title, title_candidates=candidates,
                 ids=dict(body='42', cfg='42'), authenticated=True, login=False, blocked=False,
                 recognized=True, truncated=False, rows=[],
                 diag=dict(ready='complete', h1_total=0, h1_visible=0, banner=0, breadcrumb=0, collapsed=0))
    value.update(changes)
    return {'result': {'value': value}}


class ResolveTitleTests(unittest.TestCase):
    def test_header_h1_confirmed_by_tab_title(self):
        r = resolve_title([c('header_h1', COURSE)], f'Curso: {COURSE} | AVA Fictício')
        self.assertEqual((r.title, r.confidence, r.choices), (COURSE, 'confirmado', ()))
        self.assertIn('título da aba', r.sources)

    def test_custom_theme_banner_without_h1(self):
        # AEDB-like theme: title inside a highlighted course area, no <h1>.
        r = resolve_title([c('course_banner', COURSE), c('breadcrumb', COURSE)], '')
        self.assertEqual((r.title, r.confidence), (COURSE, 'confirmado'))

    def test_tab_title_alone_keeps_dash_inside_course_name(self):
        r = resolve_title([], f'Curso: {COURSE} | AVA Fictício')
        self.assertEqual((r.title, r.confidence), (COURSE, 'fonte única'))

    def test_short_banner_and_full_tab_title_are_one_course(self):
        r = resolve_title([c('course_banner', 'Modelagem Fictícia'), c('header_h1', COURSE)],
                          f'Curso: {COURSE} | AVA')
        self.assertEqual((r.title, r.confidence, r.choices), (COURSE, 'confirmado', ()))

    def test_conflicting_titles_require_manual_choice(self):
        r = resolve_title([c('header_h1', 'Disciplina A fictícia'), c('course_banner', 'Disciplina B fictícia')], '')
        self.assertEqual(r.confidence, 'ambíguo')
        self.assertEqual(set(r.choices), {'Disciplina A fictícia', 'Disciplina B fictícia'})

    def test_site_heading_loses_to_confirmed_course(self):
        r = resolve_title([c('header_h1', 'AVA Fictício'), c('course_banner', 'Modelagem Fictícia')],
                          f'Curso: {COURSE} | AVA Fictício')
        self.assertEqual(r.title, COURSE)
        self.assertNotEqual(r.confidence, 'ambíguo')

    def test_greeting_heading_is_not_the_course(self):
        r = resolve_title([c('h1', 'Olá, estudante fictício'), c('course_banner', COURSE)], f'{COURSE} | AVA')
        self.assertEqual((r.title, r.confidence), (COURSE, 'confirmado'))

    def test_duplicated_visual_and_screen_reader_text(self):
        self.assertEqual(clean_title('Modelagem Fictícia Modelagem Fictícia'), 'Modelagem Fictícia')
        self.assertEqual(clean_title('  Curso: Modelagem   Fictícia '), 'Modelagem Fictícia')
        # innerText joins adjacent inline copies without whitespace.
        self.assertEqual(clean_title(COURSE + COURSE), COURSE)
        self.assertEqual(clean_title('UML UML2'), 'UML UML2')

    def test_case_and_dash_variants_group_together(self):
        r = resolve_title([c('header_h1', '4º P CURSO FICTÍCIO – Modelagem Fictícia'),
                           c('breadcrumb', '4º p curso fictício - modelagem fictícia')], '')
        self.assertEqual((r.confidence, r.choices), ('confirmado', ()))

    def test_no_candidates(self):
        self.assertIsNone(resolve_title([], ''))
        self.assertIsNone(resolve_title([c('h1', '   '), c('unknown', 'X fictício')], ''))

    def test_choices_and_lengths_are_bounded(self):
        many = [c('header_h1', f'Disciplina {i} fictícia') for i in range(30)]
        r = resolve_title(many, '')
        self.assertLessEqual(len(r.choices), 5)
        r = resolve_title([c('header_h1', 'X' * 5000)], '')
        self.assertLessEqual(len(r.title), 400)

    def test_kind_labels(self):
        self.assertEqual(kind_label('assign'), 'Tarefa')
        self.assertEqual(kind_label('resource'), 'Arquivo')
        self.assertEqual(kind_label('desconhecido'), 'Item')


class ReaderTitleTests(unittest.TestCase):
    def setUp(self):
        self.page = Mock(url=URL)
        self.page.is_closed.return_value = False
        self.cdp = Mock()
        self.reader = PilotReader(self.page, self.cdp, PilotLimits(3000, 5000, 15000))

    def test_selection_uses_banner_when_no_h1(self):
        self.cdp.send.return_value = snap([c('course_banner', COURSE)], f'Curso: {COURSE} | AVA')
        chosen = self.reader.select()
        self.assertEqual((chosen.title, chosen.confidence), (COURSE, 'confirmado'))
        self.page.goto.assert_not_called()

    def test_async_header_is_awaited_without_navigation(self):
        self.cdp.send.side_effect = [snap([]), snap([c('header_h1', COURSE)])]
        self.assertEqual(self.reader.select().title, COURSE)
        self.page.wait_for_timeout.assert_called()
        self.page.goto.assert_not_called(); self.page.reload.assert_not_called()

    def test_unrecognized_title_reports_structure_only(self):
        self.cdp.send.return_value = snap([], '', diag=dict(ready='complete', h1_total=2, h1_visible=0,
                                                           banner=0, breadcrumb=0, collapsed=0))
        with self.assertRaises(PilotRejected) as caught:
            self.reader.select()
        message = str(caught.exception)
        self.assertIn('Título da disciplina não reconhecido', message)
        self.assertIn('h1 visíveis 0/2', message)
        self.assertLessEqual(self.cdp.send.call_count, 3)

    def test_cancel_during_retry(self):
        self.cdp.send.return_value = snap([])
        checks = iter((False, False, True, True, True))
        with self.assertRaises(PilotRejected) as caught:
            self.reader.select(cancelled=lambda: next(checks))
        self.assertIn('cancelada', str(caught.exception).lower())

    def test_closed_browser_during_retry(self):
        self.cdp.send.return_value = snap([])
        self.page.wait_for_timeout.side_effect = RuntimeError('Target closed SECRET')
        with self.assertRaises(PilotRejected) as caught:
            self.reader.select()
        self.assertNotIn('SECRET', str(caught.exception))

    def test_course_id_mismatch_rejected(self):
        for ids in (dict(body='43', cfg=''), dict(body='', cfg='43')):
            self.cdp.send.return_value = snap([c('header_h1', COURSE)], ids=ids)
            with self.subTest(ids=ids), self.assertRaises(PilotRejected) as caught:
                self.reader.select()
            self.assertIn('ID', str(caught.exception))

    def test_missing_id_signals_are_only_auxiliary(self):
        self.cdp.send.return_value = snap([c('header_h1', COURSE)], ids={})
        self.assertEqual(self.reader.select().title, COURSE)

    def test_url_does_not_replace_authentication(self):
        self.cdp.send.return_value = snap([c('header_h1', COURSE)], authenticated=False)
        with self.assertRaises(PilotRejected) as caught:
            self.reader.select()
        self.assertIn('Sessão', str(caught.exception))

    def test_ambiguous_selection_manual_choice_then_read(self):
        candidates = [c('header_h1', 'Disciplina A fictícia'), c('course_banner', 'Disciplina B fictícia')]
        self.cdp.send.return_value = snap(candidates)
        chosen = self.reader.select()
        self.assertEqual(chosen.confidence, 'ambíguo')
        picked = chosen.choose('Disciplina B fictícia')
        self.assertTrue(chosen.accepts(picked))
        with self.assertRaises(PilotRejected):
            chosen.choose('Disciplina injetada')
        self.cdp.send.return_value = snap(candidates, rows=[dict(kind='assign', title='Tarefa fictícia', due='', url='')])
        result = self.reader.read(picked)
        self.assertEqual(result.rows[0].course, 'Disciplina B fictícia')

    def test_read_rejects_when_title_changed(self):
        self.cdp.send.return_value = snap([c('header_h1', COURSE)])
        chosen = self.reader.select()
        self.cdp.send.return_value = snap([c('header_h1', 'Outra disciplina fictícia')])
        with self.assertRaises(PilotRejected):
            self.reader.read(chosen)

    def test_read_rows_labels_and_partial_reasons(self):
        self.cdp.send.return_value = snap([c('header_h1', COURSE)])
        chosen = self.reader.select()
        rows = [dict(kind='Seção', title='Aula 1 fictícia', due='', url=''),
                dict(kind='assign', title='Tarefa fictícia', due='Vencimento: 20/10/2026, 23:59',
                     url='/ava/mod/assign/view.php?id=8&sesskey=SECRET'),
                dict(kind='quiz', title='Questionário fictício', due='', url='')]
        sections = [dict(key='0:a', name='Aula 1 fictícia', state='open', items=2),
                    dict(key='1:b', name='Aula 2 fictícia', state='collapsed', items=0)]
        self.cdp.send.return_value = snap([c('header_h1', COURSE)], rows=rows, sections=sections)
        result = self.reader.read(chosen)
        self.assertEqual([r.kind for r in result.rows], ['Seção', 'Tarefa', 'Questionário'])
        self.assertEqual(result.rows[1].due, 'Vencimento: 20/10/2026, 23:59')
        self.assertEqual(result.rows[2].due, 'Não informado')
        self.assertEqual(result.rows[1].url, 'https://ead.aedb.br/ava/mod/assign/view.php?id=8')
        self.assertEqual(result.state, 'parcial')
        self.assertIn('1 não acessível', result.diagnostic)
        self.assertEqual([name for name, _ in result.coverage.reasons], ['Aula 2 fictícia'])
        self.assertNotIn('Cobertura completa', result.diagnostic)
        self.assertNotIn('SECRET', str(result))

    def test_selection_accepts_only_titles_found_on_the_same_page(self):
        ambiguous = PilotSelection(URL, 'Disciplina A fictícia', ('Disciplina A fictícia', 'Disciplina B fictícia'),
                                   'ambíguo')
        self.assertTrue(ambiguous.accepts(ambiguous.choose('Disciplina B fictícia')))
        forged_title = PilotSelection(URL, 'Disciplina C fictícia', ambiguous.choices, 'escolha manual')
        forged_url = PilotSelection(URL.replace('42', '43'), 'Disciplina B fictícia', ambiguous.choices, 'escolha manual')
        self.assertFalse(ambiguous.accepts(forged_title))
        self.assertFalse(ambiguous.accepts(forged_url))
        self.assertFalse(ambiguous.accepts('Disciplina B fictícia'))


if __name__ == '__main__':
    unittest.main()

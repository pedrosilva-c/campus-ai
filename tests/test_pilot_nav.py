"""Controlled navigation through the course's navigation cards, against an in-memory portal.

No browser, account or network. The simulator answers the three fixed DOM programs (read snapshot,
expand/scroll and card navigation) for a two-page portal: course home (cards) and the page of the
target card. Real DOM behaviour of NAV_JS is covered by the opt-in tests/test_pilot_dom_nav.py.
"""
import unittest
from unittest.mock import patch

try:
    from test_pilot_expand import CourseSim, section, item, CHOSEN, URL
except ImportError:   # run as `python -m unittest tests.test_pilot_nav`
    from tests.test_pilot_expand import CourseSim, section, item, CHOSEN, URL

import json

from campus_ai.authorized_courses import AuthorizedCourse
from campus_ai.pilot import PilotLimits, PilotLoginRequired, PilotReader, PilotRejected, PilotResult
from campus_ai.pilot_nav import (NAV_JS, CardNavigator, NavQuestion, classify_destination, normalize_label,
                                 role_of, MAX_NAV_PAGES)

COURSE = AuthorizedCourse('42', 'Modelagem Fictícia')
HOME = URL
DEST = URL + '&section=3'
ABS = 'https://ead.aedb.br'


def card(label, kind='link', dest='', *, key=None, tag='a', **extra):
    value = dict(key=key or 'c-' + normalize_label(label).replace(' ', '-'), role=role_of(label), label=label,
                 kind=kind, tag=tag, has_href=kind in ('link', 'fragment'), host='ead.aedb.br' if dest else '',
                 route=dest.split('42', 1)[0] if dest else '', dest=dest, dropped=0, flags=[])
    value.update(extra)
    return value


def standard_cards(target=None):
    return [card('Informações da Disciplina', 'link', HOME + '&section=1'),
            card('Trilhas de Aprendizagem', 'link', HOME + '&section=2'),
            target or card('Atividades Avaliativas', 'link', DEST),
            card('Feedback das Aulas', 'link', ABS + '/ava/mod/feedback/view.php?id=77'),
            card('Fale com o Professor', 'js', '', tag='div')]


def av_sections():
    return [section('AV1', [item('resource', 'Slides AV1 fictícios', cmid=21),
                            item('assign', 'Trabalho AV1 fictício', 'Vencimento: 20/10/2026, 23:59', cmid=22)],
                    collapsed=True),
            section('AV2', [item('quiz', 'Prova AV2 fictícia', 'Fecha: 25 out 2026, 18:00', cmid=31),
                            item('page', 'Resumo AV2 fictício', cmid=32)])]


class NavSim(CourseSim):
    """Two pages: the course home (cards) and the destination of the target card."""
    def __init__(self, cards, dest_sections, *, home_sections=None, dest_cards=()):
        super().__init__(list(home_sections or []))
        self.home_sections, self.dest_sections = list(home_sections or []), dest_sections
        self.cards, self.dest_cards = cards, list(dest_cards)
        self.gotos, self.card_clicks = [], []
        self.goto_error = self.goto_hook = None
        self.redirects, self.expire_on_goto, self.tab_target = {}, None, None
        self.goto = self._goto

    def _goto(self, url, **kwargs):
        if self.goto_error:
            raise self.goto_error
        self.gotos.append(url)
        self.events.append('goto')
        final = self.redirects.get(url, url)
        if self.expire_on_goto == len(self.gotos):
            self.logged_in, final = False, ABS + '/ava/login/index.php'
        self.url = final
        self.sections = self.dest_sections if 'section=3' in final else self.home_sections
        if self.goto_hook:
            self.goto_hook(self)

    def on_dest(self):
        return self.sections is self.dest_sections

    def send(self, method, params=None):
        if method == 'Runtime.evaluate' and params['expression'].startswith(NAV_JS):
            self.events.append('nav')
            options = json.loads(params['expression'][len(NAV_JS) + 1:-1])
            self.programs.append(('nav', options))
            return {'result': {'value': self.nav(options)}}
        return super().send(method, params)

    def nav(self, options):
        value = self.base()
        mode = options['mode']
        if mode == 'cards':
            value['cards'] = list(self.dest_cards if self.on_dest() else self.cards)
            value['structure'] = dict(cards=len(value['cards']))
        elif mode == 'probe':
            value.update(diag=dict(ready='complete'), academic=len(self.sections),
                         activities=sum(len(s['items']) for s in self.sections))
        elif mode in ('tab_click', 'card_click'):
            found = next((c for c in self.cards if c['key'] == options.get('key')), None)
            if not found or normalize_label(found['label']) != options.get('label'):
                value.update(clicked=False, reason='mudou')
            else:
                self.card_clicks.append(found['label'])
                self.events.append('card-click')
                value.update(clicked=True, reason='')
                if mode == 'tab_click':
                    self.sections = self.dest_sections          # same page, content swapped by script
                else:
                    self.url, self.sections = DEST, self.dest_sections   # script navigation
        return value


def navigate(sim, *, limits=None, progress=None, cancelled=None, **options):
    reader = PilotReader(sim, sim.cdp, limits or PilotLimits())
    return CardNavigator(reader).analyze(COURSE, CHOSEN, progress=progress, cancelled=cancelled, **options)


class NavBase(unittest.TestCase):
    def setUp(self):
        patcher = patch('campus_ai.pilot.time.monotonic', side_effect=lambda: self.sim.now)
        patcher.start(); self.addCleanup(patcher.stop)

    def run_nav(self, sim, **kwargs):
        self.sim = sim
        return navigate(sim, **kwargs)

    def titles(self, result):
        return [r.title for r in result.rows if r.kind != 'Seção']


class DestinationTests(unittest.TestCase):
    def test_same_course_pages_are_allowed(self):
        for url in (HOME, DEST, HOME + '&section=12'):
            with self.subTest(url=url):
                d = classify_destination(url, '42')
                self.assertEqual((d.kind, d.url), ('course', url))

    def test_other_course_host_scheme_and_credentials_are_blocked(self):
        for url in (ABS + '/ava/course/view.php?id=99&section=3',
                    'https://other.example.invalid/ava/course/view.php?id=42&section=3',
                    'http://ead.aedb.br/ava/course/view.php?id=42&section=3',
                    'https://user@ead.aedb.br/ava/course/view.php?id=42&section=3',
                    'https://ead.aedb.br:8443/ava/course/view.php?id=42&section=3',
                    'https://ead.aedb.br.evil.example.invalid/ava/course/view.php?id=42'):
            with self.subTest(url=url):
                self.assertEqual(classify_destination(url, '42').kind, 'blocked')

    def test_activity_submission_download_and_account_routes_are_blocked(self):
        for path in ('/ava/mod/assign/view.php?id=9', '/ava/mod/quiz/attempt.php?id=9', '/ava/mod/forum/view.php?id=9',
                     '/ava/mod/resource/view.php?id=9', '/ava/mod/feedback/view.php?id=9',
                     '/ava/pluginfile.php/1/mod_resource/content/1/x.pdf', '/ava/login/logout.php',
                     '/ava/message/index.php', '/ava/user/profile.php?id=3', '/ava/course/delete.php?id=42',
                     '/ava/course/modedit.php?id=42'):
            with self.subTest(path=path):
                self.assertEqual(classify_destination(ABS + path, '42').kind, 'blocked')

    def test_readable_module_pages_are_valid_but_not_supported_in_this_step(self):
        for module in ('page', 'book', 'folder'):
            d = classify_destination(f'{ABS}/ava/mod/{module}/view.php?id=9', '42')
            self.assertEqual(d.kind, 'unsupported', module)

    def test_unknown_same_origin_route_is_ambiguous_never_assumed_safe(self):
        d = classify_destination(ABS + '/ava/local/aedb/avaliativas.php?courseid=42', '42')
        self.assertEqual(d.kind, 'unknown')
        self.assertNotIn('42', d.route, 'route patterns never carry identifiers')

    def test_unexpected_query_parameters_are_not_a_valid_course_page(self):
        self.assertEqual(classify_destination(ABS + '/ava/course/view.php?id=42&edit=on&sesskey=SECRET', '42').kind,
                         'blocked')

    def test_labels_are_matched_without_accents_case_or_spacing(self):
        self.assertEqual(normalize_label('  ATIVIDADES   Avaliativas '), 'atividades avaliativas')
        self.assertEqual(role_of('Atividades Avaliativas'), 'target')
        self.assertEqual(role_of('Trilhas de Aprendizagem'), 'study')
        self.assertEqual(role_of('Informações da Disciplina'), 'info')
        for blocked in ('Feedback das Aulas', 'Fale com o Professor', 'Enviar tarefa', 'Excluir seção'):
            self.assertEqual(role_of(blocked), 'blocked', blocked)
        self.assertEqual(role_of('Outro cartão'), 'other')
        self.assertEqual(role_of('Atividades Avaliativas e Feedback'), 'blocked', 'a blocked word always wins')


class LinkNavigationTests(NavBase):
    def test_target_link_is_validated_navigated_read_and_the_course_home_is_restored(self):
        states = []
        sim = NavSim(standard_cards(), av_sections())
        result = self.run_nav(sim, progress=states.append)
        self.assertEqual(sim.gotos, [DEST, HOME], 'one page forward, one back, nothing else')
        self.assertEqual(sim.card_clicks, [], 'a validated link is opened by address, never clicked')
        self.assertEqual(self.titles(result), ['Slides AV1 fictícios', 'Trabalho AV1 fictício',
                                               'Prova AV2 fictícia', 'Resumo AV2 fictício'])
        by = {r.title: r for r in result.rows}
        self.assertEqual(by['Trabalho AV1 fictício'].section, 'AV1')
        self.assertEqual(by['Trabalho AV1 fictício'].due, 'Vencimento: 20/10/2026, 23:59')
        self.assertEqual(by['Prova AV2 fictícia'].due, 'Fecha: 25 out 2026, 18:00')
        self.assertEqual(by['Slides AV1 fictícios'].due, 'Não informado')
        self.assertEqual(sim.clicks, ['AV1'], 'only the section expander was clicked, on the destination page')
        self.assertEqual(sim.url, HOME)
        nav = result.navigation
        self.assertEqual((nav.method, nav.target, nav.returned), ('link', 'Atividades Avaliativas', True))
        for expected in ('acessando:Atividades Avaliativas', 'explorando', 'expandindo',
                         'identificando:AV1', 'identificando:AV2', 'analisando', 'verificando'):
            self.assertIn(expected, states)
        self.assertLess(states.index('acessando:Atividades Avaliativas'), states.index('identificando:AV1'))
        self.assertLess(states.index('analisando'), states.index('verificando'))

    def test_other_academic_card_not_read_keeps_the_result_partial_and_says_so(self):
        result = self.run_nav(NavSim(standard_cards(), av_sections()))
        self.assertEqual(result.state, 'parcial')
        self.assertIn('Trilhas de Aprendizagem', result.diagnostic)
        self.assertIn('não examinad', result.diagnostic)
        self.assertEqual(result.navigation.unread, ('Trilhas de Aprendizagem',))
        self.assertEqual(result.navigation.informational, ('Informações da Disciplina',))
        self.assertEqual(set(result.navigation.blocked), {'Feedback das Aulas', 'Fale com o Professor'})

    def test_attribute_and_script_destinations_are_opened_by_address_not_by_clicking(self):
        for kind in ('attr-url', 'onclick-url'):
            with self.subTest(kind=kind):
                sim = NavSim(standard_cards(card('Atividades Avaliativas', kind, DEST, tag='div')), av_sections())
                result = self.run_nav(sim)
                self.assertEqual(sim.gotos, [DEST, HOME])
                self.assertEqual(sim.card_clicks, [])
                self.assertEqual(result.navigation.method, kind)
                self.assertEqual(len(self.titles(result)), 4)

    def test_same_page_tab_card_is_clicked_once_and_read_in_place(self):
        sim = NavSim(standard_cards(card('Atividades Avaliativas', 'tab', '', tag='button')), av_sections())
        result = self.run_nav(sim)
        self.assertEqual(sim.card_clicks, ['Atividades Avaliativas'])
        self.assertEqual(sim.gotos, [])
        self.assertEqual(len(self.titles(result)), 4)
        self.assertEqual(result.navigation.method, 'tab')

    def test_fragment_card_is_not_navigation_the_page_is_read_as_is(self):
        sim = NavSim(standard_cards(card('Atividades Avaliativas', 'fragment', '#section-1')), av_sections(),
                     home_sections=[section('Geral', [item('forum', 'Avisos fictícios', cmid=1)])])
        result = self.run_nav(sim)
        self.assertEqual((sim.gotos, sim.card_clicks), ([], []))
        self.assertEqual(result.navigation.method, 'fragment')
        self.assertEqual(self.titles(result), ['Avisos fictícios'])

    def test_destination_page_cards_are_never_followed_depth_is_one(self):
        sim = NavSim(standard_cards(), av_sections(), dest_cards=standard_cards())
        self.run_nav(sim)
        self.assertEqual(sim.gotos, [DEST, HOME])
        self.assertLessEqual(len(sim.gotos), MAX_NAV_PAGES)


class SafetyTests(NavBase):
    def test_dangerous_or_foreign_destinations_are_never_opened(self):
        for dest in (ABS + '/ava/mod/assign/view.php?id=9', ABS + '/ava/course/view.php?id=99&section=3',
                     'https://other.example.invalid/x', ABS + '/ava/pluginfile.php/1/x.pdf'):
            with self.subTest(dest=dest):
                sim = NavSim(standard_cards(card('Atividades Avaliativas', 'link', dest)), av_sections(),
                             home_sections=[section('Geral', [item('forum', 'Avisos fictícios', cmid=1)])])
                result = self.run_nav(sim)
                self.assertEqual(sim.gotos, [])
                self.assertEqual(sim.card_clicks, [])
                self.assertEqual(result.state, 'parcial')
                self.assertEqual(result.navigation.method, 'blocked')
                self.assertIn('bloqueado', result.diagnostic)

    def test_blocked_cards_are_never_touched_even_when_they_are_the_only_ones(self):
        cards = [card('Feedback das Aulas', 'link', ABS + '/ava/mod/feedback/view.php?id=77'),
                 card('Fale com o Professor', 'js', '', tag='div')]
        sim = NavSim(cards, av_sections(), home_sections=[section('Geral', [item('forum', 'Avisos', cmid=1)])])
        result = self.run_nav(sim)
        self.assertEqual((sim.gotos, sim.card_clicks), ([], []))
        self.assertEqual(result.state, 'parcial')
        self.assertIn('não encontrado', result.diagnostic)

    def test_unverifiable_script_card_asks_the_student_and_touches_nothing_meanwhile(self):
        ambiguous = card('Atividades Avaliativas', 'js', '', tag='div')
        sim = NavSim(standard_cards(ambiguous), av_sections())
        question = self.run_nav(sim)
        self.assertIsInstance(question, NavQuestion)
        self.assertEqual(question.label, 'Atividades Avaliativas')
        self.assertEqual((sim.gotos, sim.card_clicks, sim.clicks), ([], [], []))

    def test_confirmed_ambiguous_card_is_clicked_once_verified_and_the_result_stays_partial(self):
        ambiguous = card('Atividades Avaliativas', 'js', '', tag='div')
        sim = NavSim(standard_cards(ambiguous), av_sections())
        question = self.run_nav(sim)
        result = navigate(sim, confirmed=question.key)
        self.assertEqual(sim.card_clicks, ['Atividades Avaliativas'])
        self.assertEqual(len(self.titles(result)), 4)
        self.assertEqual(result.state, 'parcial')
        self.assertEqual(result.navigation.method, 'confirmed-click')
        self.assertEqual(sim.gotos, [HOME], 'returned to the course home afterwards')

    def test_declined_ambiguous_card_is_not_touched_and_the_home_is_read_partially(self):
        sim = NavSim(standard_cards(card('Atividades Avaliativas', 'js', '', tag='div')), av_sections(),
                     home_sections=[section('Geral', [item('forum', 'Avisos fictícios', cmid=1)])])
        question = self.run_nav(sim)
        result = navigate(sim, declined=question.key)
        self.assertEqual((sim.gotos, sim.card_clicks), ([], []))
        self.assertEqual(result.state, 'parcial')
        self.assertIn('não autorizado', result.diagnostic)

    def test_a_confirmation_cannot_be_reused_for_another_card(self):
        sim = NavSim(standard_cards(card('Atividades Avaliativas', 'js', '', tag='div')), av_sections())
        self.run_nav(sim)
        with self.assertRaises(PilotRejected):
            navigate(sim, confirmed='c-qualquer-outro')
        self.assertEqual(sim.card_clicks, [])

    def test_unknown_same_origin_route_asks_before_any_navigation(self):
        sim = NavSim(standard_cards(card('Atividades Avaliativas', 'link', ABS + '/ava/local/aedb/aval.php?courseid=42')),
                     av_sections())
        question = self.run_nav(sim)
        self.assertIsInstance(question, NavQuestion)
        self.assertEqual(sim.gotos, [])

    def test_module_page_destination_is_reported_as_unsupported_not_followed(self):
        sim = NavSim(standard_cards(card('Atividades Avaliativas', 'link', ABS + '/ava/mod/page/view.php?id=9')),
                     av_sections(), home_sections=[section('Geral', [item('forum', 'Avisos', cmid=1)])])
        result = self.run_nav(sim)
        self.assertEqual(sim.gotos, [])
        self.assertEqual(result.state, 'parcial')
        self.assertIn('não suportado', result.diagnostic)

    def test_no_dangerous_control_is_ever_a_click_target(self):
        sim = NavSim(standard_cards(card('Atividades Avaliativas', 'tab', '', tag='button')), av_sections())
        self.run_nav(sim)
        self.assertEqual(sim.card_clicks, ['Atividades Avaliativas'])
        for kind, options in sim.programs:
            if kind == 'nav' and options['mode'] in ('tab_click', 'card_click'):
                self.assertEqual(set(options) - {'max_elements', 'timeout_ms', 'max_sections', 'lists'},
                                 {'mode', 'key', 'label'})

    def test_downloads_are_denied_before_the_first_navigation_in_the_runtime(self):
        from unittest.mock import Mock
        from campus_ai.browser_runtime import BrowserRuntime
        sim = NavSim(standard_cards(), av_sections())
        self.sim = sim
        runtime = BrowserRuntime('https://ead.aedb.br/ava')
        runtime._page = sim
        runtime._context = Mock(pages=[sim])
        runtime._context.new_cdp_session.return_value = sim.cdp
        result = runtime.perform('pilot_analyze', cancelled=lambda: False, settings=(COURSE, PilotLimits()))
        self.assertLess(sim.events.index('Browser.setDownloadBehavior'), sim.events.index('goto'))
        self.assertEqual(sim.gotos, [DEST, HOME])
        self.assertIsInstance(result, PilotResult)
        self.assertEqual(len(self.titles(result)), 4)
        runtime._context.close.assert_not_called()


class FailureTests(NavBase):
    def test_arrival_outside_the_course_is_rejected_and_the_student_is_returned_home(self):
        sim = NavSim(standard_cards(), av_sections(), home_sections=[section('Geral', [item('forum', 'Avisos', cmid=1)])])
        sim.redirects[DEST] = ABS + '/ava/mod/assign/view.php?id=3'
        result = self.run_nav(sim)
        self.assertEqual(sim.gotos, [DEST, HOME])
        self.assertEqual(sim.url, HOME)
        self.assertEqual(result.state, 'parcial')
        self.assertIn('fora da disciplina', result.diagnostic)

    def test_session_lost_on_arrival_stops_without_trying_to_go_back(self):
        sim = NavSim(standard_cards(), av_sections())
        sim.expire_on_goto = 1
        with self.assertRaises(PilotLoginRequired):
            self.run_nav(sim)
        self.assertEqual(sim.gotos, [DEST])

    def test_navigation_timeout_is_explained_and_nothing_else_is_requested(self):
        class TimeoutError(Exception):
            pass
        sim = NavSim(standard_cards(), av_sections())
        sim.goto_error = TimeoutError('Timeout 20000ms exceeded for ...sesskey=SECRET')
        with self.assertRaises(PilotRejected) as caught:
            self.run_nav(sim)
        self.assertIn('Tempo esgotado', str(caught.exception))
        self.assertIn('sessão', str(caught.exception))
        self.assertNotIn('SECRET', str(caught.exception))
        self.sim.close.assert_not_called()

    def test_cancel_after_arriving_abandons_the_run_without_further_navigation(self):
        sim = NavSim(standard_cards(), av_sections())
        with self.assertRaises(PilotRejected) as caught:
            self.run_nav(sim, cancelled=lambda: len(sim.gotos) >= 1)
        self.assertIn('cancelada', str(caught.exception).lower())
        self.assertEqual(sim.gotos, [DEST])
        sim.close.assert_not_called()

    def test_browser_closed_while_navigating(self):
        sim = NavSim(standard_cards(), av_sections())
        sim.goto_hook = lambda s: setattr(s, 'closed', True)
        with self.assertRaises(PilotRejected) as caught:
            self.run_nav(sim)
        self.assertIn('Navegador fechado', str(caught.exception))

    def test_failure_to_return_home_is_reported_and_the_result_is_partial(self):
        sim = NavSim(standard_cards(), av_sections())
        sim.goto_hook = lambda s: s.redirects.update({HOME: DEST}) if len(s.gotos) == 1 else None
        result = self.run_nav(sim)
        self.assertFalse(result.navigation.returned)
        self.assertEqual(result.state, 'parcial')
        self.assertIn('retorno', result.diagnostic)


class StructureTests(NavBase):
    def test_inspection_mode_reads_the_structure_and_navigates_nowhere(self):
        sim = NavSim(standard_cards(), av_sections())
        result = self.run_nav(sim, inspect_only=True)
        self.assertEqual((sim.gotos, sim.card_clicks, sim.clicks), ([], [], []))
        self.assertEqual(result.state, 'nao_validada')
        self.assertEqual(result.rows, [])
        text = result.diagnostic
        self.assertIn('Modo de inspeção', text)
        self.assertIn('cartões 5', text)
        self.assertIn('link 4', text)
        self.assertIn('js 1', text)
        self.assertNotIn('section=', text, 'route patterns, never raw URLs')
        self.assertNotIn('sesskey', text)

    def test_structure_lists_type_href_route_and_decision_without_private_data(self):
        sim = NavSim(standard_cards(), av_sections())
        result = self.run_nav(sim, inspect_only=True)
        rows = result.navigation.cards
        target = next(c for c in rows if c['role'] == 'target')
        self.assertEqual((target['tag'], target['kind'], target['has_href'], target['decision']),
                         ('a', 'link', True, 'navegaria (link validado)'))
        self.assertEqual(target['host'], 'ead.aedb.br')
        self.assertTrue(all(set(c) <= {'role', 'label', 'tag', 'kind', 'has_href', 'host', 'route', 'decision'}
                            for c in rows))
        self.assertTrue(all(c['label'] == '' for c in rows if c['role'] == 'other'))

    def test_course_without_navigation_cards_is_read_as_before(self):
        sim = NavSim([], [], home_sections=[section('Geral', [item('forum', 'Avisos fictícios', cmid=1)])])
        result = self.run_nav(sim)
        self.assertEqual((sim.gotos, result.navigation), ([], None))
        self.assertEqual(self.titles(result), ['Avisos fictícios'])

    def test_missing_target_card_among_other_cards_is_a_partial_result(self):
        cards = [card('Trilhas de Aprendizagem', 'link', HOME + '&section=2')]
        sim = NavSim(cards, av_sections(), home_sections=[section('Geral', [item('forum', 'Avisos', cmid=1)])])
        result = self.run_nav(sim)
        self.assertEqual(sim.gotos, [])
        self.assertEqual(result.state, 'parcial')
        self.assertIn('Atividades Avaliativas não encontrado', result.diagnostic)

    def test_a_completely_read_destination_without_other_unread_cards_is_complete(self):
        cards = [card('Atividades Avaliativas', 'link', DEST), card('Feedback das Aulas', 'link', ABS + '/ava/mod/feedback/view.php?id=7')]
        sim = NavSim(cards, [section('AV1', [item('page', 'Resumo AV1', cmid=5)]),
                             section('AV2', [item('quiz', 'Prova AV2', cmid=6)])])
        result = self.run_nav(sim)
        self.assertEqual(result.state, 'completa')
        self.assertTrue(result.diagnostic.startswith('Cobertura completa'))
        self.assertIn('Navegação', result.diagnostic)


if __name__ == '__main__':
    unittest.main()

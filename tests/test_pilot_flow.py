"""Direct-open pilot flow against a simulated portal: no account, network or Chromium."""
import unittest
from unittest.mock import Mock, patch

from campus_ai.authorized_courses import AuthorizedCourse
from campus_ai.pilot import (PilotReader, PilotLimits, PilotRejected, PilotResult, PilotSelection,
                             PilotLoginRequired)
from campus_ai.pilot_flow import reach_course

COURSE = AuthorizedCourse('42', 'Modelagem Fictícia')
URL = COURSE.url
LOGIN = 'https://ead.aedb.br/ava/login/index.php'
FULL = '4º P CURSO FICTÍCIO - Modelagem Fictícia'


def projection(url, *, logged_in=True, candidates=None, ids=('42', '42'), rows=None, **extra):
    value = dict(url=url, doc_title='', authenticated=logged_in, login=not logged_in, blocked=False,
                 sections=[dict(key='0:s', name='Aula fictícia', state='open', items=2)],
                 recognized=True, truncated=False,
                 rows=[dict(kind='page', title='Página fictícia', due='', url='', section='Aula fictícia')]
                 if rows is None else rows,
                 title_candidates=[dict(source='header_h1', text=FULL)] if candidates is None else candidates,
                 ids=dict(body=ids[0], cfg=ids[1]), diag=dict(ready='complete', collapsed=0))
    value.update(extra)
    return {'result': {'value': value}}


class Portal:
    """Page + CDP double. `wait_for_timeout` advances a fake clock and may complete the login."""
    def __init__(self, url='about:blank', *, logged_in=False, login_after_polls=None,
                 after_login=URL, **page_projection):
        self.url, self.logged_in = url, logged_in
        self.login_after_polls, self.after_login = login_after_polls, after_login
        self.projection = page_projection
        self.now, self.polls, self.closed = 0.0, 0, False
        self.gotos, self.evaluations = [], []
        self.close = Mock(); self.reload = Mock(); self.click = Mock(); self.content = Mock()
        self.cdp = Mock(); self.cdp.send.side_effect = self.send
        self.goto_error = None

    def is_closed(self):
        return self.closed

    def clock(self):
        return self.now

    def goto(self, url, **kwargs):
        self.gotos.append((url, kwargs))
        if self.goto_error:
            raise self.goto_error
        self.url = url if self.logged_in else LOGIN

    def wait_for_timeout(self, ms):
        self.now += ms / 1000
        self.polls += 1
        if self.login_after_polls is not None and self.polls >= self.login_after_polls:
            self.logged_in, self.url = True, self.after_login
            self.login_after_polls = None

    def send(self, method, params=None):
        if method != 'Runtime.evaluate':
            return {}
        self.evaluations.append(self.url)
        return projection(self.url, logged_in=self.logged_in, **self.projection)


def reach(portal, **kwargs):
    states = []
    reader = PilotReader(portal, portal.cdp, PilotLimits())
    kwargs.setdefault('cancelled', lambda: False)
    reach_course(portal, reader, COURSE, progress=states.append, clock=portal.clock, **kwargs)
    return states


class ReachCourseTests(unittest.TestCase):
    def test_opens_the_authorized_course_directly_never_blank(self):
        portal = Portal(logged_in=True)
        states = reach(portal)
        self.assertEqual([g[0] for g in portal.gotos], [URL])
        self.assertEqual(portal.gotos[0][1]['wait_until'], 'domcontentloaded')
        self.assertEqual(states, ['abrindo', 'autenticado'])
        self.assertEqual(portal.url, URL)

    def test_current_course_tab_is_not_reloaded(self):
        portal = Portal(url=URL + '&sesskey=SECRET', logged_in=True)
        self.assertEqual(reach(portal), ['abrindo', 'autenticado'])
        self.assertEqual(portal.gotos, [])
        portal.reload.assert_not_called()

    def test_login_is_manual_and_analysis_continues_after_it(self):
        portal = Portal(logged_in=False, login_after_polls=3)
        states = reach(portal)
        self.assertEqual(states, ['abrindo', 'login', 'autenticado'])
        self.assertEqual(len(portal.gotos), 1, 'must not navigate while the student signs in')
        portal.click.assert_not_called()
        portal.close.assert_not_called()

    def test_landing_elsewhere_after_login_navigates_once_more_to_the_same_url(self):
        portal = Portal(logged_in=False, login_after_polls=2, after_login='https://ead.aedb.br/ava/my/')
        reach(portal)
        self.assertEqual([g[0] for g in portal.gotos], [URL, URL])

    def test_external_login_provider_is_only_waited_on(self):
        portal = Portal(logged_in=False, login_after_polls=4)
        portal.goto = lambda url, **kw: (portal.gotos.append((url, kw)),
                                         setattr(portal, 'url', 'https://sso.example.invalid/entrar'))
        states = reach(portal)
        self.assertEqual(states, ['abrindo', 'login', 'autenticado'])
        self.assertEqual(len(portal.gotos), 1)
        self.assertNotIn('https://sso.example.invalid/entrar', portal.evaluations,
                         'the DOM of a foreign origin must never be inspected')

    def test_login_timeout_preserves_the_session(self):
        portal = Portal(logged_in=False)
        with self.assertRaises(PilotRejected) as caught:
            reach(portal, login_wait_s=10)
        self.assertIn('Login não concluído', str(caught.exception))
        portal.close.assert_not_called()

    def test_cancel_while_waiting_for_login_keeps_the_browser(self):
        portal = Portal(logged_in=False)
        with self.assertRaises(PilotRejected) as caught:
            reach(portal, cancelled=lambda: portal.polls >= 2)
        self.assertIn('cancelada', str(caught.exception).lower())
        self.assertIn('preserv', str(caught.exception))
        portal.close.assert_not_called()

    def test_browser_closed_while_waiting(self):
        portal = Portal(logged_in=False)
        original = portal.wait_for_timeout
        portal.wait_for_timeout = lambda ms: (original(ms), setattr(portal, 'closed', True))
        with self.assertRaises(PilotRejected) as caught:
            reach(portal)
        self.assertIn('Navegador fechado', str(caught.exception))

    def test_navigation_timeout_message_is_useful_and_private(self):
        class TimeoutError(Exception):
            pass
        portal = Portal(logged_in=True)
        portal.goto_error = TimeoutError('Timeout 20000ms exceeded navigating to ...sesskey=SECRET')
        with self.assertRaises(PilotRejected) as caught:
            reach(portal)
        message = str(caught.exception)
        self.assertIn('Tempo esgotado', message)
        self.assertIn('sessão', message)
        self.assertNotIn('SECRET', message)

    def test_gives_up_after_bounded_navigations(self):
        portal = Portal(logged_in=True)
        portal.goto = lambda url, **kw: portal.gotos.append((url, kw))  # url never changes
        with self.assertRaises(PilotRejected):
            reach(portal)
        self.assertEqual(len(portal.gotos), 3)

    def test_blocked_portal_stops_immediately(self):
        portal = Portal(url=URL, logged_in=True, blocked=True)
        with self.assertRaises(PilotRejected) as caught:
            reach(portal)
        self.assertIn('Bloqueio', str(caught.exception))
        self.assertEqual(portal.polls, 0)

    def test_slow_page_is_not_reported_as_login(self):
        portal = Portal(url=URL, logged_in=False)
        portal.projection = dict(diag=dict(ready='loading'), login=False)  # no login form yet
        original = portal.wait_for_timeout
        def finish(ms):
            original(ms)
            if portal.polls == 2:
                portal.logged_in = True
        portal.wait_for_timeout = finish
        self.assertEqual(reach(portal), ['abrindo', 'autenticado'])

    def test_only_the_authorized_url_is_ever_requested(self):
        portal = Portal(logged_in=False, login_after_polls=2, after_login='https://ead.aedb.br/ava/my/')
        reach(portal)
        self.assertTrue(all(g[0] == URL for g in portal.gotos))


class IdentifyTests(unittest.TestCase):
    def reader(self, **page_projection):
        portal = Portal(url=URL, logged_in=True, **page_projection)
        return PilotReader(portal, portal.cdp, PilotLimits()), portal

    def test_title_containing_the_expected_name_is_confirmed_silently(self):
        reader, _ = self.reader()
        chosen = reader.identify(COURSE)
        self.assertEqual((chosen.title, chosen.confidence), (FULL, 'fonte única'))

    def test_unrecognized_header_is_not_blocking_when_the_course_id_matches(self):
        reader, portal = self.reader(candidates=[])
        chosen = reader.identify(COURSE)
        self.assertEqual((chosen.title, chosen.confidence), (COURSE.name, 'id do curso'))
        self.assertLessEqual(portal.cdp.send.call_count, 3)

    def test_url_alone_never_confirms_identity(self):
        reader, _ = self.reader(candidates=[], ids=('', ''))
        chosen = reader.identify(COURSE)
        self.assertEqual((chosen.confidence, chosen.choices), ('manual', (COURSE.name,)))

    def test_other_title_with_matching_id_keeps_the_real_title_visible(self):
        reader, _ = self.reader(candidates=[dict(source='header_h1', text='Outra disciplina fictícia')])
        chosen = reader.identify(COURSE)
        self.assertEqual((chosen.title, chosen.confidence), ('Outra disciplina fictícia', 'id do curso'))

    def test_other_title_without_id_signals_asks_the_student(self):
        reader, _ = self.reader(candidates=[dict(source='header_h1', text='Outra disciplina fictícia')], ids=('', ''))
        chosen = reader.identify(COURSE)
        self.assertEqual(chosen.confidence, 'manual')
        self.assertEqual(set(chosen.choices), {'Outra disciplina fictícia', COURSE.name})

    def test_wrong_page_is_rejected(self):
        reader, portal = self.reader()
        portal.url = URL.replace('42', '43')
        with self.assertRaises(PilotRejected):
            reader.identify(COURSE)

    def test_manual_name_flow(self):
        reader, _ = self.reader(candidates=[], ids=('', ''))
        pending = reader.identify(COURSE)
        with self.assertRaises(PilotRejected):
            reader.read(pending)
        named = pending.choose('  Modelagem   Fictícia  ')
        self.assertEqual((named.title, named.confidence), ('Modelagem Fictícia', 'nome informado'))
        self.assertTrue(pending.accepts(named))
        with self.assertRaises(PilotRejected):
            pending.choose('   ')
        result = reader.read(named)
        self.assertEqual(result.state, 'completa')

    def test_id_confirmed_read_requires_the_id_signal_again(self):
        reader, portal = self.reader(candidates=[])
        chosen = reader.identify(COURSE)
        portal.projection['ids'] = ('', '')
        with self.assertRaises(PilotRejected):
            reader.read(chosen)
        portal.projection['ids'] = ('42', '')
        rows = [dict(kind='assign', title='Tarefa fictícia', due='Vencimento: 20/10/2026', url='')]
        portal.projection['rows'] = rows
        result = reader.read(chosen)
        self.assertEqual((result.rows[0].course, result.rows[0].kind), (COURSE.name, 'Tarefa'))


class RuntimeAnalyzeTests(unittest.TestCase):
    def runtime(self, portal, extra_pages=()):
        from campus_ai.browser_runtime import BrowserRuntime
        runtime = BrowserRuntime('https://ead.aedb.br/ava')
        runtime._page = portal
        runtime._context = Mock(pages=[portal, *extra_pages])
        self.order = []
        def new_session(page):
            self.order.append('cdp')
            return portal.cdp
        runtime._context.new_cdp_session.side_effect = new_session
        original = portal.cdp.send.side_effect
        portal.cdp.send.side_effect = lambda m, p=None: (self.order.append(m), original(m, p))[1]
        original_goto = portal.goto
        portal.goto = lambda url, **kw: (self.order.append('goto'), original_goto(url, **kw))[1]
        return runtime

    def test_one_call_opens_authenticates_identifies_and_reads(self):
        rows = [dict(kind='Seção', title='Aula 1 fictícia', due='', url=''),
                dict(kind='assign', title='Tarefa fictícia', due='Vencimento: 20/10/2026, 23:59',
                     url='/ava/mod/assign/view.php?id=8&sesskey=SECRET')]
        portal = Portal(logged_in=True, rows=rows)
        runtime = self.runtime(portal)
        states = []
        with patch('campus_ai.engine.run_scan') as scan, patch('campus_ai.obsidian.ObsidianWriter') as writer, \
             patch('campus_ai.gmail.scan_gmail') as gmail, patch('campus_ai.state.History') as history:
            result = runtime.perform('pilot_analyze', cancelled=lambda: False,
                                     settings=(COURSE, PilotLimits()), progress=states.append)
        for function in (scan, writer, gmail, history):
            function.assert_not_called()
        self.assertIsInstance(result, PilotResult)
        self.assertEqual(result.state, 'completa')
        self.assertEqual([r.title for r in result.rows], ['Aula 1 fictícia', 'Tarefa fictícia'])
        self.assertEqual(result.selection.title, FULL)
        self.assertNotIn('SECRET', str(result))
        self.assertEqual(states, ['abrindo', 'autenticado', 'explorando', 'expandindo', 'analisando'])
        self.assertLess(self.order.index('Browser.setDownloadBehavior'), self.order.index('goto'),
                        'downloads must be denied before the first navigation')
        portal.close.assert_not_called()

    def test_other_tabs_are_ignored_not_inspected(self):
        other = Mock(url='https://ead.aedb.br/ava/course/view.php?id=99')
        portal = Portal(logged_in=True)
        runtime = self.runtime(portal, extra_pages=[other])
        result = runtime.perform('pilot_analyze', cancelled=lambda: False, settings=(COURSE, PilotLimits()))
        self.assertEqual(result.state, 'completa')
        runtime._context.new_cdp_session.assert_called_once_with(portal)
        self.assertEqual(other.mock_calls, [])

    def test_download_policy_failure_prevents_any_navigation(self):
        portal = Portal(logged_in=True)
        runtime = self.runtime(portal)
        runtime._context.new_cdp_session.side_effect = RuntimeError('private details')
        with self.assertRaises(PilotRejected):
            runtime.perform('pilot_analyze', settings=(COURSE, PilotLimits()))
        self.assertEqual(portal.gotos, [])

    def test_unrecognized_title_without_id_asks_then_reads_without_reopening(self):
        portal = Portal(logged_in=True, candidates=[], ids=('', ''))
        runtime = self.runtime(portal)
        pending = runtime.perform('pilot_analyze', cancelled=lambda: False, settings=(COURSE, PilotLimits()))
        self.assertIsInstance(pending, PilotSelection)
        self.assertEqual(pending.confidence, 'manual')
        goto_count = len(portal.gotos)
        forged = PilotSelection(URL.replace('42', '43'), 'X fictícia', pending.choices, 'nome informado')
        with self.assertRaises(PilotRejected):
            runtime.perform('pilot_read', cancelled=lambda: False, settings=(forged, PilotLimits()))
        result = runtime.perform('pilot_read', cancelled=lambda: False,
                                 settings=(pending.choose('Modelagem Fictícia'), PilotLimits()))
        self.assertEqual(result.state, 'completa')
        self.assertEqual(len(portal.gotos), goto_count)

    def test_cancel_during_login_keeps_context_open(self):
        portal = Portal(logged_in=False)
        runtime = self.runtime(portal)
        with self.assertRaises(PilotRejected):
            runtime.perform('pilot_analyze', cancelled=lambda: portal.polls >= 1, settings=(COURSE, PilotLimits()))
        runtime._context.close.assert_not_called()
        portal.close.assert_not_called()
        self.assertIs(runtime._page, portal)

    def test_open_goes_to_the_course_not_blank_and_does_not_read(self):
        portal = Portal(logged_in=True)
        runtime = self.runtime(portal)
        result = runtime.perform('pilot_open', cancelled=lambda: False, settings=(COURSE, PilotLimits()))
        self.assertEqual([g[0] for g in portal.gotos], [URL])
        self.assertEqual(result.state, 'aberta')
        self.assertEqual(result.rows, [])
        self.assertEqual(portal.evaluations.count(URL), 1, 'only the session probe, no content read')

    def test_unauthorized_course_object_cannot_be_forged(self):
        with self.assertRaises(ValueError):
            AuthorizedCourse('42&x=1', 'Fictícia')


class LoginErrorTypeTests(unittest.TestCase):
    def test_expired_session_is_a_login_required_rejection(self):
        portal = Portal(url=URL, logged_in=False)
        reader = PilotReader(portal, portal.cdp, PilotLimits())
        with self.assertRaises(PilotLoginRequired):
            reader.select()


if __name__ == '__main__':
    unittest.main()

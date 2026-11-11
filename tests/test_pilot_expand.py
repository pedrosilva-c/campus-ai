"""Safe section expansion and coverage reporting, against an in-memory course simulator.

No browser, account or network. The simulator answers the two fixed DOM programs
(read snapshot and expand plan/click/state); real DOM behaviour of those programs is
covered by the opt-in tests/test_pilot_dom_expand.py.
"""
import json
import unittest
from unittest.mock import Mock, patch

from campus_ai.pilot_nav import NAV_JS
from campus_ai.pilot import (EXPAND_JS, SNAPSHOT_JS, PilotLimits, PilotLoginRequired, PilotReader,
                             PilotRejected, PilotSelection, MAX_EXPAND_SECTIONS)

URL = 'https://ead.aedb.br/ava/course/view.php?id=42'
CHOSEN = PilotSelection(URL, 'Modelagem Fictícia', (), 'id do curso', ('id do curso',))


def item(kind, title, due='', cmid=None):
    url = f'/ava/mod/{kind}/view.php?id={cmid}' if cmid else ''
    return dict(kind=kind, title=title, due=due, url=url)


def section(name, items=(), *, collapsed=False, expander='safe', load_polls=0, on_click='expand', nested=None,
            evidence=False, hint=''):
    return dict(name=name, items=list(items), collapsed=collapsed, expander=expander, load_polls=load_polls,
                on_click=on_click, pending=0, nested=nested, evidence=evidence, hint=hint)


class CourseSim:
    """Page + CDP double. `wait_for_timeout` advances the clock and finishes async loads."""
    def __init__(self, sections, *, url=URL):
        self.url, self.sections, self.closed = url, sections, False
        self.now, self.polls = 1000.0, 0
        self.clicks, self.programs, self.logged_in = [], [], True
        self.events = []
        self.after_click = None
        self.scroll_steps, self.scroll_needed, self.late = 0, 2, []   # late: [(scroll step, section)]
        self.on_scroll, self.nav_missing, self.index, self.layout, self.orphan_links = None, 0, None, 0, 0
        self.goto = Mock(); self.click = Mock(); self.reload = Mock(); self.content = Mock(); self.close = Mock()
        self.cdp = Mock(); self.cdp.send.side_effect = self.send

    # page API used by the reader
    def is_closed(self):
        return self.closed

    def clock(self):
        return self.now

    def wait_for_timeout(self, ms):
        self.now += ms / 1000
        self.polls += 1
        for sec in self.sections:
            if sec['pending'] > 0:
                sec['pending'] -= 1

    # helpers
    def key(self, i):
        return f'{i}:sec{i}'

    def visible_items(self, sec):
        return [] if sec['collapsed'] or sec['pending'] > 0 else sec['items']

    def state_name(self, sec):
        """Mirrors the DOM program: 'open' needs visible content or expansion evidence."""
        if sec['collapsed']:
            return 'collapsed'
        return 'open' if self.visible_items(sec) or sec['evidence'] else 'unknown'

    def structure(self):
        named = [sec for sec in self.sections if sec['name']]
        return dict(candidates=len(self.sections) + self.layout, academic=len(self.sections), layout=self.layout,
                    activity_elements=sum(len(sec['items']) for sec in self.sections), orphan_activities=0,
                    orphan_links=self.orphan_links, nav_total=self.nav_missing, nav_missing=self.nav_missing,
                    index=self.index or dict(present=False, sections=0, cms=0),
                    unnamed=len(self.sections) - len(named))

    def base(self):
        return dict(url=self.url, authenticated=self.logged_in, login=not self.logged_in, blocked=False,
                    ids=dict(body='42', cfg='42'), doc_title='', title_candidates=[], diag=dict(ready='complete'),
                    truncated=False)

    def send(self, method, params=None):
        self.events.append(method)
        if method != 'Runtime.evaluate':
            return {}
        expression = params['expression']
        if expression.startswith(NAV_JS):
            # An ordinary course page: no navigation cards, and nothing to wait for.
            self.events.append('nav')
            return {'result': {'value': dict(self.base(), cards=[], academic=len(self.sections), activities=0)}}
        if expression.startswith(EXPAND_JS):
            options = json.loads(expression[len(EXPAND_JS) + 1:-1])
            self.programs.append(('expand', options))
            return {'result': {'value': self.expand(options)}}
        assert expression.startswith(SNAPSHOT_JS), 'unknown program'
        self.programs.append(('snapshot', json.loads(expression[len(SNAPSHOT_JS) + 1:-1])))
        return {'result': {'value': self.snapshot()}}

    def expand(self, options):
        value = self.base()
        mode = options['mode']
        index = None
        if 'key' in options:
            index = next((i for i, _ in enumerate(self.sections) if self.key(i) == options['key']), None)
        if mode == 'scroll':
            self.scroll_steps += 1
            self.events.append('scroll')
            for step, late in list(self.late):
                if self.scroll_steps >= step:
                    self.sections.append(late); self.late.remove((step, late))
            if self.on_scroll:
                self.on_scroll(self)
            value.update(height=3000 + 10 * len(self.sections), y=100 * self.scroll_steps,
                         bottom=self.scroll_steps >= self.scroll_needed,
                         activities=sum(len(sec['items']) for sec in self.sections), sections=len(self.sections))
            return value
        if mode == 'top':
            self.events.append('top')
            value.update(y=0)
            return value
        if mode == 'plan':
            value['sections'] = [dict(key=self.key(i), name=s['name'], number=str(i + 1), state=self.state_name(s),
                                      items=len(self.visible_items(s)),
                                      expander=dict(status=s['expander'], hint=s['hint']))
                                 for i, s in enumerate(self.sections)]
            value['truncated_sections'] = False
            value['structure'] = self.structure()
        elif mode == 'click':
            if index is None or not self.sections[index]['collapsed'] or self.sections[index]['expander'] != 'safe':
                value['clicked'] = False; value['reason'] = 'mudou'
            else:
                sec = self.sections[index]
                self.clicks.append(sec['name'])
                self.events.append('click:' + sec['name'])
                if sec['on_click'] == 'expand':
                    sec['collapsed'], sec['pending'], sec['evidence'] = False, sec['load_polls'], True
                    if sec['nested']:
                        self.sections.extend(sec['nested'])
                value['clicked'] = True
                if self.after_click:
                    self.after_click(self)
        elif mode == 'state':
            sec = self.sections[index] if index is not None else None
            value.update(found=sec is not None, expanded=bool(sec) and not sec['collapsed'],
                         busy=bool(sec) and sec['pending'] > 0,
                         items=len(self.visible_items(sec)) if sec else 0,
                         text_len=10 * len(self.visible_items(sec)) if sec else 0)
        return value

    def snapshot(self):
        value = self.base()
        rows, sections = [], []
        for i, sec in enumerate(self.sections):
            if sec['name']:
                rows.append(dict(kind='Seção', title=sec['name'], section=sec['name'], due='', url=''))
            for it in self.visible_items(sec):
                rows.append(dict(it, section=sec['name']))
            sections.append(dict(key=self.key(i), name=sec['name'], number=str(i + 1), state=self.state_name(sec),
                                 items=len(self.visible_items(sec)), hint=sec['hint']))
        value.update(rows=rows, sections=sections, recognized=bool(self.sections), structure=self.structure())
        return value


def reader_for(sim, limits=None):
    return PilotReader(sim, sim.cdp, limits or PilotLimits()), sim


class ExpansionTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('campus_ai.pilot.time.monotonic', side_effect=lambda: self.sim.now)
        patcher.start(); self.addCleanup(patcher.stop)

    def read(self, sections, *, limits=None, cancelled=None, progress=None, expand=True, sim=None):
        self.sim = sim or CourseSim(sections)
        reader = PilotReader(self.sim, self.sim.cdp, limits or PilotLimits())
        return reader.read(CHOSEN, cancelled=cancelled, expand=expand, progress=progress)

    def test_av1_and_av2_collapsed_are_expanded_automatically_and_read(self):
        sections = [section('Geral', [item('forum', 'Avisos fictícios', cmid=1)]),
                    section('AV1', [item('resource', 'Slides AV1 fictícios', cmid=2),
                                    item('assign', 'Trabalho AV1 fictício', 'Vencimento: 20/10/2026, 23:59', cmid=3)],
                            collapsed=True),
                    section('AV2', [item('quiz', 'Prova AV2 fictícia', cmid=4)], collapsed=True)]
        states = []
        result = self.read(sections, progress=states.append)
        self.assertEqual(self.sim.clicks, ['AV1', 'AV2'])
        titles = {r.title: r for r in result.rows}
        self.assertEqual(titles['Trabalho AV1 fictício'].section, 'AV1')
        self.assertEqual(titles['Trabalho AV1 fictício'].due, 'Vencimento: 20/10/2026, 23:59')
        self.assertEqual(titles['Prova AV2 fictícia'].due, 'Não informado')
        self.assertEqual(titles['Prova AV2 fictícia'].kind, 'Questionário')
        c = result.coverage
        self.assertEqual((c.sections_total, c.expanded, c.already_open, c.inaccessible), (3, 2, 1, 0))
        self.assertEqual((c.materials, c.activities), (1, 3))
        self.assertEqual(result.state, 'completa')
        self.assertTrue(result.diagnostic.startswith('Cobertura completa'))
        self.assertIn('3 seções acadêmicas reconhecidas', result.diagnostic)
        self.assertIn('2 expandidas automaticamente', result.diagnostic)
        self.assertIn('0 não acessíveis', result.diagnostic)
        self.assertEqual(states, ['explorando', 'expandindo', 'analisando'])

    def test_sections_already_open_are_never_clicked(self):
        result = self.read([section('Geral', [item('page', 'Página fictícia', cmid=1)]),
                            section('AV1', [item('resource', 'Slides fictícios', cmid=2)])])
        self.assertEqual(self.sim.clicks, [])
        self.assertEqual((result.coverage.expanded, result.coverage.already_open), (0, 2))
        self.assertEqual(result.state, 'completa')

    def test_content_loaded_after_the_click_is_awaited_before_reading(self):
        sections = [section('AV1', [item('resource', 'Slides tardios fictícios', cmid=2)], collapsed=True, load_polls=4)]
        result = self.read(sections)
        self.assertEqual([r.title for r in result.rows if r.kind != 'Seção'], ['Slides tardios fictícios'])
        self.assertGreaterEqual(self.sim.polls, 4)
        self.assertEqual(result.state, 'completa')

    def test_empty_section_counts_as_examined_but_zero_items_are_not_validated_alone(self):
        result = self.read([section('AV3 vazia', [], collapsed=True)])
        self.assertEqual((result.coverage.expanded, result.coverage.inaccessible), (1, 0))
        self.assertEqual(result.rows[0].kind, 'Seção')
        self.assertEqual(result.state, 'nao_validada', 'nothing extracted and nothing independent confirms emptiness')

    def test_zero_items_are_complete_only_when_the_course_index_confirms_the_emptiness(self):
        self.sim = CourseSim([section('AV3 vazia', [], collapsed=True)])
        self.sim.index = dict(present=True, sections=1, cms=0)
        result = PilotReader(self.sim, self.sim.cdp, PilotLimits()).read(CHOSEN, expand=True)
        self.assertEqual(result.state, 'completa')

    def test_ambiguous_expander_is_left_intact_and_marks_partial(self):
        result = self.read([section('AV1', [item('resource', 'Slides fictícios', cmid=2)], collapsed=True),
                            section('AV2', [item('quiz', 'Prova fictícia', cmid=4)], collapsed=True, expander='ambiguous')])
        self.assertEqual(self.sim.clicks, ['AV1'])
        self.assertEqual(result.state, 'parcial')
        c = result.coverage
        self.assertEqual((c.expanded, c.inaccessible), (1, 1))
        self.assertEqual(c.reasons[0][0], 'AV2')
        self.assertIn('ambíguo', c.reasons[0][1])
        self.assertTrue(result.diagnostic.startswith('Cobertura parcial'))
        self.assertIn('AV2', result.diagnostic)
        self.assertNotIn('Prova fictícia', [r.title for r in result.rows])

    def test_unsafe_and_missing_expanders_are_reported_with_distinct_reasons(self):
        result = self.read([section('Unsafe', collapsed=True, expander='unsafe'),
                            section('SemControle', collapsed=True, expander='none')])
        self.assertEqual(self.sim.clicks, [])
        reasons = dict(result.coverage.reasons)
        self.assertIn('verificável', reasons['Unsafe'])
        self.assertIn('nenhum controle', reasons['SemControle'])
        self.assertEqual(result.state, 'parcial')

    def test_duplicated_content_is_listed_once(self):
        duplicated = [item('resource', 'Slides fictícios', cmid=2), item('resource', 'Slides fictícios', cmid=2),
                      item('page', 'Sem identificador fictícia'), item('page', 'sem identificador fictícia')]
        result = self.read([section('AV1', duplicated), section('Duplicada', []), section('Duplicada', [])])
        items = [r.title for r in result.rows if r.kind != 'Seção']
        self.assertEqual(items, ['Slides fictícios', 'Sem identificador fictícia'])
        self.assertEqual(result.coverage.duplicates, 3)
        self.assertEqual([r.title for r in result.rows if r.kind == 'Seção'].count('Duplicada'), 1)

    def test_expansion_time_limit_leaves_remaining_sections_intact(self):
        sections = [section(f'AV{i}', [item('page', f'Página {i}', cmid=i)], collapsed=True, load_polls=2)
                    for i in range(1, 7)]
        result = self.read(sections, limits=PilotLimits(3000, 5000, 15000, expand_ms=2500))
        self.assertLess(len(self.sim.clicks), 6)
        self.assertEqual(result.state, 'parcial')
        self.assertTrue(any('tempo' in why for _, why in result.coverage.reasons))
        self.assertEqual(result.coverage.expanded + result.coverage.inaccessible, 6)

    def test_section_that_never_expands_is_bounded_and_partial(self):
        sim = CourseSim([section('AV1', [item('page', 'Página', cmid=1)], collapsed=True, on_click='noop')])
        result = self.read(None, sim=sim)
        self.assertEqual(sim.clicks, ['AV1'])
        self.assertLessEqual(sim.polls, 60)
        self.assertEqual(result.state, 'parcial')
        self.assertIn('não expandiu', dict(result.coverage.reasons)['AV1'])

    def test_click_refused_because_page_changed_is_partial(self):
        sim = CourseSim([section('AV1', collapsed=True)])
        sim.sections[0]['expander'] = 'safe'
        original = sim.expand
        sim.expand = lambda options: (dict(original(dict(options, key='9:other'))) if options['mode'] == 'click'
                                      else original(options))
        result = self.read(None, sim=sim)
        self.assertEqual(sim.clicks, [])
        self.assertEqual(result.state, 'parcial')

    def test_nested_section_revealed_by_expansion_is_found_in_a_later_round(self):
        inner = section('AV1 — Parte 2', [item('page', 'Página interna', cmid=9)], collapsed=True)
        outer = section('AV1', [item('page', 'Página externa', cmid=8)], collapsed=True, nested=[inner])
        result = self.read([outer])
        self.assertEqual(self.sim.clicks, ['AV1', 'AV1 — Parte 2'])
        self.assertEqual(result.coverage.expanded, 2)
        self.assertEqual(result.state, 'completa')

    def test_cancel_stops_before_any_further_click_and_keeps_the_page(self):
        sim = CourseSim([section('AV1', collapsed=True), section('AV2', collapsed=True), section('AV3', collapsed=True)])
        with self.assertRaises(PilotRejected) as caught:
            self.read(None, sim=sim, cancelled=lambda: len(sim.clicks) >= 1)
        self.assertEqual(sim.clicks, ['AV1'])
        self.assertIn('cancelada', str(caught.exception).lower())
        sim.close.assert_not_called(); sim.reload.assert_not_called(); sim.goto.assert_not_called()

    def test_session_expiring_during_expansion_discards_everything(self):
        sim = CourseSim([section('AV1', collapsed=True), section('AV2', collapsed=True)])
        sim.after_click = lambda s: setattr(s, 'logged_in', False)
        with self.assertRaises(PilotLoginRequired):
            self.read(None, sim=sim)
        self.assertEqual(sim.clicks, ['AV1'], 'no click after the session was lost')

    def test_navigation_away_during_expansion_stops(self):
        sim = CourseSim([section('AV1', collapsed=True), section('AV2', collapsed=True)])
        sim.after_click = lambda s: setattr(s, 'url', 'https://ead.aedb.br/ava/mod/assign/view.php?id=3')
        with self.assertRaises(PilotRejected):
            self.read(None, sim=sim)
        self.assertEqual(sim.clicks, ['AV1'])

    def test_browser_closed_during_expansion(self):
        sim = CourseSim([section('AV1', collapsed=True), section('AV2', collapsed=True)])
        sim.after_click = lambda s: setattr(s, 'closed', True)
        with self.assertRaises(PilotRejected) as caught:
            self.read(None, sim=sim)
        self.assertIn('Navegador fechado', str(caught.exception))

    def test_number_of_sections_is_capped(self):
        sections = [section(f'S{i}', collapsed=True) for i in range(MAX_EXPAND_SECTIONS + 10)]
        result = self.read(sections)
        self.assertLessEqual(len(self.sim.clicks), MAX_EXPAND_SECTIONS)
        self.assertEqual(result.state, 'parcial')

    def test_zero_sections_is_never_reported_as_complete(self):
        result = self.read([])
        self.assertEqual(result.state, 'nao_validada')
        self.assertEqual(result.coverage.sections_total, 0)
        self.assertIn('estrutura', result.diagnostic)

    def test_reading_without_expansion_never_clicks_and_flags_collapsed_as_inaccessible(self):
        result = self.read([section('AV1', [item('page', 'Oculta', cmid=1)], collapsed=True)], expand=False)
        self.assertEqual(self.sim.clicks, [])
        self.assertEqual(result.state, 'parcial')
        self.assertEqual(result.coverage.inaccessible, 1)

    def test_only_fixed_programs_and_plan_keys_are_sent_and_the_page_is_not_driven(self):
        self.read([section('AV1', [item('page', 'P', cmid=1)], collapsed=True)])
        clicks = [o for kind, o in self.sim.programs if kind == 'expand' and o['mode'] == 'click']
        self.assertEqual([o['key'] for o in clicks], ['0:sec0'])
        for kind, options in self.sim.programs:
            self.assertLessEqual(set(options), {'mode', 'key', 'max_elements', 'timeout_ms', 'max_sections',
                                                'selection_only'})
        for forbidden in ('goto', 'click', 'reload', 'content'):
            getattr(self.sim, forbidden).assert_not_called()

    def test_delivery_status_is_never_inferred(self):
        result = self.read([section('AV1', [item('assign', 'Trabalho fictício', cmid=3)])])
        self.assertIn('entrega não verificado', result.diagnostic)
        self.assertNotIn('pendente', ' '.join(r.due.lower() for r in result.rows))


class ExplorationTests(unittest.TestCase):
    """Scrolling, honest section states and the structural diagnostic."""
    def setUp(self):
        patcher = patch('campus_ai.pilot.time.monotonic', side_effect=lambda: self.sim.now)
        patcher.start(); self.addCleanup(patcher.stop)

    def read(self, sections, *, limits=None, cancelled=None, progress=None, configure=None):
        self.sim = CourseSim(sections)
        if configure:
            configure(self.sim)
        reader = PilotReader(self.sim, self.sim.cdp, limits or PilotLimits())
        return reader.read(CHOSEN, cancelled=cancelled, expand=True, progress=progress)

    def test_content_that_only_appears_after_scrolling_is_read(self):
        late = section('AV2', [item('quiz', 'Prova AV2 fictícia', cmid=4)])
        result = self.read([section('Geral', [item('forum', 'Avisos fictícios', cmid=1)])],
                           configure=lambda sim: (sim.late.append((2, late)), setattr(sim, 'scroll_needed', 4)))
        self.assertEqual([r.title for r in result.rows if r.kind != 'Seção'], ['Avisos fictícios', 'Prova AV2 fictícia'])
        self.assertEqual(result.coverage.sections_total, 2)
        self.assertGreaterEqual(result.coverage.scrolls, 4)
        self.assertEqual(self.sim.events[-1] if False else self.sim.events.count('top') >= 1, True)
        self.assertEqual(result.state, 'completa')

    def test_page_is_returned_to_the_top_and_scrolling_precedes_any_click(self):
        self.read([section('AV1', [item('page', 'P', cmid=1)], collapsed=True)])
        self.assertLess(self.sim.events.index('scroll'), self.sim.events.index('click:AV1'))
        self.assertIn('top', self.sim.events)

    def test_scroll_is_bounded_by_steps_and_flagged_partial(self):
        from campus_ai.pilot import MAX_SCROLL_STEPS
        result = self.read([section('AV1', [item('page', 'P', cmid=1)])],
                           configure=lambda sim: setattr(sim, 'scroll_needed', 10 ** 6))
        self.assertEqual(self.sim.scroll_steps, MAX_SCROLL_STEPS)
        self.assertEqual(result.state, 'parcial')
        self.assertIn('rolagem', result.diagnostic)

    def test_scroll_time_limit_is_flagged_partial(self):
        result = self.read([section('AV1', [item('page', 'P', cmid=1)])], limits=PilotLimits(scroll_ms=1000),
                           configure=lambda sim: setattr(sim, 'scroll_needed', 10 ** 6))
        self.assertLess(self.sim.scroll_steps, 6)
        self.assertEqual(result.state, 'parcial')

    def test_cancel_during_scrolling_stops_before_any_click_and_keeps_the_page(self):
        sim_holder = {}
        def configure(sim):
            sim.scroll_needed = 10 ** 6; sim_holder['sim'] = sim
        with self.assertRaises(PilotRejected) as caught:
            self.read([section('AV1', collapsed=True)], configure=configure,
                      cancelled=lambda: sim_holder['sim'].scroll_steps >= 2)
        self.assertIn('cancelada', str(caught.exception).lower())
        self.assertEqual(self.sim.clicks, [])
        self.sim.close.assert_not_called()

    def test_session_expiring_while_scrolling_discards_the_reading(self):
        with self.assertRaises(PilotLoginRequired):
            self.read([section('AV1', collapsed=True)],
                      configure=lambda sim: setattr(sim, 'on_scroll', lambda s: setattr(s, 'logged_in', False)))
        self.assertEqual(self.sim.clicks, [])

    def test_section_without_content_or_recognized_expander_is_unknown_not_open(self):
        result = self.read([section('AV1', [item('page', 'P', cmid=1)]),
                            section('AV2', [], hint='div.hdr')])
        c = result.coverage
        self.assertEqual((c.sections_total, c.already_open, c.unknown), (2, 1, 1))
        self.assertEqual(result.state, 'parcial')
        reason = dict(c.reasons)['AV2']
        self.assertIn('sem conteúdo visível', reason)
        self.assertIn('div.hdr', reason)
        self.assertIn('1 de estado desconhecido', result.diagnostic)

    def test_nothing_extracted_from_unknown_sections_is_not_validated(self):
        result = self.read([section('', [], hint='div'), section('', [], hint='div')])
        self.assertEqual(result.state, 'nao_validada')
        self.assertTrue(result.diagnostic.startswith('Cobertura não validada'))
        self.assertEqual((result.coverage.unknown, result.coverage.unnamed), (2, 2))
        self.assertEqual(result.rows, [], 'unnamed blocks never become generic "Seção N" rows')

    def test_navigation_to_other_pages_makes_the_reading_partial_and_is_not_followed(self):
        result = self.read([section('AV1', [item('page', 'P', cmid=1)])],
                           configure=lambda sim: setattr(sim, 'nav_missing', 2))
        self.assertEqual(result.state, 'parcial')
        self.assertIn('outra página', result.diagnostic)
        self.assertEqual(result.coverage.nav_missing, 2)
        self.sim.goto.assert_not_called()

    def test_course_index_listing_more_items_than_extracted_is_partial(self):
        result = self.read([section('AV1', [item('page', 'P', cmid=1)])],
                           configure=lambda sim: setattr(sim, 'index', dict(present=True, sections=1, cms=5)))
        self.assertEqual(result.state, 'parcial')
        self.assertIn('índice do curso', result.diagnostic)

    def test_course_index_matching_the_extraction_keeps_it_complete(self):
        result = self.read([section('AV1', [item('page', 'P', cmid=1)])],
                           configure=lambda sim: setattr(sim, 'index', dict(present=True, sections=1, cms=1)))
        self.assertEqual(result.state, 'completa')

    def test_layout_regions_are_counted_as_ignored_not_as_sections(self):
        result = self.read([section('AV1', [item('page', 'P', cmid=1)])],
                           configure=lambda sim: (setattr(sim, 'layout', 5), setattr(sim, 'orphan_links', 1)))
        c = result.coverage
        self.assertEqual((c.sections_total, c.layout, c.candidates, c.orphan_links), (1, 5, 6, 1))
        self.assertEqual(dict(c.ignored)['layout'], 5)
        self.assertIn('regiões candidatas 6', result.diagnostic)

    def test_structural_diagnostic_lists_every_requested_count(self):
        result = self.read([section('AV1', [item('assign', 'T', 'Vencimento: 1/1', cmid=3)], collapsed=True),
                            section('AV2', [item('page', 'P', cmid=4)])])
        for fragment in ('regiões candidatas 2', 'seções acadêmicas reconhecidas', 'expansores seguros 1',
                         'acionados 1', 'elementos de atividade 2', 'itens extraídos 2', 'rolagens', 'ignorados'):
            self.assertIn(fragment, result.diagnostic)
        self.assertNotIn('<', result.diagnostic)


class RuntimeExpansionTests(unittest.TestCase):
    """The 'Analisar' operation itself must expand, read and report coverage."""
    def setUp(self):
        patcher = patch('campus_ai.pilot.time.monotonic', side_effect=lambda: self.sim.now)
        patcher.start(); self.addCleanup(patcher.stop)

    def runtime(self, sections):
        from campus_ai.browser_runtime import BrowserRuntime
        self.sim = CourseSim(sections)
        runtime = BrowserRuntime('https://ead.aedb.br/ava')
        runtime._page = self.sim
        runtime._context = Mock(pages=[self.sim])
        runtime._context.new_cdp_session.return_value = self.sim.cdp
        return runtime

    def course(self):
        from campus_ai.authorized_courses import AuthorizedCourse
        return AuthorizedCourse('42', 'Modelagem Fictícia')

    def test_analyze_opens_av1_and_av2_without_user_help_and_denies_downloads_first(self):
        runtime = self.runtime([section('Geral', [item('forum', 'Avisos fictícios', cmid=1)]),
                                section('AV1', [item('assign', 'Trabalho fictício', 'Vencimento: 20/10/2026', cmid=3)],
                                        collapsed=True),
                                section('AV2', [item('quiz', 'Prova fictícia', cmid=4)], collapsed=True, load_polls=3)])
        states = []
        result = runtime.perform('pilot_analyze', cancelled=lambda: False, progress=states.append,
                                 settings=(self.course(), PilotLimits()))
        self.assertEqual(self.sim.clicks, ['AV1', 'AV2'])
        self.assertEqual(states, ['abrindo', 'autenticado', 'explorando', 'expandindo',
                                 'identificando:AV1', 'identificando:AV2', 'analisando'])
        self.assertEqual(result.state, 'completa')
        self.assertEqual((result.coverage.sections_total, result.coverage.expanded), (3, 2))
        self.assertIn('2 expandidas automaticamente', result.diagnostic)
        self.assertLess(self.sim.events.index('Browser.setDownloadBehavior'), self.sim.events.index('click:AV1'))
        self.sim.goto.assert_not_called()
        self.assertIs(runtime._page, self.sim)

    def test_manual_name_then_read_also_expands(self):
        runtime = self.runtime([section('AV1', [item('page', 'Página fictícia', cmid=1)], collapsed=True)])
        self.sim.base = lambda: dict(CourseSim.base(self.sim), ids=dict(body='', cfg=''))  # no id signal
        pending = runtime.perform('pilot_analyze', cancelled=lambda: False, settings=(self.course(), PilotLimits()))
        self.assertIsInstance(pending, PilotSelection)
        self.assertEqual(self.sim.clicks, [], 'nothing is touched until the student names the course')
        result = runtime.perform('pilot_read', cancelled=lambda: False,
                                 settings=(pending.choose('Modelagem Fictícia'), PilotLimits()))
        self.assertEqual(self.sim.clicks, ['AV1'])
        self.assertEqual(result.state, 'completa')

    def test_cancelled_analysis_keeps_browser_and_leaves_remaining_sections_intact(self):
        runtime = self.runtime([section('AV1', collapsed=True), section('AV2', collapsed=True)])
        with self.assertRaises(PilotRejected):
            runtime.perform('pilot_analyze', cancelled=lambda: len(self.sim.clicks) >= 1,
                            settings=(self.course(), PilotLimits()))
        self.assertEqual(self.sim.clicks, ['AV1'])
        runtime._context.close.assert_not_called()
        self.sim.close.assert_not_called()

    def test_open_only_never_expands(self):
        runtime = self.runtime([section('AV1', collapsed=True)])
        runtime.perform('pilot_open', cancelled=lambda: False, settings=(self.course(), PilotLimits()))
        self.assertEqual(self.sim.clicks, [])


if __name__ == '__main__':
    unittest.main()

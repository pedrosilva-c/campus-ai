"""Owns the live Chromium session in exactly one worker thread.

No credentials are extracted or written by this module. A Moodle login is
usually browser-session scoped; this runtime deliberately does not try to
extend or replay cookies after the browser has closed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable
import os

from .browser_profile import verify_private_profile
from .config import app_dir
from .moodle_browser import MoodleBrowserClient, BrowserUnavailable


class BrowserRuntime:
    def __init__(self, base_url: str, *, playwright_factory: Callable | None = None):
        self.base_url = base_url
        self._factory = playwright_factory
        self._driver = None
        self._context = None
        self._page = None
        self._pilot_reader = None
        self._pilot_selection = None
        self._pilot_context = None    # (course, options) of the analysis in progress
        self._pilot_question = None   # (NavQuestion, selection) awaiting the student's answer

    def _ensure_open(self):
        self._reuse_page()
        if self._page is not None:
            try:
                if not self._page.is_closed():
                    return self._page
            except Exception:
                pass
        self.close()
        # Check the private profile on every fresh launch.
        verify_private_profile()
        expected = app_dir().resolve() / 'browser_profile'
        if expected.is_symlink() or not expected.is_dir():
            raise BrowserUnavailable('Perfil do Moodle ausente ou redirecionado.')
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', '0')
        try:
            if self._factory is None:
                from playwright.sync_api import sync_playwright
                self._driver = sync_playwright().start()
            else:
                self._driver = self._factory()
            self._context = self._driver.chromium.launch_persistent_context(
                user_data_dir=str(expected), headless=False,
                accept_downloads=False, service_workers='block')
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
            return self._page
        except Exception:
            self.close()
            raise BrowserUnavailable('Não foi possível abrir o Chromium privado do Campus AI.') from None

    def perform(self, action: str, *, cancelled: Callable[[], bool] | None = None, settings=None,
                progress: Callable[[str], None] | None = None):
        if action == 'pilot_clear':
            self._detach_pilot()
            self._pilot_selection = None
            return True
        if action in ('pilot_open', 'pilot_analyze'):
            # One call: open the dedicated Chromium directly on the authorized
            # course, wait for the student's manual login if needed, identify the
            # course and (analyze only) read visible titles/deadlines.
            from dataclasses import replace
            from .pilot import PilotReader, PilotRejected, PilotResult
            from .pilot_flow import reach_course
            course, limits = settings[0], settings[1]
            options = settings[2] if len(settings) > 2 and isinstance(settings[2], dict) else {}
            states = []

            def say(state):
                if not states or states[-1] != state:
                    states.append(state)
                    if progress:
                        progress(state)
            say('abrindo')
            self._pilot_selection = self._pilot_question = None
            self._detach_pilot()
            page = self._ensure_open()
            try:
                # Denied before the first navigation to the portal.
                cdp = self._context.new_cdp_session(page)
                cdp.send('Browser.setDownloadBehavior', {'behavior': 'deny'})
            except Exception:
                raise PilotRejected('Não foi possível bloquear downloads. Análise interrompida; '
                                    'nenhuma página foi aberta.') from None
            reader = self._pilot_reader = PilotReader(page, cdp, limits)
            reach_course(page, reader, course, cancelled=cancelled, progress=say)
            if action == 'pilot_open':
                return PilotResult([], 'aberta', 'Disciplina autorizada aberta e sessão reconhecida. '
                                   'Clique em Analisar disciplina.')
            selection = reader.identify(course, cancelled=cancelled)
            self._pilot_selection = selection
            self._pilot_context = (course, options)
            if selection.pending:
                return selection  # The student names the course; no content was read.
            return self._pilot_run(course, selection, options, cancelled, say)
        if action == 'pilot_read':
            from .pilot import PilotRejected
            selected, limits = settings
            # Only a name typed/chosen for the pending selection of this same
            # page is accepted; any other title or URL requires a new analysis.
            try:
                usable = (self._pilot_reader is not None and self._pilot_selection is not None and
                          self._pilot_selection.accepts(selected) and not self._pilot_reader.page.is_closed())
            except Exception:
                usable = False
            if not usable:
                raise PilotRejected('Analise a disciplina antes de ler.')
            self._pilot_reader.limits = limits
            course, options = self._pilot_context
            return self._pilot_run(course, selected, options, cancelled, progress)
        if action == 'pilot_continue':
            from .pilot import PilotRejected
            question, accept, limits = settings
            pending = self._pilot_question
            try:
                usable = (pending is not None and pending[0] == question and self._pilot_reader is not None
                          and not self._pilot_reader.page.is_closed())
            except Exception:
                usable = False
            if not usable:
                raise PilotRejected('Analise a disciplina novamente; a pergunta de navegação não está mais pendente.')
            self._pilot_reader.limits = limits
            course, options = self._pilot_context
            return self._pilot_run(course, pending[1], options, cancelled, progress,
                                   confirmed=question.key if accept else None,
                                   declined=None if accept else question.key)
        if action == 'disconnect':
            self.close()
            MoodleBrowserClient(self.base_url).disconnect()
            return True
        if action == 'scan':
            from .engine import run_scan
            if settings is None or settings.moodle_url != self.base_url:
                raise ValueError('Configuração incompatível com a sessão ativa.')
            # The callback runs on this same owner thread; connector failures
            # remain partial and never prevent Gmail from being processed.
            def scan_live():
                from .moodle_browser import SessionExpired
                if self._page is None or self._page.is_closed():
                    raise SessionExpired('Conecte o navegador manualmente antes de analisar.')
                return MoodleBrowserClient(self.base_url, page=self._page).scan(
                    cancelled=cancelled, max_courses=1, course_id=settings.moodle_course_id)
            return run_scan(settings, browser_scan=scan_live)
        page = self._ensure_open()
        client = MoodleBrowserClient(self.base_url, page=page)
        if action == 'connect':
            return client.connect(cancelled=cancelled)
        if action == 'check':
            return client.check_session()
        if action == 'show':
            if page.url in ('', 'about:blank'):
                page.goto(self.base_url + '/my/', wait_until='domcontentloaded', timeout=15000)
            page.bring_to_front()
            return True
        raise ValueError('Ação Moodle inválida.')

    def _pilot_run(self, course, selection, options, cancelled, progress, *, confirmed=None, declined=None):
        """Read the course through its navigation cards (or the page itself when it has none)."""
        from dataclasses import replace
        from .pilot_nav import CardNavigator, NavQuestion
        outcome = CardNavigator(self._pilot_reader).analyze(
            course, selection, inspect_only=bool(options.get('inspect_only')), confirmed=confirmed,
            declined=declined, cancelled=cancelled, progress=progress)
        if isinstance(outcome, NavQuestion):
            self._pilot_question = (outcome, selection)   # nothing was clicked: the student decides
            return outcome
        self._pilot_question = None
        return replace(outcome, selection=selection)

    def _detach_pilot(self):
        if self._pilot_reader is not None:
            try:
                self._pilot_reader.cdp.detach()
            except Exception:
                pass
        self._pilot_reader = None

    def close(self):
        self._pilot_reader = None
        self._pilot_selection = self._pilot_context = self._pilot_question = None
        context, driver = self._context, self._driver
        self._context = None
        self._driver = None
        self._page = None
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if driver is not None:
            try:
                driver.stop()
            except Exception:
                pass

    def poll_closed(self) -> bool:
        """Dispatch local driver events only; never navigate or reopen on a timer."""
        if self._page is None:
            return False
        try:
            self._reuse_page()
            self._page.wait_for_timeout(1)
            self._reuse_page()
            if not self._page.is_closed():
                return False
        except Exception:
            if self._reuse_page():
                return False
        self.close()
        return True

    def _reuse_page(self):
        if self._context is not None:
            try:
                if self._page is None or self._page.is_closed():
                    previous = self._page
                    self._page = next((p for p in self._context.pages if not p.is_closed()), self._page)
                    return self._page is not previous
            except Exception:
                pass
        return False

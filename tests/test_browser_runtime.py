"""Offline tests: never start Chromium or contact the Moodle portal."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from campus_ai.browser_runtime import BrowserRuntime

URL = 'https://ead.aedb.br/ava'
HOME = '<html><nav class="usermenu"><a href="/ava/login/logout.php">Sair</a></nav></html>'
LOGIN = '<html><form id="login"><input name="password" type="password"></form></html>'


class DummyPage:
    def __init__(self, authenticated=True):
        self.authenticated = authenticated
        self.url = ''
        self.closed = False
        self.foreground = False

    def is_closed(self):
        return self.closed

    def goto(self, url, **kwargs):
        self.url = URL + ('/my/' if self.authenticated else '/login/index.php')

    def content(self):
        return HOME if self.authenticated else LOGIN

    def bring_to_front(self):
        self.foreground = True

    def wait_for_timeout(self, milliseconds):
        pass


class DummyContext:
    def __init__(self, page):
        self.pages = [page]
        self.closed = False

    def close(self):
        self.closed = True
        for page in self.pages:
            page.closed = True


class DummyDriver:
    def __init__(self, authenticated=True):
        self.chromium = self
        self.page = DummyPage(authenticated)
        self.context = None
        self.launches = 0
        self.stopped = False

    def launch_persistent_context(self, **kwargs):
        self.launches += 1
        self.context = DummyContext(self.page)
        return self.context

    def stop(self):
        self.stopped = True


class PersistentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'browser_profile').mkdir()
        self.p1 = patch('campus_ai.browser_runtime.app_dir', return_value=self.root)
        self.p2 = patch('campus_ai.browser_runtime.verify_private_profile')
        self.p1.start()
        self.p2.start()
        self.addCleanup(self.p1.stop)
        self.addCleanup(self.p2.stop)

    def test_check_reuses_same_live_chromium_context(self):
        driver = DummyDriver(authenticated=True)
        runtime = BrowserRuntime(URL, playwright_factory=lambda: driver)
        try:
            self.assertTrue(runtime.perform('connect'))
            self.assertFalse(driver.context.closed)
            self.assertTrue(runtime.perform('check'))
            self.assertEqual(driver.launches, 1)
            self.assertFalse(driver.context.closed)
        finally:
            runtime.close()
        self.assertTrue(driver.context.closed)
        self.assertTrue(driver.stopped)

    def test_browser_show_does_not_close_logged_in_profile(self):
        driver = DummyDriver(authenticated=True)
        runtime = BrowserRuntime(URL, playwright_factory=lambda: driver)
        try:
            runtime.perform('connect')
            runtime.perform('show')
            self.assertTrue(driver.page.foreground)
            self.assertEqual(driver.launches, 1)
        finally:
            runtime.close()

    def test_browser_close_relogin_may_be_required(self):
        first, second = DummyDriver(True), DummyDriver(False)
        drivers = iter((first, second))
        runtime = BrowserRuntime(URL, playwright_factory=lambda: next(drivers))
        try:
            self.assertTrue(runtime.perform('connect'))
            first.page.closed = True
            self.assertFalse(runtime.perform('check'))
            self.assertTrue(first.context.closed)
        finally:
            runtime.close()
        self.assertTrue(second.context.closed)

    def test_closed_context_releases_browser_on_shutdown(self):
        driver = DummyDriver(True)
        runtime = BrowserRuntime(URL, playwright_factory=lambda: driver)
        runtime.perform('connect')
        runtime.close()
        runtime.close()
        self.assertTrue(driver.stopped)

    def test_scan_uses_live_page_and_keeps_context_open(self):
        from campus_ai.config import Settings
        from campus_ai.moodle_browser import BrowserScan
        driver = DummyDriver(True)
        runtime = BrowserRuntime(URL, playwright_factory=lambda: driver)
        self.addCleanup(runtime.close)
        runtime.perform('connect')
        settings = Settings(mode='live', moodle_method='browser', vault_path=str(self.root))
        with patch('campus_ai.moodle_browser.MoodleBrowserClient.scan', autospec=True, return_value=BrowserScan([], [], True)) as scan, \
             patch('campus_ai.engine.app_dir', return_value=self.root), \
             patch('campus_ai.gmail.gmail_enabled', return_value=False):
            runtime.perform('scan', settings=settings)
        scan.assert_called_once()
        self.assertIs(scan.call_args.args[0].page, driver.page)
        self.assertEqual(driver.launches, 1)
        self.assertFalse(driver.context.closed)

    def test_expired_scan_still_processes_other_connector(self):
        from campus_ai.config import Settings
        driver = DummyDriver(False)
        runtime = BrowserRuntime(URL, playwright_factory=lambda: driver)
        self.addCleanup(runtime.close)
        with patch('campus_ai.engine.app_dir', return_value=self.root), \
             patch('campus_ai.gmail.gmail_enabled', return_value=True), \
             patch('campus_ai.gmail.scan_gmail', return_value=[]) as gmail:
            result = runtime.perform('scan', settings=Settings(
                mode='live', moodle_method='browser', vault_path=str(self.root)))
        gmail.assert_called_once()
        self.assertTrue(any('SessionExpired' in warning for warning in result.warnings))

    def test_idle_pumps_driver_and_reports_closed_browser_once(self):
        driver = DummyDriver(True)
        runtime = BrowserRuntime(URL, playwright_factory=lambda: driver)
        self.addCleanup(runtime.close)
        runtime.perform('connect')
        self.assertFalse(runtime.poll_closed())
        driver.page.closed = True
        self.assertTrue(runtime.poll_closed())
        self.assertFalse(runtime.poll_closed())
        self.assertTrue(driver.stopped)

    def test_closing_one_tab_keeps_remaining_session(self):
        driver = DummyDriver(True)
        runtime = BrowserRuntime(URL, playwright_factory=lambda: driver)
        self.addCleanup(runtime.close)
        runtime.perform('connect')
        second = DummyPage(True)
        driver.context.pages.append(second)
        driver.page.closed = True
        self.assertFalse(runtime.poll_closed())
        self.assertTrue(runtime.perform('check'))
        self.assertIs(runtime._page, second)
        self.assertEqual(driver.launches, 1)
        self.assertFalse(driver.context.closed)


if __name__ == '__main__':
    unittest.main()

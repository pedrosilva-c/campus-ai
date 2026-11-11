"""Deterministic, offline regression tests for manual Moodle login lifecycle.

Run: python -m unittest tests.test_moodle_connect_lifecycle -v
These tests do NOT open a browser or access the AEDB portal.
"""
import unittest
from unittest.mock import patch

from campus_ai.moodle_browser import MoodleBrowserClient

BASE = 'https://ead.aedb.br/ava'
HOME = '<html><nav class="usermenu"><a href="/ava/login/logout.php">Sair</a></nav></html>'
LOGIN = '<html><form id="login"><input name="username"><input name="password" type="password"></form></html>'


class DummyPage:
    def __init__(self, initial=HOME, logged_in=True):
        self.url = ''
        self._html = initial
        self.closed = False
        self.logged_in = logged_in
        self.waits = []
        self.visited = []
        self.on_wait = lambda: None

    def goto(self, url, **kwargs):
        self.visited.append(url)
        self.url = url if self.logged_in else BASE + '/login/index.php'

    def content(self):
        if self.closed:
            raise RuntimeError('Target closed')
        return self._html

    def is_closed(self):
        return self.closed

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)
        self.on_wait()


class ManualLoginTests(unittest.TestCase):
    def test_existing_session_recognized_without_waiting(self):
        page = DummyPage()
        client = MoodleBrowserClient(BASE, page=page)
        self.assertTrue(client.connect(wait_seconds=2))
        self.assertEqual(page.visited, [BASE + '/my/'])
        self.assertEqual(page.waits, [])

    def test_manual_login_transition_recognized(self):
        page = DummyPage(initial=LOGIN, logged_in=False)
        def login():
            page._html = HOME
            page.url = BASE + '/my/'
        page.on_wait = login
        client = MoodleBrowserClient(BASE, page=page)
        self.assertTrue(client.connect(wait_seconds=2))
        self.assertGreaterEqual(len(page.waits), 1)

    def test_closed_browser_finishes_cleanly(self):
        page = DummyPage(initial=LOGIN, logged_in=False)
        page.on_wait = lambda: setattr(page, 'closed', True)
        client = MoodleBrowserClient(BASE, page=page)
        self.assertFalse(client.connect(wait_seconds=2))
        self.assertEqual(len(page.waits), 1)

    def test_cancelled_connection_finishes_cleanly(self):
        page = DummyPage(initial=LOGIN, logged_in=False)
        stop = {'value': False}
        page.on_wait = lambda: stop.update(value=True)
        client = MoodleBrowserClient(BASE, page=page)
        self.assertFalse(client.connect(wait_seconds=2, cancelled=lambda: stop['value']))

    def test_page_close_during_driver_wait_is_handled(self):
        page = DummyPage(initial=LOGIN, logged_in=False)
        def closed_wait():
            page.closed = True
            raise RuntimeError('Target closed')
        page.wait_for_timeout = lambda milliseconds: closed_wait()
        client = MoodleBrowserClient(BASE, page=page)
        self.assertFalse(client.connect(wait_seconds=2))

    def test_playwright_wait_not_python_sleep(self):
        page = DummyPage(initial=LOGIN, logged_in=False)
        page.on_wait = lambda: setattr(page, 'closed', True)
        client = MoodleBrowserClient(BASE, page=page)
        with patch('campus_ai.moodle_browser.time.sleep', side_effect=AssertionError('Blocking sleep used')):
            self.assertFalse(client.connect(wait_seconds=2))
        self.assertEqual(len(page.waits), 1)

    def test_zero_timeout_returns_without_wait(self):
        page = DummyPage(initial=LOGIN, logged_in=False)
        client = MoodleBrowserClient(BASE, page=page)
        self.assertFalse(client.connect(wait_seconds=0))
        self.assertEqual(page.waits, [])


if __name__ == '__main__':
    unittest.main()

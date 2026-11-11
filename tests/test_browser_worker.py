"""Queue ownership and cancellation tests without a real Playwright driver."""
import unittest
from threading import Event, get_ident
from unittest.mock import patch
from campus_ai.browser_worker import BrowserWorker


class WorkerTests(unittest.TestCase):
    def test_fifo_operations_and_close_share_owner_thread(self):
        calls = []
        completed = Event()
        class Runtime:
            def __init__(self, url):
                calls.append(('init', get_ident()))
            def perform(self, action, **kwargs):
                calls.append((action, get_ident()))
                if action == 'scan':
                    completed.set()
            def poll_closed(self):
                return False
            def close(self):
                calls.append(('close', get_ident()))
        worker = BrowserWorker('https://example.test')
        with patch('campus_ai.browser_worker.BrowserRuntime', Runtime):
            worker.request('connect')
            worker.request('check')
            worker.request('scan')
            worker.start()
            try:
                self.assertTrue(completed.wait(3))
            finally:
                worker.stop_safely()
                self.assertTrue(worker.wait(3000))
        self.assertEqual([c[0] for c in calls], ['init', 'connect', 'check', 'scan', 'close'])
        self.assertEqual(len({c[1] for c in calls}), 1)
        self.assertNotEqual(calls[0][1], get_ident())
        self.assertFalse(worker.request('connect'))

    def test_progress_states_are_forwarded_from_the_owner_thread(self):
        seen, done = [], Event()
        class Runtime:
            def __init__(self, url):
                pass
            def perform(self, action, progress=None, **kwargs):
                progress('abrindo')
                progress('login')
                return 'ok'
            def poll_closed(self):
                return False
            def close(self):
                pass
        worker = BrowserWorker('https://example.test')
        from PySide6.QtCore import Qt
        worker.progress.connect(lambda op, state: seen.append((op, state)), Qt.ConnectionType.DirectConnection)
        worker.result.connect(lambda op, value: done.set(), Qt.ConnectionType.DirectConnection)
        with patch('campus_ai.browser_worker.BrowserRuntime', Runtime):
            worker.request('pilot_analyze', ('curso', 'limites'))
            worker.start()
            try:
                self.assertTrue(done.wait(3))
            finally:
                worker.stop_safely()
                self.assertTrue(worker.wait(3000))
        self.assertEqual(seen, [('pilot_analyze', 'abrindo'), ('pilot_analyze', 'login')])

    def test_stop_cancels_active_login_and_discards_queued_actions(self):
        entered = Event()
        calls = []
        class Runtime:
            def __init__(self, url):
                pass
            def perform(self, action, cancelled, **kwargs):
                calls.append(action)
                entered.set()
                self_outer.assertTrue(worker._stop.wait(3))
                self_outer.assertTrue(cancelled())
            def close(self):
                calls.append('close')
        self_outer = self
        worker = BrowserWorker('https://example.test')
        with patch('campus_ai.browser_worker.BrowserRuntime', Runtime):
            worker.request('connect')
            worker.request('scan')
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
            finally:
                worker.stop_safely()
                self.assertTrue(worker.wait(3000))
        self.assertEqual(calls, ['connect', 'close'])

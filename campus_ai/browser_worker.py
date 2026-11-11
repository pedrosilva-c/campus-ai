"""Qt worker keeping Playwright and the Chromium window on one thread.

Playwright's synchronous objects must never move between QThreads. Commands
enter this worker through a Python queue; only sanitized statuses go to Qt UI.
"""
from __future__ import annotations

from queue import Queue, Empty
from threading import Event
from PySide6.QtCore import QThread, Signal

from .browser_runtime import BrowserRuntime


class BrowserWorker(QThread):
    result = Signal(str, object)
    failure = Signal(str, str)
    progress = Signal(str, str)  # (operation, state): sanitized UI states only
    browser_closed = Signal()

    def __init__(self, base_url: str, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self._requests = Queue()
        self._cancel = Event()
        self._stop = Event()

    def request(self, operation: str, settings=None) -> bool:
        if self._stop.is_set():
            return False
        self._cancel.clear()
        self._requests.put((operation, settings))
        return True

    def cancel_connection(self) -> None:
        self._cancel.set()

    def stop_safely(self) -> None:
        self._stop.set()
        self._cancel.set()
        self._requests.put(('stop', None))

    def run(self):
        runtime = BrowserRuntime(self.base_url)
        try:
            while not self._stop.is_set():
                try:
                    action, settings = self._requests.get(timeout=0.2)
                except Empty:
                    if runtime.poll_closed():
                        self.browser_closed.emit()
                    continue
                if action == 'stop' or self._stop.is_set():
                    break
                try:
                    outcome = runtime.perform(
                        action, cancelled=self._cancel.is_set, settings=settings,
                        progress=lambda state, op=action: self.progress.emit(op, state))
                except Exception as exc:
                    from .pilot import PilotRejected, PilotResult
                    if isinstance(exc, PilotRejected):
                        self.result.emit(action, PilotResult([], 'falhou', str(exc)))
                        continue
                    # Never emit arbitrary exception text: browser errors can
                    # contain URLs and private query strings.
                    self.failure.emit(action, exc.__class__.__name__)
                else:
                    self.result.emit(action, outcome)
        finally:
            runtime.close()

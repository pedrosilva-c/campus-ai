"""The Jarvis conversation panel of the main window (stage 1: text).

* typed commands run in a worker thread (the window never freezes); "Interromper" asks the running tool to stop;
* the transcript shows what is running, the answers and the files delivered, as links that open the file;
* only files inside the delivery folder can be opened from here (a link never opens anything else);
* due reminders are checked every 30 s and handed to the window (tray notification) and to the transcript.
Text from the conversation is inserted as escaped text; no HTML from anywhere is interpreted.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout,
                               QWidget)

from . import ui_theme as theme
from .jarvis import Jarvis, JarvisStore
from .jarvis.tools import local_text
from .jarvis_chat import ChatInput, ChatView

EXAMPLES = ('O que tenho para fazer hoje?', 'Quais atividades vencem primeiro?', 'Prepare essa atividade',
            'Organize minha semana')
COLUMN = 920                                          # width of the conversation column


class _Worker(QObject):
    finished = Signal(object)

    def __init__(self, jarvis: Jarvis, text: str, cancel: threading.Event):
        super().__init__()
        self.jarvis, self.text, self.cancel = jarvis, text, cancel

    def run(self):
        try:
            reply = self.jarvis.handle(self.text, cancelled=self.cancel.is_set)
        except Exception as exc:                      # the panel must survive anything
            reply = None
            self.finished.emit(exc)
            return
        self.finished.emit(reply)


class JarvisPanel(QWidget):
    reminder_due = Signal(str)                        # text for the tray notification
    ai_status_changed = Signal(object)                # llm.Status, emitted from a background check
    ai_display = Signal(str, str, str)                # short text, tone (ok/warn/muted), full text — for the window

    def __init__(self, parent=None, *, store_path: Path, live_db: Path, output_dir: Path, obsidian_vault: str = '',
                 clock=lambda: datetime.now(timezone.utc), reminder_interval_ms: int = 30000, local_ai=None,
                 start_local_server: bool = False, ai_check_interval_ms: int = 30000):
        """``local_ai``: an llm.OllamaClient (None = rules only). ``start_local_server``: start the portable Ollama of
        this user (LOCALAPPDATA\\CampusAI-Ollama) if it is not running, and stop it on exit if this panel started it."""
        super().__init__(parent)
        self.output_dir = Path(output_dir)
        self.clock = clock
        self.store = JarvisStore(store_path)
        self.ai = local_ai
        self.ai_status = None
        self._server = None
        router = None
        if local_ai is not None:
            from .jarvis.llm import IntentRouter
            router = IntentRouter(local_ai)
        self.jarvis = Jarvis(self.store, live_db=live_db, output_dir=self.output_dir, clock=clock,
                             obsidian_vault=obsidian_vault, router=router)
        self._thread = None
        self._worker = None
        self._cancel = threading.Event()

        self._build(configured=local_ai is not None)
        self.ai_status_changed.connect(self._show_ai_status)
        self._load_history()
        self.reminders = QTimer(self)
        self.reminders.timeout.connect(self.check_reminders)
        self.reminders.start(reminder_interval_ms)
        self.ai_timer = QTimer(self)
        self.ai_timer.timeout.connect(self.refresh_ai_status)
        if local_ai is not None:
            if start_local_server:
                self._start_server_if_needed()
            self.refresh_ai_status(warm=True)
            self.ai_timer.start(ai_check_interval_ms)

    # --- layout (presentation only) --------------------------------------------------------------------------------
    def _build(self, *, configured: bool):
        self.setObjectName('Page')
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        def column(widget_or_layout, margins=(36, 0, 36, 0)):
            row = QHBoxLayout()
            row.setContentsMargins(*margins)
            holder = QWidget()
            holder.setMaximumWidth(COLUMN)
            inner = QVBoxLayout(holder)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.setSpacing(0)
            if isinstance(widget_or_layout, QWidget):
                inner.addWidget(widget_or_layout)
            else:
                inner.addLayout(widget_or_layout)
            row.addWidget(holder, 1)
            return row

        # header: name + a discreet chip with the local AI state
        header = QHBoxLayout()
        header.setSpacing(12)
        title = QLabel('Jarvis')
        title.setObjectName('PageTitle')
        header.addWidget(title)
        header.addStretch(1)
        chip = QFrame()
        chip.setObjectName('StatusChip')
        chip_row = QHBoxLayout(chip)
        chip_row.setContentsMargins(12, 6, 14, 6)
        chip_row.setSpacing(8)
        self.ai_dot = QLabel()
        chip_row.addWidget(self.ai_dot)
        self.ai_label = QLabel()
        self.ai_label.setObjectName('muted')
        self.ai_label.setTextFormat(Qt.TextFormat.PlainText)
        chip_row.addWidget(self.ai_label)
        header.addWidget(chip)
        root.addLayout(column(header, (36, 24, 36, 8)))
        if configured:
            self._set_ai('Verificando a IA local…', 'muted', 'IA local: verificando…')
        else:
            self._set_ai('Interpretação por regras', 'muted',
                         'IA local: não configurada — usando a interpretação por regras')

        # conversation (or the welcome screen while it is empty)
        self.views = QStackedWidget()
        welcome = QWidget()
        welcome.setObjectName('Page')
        w = QVBoxLayout(welcome)
        w.setContentsMargins(0, 0, 0, 0)
        w.setSpacing(10)
        w.addStretch(3)
        mark = QLabel()
        mark.setPixmap(theme.icon('sparkle', theme.ACCENT, 40).pixmap(40, 40))
        w.addWidget(mark)
        w.addSpacing(6)
        greeting = QLabel('Olá. Como posso ajudar hoje?')
        greeting.setObjectName('Greeting')
        w.addWidget(greeting)
        hint = QLabel('Pergunte sobre prazos e pendências, peça para preparar uma atividade, organizar a semana ou criar '
                      'um lembrete. Eu respondo com os seus dados reais e não envio nada ao Moodle nem por e-mail.')
        hint.setObjectName('PageSubtitle')
        hint.setWordWrap(True)
        w.addWidget(hint)
        w.addSpacing(14)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.suggestions = []
        for index, example in enumerate(EXAMPLES):
            suggestion = QPushButton(example)
            suggestion.setObjectName('suggestion')
            suggestion.setCursor(Qt.CursorShape.PointingHandCursor)
            suggestion.clicked.connect(lambda _=False, text=example: self.send(text))
            grid.addWidget(suggestion, index // 2, index % 2)
            self.suggestions.append(suggestion)
        w.addLayout(grid)
        w.addStretch(4)
        self.views.addWidget(welcome)
        self.transcript = ChatView(on_file=self._open_link)
        self.views.addWidget(self.transcript)
        root.addLayout(column(self.views, (36, 8, 28, 0)), 1)

        # composer
        composer = QFrame()
        composer.setObjectName('Composer')
        row = QHBoxLayout(composer)
        row.setContentsMargins(16, 8, 8, 8)
        row.setSpacing(8)
        self.input = ChatInput('Pergunte ao Jarvis…  (ex.: o que tenho para fazer hoje?)')
        self.input.submitted.connect(self.send)
        row.addWidget(self.input, 1, Qt.AlignmentFlag.AlignVCenter)
        self.stop_button = QPushButton()
        self.stop_button.setObjectName('iconButton')
        self.stop_button.setIcon(theme.icon('stop', theme.TEXT, 16))
        self.stop_button.setIconSize(QSize(16, 16))
        self.stop_button.setToolTip('Interromper (Esc)')
        self.stop_button.setAccessibleName('Interromper')
        self.stop_button.setEnabled(False)
        self.stop_button.hide()
        self.stop_button.clicked.connect(self.interrupt)
        row.addWidget(self.stop_button, 0, Qt.AlignmentFlag.AlignBottom)
        self.send_button = QPushButton()
        self.send_button.setObjectName('sendButton')
        self.send_button.setIcon(theme.icon('send', '#FFFFFF', 18))
        self.send_button.setIconSize(QSize(18, 18))
        self.send_button.setToolTip('Enviar (Enter)')
        self.send_button.setAccessibleName('Enviar')
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.clicked.connect(self.send)
        row.addWidget(self.send_button, 0, Qt.AlignmentFlag.AlignBottom)
        self.input.textChanged.connect(self._sync_send)
        self._sync_send()
        root.addLayout(column(composer, (36, 12, 36, 0)))
        foot = QHBoxLayout()
        foot.setContentsMargins(6, 8, 6, 0)
        self.status = QLabel('Pronto.')
        self.status.setObjectName('faint')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        foot.addWidget(self.status, 1)
        keys = QLabel('Enter envia  ·  Shift+Enter quebra a linha')
        keys.setObjectName('faint')
        foot.addWidget(keys)
        root.addLayout(column(foot, (36, 0, 36, 20)))
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.interrupt,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def _sync_send(self):
        self.send_button.setEnabled(not self.busy and bool(self.input.text().strip()))

    def _set_ai(self, short: str, tone: str, full: str):
        color = {'ok': theme.SUCCESS, 'warn': theme.WARNING, 'error': theme.DANGER}.get(tone, theme.FAINT)
        self.ai_dot.setPixmap(theme.dot(color, 8))
        self.ai_label.setText(short)
        self.ai_label.setToolTip(full)
        self.ai_full = full
        self.ai_display.emit(short, tone, full)

    # --- local AI status (checked off the UI thread) --------------------------------------------------------------
    def _start_server_if_needed(self):
        from .jarvis.llm import LocalServer
        status = self.ai.status()
        if status.server:
            return
        server = LocalServer()
        if server.start():
            self._server = server

    def refresh_ai_status(self, warm: bool = False):
        if self.ai is None:
            return
        client = self.ai

        def check():
            status = client.status()
            if not status.server and self._server is not None:     # just started: give it a few seconds
                for _ in range(20):
                    threading.Event().wait(0.5)
                    status = client.status()
                    if status.server:
                        break
            if warm and status.ready:
                self.ai_status_changed.emit(('carregando', status))
                client.warm_up()
            try:
                self.ai_status_changed.emit(status)
            except RuntimeError:                                    # the panel was deleted meanwhile
                pass

        threading.Thread(target=check, name='campus-ai-ia-local-status', daemon=True).start()

    def _show_ai_status(self, status):
        if isinstance(status, tuple):
            model = status[1].model
            self._set_ai(f'Carregando {model}…', 'warn', f'IA local: carregando o modelo {model} na memória (só na '
                         'primeira vez; pode levar até 1–2 min)…')
            return
        self.ai_status = status
        if status.ready:
            short, tone = f'IA local · {status.model}', 'ok'
        elif status.server:
            short, tone = 'IA local · modelo ausente', 'warn'
        else:
            short, tone = 'IA local desligada · regras', 'muted'
        self._set_ai(short, tone, status.text())

    # --- transcript -----------------------------------------------------------------------------------------------
    def _append(self, who: str, text: str, files=()):
        role = 'user' if who == 'Você' else 'note' if who == 'Lembrete' else 'jarvis'
        self.transcript.add(role, who, text, files)
        self.views.setCurrentWidget(self.transcript)

    def _load_history(self):
        for message in self.store.messages(60):
            self._append('Você' if message['role'] == 'user' else 'Jarvis', message['text'],
                         [f for f in message['files'] if Path(f).exists()])

    def _open_link(self, url: QUrl):
        path = Path(url.toLocalFile()).resolve()
        try:
            path.relative_to(self.output_dir.resolve())
        except ValueError:
            self.status.setText('Esse link não aponta para a pasta de entregas do Jarvis; não foi aberto.')
            return
        if path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            self.status.setText('O arquivo não existe mais.')

    # --- running --------------------------------------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self._thread is not None

    def send(self, text=None):
        text = (text if isinstance(text, str) else self.input.text()).strip()
        if not text or self.busy:
            return
        self.input.clear()
        self._append('Você', text)
        self.status.setText(f'Executando: "{text[:80]}"…')
        self.send_button.setEnabled(False)
        self.send_button.hide()
        self.stop_button.setEnabled(True)
        self.stop_button.show()
        self.transcript.typing.start('Jarvis está trabalhando')
        self.transcript.scroll_to_end()
        self._cancel.clear()
        # Lifecycle owned by Qt: the worker lives in the thread; when the thread finishes, Qt deletes both, in the
        # right thread, while the application still exists. (Before: the Python references were dropped and the C++
        # objects were destroyed at interpreter exit, after QApplication -> access violation 0xC0000005/0xC0000409.)
        thread = QThread()
        worker = _Worker(self.jarvis, text, self._cancel)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._done)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._thread_gone)
        self._thread, self._worker = thread, worker
        thread.start()

    def _thread_gone(self):
        self._thread = None
        self._worker = None
        self._sync_send()

    def interrupt(self):
        if self.busy:
            self._cancel.set()
            self.status.setText('Interrompendo…')
            self.stop_button.setEnabled(False)

    def _done(self, reply):
        if isinstance(reply, Exception):
            self._append('Jarvis', f'Falha inesperada ({reply.__class__.__name__}). Nada foi alterado.')
            self.status.setText('Erro: a operação falhou e nada foi alterado.')
        else:
            who = 'Jarvis' if reply.source == 'regras' else f'Jarvis · entendido pela IA local ({reply.source.split(":", 1)[1]})'
            self._append(who, reply.text, reply.files)
            self.status.setText({'cancelado': 'Interrompido.', 'falhou': 'Concluído: a informação pedida não foi encontrada '
                                 'ou não pôde ser obtida (veja a resposta).', 'recusado': 'Concluído: pedido recusado (veja o '
                                 'motivo).', 'aguardando_confirmacao': 'Aguardando sua resposta.'}.get(reply.status, 'Pronto.'))
        self.transcript.typing.stop()
        self.stop_button.setEnabled(False)
        self.stop_button.hide()
        self.send_button.show()
        self._sync_send()
        self.input.setFocus()

    def wait_idle(self, timeout_ms: int = 10000) -> bool:
        """For tests and for closing: process events until the running request ends."""
        from PySide6.QtCore import QCoreApplication, QElapsedTimer
        timer = QElapsedTimer()
        timer.start()
        while self.busy and timer.elapsed() < timeout_ms:
            QCoreApplication.processEvents()
            QThread.msleep(10)
        return not self.busy

    # --- reminders ------------------------------------------------------------------------------------------------
    def check_reminders(self):
        now = self.clock()
        for reminder in self.store.due_reminders(now):
            self.store.mark_delivered(reminder.id)
            when = local_text(datetime.fromisoformat(reminder.due_at))
            self._append('Lembrete', f'{reminder.text} (agendado para {when})')
            self.reminder_due.emit(f'Lembrete: {reminder.text}')

    def shutdown(self):
        """Stops the reminders, interrupts a running request and waits until its thread really ended."""
        self.reminders.stop()
        self.ai_timer.stop()
        self.interrupt()
        self.wait_idle(5000)
        thread = self._thread
        if thread is not None:                         # still running after the wait: never leave it orphaned
            thread.quit()
            thread.wait(5000)
        if self._server is not None:                   # the local AI server this panel started
            self._server.stop()
            self._server = None

"""Native Windows-friendly Qt frontend; no passwords handled by this application."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QDialog, QLineEdit, QFileDialog, QFormLayout, QComboBox,
    QDialogButtonBox, QGroupBox, QSystemTrayIcon, QStyle, QAbstractItemView, QMenu, QCheckBox,
    QSpinBox, QPlainTextEdit, QTabWidget
)
from .config import Settings, app_dir
from .engine import run_scan
from .security import set_secret, get_secret, delete_secret
from .state import History

from .ui_theme import STYLE, apply_theme  # noqa: E402  (dark theme; STYLE kept for callers of the old name)


class Job(QThread):
    success = Signal(object)
    failure = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.success.emit(self.fn())
        except Exception as exc:
            # No token or request content should reach UI error logs.
            if exc.__class__.__name__ == 'BrowserProfileUnsafe':
                self.failure.emit('Perfil Moodle não protegido. Execute a preparação local descrita no README.')
            else:
                self.failure.emit(f'Falha na tarefa ({exc.__class__.__name__}). Confira configurações e rede.')


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle('Configurações — Campus AI')
        self.resize(680, 430)
        layout = QVBoxLayout(self)
        title = QLabel('Integrações e armazenamento local')
        title.setStyleSheet('font-size:17pt;font-weight:700;')
        layout.addWidget(title)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItems(['Demonstração (dados fictícios)', 'Real (Moodle + Gmail)'])
        self.mode.setCurrentIndex(1 if settings.mode == 'live' else 0)
        form.addRow('Modo', self.mode)
        self.vault = QLineEdit(settings.vault_path)
        browse_vault = QPushButton('Escolher pasta')
        browse_vault.clicked.connect(self._pick_vault)
        vr = QHBoxLayout(); vr.addWidget(self.vault); vr.addWidget(browse_vault)
        form.addRow('Vault do Obsidian', vr)
        self.moodle_url = QLineEdit(settings.moodle_url)
        form.addRow('URL base Moodle', self.moodle_url)
        self.moodle_method = QComboBox()
        self.moodle_method.addItems(['API com token autorizado', 'Navegador com login manual'])
        self.moodle_method.setCurrentIndex(1 if settings.moodle_method == 'browser' else 0)
        form.addRow('Acesso Moodle', self.moodle_method)
        self.course_id = QLineEdit(settings.moodle_course_id)
        self.course_id.setPlaceholderText('ID opcional; vazio usa a primeira disciplina visível')
        form.addRow('Disciplina piloto', self.course_id)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText('Token autorizado (nunca a senha da faculdade)')
        token_save = QPushButton('Salvar token')
        token_save.clicked.connect(self._save_token)
        token_remove = QPushButton('Remover')
        token_remove.clicked.connect(self._remove_token)
        tr = QHBoxLayout(); tr.addWidget(self.token); tr.addWidget(token_save); tr.addWidget(token_remove)
        form.addRow('Token Moodle', tr)
        self.token_info = QLabel('Token salvo' if get_secret('moodle-token') else 'Token não configurado')
        self.token_info.setObjectName('muted')
        form.addRow('', self.token_info)
        self.gmail_file = QLineEdit(settings.gmail_credentials_path)
        choose_json = QPushButton('credentials.json')
        choose_json.clicked.connect(self._pick_credentials)
        gr = QHBoxLayout(); gr.addWidget(self.gmail_file); gr.addWidget(choose_json)
        form.addRow('OAuth Google (Desktop)', gr)
        self.gmail_connect = QPushButton('Conectar Gmail pelo navegador')
        self.gmail_connect.clicked.connect(self._connect_gmail)
        self.gmail_disconnect = QPushButton('Desconectar Gmail')
        self.gmail_disconnect.clicked.connect(self._disconnect_gmail)
        gbr = QHBoxLayout(); gbr.addWidget(self.gmail_connect); gbr.addWidget(self.gmail_disconnect)
        form.addRow('', gbr)
        self.gmail_info = QLabel('Gmail conectado' if self._safe_gmail_connected() else 'Gmail não conectado')
        self.gmail_info.setObjectName('muted')
        form.addRow('', self.gmail_info)
        self.gmail_query = QLineEdit(settings.gmail_query)
        self.gmail_query.setPlaceholderText('newer_than:14d')
        form.addRow('Filtro Gmail', self.gmail_query)
        from . import startup
        self.login_start = QCheckBox('Iniciar na bandeja ao entrar no Windows (sem analisar)')
        try:
            self.login_start.setChecked(startup.enabled())
        except OSError:
            self.login_start.setEnabled(False)
        self._initial_startup = self.login_start.isChecked()
        form.addRow('Agente residente', self.login_start)
        self.periodic = QCheckBox('Autorizar análises periódicas das fontes configuradas')
        self.periodic.setChecked(settings.periodic_enabled)
        form.addRow('Agendamento', self.periodic)
        self.interval = QSpinBox()
        self.interval.setRange(15, 1440)
        self.interval.setValue(settings.periodic_minutes)
        self.interval.setSuffix(' minutos')
        form.addRow('Intervalo', self.interval)
        layout.addLayout(form)
        help_label = QLabel('Segurança: a senha da faculdade não entra no Campus AI. O Gmail pede consentimento em uma janela do navegador.\n'
            'Moodle por navegador exige login manual e permissão institucional para automação de leitura.')
        help_label.setObjectName('muted')
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.job = None

    @staticmethod
    def _safe_gmail_connected():
        try:
            from .gmail import gmail_enabled
            return gmail_enabled()
        except Exception:
            return False

    def _pick_vault(self):
        value = QFileDialog.getExistingDirectory(self, 'Selecione o vault do Obsidian', self.vault.text() or str(Path.home()))
        if value:
            self.vault.setText(value)

    def _pick_credentials(self):
        value, _ = QFileDialog.getOpenFileName(self, 'Arquivo OAuth do Google Cloud', str(Path.home()), 'JSON (*.json)')
        if value:
            self.gmail_file.setText(value)

    def _save_token(self):
        token = self.token.text().strip()
        if not token:
            QMessageBox.information(self, 'Token', 'Cole somente um token de webservice válido, se a instituição disponibilizou um.')
            return
        try:
            set_secret('moodle-token', token)
            self.token.clear()
            self.token_info.setText('Token salvo no cofre do sistema')
        except Exception as exc:
            QMessageBox.warning(self, 'Segurança', f'Não foi possível guardar o token com segurança ({exc.__class__.__name__}).')

    def _remove_token(self):
        try:
            delete_secret('moodle-token')
            self.token_info.setText('Token removido do cofre')
        except Exception as exc:
            QMessageBox.warning(self, 'Erro', f'Falha ao remover token ({exc.__class__.__name__}).')

    def _connect_gmail(self):
        filepath = self.gmail_file.text().strip()
        if not Path(filepath).is_file():
            QMessageBox.warning(self, 'OAuth', 'Selecione o credentials.json do Google Cloud (tipo Desktop).')
            return
        self.gmail_connect.setEnabled(False)
        self.gmail_info.setText('Autorização aberta no navegador; conclua o consentimento...')
        from .gmail import connect_gmail
        self.job = Job(lambda: connect_gmail(filepath), self)
        self.job.success.connect(lambda _: self._gmail_result(True))
        self.job.failure.connect(lambda e: self._gmail_result(False, e))
        self.job.start()

    def _gmail_result(self, ok, error=''):
        self.gmail_connect.setEnabled(True)
        self.gmail_info.setText('Gmail conectado com permissão de leitura' if ok else 'Gmail não conectado')
        if not ok:
            QMessageBox.warning(self, 'OAuth', error + '\nConfira permissões da instituição, projeto Google Cloud e usuário de teste.')

    def _disconnect_gmail(self):
        try:
            from .gmail import disconnect_gmail
            disconnect_gmail()
            self.gmail_info.setText('Gmail desconectado localmente')
        except Exception as exc:
            QMessageBox.warning(self, 'Erro', f'Falha ao desconectar ({exc.__class__.__name__}).')

    def _copy_settings(self) -> Settings:
        return Settings(mode='live' if self.mode.currentIndex() else 'demo',
                        vault_path=self.vault.text().strip(),
                        moodle_url=self.moodle_url.text().strip().rstrip('/'),
                        moodle_method='browser' if self.moodle_method.currentIndex() else 'api',
                        gmail_credentials_path=self.gmail_file.text().strip(),
                        gmail_query=self.gmail_query.text().strip() or 'newer_than:14d',
                        max_emails=self.settings.max_emails,
                        moodle_course_id=self.course_id.text().strip(),
                        periodic_enabled=self.periodic.isChecked(), periodic_minutes=self.interval.value())

    def _save(self):
        try:
            settings = self._copy_settings()
            if settings.periodic_enabled and settings != self.settings:
                answer = QMessageBox.question(self, 'Autorizar agendamento',
                    f'Autoriza leitura periódica das fontes configuradas a cada {settings.periodic_minutes} minutos '
                    'e atualização das notas no vault? O Moodle por navegador permanece limitado a uma disciplina. '
                    'Confirme que a política institucional permite esta leitura.',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
            settings.save()
            if self.login_start.isChecked() != self._initial_startup:
                from .startup import configure
                configure(self.login_start.isChecked())
            self.settings = settings
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, 'Erro', f'Confira os campos: {exc}')


class MainWindow(QMainWindow):
    def __init__(self, startup=False, pilot=False):
        super().__init__()
        self.settings = Settings.load()
        self.setWindowTitle('Campus AI — Jarvis')
        self.resize(1360, 860)
        self.setMinimumSize(1040, 680)
        self.current_page = 'jarvis'
        self.job = None
        self._moodle_operation = None
        self._close_pending = False
        self._quitting = False
        self._pilot_active = False
        self._periodic_suspended = False
        self.browser_worker = None
        self._browser_busy = False
        self._browser_op = None
        self._session_valid = False
        self._items = []
        self._settings_open = False
        self._scan_done = False
        self._scan_stats = {'new': 0, 'pending': 0}
        self._overview_tail = 'IA: consulta local • Voz: inativa'
        self._companion = None
        self._companion_signature = None
        self._db_stamp = None
        # Every widget with behaviour is created here, as before; ui_pages only places them (sidebar + pages).
        self.settings_button = QPushButton('Configurações')
        self.settings_button.clicked.connect(self.open_settings)
        self.run_button = QPushButton('Iniciar análise')
        self.run_button.setObjectName('primary')
        self.run_button.clicked.connect(self.start_scan)
        self.labels = {}
        for key in ('total', 'new', 'pending', 'late', 'alerts'):
            self.labels[key] = QLabel('—')
            self.labels[key].setTextFormat(Qt.TextFormat.PlainText)
        self.info = QLabel('Selecione um vault no Obsidian e clique em Executar análise. O modo demonstração é o padrão.')
        self.info.setTextFormat(Qt.TextFormat.PlainText)
        self.info.setWordWrap(True)
        self.companion_box = QGroupBox('Campus AI Companion (Chrome) — leitura da extensão')
        companion_layout = QVBoxLayout(self.companion_box)
        self.companion_status = QLabel('Nenhuma leitura do Campus AI Companion foi recebida ainda.')
        self.companion_status.setTextFormat(Qt.TextFormat.PlainText)
        self.companion_status.setWordWrap(True)
        companion_layout.addWidget(self.companion_status)
        moodle_group = QGroupBox('Leitor antigo (navegador Playwright) — opcional e independente do Companion')
        self.moodle_group = moodle_group
        moodle_layout = QVBoxLayout(moodle_group)
        moodle_layout.setSpacing(12)
        intro = QLabel('Abre um Chromium dedicado com login manual na AEDB. Não é necessário para o Companion. '
                       'A análise das fontes é feita pelo botão "Executar análise" da Visão geral.')
        intro.setObjectName('Tiny')
        intro.setWordWrap(True)
        moodle_layout.addWidget(intro)
        moodle_actions = QHBoxLayout()
        self.moodle_buttons = []
        for label, callback in (                  # "Iniciar análise" was a duplicate of the main analysis button
            ('Conectar conta AEDB', self.connect_moodle),
            ('Verificar sessão', self.check_moodle),
            ('Abrir navegador', self.open_moodle),
            ('Desconectar sessão', self.disconnect_moodle),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            moodle_actions.addWidget(button)
            self.moodle_buttons.append(button)
        moodle_actions.addStretch(1)
        moodle_layout.addLayout(moodle_actions)
        self.moodle_status = QLabel('Sessão do leitor antigo ainda não verificada.')
        self.moodle_status.setObjectName('muted')
        self.moodle_status.setWordWrap(True)
        moodle_layout.addWidget(self.moodle_status)
        self.last_sync = QLabel()
        self.last_sync.setObjectName('muted')
        moodle_layout.addWidget(self.last_sync)
        moodle_layout.addStretch(1)
        self._refresh_moodle_controls()
        self._refresh_last_sync()
        self.items_heading = QLabel('Atividades')
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(['Origem', 'Disciplina', 'Tipo', 'Título', 'Prazo', 'Tempo restante',
                                              'Situação', 'Verificado em'])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for i, width in ((0, 150), (1, 230), (2, 190), (4, 130), (5, 120), (6, 190), (7, 130)):
            self.table.setColumnWidth(i, width)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self.open_item)
        self.overview = QLabel('Disciplinas: aguardando análise • IA: consulta local • Voz: inativa')
        self.overview.setWordWrap(True)
        self.overview.setTextFormat(Qt.TextFormat.PlainText)
        self.recent = QPlainTextEdit()
        self.recent.setReadOnly(True)
        self.recent.setPlaceholderText('Alertas recentes aparecerão após uma análise.')
        # Advanced area (Configurações › Avançado): the old reader, the Companion diagnostic and the pilot.
        self.tabs = QTabWidget()
        reader_page = QWidget()
        reader_layout = QVBoxLayout(reader_page)
        reader_layout.setContentsMargins(16, 16, 16, 16)
        reader_layout.addWidget(moodle_group)
        self.reader_tab = self.tabs.addTab(reader_page, 'Leitor antigo')
        # Campus AI Companion (Chrome): read-only summary of the readings received from the extension.
        self.companion_view = QPlainTextEdit()
        self.companion_view.setReadOnly(True)
        self.companion_tab = self.tabs.addTab(self.companion_view, 'Companion (Chrome)')
        from .pilot_ui import PilotPanel
        from .authorized_courses import load as load_authorized_courses
        self.pilot_panel = PilotPanel(self, load_authorized_courses(app_dir() / 'authorized_courses.json'))
        self.pilot_tab = self.tabs.addTab(self.pilot_panel, 'Teste piloto — Uma disciplina')
        self.pilot_panel.request.connect(self._pilot_request)
        self.pilot_panel.cancel.connect(self._pilot_cancel)
        self.tabs.currentChanged.connect(self._companion_tab_changed)
        # Jarvis (stage 1): conversation with tools over the real local data; its own jarvis.db, never live.db writes.
        from .jarvis_ui import JarvisPanel
        from .jarvis.llm import OllamaClient, find_executable
        # Local AI (Ollama + qwen3.5:4b) only when the portable install of this user exists; otherwise rules only.
        local_ai = OllamaClient() if find_executable() is not None else None
        self.jarvis_panel = JarvisPanel(self, store_path=app_dir() / 'jarvis.db', live_db=app_dir() / 'live.db',
                                        output_dir=Path.home() / 'Documents' / 'Campus AI',
                                        obsidian_vault=self.settings.vault_path or '', local_ai=local_ai,
                                        start_local_server=local_ai is not None)
        self.jarvis_panel.reminder_due.connect(self._jarvis_reminder)
        jarvis_shortcut = QShortcut(QKeySequence('Ctrl+J'), self)
        jarvis_shortcut.activated.connect(self.open_jarvis)
        self.mode_label = QLabel('Modo: ' + ('demonstração' if self.settings.mode == 'demo' else 'real'))
        self.mode_label.setObjectName('muted')
        self.ask_button = QPushButton('Perguntar ao Campus AI')
        self.ask_button.clicked.connect(self.ask_campus)
        self.obsidian_button = QPushButton('Abrir pasta do Obsidian')
        self.obsidian_button.clicked.connect(self.open_obsidian)
        from . import ui_pages
        self._pages = ui_pages
        ui_pages.build(self)
        for index, key in enumerate(('jarvis', 'overview', 'activities', 'materials', 'history', 'integrations',
                                     'settings'), start=1):
            QShortcut(QKeySequence(f'Ctrl+{index}'), self, activated=lambda k=key: self.navigate(k))
        self.navigate('jarvis')
        self.tray = QSystemTrayIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon), self)
        self.tray.setToolTip('Campus AI — assistente acadêmico')
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.reminder = QTimer(self)
        self.reminder.setSingleShot(True)
        self.reminder.timeout.connect(self.ask_on_start)
        menu = QMenu(self)
        menu.addAction('Abrir Campus AI', self.show_interface)
        self.tray_scan = menu.addAction('Analisar agora', self.analyze_from_tray)
        menu.addAction('Lembrar mais tarde', self.remind_later)
        menu.addAction('Ignorar', self.ignore_offer)
        menu.addSeparator()
        menu.addAction('Encerrar Campus AI', self.quit_agent)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.messageClicked.connect(self.show_offer)
        self.offer = None
        self.periodic_timer = QTimer(self)
        self.periodic_timer.timeout.connect(self._periodic_scan)
        self._configure_periodic()
        self._refresh_alerts()
        # New readings saved by the extension appear without restarting: a cheap check of the database file
        # signature every 2 s (a stat call); the database is only read when it actually changed.
        self.companion_timer = QTimer(self)
        self.companion_timer.setInterval(2000)
        self.companion_timer.timeout.connect(self._poll_companion)
        self.companion_timer.start()
        self._refresh_companion(force=True)
        self.tabs.currentChanged.connect(self._pilot_tab_changed)
        if pilot:
            self.tabs.setCurrentIndex(self.pilot_tab)
        if self._tray_available:
            self.tray.show()
        if startup:
            QTimer.singleShot(500, self.ask_on_start)

    # --- navigation (sidebar + pages) -------------------------------------------------------------------------------
    def navigate(self, name: str):
        """Shows a page. While the pilot runs, only Configurações (where the pilot lives) can be shown."""
        if name not in self.pages or (self._pilot_active and name != 'settings'):
            self.sidebar.select(self.current_page)
            return
        self.current_page = name
        self.stack.setCurrentWidget(self.pages[name])
        self.sidebar.select(name)
        if name == 'jarvis':
            self.jarvis_panel.input.setFocus()
        elif name == 'history':
            self._pages.refresh_history(self)
        elif name == 'materials':
            self._pages.refresh_documents(self)
        elif name in ('overview', 'integrations'):
            self._pages.refresh_overview(self)

    def show_advanced(self, index: int):
        self.navigate('settings')
        if not self._pilot_active:
            self.tabs.setCurrentIndex(index)

    def open_jarvis(self):
        self.show_interface()
        if not self._pilot_active:
            self.navigate('jarvis')

    def _jarvis_reminder(self, text):
        if self._tray_available and self.tray.isVisible() and not self._quitting:
            self.tray.showMessage('Campus AI — Jarvis', text[:900], QSystemTrayIcon.MessageIcon.Information, 15000)

    def ask_on_start(self):
        if self._quitting or self._pilot_active:
            return
        if self._tray_available:
            self.tray.showMessage('Campus AI',
                'Quer analisar as novidades acadêmicas? Clique aqui ou use o menu da bandeja.',
                QSystemTrayIcon.MessageIcon.Information, 10000)
        else:
            self.show_offer()

    def show_interface(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_interface()

    def show_offer(self):
        if self._quitting or self._pilot_active:
            return
        if self.offer is not None:
            self.offer.raise_()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Campus AI — análise acadêmica')
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Deseja analisar as fontes configuradas e atualizar o Obsidian?'))
        for label, action in (('Analisar agora', self.analyze_from_tray),
                              ('Lembrar mais tarde', self.remind_later), ('Ignorar', self.ignore_offer)):
            button = QPushButton(label)
            button.clicked.connect(action)
            layout.addWidget(button)
        dialog.finished.connect(self._offer_closed)
        self.offer = dialog
        dialog.show()

    def _offer_closed(self, _=None):
        if self.offer is not None:
            self.offer.deleteLater()
            self.offer = None

    def ignore_offer(self):
        self.reminder.stop()
        if self.offer is not None:
            self.offer.close()

    def remind_later(self):
        self.ignore_offer()
        self.reminder.start(15 * 60 * 1000)

    def analyze_from_tray(self):
        self.ignore_offer()
        self.show_interface()
        self.start_scan()

    def quit_agent(self):
        self._quitting = True
        self.ignore_offer()
        self.close()

    def _history(self):
        return History(app_dir() / ('demo.db' if self.settings.mode == 'demo' else 'live.db'))

    def _refresh_alerts(self):
        rows = self._history().recent_alerts()
        self.recent.setPlainText('\n'.join(f'{date} UTC — {kind}: {message}' for date, kind, message in rows))

    def _notify(self, alerts):
        self._refresh_alerts()
        if alerts and self.tray.isVisible() and not self._quitting:
            text = '\n'.join(f'{alert.kind}: {alert.message}' for alert in alerts[:3])
            if len(alerts) > 3:
                text += f'\nMais {len(alerts) - 3} alerta(s) no histórico.'
            self.tray.showMessage('Campus AI', text[:900], QSystemTrayIcon.MessageIcon.Information, 8000)

    def _configure_periodic(self):
        self.periodic_timer.stop()
        if not self._pilot_active:
            self._periodic_suspended = False
        if self.settings.periodic_enabled is True and not self._pilot_active:
            self.periodic_timer.start(max(15, min(1440, int(self.settings.periodic_minutes))) * 60000)

    def _periodic_scan(self):
        if (self._pilot_active or self._periodic_suspended or not self.settings.periodic_enabled or self._quitting or self._settings_open or
                self._browser_busy or (self.job is not None and self.job.isRunning())):
            return
        if not self.settings.vault_path or not Path(self.settings.vault_path).is_dir():
            return
        # Browser runtime never opens Chromium during a scan. An absent session
        # produces a partial result, so independent connectors can still run.
        self.start_scan()

    def ask_campus(self):
        from .intelligence import local_answer
        dialog = QDialog(self)
        dialog.setWindowTitle('Perguntar ao Campus AI — consulta local')
        dialog.resize(680, 420)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Consulte disciplinas, atividades ou prazos. IA externa ainda não conectada.'))
        question = QLineEdit()
        question.setPlaceholderText('Quais são minhas próximas atividades?')
        output = QPlainTextEdit()
        output.setReadOnly(True)
        send = QPushButton('Consultar dados desta sessão')
        send.clicked.connect(lambda: output.setPlainText(local_answer(question.text(), self._items)))
        layout.addWidget(question)
        layout.addWidget(send)
        layout.addWidget(output)
        dialog.exec()

    def open_settings(self):
        if self._pilot_active or self._quitting or self._browser_busy or (self.job is not None and self.job.isRunning()):
            return
        self._settings_open = True
        dialog = SettingsDialog(self.settings, self)
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            self._settings_open = False
        if accepted:
            if (self.browser_worker is not None and self.browser_worker.isRunning() and
                    (self.settings.moodle_url != dialog.settings.moodle_url or
                     dialog.settings.mode != 'live' or dialog.settings.moodle_method != 'browser')):
                self._browser_busy = True
                self.browser_worker.stop_safely()
                self.moodle_status.setText('Navegador encerrando após mudança de configuração.')
            self.settings = dialog.settings
            self.mode_label.setText('Modo: ' + ('demonstração' if self.settings.mode == 'demo' else 'real'))
            self.info.setText('Configurações salvas. Clique em Iniciar análise.')
            self._refresh_moodle_controls()
            self._refresh_last_sync()
            self._configure_periodic()
            self._refresh_alerts()
            self._items = []
            self.table.setRowCount(0)
            for label in self.labels.values():
                label.setText('—')
            self.overview.setText('Configurações atualizadas. Aguardando próxima análise autorizada.')
            self._refresh_pages()

    def _refresh_moodle_controls(self):
        enabled = self.settings.mode == 'live' and self.settings.moodle_method == 'browser'
        busy = (self.job is not None and self.job.isRunning()) or self._browser_busy or self._quitting
        if hasattr(self, 'tray_scan'):
            self.tray_scan.setEnabled(not busy and not self._pilot_active)
        for button in self.moodle_buttons:
            button.setEnabled(enabled and not busy and not self._pilot_active)
        self.moodle_buttons[0].setText('Conectar conta AEDB')
        if self._browser_busy and self._browser_op == 'connect':
            self.moodle_buttons[0].setText('Cancelar conexão')
            self.moodle_buttons[0].setEnabled(True)
        if not enabled:
            self.moodle_status.setText('Leitor antigo desligado: para usá-lo, selecione modo Real e acesso Moodle por '
                                       'navegador nas Configurações. A leitura pelo Chrome (Companion) não depende dele.')

    def _refresh_last_sync(self):
        if self.settings.mode == 'demo':
            self.last_sync.setText('Leitor antigo — última sincronização: nenhuma no modo demonstração')
            return
        last = History(app_dir() / 'live.db').last_moodle_scan()
        self.last_sync.setText('Leitor antigo — última sincronização: ' +
            (f'{last[0]} UTC — {"completa" if last[1] else "parcial"}' if last else 'nenhuma'))

    def _moodle_job(self, operation, fn=None, *, job=None):
        if self.job is not None and self.job.isRunning():
            return
        self._moodle_operation = operation
        self.job = job if job is not None else Job(fn, self)
        self.job.success.connect(lambda result: self._moodle_done(operation, result))
        self.job.failure.connect(self._moodle_failed)
        self.job.finished.connect(self._moodle_finished)
        self.moodle_status.setText(operation + '...')
        self.run_button.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.job.start()
        self._refresh_moodle_controls()

    def _moodle_finished(self):
        # Only release the QThread after its finished signal (never while running).
        finished_job = self.job
        self.job = None
        self._moodle_operation = None
        if finished_job is not None:
            finished_job.deleteLater()
        self._refresh_moodle_controls()
        self.run_button.setEnabled(True)
        self.settings_button.setEnabled(True)
        if self._close_pending:
            self._close_pending = False
            QTimer.singleShot(0, self.close)

    def _moodle_done(self, operation, result):
        if operation == 'Verificando sessão':
            self.moodle_status.setText('Sessão válida.' if result else 'Login manual necessário.')
        elif operation == 'Conectando AEDB':
            self.moodle_status.setText('Sessão válida.' if result else 'Login não confirmado (janela fechada, cancelamento ou prazo esgotado).')
        else:
            self.moodle_status.setText('Operação concluída.')

    def _moodle_failed(self, error):
        self.moodle_status.setText(error)
        QMessageBox.warning(self, 'Moodle AEDB', error)

    def _browser_client(self):
        from .moodle_browser import MoodleBrowserClient
        return MoodleBrowserClient(self.settings.moodle_url)

    def _ensure_browser_worker(self):
        if self.browser_worker is not None and self.browser_worker.isRunning():
            return self.browser_worker
        from .browser_worker import BrowserWorker
        worker = BrowserWorker(self.settings.moodle_url, self)
        worker.result.connect(self._browser_done)
        worker.failure.connect(self._browser_failed)
        worker.progress.connect(self._browser_progress)
        worker.browser_closed.connect(self._browser_closed)
        worker.finished.connect(self._browser_stopped)
        self.browser_worker = worker
        worker.start()
        return worker

    def _browser_closed(self):
        if self._pilot_active:
            self.pilot_panel.clear()
            self.pilot_panel.status.setText('Estado: navegador fechado. Clique em Analisar disciplina selecionada para reabri-lo.')
        self._session_valid = False
        self.moodle_status.setText('Navegador encerrado. Reconecte e faça login manual se solicitado.')

    def _browser_task(self, operation: str, message: str):
        if self._pilot_active or self._quitting or self._browser_busy or (self.job is not None and self.job.isRunning()):
            return
        self._browser_busy = True
        self._browser_op = operation
        self.moodle_status.setText(message)
        self.run_button.setEnabled(False)
        self.settings_button.setEnabled(False)
        self._refresh_moodle_controls()
        from dataclasses import replace
        self._ensure_browser_worker().request(operation, replace(self.settings) if operation == 'scan' else None)

    def _browser_done(self, operation: str, result):
        if operation == 'pilot_clear':
            return
        if operation.startswith('pilot_'):
            # Release the busy flag first: the panel may immediately request the
            # follow-up read after the student names the course.
            self._browser_complete()
            self.pilot_panel.complete(operation, result)
            return
        if operation == 'scan':
            self._scan_ok(result)
            expired = any('SessionExpired' in w or 'Sessão Moodle expirou' in w for w in result.warnings)
            if expired:
                self._session_valid = False
            self.moodle_status.setText('Sessão AEDB expirada; use Conectar conta AEDB para login manual.'
                                      if expired else 'Análise finalizada; confira os alertas de integração.')
            self._browser_complete()
            return
        if operation == 'connect':
            self._session_valid = bool(result)
            message = ('Sessão válida enquanto o navegador estiver aberto.' if result else
                       'Login não confirmado. Você pode conectar novamente.')
        elif operation == 'check':
            self._session_valid = bool(result)
            message = ('Sessão válida enquanto o navegador estiver aberto.' if result else
                       'Login manual necessário (sessão encerrada ou não reconhecida).')
        elif operation == 'disconnect':
            self._session_valid = False
            message = 'Sessão local desconectada.'
            # The directory was removed; stop the now-idle worker.
            if self.browser_worker is not None:
                self.browser_worker.stop_safely()
            self.moodle_status.setText(message)
            return  # Keep controls locked until the owner thread has exited.
        else:
            message = 'Navegador do Campus AI aberto.'
        self.moodle_status.setText(message)
        if operation in ('check', 'connect') and not result:
            from .notifications import remember
            alert = remember(self._history(), 'Sessão AEDB expirada', 'manual-login', message)
            self._notify([alert] if alert else [])
        self._browser_complete()

    def _browser_failed(self, operation: str, error_class: str):
        if operation.startswith('pilot_'):
            from .pilot import PilotResult
            reason = ('Perfil do navegador não protegido (confira a verificação de ACL).'
                      if error_class == 'BrowserProfileUnsafe' else
                      'Chromium indisponível ou falha inesperada.')
            self._browser_complete()
            self.pilot_panel.complete(operation, PilotResult([], 'falhou',
                f'{reason} ({error_class}) Nenhum dado foi salvo; tente analisar novamente.'))
            return
        if error_class == 'BrowserProfileUnsafe':
            message = 'Perfil Moodle não protegido. Confira a verificação de ACL.'
        elif error_class == 'SessionExpired':
            message = 'Sessão AEDB expirada. Use Conectar conta AEDB para fazer login manual.'
        else:
            message = f'Falha no navegador ({error_class}). Confira a sessão e a rede.'
        self.moodle_status.setText(message)
        self._browser_complete()

    def _browser_progress(self, operation: str, state: str):
        if operation.startswith('pilot_') and self._pilot_active:
            self.pilot_panel.show_progress(state)

    def _browser_complete(self):
        self._browser_busy = False
        self._browser_op = None
        self._refresh_moodle_controls()
        self.run_button.setEnabled(not self._quitting and not self._pilot_active)
        self.settings_button.setEnabled(not self._quitting and not self._pilot_active)

    def _browser_stopped(self):
        former = self.browser_worker
        self.browser_worker = None
        if former is not None:
            former.deleteLater()
        self._browser_busy = False
        self._browser_op = None
        self._refresh_moodle_controls()
        self.run_button.setEnabled(not self._quitting)
        self.settings_button.setEnabled(not self._quitting)
        if self._close_pending:
            self._close_pending = False
            QTimer.singleShot(0, self.close)

    def connect_moodle(self):
        if self._browser_busy and self._browser_op == 'connect':
            self.browser_worker.cancel_connection()
            self.moodle_status.setText('Cancelando conexão, aguarde...')
            self.moodle_buttons[0].setEnabled(False)
            return
        self._browser_task('connect', 'Aguardando login manual no navegador...')

    def check_moodle(self):
        self._browser_task('check', 'Verificando sessão sem analisar disciplinas...')

    def open_moodle(self):
        self._browser_task('show', 'Abrindo navegador...')

    def disconnect_moodle(self):
        answer = QMessageBox.question(self, 'Desconectar AEDB',
            'Apagar o perfil exclusivo do Campus AI e encerrar a sessão local?')
        if answer == QMessageBox.StandardButton.Yes:
            self._browser_task('disconnect', 'Encerrando sessão local...')

    def start_scan(self):
        if self._pilot_active or self._quitting or self._settings_open or self._browser_busy or (self.job is not None and self.job.isRunning()):
            return
        if not self.settings.vault_path or not Path(self.settings.vault_path).is_dir():
            QMessageBox.information(self, 'Primeira configuração',
                    'Crie ou abra um vault no Obsidian e selecione a pasta dele nas Configurações.')
            self.open_settings()
            return
        if self.settings.mode == 'live' and self.settings.moodle_method == 'browser':
            self._browser_task('scan', 'Analisando com a sessão do navegador dedicado...')
            return
        self.run_button.setEnabled(False)
        self.settings_button.setEnabled(False)
        for button in self.moodle_buttons:
            button.setEnabled(False)
        self.info.setText('Lendo fontes conectadas e sincronizando notas locais...')
        self.job = Job(lambda: run_scan(self.settings), self)
        self.job.success.connect(self._scan_ok)
        self.job.failure.connect(self._scan_error)
        self.job.finished.connect(self._moodle_finished)
        self.job.start()

    def _scan_error(self, message):
        self.run_button.setEnabled(True)
        self.settings_button.setEnabled(True)
        self._refresh_moodle_controls()
        self.info.setText(message)
        QMessageBox.warning(self, 'Falha na análise', message)

    def _companion_tab_changed(self, index):
        if index == self.companion_tab:
            self._refresh_companion()

    def _db_signature(self):
        try:
            stat = (app_dir() / 'live.db').stat()
            return (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return None

    def _poll_companion(self):
        stamp = self._db_signature()
        if stamp != self._db_stamp:
            self._refresh_companion()

    def _refresh_companion(self, force=False):
        """Reload what the extension saved (read-only), then update the box, the main table and the tab."""
        from .companion_host import registration_status
        from .companion_store import read_summary, summary_text
        from .companion_view import load_view, status_text
        stamp = self._db_signature()
        try:
            view = load_view(app_dir() / 'live.db')
            self._db_stamp = stamp
        except Exception:                 # locked while the host writes, or damaged: keep what is shown, retry later
            if not force:
                return
            view = self._companion
        signature = view.signature if view is not None else None
        changed = force or signature != self._companion_signature
        self._companion, self._companion_signature = view, signature
        if not changed:
            return
        self.companion_status.setText(status_text(view))
        self._render_items()
        self._refresh_pages()
        try:
            text = summary_text(read_summary(app_dir() / 'live.db'))
        except Exception as exc:        # a locked or damaged database must not break the window
            text = f'Resumo do Companion indisponível ({exc.__class__.__name__}).'
        host = {'registrado': 'host Native Messaging registrado para este usuário.',
                'nao_registrado': 'host Native Messaging não registrado neste Windows (ativação pendente de '
                                  'autorização).'}.get(registration_status(), 'estado do registro indisponível.')
        self.companion_view.setPlainText(text + '\n\nIntegração local: ' + host)

    def _refresh_pages(self):
        """Read-only summaries of the pages (overview, materials, integrations) from what the window has loaded."""
        self._pages.refresh_overview(self)
        self._pages.refresh_materials(self)

    def _render_items(self):
        """One table for every source: the last scan's items plus the Companion modules (read from live.db)."""
        from .companion_view import SOURCE_LABEL, STATE_TEXT, urgency
        from .deadlines import SITUATION_TEXT
        comp = self._companion if (self._companion is not None and self._companion.has_reading) else None
        if not self._scan_done and comp is None:
            return
        # Most urgent first: late, pending (earliest deadline first), ..., done, materials last.
        rows = sorted((r for r in comp.rows), key=urgency) if comp else []
        self.labels['total'].setText(str(len(self._items) + (comp.modules if comp else 0)))
        self.labels['new'].setText(str(self._scan_stats['new'] + (comp.novos + comp.alterados if comp else 0)))
        self.labels['pending'].setText(str(self._scan_stats['pending'] + (comp.confirmed_pending if comp else 0)))
        self.table.setRowCount(0)

        # Late = red, due within 72 h = amber, done/submitted = green. The text says it too (never colour only).
        from .ui_theme import TONES as tones

        def add(columns, tooltip, url, tone=None):
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, value in enumerate(columns):
                cell = QTableWidgetItem(str(value))
                cell.setToolTip(tooltip)
                cell.setData(Qt.ItemDataRole.UserRole, url)
                if tone and col in (4, 5, 6):                    # deadline, time left, situation
                    cell.setForeground(QBrush(QColor(tones[tone][1])))
                    if col == 6:
                        cell.setBackground(QBrush(QColor(tones[tone][0])))
                self.table.setItem(row, col, cell)

        for item in sorted(self._items, key=lambda i: (i.due_iso or '9999', i.course, i.title)):
            add([item.source, item.course, item.category + (' • enviado' if item.status == 'submitted' else ''),
                 item.title, item.due_iso[:16].replace('T', ' ') if item.due_iso else '—', '', '', ''],
                item.description[:500], item.url)
        for r in rows:
            kind = f'{r.kind_label} • {"Material" if r.category == "material" else "Atividade"}'
            if r.assessment:
                kind += f' • {r.assessment}'
            if STATE_TEXT.get(r.state):
                kind += f' • {STATE_TEXT[r.state]}'
            tip = f'Origem: {SOURCE_LABEL} • visto pela última vez em {r.last_seen_local}'
            if r.verified_local:
                tip += (f'\nPrazo e entrega lidos na página da atividade em {r.verified_local} '
                        f'(horário de Brasília). Entrega: {r.delivery_text}.')
            elif r.situation != 'nao_se_aplica':
                tip += '\nPrazo e entrega: não verificados (a página desta atividade ainda não foi lida).'
            else:
                tip += '\nPrazo e entrega: não verificados (a página deste tipo de módulo não é consultada).'
            if r.check_note:
                tip += f'\n{r.check_note}'
            if r.assessment:
                tip += f'\nGrupo {r.assessment}: pode ter sido inferido pela posição na página.'
            if r.url:
                tip += '\nDuplo clique abre o módulo no navegador.'
            place = f'{r.course_name} › {r.section_name}' if r.section_name else r.course_name
            due = r.due_text or 'não verificado'          # unknown is never shown as "no deadline"
            situation = SITUATION_TEXT.get(r.situation, r.situation)
            if r.soon and r.situation == 'pendente':
                situation += ' — vence em até 72 h'
            tone = ('late' if r.situation == 'atrasada' else 'soon' if r.soon else
                    'done' if r.situation in ('concluida', 'aguardando_avaliacao', 'enviada') else None)
            add([SOURCE_LABEL, place, kind, r.title, due, r.time_left, situation, r.verified_local or '—'], tip, r.url,
                tone)
        courses = sorted({i.course for i in self._items} | ({comp.course_name} if comp else set()))
        self.overview.setText(f'Disciplinas: {", ".join(courses) or "nenhuma identificada"} • {self._overview_tail}')
        self._pages.apply_filter(self)


    def _pilot_tab_changed(self, index):
        entering = index == self.pilot_tab
        if not entering and not self._pilot_active:
            return
        if self._browser_busy or (self.job is not None and self.job.isRunning()):
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(self.pilot_tab if self._pilot_active else 0)
            self.tabs.blockSignals(False)
            return
        if entering:                                   # the pilot lives in Configurações › Avançado: show it there
            self.navigate('settings')
        self._pilot_active = entering
        self._periodic_suspended = True
        # While the pilot runs, the rest of the app is out of reach (as before, when its panels were hidden).
        for key, nav in self.sidebar.buttons.items():
            nav.setEnabled(not entering or key == 'settings')
        for widget in (self.ask_button, self.obsidian_button):
            widget.setEnabled(not entering)
        self.mode_label.setText('Piloto temporário — sem dados fictícios ou sincronização' if entering else
                               'Modo: ' + ('demonstração' if self.settings.mode == 'demo' else 'real'))
        self.periodic_timer.stop()
        self.ignore_offer()
        if not entering:
            self.pilot_panel.clear()
            if self.browser_worker is not None and self.browser_worker.isRunning():
                self.browser_worker.request('pilot_clear')
        self.run_button.setEnabled(not entering)
        self.settings_button.setEnabled(not entering)
        self._refresh_moodle_controls()

    def _pilot_request(self, operation, payload):
        from .pilot import PilotResult
        if (not self._pilot_active or self._quitting or self._browser_busy or
                (self.job is not None and self.job.isRunning())):
            return
        if operation in ('pilot_open', 'pilot_analyze'):
            worker = self._ensure_browser_worker()  # The worker is the single Chromium owner.
        elif self.browser_worker is None or not self.browser_worker.isRunning():
            self.pilot_panel.complete(operation, PilotResult([], 'falhou',
                'Analise a disciplina antes de ler. Nenhum navegador foi iniciado.'))
            return
        else:
            worker = self.browser_worker
        self._browser_busy = True
        self._browser_op = operation
        self._refresh_moodle_controls()
        worker.request(operation, payload)

    def _pilot_cancel(self):
        # Cooperative: only the current operation is abandoned; the browser,
        # its persistent profile and the signed-in session stay open.
        if self.browser_worker is not None and self._browser_op in ('pilot_open', 'pilot_analyze', 'pilot_read',
                                                                         'pilot_continue'):
            self.browser_worker.cancel_connection()

    def _scan_ok(self, result):
        self._items = result.items
        self.run_button.setEnabled(True)
        self.settings_button.setEnabled(True)
        self._refresh_moodle_controls()
        self._refresh_last_sync()
        self._scan_done = True
        self._scan_stats = {'new': len(result.new_items), 'pending': sum(i.status == 'pending' for i in result.items)}
        self.labels['alerts'].setText(str(len(result.warnings)))
        summary = f'Última análise: {datetime.now():%d/%m/%Y %H:%M} • {len(result.new_items)} novo(s)/alterado(s) • notas em Campus AI/.'
        if result.warnings:
            summary += ' ATENÇÃO: ' + ' | '.join(result.warnings)
        if self.settings.mode == 'demo':
            summary = 'DADOS FICTÍCIOS DE DEMONSTRAÇÃO. ' + summary
        self.info.setText(summary)
        gmail_status = 'com alerta' if any('Gmail' in w for w in result.warnings) else ('demonstração' if self.settings.mode == 'demo' else 'consultado')
        self._overview_tail = (f'Gmail: {gmail_status} • Obsidian: {result.notes_written} escrita(s) • '
                               'IA: consulta local')
        self._render_items()
        self._refresh_pages()
        from .notifications import collect_alerts
        self._notify(collect_alerts(self._history(), result))

    def closeEvent(self, event):
        if self._tray_available and not self._quitting:
            self.hide()
            event.ignore()
            return
        self._quitting = True
        self.reminder.stop()
        self.periodic_timer.stop()
        if getattr(self, 'jarvis_panel', None) is not None:
            self.jarvis_panel.shutdown()               # stops reminders, interrupts a running request, waits briefly
        if self.browser_worker is not None and self.browser_worker.isRunning():
            self._close_pending = True
            self.browser_worker.stop_safely()
            self.moodle_status.setText('Encerrando navegador com segurança...')
            event.ignore()
            return
        if self.job is not None and self.job.isRunning():
            self._close_pending = True
            self.job.requestInterruption()
            self.moodle_status.setText('Encerrando operação com segurança...')
            event.ignore()
            return
        # OAuth can still own a worker in the settings dialog. Never destroy a
        # running QThread when quitting through the tray.
        for thread in self.findChildren(QThread):
            if thread.isRunning():
                thread.finished.connect(self.close, Qt.ConnectionType.UniqueConnection)
                event.ignore()
                return
        self.tray.hide()
        super().closeEvent(event)
        QApplication.instance().quit()

    def open_item(self, row, col):
        url = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if url and str(url).startswith('https://'):
            QDesktopServices.openUrl(QUrl(str(url)))

    def open_obsidian(self):
        if self.settings.vault_path:
            path = Path(self.settings.vault_path) / 'Campus AI'
            if path.is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                return
        QMessageBox.information(self, 'Obsidian', 'Selecione um vault e execute a análise para criar a pasta Campus AI.')


def launch(startup=False, pilot=False):
    import sys
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)
    window = MainWindow(startup, pilot=pilot)
    if not startup or not window._tray_available:
        window.show()
    sys.exit(app.exec())

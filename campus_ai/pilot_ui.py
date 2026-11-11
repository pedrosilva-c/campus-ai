"""Temporary pilot surface, independent of history and vaults.

One button ("Analisar disciplina") does everything: the worker opens the dedicated Chromium on
the authorized course, waits for the student's manual login if needed, identifies the course, goes
through its navigation cards (Atividades Avaliativas first), reads visible titles and deadlines and
returns to the course home. A dialog appears only when the course name cannot be confirmed, or when
a card's behaviour cannot be verified in advance and the student must decide.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QAbstractItemView, QInputDialog, QMessageBox,
    QCheckBox)
from .pilot import PilotLimits, PilotResult
from .pilot_nav import NavQuestion

PROGRESS_TEXT = {
    'abrindo': 'Abrindo disciplina (navegador dedicado)...',
    'login': 'Login necessário: entre manualmente na janela do Chromium. A análise continua sozinha depois do login.',
    'autenticado': 'Autenticado. Identificando a disciplina...',
    'explorando': 'Rolando a página para carregar conteúdo tardio (nada é clicado)...',
    'expandindo': 'Expandindo seções recolhidas da disciplina (nenhuma atividade é aberta)...',
    'analisando': 'Extraindo materiais, atividades e prazos visíveis...',
    'verificando': 'Verificando cobertura e voltando à página da disciplina...',
}
# States that carry a name found on the page: "acessando:<cartão>", "identificando:<seção>".
DETAIL_TEXT = {'acessando': 'Acessando {}...', 'identificando': 'Identificando {}...'}
# 'completa' only ever means: every identified section was examined (see the coverage counts).
RESULT_LABEL = {'completa': 'cobertura completa', 'parcial': 'cobertura parcial',
                'nao_validada': 'cobertura não validada', 'falhou': 'erro', 'aberta': 'navegador pronto'}


class PilotPanel(QWidget):
    request = Signal(str, object)
    cancel = Signal()

    def __init__(self, parent=None, courses=()):
        super().__init__(parent)
        self.selection = None
        self.cancelled = False
        self.courses = list(courses)
        layout = QVBoxLayout(self)
        help_text = QLabel('Clique em Analisar disciplina. O Campus AI abre o navegador dedicado na disciplina, '
            'aguarda seu login manual se necessário, entra sozinho no cartão Atividades Avaliativas (só depois de '
            'validar o destino), abre as seções recolhidas e lê títulos, materiais, atividades e prazos visíveis, '
            'voltando à disciplina no fim. Nunca aciona Feedback das Aulas, Fale com o Professor, envio, conclusão '
            'ou download. Nada é salvo. O Moodle pode registrar o acesso e lembrar seções abertas.')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.course = QLabel('Disciplina: nenhuma análise ainda')
        self.status = QLabel('Estado: aguardando • Itens: 0')
        for label in (self.course, self.status):
            label.setTextFormat(Qt.TextFormat.PlainText); label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)  # copy the diagnostic
            layout.addWidget(label)
        controls = QHBoxLayout()
        self.combo = QComboBox()
        for course in self.courses:
            self.combo.addItem(f'{course.name} (id {course.course_id})', course)
        controls.addWidget(self.combo, 1)
        self.analyze_button = QPushButton('Analisar disciplina')
        self.cancel_button = QPushButton('Cancelar')
        self.analyze_button.clicked.connect(self.analyze_course)
        self.cancel_button.clicked.connect(self.cancel_read)
        for button in (self.analyze_button, self.cancel_button): controls.addWidget(button)
        layout.addLayout(controls)
        self.inspect_check = QCheckBox('Somente inspecionar a estrutura dos cartões (não navega nem lê conteúdo)')
        layout.addWidget(self.inspect_check)
        self.progress = QProgressBar(); self.progress.setRange(0, 1); self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Disciplina', 'Seção', 'Tipo', 'Título', 'Prazo'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        self.busy(False)
        self.progress.setValue(0)

    def limits(self):
        return PilotLimits()

    def current_course(self):
        return self.combo.currentData()

    def busy(self, value):
        ready = not value and self.current_course() is not None
        self.analyze_button.setEnabled(ready)
        self.inspect_check.setEnabled(not value)
        self.combo.setEnabled(not value and self.combo.count() > 1)
        self.cancel_button.setEnabled(value)
        self.progress.setRange(0, 0 if value else 1)
        self.progress.setValue(0 if value else 1)

    def _begin(self, operation, message):
        course = self.current_course()
        if course is None:
            return
        self.selection = None
        self.cancelled = False
        self.table.setRowCount(0)
        self.course.setText(f'Disciplina: {course.name}')
        self.status.setText(message)
        self.busy(True)
        self.request.emit(operation, (course, self.limits(), {'inspect_only': self.inspect_check.isChecked()}))

    def analyze_course(self):
        self._begin('pilot_analyze', 'Estado: ' + PROGRESS_TEXT['abrindo'])

    def cancel_read(self):
        self.cancelled = True
        self.cancel.emit()
        self.status.setText('Cancelamento solicitado. O navegador e a sessão serão preservados...')
        self.cancel_button.setEnabled(False)

    def show_progress(self, state):
        if self.cancelled:
            return
        name, _, detail = str(state).partition(':')
        if detail and name in DETAIL_TEXT:
            self.status.setText('Estado: ' + DETAIL_TEXT[name].format(detail[:80]))
        elif name in PROGRESS_TEXT:
            self.status.setText('Estado: ' + PROGRESS_TEXT[name])

    def _ask_card(self, question):
        """A card's behaviour could not be verified. Nothing was touched; 'No' is the default."""
        box = QMessageBox(self)
        box.setWindowTitle('Cartão sem destino verificável')
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(f'O cartão "{question.label}" não tem um destino que o Campus AI consiga verificar antes de '
                    f'acioná-lo ({question.reason}).\n\nPermitir que ele seja acionado uma única vez? A leitura '
                    'continuará marcada como parcial. Se responder Não, nada será acionado e só a página inicial '
                    'será lida.')
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _ask_name(self, pending):
        """The only dialog: shown when neither the visible title nor the page's course id
        confirmed the course. Typing a name is a label; reading still needs the authorized URL."""
        items = list(pending.choices) or [pending.title]
        text, ok = QInputDialog.getItem(
            self, 'Confirmar nome da disciplina',
            'Não foi possível confirmar o nome desta disciplina automaticamente.\n'
            'Escolha ou digite o nome da disciplina autorizada (nada além desta página será aberto):',
            items, 0, pending.confidence == 'manual')
        if not ok:
            return None
        try:
            return pending.choose(text)
        except Exception:
            return None

    def complete(self, operation, result):
        if self.cancelled:
            result = PilotResult([], 'falhou',
                'Cancelada pelo usuário. Nenhum resultado aplicado; o navegador e a sessão foram preservados.')
        if isinstance(result, PilotResult):
            self.table.setRowCount(0)
            for row in result.rows:
                index = self.table.rowCount(); self.table.insertRow(index)
                for column, text in enumerate((row.course, row.section, row.kind, row.title, row.due)):
                    cell = QTableWidgetItem(text)
                    cell.setToolTip(row.url if column == 3 and row.url else text)
                    self.table.setItem(index, column, cell)
            label = RESULT_LABEL.get(result.state, result.state)
            if result.state == 'nao_validada' and result.diagnostic.startswith('Modo de inspeção'):
                label = 'inspeção estrutural (nada foi lido)'
            items = sum(1 for row in result.rows if row.kind != 'Seção')
            self.status.setText(f'Estado: {label} • Itens: {items}\n{result.diagnostic}')
            chosen = result.selection
            if chosen is not None:
                origin = ', '.join(chosen.sources) or 'fonte não detalhada'
                self.course.setText(f'{chosen.title}\n{chosen.url}\nIdentificação: {chosen.confidence} ({origin})')
            if result.state == 'falhou':
                self.selection = None
                self.course.setText('Análise não concluída. Veja o estado abaixo e clique em Analisar novamente.')
            self.busy(False)
            return
        if isinstance(result, NavQuestion):
            accept = self._ask_card(result)
            self.status.setText('Estado: ' + ('Acessando ' + result.label + ' com sua confirmação...' if accept else
                                              'Cartão não autorizado: lendo somente a página inicial...'))
            self.busy(True)
            self.request.emit('pilot_continue', (result, accept, self.limits()))
            return
        chosen = self._ask_name(result)
        if chosen is None:
            self.selection = None
            self.status.setText('Estado: nome não confirmado. Nenhuma leitura de materiais iniciada.')
            self.busy(False)
            return
        # The student's choice is the authorization to read this one page.
        self.selection = chosen
        self.course.setText(f'{chosen.title}\n{chosen.url}\nIdentificação: {chosen.confidence}')
        self.status.setText('Estado: ' + PROGRESS_TEXT['analisando'])
        self.busy(True)
        self.request.emit('pilot_read', (chosen, self.limits()))

    def clear(self):
        self.selection = None
        self.table.setRowCount(0)
        self.course.setText('Disciplina: nenhuma análise ainda')
        self.status.setText('Dados temporários limpos • Estado: aguardando')
        self.busy(False)
        self.progress.setValue(0)

"""Pages of the main window: where each existing widget lives. Presentation only.

The window (``ui.MainWindow``) creates and owns every widget with behaviour (buttons, labels, the table, the panels);
this module only places them in a sidebar + pages shell and renders read-only summaries of data the window already
loaded (the Companion view, the Jarvis store). Nothing here writes anywhere or invents a number: what is unknown is
said to be unknown.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from . import ui_theme as theme
from .ui_widgets import MetricTile, PageHeader, Sidebar, StatusLine, button, card, divider, label, page

PAGES = (('jarvis', 'Jarvis', 'jarvis'), ('overview', 'Visão geral', 'overview'),
         ('activities', 'Atividades', 'activities'), ('materials', 'Materiais', 'materials'),
         ('history', 'Histórico', 'history'), ('integrations', 'Integrações', 'integrations'))
BOTTOM = (('settings', 'Configurações', 'settings'),)

FILTERS = (('Todos os itens', None), ('Só atividades', 'atividade'), ('Atrasadas', 'atrasada'),
           ('Pendentes', 'pendente'), ('Prazo não verificado', 'nao_verificado'), ('Materiais', 'material'))


# --- shell ----------------------------------------------------------------------------------------------------------
def build(w) -> None:
    """Sidebar + stacked pages on the window ``w``; sets ``w.sidebar``, ``w.stack``, ``w.pages``, ``w.page_names``."""
    root = QWidget()
    root.setObjectName('Root')
    row = QHBoxLayout(root)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)
    w.sidebar = Sidebar(PAGES, BOTTOM)
    w.sidebar.navigated.connect(w.navigate)
    row.addWidget(w.sidebar)
    w.stack = QStackedWidget()
    w.stack.setObjectName('Content')
    row.addWidget(w.stack, 1)
    w.pages = {}
    for key, builder in (('jarvis', _jarvis), ('overview', _overview), ('activities', _activities),
                         ('materials', _materials), ('history', _history), ('integrations', _integrations),
                         ('settings', _settings)):
        widget = builder(w)
        w.pages[key] = widget
        w.stack.addWidget(widget)
    w.page_names = tuple(w.pages)
    w.setCentralWidget(root)
    w.jarvis_panel.ai_display.connect(lambda short, tone, full: _ai_changed(w, short, tone, full))
    _ai_changed(w, w.jarvis_panel.ai_label.text(), 'muted', getattr(w.jarvis_panel, 'ai_full', ''))


def _ai_changed(w, short, tone, full):
    w.sidebar.ai.set(short, tone)
    w.sidebar.ai.setToolTip(full)
    detail = full.replace('IA local: ', '') if full else short
    w.integration_lines['ai'].set(detail[:1].upper() + detail[1:], tone)
    w.overview_lines['ai'].set(short, tone)
    w.ai_detail.setText(full or short)


# --- Jarvis ---------------------------------------------------------------------------------------------------------
def _jarvis(w):
    return w.jarvis_panel


# --- overview -------------------------------------------------------------------------------------------------------
class DeadlineList(QWidget):
    """Rows: title / place on the left, deadline and a situation pill on the right."""

    def __init__(self):
        super().__init__()
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(0)

    def clear(self):
        while self.layout_.count():
            item = self.layout_.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def set_rows(self, rows, empty: str):
        self.clear()
        if not rows:
            self.layout_.addWidget(label(empty, 'muted'))
            return
        for title, place, due, pill, tone in rows:
            frame = QFrame()
            frame.setObjectName('Row')
            line = QHBoxLayout(frame)
            line.setContentsMargins(0, 10, 0, 10)
            line.setSpacing(12)
            text = QVBoxLayout()
            text.setSpacing(2)
            name = label(title)
            text.addWidget(name)
            text.addWidget(label(place, 'Tiny'))
            line.addLayout(text, 1)
            if due:
                line.addWidget(label(due, 'muted', wrap=False), 0, Qt.AlignmentFlag.AlignVCenter)
            line.addWidget(pill_label(pill, tone), 0, Qt.AlignmentFlag.AlignVCenter)
            self.layout_.addWidget(frame)


def pill_label(text: str, tone: str | None) -> QLabel:
    widget = label(text, 'Pill', wrap=False)
    background, color = theme.TONES.get(tone, (theme.SURFACE_2, theme.MUTED))
    widget.setStyleSheet(f'background:{background}; color:{color};')
    return widget


def _overview(w):
    area, col = page()
    w.run_button.setText('Executar análise')
    w.run_button.setIcon(theme.icon('refresh', '#FFFFFF', 16))
    w.run_button.setToolTip('Lê as fontes configuradas (modo demonstração ou real) e atualiza as notas do Obsidian.')
    col.addWidget(PageHeader('Visão geral', 'O que importa agora, a partir das leituras verificadas.',
                             actions=[w.run_button]))
    w.info.setObjectName('Notice')
    col.addWidget(w.info)
    grid = QGridLayout()
    grid.setHorizontalSpacing(14)
    for index, (key, caption) in enumerate((('pending', 'Pendências indicadas'), ('late', 'Atrasadas (verificadas)'),
                                            ('new', 'Novos ou alterados'), ('total', 'Itens identificados'))):
        grid.addWidget(MetricTile(w.labels[key], caption), 0, index)
    col.addLayout(grid)

    columns = QHBoxLayout()
    columns.setSpacing(16)
    deadlines, box = card()
    box.addWidget(label('Próximos prazos', 'SectionTitle'))
    w.overview_deadlines = DeadlineList()
    box.addWidget(w.overview_deadlines)
    box.addStretch(1)
    more = button('Ver todas as atividades', kind='ghost', slot=lambda: w.navigate('activities'))
    box.addWidget(more, 0, Qt.AlignmentFlag.AlignLeft)
    columns.addWidget(deadlines, 3)

    status, side = card()
    side.addWidget(label('Sincronização', 'SectionTitle'))
    w.overview_sync = label('', 'muted')
    side.addWidget(w.overview_sync)
    side.addWidget(divider())
    side.addWidget(label('Integrações', 'SectionTitle'))
    w.overview_lines = {}
    for key, name in (('companion', 'Companion'), ('ai', 'IA local'), ('gmail', 'Gmail'), ('obsidian', 'Obsidian')):
        line = StatusLine(name)
        line.name.setMinimumWidth(90)
        side.addWidget(line)
        w.overview_lines[key] = line
    alerts = QHBoxLayout()
    alerts.addWidget(label('Alertas de integração', 'muted'))
    alerts.addStretch(1)
    w.labels['alerts'].setObjectName('SectionTitle')
    alerts.addWidget(w.labels['alerts'])
    side.addLayout(alerts)
    side.addStretch(1)
    side.addWidget(button('Abrir integrações', kind='ghost', slot=lambda: w.navigate('integrations')), 0,
                   Qt.AlignmentFlag.AlignLeft)
    columns.addWidget(status, 2)
    col.addLayout(columns)
    w.overview.setObjectName('faint')
    col.addWidget(w.overview)
    col.addStretch(1)
    return area


def refresh_overview(w) -> None:
    from .deadlines import SITUATION_TEXT
    comp = w._companion if (w._companion is not None and w._companion.has_reading) else None
    w.labels['late'].setText(str(comp.overdue) if comp else '—')
    rows = []
    unverified = 0
    if comp:
        from .companion_view import urgency
        for r in sorted(comp.rows, key=urgency):
            if r.category == 'material' or not r.present:
                continue
            if not r.due_at:                                  # no deadline read: never shown as a deadline
                unverified += r.situation != 'nao_se_aplica'
                continue
            if r.situation in ('concluida', 'enviada', 'aguardando_avaliacao'):
                continue
            tone = 'late' if r.situation == 'atrasada' else 'soon' if r.soon else None
            place = f'{r.course_name} › {r.section_name}' if r.section_name else r.course_name
            due = f'{r.due_text} · {r.time_left}' if r.time_left else r.due_text
            rows.append((r.title, place, due, SITUATION_TEXT.get(r.situation, r.situation), tone))
    for item in sorted((i for i in w._items if i.due_iso and i.category != 'material'), key=lambda i: i.due_iso):
        rows.append((item.title, f'{item.course} · {item.source}', item.due_iso[:16].replace('T', ' '),
                     'enviado' if item.status == 'submitted' else 'prazo informado', None))
    if comp is None and not w._items:
        empty = ('Nenhuma leitura ainda. Use "Sincronizar disciplina" no Campus AI Companion (Chrome) e confirme '
                 '"Salvar no Campus AI"; os prazos aparecem aqui.')
    elif unverified:
        empty = (f'{unverified} atividade(s) sem prazo verificado. O Companion lê o prazo na página de cada atividade; '
                 'até lá, o prazo é "não verificado" — nunca "sem prazo".')
    else:
        empty = 'Nenhum prazo em aberto entre as atividades lidas.'
    w.overview_deadlines.set_rows(rows[:6], empty)
    if rows and unverified:
        w.overview_deadlines.layout_.addWidget(label(f'+ {unverified} atividade(s) com prazo não verificado.', 'Tiny'))

    if comp:
        when = f'Última leitura do Companion: {comp.received_local}' + (' (antiga)' if comp.stale else '')
        detail = f'Prazos verificados em {comp.last_verified_local}' if comp.last_verified_local else \
            'Prazos ainda não verificados nesta leitura'
        sync = f'{when}\n{detail}\nCobertura: {comp.coverage}'
    else:
        sync = 'Nenhuma leitura do Companion recebida.'
    w.overview_sync.setText(sync + '\n' + w.last_sync.text())
    _refresh_integrations(w, comp)


# --- activities -----------------------------------------------------------------------------------------------------
def _activities(w):
    body, col = page(None, scroll=False)
    w.activity_search = QLineEdit()
    w.activity_search.setPlaceholderText('Buscar por título ou disciplina')
    w.activity_search.setClearButtonEnabled(True)
    w.activity_search.setMinimumWidth(260)
    w.activity_search.textChanged.connect(lambda _=None: apply_filter(w))
    w.activity_filter = QComboBox()
    for text, _ in FILTERS:
        w.activity_filter.addItem(text)
    w.activity_filter.currentIndexChanged.connect(lambda _=None: apply_filter(w))
    w.activity_columns = QCheckBox('Mais colunas')
    w.activity_columns.setToolTip('Mostra também o tipo do módulo e quando o prazo foi verificado.')
    w.activity_columns.toggled.connect(lambda on: _detail_columns(w, on))
    header = PageHeader('Atividades', 'Do mais urgente ao menos urgente. "Não verificado" quer dizer que o prazo '
                        'ou a entrega ainda não foram lidos — nunca que não existem.',
                        actions=[w.activity_search, w.activity_filter])
    w.items_heading = header.title
    col.addWidget(header)
    table = w.table
    table.verticalHeader().hide()
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.verticalHeader().setDefaultSectionSize(42)
    head = table.horizontalHeader()
    head.setHighlightSections(False)
    head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    head.setMinimumSectionSize(90)
    # Visual order only (the logical columns, used everywhere else, do not change): what you read first comes first.
    for visual, logical in enumerate((3, 6, 4, 5, 1, 0, 2, 7)):
        head.moveSection(head.visualIndex(logical), visual)
    head.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
    for logical, width in ((6, 200), (4, 140), (5, 150), (1, 200), (0, 150), (2, 210), (7, 130)):
        table.setColumnWidth(logical, width)
    _detail_columns(w, False)
    col.addWidget(table, 1)
    legend = QHBoxLayout()
    legend.setSpacing(10)
    for text, tone in (('Atrasada', 'late'), ('Vence em até 72 h', 'soon'), ('Entregue ou concluída', 'done')):
        legend.addWidget(pill_label(text, tone))
    legend.addSpacing(8)
    legend.addWidget(label('Passe o mouse sobre uma linha para ver como cada dado foi obtido; duplo clique abre no '
                           'navegador.', 'Tiny'), 1)
    legend.addWidget(w.activity_columns)
    col.addLayout(legend)
    return body


def _detail_columns(w, on: bool) -> None:
    for logical in (2, 7):                                  # Tipo, Verificado em
        w.table.setColumnHidden(logical, not on)


def apply_filter(w) -> None:
    query = w.activity_search.text().strip().casefold()
    wanted = FILTERS[max(0, w.activity_filter.currentIndex())][1]
    table = w.table
    for row in range(table.rowCount()):
        cells = [table.item(row, c).text() if table.item(row, c) else '' for c in range(table.columnCount())]
        show = not query or any(query in c.casefold() for c in (cells[1], cells[3]))
        kind, due, situation = cells[2].casefold(), cells[4].casefold(), cells[6].casefold()
        if wanted == 'material':
            show = show and 'material' in kind
        elif wanted == 'atividade':
            show = show and 'material' not in kind
        elif wanted == 'atrasada':
            show = show and situation.startswith('atrasad')
        elif wanted == 'pendente':
            show = show and situation.startswith('pendente')
        elif wanted == 'nao_verificado':
            show = show and 'material' not in kind and ('não verificad' in due or 'não verificad' in situation)
        table.setRowHidden(row, not show)


# --- materials ------------------------------------------------------------------------------------------------------
def _materials(w):
    area, col = page()
    col.addWidget(PageHeader('Materiais', 'Arquivos publicados nas disciplinas lidas e os documentos que o Jarvis '
                             'preparou para você.'))
    box, inner = card(padding=0, spacing=0)
    w.materials_table = QTableWidget(0, 4)
    w.materials_table.setHorizontalHeaderLabels(['Título', 'Disciplina', 'Tipo', 'Visto em'])
    w.materials_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for i, width in ((1, 260), (2, 130), (3, 150)):
        w.materials_table.setColumnWidth(i, width)
    _plain_table(w.materials_table)
    w.materials_table.setMinimumHeight(220)
    w.materials_table.cellDoubleClicked.connect(lambda r, c: _open_https(w.materials_table, r))
    inner.addWidget(w.materials_table)
    col.addWidget(label('Materiais das disciplinas', 'SectionTitle'))
    col.addWidget(box)
    w.materials_empty = label('', 'muted')
    col.addWidget(w.materials_empty)

    col.addSpacing(8)
    docs_head = QHBoxLayout()
    docs_head.addWidget(label('Documentos preparados pelo Jarvis', 'SectionTitle'), 1)
    docs_head.addWidget(button('Abrir pasta', icon_name='folder', slot=lambda: _open_folder(w.jarvis_panel.output_dir)))
    docs_head.addWidget(button('Atualizar', icon_name='refresh', slot=lambda: refresh_documents(w)))
    col.addLayout(docs_head)
    w.documents = QListWidget()
    w.documents.setObjectName('Documents')
    w.documents.setMinimumHeight(180)
    w.documents.itemDoubleClicked.connect(
        lambda item: w.jarvis_panel._open_link(QUrl.fromLocalFile(item.data(Qt.ItemDataRole.UserRole))))
    col.addWidget(w.documents)
    col.addWidget(label('Peça ao Jarvis: "prepare essa atividade". Os arquivos ficam em Documentos\\Campus AI e só '
                        'abrem a partir desta pasta.', 'Tiny'))
    col.addStretch(1)
    refresh_documents(w)
    return area


def _plain_table(table):
    table.verticalHeader().hide()
    table.setShowGrid(False)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setDefaultSectionSize(40)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    table.setFrameShape(QFrame.Shape.NoFrame)


def _open_https(table, row):
    item = table.item(row, 0)
    url = item.data(Qt.ItemDataRole.UserRole) if item else ''
    if url and str(url).startswith('https://'):
        QDesktopServices.openUrl(QUrl(str(url)))


def _open_folder(path: Path):
    path = Path(path)
    if path.is_dir():
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def refresh_materials(w) -> None:
    comp = w._companion if (w._companion is not None and w._companion.has_reading) else None
    rows = []
    if comp:
        for r in comp.rows:
            if r.category == 'material':
                place = f'{r.course_name} › {r.section_name}' if r.section_name else r.course_name
                rows.append((r.title, place, r.kind_label, r.last_seen_local, r.url))
    for item in w._items:
        if item.category == 'material':
            rows.append((item.title, item.course, item.source, item.due_iso[:10] if item.due_iso else '—', item.url))
    table = w.materials_table
    table.setRowCount(0)
    for values in rows:
        row = table.rowCount()
        table.insertRow(row)
        for col, value in enumerate(values[:4]):
            cell = QTableWidgetItem(str(value))
            cell.setData(Qt.ItemDataRole.UserRole, values[4])
            if values[4]:
                cell.setToolTip('Duplo clique abre no navegador.')
            table.setItem(row, col, cell)
    w.materials_empty.setVisible(not rows)
    w.materials_empty.setText('Nenhum material lido ainda.' if not rows else '')


def refresh_documents(w) -> None:
    w.documents.clear()
    folder = Path(w.jarvis_panel.output_dir)
    files = []
    if folder.is_dir():
        files = sorted((p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in ('.docx', '.md')),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:40]
    for path in files:
        item = QListWidgetItem(theme.icon('document', theme.ACCENT, 18), f'{path.name}    ·    {path.parent.name}')
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        item.setToolTip(f'{path}\nDuplo clique abre o arquivo.')
        w.documents.addItem(item)
    if not files:
        placeholder = QListWidgetItem('Nenhum documento preparado ainda.')
        placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        w.documents.addItem(placeholder)


# --- history --------------------------------------------------------------------------------------------------------
def _history(w):
    area, col = page()
    col.addWidget(PageHeader('Histórico', 'O que o Jarvis executou e os alertas das análises. A conversa completa fica '
                             'na página Jarvis.', actions=[button('Atualizar', icon_name='refresh',
                                                                  slot=lambda: refresh_history(w))]))
    col.addWidget(label('Operações do Jarvis', 'SectionTitle'))
    box, inner = card(padding=0, spacing=0)
    w.operations_table = QTableWidget(0, 4)
    w.operations_table.setHorizontalHeaderLabels(['Quando', 'Ferramenta', 'Situação', 'Resumo'])
    w.operations_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
    for i, width in ((0, 210), (1, 190), (2, 130)):
        w.operations_table.setColumnWidth(i, width)
    _plain_table(w.operations_table)
    w.operations_table.setMinimumHeight(260)
    inner.addWidget(w.operations_table)
    col.addWidget(box)
    col.addWidget(label('Alertas recentes das análises', 'SectionTitle'))
    w.recent.setMinimumHeight(160)
    col.addWidget(w.recent)
    col.addStretch(1)
    refresh_history(w)
    return area


def refresh_history(w) -> None:
    from datetime import datetime
    from .jarvis.tools import local_text
    try:
        operations = w.jarvis_panel.store.operations(100)
    except Exception:                                   # a locked store must not break the page
        operations = []
    table = w.operations_table
    table.setRowCount(0)
    labels = {'ok': 'concluída', 'falhou': 'falhou', 'cancelado': 'interrompida', 'recusado': 'recusada',
              'executando': 'em execução'}
    for op in operations:
        row = table.rowCount()
        table.insertRow(row)
        try:
            when = local_text(datetime.fromisoformat(op['started_at']))
        except (TypeError, ValueError):
            when = str(op.get('started_at', ''))
        status = str(op.get('status', ''))
        values = (when, str(op.get('tool', '')), labels.get(status, status), str(op.get('summary') or ''))
        for col, value in enumerate(values):
            cell = QTableWidgetItem(value)
            cell.setToolTip(value)
            if col == 2 and status in ('falhou', 'recusado'):
                cell.setForeground(theme_color(theme.DANGER))
            table.setItem(row, col, cell)


def theme_color(hex_color: str):
    from PySide6.QtGui import QBrush, QColor
    return QBrush(QColor(hex_color))


# --- integrations ---------------------------------------------------------------------------------------------------
def _integration_card(title: str, description: str):
    frame, box = card(padding=20, spacing=10)
    head = QHBoxLayout()
    head.addWidget(label(title, 'SectionTitle'), 1)
    box.addLayout(head)
    box.addWidget(label(description, 'Tiny'))
    line = StatusLine('Estado')
    line.name.setObjectName('muted')
    line.name.setMinimumWidth(70)
    box.addWidget(line)
    return frame, box, line


def _integrations(w):
    area, col = page()
    col.addWidget(PageHeader('Integrações', 'Cada fonte é independente: uma que falhe não impede as outras.'))
    w.integration_lines = {}
    grid = QGridLayout()
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(16)

    # Companion: the existing box (title and status text kept) restyled as a card
    w.companion_box.setTitle('Campus AI Companion (Chrome)')
    comp_layout = w.companion_box.layout()
    comp_layout.setContentsMargins(0, 0, 0, 0)               # the group box padding is the card padding
    comp_layout.setSpacing(10)
    w.moodle_group.layout().setContentsMargins(0, 0, 0, 0)
    comp_layout.insertWidget(0, label('Lê o Moodle AEDB na sua aba do Chrome, só depois do seu clique, e grava aqui '
                                      'apenas quando você confirma "Salvar no Campus AI".', 'Tiny'))
    line = StatusLine('Estado')
    line.name.setObjectName('muted')
    line.name.setMinimumWidth(70)
    comp_layout.insertWidget(1, line)
    w.integration_lines['companion'] = line
    w.companion_status.setObjectName('muted')
    actions = QHBoxLayout()
    actions.addWidget(button('Ver diagnóstico', slot=lambda: w.show_advanced(w.companion_tab)))
    actions.addStretch(1)
    comp_layout.addLayout(actions)
    grid.addWidget(w.companion_box, 0, 0, 1, 2)

    ai, box, line = _integration_card('IA local (Ollama)', 'Interpreta frases que as regras não entendem. Roda só neste '
                                      'computador (127.0.0.1), sem nuvem; nunca recebe dados do Moodle.')
    w.integration_lines['ai'] = line
    row = QHBoxLayout()
    row.addWidget(button('Verificar agora', icon_name='refresh', slot=lambda: w.jarvis_panel.refresh_ai_status()))
    row.addWidget(button('Detalhes', slot=lambda: w.navigate('settings')))
    row.addStretch(1)
    box.addLayout(row)
    grid.addWidget(ai, 1, 0)

    gmail, box, line = _integration_card('Gmail institucional', 'Leitura de e-mails com permissão somente leitura '
                                         '(OAuth gmail.readonly), nas análises.')
    w.integration_lines['gmail'] = line
    row = QHBoxLayout()
    row.addWidget(button('Configurar', slot=w.open_settings))
    row.addStretch(1)
    box.addLayout(row)
    grid.addWidget(gmail, 1, 1)

    obsidian, box, line = _integration_card('Obsidian', 'As análises escrevem notas só na pasta "Campus AI" do seu '
                                            'vault; suas notas pessoais nunca são alteradas.')
    w.integration_lines['obsidian'] = line
    row = QHBoxLayout()
    w.obsidian_button.setText('Abrir pasta')
    w.obsidian_button.setIcon(theme.icon('folder', theme.MUTED, 18))
    row.addWidget(w.obsidian_button)
    row.addWidget(button('Escolher vault', slot=w.open_settings))
    row.addStretch(1)
    box.addLayout(row)
    grid.addWidget(obsidian, 2, 0)

    moodle, box, line = _integration_card('Moodle AEDB — leitor antigo', 'Leitura opcional por um navegador dedicado '
                                          '(Playwright), independente do Companion. Os controles ficam em '
                                          'Configurações › Avançado.')
    w.integration_lines['moodle'] = line
    row = QHBoxLayout()
    row.addWidget(button('Abrir controles', slot=lambda: w.show_advanced(0)))
    row.addStretch(1)
    box.addLayout(row)
    grid.addWidget(moodle, 2, 1)
    col.addLayout(grid)
    col.addStretch(1)
    return area


def _gmail_connected() -> bool:
    try:
        from .gmail import gmail_enabled
        return bool(gmail_enabled())
    except Exception:
        return False


def _refresh_integrations(w, comp) -> None:
    lines = w.integration_lines
    if comp is not None:
        state = ('ok', f'Leitura nº {comp.run_id} recebida em {comp.received_local}')
        if comp.stale:
            state = ('warn', f'Última leitura (nº {comp.run_id}) em {comp.received_local} — antiga')
        if comp.errors:
            state = ('warn', state[1] + f' · {comp.errors} erro(s) de sincronização')
    elif w._companion is not None and w._companion.errors:
        state = ('error', f'Sem leitura válida · {w._companion.errors} erro(s) ({w._companion.last_error_code})')
    else:
        state = ('muted', 'Aguardando a primeira leitura')
    lines['companion'].set(state[1], state[0])
    w.overview_lines['companion'].set(state[1], state[0])
    demo = w.settings.mode == 'demo'
    gmail = ('ok', 'Conectado (somente leitura)') if _gmail_connected() else ('muted', 'Não conectado')
    if demo:
        gmail = ('muted', gmail[1] + ' · modo demonstração usa dados fictícios')
    lines['gmail'].set(gmail[1], gmail[0])
    w.overview_lines['gmail'].set(gmail[1].split(' · ')[0], gmail[0])
    vault = w.settings.vault_path
    if vault and Path(vault).is_dir():
        obsidian = ('ok', f'Vault: {vault}')
    elif vault:
        obsidian = ('error', f'Pasta do vault não encontrada: {vault}')
    else:
        obsidian = ('muted', 'Nenhum vault selecionado')
    lines['obsidian'].set(obsidian[1], obsidian[0])
    w.overview_lines['obsidian'].set('Vault selecionado' if obsidian[0] == 'ok' else obsidian[1].split(':')[0],
                                     obsidian[0])
    reader = w.settings.mode == 'live' and w.settings.moodle_method == 'browser'
    lines['moodle'].set(('Ligado' if reader else 'Desligado') + ' · ' + w.last_sync.text().replace(
        'Leitor antigo — ', ''), 'ok' if reader and w._session_valid else 'muted')


# --- settings -------------------------------------------------------------------------------------------------------
def _settings(w):
    area, col = page()
    w.settings_button.setText('Preferências e contas')
    w.settings_button.setIcon(theme.icon('settings', theme.MUTED, 18))
    col.addWidget(PageHeader('Configurações', 'Preferências, IA local, manutenção e ferramentas avançadas.',
                             actions=[w.settings_button]))

    general, box = card()
    box.addWidget(label('Geral', 'SectionTitle'))
    w.mode_label.setObjectName('muted')
    box.addWidget(w.mode_label)
    box.addWidget(label('Modo, vault do Obsidian, Moodle, Gmail, início com o Windows e análises periódicas ficam em '
                        '"Preferências e contas". Atalho: Ctrl+J abre o Jarvis de qualquer página.', 'Tiny'))
    col.addWidget(general)

    ai, box = card()
    box.addWidget(label('IA local', 'SectionTitle'))
    w.ai_detail = label('', 'muted')
    box.addWidget(w.ai_detail)
    from .jarvis.llm import DEFAULT_MODEL, find_executable, ollama_home
    exe = find_executable()
    facts = [('Modelo', DEFAULT_MODEL), ('Endereço', '127.0.0.1:11434 (somente este computador)'),
             ('Instalação', str(exe) if exe else 'não encontrada (o Jarvis usa só as regras)'),
             ('Registro do servidor', str(ollama_home() / 'logs' / 'server.log'))]
    form = QGridLayout()
    form.setHorizontalSpacing(18)
    form.setVerticalSpacing(6)
    for index, (name, value) in enumerate(facts):
        form.addWidget(label(name, 'Tiny', wrap=False), index, 0, Qt.AlignmentFlag.AlignTop)
        text = label(value)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addWidget(text, index, 1)
    form.setColumnStretch(1, 1)
    box.addLayout(form)
    row = QHBoxLayout()
    row.addWidget(button('Verificar agora', icon_name='refresh', slot=lambda: w.jarvis_panel.refresh_ai_status()))
    row.addWidget(button('Abrir pasta de registros', icon_name='folder', slot=lambda: _open_folder(ollama_home() / 'logs')))
    row.addStretch(1)
    box.addLayout(row)
    col.addWidget(ai)

    tools, box = card()
    box.addWidget(label('Manutenção', 'SectionTitle'))
    row = QHBoxLayout()
    from .config import app_dir
    w.ask_button.setText('Consulta rápida (sem IA)')
    w.ask_button.setToolTip('A consulta local antiga sobre os itens da última análise.')
    row.addWidget(w.ask_button)
    row.addWidget(button('Abrir pasta de dados', icon_name='folder', slot=lambda: _open_folder(app_dir())))
    row.addWidget(button('Abrir documentos do Jarvis', icon_name='folder',
                         slot=lambda: _open_folder(w.jarvis_panel.output_dir)))
    row.addStretch(1)
    box.addLayout(row)
    box.addWidget(label('Os dados ficam só neste computador. O Jarvis nunca escreve no banco das leituras (live.db).',
                        'Tiny'))
    col.addWidget(tools)

    col.addWidget(label('Avançado', 'SectionTitle'))
    col.addWidget(label('Leitor antigo por navegador, diagnóstico do Companion e o teste piloto de uma disciplina.',
                        'Tiny'))
    w.tabs.setMinimumHeight(460)
    col.addWidget(w.tabs)
    col.addStretch(1)
    return area

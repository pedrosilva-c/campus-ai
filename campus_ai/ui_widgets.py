"""Small reusable widgets of the Campus AI shell (no business logic)."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import ui_theme as theme

SPACE = 8                 # spacing unit: 8 / 16 / 24 / 32


def label(text: str = '', name: str = '', *, wrap: bool = True, plain: bool = True) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    if plain:
        widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


def card(*, padding: int = 20, spacing: int = 12) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName('Card')
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(padding, padding, padding, padding)
    layout.setSpacing(spacing)
    return frame, layout


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName('Divider')
    return line


def button(text: str, *, kind: str = '', icon_name: str = '', icon_color: str = theme.MUTED, slot=None) -> QPushButton:
    widget = QPushButton(text)
    if kind:
        widget.setObjectName(kind)
    if icon_name:
        widget.setIcon(theme.icon(icon_name, '#FFFFFF' if kind == 'primary' else icon_color, 18))
        widget.setIconSize(QSize(18, 18))
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot is not None:
        widget.clicked.connect(slot)
    return widget


class PageHeader(QWidget):
    """Title + subtitle on the left, actions on the right."""

    def __init__(self, title: str, subtitle: str = '', actions=()):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(4)
        self.title = label(title, 'PageTitle', wrap=False)
        self.subtitle = label(subtitle, 'PageSubtitle')
        text.addWidget(self.title)
        if subtitle:
            text.addWidget(self.subtitle)
        row.addLayout(text, 1)
        for action in actions:
            row.addWidget(action, 0, Qt.AlignmentFlag.AlignTop)


class StatusLine(QWidget):
    """● Name ............ state text   [action]"""

    def __init__(self, name: str, icon_name: str = ''):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 6, 0, 6)
        row.setSpacing(10)
        if icon_name:
            glyph = QLabel()
            glyph.setPixmap(theme.icon(icon_name, theme.MUTED, 18).pixmap(18, 18))
            row.addWidget(glyph)
        self.name = label(name, wrap=False)
        self.name.setMinimumWidth(150)
        row.addWidget(self.name)
        self.dot = QLabel()
        row.addWidget(self.dot)
        self.state = label('', 'muted')
        self.state.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(self.state, 1)

    def set(self, text: str, tone: str = 'muted') -> None:
        color = {'ok': theme.SUCCESS, 'warn': theme.WARNING, 'error': theme.DANGER}.get(tone, theme.FAINT)
        self.dot.setPixmap(theme.dot(color, 5))
        self.state.setText(text)


class MetricTile(QFrame):
    """A compact number with its caption (never a made-up number: the text comes from the window's labels)."""

    def __init__(self, value_label: QLabel, caption: str):
        super().__init__()
        self.setObjectName('Card')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(2)
        value_label.setObjectName('Metric')
        layout.addWidget(value_label)
        layout.addWidget(label(caption, 'MetricCaption'))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


def page(max_width: int | None = 1120, *, scroll: bool = True, margins=(36, 28, 36, 28)) -> tuple[QWidget, QVBoxLayout]:
    """A page: optional scroll area, content column centred up to ``max_width``."""
    body = QWidget()
    body.setObjectName('Page')
    outer = QHBoxLayout(body)
    outer.setContentsMargins(*margins)
    column = QWidget()
    if max_width:
        column.setMaximumWidth(max_width)
    layout = QVBoxLayout(column)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(20)
    outer.addStretch(0)
    outer.addWidget(column, 1)
    outer.addStretch(0)
    if not scroll:
        return body, layout
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(body)
    return area, layout


class Sidebar(QWidget):
    navigated = Signal(str)

    def __init__(self, items, bottom_items=()):
        super().__init__()
        self.setObjectName('Sidebar')
        self.setFixedWidth(232)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 24, 16, 18)
        layout.setSpacing(4)
        brand = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(theme.icon('sparkle', theme.ACCENT, 26).pixmap(26, 26))
        brand.addWidget(mark)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(label('Campus AI', 'Brand', wrap=False))
        names.addWidget(label('Assistente pessoal', 'BrandSub', wrap=False))
        brand.addLayout(names, 1)
        layout.addLayout(brand)
        layout.addSpacing(22)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        self._icons = {}
        for key, text, icon_name in items:
            layout.addWidget(self._item(key, text, icon_name))
        layout.addStretch(1)
        for key, text, icon_name in bottom_items:
            layout.addWidget(self._item(key, text, icon_name))
        layout.addSpacing(10)
        layout.addWidget(divider())
        layout.addSpacing(8)
        self.ai = StatusLine('')
        self.ai.name.hide()
        self.ai.name.setMinimumWidth(0)
        self.ai.state.setObjectName('SidebarFoot')
        layout.addWidget(self.ai)
        self.foot = label('', 'SidebarFoot')
        layout.addWidget(self.foot)

    def _item(self, key, text, icon_name):
        widget = QPushButton(f'  {text}')
        widget.setObjectName('NavButton')
        widget.setCheckable(True)
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
        widget.setIcon(theme.icon(icon_name, theme.MUTED, 20))
        widget.setIconSize(QSize(20, 20))
        widget.setMinimumHeight(42)
        widget.clicked.connect(lambda _=False, k=key: self.navigated.emit(k))
        self.group.addButton(widget)
        self.buttons[key] = widget
        self._icons[key] = icon_name
        return widget

    def select(self, key: str) -> None:
        if key not in self.buttons:
            return
        self.buttons[key].setChecked(True)
        for name, widget in self.buttons.items():                # the active item gets a white icon
            widget.setIcon(theme.icon(self._icons[name], '#FFFFFF' if name == key else theme.MUTED, 20))

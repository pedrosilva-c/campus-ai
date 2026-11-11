"""Chat widgets of the Jarvis page: message bubbles, typing indicator, the composer input. Presentation only.

Text from the conversation is always escaped before it is shown (no HTML from anywhere is interpreted). File
results are shown as buttons; opening them is delegated to the panel (which only opens files of its delivery folder).
"""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import ui_theme as theme

BUBBLE_MAX = 720


def _rich(text: str) -> str:
    return html.escape(text).replace('\n', '<br>')


class Bubble(QFrame):
    def __init__(self, role: str, who: str, text: str, files=(), on_file=None):
        super().__init__()
        self.setObjectName({'user': 'BubbleUser', 'note': 'BubbleNote'}.get(role, 'BubbleJarvis'))
        self.setMaximumWidth(BUBBLE_MAX)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(6)
        if who:
            meta = QLabel(who)
            meta.setObjectName('BubbleMeta')
            meta.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(meta)
        body = QLabel(_rich(text))
        body.setObjectName('BubbleText')
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(body)
        self.body = body
        # natural width of the longest line (a word-wrapped label otherwise collapses to a narrow column)
        body.ensurePolished()                                  # the font comes from the style sheet
        metrics = body.fontMetrics()
        widest = max((metrics.horizontalAdvance(line) for line in text.split('\n')), default=0)
        if who:
            widest = max(widest, metrics.horizontalAdvance(who))
        self._natural = widest + 8
        self._files = bool(files)
        self.html = _rich(text)
        for path in files:
            p = Path(path)
            chip = QPushButton(f'  {p.name}')
            chip.setObjectName('fileChip')
            chip.setIcon(theme.icon('document', theme.ACCENT, 18))
            chip.setIconSize(QSize(18, 18))
            chip.setToolTip(f'Abrir {p}')
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            if on_file is not None:
                chip.clicked.connect(lambda _=False, u=QUrl.fromLocalFile(str(p)): on_file(u))
            layout.addWidget(chip, 0, Qt.AlignmentFlag.AlignLeft)
            self._natural = max(self._natural, chip.sizeHint().width())
            self.html += f'<br><a href="{QUrl.fromLocalFile(str(p)).toString()}">{html.escape(p.name)}</a>'

    def fit(self, available: int) -> None:
        """Width of the text: its natural width, at most ``available`` (the bubble's share of the column)."""
        width = max(40, min(self._natural, available - 32))
        self.body.setFixedWidth(width)


class TypingIndicator(QFrame):
    """A Jarvis bubble with three animated dots while a request runs."""

    def __init__(self):
        super().__init__()
        self.setObjectName('BubbleJarvis')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        self.text = QLabel('Jarvis está trabalhando')
        self.text.setObjectName('BubbleMeta')
        layout.addWidget(self.text)
        self._step = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def start(self, text: str = 'Jarvis está trabalhando'):
        self._base = text
        self._step = 0
        self._tick()
        self.timer.start(420)
        self.show()

    def stop(self):
        self.timer.stop()
        self.hide()

    def _tick(self):
        self._step = (self._step + 1) % 4
        self.text.setText(getattr(self, '_base', 'Jarvis está trabalhando') + '.' * self._step)


class ChatView(QScrollArea):
    """The conversation. ``toPlainText``/``toHtml`` expose what is shown (used by the app and its tests)."""

    def __init__(self, on_file=None):
        super().__init__()
        self.on_file = on_file
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName('Page')
        self.column = QVBoxLayout(holder)
        self.column.setContentsMargins(4, 8, 8, 8)
        self.column.setSpacing(14)
        self.column.addStretch(1)
        self.typing = TypingIndicator()
        self.typing.hide()
        self._row(self.typing, left=True)
        self.setWidget(holder)
        self._plain = []
        self._html = []
        self._bubbles = []
        self._stick = True                       # follow new messages while the view is at the bottom
        bar = self.verticalScrollBar()
        bar.rangeChanged.connect(self._range_changed)
        bar.valueChanged.connect(self._moved)

    def _range_changed(self, _low, high):
        if self._stick:
            self.verticalScrollBar().setValue(high)

    def _moved(self, value):
        self._stick = value >= self.verticalScrollBar().maximum() - 24

    def _available(self) -> int:
        return min(BUBBLE_MAX, int(self.viewport().width() * 0.82))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        available = self._available()
        for bubble in self._bubbles:
            bubble.fit(available)

    def _row(self, widget, *, left: bool):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if left:
            row.addWidget(widget, 0, Qt.AlignmentFlag.AlignLeft)
            row.addStretch(1)
        else:
            row.addStretch(1)
            row.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight)
        self.column.insertLayout(self.column.count() - 1 if widget is not self.typing else self.column.count(), row)

    def add(self, role: str, who: str, text: str, files=()):
        bubble = Bubble(role, who if role != 'user' else '', text, files, self.on_file)
        bubble.fit(self._available())
        self._bubbles.append(bubble)
        self._stick = True
        self._row(bubble, left=role != 'user')
        self._plain.append(f'{who}:\n{text}')
        self._html.append(f'<p><b>{html.escape(who)}:</b><br>{bubble.html}</p>')
        QTimer.singleShot(0, self, self.scroll_to_end)       # context object: cancelled if the view is deleted
        return bubble

    def scroll_to_end(self):
        self._stick = True
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    @property
    def empty(self) -> bool:
        return not self._plain

    def toPlainText(self) -> str:
        return '\n\n'.join(self._plain)

    def toHtml(self) -> str:
        return ''.join(self._html)


class ChatInput(QPlainTextEdit):
    """Enter sends, Shift+Enter breaks the line; grows from 1 to 6 lines. ``text``/``setText`` like a line edit."""

    submitted = Signal()

    def __init__(self, placeholder: str = ''):
        super().__init__()
        self.setObjectName('ChatInput')
        self.setPlaceholderText(placeholder)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.textChanged.connect(self._fit)
        self._fit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(event)

    def _fit(self):
        total = int(self.document().size().height())          # in lines for a QPlainTextEdit
        lines = max(1, min(6, total))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded if total > 6 else
                                        Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        line = self.fontMetrics().lineSpacing()
        self.setFixedHeight(line * lines + 18)

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:
        self.setPlainText(text)
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.setTextCursor(cursor)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._mark(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._mark(False)

    def _mark(self, focused: bool):
        frame = self.parentWidget()
        if frame is not None and frame.objectName() == 'Composer':
            frame.setProperty('focused', 'true' if focused else 'false')
            frame.style().unpolish(frame)
            frame.style().polish(frame)

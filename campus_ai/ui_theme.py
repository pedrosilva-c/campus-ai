"""Campus AI visual theme: one set of tokens, one Qt style sheet, system icons. No logic here.

Dark graphite / deep navy surfaces, a single blue accent for primary actions, Segoe UI type, Windows 11 icon font
(Segoe Fluent Icons, falling back to Segoe MDL2 Assets). Everything visual that is shared lives here so the pages
only compose widgets.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

# --- tokens ----------------------------------------------------------------------------------------------------------
BG = '#0B0F17'            # window
SIDEBAR = '#0D121B'
SURFACE = '#121925'       # cards, bubbles
SURFACE_2 = '#172030'     # controls
FIELD = '#0F1520'         # inputs, tables
BORDER = '#1E2738'
BORDER_STRONG = '#2A364D'
TEXT = '#E6EBF4'
MUTED = '#8C99AE'
FAINT = '#5E6A80'
ACCENT = '#4C8DFF'
ACCENT_HOVER = '#68A0FF'
ACCENT_PRESS = '#3A78E8'
ACCENT_SOFT = '#16264A'   # selected / user bubble
SUCCESS = '#46C08A'
WARNING = '#E8B04B'
DANGER = '#F0625B'

# Row tones for the activities table (background, text): dark-friendly, never pastel.
TONES = {
    'late': ('#2A1619', '#FF9690'),
    'soon': ('#2A2313', '#F2C96F'),
    'done': ('#11251B', '#86D9AC'),
}

FONT = "'Segoe UI Variable Text', 'Segoe UI', sans-serif"
ICON_FAMILIES = ['Segoe Fluent Icons', 'Segoe MDL2 Assets']

# Segoe Fluent Icons / MDL2 code points
ICONS = {
    'jarvis': '', 'overview': '', 'activities': '', 'materials': '', 'history': '',
    'integrations': '', 'settings': '', 'send': '', 'stop': '', 'document': '',
    'folder': '', 'refresh': '', 'search': '', 'sparkle': '', 'warning': '',
    'check': '', 'calendar': '', 'mail': '', 'plug': '', 'chip': '', 'info': '',
    'clock': '', 'open': '', 'chrome': '',
}

STYLE = f'''
* {{ font-family: {FONT}; font-size: 14px; }}
QMainWindow, QWidget#Root, QWidget#Content, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget#Page {{
    background: {BG}; }}
QWidget {{ color: {TEXT}; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER_STRONG}; padding: 6px 8px; border-radius: 6px; }}

/* sidebar */
QWidget#Sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
QLabel#Brand {{ font-size: 17px; font-weight: 600; color: {TEXT}; }}
QLabel#BrandSub {{ color: {FAINT}; font-size: 12px; }}
QPushButton#NavButton {{ text-align: left; padding: 10px 14px; border-radius: 10px; border: none; background: transparent;
    color: {MUTED}; font-size: 14px; }}
QPushButton#NavButton:hover {{ background: #141B28; color: {TEXT}; }}
QPushButton#NavButton:checked {{ background: {ACCENT_SOFT}; color: #FFFFFF; font-weight: 600; }}
QPushButton#NavButton:disabled {{ color: {FAINT}; }}
QLabel#SidebarFoot {{ color: {FAINT}; font-size: 12px; }}

/* type */
QLabel#PageTitle {{ font-size: 24px; font-weight: 600; color: {TEXT}; }}
QLabel#PageSubtitle, QLabel#muted {{ color: {MUTED}; }}
QLabel#faint {{ color: {FAINT}; font-size: 12px; }}
QLabel#SectionTitle {{ font-size: 15px; font-weight: 600; color: {TEXT}; }}
QLabel#Metric {{ font-size: 26px; font-weight: 600; color: {TEXT}; }}
QLabel#MetricCaption {{ color: {MUTED}; font-size: 13px; }}
QLabel#Notice {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 10px 14px; color: {MUTED}; }}

/* surfaces */
QFrame#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#Row {{ background: transparent; border: none; border-bottom: 1px solid {BORDER}; }}
QFrame#Divider {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}
QGroupBox {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; margin-top: 0px;
    padding: 50px 20px 18px 20px; }}
QGroupBox::title {{ subcontrol-origin: border; subcontrol-position: top left; left: 20px; top: 20px; padding: 0px;
    color: {TEXT}; font-weight: 600; font-size: 15px; }}

/* buttons */
QPushButton {{ background: {SURFACE_2}; border: 1px solid {BORDER_STRONG}; border-radius: 10px; padding: 8px 16px;
    color: {TEXT}; min-height: 20px; }}
QPushButton:hover {{ background: #1D2839; border-color: #36445E; }}
QPushButton:pressed {{ background: #151E2D; }}
QPushButton:disabled {{ color: {FAINT}; background: {SURFACE}; border-color: {BORDER}; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton#primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: #FFFFFF; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background: {ACCENT_PRESS}; }}
QPushButton#primary:disabled {{ background: #1F2D45; border-color: #1F2D45; color: #6F7E98; }}
QPushButton#ghost {{ background: transparent; border: none; color: #8DB5FF; padding: 6px 8px; }}
QPushButton#ghost:hover {{ color: #FFFFFF; }}
QPushButton#chip {{ background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: 17px; padding: 7px 14px;
    color: #C9D2E1; }}
QPushButton#chip:hover {{ border-color: {ACCENT}; color: #FFFFFF; }}
QPushButton#iconButton {{ border-radius: 12px; padding: 0px; min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; }}
QPushButton#fileChip {{ background: {FIELD}; border: 1px solid {BORDER_STRONG}; border-radius: 10px; padding: 6px 12px;
    text-align: left; color: {TEXT}; }}
QPushButton#fileChip:hover {{ border-color: {ACCENT}; }}

/* fields */
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{ background: {FIELD}; border: 1px solid {BORDER_STRONG};
    border-radius: 10px; padding: 8px 10px; selection-background-color: #2F5FB8; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{ background: {SURFACE_2}; border: 1px solid {BORDER_STRONG}; selection-background-color: {ACCENT_SOFT}; }}
QCheckBox {{ spacing: 8px; color: {MUTED}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {BORDER_STRONG};
    background: {FIELD}; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

/* tables */
QTableWidget {{ background: {FIELD}; alternate-background-color: #111826; border: 1px solid {BORDER}; border-radius: 12px;
    gridline-color: transparent; selection-background-color: #1B2C4A; selection-color: #FFFFFF; }}
QTableWidget::item {{ padding: 6px 8px; border-bottom: 1px solid #161E2C; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {SURFACE}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
    padding: 10px 8px; font-weight: 600; font-size: 13px; }}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}
QListWidget {{ background: {FIELD}; border: 1px solid {BORDER}; border-radius: 12px; padding: 6px; outline: none; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 8px; color: {TEXT}; }}
QListWidget::item:hover {{ background: #141D2C; }}
QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: #FFFFFF; }}

/* tabs (advanced area) */
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 12px; top: -1px; background: {SURFACE}; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 9px 16px; border: none;
    border-bottom: 2px solid transparent; margin-right: 4px; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: #FFFFFF; border-bottom: 2px solid {ACCENT}; }}

/* scrollbars */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: #263147; border-radius: 4px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: #33415C; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 4px; }}
QScrollBar::handle:horizontal {{ background: #263147; border-radius: 4px; min-width: 36px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* chat */
QFrame#BubbleUser {{ background: {ACCENT_SOFT}; border: 1px solid #243C6B; border-radius: 16px; }}
QFrame#BubbleJarvis {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 16px; }}
QFrame#BubbleNote {{ background: #1C1A12; border: 1px solid #3A3320; border-radius: 16px; }}
QLabel#BubbleMeta {{ color: {FAINT}; font-size: 12px; }}
QLabel#BubbleText {{ color: {TEXT}; font-size: 14px; }}
QFrame#Composer {{ background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: 18px; }}
QFrame#Composer[focused="true"] {{ border-color: {ACCENT}; }}
QPlainTextEdit#ChatInput {{ background: transparent; border: none; padding: 6px 4px; font-size: 15px; }}
QFrame#StatusChip {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
QLabel#Greeting {{ font-size: 28px; font-weight: 600; color: {TEXT}; }}
QPushButton#suggestion {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; padding: 12px 16px;
    text-align: left; color: #C9D2E1; }}
QPushButton#suggestion:hover {{ border-color: {ACCENT}; background: #141D2C; color: #FFFFFF; }}
QPushButton#sendButton {{ background: {ACCENT}; border: none; border-radius: 12px; padding: 0px;
    min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; }}
QPushButton#sendButton:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#sendButton:pressed {{ background: {ACCENT_PRESS}; }}
QPushButton#sendButton:disabled {{ background: #1F2D45; }}

/* lists of the overview / activities */
QLabel#Pill {{ border-radius: 9px; padding: 2px 9px; font-size: 12px; font-weight: 600; }}
QLabel#Tiny {{ color: {FAINT}; font-size: 12px; }}
'''


def apply_theme(app) -> None:
    app.setStyleSheet(STYLE)
    font = QFont('Segoe UI', 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)


def icon(name: str, color: str = MUTED, size: int = 20) -> QIcon:
    """A crisp icon from the Windows icon font (no image files)."""
    glyph = ICONS.get(name, ICONS['info'])
    icon_ = QIcon()
    for scale in (1, 2):
        pixmap = QPixmap(size * scale, size * scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = QFont()
        font.setFamilies(ICON_FAMILIES)
        font.setPixelSize(int(size * scale * 0.8))
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(QRectF(0, 0, size * scale, size * scale), Qt.AlignmentFlag.AlignCenter, glyph)
        painter.end()
        pixmap.setDevicePixelRatio(scale)
        icon_.addPixmap(pixmap)
    return icon_


def dot(color: str, size: int = 10) -> QPixmap:
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(0, 0, size * 2, size * 2))
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return pixmap

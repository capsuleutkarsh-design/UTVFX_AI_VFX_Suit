"""Contour VFX design system: colours, fonts and the application stylesheet.

Every colour in the UI comes from here. Widgets should not set their own
stylesheets for colours or fonts; give them an objectName or a dynamic property
("role") and style that here instead.

Neutral mid-greys in the manner of Nuke and Flame: the eye judges colour against
its surroundings, so the chrome stays grey and quiet, and the one accent colour
marks selection and the active state only.
"""
import os

from PySide6.QtGui import QColor, QFont, QPalette

_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets").replace("\\", "/")

# ---- Surfaces ---------------------------------------------------------------
BG_WINDOW = "#1e1e1e"     # outermost background, graph backdrop
BG_VIEWER = "#161616"     # around the image in the viewer
BG_PANEL = "#262626"      # side panels
BG_HEADER = "#2d2d2d"     # top bar, toolbars, panel headers
BG_INPUT = "#1b1b1b"      # text fields, lists, consoles
BG_BUTTON = "#353535"
BG_HOVER = "#3f3f3f"
BG_PRESSED = "#4a4a4a"
BORDER = "#141414"        # separators between panels
BORDER_SOFT = "#3a3a3a"   # outlines of controls

# ---- Text -------------------------------------------------------------------
TEXT = "#d6d6d6"
TEXT_DIM = "#9d9d9d"
TEXT_FAINT = "#6d6d6d"
TEXT_ON_ACCENT = "#1b1b1b"

# ---- Accent and states ------------------------------------------------------
ACCENT = "#e8833a"
ACCENT_HOVER = "#f09a57"
ACCENT_MUTED = "#5a3b24"  # selection backgrounds
ERROR = "#d0493d"
SUCCESS = "#6fa35c"
WARNING = "#d9a441"

# ---- Graph ------------------------------------------------------------------
GRAPH_BG = "#202020"
GRAPH_GRID = "#282828"
NODE_BODY = "#2e2e2e"
NODE_BORDER = "#161616"
WIRE = "#8a8a8a"

# ---- Viewer -----------------------------------------------------------------
CHECKER_DARK = "#8c8c8c"   # mid greys, as in Nuke, to judge mattes against
CHECKER_LIGHT = "#b4b4b4"

# Node header colour by category (muted, so a busy graph stays readable).
NODE_CATEGORY_COLOURS = {
    "media": "#5b7688",
    "matte": "#6b8a58",
    "tracking": "#7b6ba0",
    "keying": "#4c8a7c",
    "depth": "#8a6d52",
    "colour": "#8c7b48",
    "output": "#9a5a52",
    "utility": "#6a6a6a",
}

# Which category each node type belongs to.
NODE_CATEGORY = {
    "media_plate": "media",
    "super_matte": "matte",
    "roto_to_shape": "matte",
    "ai_roto": "matte",
    "sfm_tracker": "tracking",
    "corridor_keyer": "keying",
    "ai_depth_estimator": "depth",
    "grade": "colour",
    "ocio_colorspace": "colour",
    "composite_output": "output",
    "dot_node": "utility",
}


def node_colour(plugin_type):
    return NODE_CATEGORY_COLOURS[NODE_CATEGORY.get(plugin_type, "utility")]


# ---- Type -------------------------------------------------------------------
FONT_FAMILY = "Segoe UI"
FONT_MONO = "Cascadia Mono"
FONT_SIZE = 9  # points
SPACING = 6    # base layout spacing in px


def ui_font(size=FONT_SIZE, weight=QFont.Weight.Normal):
    font = QFont(FONT_FAMILY, size)
    font.setWeight(weight)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def mono_font(size=FONT_SIZE):
    font = QFont(FONT_MONO, size)
    font.setFamilies([FONT_MONO, "Consolas"])
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


def qcolor(hex_value, alpha=255):
    c = QColor(hex_value)
    c.setAlpha(alpha)
    return c


# ---- Stylesheet -------------------------------------------------------------
STYLESHEET = f"""
* {{
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}pt;
    color: {TEXT};
    outline: none;
}}
QMainWindow, QDialog {{ background: {BG_WINDOW}; }}
QWidget#Panel, QWidget#PanelBody {{ background: {BG_PANEL}; }}
QWidget#TopBar, QWidget#Toolbar, QWidget#PanelHeader {{
    background: {BG_HEADER};
    border-bottom: 1px solid {BORDER};
}}
QWidget#StatusBar {{ background: {BG_HEADER}; border-top: 1px solid {BORDER}; }}
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 10pt; font-weight: 600; }}
QLabel[role="section"] {{ color: {TEXT_DIM}; font-weight: 600; padding-top: 4px; }}
QLabel[role="dim"] {{ color: {TEXT_DIM}; }}
QLabel[role="faint"] {{ color: {TEXT_FAINT}; }}
QLabel[role="mono"] {{ font-family: "{FONT_MONO}", "Consolas", monospace; color: {TEXT_DIM}; }}
QFrame[role="separator"] {{ background: {BORDER_SOFT}; max-height: 1px; min-height: 1px; border: none; }}
QLabel[role="error"] {{ color: {ERROR}; }}
QLabel[role="ok"] {{ color: {SUCCESS}; }}

QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}
QSplitter::handle:hover {{ background: {ACCENT_MUTED}; }}

QPushButton, QToolButton {{
    background: {BG_BUTTON};
    border: 1px solid {BORDER_SOFT};
    border-radius: 3px;
    padding: 4px 10px;
    min-height: 16px;
}}
QPushButton:hover, QToolButton:hover {{ background: {BG_HOVER}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {BG_PRESSED}; }}
QPushButton:checked, QToolButton:checked {{ background: {ACCENT_MUTED}; border-color: {ACCENT}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {TEXT_FAINT}; background: {BG_PANEL}; border-color: {BG_BUTTON}; }}
QPushButton[role="primary"] {{
    background: {ACCENT}; color: {TEXT_ON_ACCENT}; border-color: {ACCENT}; font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[role="primary"]:disabled {{ background: {ACCENT_MUTED}; border-color: {ACCENT_MUTED}; color: {TEXT_DIM}; }}
QPushButton[role="danger"]:hover {{ background: {ERROR}; border-color: {ERROR}; color: {TEXT_ON_ACCENT}; }}
QPushButton[role="flat"], QToolButton[role="flat"] {{ background: transparent; border-color: transparent; }}
QPushButton[role="flat"]:hover, QToolButton[role="flat"]:hover {{ background: {BG_HOVER}; }}
QToolButton[role="flat"]:checked {{ background: {ACCENT_MUTED}; border-color: {ACCENT_MUTED}; }}
QToolButton[role="icon"], QPushButton[role="icon"] {{
    background: transparent; border-color: transparent; padding: 3px; min-width: 18px;
}}
QToolButton[role="icon"]:hover, QPushButton[role="icon"]:hover {{ background: {BG_HOVER}; }}
QToolButton[role="icon"]:checked {{ background: {ACCENT_MUTED}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit, QComboBox {{
    background: {BG_INPUT};
    border: 1px solid {BORDER_SOFT};
    border-radius: 3px;
    padding: 3px 6px;
    selection-background-color: {ACCENT_MUTED};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QPlainTextEdit[role="console"], QTextEdit[role="console"] {{
    font-family: "{FONT_MONO}", "Consolas", monospace; color: {TEXT_DIM}; border-color: {BORDER};
}}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{ image: url("{_ASSETS}/combo-arrow.svg"); width: 10px; height: 6px; }}
QLineEdit[role="mono"] {{ font-family: "{FONT_MONO}", "Consolas", monospace; }}
QLineEdit[role="number"] {{
    font-family: "{FONT_MONO}", "Consolas", monospace;
    background: {BG_INPUT}; border: 1px solid transparent; border-radius: 3px;
    padding: 1px 4px; color: {TEXT};
}}
QLineEdit[role="number"]:hover {{ border-color: {BORDER_SOFT}; }}
QLineEdit[role="number"]:focus {{ border-color: {ACCENT}; }}
QTabBar[role="compact"]::tab {{ padding: 5px 8px; }}
QComboBox QAbstractItemView {{
    background: {BG_HEADER}; border: 1px solid {BORDER}; selection-background-color: {ACCENT_MUTED}; padding: 2px;
}}

QCheckBox, QRadioButton {{ spacing: 6px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 13px; height: 13px; background: {BG_INPUT}; border: 1px solid {BORDER_SOFT};
}}
QCheckBox::indicator {{ border-radius: 2px; }}
QRadioButton::indicator {{ border-radius: 7px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {TEXT_DIM}; }}

QSlider::groove:horizontal {{ height: 3px; background: {BG_INPUT}; border-radius: 1px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 1px; }}
QSlider::handle:horizontal {{
    width: 10px; height: 10px; margin: -4px 0; border-radius: 5px; background: {TEXT};
}}
QSlider::handle:horizontal:hover {{ background: #ffffff; }}

QTabWidget::pane {{ border: none; border-top: 1px solid {BORDER}; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {TEXT_DIM}; padding: 5px 12px; border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}

QGroupBox {{
    border: 1px solid {BORDER_SOFT}; border-radius: 3px; margin-top: 14px; padding: 8px 6px 6px 6px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {TEXT_DIM}; font-weight: 600; }}

QListWidget, QTreeWidget, QTableWidget, QListView, QTreeView {{
    background: {BG_INPUT}; border: 1px solid {BORDER}; alternate-background-color: {BG_PANEL};
}}
QListWidget::item, QTreeWidget::item {{ padding: 3px 4px; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {BG_HOVER}; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {ACCENT_MUTED}; color: {TEXT}; }}
QHeaderView::section {{ background: {BG_HEADER}; border: none; border-right: 1px solid {BORDER}; padding: 4px; color: {TEXT_DIM}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {BG_HOVER}; border-radius: 3px; min-height: 24px; min-width: 24px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {BG_PRESSED}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{ background: {BG_HEADER}; border: 1px solid {BORDER}; padding: 4px 0; }}
QMenu::item {{ padding: 4px 22px 4px 12px; }}
QMenu::item:selected {{ background: {ACCENT_MUTED}; }}
QMenu::separator {{ height: 1px; background: {BORDER_SOFT}; margin: 4px 8px; }}
QToolTip {{ background: {BG_HEADER}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 6px; }}
QProgressBar {{ background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 2px; text-align: center; height: 12px; }}
QProgressBar::chunk {{ background: {ACCENT}; }}
QMessageBox {{ background: {BG_PANEL}; }}
"""


def apply(app):
    """Apply the Contour VFX look to the whole application."""
    app.setStyle("Fusion")
    app.setFont(ui_font())
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: BG_PANEL,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: BG_INPUT,
        QPalette.ColorRole.AlternateBase: BG_PANEL,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: BG_BUTTON,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: ACCENT_MUTED,
        QPalette.ColorRole.HighlightedText: TEXT,
        QPalette.ColorRole.ToolTipBase: BG_HEADER,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: TEXT_FAINT,
        QPalette.ColorRole.Link: ACCENT,
    }
    for role, value in roles.items():
        palette.setColor(role, QColor(value))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(TEXT_FAINT))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(TEXT_FAINT))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)


def set_role(widget, role):
    """Tag a widget with a style role defined in STYLESHEET and refresh it."""
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return widget

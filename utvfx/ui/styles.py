"""
Centralized design tokens and stylesheets for UTVFX AI & VFX TOOL.
"""

# Theme Colors
BG_MAIN = "#050505"
BG_PANEL = "#121212"
BG_ELEMENT = "#18181b"
BG_HOVER = "#27272a"
BG_ACTIVE = "#3f3f46"

TEXT_PRIMARY = "#fafafa"
TEXT_SECONDARY = "#a1a1aa"
TEXT_MUTED = "#71717a"

ACCENT_BLUE = "#3b82f6"
ACCENT_BLUE_HOVER = "#2563eb"
ACCENT_ORANGE = "#f59e0b"
ACCENT_ORANGE_HOVER = "#d97706"
ACCENT_GREEN = "#10b981"

# Fonts
FONT_MAIN = "'Inter'"
FONT_MONO = "'JetBrains Mono'"
FONT_HEADER = "'Space Grotesk'"

# Stylesheets
MAIN_WINDOW_STYLE = f"""
QMainWindow {{
    background-color: {BG_MAIN};
}}
QSplitter::handle {{
    background-color: {BG_HOVER};
}}
QSplitter::handle:horizontal {{
    width: 2px;
}}
QSplitter::handle:vertical {{
    height: 2px;
}}
QMessageBox {{
    background-color: {BG_ELEMENT};
}}
QMessageBox QLabel {{
    color: {TEXT_PRIMARY};
    font-family: {FONT_MAIN};
}}
QMessageBox QPushButton {{
    background-color: {ACCENT_BLUE};
    color: white;
    border: none;
    border-radius: 4px;
    padding: 6px 16px;
    font-weight: bold;
}}
QMessageBox QPushButton:hover {{
    background-color: {ACCENT_BLUE_HOVER};
}}
"""

def get_button_style(bg=BG_ELEMENT, text=TEXT_SECONDARY, border=BG_ACTIVE, hover_bg=BG_HOVER, hover_text=TEXT_PRIMARY):
    return f"""
    QPushButton {{
        background-color: {bg};
        color: {text};
        border: 1px solid {border};
        padding: 6px 12px;
        border-radius: 4px;
        font-family: {FONT_MAIN};
        font-weight: bold;
    }}
    QPushButton:hover {{ background-color: {hover_bg}; color: {hover_text}; }}
    QPushButton:disabled {{ color: {BG_ACTIVE}; border-color: {BG_HOVER}; }}
    """

BTN_DEFAULT = get_button_style()
BTN_PRIMARY = get_button_style(bg=ACCENT_BLUE, text="#ffffff", border=ACCENT_BLUE_HOVER, hover_bg=ACCENT_BLUE_HOVER, hover_text="#ffffff")
BTN_WARNING = get_button_style(bg=ACCENT_ORANGE, text="#ffffff", border=ACCENT_ORANGE_HOVER, hover_bg=ACCENT_ORANGE_HOVER, hover_text="#ffffff")
BTN_DARK = get_button_style(bg=BG_HOVER, text=TEXT_PRIMARY, border=BG_ACTIVE, hover_bg=BG_ACTIVE, hover_text=TEXT_PRIMARY)

def get_label_style(font=FONT_MAIN, size=11, color=TEXT_SECONDARY, bold=False):
    weight = "font-weight: bold;" if bold else ""
    return f"font-family: {font}; font-size: {size}px; color: {color}; {weight}"

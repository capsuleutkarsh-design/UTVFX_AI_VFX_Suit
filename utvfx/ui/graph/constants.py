from PySide6.QtGui import QColor

# --- Theming Constants ---
BG_COLOR = QColor("#09090b")
GRID_COLOR = QColor("#222225")
NODE_BG = QColor(18, 19, 24, 235)  # Translucent dark charcoal base
NODE_BORDER = QColor(63, 63, 70, 120)  # Zinc-700 with high transparency
NODE_BORDER_HOVER = QColor(161, 161, 170, 180)  # Zinc-400 highlight on hover
NODE_SELECTED = QColor("#0ea5e9")  # Sky blue (fallback selection outline)
PORT_COLOR = QColor("#71717a")  # Zinc-500 for idle unconnected ports
PORT_HOVER = QColor("#fafafa")  # Off-white highlight
CONN_COLOR = QColor("#52525b")  # Zinc-600
TEXT_COLOR = QColor("#fafafa")  # Zinc-50

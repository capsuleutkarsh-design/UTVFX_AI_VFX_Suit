"""Graph colours, all taken from the design system in utvfx.ui.theme."""
from utvfx.ui import theme

BG_COLOR = theme.qcolor(theme.GRAPH_BG)
GRID_COLOR = theme.qcolor(theme.GRAPH_GRID)
NODE_BG = theme.qcolor(theme.NODE_BODY)
NODE_BORDER = theme.qcolor(theme.NODE_BORDER)
NODE_BORDER_HOVER = theme.qcolor(theme.TEXT_FAINT)
NODE_SELECTED = theme.qcolor(theme.ACCENT)
PORT_COLOR = theme.qcolor(theme.TEXT_DIM)
PORT_HOVER = theme.qcolor(theme.ACCENT)
CONN_COLOR = theme.qcolor(theme.WIRE)
TEXT_COLOR = theme.qcolor(theme.TEXT)

# Node geometry
NODE_WIDTH = 190
NODE_HEADER = 20
NODE_RADIUS = 3
PORT_ROW = 18
PORT_TOP = NODE_HEADER + 15   # centre of the first port row
GRID_SIZE = 30                # background grid, also the shift-drag snap step

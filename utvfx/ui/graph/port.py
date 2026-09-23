from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsTextItem
from PySide6.QtGui import QPen, QBrush, QPainterPath, QPainter
from PySide6.QtCore import Qt, QRectF

from utvfx.ui import theme

PORT_HOVER = theme.qcolor(theme.ACCENT)
NODE_BORDER = theme.qcolor(theme.TEXT_DIM)
_LABEL = theme.qcolor(theme.TEXT_DIM)
_LABEL_HOVER = theme.qcolor(theme.TEXT)


class PortItem(QGraphicsPathItem):
    """An input or output port on a node: a small circle with a label beside it."""
    def __init__(self, name, is_output=False, parent=None):
        super().__init__(parent)
        self.name = name
        self.is_output = is_output
        self.connections = []
        self.node = parent
        self.is_hovered = False

        self.radius = 5.5  # Base reference radius for collision

        # Bounding path is used for hover detection and mouse interaction
        path = QPainterPath()
        path.addEllipse(QRectF(-self.radius - 2, -self.radius - 2, self.radius*2 + 4, self.radius*2 + 4))
        self.setPath(path)

        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CrossCursor)

        self.label = QGraphicsTextItem(self.name, self)
        self.label.setFont(theme.ui_font(8))
        self.label.setDefaultTextColor(_LABEL)
        self.label.document().setDocumentMargin(0)

        rect = self.label.boundingRect()
        y_offset = -rect.height() / 2
        if self.is_output:
            self.label.setPos(-rect.width() - 9, y_offset)
        else:
            self.label.setPos(9, y_offset)

    def hoverEnterEvent(self, event):
        self.is_hovered = True
        self.label.setDefaultTextColor(_LABEL_HOVER)
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.is_hovered = False
        self.label.setDefaultTextColor(_LABEL)
        self.update()
        super().hoverLeaveEvent(event)

    def paint(self, painter, option, widget=None):
        if getattr(self.node, "plugin_type", None) == "dot_node":
            return  # the Dot itself is the handle; its ports stay invisible
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        active = self.is_hovered or len(self.connections) > 0
        r = 5.0 if self.is_hovered else 4.5
        if active:
            painter.setPen(QPen(PORT_HOVER, 1.2))
            fill = theme.qcolor(theme.ACCENT) if self.is_hovered else theme.qcolor(theme.BG_PANEL)
        else:
            painter.setPen(QPen(NODE_BORDER, 1.0))
            fill = theme.qcolor(theme.BG_PANEL)
        painter.setBrush(QBrush(fill))
        painter.drawEllipse(QRectF(-r, -r, r * 2, r * 2))

        if active and not self.is_hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(PORT_HOVER))
            painter.drawEllipse(QRectF(-1.8, -1.8, 3.6, 3.6))

        painter.restore()

    def add_connection(self, connection):
        self.connections.append(connection)
        self.update()

    def remove_connection(self, connection):
        if connection in self.connections:
            self.connections.remove(connection)
            self.update()

    def update_connections(self):
        for conn in self.connections:
            conn.update_path()

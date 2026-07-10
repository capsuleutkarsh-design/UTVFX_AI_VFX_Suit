from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsTextItem
from PySide6.QtGui import QPen, QBrush, QColor, QPainterPath, QFont, QPainter
from PySide6.QtCore import Qt, QRectF

PORT_HOVER = QColor("#fafafa")  # Off-white highlight
NODE_BORDER = QColor(63, 63, 70, 120)  # Zinc-700 with high transparency

class PortItem(QGraphicsPathItem):
    """An input or output port on a node styled as a high-tech socket."""
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
        
        # Add the port label text
        self.label = QGraphicsTextItem(self.name, self)
        font = QFont("Inter", 8.5)
        self.label.setFont(font)
        self.label.setDefaultTextColor(QColor("#71717a"))  # Desaturated idle state
        
        # Position the label with perfect vertical centering and margin
        rect = self.label.boundingRect()
        text_height = rect.height()
        text_width = rect.width()
        y_offset = -text_height / 2 + 1.5
        
        if self.is_output:
            self.label.setPos(-text_width - 10, y_offset)
        else:
            self.label.setPos(10, y_offset)
        
    def hoverEnterEvent(self, event):
        self.is_hovered = True
        self.label.setDefaultTextColor(PORT_HOVER)
        self.update()
        super().hoverEnterEvent(event)
        
    def hoverLeaveEvent(self, event):
        self.is_hovered = False
        self.label.setDefaultTextColor(QColor("#71717a"))
        self.update()
        super().hoverLeaveEvent(event)
        
    def paint(self, painter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        
        is_connected = len(self.connections) > 0
        node_accent = self.node.accent_color if self.node else PORT_HOVER
        
        # Dynamic radius for high-tech responsive growth
        r = 6.5 if self.is_hovered else 4.8
        
        # 1. Draw outer ring
        if self.is_hovered or is_connected:
            ring_color = node_accent
            ring_width = 1.8 if self.is_hovered else 1.2
        else:
            ring_color = NODE_BORDER
            ring_width = 1.0
            
        painter.setPen(QPen(ring_color, ring_width))
        
        # 2. Draw fill
        if self.is_hovered:
            fill_color = QColor(node_accent.red(), node_accent.green(), node_accent.blue(), 60)
        elif is_connected:
            fill_color = QColor(node_accent.red(), node_accent.green(), node_accent.blue(), 30)
        else:
            fill_color = QColor(15, 15, 18, 255)  # Hollow dark inner core
            
        painter.setBrush(QBrush(fill_color))
        painter.drawEllipse(QRectF(-r, -r, r*2, r*2))
        
        # 3. Draw center core dot
        if is_connected or self.is_hovered:
            painter.setPen(Qt.NoPen)
            core_color = node_accent.lighter(120) if self.is_hovered else node_accent
            painter.setBrush(QBrush(core_color))
            dot_r = 2.2 if self.is_hovered else 1.8
            painter.drawEllipse(QRectF(-dot_r, -dot_r, dot_r*2, dot_r*2))
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#71717a")))
            painter.drawEllipse(QRectF(-1.2, -1.2, 2.4, 2.4))
            
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

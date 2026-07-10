from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsItem
from PySide6.QtGui import QPen, QBrush, QColor, QPainterPath, QLinearGradient, QPainter
from PySide6.QtCore import Qt, QPointF

class ConnectionItem(QGraphicsPathItem):
    """A sleek cubic bezier connection between two ports with dynamic color gradients."""
    def __init__(self, port1, port2=None):
        super().__init__()
        self.port1 = port1
        self.port2 = port2
        
        self.setZValue(-1)
        self.setAcceptHoverEvents(True)
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        
        self.update_path()
        
    def update_path(self, target_pos=None):
        pos1 = self.port1.scenePos()
        
        if self.port2:
            pos2 = self.port2.scenePos()
            color1 = self.port1.node.accent_color
            color2 = self.port2.node.accent_color
        elif target_pos:
            pos2 = target_pos
            color1 = self.port1.node.accent_color
            # Fade to a semi-transparent version of the start color during drag
            color2 = QColor(color1.red(), color1.green(), color1.blue(), 100)
        else:
            pos2 = pos1
            color1 = self.port1.node.accent_color
            color2 = color1
            
        path = QPainterPath()
        path.moveTo(pos1)
        
        # Calculate control points for cubic bezier
        dx = abs(pos2.x() - pos1.x()) * 0.5
        dx = max(dx, 40.0)
        
        cp1_x = pos1.x() + dx if self.port1.is_output else pos1.x() - dx
        
        if self.port2:
            cp2_x = pos2.x() + dx if self.port2.is_output else pos2.x() - dx
        else:
            cp2_x = pos2.x() - dx if self.port1.is_output else pos2.x() + dx
        
        if not self.port2 and self.port1.is_output:
            cp2_x = pos2.x() - dx
        elif not self.port2 and not self.port1.is_output:
            cp2_x = pos2.x() + dx
            
        path.cubicTo(
            QPointF(cp1_x, pos1.y()),
            QPointF(cp2_x, pos2.y()),
            pos2
        )
        self.setPath(path)
        
        # Gradient along the connection curve
        gradient = QLinearGradient(pos1, pos2)
        
        is_highlighted = self.isUnderMouse() or self.isSelected()
        width = 4.0 if is_highlighted else 2.2
        
        if is_highlighted:
            gradient.setColorAt(0, color1.lighter(115))
            gradient.setColorAt(1, color2.lighter(115))
        else:
            gradient.setColorAt(0, color1)
            gradient.setColorAt(1, color2)
            
        pen = QPen(QBrush(gradient), width)
        pen.setCapStyle(Qt.RoundCap)
        self.setPen(pen)

    def hoverEnterEvent(self, event):
        self.update_path()
        super().hoverEnterEvent(event)
        
    def hoverLeaveEvent(self, event):
        self.update_path()
        super().hoverLeaveEvent(event)

    def paint(self, painter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(Qt.NoBrush)  # Crucial: prevent open Bezier paths from being filled!
        
        path = self.path()
        pen = self.pen()
        brush = pen.brush()
        width = pen.widthF()
        
        # 1. Glow Layer (Thick, semi-transparent)
        painter.save()
        glow_pen = QPen(brush, width * 2.8)
        glow_pen.setCapStyle(Qt.RoundCap)
        painter.setOpacity(0.22)  # Soft neon glow
        painter.setPen(glow_pen)
        painter.drawPath(path)
        painter.restore()
        
        # 2. Core Layer (Thin, solid)
        core_pen = QPen(brush, width)
        core_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(core_pen)
        painter.drawPath(path)
        
        painter.restore()

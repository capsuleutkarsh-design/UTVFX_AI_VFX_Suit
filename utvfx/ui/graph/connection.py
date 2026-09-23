from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsItem
from PySide6.QtGui import QPen, QPainterPath, QPainter
from PySide6.QtCore import Qt, QPointF

from utvfx.ui import theme


class ConnectionItem(QGraphicsPathItem):
    """A plain cubic bezier wire between two ports."""
    def __init__(self, port1, port2=None):
        super().__init__()
        self.port1 = port1
        self.port2 = port2
        self._hovered = False

        self.setZValue(-1)
        self.setAcceptHoverEvents(True)
        self.setFlags(QGraphicsItem.ItemIsSelectable)

        self.update_path()

    def update_path(self, target_pos=None):
        pos1 = self.port1.scenePos()

        if self.port2:
            pos2 = self.port2.scenePos()
        elif target_pos:
            pos2 = target_pos
        else:
            pos2 = pos1

        path = QPainterPath()
        path.moveTo(pos1)

        # Control points for the cubic bezier
        dx = abs(pos2.x() - pos1.x()) * 0.5
        dx = max(dx, 40.0)

        cp1_x = pos1.x() + dx if self.port1.is_output else pos1.x() - dx

        if self.port2:
            cp2_x = pos2.x() + dx if self.port2.is_output else pos2.x() - dx
        else:
            cp2_x = pos2.x() - dx if self.port1.is_output else pos2.x() + dx

        path.cubicTo(
            QPointF(cp1_x, pos1.y()),
            QPointF(cp2_x, pos2.y()),
            pos2
        )
        self.setPath(path)
        self._update_pen()

    def _update_pen(self):
        highlighted = self._hovered or self.isSelected()
        colour = theme.ACCENT if highlighted else theme.WIRE
        pen = QPen(theme.qcolor(colour), 1.5)
        pen.setCapStyle(Qt.RoundCap)
        if self.port2 is None:
            pen.setStyle(Qt.DashLine)  # wire being dragged
        self.setPen(pen)

    def hoverEnterEvent(self, event):
        self._hovered = True
        super().hoverEnterEvent(event)
        self._update_pen()

    def hoverLeaveEvent(self, event):
        self._hovered = False
        super().hoverLeaveEvent(event)
        self._update_pen()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self._update_pen()
        return super().itemChange(change, value)

    def paint(self, painter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(Qt.NoBrush)  # open bezier paths must not be filled
        painter.setPen(self.pen())
        painter.drawPath(self.path())
        painter.restore()

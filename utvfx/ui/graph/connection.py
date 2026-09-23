from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsItem
from PySide6.QtGui import QPen, QPainterPath, QPainter
from PySide6.QtCore import Qt, QPointF

from utvfx.ui import theme


def port_direction(port):
    """Unit vector a wire leaves `port` along."""
    if getattr(port.node, "plugin_type", None) == "dot_node":
        return QPointF(0, 1) if port.is_output else QPointF(0, -1)
    return QPointF(1, 0) if port.is_output else QPointF(-1, 0)


def _reach(direction, pos1, pos2):
    """Tangent length: half the gap along the tangent's axis, at least 40 px.

    Vertical (Dot) tangents stay short when the ends are close, so a Dot right
    under its source does not loop.
    """
    if direction.x() != 0:
        return max(abs(pos2.x() - pos1.x()) * 0.5, 40.0)
    gap = abs(pos2.y() - pos1.y())
    return max(gap * 0.5, min(40.0, gap * 0.5 + 12.0))


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

        # Each end leaves along its port's direction: sideways for node ports,
        # up/down for a Dot (input on top, output below).
        d1 = port_direction(self.port1)
        d2 = port_direction(self.port2) if self.port2 else QPointF(-d1.x(), -d1.y())
        path.cubicTo(
            pos1 + d1 * _reach(d1, pos1, pos2),
            pos2 + d2 * _reach(d2, pos1, pos2),
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

from PySide6.QtWidgets import QGraphicsObject, QGraphicsItem
from PySide6.QtGui import QPen, QColor, QPainterPath, QPainter, QFont, QFontMetricsF
from PySide6.QtCore import Qt, QRectF, QPointF

from utvfx.ui import icons, theme
from utvfx.ui.graph import constants as C
from utvfx.ui.graph.port import PortItem

NODE_BORDER = C.NODE_BORDER
NODE_BORDER_HOVER = C.NODE_BORDER_HOVER


class BackdropNodeItem(QGraphicsObject):
    def __init__(self, name="Backdrop", parent=None):
        super().__init__(parent)
        self.width = 400
        self.height = 300
        self.name = name
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(-1000)
        self.resizing = False
        self._contained_items = []
        self.backdrop_id = None  # set by NodeScene.add_backdrop

    def to_dict(self):
        return {
            "backdrop_id": self.backdrop_id,
            "name": self.name,
            "x": self.pos().x(),
            "y": self.pos().y(),
            "width": self.width,
            "height": self.height,
        }

    def boundingRect(self):
        return QRectF(0, 0, self.width, self.height)

    def paint(self, painter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.boundingRect().adjusted(0.5, 0.5, -0.5, -0.5)
        body = QPainterPath()
        body.addRoundedRect(rect, C.NODE_RADIUS, C.NODE_RADIUS)

        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qcolor(theme.TEXT_FAINT, 40))
        painter.drawPath(body)

        painter.save()
        painter.setClipPath(body)
        painter.setBrush(theme.qcolor(theme.TEXT_FAINT, 70))
        painter.drawRect(QRectF(0, 0, self.width, 24))
        painter.restore()

        if self.isSelected():
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1.5))
        else:
            painter.setPen(QPen(theme.qcolor(theme.BORDER_SOFT), 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(body)

        painter.setFont(theme.ui_font(10, QFont.Weight.DemiBold))
        painter.setPen(theme.qcolor(theme.TEXT))
        painter.drawText(QRectF(10, 0, self.width - 20, 24), Qt.AlignVCenter | Qt.AlignLeft, self.name)

        painter.setPen(QPen(theme.qcolor(theme.TEXT_FAINT), 1.0))
        painter.drawLine(QPointF(self.width - 14, self.height - 4), QPointF(self.width - 4, self.height - 14))
        painter.drawLine(QPointF(self.width - 9, self.height - 4), QPointF(self.width - 4, self.height - 9))
        painter.restore()

    def mousePressEvent(self, event):
        pos = event.pos()
        if pos.x() > self.width - 20 and pos.y() > self.height - 20:
            self.resizing = True
            event.accept()
        else:
            self._contained_items = []
            scene = self.scene()
            if scene:
                for item in scene.items(self.mapToScene(self.boundingRect())):
                    if isinstance(item, VFXNodeItem):
                        if self.sceneBoundingRect().contains(item.sceneBoundingRect().center()):
                            self._contained_items.append((item, item.pos() - self.pos()))
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.resizing:
            self.prepareGeometryChange()
            self.width = max(100, event.pos().x())
            self.height = max(100, event.pos().y())
            self.update()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.resizing:
            self.resizing = False
        else:
            super().mouseReleaseEvent(event)
            self._contained_items = []

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and not self.resizing:
            if hasattr(self, '_contained_items'):
                for item, offset in self._contained_items:
                    item.setPos(value + offset)
        return super().itemChange(change, value)


class DotNodeItem(QGraphicsObject):
    def __init__(self, node_id, name="Dot", plugin_type="dot_node", color="#888888"):
        super().__init__()
        self.node_id = node_id
        self.name = name
        self.plugin_type = plugin_type
        self.accent_color = QColor(color)
        self.inputs = []
        self.outputs = []
        self.is_disabled = False
        self.is_frozen = False
        self.params = {}

        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setZValue(1)

    def to_dict(self):
        return {
            "node_id": self.node_id,
            "name": self.name,
            "plugin_type": self.plugin_type,
            "color": self.accent_color.name(),
            "x": self.pos().x(),
            "y": self.pos().y(),
            "disabled": self.is_disabled,
            "frozen": False,
            "params": self.params,
        }

    def set_execution_state(self, executing, progress=0):
        pass  # a Dot only passes its input through

    def add_input(self, name):
        port = PortItem(name, is_output=False, parent=self)
        self.inputs.append(port)
        self.update_ports()
        
    def add_output(self, name):
        port = PortItem(name, is_output=True, parent=self)
        self.outputs.append(port)
        self.update_ports()
        
    def update_ports(self):
        for port in self.inputs + self.outputs:
            port.label.hide()  # a Dot is too small for port names
        if self.inputs:
            self.inputs[0].setPos(0, -6)
        if self.outputs:
            self.outputs[0].setPos(0, 6)
            
    def boundingRect(self):
        return QRectF(-10, -10, 20, 20)
        
    def paint(self, painter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(theme.qcolor(theme.WIRE))
        if self.isSelected():
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1.5))
        else:
            painter.setPen(QPen(theme.qcolor(theme.NODE_BORDER), 1.0))
        if self.is_disabled:
            painter.setOpacity(0.45)
        painter.drawEllipse(QRectF(-6, -6, 12, 12))
        painter.restore()

    def itemChange(self, change, value):
        # After the move, not before it, so wires end on the Dot's new position.
        if change == QGraphicsItem.ItemPositionHasChanged:
            for port in self.inputs + self.outputs:
                for conn in port.connections:
                    conn.update_path()
        return super().itemChange(change, value)

    def toggle_disable(self):
        self.is_disabled = not self.is_disabled
        self.update()


class VFXNodeItem(QGraphicsObject):
    """A compact graph node: a coloured header strip over a flat grey body."""
    def __init__(self, node_id, name, plugin_type, accent_color="#f59e0b"):
        super().__init__()
        self.node_id = node_id
        self.name = name
        self.plugin_type = plugin_type

        # Dimensions & styling
        self.width = C.NODE_WIDTH
        self.base_height = C.NODE_HEADER + 24
        self.height = self.base_height
        self.corner_radius = C.NODE_RADIUS
        self.is_disabled = False
        self.accent_color = QColor(accent_color)  # saved with the project; not used for drawing
        self.header_color = theme.qcolor(theme.node_colour(plugin_type))
        self.is_hovered = False

        # Execution State
        self.is_executing = False
        self.progress = 0
        self.is_error = False
        self.error_message = ""
        self.is_cached = False

        # Shake to Disconnect tracking
        import time
        self._shake_history = []
        self._last_shake_time = time.time()

        self.setFlags(
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)

        self.shadow = None  # nodes are flat; kept for code that looks for it

        self.inputs = []
        self.outputs = []
        self.old_pos = None

    def hoverEnterEvent(self, event):
        self.is_hovered = True
        self.update()
        super().hoverEnterEvent(event)
        
    def hoverLeaveEvent(self, event):
        self.is_hovered = False
        self.update()
        super().hoverLeaveEvent(event)
        
    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        # Shake to Disconnect Logic
        import time
        current_time = time.time()
        
        # Only track if moved recently
        if current_time - self._last_shake_time < 0.2:
            delta_x = event.scenePos().x() - event.lastScenePos().x()
            if abs(delta_x) > 15:
                direction = 1 if delta_x > 0 else -1
                
                # If direction changed, record it
                if not self._shake_history or self._shake_history[-1] != direction:
                    self._shake_history.append(direction)
                    
                # Keep last 6 direction changes
                if len(self._shake_history) > 12:
                    self._shake_history.pop(0)
                    
                # If we have 6 alternating rapid direction changes, trigger disconnect
                if len(self._shake_history) == 12:
                    if self.scene() and hasattr(self.scene(), "undo_stack") and self.scene().undo_stack:
                        from utvfx.core.commands import DisconnectCommand
                        # Disconnect all ports
                        for port in self.inputs + self.outputs:
                            for conn in list(port.connections):
                                self.scene().undo_stack.push(DisconnectCommand(self.scene(), conn))
                        self._shake_history.clear()
        else:
            self._shake_history.clear()
            
        self._last_shake_time = current_time
        
    def add_input(self, name):
        port = PortItem(name, is_output=False, parent=self)
        self.inputs.append(port)
        self._recalculate_size()
        return port
        
    def add_output(self, name):
        port = PortItem(name, is_output=True, parent=self)
        self.outputs.append(port)
        self._recalculate_size()
        return port
        
    def _recalculate_size(self):
        port_count = max(len(self.inputs), len(self.outputs))
        self.prepareGeometryChange()
        self.height = max(self.base_height, C.PORT_TOP - C.PORT_ROW + 12 + port_count * C.PORT_ROW)

        y = C.PORT_TOP
        for port in self.inputs:
            port.setPos(0, y)
            y += C.PORT_ROW

        y = C.PORT_TOP
        for port in self.outputs:
            port.setPos(self.width, y)
            y += C.PORT_ROW

    def boundingRect(self):
        return QRectF(-4, -4, self.width + 8, self.height + 8)

    def _status_icons(self):
        """(icon name, colour, on a dark badge) for the header, right to left."""
        result = []
        if self.is_error:
            result.append(("warning", theme.TEXT_ON_ACCENT, False))
        if self.is_cached:
            result.append(("check", theme.SUCCESS, True))
        if getattr(self, "is_frozen", False):
            result.append(("freeze", theme.TEXT_ON_ACCENT, False))
        return result

    def paint(self, painter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        w, h, hh, r = self.width, self.height, C.NODE_HEADER, self.corner_radius
        body_path = QPainterPath()
        body_path.addRoundedRect(QRectF(0, 0, w, h), r, r)
        dim = self.is_disabled

        # Body
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qcolor(theme.NODE_BODY))
        painter.drawPath(body_path)

        # Header strip in the category colour (red when the node failed)
        header = theme.qcolor(theme.ERROR) if self.is_error else QColor(self.header_color)
        if dim:
            header = QColor.fromHsvF(header.hsvHueF(), header.hsvSaturationF() * 0.3,
                                     header.valueF() * 0.65)
        painter.save()
        painter.setClipPath(body_path)
        painter.setBrush(header)
        painter.drawRect(QRectF(0, 0, w, hh))
        painter.setPen(QPen(theme.qcolor(theme.NODE_BORDER), 1.0))
        painter.drawLine(QPointF(0, hh), QPointF(w, hh))
        painter.restore()

        # Status icons, right-aligned in the header
        x = w - 5
        for name, colour, badge in self._status_icons():
            size = 12
            x -= size
            rect = QRectF(x, (hh - size) / 2, size, size)
            if badge:
                painter.setPen(Qt.NoPen)
                painter.setBrush(theme.qcolor(theme.NODE_BODY))
                painter.drawRoundedRect(rect.adjusted(-1.5, -1.5, 1.5, 1.5), 2, 2)
            painter.drawPixmap(rect, icons.pixmap(name, size, colour, 4.0), QRectF())
            x -= 5

        # Title
        font = theme.ui_font(9, QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(theme.qcolor(theme.TEXT_ON_ACCENT, 170 if dim else 255))
        title_rect = QRectF(7, 0, max(10.0, x - 7), hh)
        self.name_display = QFontMetricsF(font).elidedText(self.name, Qt.ElideRight, title_rect.width())
        painter.drawText(title_rect, Qt.AlignVCenter | Qt.AlignLeft, self.name_display)

        # Bypassed: dim the body and strike the node through, as Nuke does
        if dim:
            painter.save()
            painter.setClipPath(body_path)
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.qcolor(theme.GRAPH_BG, 130))
            painter.drawRect(QRectF(0, hh, w, h - hh))
            painter.setPen(QPen(theme.qcolor(theme.TEXT_DIM), 1.5))
            painter.drawLine(QPointF(0, 0), QPointF(w, h))
            painter.restore()

        # Thin progress bar along the bottom edge while executing
        if self.is_executing:
            painter.save()
            painter.setClipPath(body_path)
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.qcolor(theme.BG_INPUT))
            painter.drawRect(QRectF(0, h - 3, w, 3))
            painter.setBrush(theme.qcolor(theme.ACCENT))
            fraction = max(0.0, min(1.0, self.progress / 100.0))
            painter.drawRect(QRectF(0, h - 3, w * fraction, 3))
            painter.restore()

        # Outline
        if self.isSelected():
            pen = QPen(theme.qcolor(theme.ACCENT), 1.5)
        elif self.is_error:
            pen = QPen(theme.qcolor(theme.ERROR), 1.5)
        elif self.is_hovered:
            pen = QPen(NODE_BORDER_HOVER, 1.0)
        else:
            pen = QPen(NODE_BORDER, 1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(body_path)

        painter.restore()

    def set_execution_state(self, executing, progress=0):
        self.is_executing = executing
        self.progress = progress
        if executing:
            self.is_error = False
            self.is_cached = False
            self.error_message = ""
            self.setToolTip("")
        self.update()

    def set_error_state(self, is_error, message=""):
        self.is_error = is_error
        self.error_message = message
        self.setToolTip(message if is_error else "")
        if is_error:
            self.is_executing = False
        self.update()

    def set_cached_state(self):
        self.is_cached = True
        self.is_executing = False
        self.is_error = False
        self.update()

        # Clear cached state indicator automatically after 3 seconds
        from PySide6.QtCore import QTimer
        QTimer.singleShot(3000, self._clear_cached_state)

    def _clear_cached_state(self):
        self.is_cached = False
        self.update()

    def toggle_disable(self):
        self.is_disabled = not self.is_disabled
        self.update()

    def toggle_freeze(self):
        self.is_frozen = not getattr(self, 'is_frozen', False)
        self.update()

    def to_dict(self):
        return {
            "node_id": self.node_id,
            "name": self.name,
            "plugin_type": self.plugin_type,
            "color": self.accent_color.name(),
            "x": self.pos().x(),
            "y": self.pos().y(),
            "disabled": getattr(self, "is_disabled", False),
            "frozen": getattr(self, "is_frozen", False),
            "params": getattr(self, "params", {})
        }

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            # Grid Snapping
            from PySide6.QtWidgets import QApplication
            if QApplication.keyboardModifiers() & Qt.ShiftModifier:
                new_pos = value
                grid_size = C.GRID_SIZE  # matches the background grid
                snapped_x = round(new_pos.x() / grid_size) * grid_size
                snapped_y = round(new_pos.y() / grid_size) * grid_size
                return QPointF(snapped_x, snapped_y)
        elif change == QGraphicsItem.ItemPositionHasChanged:
            # Update connections while dragging
            for port in self.inputs + self.outputs:
                port.update_connections()
        return super().itemChange(change, value)

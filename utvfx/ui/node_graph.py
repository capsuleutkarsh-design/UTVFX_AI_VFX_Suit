import math
from PySide6.QtWidgets import (
    QGraphicsObject, QGraphicsPathItem, QGraphicsScene, QGraphicsView,
    QGraphicsItem, QGraphicsTextItem, QGraphicsDropShadowEffect, QWidget, QMenu,
    QLineEdit, QListWidget, QVBoxLayout
)
from PySide6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QFont, QLinearGradient, QRadialGradient, QPainter, QPolygonF, QShortcut, QKeySequence, QPainterPathStroker
)
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QObject

class NodeSearchMenu(QWidget):
    node_selected = Signal(str) # Emits plugin_type

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search Nodes...")
        self.search_bar.setStyleSheet("background-color: #18181b; color: white; border: 1px solid #3f3f46; border-radius: 4px; padding: 6px; font-family: 'Inter';")
        self.layout.addWidget(self.search_bar)
        
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("QListWidget { background-color: #18181b; color: white; border: 1px solid #3f3f46; border-radius: 4px; font-family: 'Inter'; } QListWidget::item:selected { background-color: #2563eb; }")
        self.layout.addWidget(self.list_widget)
        
        self.search_bar.textChanged.connect(self.filter_nodes)
        self.list_widget.itemActivated.connect(self.accept_selection)
        
        from utvfx.core.data_model import NODES_REGISTRY
        self.registry = NODES_REGISTRY
        self.filter_nodes("")
        
        self.setFixedSize(220, 260)
        
    def filter_nodes(self, text):
        self.list_widget.clear()
        text = text.lower()
        for ptype, pdef in self.registry.items():
            if text in pdef["name"].lower() or text in ptype.lower():
                from PySide6.QtWidgets import QListWidgetItem
                item = QListWidgetItem(pdef["name"])
                item.setData(Qt.UserRole, ptype)
                self.list_widget.addItem(item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
            
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Down:
            row = min(self.list_widget.count() - 1, self.list_widget.currentRow() + 1)
            self.list_widget.setCurrentRow(row)
        elif event.key() == Qt.Key_Up:
            row = max(0, self.list_widget.currentRow() - 1)
            self.list_widget.setCurrentRow(row)
        elif event.key() in (Qt.Key_Enter, Qt.Key_Return):
            self.accept_selection()
        elif event.key() == Qt.Key_Escape:
            self.hide()
        else:
            self.search_bar.event(event)

    def accept_selection(self):
        item = self.list_widget.currentItem()
        if item:
            ptype = item.data(Qt.UserRole)
            self.node_selected.emit(ptype)
        self.hide()

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

    def boundingRect(self):
        return QRectF(0, 0, self.width, self.height)

    def paint(self, painter, option, widget):
        painter.setBrush(QColor(40, 40, 45, 180))
        if self.isSelected():
            painter.setPen(QPen(QColor(200, 200, 200, 255), 2.0))
        else:
            painter.setPen(QPen(QColor(100, 100, 100, 255), 1.0))
        painter.drawRect(self.boundingRect())
        
        painter.setBrush(QColor(30, 30, 35, 200))
        painter.setPen(Qt.NoPen)
        painter.drawRect(0, 0, self.width, 30)
        
        painter.setPen(QColor(200, 200, 200))
        font = QFont("Inter", 12)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(10, 20, self.name)
        
        painter.setPen(QColor(100, 100, 100))
        painter.drawLine(self.width - 15, self.height - 5, self.width - 5, self.height - 15)
        painter.drawLine(self.width - 10, self.height - 5, self.width - 5, self.height - 10)

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
        
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setZValue(1)
        
    def add_input(self, name):
        port = PortItem(name, is_output=False, parent=self)
        self.inputs.append(port)
        self.update_ports()
        
    def add_output(self, name):
        port = PortItem(name, is_output=True, parent=self)
        self.outputs.append(port)
        self.update_ports()
        
    def update_ports(self):
        if self.inputs:
            self.inputs[0].setPos(0, -6)
        if self.outputs:
            self.outputs[0].setPos(0, 6)
            
    def boundingRect(self):
        return QRectF(-10, -10, 20, 20)
        
    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        if self.isSelected():
            painter.setBrush(self.accent_color)
            painter.setPen(QPen(QColor(255, 255, 255), 2))
        else:
            painter.setBrush(QColor(100, 100, 100))
            painter.setPen(QPen(QColor(50, 50, 50), 1))
        
        painter.drawEllipse(QRectF(-6, -6, 12, 12))
        
    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            for port in self.inputs + self.outputs:
                for conn in port.connections:
                    conn.update_path()
        return super().itemChange(change, value)
        
    def toggle_disable(self):
        self.is_disabled = not self.is_disabled
        self.update()


class VFXNodeItem(QGraphicsObject):
    """A premium, glassmorphic node visual item with glowing selections and dynamic headers."""
    def __init__(self, node_id, name, plugin_type, accent_color="#f59e0b"):
        super().__init__()
        self.node_id = node_id
        self.name = name
        self.plugin_type = plugin_type
        
        # Dimensions & Styling
        self.width = 240
        self.base_height = 52
        self.corner_radius = 10
        self.is_disabled = False
        self.accent_color = QColor(accent_color)
        self.is_hovered = False
        
        # Execution State
        self.is_executing = False
        self.progress = 0
        
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
        
        # Rich drop shadow for visual separation (referenced as self.shadow)
        self.shadow = QGraphicsDropShadowEffect()
        self.shadow.setBlurRadius(20)
        self.shadow.setColor(QColor(0, 0, 0, 160))
        self.shadow.setOffset(0, 8)
        self.setGraphicsEffect(self.shadow)
        
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
        # Mathematically balanced padding: 58px top starting, 28px step, 18px bottom padding
        self.height = max(self.base_height, 48 + port_count * 28)
        
        # Position inputs (sitting right on the left border)
        y = 58
        for port in self.inputs:
            port.setPos(0, y)
            y += 28
            
        # Position outputs (sitting right on the right border)
        y = 58
        for port in self.outputs:
            port.setPos(self.width, y)
            y += 28
            
    def boundingRect(self):
        # Extend slightly to prevent clipping selection border or glow
        return QRectF(-4, -4, self.width + 8, self.height + 8)
        
    def paint(self, painter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Dim if disabled
        if self.is_disabled:
            painter.setOpacity(0.4)
        
        # 1. Dynamic Underglow (Selection-based drop shadow adjustment)
        if self.isSelected():
            # Glowing accent color underglow
            glow_color = QColor(self.accent_color.red(), self.accent_color.green(), self.accent_color.blue(), 100)
            if self.shadow.color() != glow_color or self.shadow.blurRadius() != 28 or self.shadow.yOffset() != 0:
                self.shadow.setColor(glow_color)
                self.shadow.setBlurRadius(28)
                self.shadow.setOffset(0, 0)
        else:
            # Standard deep black shadow
            dark_shadow = QColor(0, 0, 0, 160)
            if self.shadow.color() != dark_shadow or self.shadow.blurRadius() != 20 or self.shadow.yOffset() != 8:
                self.shadow.setColor(dark_shadow)
                self.shadow.setBlurRadius(20)
                self.shadow.setOffset(0, 8)
        
        # Body shape
        body_path = QPainterPath()
        body_path.addRoundedRect(0, 0, self.width, self.height, self.corner_radius, self.corner_radius)
        
        # 2. Glassmorphic Body Fill (Charcoal-to-black vertical gradient)
        bg_gradient = QLinearGradient(0, 0, 0, self.height)
        bg_gradient.setColorAt(0, QColor(22, 24, 30, 235))  # Translucent top
        bg_gradient.setColorAt(1, QColor(10, 10, 12, 245))  # Deep nearly-opaque bottom
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bg_gradient))
        painter.drawPath(body_path)
        
        # 3. Top Accent Bar (Clipped to body rounded corners)
        accent_bar_height = 3.5
        clip_rect = QRectF(0, 0, self.width, accent_bar_height)
        
        painter.save()
        painter.setClipPath(body_path)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self.accent_color))
        painter.drawRect(clip_rect)
        painter.restore()
        
        # 4. Top-Lit Color Bleed (Radial glow radiating from top center)
        radial_glow = QRadialGradient(
            QPointF(self.width / 2.0, 0),
            self.width * 0.7,
            QPointF(self.width / 2.0, accent_bar_height)
        )
        radial_glow.setColorAt(0, QColor(self.accent_color.red(), self.accent_color.green(), self.accent_color.blue(), 40))
        radial_glow.setColorAt(0.3, QColor(self.accent_color.red(), self.accent_color.green(), self.accent_color.blue(), 15))
        radial_glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        
        painter.save()
        painter.setClipPath(body_path)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(radial_glow))
        painter.drawRect(QRectF(0, accent_bar_height, self.width, 50))
        painter.restore()
        
        # 5. Inner Glass Bevel Highlight
        highlight_path = QPainterPath()
        highlight_path.addRoundedRect(0.5, 0.5, self.width - 1.0, self.height - 1.0, self.corner_radius - 0.5, self.corner_radius - 0.5)
        
        highlight_gradient = QLinearGradient(0, 0, 0, self.height)
        highlight_gradient.setColorAt(0, QColor(255, 255, 255, 22))  # Inner top glow
        highlight_gradient.setColorAt(0.4, QColor(255, 255, 255, 4))
        highlight_gradient.setColorAt(1, QColor(255, 255, 255, 0))
        
        painter.setPen(QPen(highlight_gradient, 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(highlight_path)
        
        # Categorize node based on type or name for sub-header label
        category_text = "VFX NODE"
        ptype_lower = self.plugin_type.lower()
        name_lower = self.name.lower()
        
        if "tracker" in ptype_lower or "camera" in name_lower:
            category_text = "3D TRACKER"
        elif "keyer" in ptype_lower or "keyer" in name_lower:
            category_text = "CHROMA KEYER"
        elif "rotoscope" in ptype_lower or "roto" in name_lower:
            category_text = "AI SEGMENTATION"
        elif "plate" in ptype_lower or "media" in name_lower:
            category_text = "INPUT PLATE"
        elif "output" in ptype_lower or "composite" in name_lower:
            category_text = "COMPOSITE OUTPUT"
        elif "matte" in ptype_lower:
            category_text = "AI MATTING"
            
        # 6. Modern Status Indicator Dot
        dot_center = QPointF(16, 14.5)
        dot_radius = 3.0
        
        # Draw status dot glow
        dot_glow = QRadialGradient(dot_center, dot_radius * 2.5)
        dot_glow.setColorAt(0, QColor(self.accent_color.red(), self.accent_color.green(), self.accent_color.blue(), 180))
        dot_glow.setColorAt(1, QColor(self.accent_color.red(), self.accent_color.green(), self.accent_color.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(dot_glow))
        painter.drawEllipse(dot_center, dot_radius * 2.5, dot_radius * 2.5)
        
        # Draw status dot core
        painter.setBrush(QBrush(self.accent_color.lighter(115)))
        painter.drawEllipse(dot_center, dot_radius, dot_radius)
        
        # 7. Draw Category Subtitle (Shifted to x=26 to accommodate status dot)
        category_font = QFont("Inter", 7.0, QFont.Bold)
        category_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        painter.setFont(category_font)
        painter.setPen(QPen(QColor(200, 200, 210, 160)))
        painter.drawText(26, 18, category_text)
        
        # 8. Draw Main Node Title
        title_font = QFont("Inter", 9.5, QFont.Bold)
        if getattr(self, "is_frozen", False):
            title_font.setItalic(True)
            self.name_display = self.name + " ❄ (Frozen)"
        elif self.is_disabled:
            title_font.setItalic(True)
            self.name_display = self.name + " (Bypassed)"
        else:
            self.name_display = self.name
            
        painter.setFont(title_font)
        painter.setPen(QPen(QColor("#ffffff")))
        painter.drawText(14, 33, self.name_display)
        
        # 9. Outer Border Outline
        if self.isSelected():
            border_pen = QPen(self.accent_color.lighter(110), 2.0)
        elif self.is_executing:
            # Pulsing border when executing
            border_pen = QPen(QColor(self.accent_color.red(), self.accent_color.green(), self.accent_color.blue(), 255), 2.5)
        elif self.is_hovered:
            border_pen = QPen(NODE_BORDER_HOVER, 1.2)
        else:
            border_pen = QPen(NODE_BORDER, 1.0)
            
        painter.setPen(border_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(body_path)
        
        # 10. Execution Progress Bar
        if self.is_executing:
            progress_rect = QRectF(10, self.height - 8, (self.width - 20) * (self.progress / 100.0), 3)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(self.accent_color))
            painter.drawRoundedRect(progress_rect, 1.5, 1.5)
            
        # 11. Bypass Overlay
        if self.is_disabled:
            painter.setPen(QPen(QColor(255, 0, 0, 150), 3, Qt.DashLine))
            painter.drawLine(10, 10, self.width - 10, self.height - 10)
            painter.drawLine(self.width - 10, 10, 10, self.height - 10)
        
        painter.restore()

    def set_execution_state(self, executing, progress=0):
        self.is_executing = executing
        self.progress = progress
        self.update()

        self.is_frozen = False

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
                # Grid size is 30 based on drawBackground
                grid_size = 30
                snapped_x = round(new_pos.x() / grid_size) * grid_size
                snapped_y = round(new_pos.y() / grid_size) * grid_size
                return QPointF(snapped_x, snapped_y)
        elif change == QGraphicsItem.ItemPositionHasChanged:
            # Update connections while dragging
            for port in self.inputs + self.outputs:
                port.update_connections()
        return super().itemChange(change, value)


class NodeScene(QGraphicsScene):
    """The graph canvas scene."""
    
    class Signals(QObject):
        nodeSelected = Signal(object)  # Emits node data dict
        nodeAdded = Signal(str, str)   # node_id, plugin_type
        nodeDeleted = Signal(str)      # node_id
        connectionChanged = Signal()
        viewerHotkey = Signal(object, int) # node_data, key_number
        queueNodeRequested = Signal(object) # Emits the node to add to the render queue
        fileDropped = Signal(str, dict) # Emits the file path and drop location {x: float, y: float}
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = self.Signals()
        self.setSceneRect(-5000, -5000, 10000, 10000)
        self.setBackgroundBrush(QBrush(BG_COLOR))
        
        self.nodes = []
        self.connections = []
        self._next_id = 0
        
        # Interaction state
        self.is_connecting = False
        self.temp_connection = None
        self.connection_start_port = None
        self.undo_stack = None
        
        self.selectionChanged.connect(self._on_selection_changed)

    def toggle_selected_nodes_disable(self):
        for item in self.selectedItems():
            if isinstance(item, VFXNodeItem):
                item.toggle_disable()

    def _on_selection_changed(self):
        items = self.selectedItems()
        node = None
        for item in items:
            if isinstance(item, VFXNodeItem):
                node = item
                break
        self.signals.nodeSelected.emit(node)



    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor("#121212"))
        
        # Draw dot grid
        left = int(rect.left()) - (int(rect.left()) % 30)
        top = int(rect.top()) - (int(rect.top()) % 30)
        
        painter.setPen(QPen(QColor("#2c2c2c"), 1))
        points = QPolygonF()
        
        for x in range(left, int(rect.right()), 30):
            for y in range(top, int(rect.bottom()), 30):
                points.append(QPointF(x, y))
                
        painter.drawPoints(points)
                
    def add_node(self, name, plugin_type, inputs=None, outputs=None, color="#f59e0b", pos=(0,0), node_id=None):
        import uuid
        if node_id is None:
            node_id = str(uuid.uuid4())
            
        inputs = inputs or []
        outputs = outputs or []
        
        if plugin_type == "dot_node":
            node = DotNodeItem(node_id, name, plugin_type, color)
        else:
            node = VFXNodeItem(node_id, name, plugin_type, color)
        
        for inp in inputs:
            node.add_input(inp)
        for out in outputs:
            node.add_output(out)
            
        node.setPos(*pos)
        self.addItem(node)
        self.nodes.append(node)
        return node
        
    def mousePressEvent(self, event):
        if not self.views(): return
        item = self.itemAt(event.scenePos(), self.views()[0].transform())
        
        # Start connection if clicking a port
        if isinstance(item, PortItem):
            self.is_connecting = True
            self.connection_start_port = item
            self.temp_connection = ConnectionItem(item)
            self.addItem(self.temp_connection)
            event.accept()
            return
            
        # Record positions of selected nodes for Move command
        for node in self.selectedItems():
            if isinstance(node, VFXNodeItem):
                node.old_pos = node.pos()
                
        super().mousePressEvent(event)
        
    def mouseMoveEvent(self, event):
        if self.is_connecting and self.temp_connection:
            self.temp_connection.update_path(event.scenePos())
            event.accept()
            return
            
        super().mouseMoveEvent(event)
        
    def mouseReleaseEvent(self, event):
        if self.is_connecting:
            self.is_connecting = False
            if not self.views(): return
            if self.temp_connection:
                self.temp_connection.hide()
            item = self.itemAt(event.scenePos(), self.views()[0].transform())
            if self.temp_connection:
                self.temp_connection.show()
            
            # Successful connection?
            if isinstance(item, PortItem) and item != self.connection_start_port:
                # Basic validation: input to output, diff nodes
                p1 = self.connection_start_port
                p2 = item
                if p1.is_output != p2.is_output and p1.node != p2.node:
                    # Make sure p1 is the output for logic simplicity
                    out_port = p1 if p1.is_output else p2
                    in_port = p2 if not p2.is_output else p1
                    
                    if self.undo_stack:
                        from utvfx.core.commands import ConnectCommand
                        cmd = ConnectCommand(self, out_port, in_port)
                        self.undo_stack.push(cmd)
                    else:
                        # Fallback if no undo stack
                        for existing_conn in list(in_port.connections):
                            if existing_conn in self.connections:
                                self.connections.remove(existing_conn)
                            existing_conn.port1.remove_connection(existing_conn)
                            if existing_conn.port2:
                                existing_conn.port2.remove_connection(existing_conn)
                            self.removeItem(existing_conn)
                        
                        conn = ConnectionItem(out_port, in_port)
                        out_port.add_connection(conn)
                        in_port.add_connection(conn)
                        self.addItem(conn)
                        self.connections.append(conn)
            elif self.views():
                # Dropped in empty space - context-aware wire drop
                view = self.views()[0]
                if hasattr(view, "show_search_menu"):
                    # Pass the starting port and the global position to the view
                    global_pos = event.screenPos()
                    view.show_search_menu(global_pos, self.connection_start_port)
                    
            # Cleanup temp
            if self.temp_connection:
                self.removeItem(self.temp_connection)
                self.temp_connection = None
                
            event.accept()
            return
            
        super().mouseReleaseEvent(event)
        
        # Check if nodes moved and push to undo stack
        if self.undo_stack:
            from utvfx.core.commands import MoveNodeCommand, DisconnectCommand, ConnectCommand
            for node in self.selectedItems():
                if isinstance(node, VFXNodeItem) and hasattr(node, "old_pos") and node.old_pos is not None:
                    if node.old_pos != node.pos():
                        # Auto-Insertion (Drop-on-Wire)
                        if len(self.selectedItems()) == 1 and node.inputs and node.outputs:
                            node_rect = node.sceneBoundingRect()
                            for conn in list(self.connections):
                                # Ignore connections that this node is already part of
                                if getattr(conn.port1, 'node', None) == node or getattr(conn.port2, 'node', None) == node:
                                    continue
                                
                                if conn.sceneBoundingRect().intersects(node_rect):
                                    if conn.path().intersects(node_rect):
                                        # Find true output and input
                                        out_port = conn.port1 if conn.port1.is_output else conn.port2
                                        in_port = conn.port2 if not conn.port2.is_output else conn.port1
                                        if out_port and in_port:
                                            # Push commands
                                            self.undo_stack.push(DisconnectCommand(self, conn))
                                            self.undo_stack.push(ConnectCommand(self, out_port, node.inputs[0]))
                                            self.undo_stack.push(ConnectCommand(self, node.outputs[0], in_port))
                                            break
                                            
                        cmd = MoveNodeCommand(node, node.old_pos, node.pos())
                        self.undo_stack.push(cmd)
                    node.old_pos = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace:
            if self.undo_stack:
                from utvfx.core.commands import DeleteNodeCommand, DisconnectCommand
                for item in list(self.selectedItems()):
                    if isinstance(item, VFXNodeItem):
                        cmd = DeleteNodeCommand(self, item)
                        self.undo_stack.push(cmd)
                    elif isinstance(item, ConnectionItem):
                        cmd = DisconnectCommand(self, item)
                        self.undo_stack.push(cmd)
            else:
                for item in list(self.selectedItems()):
                    if isinstance(item, VFXNodeItem):
                        for port in item.inputs + item.outputs:
                            for conn in list(port.connections):
                                if conn in self.connections:
                                    self.connections.remove(conn)
                                conn.port1.remove_connection(conn)
                                if conn.port2:
                                    conn.port2.remove_connection(conn)
                                self.removeItem(conn)
                        self.removeItem(item)
                        self.nodes.remove(item)
                    elif isinstance(item, ConnectionItem):
                        if item in self.connections:
                            self.connections.remove(item)
                        item.port1.remove_connection(item)
                        if item.port2:
                            item.port2.remove_connection(item)
                        self.removeItem(item)
            event.accept()
            return
        elif event.key() == Qt.Key_D:
            for item in self.selectedItems():
                if isinstance(item, VFXNodeItem):
                    item.toggle_disable()
            event.accept()
            return
        super().keyPressEvent(event)

    def to_dict(self):
        nodes_data = [node.to_dict() for node in self.nodes]
        connections_data = []
        for conn in self.connections:
            # We need to find the port index
            src_node = conn.port1.node
            dst_node = conn.port2.node
            src_port_name = conn.port1.name
            dst_port_name = conn.port2.name
            
            connections_data.append({
                "src_node_id": src_node.node_id,
                "src_port_name": src_port_name,
                "dst_node_id": dst_node.node_id,
                "dst_port_name": dst_port_name
            })
            
        return {
            "nodes": nodes_data,
            "connections": connections_data
        }
        
    def from_dict(self, data):
        from utvfx.core.data_model import NODES_REGISTRY
        
        self.signals.nodeSelected.emit(None)
        
        # Clear existing
        for conn in list(self.connections):
            self.removeItem(conn)
        for node in list(self.nodes):
            self.removeItem(node)
        self.connections.clear()
        self.nodes.clear()
        
        # Recreate nodes
        for n_data in data.get("nodes", []):
            ptype = n_data["plugin_type"]
            registry_def = NODES_REGISTRY.get(ptype, {})
            inps = registry_def.get("inputs", [])
            outs = registry_def.get("outputs", [])
            
            node = self.add_node(
                name=n_data.get("name", "Unknown"),
                plugin_type=ptype,
                inputs=inps,
                outputs=outs,
                color=n_data.get("color", "#f59e0b"),
                pos=(n_data.get("x", 0), n_data.get("y", 0)),
                node_id=n_data.get("node_id")
            )
            node.params = n_data.get("params", {})
            
        # Recreate connections
        for c_data in data.get("connections", []):
            src_node = next((n for n in self.nodes if n.node_id == c_data["src_node_id"]), None)
            dst_node = next((n for n in self.nodes if n.node_id == c_data["dst_node_id"]), None)
            
            if src_node and dst_node:
                try:
                    if "src_port_name" in c_data and "dst_port_name" in c_data:
                        src_port = next((p for p in src_node.outputs if p.name == c_data["src_port_name"]), None)
                        dst_port = next((p for p in dst_node.inputs if p.name == c_data["dst_port_name"]), None)
                    else:
                        # Backward compatibility
                        src_port = src_node.outputs[c_data["src_port_idx"]]
                        dst_port = dst_node.inputs[c_data["dst_port_idx"]]
                    
                    if src_port and dst_port:
                        conn = ConnectionItem(src_port, dst_port)
                        src_port.add_connection(conn)
                        dst_port.add_connection(conn)
                        self.addItem(conn)
                        self.connections.append(conn)
                    else:
                        print(f"Warning: Ports not found for connection from {src_node.name} to {dst_node.name}")
                except Exception as e:
                    print(f"Warning: Failed to restore connection for {src_node.name} to {dst_node.name}. Error: {e}")


class NodeView(QGraphicsView):
    """The interactive view container for the graph."""
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        
        # Enable dragging to pan
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self._pan = False
        self._panStartX = 0
        self._panStartY = 0
        
        # Tool states
        self.current_tool = "normal"  # "normal" or "knife"
        self.knife_line = None
        self.knife_start_pos = None
        
        # Search Menu
        self.search_menu = NodeSearchMenu(self)
        self.search_menu.hide()
        self.search_menu.node_selected.connect(self._on_search_node_selected)
        self._last_search_pos = QPointF(0, 0)
        
        from PySide6.QtGui import QShortcut, QKeySequence
        self.shortcut_disable = QShortcut(QKeySequence("D"), self)
        self.shortcut_disable.activated.connect(self.scene().toggle_selected_nodes_disable)
        
        # Styling
        self.setStyleSheet("border: none; background-color: #09090b;")
        
    def _on_search_node_selected(self, plugin_type):
        parent_widget = self.scene().parent()
        if hasattr(parent_widget, "add_node_requested"):
            parent_widget.add_node_requested.emit(plugin_type, {"x": self._last_search_pos.x(), "y": self._last_search_pos.y()})
            # If we originated from a wire drop, connect it immediately
            if self._context_start_port:
                # We need to defer this slightly so the node has time to spawn
                from PySide6.QtCore import QTimer
                QTimer.singleShot(50, lambda: self._connect_context_node(self._context_start_port))
            self._context_start_port = None
            
    def _connect_context_node(self, start_port):
        # The node that was just spawned is usually the last item added
        # Or we can just find the most recent node
        nodes = [item for item in self.scene().items() if isinstance(item, VFXNodeItem)]
        if not nodes: return
        new_node = max(nodes, key=lambda n: n.zValue() if hasattr(n, 'zValue') else 0)
        
        # Determine port to connect to
        target_port = None
        if start_port.is_output and new_node.inputs:
            target_port = new_node.inputs[0]
        elif not start_port.is_output and new_node.outputs:
            target_port = new_node.outputs[0]
            
        if target_port:
            from utvfx.core.commands import ConnectCommand
            out_p = start_port if start_port.is_output else target_port
            in_p = target_port if start_port.is_output else start_port
            if self.scene().undo_stack:
                self.scene().undo_stack.push(ConnectCommand(self.scene(), out_p, in_p))
            
    def show_search_menu(self, global_pos, start_port=None):
        self._context_start_port = start_port
        self._last_search_pos = self.mapToScene(self.mapFromGlobal(global_pos))
        self.search_menu.move(global_pos)
        self.search_menu.show()
        self.search_menu.search_bar.setFocus()
        self.search_menu.search_bar.selectAll()
        
    def resizeEvent(self, event):
        super().resizeEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)
            
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)
            
    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                file_path = urls[0].toLocalFile()
                # Determine supported extensions (e.g., mp4, mov, png, jpg, exr)
                ext = file_path.lower().split(".")[-1]
                if ext in ["mp4", "mov", "avi", "mkv", "png", "jpg", "jpeg", "exr", "dpx", "hdr", "tif", "tiff"]:
                    pos = self.mapToScene(event.pos())
                    # Emit to scene's signals
                    if hasattr(self.scene(), "signals") and hasattr(self.scene().signals, "fileDropped"):
                        self.scene().signals.fileDropped.emit(file_path, {"x": pos.x(), "y": pos.y()})
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_V:
            self.current_tool = "normal"
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        elif event.key() == Qt.Key_K:
            self.current_tool = "knife"
            self.setCursor(Qt.CrossCursor)
            event.accept()
            return
        elif event.key() == Qt.Key_D:
            selected_items = self.scene().selectedItems()
            for item in selected_items:
                if isinstance(item, VFXNodeItem):
                    item.toggle_disable()
            event.accept()
            return
        elif event.key() == Qt.Key_Tab:
            self._last_search_pos = self.mapToScene(self.mapFromGlobal(self.cursor().pos()))
            self.search_menu.move(self.cursor().pos())
            self.search_menu.show()
            self.search_menu.search_bar.setFocus()
            self.search_menu.search_bar.selectAll()
            event.accept()
            return
        elif Qt.Key_1 <= event.key() <= Qt.Key_9:
            # Emit viewer hotkey with the selected node
            selected_items = self.scene().selectedItems()
            if selected_items and isinstance(selected_items[0], VFXNodeItem):
                node = selected_items[0]
                key_num = event.key() - Qt.Key_0
                if hasattr(self.scene(), "signals"):
                    self.scene().signals.viewerHotkey.emit(node, key_num)
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and event.modifiers() == Qt.AltModifier):
            self._pan = True
            self._panStartX = event.x()
            self._panStartY = event.y()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        elif event.button() == Qt.LeftButton and self.current_tool == "knife":
            self.knife_start_pos = self.mapToScene(event.pos())
            self.knife_line = [self.knife_start_pos, self.knife_start_pos]
            self.viewport().update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pan:
            self._pan = False
            self.setCursor(Qt.CrossCursor if self.current_tool == "knife" else Qt.ArrowCursor)
            event.accept()
            return
        elif event.button() == Qt.LeftButton and self.current_tool == "knife" and self.knife_line:
            # End knife cut
            end_pos = self.mapToScene(event.pos())
            self.knife_line[1] = end_pos
            
            # Find all connections intersecting this line
            from PySide6.QtCore import QLineF
            cut_line = QLineF(self.knife_line[0], self.knife_line[1])
            
            if self.scene() and self.scene().undo_stack:
                from utvfx.core.commands import DisconnectCommand
                # We need to iterate over all connections and see if their path intersects cut_line
                for conn in list(self.scene().connections):
                    # Rough intersection check: bounding box intersection first, then path intersection
                    if conn.sceneBoundingRect().intersects(QRectF(self.knife_line[0], self.knife_line[1]).normalized()):
                        # Check actual path
                        conn_path = conn.path()
                        # A simple way to check intersection is to see if the path intersects a small polygon formed by the line
                        # Or just use path intersection (but QPainterPath has no direct line intersection, so we convert line to path)
                        line_path = QPainterPath()
                        line_path.moveTo(cut_line.p1())
                        line_path.lineTo(cut_line.p2())
                        
                        # Add some thickness to the line path for easier intersection
                        stroker = QPainterPathStroker()
                        stroker.setWidth(4)
                        thick_line = stroker.createStroke(line_path)
                        
                        if thick_line.intersects(conn_path):
                            cmd = DisconnectCommand(self.scene(), conn)
                            self.scene().undo_stack.push(cmd)
                            
            self.knife_line = None
            self.knife_start_pos = None
            self.viewport().update()
            event.accept()
            return
            
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan:
            dx = event.x() - self._panStartX
            dy = event.y() - self._panStartY
            self._panStartX = event.x()
            self._panStartY = event.y()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - dx)
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - dy)
            event.accept()
            return
        elif self.current_tool == "knife" and self.knife_line:
            self.knife_line[1] = self.mapToScene(event.pos())
            self.viewport().update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if self.current_tool == "knife" and self.knife_line:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            pen = QPen(QColor(239, 68, 68, 200), 2.5, Qt.DashLine) # Red dash for cut line
            painter.setPen(pen)
            painter.drawLine(self.knife_line[0], self.knife_line[1])
            painter.restore()
        
    def contextMenuEvent(self, event):
        scene_pos = self.mapToScene(event.pos())
        item = self.scene().itemAt(scene_pos, self.transform())
        
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: #18181b; color: #fafafa; border: 1px solid #27272a; border-radius: 4px; padding: 4px; } QMenu::item:selected { background-color: #2563eb; }")
        
        node_item = None
        if item:
            curr = item
            while curr and not isinstance(curr, VFXNodeItem):
                curr = curr.parentItem()
            if isinstance(curr, VFXNodeItem):
                node_item = curr
                
        if node_item:
            # Assure the item is selected so delete action works correctly
            if not node_item.isSelected():
                self.scene().clearSelection()
                node_item.setSelected(True)
                
            action_del = menu.addAction("🗑 Delete Node")
            action_disable = menu.addAction("⏻ Enable Node" if getattr(node_item, 'is_disabled', False) else "⏻ Bypass/Disable Node")
            action_freeze = menu.addAction("❄ Unfreeze Node" if getattr(node_item, 'is_frozen', False) else "❄ Freeze/Cache Node")
            menu.addSeparator()
            action_queue = menu.addAction("▶ Add to Render Queue")
            
            action = menu.exec(event.globalPos())
            if action == action_del:
                self.scene().delete_selected_nodes()
            elif action == action_disable:
                node_item.toggle_disable()
            elif action == action_freeze:
                node_item.toggle_freeze()
            elif action == action_queue:
                self.scene().signals.queueNodeRequested.emit(node_item)
        else:
            # Empty graph area clicked - show Add Node categorized list
            from utvfx.core.data_model import NODES_REGISTRY
            categories = {}
            for p_type, p_def in NODES_REGISTRY.items():
                cat = p_def.get("category", "Other")
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append((p_type, p_def))
                
            add_menu = menu.addMenu("➕ Add Node")
            
            action_backdrop = menu.addAction("⬜ Add Backdrop")
            
            for cat, nodes in categories.items():
                cat_menu = add_menu.addMenu(cat)
                for p_type, p_def in nodes:
                    act = cat_menu.addAction(p_def["name"])
                    act.triggered.connect(lambda checked=False, pt=p_type: self.scene().parent().add_node_requested.emit(pt, {}))
            
            action = menu.exec(event.globalPos())
            if action == action_backdrop:
                backdrop = BackdropNodeItem()
                backdrop.setPos(scene_pos)
                self.scene().addItem(backdrop)
        
    def wheelEvent(self, event):
        # Zoom support
        zoom_in_factor = 1.15
        zoom_out_factor = 1 / zoom_in_factor
        
        current_scale = self.transform().m11()
        
        if event.angleDelta().y() > 0:
            if current_scale > 5.0: return
            zoom_factor = zoom_in_factor
        else:
            if current_scale < 0.2: return
            zoom_factor = zoom_out_factor
            
        self.scale(zoom_factor, zoom_factor)

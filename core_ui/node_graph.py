import math
from PySide6.QtWidgets import (
    QGraphicsObject, QGraphicsPathItem, QGraphicsScene, QGraphicsView,
    QGraphicsItem, QGraphicsTextItem, QGraphicsDropShadowEffect, QWidget, QMenu
)
from PySide6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QFont, QLinearGradient, QRadialGradient, QPainter, QPolygonF, QShortcut, QKeySequence
)
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QObject

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
        
        is_hovered = self.isUnderMouse()
        width = 3.5 if is_hovered else 2.2
        
        if is_hovered:
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
        if self.is_disabled:
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
        elif self.is_hovered:
            border_pen = QPen(NODE_BORDER_HOVER, 1.2)
        else:
            border_pen = QPen(NODE_BORDER, 1.0)
            
        painter.setPen(border_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(body_path)
        
        painter.restore()

    def toggle_disable(self):
        self.is_disabled = not self.is_disabled
        self.update()

    def to_dict(self):
        return {
            "node_id": self.node_id,
            "name": self.name,
            "plugin_type": self.plugin_type,
            "color": self.accent_color.name(),
            "x": self.pos().x(),
            "y": self.pos().y(),
            "params": getattr(self, "params", {})
        }

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            # Update connections while dragging
            for port in self.inputs + self.outputs:
                port.update_connections()
        return super().itemChange(change, value)


class NodeScene(QGraphicsScene):
    """The graph canvas scene."""
    
    # We use a custom QObject to emit signals from the scene
    class Signals(QObject):
        nodeSelected = Signal(object) # Emits the selected VFXNodeItem or None
        queueNodeRequested = Signal(object) # Emits the node to add to the render queue
    
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
        
        self.shortcut_disable = QShortcut(QKeySequence("D"), self.parent() if self.parent() else None)
        self.shortcut_disable.activated.connect(self.toggle_selected_nodes_disable)

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
                        from core_ui.commands import ConnectCommand
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
                    
            # Cleanup temp
            if self.temp_connection:
                self.removeItem(self.temp_connection)
                self.temp_connection = None
                
            event.accept()
            return
            
        super().mouseReleaseEvent(event)
        
        # Check if nodes moved and push to undo stack
        if self.undo_stack:
            from core_ui.commands import MoveNodeCommand
            for node in self.selectedItems():
                if isinstance(node, VFXNodeItem) and hasattr(node, "old_pos") and node.old_pos is not None:
                    if node.old_pos != node.pos():
                        cmd = MoveNodeCommand(node, node.old_pos, node.pos())
                        self.undo_stack.push(cmd)
                    node.old_pos = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace:
            if self.undo_stack:
                from core_ui.commands import DeleteNodeCommand
                for item in list(self.selectedItems()):
                    if isinstance(item, VFXNodeItem):
                        cmd = DeleteNodeCommand(self, item)
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
        from core_ui.data_model import NODES_REGISTRY
        
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


class MinimapView(QGraphicsView):
    def __init__(self, main_view, parent=None):
        super().__init__(main_view.scene(), parent)
        self.main_view = main_view
        self.setRenderHint(QPainter.Antialiasing)
        self.setInteractive(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("background-color: rgba(15, 15, 18, 220); border: 1px solid #27272a; border-radius: 4px;")
        
        # Update minimap when main view pans
        self.main_view.horizontalScrollBar().valueChanged.connect(self.viewport().update)
        self.main_view.verticalScrollBar().valueChanged.connect(self.viewport().update)

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        
        main_rect = self.main_view.mapToScene(self.main_view.viewport().rect()).boundingRect()
        
        # The line thickness needs to be invariant to the scale, but we are drawing in scene coordinates
        # We'll calculate a pen width that looks like ~2px on screen
        current_scale = self.transform().m11()
        pen_width = max(1.0, 2.0 / current_scale) if current_scale > 0 else 2.0
        
        painter.setPen(QPen(QColor(59, 130, 246), pen_width))
        painter.setBrush(QColor(59, 130, 246, 40))
        painter.drawRect(main_rect)


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
        
        # Styling
        self.setStyleSheet("border: none; background-color: #09090b;")
        
        # Minimap
        self.minimap = MinimapView(self, self)
        self.minimap.setFixedSize(220, 160)
        
    def resizeEvent(self, event):
        super().resizeEvent(event)
        margin = 20
        self.minimap.move(self.width() - self.minimap.width() - margin, 
                          self.height() - self.minimap.height() - margin)
        self.update_minimap()
        
    def update_minimap(self):
        if self.scene():
            items_rect = self.scene().itemsBoundingRect()
            # If graph is empty, use a default rect
            if items_rect.isEmpty():
                items_rect = QRectF(0, 0, 1000, 1000)
            else:
                # Add margin to the bounding rect
                items_rect.adjust(-100, -100, 100, 100)
            
            self.minimap.fitInView(items_rect, Qt.KeepAspectRatio)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and event.modifiers() == Qt.AltModifier):
            self._pan = True
            self._panStartX = event.x()
            self._panStartY = event.y()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pan:
            self._pan = False
            self.setCursor(Qt.ArrowCursor)
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
        super().mouseMoveEvent(event)
        
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
            menu.addSeparator()
            action_queue = menu.addAction("▶ Add to Render Queue")
            
            action = menu.exec(event.globalPos())
            if action == action_del:
                self.scene().delete_selected_nodes()
            elif action == action_disable:
                node_item.toggle_disable()
            elif action == action_queue:
                self.scene().signals.queueNodeRequested.emit(node_item)
        else:
            # Empty graph area clicked - show Add Node categorized list
            from core_ui.data_model import NODES_REGISTRY
            categories = {}
            for p_type, p_def in NODES_REGISTRY.items():
                cat = p_def.get("category", "Other")
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append((p_type, p_def))
                
            add_menu = menu.addMenu("➕ Add Node")
            
            for cat, nodes in categories.items():
                cat_menu = add_menu.addMenu(cat)
                for p_type, p_def in nodes:
                    act = cat_menu.addAction(p_def["name"])
                    act.triggered.connect(lambda checked=False, pt=p_type: self.scene().parent().add_node_requested.emit(pt, {}))
            
            menu.exec(event.globalPos())
        
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
        self.minimap.viewport().update()
        self.update_minimap()

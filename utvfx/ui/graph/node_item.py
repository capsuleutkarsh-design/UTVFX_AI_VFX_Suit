from PySide6.QtWidgets import QGraphicsObject, QGraphicsItem, QGraphicsDropShadowEffect
from PySide6.QtGui import QPen, QBrush, QColor, QPainterPath, QFont, QLinearGradient, QRadialGradient, QPainter
from PySide6.QtCore import Qt, QRectF, QPointF

from utvfx.ui.graph.port import PortItem

NODE_BORDER = QColor(63, 63, 70, 120)  # Zinc-700 with high transparency
NODE_BORDER_HOVER = QColor(161, 161, 170, 180)  # Zinc-400 highlight on hover

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

    def paint(self, painter, option, widget=None):
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
        if self.is_error:
            title_font.setItalic(True)
            self.name_display = self.name + " ⚠ (Error)"
        elif getattr(self, "is_frozen", False):
            title_font.setItalic(True)
            self.name_display = self.name + " ❄ (Frozen)"
        elif self.is_disabled:
            title_font.setItalic(True)
            self.name_display = self.name + " (Bypassed)"
        elif self.is_cached:
            title_font.setItalic(True)
            self.name_display = self.name + " ✓ (Cached)"
        else:
            self.name_display = self.name
            
        painter.setFont(title_font)
        painter.setPen(QPen(QColor("#ffffff")))
        painter.drawText(14, 33, self.name_display)
        
        # 9. Outer Border Outline
        if self.is_error:
            border_pen = QPen(QColor(239, 68, 68, 255), 2.5) # Red error border
            self.shadow.setColor(QColor(239, 68, 68, 120))
        elif self.isSelected():
            border_pen = QPen(self.accent_color.lighter(110), 2.0)
        elif self.is_executing:
            # Pulsing border when executing
            border_pen = QPen(QColor(self.accent_color.red(), self.accent_color.green(), self.accent_color.blue(), 255), 2.5)
        elif self.is_cached:
            border_pen = QPen(QColor(56, 189, 248, 180), 1.5) # Light blue cached border
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
        if executing:
            self.is_error = False
            self.is_cached = False
            self.error_message = ""
        self.update()

        self.is_frozen = False
        
    def set_error_state(self, is_error, message=""):
        self.is_error = is_error
        self.error_message = message
        if is_error:
            self.is_executing = False
        self.update()
        
    def set_cached_state(self):
        self.is_cached = True
        self.is_executing = False
        self.is_error = False
        self.update()
        
        # Flash the shadow
        self.shadow.setColor(QColor(56, 189, 248, 150))
        
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

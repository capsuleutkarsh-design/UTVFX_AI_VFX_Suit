from PySide6.QtWidgets import (
    QGraphicsView, QWidget, QMenu, QLineEdit, QListWidget, QVBoxLayout
)
from PySide6.QtGui import (
    QPen, QBrush, QColor, QPainter, QPainterPathStroker
)
from PySide6.QtCore import Qt, QRectF, QPointF, Signal

from utvfx.ui.graph.node_item import VFXNodeItem

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
        self._context_start_port = None
        
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
            from PySide6.QtGui import QPainterPath
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
                from utvfx.ui.graph.node_item import BackdropNodeItem
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

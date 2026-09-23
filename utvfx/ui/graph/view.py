from PySide6.QtWidgets import (
    QGraphicsView, QWidget, QMenu, QLineEdit, QListWidget, QVBoxLayout, QFrame
)
from PySide6.QtGui import (
    QPen, QPainter, QPainterPathStroker
)
from PySide6.QtCore import Qt, QRectF, QPointF, Signal

from utvfx.ui import icons, theme
from utvfx.ui.graph.node_item import VFXNodeItem

class NodeSearchMenu(QWidget):
    node_selected = Signal(str) # Emits plugin_type

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("Panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(4)
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search nodes")
        self.search_bar.addAction(icons.icon("search", theme.TEXT_DIM), QLineEdit.LeadingPosition)
        self.layout.addWidget(self.search_bar)
        
        self.list_widget = QListWidget()
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
                item = QListWidgetItem(icons.category_icon(ptype), pdef["name"])
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
        # Set by the main window: spawn_callback(plugin_type, override_pos=(x, y)) -> new node.
        self.spawn_callback = None

        from PySide6.QtGui import QShortcut, QKeySequence
        self.shortcut_disable = QShortcut(QKeySequence("D"), self)
        self.shortcut_disable.activated.connect(self.scene().toggle_selected_nodes_disable)
        
        # Styling: the scene paints the background; no frame around the view
        self.setFrameShape(QFrame.NoFrame)
        
    def _spawn(self, plugin_type, scene_pos=None):
        if self.spawn_callback is None:
            return None
        pos = (scene_pos.x(), scene_pos.y()) if scene_pos is not None else None
        return self.spawn_callback(plugin_type, override_pos=pos)

    def _on_search_node_selected(self, plugin_type):
        start_port, self._context_start_port = self._context_start_port, None
        stack = self.scene().undo_stack
        if start_port is not None and stack is not None:
            stack.beginMacro("Add and connect node")  # one undo step for both
        try:
            new_node = self._spawn(plugin_type, self._last_search_pos)
            if new_node is not None and start_port is not None:
                self._connect_context_node(start_port, new_node)
        finally:
            if start_port is not None and stack is not None:
                stack.endMacro()

    def _connect_context_node(self, start_port, new_node):
        # Determine port to connect to
        target_port = None
        if start_port.is_output and new_node.inputs:
            target_port = new_node.inputs[0]
        elif not start_port.is_output and new_node.outputs:
            target_port = new_node.outputs[0]
            
        if target_port:
            from utvfx.core.commands import ConnectCommand, would_create_cycle
            out_p = start_port if start_port.is_output else target_port
            in_p = target_port if start_port.is_output else start_port
            if would_create_cycle(out_p.node, in_p.node):
                return
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
            pen = QPen(theme.qcolor(theme.ERROR), 1.5, Qt.DashLine)  # knife cut line
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawLine(self.knife_line[0], self.knife_line[1])
            painter.restore()
        
    def contextMenuEvent(self, event):
        scene_pos = self.mapToScene(event.pos())
        item = self.scene().itemAt(scene_pos, self.transform())
        
        menu = QMenu(self)
        
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
                
            action_del = menu.addAction(icons.icon("trash"), "Delete node")
            action_disable = menu.addAction(icons.icon("bypass"), "Enable node" if getattr(node_item, 'is_disabled', False) else "Bypass node")
            action_freeze = menu.addAction(icons.icon("freeze"), "Unfreeze node" if getattr(node_item, 'is_frozen', False) else "Freeze node")
            menu.addSeparator()
            action_queue = menu.addAction(icons.icon("queue"), "Add to render queue")
            
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
                
            add_menu = menu.addMenu(icons.icon("plus"), "Add node")
            
            action_backdrop = menu.addAction(icons.icon("box"), "Add backdrop")
            
            for cat, nodes in categories.items():
                cat_menu = add_menu.addMenu(cat)
                for p_type, p_def in nodes:
                    act = cat_menu.addAction(icons.category_icon(p_type), p_def["name"])
                    act.triggered.connect(lambda checked=False, pt=p_type, sp=scene_pos: self._spawn(pt, sp))
            
            action = menu.exec(event.globalPos())
            if action == action_backdrop:
                from utvfx.core.commands import AddBackdropCommand
                data = {"x": scene_pos.x(), "y": scene_pos.y()}
                if self.scene().undo_stack is not None:
                    self.scene().undo_stack.push(AddBackdropCommand(self.scene(), data))
                else:
                    self.scene().add_backdrop(data)
        
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

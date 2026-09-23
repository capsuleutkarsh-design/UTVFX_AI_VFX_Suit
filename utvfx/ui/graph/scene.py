from PySide6.QtWidgets import QGraphicsScene
from PySide6.QtGui import QPen, QBrush, QColor, QPolygonF
from PySide6.QtCore import Qt, QPointF, Signal, QObject, QRectF

from utvfx.ui.graph.node_item import VFXNodeItem, DotNodeItem, BackdropNodeItem
from utvfx.ui.graph.connection import ConnectionItem
from utvfx.ui.graph.port import PortItem
from utvfx.ui.graph.constants import BG_COLOR, GRID_COLOR, GRID_SIZE


def restore_params(params):
    """Undo what JSON does to node params: click keyframes are keyed by timeline position (int)."""
    # Older projects stored the timeline In/Out in every node; it is engine state now.
    params.pop("start_frame", None)
    params.pop("end_frame", None)
    for layer in params.get("mask_layers", []) or []:
        keyframes = layer.get("keyframes")
        if isinstance(keyframes, dict):
            layer["keyframes"] = {int(k): v for k, v in keyframes.items()}
    return params


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
        self.backdrops = []
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
        painter.fillRect(rect, BG_COLOR)

        # Quiet dot grid; skipped when zoomed far out so it does not turn to noise
        view = self.views()[0] if self.views() else None
        if view is not None and view.transform().m11() < 0.35:
            return
        step = GRID_SIZE
        left = int(rect.left()) - (int(rect.left()) % step)
        top = int(rect.top()) - (int(rect.top()) % step)

        pen = QPen(GRID_COLOR, 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        points = QPolygonF()
        for x in range(left, int(rect.right()) + 1, step):
            for y in range(top, int(rect.bottom()) + 1, step):
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
            if isinstance(node, (VFXNodeItem, DotNodeItem)):
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

                    from utvfx.core.commands import would_create_cycle
                    if would_create_cycle(out_port.node, in_port.node):
                        pass  # a loop would make the graph impossible to render
                    elif self.undo_stack:
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
            from utvfx.core.commands import MoveNodeCommand, DisconnectCommand, ConnectCommand, would_create_cycle
            moved = [n for n in self.selectedItems()
                     if isinstance(n, (VFXNodeItem, DotNodeItem)) and getattr(n, "old_pos", None) is not None
                     and n.old_pos != n.pos()]
            if moved:
                self.undo_stack.beginMacro("Move nodes" if len(moved) > 1 else "Move node")
            for node in self.selectedItems():
                if isinstance(node, (VFXNodeItem, DotNodeItem)) and hasattr(node, "old_pos") and node.old_pos is not None:
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
                                        if (out_port and in_port
                                                and not would_create_cycle(out_port.node, node)
                                                and not would_create_cycle(node, in_port.node)):
                                            # Push commands
                                            self.undo_stack.push(DisconnectCommand(self, conn))
                                            self.undo_stack.push(ConnectCommand(self, out_port, node.inputs[0]))
                                            self.undo_stack.push(ConnectCommand(self, node.outputs[0], in_port))
                                            break
                                            
                        cmd = MoveNodeCommand(node, node.old_pos, node.pos())
                        self.undo_stack.push(cmd)
                    node.old_pos = None
            if moved:
                self.undo_stack.endMacro()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace:
            if self.undo_stack:
                self.delete_selected_nodes()
            else:
                for item in list(self.selectedItems()):
                    if isinstance(item, VFXNodeItem):
                        for port in item.inputs + item.outputs:
                            for conn in list(port.connections):
                                if conn in self.connections:
                                    self.connections.remove(conn)
                                else:
                                    # Fallback removal
                                    pass
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

    def delete_selected_nodes(self):
        """Helper to delete selected nodes from context menu etc."""
        if self.undo_stack:
            from utvfx.core.commands import DeleteBackdropCommand, DeleteNodeCommand, DisconnectCommand
            items = list(self.selectedItems())
            if not items:
                return
            # Wires first, then nodes, all as one undo step.
            self.undo_stack.beginMacro("Delete")
            for item in items:
                if isinstance(item, ConnectionItem) and item in self.connections:
                    self.undo_stack.push(DisconnectCommand(self, item))
            for item in items:
                if isinstance(item, (VFXNodeItem, DotNodeItem)) and item in self.nodes:
                    self.undo_stack.push(DeleteNodeCommand(self, item))
                elif isinstance(item, BackdropNodeItem) and item in self.backdrops:
                    self.undo_stack.push(DeleteBackdropCommand(self, item))
            self.undo_stack.endMacro()
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
            "connections": connections_data,
            "backdrops": [b.to_dict() for b in self.backdrops],
        }

    def add_backdrop(self, data):
        import uuid
        item = BackdropNodeItem(data.get("name", "Backdrop"))
        item.backdrop_id = data.get("backdrop_id") or str(uuid.uuid4())
        item.width = data.get("width", item.width)
        item.height = data.get("height", item.height)
        item.setPos(data.get("x", 0), data.get("y", 0))
        self.addItem(item)
        self.backdrops.append(item)
        return item

    def remove_backdrop(self, item):
        if item in self.backdrops:
            self.backdrops.remove(item)
        self.removeItem(item)
        
    def from_dict(self, data):
        from utvfx.core.data_model import NODES_REGISTRY
        
        self.signals.nodeSelected.emit(None)
        
        # Clear existing
        for conn in list(self.connections):
            self.removeItem(conn)
        for node in list(self.nodes):
            self.removeItem(node)
        for backdrop in list(self.backdrops):
            self.removeItem(backdrop)
        self.connections.clear()
        self.nodes.clear()
        self.backdrops.clear()
        for b_data in data.get("backdrops", []):
            self.add_backdrop(b_data)
        
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
            node.params = restore_params(n_data.get("params", {}))
            node.is_disabled = n_data.get("disabled", False)
            node.is_frozen = n_data.get("frozen", False)
            
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

from PySide6.QtGui import QUndoCommand, QUndoStack
from PySide6.QtCore import QPointF

def create_undo_stack(parent):
    stack = QUndoStack(parent)
    return stack

class AddNodeCommand(QUndoCommand):
    def __init__(self, scene, node_data, description="Add Node"):
        super().__init__(description)
        self.scene = scene
        self.node_data = node_data
        self.node_id = node_data.get("node_id")
        self.node = None

    def redo(self):
        # We need to add the node to the scene
        from core_ui.data_model import NODES_REGISTRY
        ptype = self.node_data["plugin_type"]
        registry_def = NODES_REGISTRY.get(ptype, {})
        inps = registry_def.get("inputs", [])
        outs = registry_def.get("outputs", [])
        
        self.node = self.scene.add_node(
            name=self.node_data.get("name", "Unknown"),
            plugin_type=ptype,
            inputs=inps,
            outputs=outs,
            color=self.node_data.get("color", "#f59e0b"),
            pos=(self.node_data.get("x", 0), self.node_data.get("y", 0)),
            node_id=self.node_id
        )
        self.node.params = self.node_data.get("params", {})

    def undo(self):
        if self.node:
            self.scene.removeItem(self.node)
            self.scene.nodes.remove(self.node)
            # Remove connections to this node
            for port in self.node.inputs + self.node.outputs:
                for conn in list(port.connections):
                    if conn in self.scene.connections:
                        self.scene.connections.remove(conn)
                    conn.port1.remove_connection(conn)
                    if conn.port2:
                        conn.port2.remove_connection(conn)
                    self.scene.removeItem(conn)
            self.node = None

class MoveNodeCommand(QUndoCommand):
    def __init__(self, node, old_pos, new_pos, description="Move Node"):
        super().__init__(description)
        self.node = node
        self.old_pos = old_pos
        self.new_pos = new_pos

    def redo(self):
        self.node.setPos(self.new_pos)

    def undo(self):
        self.node.setPos(self.old_pos)

class ConnectCommand(QUndoCommand):
    def __init__(self, scene, src_port, dst_port, description="Connect Nodes"):
        super().__init__(description)
        self.scene = scene
        self.src_port = src_port
        self.dst_port = dst_port
        self.conn = None
        self.replaced_conns = []

    def redo(self):
        from core_ui.node_graph import ConnectionItem
        # Disconnect any existing connection on the dst_port
        for existing_conn in list(self.dst_port.connections):
            if existing_conn in self.scene.connections:
                self.scene.connections.remove(existing_conn)
            existing_conn.port1.remove_connection(existing_conn)
            if existing_conn.port2:
                existing_conn.port2.remove_connection(existing_conn)
            self.scene.removeItem(existing_conn)
            self.replaced_conns.append(existing_conn)
            
        self.conn = ConnectionItem(self.src_port, self.dst_port)
        self.src_port.add_connection(self.conn)
        self.dst_port.add_connection(self.conn)
        self.scene.addItem(self.conn)
        self.scene.connections.append(self.conn)

    def undo(self):
        if self.conn:
            if self.conn in self.scene.connections:
                self.scene.connections.remove(self.conn)
            self.conn.port1.remove_connection(self.conn)
            self.conn.port2.remove_connection(self.conn)
            self.scene.removeItem(self.conn)
            self.conn = None
            
        # Restore replaced connections
        for old_conn in self.replaced_conns:
            old_conn.port1.add_connection(old_conn)
            old_conn.port2.add_connection(old_conn)
            self.scene.addItem(old_conn)
            self.scene.connections.append(old_conn)
        self.replaced_conns.clear()

class DeleteNodeCommand(QUndoCommand):
    def __init__(self, scene, node, description="Delete Node"):
        super().__init__(description)
        self.scene = scene
        self.node_data = node.to_dict()
        self.node_id = self.node_data["node_id"]
        # Save connections so we can restore them
        self.saved_connections = []
        visited_conns = set()
        for port in node.inputs + node.outputs:
            for conn in port.connections:
                if conn in visited_conns: continue
                visited_conns.add(conn)
                src_node = conn.port1.node
                dst_node = conn.port2.node
                src_port_name = conn.port1.name
                dst_port_name = conn.port2.name
                self.saved_connections.append({
                    "src_node_id": src_node.node_id,
                    "src_port_name": src_port_name,
                    "dst_node_id": dst_node.node_id,
                    "dst_port_name": dst_port_name
                })
        self.node = node

    def redo(self):
        # Remove the node
        n = next((n for n in self.scene.nodes if n.node_id == self.node_id), None)
        if n:
            # Check if background worker is running and cancel it
            window = self.scene.views()[0].window()
            if hasattr(window, "execution_engine"):
                if self.node_id in window.execution_engine.active_workers:
                    worker = window.execution_engine.active_workers[self.node_id]
                    if hasattr(worker, 'cancel'):
                        worker.cancel()
                    elif hasattr(worker, 'is_cancelled'):
                        worker.is_cancelled = True

            # Check if this node is currently selected
            is_selected = n.isSelected()
            
            for port in n.inputs + n.outputs:
                for conn in list(port.connections):
                    if conn in self.scene.connections:
                        self.scene.connections.remove(conn)
                    conn.port1.remove_connection(conn)
                    if conn.port2:
                        conn.port2.remove_connection(conn)
                    self.scene.removeItem(conn)
            self.scene.removeItem(n)
            self.scene.nodes.remove(n)
            
            if is_selected:
                self.scene.signals.nodeSelected.emit(None)

    def undo(self):
        from core_ui.data_model import NODES_REGISTRY
        from core_ui.node_graph import ConnectionItem
        
        ptype = self.node_data["plugin_type"]
        registry_def = NODES_REGISTRY.get(ptype, {})
        inps = registry_def.get("inputs", [])
        outs = registry_def.get("outputs", [])
        
        n = self.scene.add_node(
            name=self.node_data.get("name", "Unknown"),
            plugin_type=ptype,
            inputs=inps,
            outputs=outs,
            color=self.node_data.get("color", "#f59e0b"),
            pos=(self.node_data.get("x", 0), self.node_data.get("y", 0)),
            node_id=self.node_id
        )
        n.params = self.node_data.get("params", {})
        
        for cdata in self.saved_connections:
            src = next((x for x in self.scene.nodes if x.node_id == cdata["src_node_id"]), None)
            dst = next((x for x in self.scene.nodes if x.node_id == cdata["dst_node_id"]), None)
            if src and dst:
                try:
                    src_port = next((p for p in src.outputs if p.name == cdata["src_port_name"]), None)
                    dst_port = next((p for p in dst.inputs if p.name == cdata["dst_port_name"]), None)
                    if src_port and dst_port:
                        conn = ConnectionItem(src_port, dst_port)
                        src_port.add_connection(conn)
                        dst_port.add_connection(conn)
                        self.scene.addItem(conn)
                        self.scene.connections.append(conn)
                except Exception as e:
                    print(f"Warning: Failed to restore connection for {src.name} to {dst.name}. Error: {e}")

class ChangeParamCommand(QUndoCommand):
    def __init__(self, node, param_id, old_val, new_val, description="Change Parameter"):
        super().__init__(description)
        self.node = node
        self.param_id = param_id
        self.old_val = old_val
        self.new_val = new_val

    def redo(self):
        if not hasattr(self.node, "params"):
            self.node.params = {}
        self.node.params[self.param_id] = self.new_val

    def undo(self):
        if not hasattr(self.node, "params"):
            self.node.params = {}
        self.node.params[self.param_id] = self.old_val

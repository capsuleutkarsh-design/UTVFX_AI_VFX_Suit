"""Undo commands for the node graph.

Commands never keep references to node, port or wire objects: undoing a delete
recreates the node as a new object, so any stored reference would go stale.
They store node ids and port names instead and look the objects up each time
they run.
"""
import uuid

from PySide6.QtGui import QUndoCommand, QUndoStack


def create_undo_stack(parent):
    stack = QUndoStack(parent)
    return stack


def _node(scene, node_id):
    return next((n for n in scene.nodes if n.node_id == node_id), None)


def _port(scene, node_id, port_name, output):
    node = _node(scene, node_id)
    if node is None:
        return None
    ports = node.outputs if output else node.inputs
    return next((p for p in ports if p.name == port_name), None)


def _wire_key(conn):
    return (conn.port1.node.node_id, conn.port1.name, conn.port2.node.node_id, conn.port2.name)


def _find_wire(scene, key):
    return next((c for c in scene.connections if c.port2 is not None and _wire_key(c) == key), None)


def _remove_wire(scene, conn):
    if conn in scene.connections:
        scene.connections.remove(conn)
    conn.port1.remove_connection(conn)
    if conn.port2:
        conn.port2.remove_connection(conn)
    scene.removeItem(conn)


def _add_wire(scene, key):
    from utvfx.ui.node_graph import ConnectionItem
    src = _port(scene, key[0], key[1], output=True)
    dst = _port(scene, key[2], key[3], output=False)
    if src is None or dst is None or _find_wire(scene, key):
        return None
    conn = ConnectionItem(src, dst)
    src.add_connection(conn)
    dst.add_connection(conn)
    scene.addItem(conn)
    scene.connections.append(conn)
    return conn


def _wires_of(node):
    keys = []
    for port in node.inputs + node.outputs:
        for conn in port.connections:
            if conn.port2 is not None and _wire_key(conn) not in keys:
                keys.append(_wire_key(conn))
    return keys


def _create_node(scene, data):
    from utvfx.core.data_model import NODES_REGISTRY
    ptype = data["plugin_type"]
    registry_def = NODES_REGISTRY.get(ptype, {})
    node = scene.add_node(
        name=data.get("name", "Unknown"),
        plugin_type=ptype,
        inputs=registry_def.get("inputs", []),
        outputs=registry_def.get("outputs", []),
        color=data.get("color", "#f59e0b"),
        pos=(data.get("x", 0), data.get("y", 0)),
        node_id=data["node_id"],
    )
    node.params = data.get("params", {})
    node.is_disabled = data.get("disabled", False)
    node.is_frozen = data.get("frozen", False)
    return node


def _remove_node(scene, node):
    for key in _wires_of(node):
        conn = _find_wire(scene, key)
        if conn:
            _remove_wire(scene, conn)
    was_selected = node.isSelected()
    scene.removeItem(node)
    scene.nodes.remove(node)
    if was_selected:
        scene.signals.nodeSelected.emit(None)


class AddNodeCommand(QUndoCommand):
    def __init__(self, scene, node_data, description="Add Node"):
        super().__init__(description)
        self.scene = scene
        self.node_data = dict(node_data)
        self.node_data.setdefault("node_id", str(uuid.uuid4()))
        self.node_id = self.node_data["node_id"]

    @property
    def node(self):
        return _node(self.scene, self.node_id)

    def redo(self):
        if self.node is None:
            _create_node(self.scene, self.node_data)

    def undo(self):
        node = self.node
        if node is not None:
            self.node_data = node.to_dict()  # keep edits made since it was added
            _remove_node(self.scene, node)


class MoveNodeCommand(QUndoCommand):
    def __init__(self, node, old_pos, new_pos, description="Move Node"):
        super().__init__(description)
        self.scene = node.scene()
        self.node_id = node.node_id
        self.old_pos = old_pos
        self.new_pos = new_pos

    def _set(self, pos):
        node = _node(self.scene, self.node_id)
        if node is not None:
            node.setPos(pos)

    def redo(self):
        self._set(self.new_pos)

    def undo(self):
        self._set(self.old_pos)


class ConnectCommand(QUndoCommand):
    def __init__(self, scene, src_port, dst_port, description="Connect Nodes"):
        super().__init__(description)
        self.scene = scene
        self.key = (src_port.node.node_id, src_port.name, dst_port.node.node_id, dst_port.name)
        self.replaced = [_wire_key(c) for c in dst_port.connections if c.port2 is not None]

    def redo(self):
        # An input takes one wire, so connecting replaces whatever was there.
        for key in self.replaced:
            conn = _find_wire(self.scene, key)
            if conn:
                _remove_wire(self.scene, conn)
        _add_wire(self.scene, self.key)

    def undo(self):
        conn = _find_wire(self.scene, self.key)
        if conn:
            _remove_wire(self.scene, conn)
        for key in self.replaced:
            _add_wire(self.scene, key)


class DisconnectCommand(QUndoCommand):
    def __init__(self, scene, connection, description="Disconnect Nodes"):
        super().__init__(description)
        self.scene = scene
        self.key = _wire_key(connection)

    def redo(self):
        conn = _find_wire(self.scene, self.key)
        if conn:
            _remove_wire(self.scene, conn)

    def undo(self):
        _add_wire(self.scene, self.key)


class DeleteNodeCommand(QUndoCommand):
    def __init__(self, scene, node, description="Delete Node"):
        super().__init__(description)
        self.scene = scene
        self.node_data = node.to_dict()
        self.node_id = self.node_data["node_id"]
        self.wires = _wires_of(node)

    def redo(self):
        node = _node(self.scene, self.node_id)
        if node is None:
            return
        views = self.scene.views()
        window = views[0].window() if views else None
        engine = getattr(window, "execution_engine", None)
        worker = engine.active_workers.get(self.node_id) if engine else None
        if worker is not None:
            if hasattr(worker, "cancel"):
                worker.cancel()
            else:
                worker.is_cancelled = True
        self.node_data = node.to_dict()
        self.wires = _wires_of(node)
        _remove_node(self.scene, node)

    def undo(self):
        if _node(self.scene, self.node_id) is None:
            _create_node(self.scene, self.node_data)
        for key in self.wires:
            _add_wire(self.scene, key)


class ChangeParamCommand(QUndoCommand):
    def __init__(self, node, param_id, old_val, new_val, description="Change Parameter"):
        super().__init__(description)
        self.scene = node.scene()
        self.node_id = node.node_id
        self._fallback = node  # nodes that are not in a scene (tests, previews)
        self.param_id = param_id
        self.old_val = old_val
        self.new_val = new_val

    def _set(self, value):
        node = _node(self.scene, self.node_id) if self.scene is not None else self._fallback
        if node is None:
            return
        if not hasattr(node, "params"):
            node.params = {}
        node.params[self.param_id] = value

    def redo(self):
        self._set(self.new_val)

    def undo(self):
        self._set(self.old_val)

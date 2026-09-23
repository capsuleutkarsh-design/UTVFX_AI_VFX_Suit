"""Graph editing: loops are refused, deletes are one undo step, backdrops save and undo."""
import json

import pytest
from PySide6.QtGui import QUndoStack

from utvfx.core.commands import AddBackdropCommand, ConnectCommand, would_create_cycle


@pytest.fixture
def graph(node_scene):
    from utvfx.core.data_model import NODES_REGISTRY

    node_scene.undo_stack = QUndoStack(node_scene)

    def add(name):
        reg = NODES_REGISTRY["grade"]
        node = node_scene.add_node(name, "grade", reg["inputs"], reg["outputs"])
        node.params = {}
        return node

    return node_scene, add


def test_wiring_a_loop_is_detected(graph):
    scene, add = graph
    a, b, c = add("A"), add("B"), add("C")
    ConnectCommand(scene, a.outputs[0], b.inputs[0]).redo()
    ConnectCommand(scene, b.outputs[0], c.inputs[0]).redo()
    assert would_create_cycle(c, a)       # C -> A closes A -> B -> C
    assert would_create_cycle(a, a)
    assert not would_create_cycle(a, c)


def test_deleting_several_nodes_is_one_undo_step(graph):
    scene, add = graph
    a, b, c = add("A"), add("B"), add("C")
    scene.undo_stack.push(ConnectCommand(scene, a.outputs[0], b.inputs[0]))
    scene.undo_stack.push(ConnectCommand(scene, b.outputs[0], c.inputs[0]))
    a.setSelected(True)
    b.setSelected(True)
    scene.delete_selected_nodes()
    assert [n.name for n in scene.nodes] == ["C"]
    scene.undo_stack.undo()
    assert sorted(n.name for n in scene.nodes) == ["A", "B", "C"]
    assert len(scene.connections) == 2


def test_backdrops_are_saved_loaded_and_undoable(graph):
    scene, add = graph
    scene.undo_stack.push(AddBackdropCommand(scene, {"x": 10, "y": 20, "name": "Keying"}))
    assert len(scene.backdrops) == 1
    scene.backdrops[0].width = 500

    saved = json.loads(json.dumps(scene.to_dict()))
    scene.from_dict(saved)
    assert len(scene.backdrops) == 1
    b = scene.backdrops[0]
    assert (b.name, b.width, b.pos().x(), b.pos().y()) == ("Keying", 500, 10, 20)

    b.setSelected(True)
    scene.delete_selected_nodes()
    assert not scene.backdrops
    scene.undo_stack.undo()
    assert len(scene.backdrops) == 1 and scene.backdrops[0].width == 500

"""ISSUE-H2: node inputs follow their wires instead of guessing from port names."""
import os

import pytest

from utvfx.core.commands import ConnectCommand
from utvfx.core.media_resolver import resolve_input


@pytest.fixture
def graph(node_scene, tmp_path):
    from utvfx.core.data_model import NODES_REGISTRY

    cache = tmp_path / "cache"

    def add(ptype):
        reg = NODES_REGISTRY[ptype]
        return node_scene.add_node(reg["name"], ptype, reg.get("inputs", []), reg.get("outputs", []))

    def wire(src, out_name, dst, in_name):
        out = next(p for p in src.outputs if p.name == out_name)
        inp = next(p for p in dst.inputs if p.name == in_name)
        ConnectCommand(node_scene, out, inp).redo()

    def rendered(node, folder, name="0001.png"):
        path = cache / node.node_id / folder if folder != "." else cache / node.node_id
        path = path.resolve()
        path.mkdir(parents=True, exist_ok=True)
        (path / name).write_bytes(b"x")
        return str(path)

    plate_file = tmp_path / "plate.1001.png"
    plate_file.write_bytes(b"x")
    plate = add("media_plate")
    plate.params = {"plate_file": str(plate_file), "is_sequence": False}
    return add, wire, rendered, plate, str(plate_file), str(cache)


def test_each_output_input_gets_its_own_wire(graph):
    add, wire, rendered, plate, plate_file, cache = graph
    key, depth, out = add("corridor_keyer"), add("ai_depth_estimator"), add("composite_output")
    wire(plate, "Video Plate", key, "Video Plate")
    wire(plate, "Video Plate", depth, "Video Plate")
    wire(key, "Keyed RGBA", out, "Keyed RGBA")
    wire(plate, "Video Plate", out, "Video Plate")
    wire(depth, "Dense Depth Map", out, "Dense Depth Map")
    keyed = rendered(key, "Output/Processed")
    depth_dir = rendered(depth, ".", "depth_00000.png")

    assert resolve_input(out, "Keyed RGBA", cache) == keyed
    assert resolve_input(out, "Video Plate", cache) == plate_file
    assert resolve_input(out, "Dense Depth Map", cache) == depth_dir


def test_matte_input_wired_to_a_keyer_gets_its_matte(graph):
    add, wire, rendered, plate, plate_file, cache = graph
    key, roto = add("corridor_keyer"), add("roto_to_shape")
    wire(key, "Keyed RGBA", roto, "Alpha Matte")
    rendered(key, "Output/Processed")
    matte = rendered(key, "Output/Matte")
    assert resolve_input(roto, "Alpha Matte", cache) == matte


def test_bypassed_node_passes_its_input_through(graph):
    add, wire, rendered, plate, plate_file, cache = graph
    grade, depth = add("grade"), add("ai_depth_estimator")
    wire(plate, "Video Plate", grade, "Image")
    wire(grade, "Image", depth, "Video Plate")
    rendered(grade, ".")
    grade.is_disabled = True
    assert resolve_input(depth, "Video Plate", cache) == plate_file


def test_unwired_depth_input_stays_empty(graph):
    add, wire, rendered, plate, plate_file, cache = graph
    roto = add("roto_to_shape")
    wire(plate, "Video Plate", roto, "Video Plate")
    assert resolve_input(roto, "Depth Map", cache) is None
    assert resolve_input(roto, "Video Plate", cache) == plate_file


def test_hash_file_in_meta_is_not_output(graph):
    add, wire, rendered, plate, plate_file, cache = graph
    from utvfx.core.media_resolver import has_rendered_output, state_hash_path

    grade = add("grade")
    node_cache = os.path.join(cache, grade.node_id)
    os.makedirs(os.path.dirname(state_hash_path(node_cache)))
    open(state_hash_path(node_cache), "w").write("abc")
    assert not has_rendered_output(grade, cache)
    rendered(grade, ".")
    assert has_rendered_output(grade, cache)


def test_graph_menus_add_nodes_and_wire_drop_connects_the_new_one(qtbot):
    """ISSUE-H6: right-click Add Node, Tab search and wire-drop search used to do nothing."""
    from main import VFXCoreWindow

    win = VFXCoreWindow()
    qtbot.addWidget(win)
    view = win.node_view
    plate = win.spawn_node("media_plate", override_pos=(0, 0))
    assert plate is not None and plate in win.node_scene.nodes

    view._spawn("grade", view.mapToScene(10, 10))  # what the right-click menu does
    assert [n.plugin_type for n in win.node_scene.nodes] == ["media_plate", "grade"]

    view._context_start_port = plate.outputs[0]  # a wire dragged from the plate onto empty space
    view._on_search_node_selected("ai_depth_estimator")
    depth = win.node_scene.nodes[-1]
    assert depth.plugin_type == "ai_depth_estimator"
    assert depth.inputs[0].connections and depth.inputs[0].connections[0].port1 is plate.outputs[0]

    win.undo_stack.undo()  # one step removes both the node and its wire
    assert [n.plugin_type for n in win.node_scene.nodes] == ["media_plate", "grade"]
    assert not plate.outputs[0].connections

"""Bugs confirmed by the September 2026 audit (see ISSUES.md).

Each test describes the correct behaviour and is marked xfail until the bug is
fixed. xfail is strict, so a fix makes the test "unexpectedly pass" and fail the
run: remove the marker in the same commit as the fix.
"""
import json
import os
import types

import numpy as np
import pytest


def test_exr_highlights_survive_loading(hdr_exr_sequence):
    """ISSUE-C1: scene-linear reads keep highlights; display reads roll them off instead of clipping."""
    from utvfx.core import colour
    from utvfx.core.image_utils import load_frame

    path = str(hdr_exr_sequence / "shot.1001.exr")
    linear = colour.read_linear(path, "ACEScg")
    assert linear.dtype == np.float32 and linear.max() > 3.9
    display = load_frame(path, "ACEScg")
    assert display[15, 15].max() < 255


@pytest.mark.xfail(reason="ISSUE-C2: camera export writes literal '\\n' instead of line breaks")
def test_nuke_camera_export_has_line_breaks(tmp_path):
    from plugins.CompositeOutput.colmap_exporter import export_to_nuke

    cameras = {1: {"model": "SIMPLE_PINHOLE", "width": 1920, "height": 1080, "params": [1500.0, 960.0, 540.0]}}
    images = {
        1: {"q": (1.0, 0.0, 0.0, 0.0), "t": (0.0, 0.0, 0.0), "camera_id": 1, "name": "frame_001001.jpg"},
        2: {"q": (1.0, 0.0, 0.0, 0.0), "t": (0.1, 0.0, 0.0), "camera_id": 1, "name": "frame_001002.jpg"},
    }
    points = {1: {"xyz": (0.0, 0.0, 5.0), "rgb": (255, 255, 255)}}
    out = tmp_path / "cam.nk"
    export_to_nuke(cameras, images, points, str(out))
    text = out.read_text()
    assert "\\n" not in text
    assert text.count("\n") > 5


@pytest.mark.models
@pytest.mark.xfail(reason="ISSUE-C3: ViTMatte padding is never cropped, so 1080-row plates break")
def test_vitmatte_alpha_matches_plate_size():
    from transformers import VitMatteForImageMatting, VitMatteImageProcessor
    from plugins.SuperMatte.backend import SuperMatteWorker

    model_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "ViTMatte")
    processor = VitMatteImageProcessor.from_pretrained(model_dir)
    model = VitMatteForImageMatting.from_pretrained(model_dir, use_safetensors=True).eval()

    worker = SuperMatteWorker.__new__(SuperMatteWorker)
    worker.params = {}
    h, w = 270, 480  # 270 is not a multiple of 32, like 1080
    frame = np.full((h, w, 3), 128, np.uint8)
    mask = np.zeros((h, w), np.uint8)
    mask[60:200, 150:330] = 255
    alpha = worker.run_vitmatte(frame, mask, False, False, model, processor, None, 5, 5, "cpu")
    assert alpha.shape == (h, w)


def test_add_node_keeps_id_through_undo_redo(node_scene):
    """ISSUE-C5"""
    from utvfx.core.commands import AddNodeCommand

    cmd = AddNodeCommand(node_scene, {"plugin_type": "grade", "name": "Grade"})
    cmd.redo()
    first_id = cmd.node.node_id
    cmd.undo()
    cmd.redo()
    assert cmd.node.node_id == first_id


def test_keyframes_stay_ints_after_save_and_reload(node_scene):
    """ISSUE-C6"""
    node = node_scene.add_node("SuperMatte", "super_matte")
    node.params = {"mask_layers": [{"id": "l1", "keyframes": {5: [[0.5, 0.5, True]]}}]}
    saved = json.loads(json.dumps(node_scene.to_dict()))
    node_scene.from_dict(saved)
    keys = node_scene.nodes[0].params["mask_layers"][0]["keyframes"].keys()
    assert all(isinstance(k, int) for k in keys)


def test_project_with_dot_node_can_be_saved(node_scene):
    """ISSUE-H1"""
    node_scene.add_node("Dot", "dot_node")
    json.dumps(node_scene.to_dict())


def test_hash_file_alone_is_not_rendered_output(tmp_path):
    """ISSUE-H3"""
    from utvfx.core.media_resolver import get_cached_output

    node = types.SimpleNamespace(node_id="abc", plugin_type="grade", params={})
    (tmp_path / "abc").mkdir()
    (tmp_path / "abc" / "last_state_hash.txt").write_text("deadbeef")
    assert get_cached_output(node, cache_dir=str(tmp_path)) is None


def test_undo_after_delete_restores_graph_without_crashing(node_scene):
    """ISSUE-C5: add A and B, connect, delete B, then undo everything (used to segfault)."""
    from PySide6.QtGui import QUndoStack
    from utvfx.core.commands import AddNodeCommand, ConnectCommand, DeleteNodeCommand

    stack = QUndoStack(node_scene)
    node_scene.undo_stack = stack
    stack.push(AddNodeCommand(node_scene, {"plugin_type": "media_plate", "name": "Plate"}))
    stack.push(AddNodeCommand(node_scene, {"plugin_type": "grade", "name": "Grade"}))
    plate, grade = node_scene.nodes
    stack.push(ConnectCommand(node_scene, plate.outputs[0], grade.inputs[0]))
    stack.push(DeleteNodeCommand(node_scene, grade))
    assert len(node_scene.nodes) == 1 and not node_scene.connections

    stack.undo()  # delete
    assert len(node_scene.nodes) == 2 and len(node_scene.connections) == 1
    stack.undo()  # connect
    assert not node_scene.connections
    stack.undo()  # add grade
    stack.undo()  # add plate
    assert not node_scene.nodes

    for _ in range(4):
        stack.redo()
    assert len(node_scene.nodes) == 1 and node_scene.nodes[0].plugin_type == "media_plate"
    stack.undo()
    assert [n.plugin_type for n in node_scene.nodes] == ["media_plate", "grade"]
    assert len(node_scene.connections) == 1

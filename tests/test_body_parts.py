"""Matte to Shape, body-parts mode (formerly AI Roto): parts cover the matte, a limb behind the body
fades and one in front stays, plate frame numbers, depth encodings, old projects upgrade."""
import json
import types

import cv2
import numpy as np
import pytest

from plugins.RotoToShape import body_parts as bp
from plugins.RotoToShape.backend import RotoToShapeWorker
from utvfx.core import exr

FRAMES = range(1001, 1007)
JOINTS = {0: (100, 35), 11: (120, 60), 12: (80, 60), 13: (160, 60), 14: (40, 60), 15: (190, 60), 16: (10, 60),
          23: (115, 120), 24: (85, 120), 25: (115, 160), 26: (85, 160), 27: (115, 195), 28: (85, 195)}


class FakePose:
    """MediaPipe Pose stand-in: the same skeleton on every frame, every joint visible."""

    def __init__(self, **kwargs):
        pass

    def process(self, rgb):
        h, w = rgb.shape[:2]
        marks = [types.SimpleNamespace(x=JOINTS.get(i, (100, 100))[0] / w, y=JOINTS.get(i, (100, 100))[1] / h,
                                       visibility=1.0 if i in JOINTS else 0.0) for i in range(33)]
        return types.SimpleNamespace(pose_landmarks=types.SimpleNamespace(landmark=marks))

    def close(self):
        pass


def stick_figure():
    m = np.zeros((200, 200), np.uint8)
    cv2.fillConvexPoly(m, np.array([JOINTS[11], JOINTS[12], JOINTS[24], JOINTS[23]], np.int32), 255)
    for a, b in ((11, 13), (13, 15), (12, 14), (14, 16), (23, 25), (25, 27), (24, 26), (26, 28)):
        cv2.line(m, JOINTS[a], JOINTS[b], 255, 12)
    cv2.circle(m, JOINTS[0], 18, 255, -1)
    return m


@pytest.fixture
def body(tmp_path, monkeypatch):
    from mediapipe.python.solutions import pose
    monkeypatch.setattr(pose, "Pose", FakePose)
    plate, matte, depth = tmp_path / "plate", tmp_path / "sm" / "Matte", tmp_path / "depth"
    for folder in (plate, matte, depth):
        folder.mkdir(parents=True)
    m = stick_figure()
    near = np.full((200, 200), 0.5, np.float32)
    near[:, 125:] = 0.4   # the arm on the right of the frame is behind the torso
    near[:, :75] = 0.6    # the one on the left is in front of it
    for n in FRAMES:
        cv2.imwrite(str(plate / f"frame_{n:06d}.png"), cv2.cvtColor(m, cv2.COLOR_GRAY2BGR))
        cv2.imwrite(str(matte / f"matte_{n:06d}.png"), m.astype(np.uint16) * 257)
        exr.write(str(depth / f"depth_{n:06d}.exr"), near, ("Z",), half=False,
                  attributes={"contour/depth": "relative, near = 1"})
    return tmp_path


def run(root, frame_range=None, depth=True, **params):
    inputs = {"Video Plate": str(root / "plate"), "Alpha Matte": str(root / "sm" / "Matte")}
    if depth:
        inputs["Depth Map"] = str(root / "depth")
    params = dict({"mode": "Body parts (people)", "temporal_smoothing": False, "edge_snap_radius": 0,
                   "generate_feather": False, "min_area": 20}, **params)
    w = RotoToShapeWorker("r", params, inputs, str(root / "roto"), str(root))
    w.frame_range = frame_range
    w.run_task()
    return json.load(open(root / "roto" / "roto_shapes" / "shapes.json"))


def parts_of(frame):
    return {sid.split("/")[-1]: v for sid, v in frame.items()}


def test_parts_cover_the_matte(body):
    data = run(body)
    last = parts_of(data[str(FRAMES[-1])])
    assert {"Torso", "Head", "L_Forearm", "R_Forearm", "L_Calf", "R_Calf"} <= set(last)
    mask = np.zeros((200, 200), np.uint8)
    for v in last.values():
        pts = np.array([[p[0] - 0.5, 200 - p[1] - 0.5] for p in v["points"]], np.int32)
        cv2.fillPoly(mask, [pts], 1)
    matte = stick_figure() > 0
    assert (mask.astype(bool) & matte).sum() / matte.sum() > 0.9


def test_limb_behind_torso_fades_and_limb_in_front_stays(body):
    last = parts_of(run(body)[str(FRAMES[-1])])
    assert last["L_Forearm"]["opacity"] == 0.0   # joints 13-15: behind
    assert last["R_Forearm"]["opacity"] == 1.0   # joints 14-16: in front
    assert last["Torso"]["opacity"] == 1.0


def test_without_depth_everything_stays_visible(body):
    last = parts_of(run(body, depth=False)[str(FRAMES[-1])])
    assert all(v["opacity"] == 1.0 for v in last.values())


def test_plate_frame_numbers_in_out_and_fixed_point_counts(body):
    data = run(body, frame_range=(2, 3), points_limb=24)
    assert sorted(k for k in data if k.isdigit()) == ["1003", "1004"]
    counts = {len(v["points"]) for k, v in parts_of(data["1004"]).items() if k != "Torso" and k != "Head"}
    assert counts == {24}


def test_depth_encodings():
    assert bp.behind_amount(0.4, 0.5, "relative, near = 1") == pytest.approx(0.2)
    assert bp.behind_amount(6.0, 5.0, "metric") == pytest.approx(0.2)
    assert bp.behind_amount(0.6, 0.5, "relative, near = 1") < 0


def test_near_zero_maps_are_flipped(tmp_path):
    path = str(tmp_path / "d.exr")
    exr.write(path, np.full((4, 4), 0.25, np.float32), ("Z",), attributes={"contour/depth": "relative, near = 0"})
    convention = bp.depth_convention(path)
    assert convention == "relative, near = 0"
    assert bp.read_depth(path, convention)[0, 0] == pytest.approx(0.75)


def test_old_ai_roto_nodes_open_as_body_parts(tmp_path):
    from utvfx.core import project
    path = tmp_path / "old.contour"
    path.write_text(json.dumps({"format": 2, "nodes": [
        {"node_id": "a", "name": "AI Roto1", "plugin_type": "ai_roto",
         "params": {"target_points_limb": 40, "hysteresis_high": 0.1, "first_frame": 1001}}], "connections": []}))
    node = project.load(str(path))["nodes"][0]
    assert node["plugin_type"] == "roto_to_shape" and node["name"] == "Matte to Shape1"
    assert node["params"] == {"points_limb": 40, "hide_behind": 0.1, "first_frame": 1001, "mode": "Body parts (people)"}

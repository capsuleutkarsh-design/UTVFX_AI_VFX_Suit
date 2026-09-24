"""RotoToShape: per-layer shapes, stable shape ids and point counts, frame limits, Nuke coordinates."""
import json
import os

import cv2
import numpy as np
import pytest

from plugins.RotoToShape.backend import RotoToShapeWorker


def write_layer(folder, circles):
    """circles: {frame_number: [(cx, cy, r), ...]} -> 16-bit mattes like SuperMatte writes."""
    os.makedirs(folder, exist_ok=True)
    for n, items in circles.items():
        m = np.zeros((120, 200), np.uint16)
        for cx, cy, r in items:
            cv2.circle(m, (cx, cy), r, 65535, -1)
        cv2.imwrite(os.path.join(folder, f"alpha_{n:06d}.png"), m)


@pytest.fixture
def supermatte_cache(tmp_path):
    cache = tmp_path / "sm"
    frames = range(1001, 1009)
    write_layer(str(cache / "alpha" / "Actor"), {n: [(40 + 2 * (n - 1001), 60, 20)] for n in frames})
    # The prop disappears on 1004-1005 and comes back near where it was.
    write_layer(str(cache / "alpha" / "Prop"), {n: ([] if n in (1004, 1005) else [(150, 60, 15)]) for n in frames})
    combined = cache / "Matte"
    combined.mkdir()
    for n in frames:
        cv2.imwrite(str(combined / f"matte_{n:06d}.png"), np.zeros((120, 200), np.uint16))
    return cache


def run(cache, tmp_path, frame_range=None, **params):
    params = dict({"temporal_smoothing": False, "generate_feather": False, "max_missing_frames": 1}, **params)
    w = RotoToShapeWorker("r", params, {"Alpha Matte": str(cache / "Matte")}, str(tmp_path / "roto"), str(tmp_path))
    w.frame_range = frame_range
    w.run_task()
    return json.load(open(tmp_path / "roto" / "roto_shapes" / "shapes.json"))


def shape_ids(data):
    return {sid for k, v in data.items() if k.isdigit() for sid in v}


def test_each_layer_gets_its_own_shapes(supermatte_cache, tmp_path):
    ids = shape_ids(run(supermatte_cache, tmp_path))
    assert any(i.startswith("Actor/") for i in ids) and any(i.startswith("Prop/") for i in ids)


def test_a_returning_shape_keeps_its_id_and_point_count(supermatte_cache, tmp_path):
    data = run(supermatte_cache, tmp_path)
    prop = [i for i in shape_ids(data) if i.startswith("Prop/")]
    assert len(prop) == 1  # the same shape before and after the gap
    counts = {len(data[str(n)][prop[0]]["points"]) for n in (1001, 1003, 1006, 1008)}
    assert len(counts) == 1


def test_a_new_far_away_object_gets_a_new_shape(tmp_path):
    cache = tmp_path / "sm"
    write_layer(str(cache / "alpha" / "Solo"), {1001: [(30, 30, 12)], 1002: [], 1003: [], 1004: [(170, 90, 12)]})
    (cache / "Matte").mkdir()
    data = run(cache, tmp_path)
    assert len([i for i in shape_ids(data) if i.startswith("Solo/")]) == 2


def test_frame_limits_are_plate_numbers_and_in_out_applies(supermatte_cache, tmp_path):
    data = run(supermatte_cache, tmp_path, first_frame=1003, last_frame=1006)
    assert sorted(int(k) for k in data if k.isdigit()) == [1003, 1004, 1005, 1006]
    data = run(supermatte_cache, tmp_path, frame_range=(0, 1))
    assert sorted(int(k) for k in data if k.isdigit()) == [1001, 1002]


def test_points_are_pixel_centres_in_nuke_space(tmp_path):
    cache = tmp_path / "sm"
    folder = cache / "alpha" / "Box"
    folder.mkdir(parents=True)
    m = np.zeros((120, 200), np.uint16)
    m[20:61, 50:101] = 65535  # rows 20-60, columns 50-100
    cv2.imwrite(str(folder / "alpha_001001.png"), m)
    (cache / "Matte").mkdir()
    data = run(cache, tmp_path, point_mode="Fixed", target_points=8, edge_snap_radius=0, simplify_epsilon=0)
    pts = np.array([p[:2] for p in next(iter(data["1001"].values()))["points"]], float)
    # The box spans x 50..101 and, flipped, y 120-61=59 .. 120-20=100 in Nuke; centres sit half a pixel in.
    assert pts[:, 0].min() == pytest.approx(50.5, abs=1.0) and pts[:, 0].max() == pytest.approx(100.5, abs=1.0)
    assert pts[:, 1].min() == pytest.approx(59.5, abs=1.0) and pts[:, 1].max() == pytest.approx(99.5, abs=1.0)


def test_points_stay_on_the_object_when_only_part_of_it_moves(tmp_path):
    """A bump grows on one side; the points on the other side must not crawl along the edge
    (they used to be re-spaced evenly every frame, so every point moved)."""
    rng = np.random.default_rng(0)
    texture = (rng.random((200, 300, 3)) * 255).astype(np.uint8)
    plate, matte = tmp_path / "plate", tmp_path / "sm" / "Matte"
    plate.mkdir(parents=True)
    matte.mkdir(parents=True)
    for i, n in enumerate(range(1001, 1009)):
        cv2.imwrite(str(plate / f"frame_{n:06d}.png"), texture)  # a still plate: nothing slides for real
        m = np.zeros((200, 300), np.uint16)
        cv2.rectangle(m, (60, 40), (160, 160), 65535, -1)
        cv2.circle(m, (160, 100), 10 + 6 * i, 65535, -1)  # grows to the right
        cv2.imwrite(str(matte / f"matte_{n:06d}.png"), m)
    params = {"temporal_smoothing": False, "generate_feather": False, "point_mode": "Fixed", "target_points": 40}
    w = RotoToShapeWorker("r", params, {"Alpha Matte": str(matte), "Video Plate": str(plate)},
                          str(tmp_path / "roto"), str(tmp_path))
    w.run_task()
    data = json.load(open(tmp_path / "roto" / "roto_shapes" / "shapes.json"))
    sid = next(iter(data["1001"]))
    first = np.array([p[:2] for p in data["1001"][sid]["points"]])
    last = np.array([p[:2] for p in data["1008"][sid]["points"]])
    left = first[:, 0] < 100  # points on the side that does not change
    assert left.sum() >= 5
    assert np.abs(last[left] - first[left]).max() < 3.0

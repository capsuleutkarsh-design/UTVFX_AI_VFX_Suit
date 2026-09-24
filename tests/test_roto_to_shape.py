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


def polygon_iou(points, matte, height):
    drawn = np.zeros(matte.shape, np.uint8)
    pts = np.array([[p[0] - 0.5, height - p[1] - 0.5] for p in points])
    cv2.fillPoly(drawn, [np.round(pts * 16).astype(np.int32)], 1, shift=4)
    truth = matte > 0
    return (drawn.astype(bool) & truth).sum() / (drawn.astype(bool) | truth).sum()


def test_an_object_that_grows_gets_a_shape_with_enough_points(tmp_path):
    """A shape keeps its point count (Nuke keys every point), so one made for a small blob
    could not outline the large object it grew into: it hands over to a new shape."""
    cache = tmp_path / "sm"
    folder = cache / "alpha" / "Grow"
    folder.mkdir(parents=True)
    (cache / "Matte").mkdir()
    mattes = {}
    for i, n in enumerate(range(1001, 1007)):
        m = np.zeros((300, 400), np.uint16)
        cv2.ellipse(m, (200, 150), (8 + 30 * i, 6 + 22 * i), 0, 0, 360, 65535, -1)
        cv2.imwrite(str(folder / f"alpha_{n:06d}.png"), m)
        mattes[n] = m
    data = run(cache, tmp_path, max_missing_frames=0, auto_point_spacing=10)
    for n, m in mattes.items():
        visible = [v for v in data[str(n)].values() if v["opacity"] > 0]
        assert len(visible) == 1
        assert polygon_iou(visible[0]["points"], m, 300) > (0.85 if n == 1001 else 0.95), n  # 1001: 16 x 12 px
    assert len(shape_ids(data)) >= 2  # the handover


def test_a_soft_edge_puts_the_shape_on_the_core_and_the_feather_outside(tmp_path):
    """Nuke fades from 100% at the shape to 0 at the feather: the shape belongs where the matte
    is solid and the feather where it has faded, or every soft edge ends up outside the object."""
    cache = tmp_path / "sm"
    folder = cache / "alpha" / "Soft"
    folder.mkdir(parents=True)
    (cache / "Matte").mkdir()
    yy, xx = np.mgrid[0:200, 0:200]
    r = np.hypot(xx - 100, yy - 100)
    m = np.clip((70 - r) / 20 + 0.5, 0, 1)  # 50% at r=70, solid inside 60, gone beyond 80
    for n in (1001, 1002):
        cv2.imwrite(str(folder / f"alpha_{n:06d}.png"), (m * 65535).astype(np.uint16))
    data = run(cache, tmp_path, generate_feather=True, edge_snap_radius=0)
    pts = np.array([[p[0], p[1], p[3], p[4]] for p in next(iter(data["1001"].values()))["points"]])
    inner = np.hypot(pts[:, 0] - 100, pts[:, 1] - 100)
    outer = np.hypot(pts[:, 2] - 100, pts[:, 3] - 100)
    assert np.median(inner) == pytest.approx(61, abs=2.5)
    assert np.median(outer) == pytest.approx(79, abs=2.5)


def test_only_real_corners_are_cusps(tmp_path):
    """Corners come from the matte's outline: a circle has none, a square has four. (Judged from
    a shape's own points, most points of a shape with few points became cusps.)"""
    cache = tmp_path / "sm"
    (cache / "Matte").mkdir(parents=True)
    for name, draw in (("Circle", lambda m: cv2.circle(m, (100, 100), 40, 65535, -1)),
                       ("Square", lambda m: cv2.rectangle(m, (60, 60), (140, 140), 65535, -1))):
        folder = cache / "alpha" / name
        folder.mkdir(parents=True)
        m = np.zeros((200, 200), np.uint16)
        draw(m)
        cv2.imwrite(str(folder / "alpha_001001.png"), m)
    data = run(cache, tmp_path, point_mode="Fixed", target_points=8, edge_snap_radius=0)
    kinds = {sid.split("/")[0]: [p[2] for p in v["points"]] for sid, v in data["1001"].items()}
    assert kinds["Circle"].count("cusp") == 0
    assert kinds["Square"].count("cusp") >= 4

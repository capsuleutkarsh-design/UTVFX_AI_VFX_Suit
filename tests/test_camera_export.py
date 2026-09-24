"""Unified Output camera export (C2): real line breaks, plate frame numbers, full-size camera from a
half-size solve, and every format the Automated Tracker's writers produce."""
import json
import os

import pytest

from plugins.CompositeOutput.camera import export_camera, scale_cameras


def tracker_cache(root, working_scale=1.0, numbers=(1001, 1002, 1003)):
    model = root / "sparse" / "0"
    model.mkdir(parents=True)
    w, h = int(1920 * working_scale), int(1080 * working_scale)
    (model / "cameras.txt").write_text(f"# cameras\n1 SIMPLE_RADIAL {w} {h} {1500 * working_scale} {w / 2} {h / 2} 0.02\n")
    lines = ["# images"]
    for i, n in enumerate(numbers, 1):
        lines += [f"{i} 1 0 0 0 {0.1 * i} 0 0 1 frame_{n:06d}.jpg", f"100 200 {i}"]
    (model / "images.txt").write_text("\n".join(lines) + "\n")
    (model / "points3D.txt").write_text("".join(f"{i} {i * 0.1} 0 5 200 200 200 0.4 1 0\n" for i in range(1, 40)))
    solve = {"frames": {f"frame_{n:06d}.jpg": n for n in numbers}, "registered": list(numbers),
             "image_width": w, "image_height": h, "working_scale": working_scale, "pixel_aspect": 1.0,
             "fps": 24.0, "plate_cache": None}
    (root / "sparse" / "solve.json").write_text(json.dumps(solve))
    return root


def chan_rows(out):
    rows = []
    for line in (out / "tracking" / "camera_track.chan").read_text().splitlines():
        try:
            rows.append([float(v) for v in line.split()])
        except ValueError:
            continue  # header
    return rows


def test_nuke_script_has_line_breaks_and_plate_frame_numbers(tmp_path):
    cache = tracker_cache(tmp_path / "trk")
    result = export_camera(str(cache), str(tmp_path / "out"), {}, lambda m: None)
    nk = (tmp_path / "out" / "tracking" / "camera_track_nuke.nk").read_text()
    assert nk.count("\n") > 20  # a real multi-line script (labels may still hold Nuke's escaped \n)
    assert "x1001" in nk and "x1003" in nk  # keys on plate frames, not 1..N
    names = {os.path.basename(p) for p in result["exported_files"]}
    assert {"camera_track_nuke.nk", "camera_track.chan", "import_to_blender.py", "points3D.ply",
            "camera_track.json"} <= names
    assert chan_rows(tmp_path / "out")[0][0] == 1001


def test_half_size_solve_exports_a_full_size_camera(tmp_path):
    cache = tracker_cache(tmp_path / "trk", working_scale=0.5)
    export_camera(str(cache), str(tmp_path / "out"), {}, lambda m: None)
    camera = json.loads((tmp_path / "out" / "tracking" / "camera_track.json").read_text())["cameras"]["1"]
    assert (camera["width"], camera["height"]) == (1920, 1080)
    assert camera["focal_x"] == pytest.approx(1500)


def test_scaling_keeps_distortion(tmp_path):
    src, dst = tmp_path / "a.txt", tmp_path / "b.txt"
    src.write_text("1 OPENCV 960 540 800 800 480 270 0.1 -0.02 0.001 0.002\n")
    scale_cameras(src, dst, 2.0)
    assert dst.read_text().split()[2:] == ["1920", "1080", "1600.0", "1600.0", "960.0", "540.0",
                                            "0.1", "-0.02", "0.001", "0.002"]


def test_no_solve_is_a_clear_error(tmp_path):
    with pytest.raises(RuntimeError, match="Render the tracker first"):
        export_camera(str(tmp_path), str(tmp_path / "out"), {}, lambda m: None)


def test_scene_scale_scales_the_camera_path(tmp_path):
    cache = tracker_cache(tmp_path / "trk")
    export_camera(str(cache), str(tmp_path / "a"), {}, lambda m: None)
    export_camera(str(cache), str(tmp_path / "b"), {"scene_scale": 10.0}, lambda m: None)
    first = chan_rows(tmp_path / "a")[1][1:4]
    scaled = chan_rows(tmp_path / "b")[1][1:4]
    assert scaled == pytest.approx([10 * v for v in first], abs=1e-4)

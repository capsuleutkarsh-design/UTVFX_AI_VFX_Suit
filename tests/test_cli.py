"""Command-line rendering: arguments, frame ranges, targets, and a real headless render of a project."""
import os

import pytest

from utvfx import cli
from utvfx.core import project


def test_parse_frames():
    assert cli.parse_frames("1001-1050") == (1001, 1050)
    assert cli.parse_frames("1001-") == (1001, None)
    assert cli.parse_frames("-1050") == (None, 1050)
    assert cli.parse_frames("1010") == (1010, 1010)
    with pytest.raises(ValueError):
        cli.parse_frames("ten")


def test_frames_to_positions():
    numbers = list(range(1001, 1011))
    assert cli.frames_to_positions(numbers, 1003, 1005) == (2, 4)
    assert cli.frames_to_positions(numbers, None, 1002) == (0, 1)
    with pytest.raises(ValueError):
        cli.frames_to_positions(numbers, 2000, None)


def graph_with_grade(plate_file):
    return {"format": 2, "nodes": [
        {"node_id": "p", "name": "Plate1", "plugin_type": "media_plate", "x": 0, "y": 0,
         "params": {"plate_file": plate_file, "is_sequence": True}},
        {"node_id": "g", "name": "Grade1", "plugin_type": "grade", "x": 200, "y": 0, "params": {"gain": 2.0}},
    ], "connections": [{"src_node_id": "p", "src_port_name": "Video Plate", "dst_node_id": "g", "dst_port_name": "Image"}]}


def test_render_a_node_headless(hdr_exr_sequence, tmp_path, qapp, capsys):
    first = sorted(os.listdir(hdr_exr_sequence))[0]
    path = str(tmp_path / "shot.contour")
    project.save(path, graph_with_grade(str(hdr_exr_sequence / first)))
    assert cli.main([path, "--list"]) == 0
    assert "Grade1" in capsys.readouterr().out
    assert cli.main([path, "--node", "Grade1", "--frames", "1002-1003", "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "Grade1: done" in out and "Frames 1002-1003" in out
    from utvfx.core.media_resolver import get_node_cache
    from utvfx.core.plate import find_sequence
    node = type("N", (), {"node_id": "g", "plugin_type": "grade", "name": "Grade1"})()
    graded = find_sequence(os.path.join(get_node_cache(node), "Frames"))
    assert [n for n, _ in graded] == [1002, 1003]


def test_bad_node_and_no_output(tmp_path, hdr_exr_sequence, qapp, capsys):
    path = str(tmp_path / "shot.contour")
    project.save(path, graph_with_grade(str(hdr_exr_sequence / sorted(os.listdir(hdr_exr_sequence))[0])))
    assert cli.main([path, "--node", "Nope"]) == cli.EXIT_USAGE
    assert cli.main([path]) == cli.EXIT_USAGE  # no Unified Output to render by default
    assert cli.main([str(tmp_path / "missing.contour")]) == cli.EXIT_USAGE

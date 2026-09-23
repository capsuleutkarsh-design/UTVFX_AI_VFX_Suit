"""Project files and folders (M1, M2): safe save, checked load, relink, autosave, Save As keeps renders."""
import json
import os

import pytest

from utvfx.core import project
from utvfx.core.settings_manager import SettingsManager, safe_project_name


def scene_data(plate_path):
    return {
        "nodes": [{"node_id": "p1", "plugin_type": "media_plate", "name": "Plate",
                   "params": {"plate_file": plate_path}}],
        "connections": [],
    }


def test_save_is_atomic_and_versioned(tmp_path):
    path = tmp_path / "shot.contour"
    project.save(str(path), scene_data("x.exr"))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == project.FORMAT and "app_version" in data
    assert not (tmp_path / "shot.contour.saving").exists()


@pytest.mark.parametrize("content, message", [
    ("{not json", "damaged"),
    ('{"hello": 1}', "not a Contour VFX project"),
    ('{"nodes": [{"name": "x"}]}', "cannot read"),
    ('{"format": 99, "nodes": []}', "newer version"),
])
def test_bad_files_are_refused_with_a_clear_message(tmp_path, content, message):
    path = tmp_path / "bad.contour"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(project.ProjectError, match=message):
        project.load(str(path))


def test_old_utvfx_files_still_open(tmp_path):
    path = tmp_path / "old.utvfx"
    path.write_text(json.dumps(scene_data("x.exr")), encoding="utf-8")
    data = project.load(str(path))
    assert data["backdrops"] == [] and data["nodes"][0]["node_id"] == "p1"


def test_missing_plates_are_found_and_relinked(tmp_path):
    moved = tmp_path / "new_disk" / "plates"
    moved.mkdir(parents=True)
    (moved / "sh010.1001.exr").write_bytes(b"x")
    data = scene_data(r"D:\old_disk\plates\sh010.1001.exr")
    assert project.missing_media(data) == [("p1", r"D:\old_disk\plates\sh010.1001.exr")]
    assert project.relink(data, str(tmp_path)) == 1
    assert data["nodes"][0]["params"]["plate_file"] == str(moved / "sh010.1001.exr")
    assert project.missing_media(data) == []


def test_autosave_round_trip(tmp_path):
    project.write_autosave(str(tmp_path), scene_data("x.exr"), project_path="C:/shots/a.contour")
    data = project.read_autosave(str(tmp_path))
    assert data["autosave_of"] == "C:/shots/a.contour" and data["nodes"]
    project.clear_autosave(str(tmp_path))
    assert project.read_autosave(str(tmp_path)) is None


def test_project_names_are_safe_folder_names():
    assert safe_project_name('shot: "010" / v2?') == "shot_ _010_ _ v2_"
    assert safe_project_name("  ") == "Untitled"


@pytest.fixture
def settings(tmp_path):
    """The real SettingsManager, pointed at a temporary workspace and restored afterwards."""
    sm = SettingsManager()
    saved_settings, saved_name, saved_file = dict(sm.settings), sm.current_project_name, sm.settings_file
    sm.settings_file = str(tmp_path / "settings.json")
    sm.settings["workspace_dir"] = str(tmp_path / "ws")
    yield sm
    sm.settings, sm.current_project_name, sm.settings_file = saved_settings, saved_name, saved_file


def test_save_as_keeps_renders_under_both_names(settings, tmp_path):
    settings.set_project_name("sh010_v1", carry_cache=False)
    render = os.path.join(settings.get("cache_dir"), "node1", "frame_0001.png")
    os.makedirs(os.path.dirname(render))
    open(render, "wb").write(b"pixels")

    settings.set_project_name("sh010_v2", carry_cache=True)  # Save As
    new_render = os.path.join(settings.get("cache_dir"), "node1", "frame_0001.png")
    assert settings.get("cache_dir").endswith(os.path.join("sh010_v2", "cache"))
    assert open(new_render, "rb").read() == b"pixels"
    assert os.path.exists(render)  # the first project keeps its renders too


def test_chosen_folders_survive_a_project_switch(settings, tmp_path):
    settings.set("default_output_dir", str(tmp_path / "deliveries"))
    settings.set_project_name("sh020", carry_cache=False)
    assert settings.get("output_dir") == str(tmp_path / "deliveries" / "sh020")
    assert settings.get("cache_dir").startswith(str(tmp_path / "ws"))


def test_unhandled_errors_and_native_crashes_are_logged(tmp_path, monkeypatch):
    """M4: the crash handler logs the traceback; faulthandler writes native crashes to a file."""
    import faulthandler
    import logging
    import sys
    import threading
    from utvfx.core import logger

    monkeypatch.setattr(logger, "_state", {"log_file": None, "fault_file": None, "installed": False})
    monkeypatch.setattr(logger, "log_dir", lambda: str(tmp_path / "logs"))
    for name in ("excepthook",):
        monkeypatch.setattr(sys, name, getattr(sys, name))
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(logger, "_show_crash_dialog", lambda summary: None)
    try:
        logger.setup_global_logger()
        assert faulthandler.is_enabled()
        try:
            raise ValueError("boom in a slot")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        for h in logging.getLogger().handlers:
            h.flush()
        text = open(logger.current_log_file(), encoding="utf-8").read()
        assert "Unhandled error" in text and "boom in a slot" in text and "Traceback" in text
    finally:
        logger.shutdown_logger()
        faulthandler.enable(file=sys.__stderr__)  # pytest's own crash reporting


@pytest.mark.parametrize("path, name", [
    (r"C:\shots\sh010_plate.1001.exr", "sh010_plate"),
    (r"C:\shots\sh020\1001.exr", "sh020"),
    (r"C:\shots\renders\1001.exr", "1001"),
    (r"C:\shots\interview_cam_a.mov", "interview_cam_a"),
])
def test_shot_name_from_plate_path(path, name):
    assert project.shot_name_from_path(path) == name

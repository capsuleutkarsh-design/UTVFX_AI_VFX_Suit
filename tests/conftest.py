import os
import sys

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")  # as main.py does, before cv2 loads

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Private test plates stay outside the repo and are never uploaded or committed.
FOOTAGE_DIR = os.environ.get(
    "CONTOUR_FOOTAGE", os.path.join(os.path.expanduser("~"), "Documents", "Test")
)


@pytest.fixture(autouse=True, scope="session")
def private_settings(tmp_path_factory):
    """Keep tests out of the real settings.json and workspace (projects, caches, outputs).

    Model weights are still read from the real models folder.
    """
    from utvfx.core.settings_manager import SettingsManager
    sm = SettingsManager()
    saved = (sm.settings_file, dict(sm.settings), sm.current_project_name)
    root = tmp_path_factory.mktemp("contour_settings")
    sm.settings_file = str(root / "settings.json")
    sm.settings["workspace_dir"] = str(root / "workspace")
    sm.settings.pop("default_output_dir", None)
    sm.set_project_name("Untitled", carry_cache=False)
    yield sm
    sm.settings_file, sm.settings, sm.current_project_name = saved[0], saved[1], saved[2]
    sm._derive_folders()


@pytest.fixture(autouse=True, scope="session")
def no_modal_dialogs():
    """Answer message boxes automatically for the whole run, so a prompt (even one fired by a
    leftover timer from an earlier test) can never hang it."""
    from PySide6.QtWidgets import QMessageBox

    answered = []

    def answer(kind, value):
        def _answer(*args, **kwargs):
            answered.append((kind, args[1] if len(args) > 1 else ""))
            return value
        return staticmethod(_answer)

    buttons = QMessageBox.StandardButton
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(QMessageBox, "question", answer("question", buttons.Discard))
        mp.setattr(QMessageBox, "warning", answer("warning", buttons.Ok))
        mp.setattr(QMessageBox, "information", answer("information", buttons.Ok))
        mp.setattr(QMessageBox, "critical", answer("critical", buttons.Ok))
        mp.setattr(QMessageBox, "exec", lambda self: 0)
        yield answered


@pytest.fixture(scope="session")
def footage_dir():
    if not os.path.isdir(FOOTAGE_DIR):
        pytest.skip(f"test plates not found at {FOOTAGE_DIR} (set CONTOUR_FOOTAGE)")
    return FOOTAGE_DIR


@pytest.fixture(scope="session")
def exr_plate(footage_dir):
    """4K ACES EXR sequence numbered from 1001."""
    path = os.path.join(footage_dir, "Exr", "05052026")
    if not os.path.isdir(path):
        pytest.skip("EXR test plate missing")
    return path


@pytest.fixture
def hdr_exr_sequence(tmp_path):
    """A tiny synthetic linear EXR sequence (1001-1003) with highlights above 1.0."""
    import OpenImageIO as oiio

    folder = tmp_path / "plate"
    folder.mkdir()
    for frame in (1001, 1002, 1003):
        pixels = np.full((48, 64, 3), 0.18, dtype=np.float32)
        pixels[10:20, 10:20] = 4.0
        spec = oiio.ImageSpec(64, 48, 3, oiio.HALF)
        out = oiio.ImageOutput.create(str(folder / f"shot.{frame}.exr"))
        out.open(str(folder / f"shot.{frame}.exr"), spec)
        out.write_image(pixels)
        out.close()
    return folder


@pytest.fixture
def node_scene(qapp):
    from utvfx.ui.graph.scene import NodeScene

    scene = NodeScene()
    yield scene
    # Tear down inside Qt, not whenever Python's GC gets to it; a scene collected
    # during a later test's event processing crashes the interpreter.
    scene.clear()
    scene.nodes.clear()
    scene.connections.clear()
    scene.deleteLater()
    qapp.processEvents()


def pytest_collection_modifyitems(config, items):
    """Tests marked `models` need the downloaded weights; on a fresh clone they are skipped, not failed."""
    weights = os.path.join(ROOT, "models", "ViTMatte", "model.safetensors")
    if os.path.isfile(weights):
        return
    skip = pytest.mark.skip(reason="model weights not installed (run first_setup.py)")
    for item in items:
        if "models" in item.keywords:
            item.add_marker(skip)

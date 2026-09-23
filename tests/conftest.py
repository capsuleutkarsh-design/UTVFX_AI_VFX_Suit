import os
import sys

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Private test plates stay outside the repo and are never uploaded or committed.
FOOTAGE_DIR = os.environ.get(
    "CONTOUR_FOOTAGE", os.path.join(os.path.expanduser("~"), "Documents", "Test")
)


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

    return NodeScene()

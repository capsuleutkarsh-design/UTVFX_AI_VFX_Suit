"""Depth: float EXR output, plate frame numbers, In/Out, one range for the shot (no pumping)."""
import os

import cv2
import numpy as np
import pytest

from plugins.DepthEstimator import backend
from plugins.DepthEstimator.backend import DepthWorker, fit_scale_offset
from utvfx.core import exr


class DriftingModel:
    """Returns the true disparity with a different scale and offset each frame, like the real model."""

    def __init__(self):
        self.calls = 0

    def infer_image(self, frame, input_size=518):
        self.calls += 1
        h, w = frame.shape[:2]
        truth = np.tile(np.linspace(0.2, 1.0, h, dtype=np.float32)[:, None], (1, w))  # nearer towards the bottom
        scale, offset = 1.0 + 0.4 * (self.calls % 3), 0.3 * (self.calls % 2)
        return truth * scale + offset


@pytest.fixture
def plate(tmp_path):
    folder = tmp_path / "plate"
    folder.mkdir()
    rng = np.random.default_rng(3)
    texture = (rng.random((60, 80, 3)) * 255).astype(np.uint8)
    for n in range(1001, 1007):
        cv2.imwrite(str(folder / f"frame_{n:06d}.png"), np.roll(texture, n - 1001, axis=1))
    return folder


def run(plate, tmp_path, monkeypatch, frame_range=None, **params):
    model = DriftingModel()
    monkeypatch.setattr(backend, "load_model", lambda *a, **k: model)
    params = dict({"temporal_smoothing": 0.0}, **params)
    w = DepthWorker("d", params, {"Video Plate": str(plate)}, str(tmp_path / "depth"), str(tmp_path))
    w.frame_range = frame_range
    w.run_task()
    return tmp_path / "depth"


def test_float_exr_with_plate_numbers(plate, tmp_path, monkeypatch):
    out = run(plate, tmp_path, monkeypatch)
    files = sorted(os.listdir(out / "Depth"))
    assert files[0] == "depth_001001.exr" and len(files) == 6
    pixels, channels = exr.read(str(out / "Depth" / files[0]))
    assert channels == ["Z"] and pixels.dtype == np.float32
    assert len(os.listdir(out / "Preview")) == 6


def test_no_pumping_when_the_model_drifts(plate, tmp_path, monkeypatch):
    out = run(plate, tmp_path, monkeypatch)
    frames = [exr.read(str(out / "Depth" / f))[0][..., 0] for f in sorted(os.listdir(out / "Depth"))]
    for f in frames[1:]:
        assert np.abs(f - frames[0]).mean() < 0.02
    assert frames[0][-1].mean() > frames[0][0].mean()  # near = 1 by default


def test_near_zero_option_and_in_out(plate, tmp_path, monkeypatch):
    out = run(plate, tmp_path, monkeypatch, frame_range=(1, 2), near_value="Near = 0, far = 1")
    assert sorted(os.listdir(out / "Depth")) == ["depth_001002.exr", "depth_001003.exr"]
    d = exr.read(str(out / "Depth" / "depth_001002.exr"))[0][..., 0]
    assert d[-1].mean() < d[0].mean()


def test_fit_recovers_scale_and_offset():
    x = np.random.default_rng(0).random((30, 40)).astype(np.float32)
    y = 2.5 * x - 0.7
    y[:3] = 50  # outliers
    s, b = fit_scale_offset(x, y)
    assert abs(s - 2.5) < 1e-3 and abs(b + 0.7) < 1e-3


def test_missing_weights_say_how_to_install(monkeypatch, tmp_path):
    from utvfx.core.settings_manager import SettingsManager
    monkeypatch.setattr(SettingsManager(), "models_dir", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="SETUP"):
        backend.weights_path("vits", "indoor")

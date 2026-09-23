"""SuperMatte stages with a stand-in SAM engine and refiner (no models, no GPU)."""
import os

import cv2
import numpy as np
import pytest

from plugins.SuperMatte import backend


class FakeBridge:
    """Answers with a filled circle around the first click, like SAM would."""

    def __init__(self):
        self.calls = []
        self.tracked = None
        self.last_error = ""

    def query_mask(self, image_path, points, labels, fill_color_hex, out_mask_path, sam_version, text_prompt, boxes):
        img = cv2.imread(image_path)
        self.calls.append(os.path.basename(image_path))
        mask = np.zeros(img.shape[:2], np.uint8)
        x, y = map(int, points[0])
        cv2.circle(mask, (x, y), 8, 255, -1)
        cv2.imwrite(out_mask_path, mask)
        return object()

    def track_video(self, frames_dir, start, prompts, out_dir, sam_version="SAM 2 (SAMURAI)"):
        self.tracked = (sorted(os.listdir(frames_dir)), prompts)
        h, w = cv2.imread(os.path.join(frames_dir, "00000.jpg")).shape[:2]
        for k in range(len(os.listdir(frames_dir))):
            m = np.zeros((h, w), np.uint8)
            m[5:15, 5 + k:15 + k] = 255
            cv2.imwrite(os.path.join(out_dir, f"sam_mask_0_{k:06d}.png"), m)
        return True


@pytest.fixture
def plate(tmp_path):
    folder = tmp_path / "plate"
    folder.mkdir()
    for n in range(1001, 1005):
        img = np.full((40, 60, 3), 60, np.uint8)
        cv2.rectangle(img, (20, 10), (40, 30), (200, 200, 200), -1)
        cv2.imwrite(str(folder / f"sh.{n}.png"), img)
    return folder


@pytest.fixture
def run(tmp_path, plate, monkeypatch):
    from utvfx.bridge import ai_bridge_client

    bridge = FakeBridge()
    monkeypatch.setattr(ai_bridge_client.AIBridgeClient, "get_instance", staticmethod(lambda: bridge))
    monkeypatch.setattr(backend.SuperMatteWorker, "_load_refiner",
                        lambda self, mode, device: {"videomama": None, "mematte": False, "onnx": False,
                                                    "model": None, "processor": None, "ort": None})
    monkeypatch.setattr(backend.SuperMatteWorker, "run_vitmatte",
                        lambda self, frame, mask, *a: mask.astype(np.float32) / 255.0)

    def _run(params, frame_range=None):
        params = dict({"refiner_model": "ViTMatte", "sam_version": "SAM 1 (ViT-H)"}, **params)
        w = backend.SuperMatteWorker("n", params, {"Video Plate": str(plate)}, str(tmp_path / "cache"), str(tmp_path))
        w.frame_range = frame_range
        w.run_task()
        return tmp_path / "cache", bridge
    return _run


def layer(keys):
    return {"mask_layers": [{"id": "l1", "name": "Actor", "keyframes": keys}]}


def test_clicks_on_a_later_frame_also_matte_the_frames_before_it(run):
    cache, bridge = run(layer({2: [[0.5, 0.5, True]]}))
    assert sorted(os.listdir(cache / "Matte")) == [f"matte_{n:06d}.png" for n in range(1001, 1005)]
    assert bridge.calls[:2] == ["sh.1003.png", "sh.1004.png"]          # forward from the click
    assert "sh.1001.png" in bridge.calls and "sh.1002.png" in bridge.calls  # then backward


def test_in_out_range_limits_the_render(run):
    cache, bridge = run(layer({0: [[0.5, 0.5, True]]}), frame_range=(1, 2))
    assert sorted(os.listdir(cache / "Matte")) == ["matte_001002.png", "matte_001003.png"]


def test_mattes_are_16_bit(run):
    cache, _ = run(layer({0: [[0.5, 0.5, True]]}))
    matte = cv2.imread(str(cache / "Matte" / "matte_001001.png"), cv2.IMREAD_UNCHANGED)
    assert matte.dtype == np.uint16 and matte.max() == 65535
    assert os.path.exists(cache / "alpha" / "Actor" / "alpha_001001.png")


def test_unreadable_frame_stops_with_a_clear_error(run, plate):
    (plate / "sh.1003.png").write_bytes(b"not a png")
    with pytest.raises(Exception, match="1003"):
        run(layer({0: [[0.5, 0.5, True]]}))


def test_samurai_gets_numbered_jpgs_and_masks_map_back(run):
    cache, bridge = run(dict(layer({1: [[0.5, 0.5, True]]}), sam_version="SAM 2 (SAMURAI)"), frame_range=(1, 3))
    names, prompts = bridge.tracked
    assert names == ["00000.jpg", "00001.jpg", "00002.jpg"]  # what SAMURAI's loader can read
    assert prompts[0]["frame"] == 0                          # position 1 is the first frame of the range
    assert sorted(os.listdir(cache / "Matte")) == ["matte_001002.png", "matte_001003.png", "matte_001004.png"]


def test_stabilisation_lines_the_previous_matte_up_with_the_current_frame():
    def frame(x):
        g = np.full((80, 120), 40, np.uint8)
        cv2.rectangle(g, (x, 25), (x + 30, 55), 220, -1)
        return g

    prev_gray, gray = frame(40), frame(50)  # the object moved 10 px right
    prev_alpha = (frame(40) > 100).astype(np.float32)
    alpha = (frame(50) > 100).astype(np.float32)
    blended = backend.SuperMatteWorker._stabilise(alpha, prev_alpha, gray, prev_gray)
    naive = 0.6 * alpha + 0.4 * prev_alpha  # what an unaligned blend looks like
    assert np.abs(blended - alpha).mean() < 0.5 * np.abs(naive - alpha).mean()


def test_guided_upscale_returns_full_size():
    frame = np.full((2160, 4096, 3), 128, np.uint8)
    trimap = np.full((2160, 4096), 128, np.uint8)
    alpha = backend.SuperMatteWorker._guided_upscale(np.full((1080, 2048), 0.5, np.float32), frame, trimap)
    assert alpha.shape == (2160, 4096) and alpha.dtype == np.float32


def test_videomama_pads_instead_of_squashing(run, monkeypatch):
    from PIL import Image

    class FakePipeline:
        def run(self, cond_frames, mask_frames, seed, mask_cond_mode):
            assert all(f.size == backend.VIDEOMAMA_SIZE for f in cond_frames)
            return [m.convert("RGB") for m in mask_frames]  # echo the mask back as the matte

    monkeypatch.setattr(backend.SuperMatteWorker, "_load_refiner",
                        lambda self, mode, device: {"videomama": FakePipeline(), "mematte": False, "onnx": False,
                                                    "model": None, "processor": None, "ort": None})
    cache, _ = run(dict(layer({0: [[0.5, 0.5, True]]}), refiner_model="VideoMaMa"))
    matte = cv2.imread(str(cache / "Matte" / "matte_001001.png"), cv2.IMREAD_UNCHANGED)
    assert matte.shape == (40, 60)
    ys, xs = np.nonzero(matte > 32768)
    # The SAM circle (radius 8) stays round: equal width and height within a pixel or two.
    assert abs((xs.max() - xs.min()) - (ys.max() - ys.min())) <= 2

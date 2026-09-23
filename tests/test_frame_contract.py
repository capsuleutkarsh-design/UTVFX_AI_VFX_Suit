"""ISSUE-C7: clicks are keyed by timeline position; frame numbers only name files.

On a plate numbered from 1001, a correction clicked on the third frame must be
used on the third frame (file 1003), not ignored.
"""
import os

import cv2
import numpy as np


class FakeBridge:
    def __init__(self):
        self.calls = []

    def query_mask(self, image_path, points, labels, fill_color_hex, out_mask_path, sam_version, text_prompt, boxes):
        self.calls.append((os.path.basename(image_path), [tuple(p) for p in points]))
        cv2.imwrite(out_mask_path, np.full(cv2.imread(image_path).shape[:2], 255, np.uint8))
        return object()  # the real bridge returns the mask as a QImage


class _Dummy:
    def __getattr__(self, name):
        return lambda *a, **k: self


def test_clicks_on_later_frames_of_a_1001_plate_are_used(tmp_path, monkeypatch):
    import transformers
    from plugins.SuperMatte import backend
    from utvfx.bridge import ai_bridge_client

    plate = tmp_path / "plate"
    plate.mkdir()
    for n in (1001, 1002, 1003, 1004):
        cv2.imwrite(str(plate / f"shot.{n}.png"), np.full((40, 60, 3), 90, np.uint8))

    bridge = FakeBridge()
    monkeypatch.setattr(ai_bridge_client.AIBridgeClient, "get_instance", staticmethod(lambda: bridge))
    monkeypatch.setattr(transformers.VitMatteImageProcessor, "from_pretrained", staticmethod(lambda *a, **k: _Dummy()))
    monkeypatch.setattr(transformers.VitMatteForImageMatting, "from_pretrained", staticmethod(lambda *a, **k: _Dummy()))
    monkeypatch.setattr(backend.SuperMatteWorker, "run_vitmatte", lambda self, frame, mask, *a: mask)

    first, correction = [0.25, 0.25, True], [0.75, 0.5, True]
    params = {
        "mask_layers": [{"id": "l1", "name": "Layer", "keyframes": {0: [first], 2: [correction]}}],
        "refiner_model": "ViTMatte",
        "sam_version": "SAM 1 (ViT-H)",
    }
    worker = backend.SuperMatteWorker("n1", params, {"Video Plate": str(plate)}, str(tmp_path / "cache"), str(tmp_path))
    worker.run_task()

    by_file = dict(bridge.calls)
    assert list(by_file) == ["frame_001001.png", "frame_001002.png", "frame_001003.png", "frame_001004.png"]
    assert by_file["frame_001001.png"] == [(15.0, 10.0)]
    assert by_file["frame_001003.png"] == [(45.0, 20.0)]  # the correction, in pixels
    assert sorted(os.listdir(tmp_path / "cache" / "Matte")) == [f"matte_{n:06d}.png" for n in (1001, 1002, 1003, 1004)]

"""CorridorKey wrapper: In/Out, guide matte, despill limit, linear EXRs, matte clean-up, no handler leak.

The real network is replaced by a fake engine that writes what the real one writes:
FG (sRGB-encoded EXR), Matte (linear EXR), Processed and Comp, named after the input frames.
"""
import logging
import os
import sys
import types

import cv2
import numpy as np
import pytest

from plugins.CorridorKey import backend
from plugins.CorridorKey.backend import CorridorKeyWorker
from utvfx.core import media_resolver


def write_plate(folder, numbers):
    os.makedirs(folder, exist_ok=True)
    for n in numbers:
        img = np.full((40, 60, 3), (40, 200, 40), np.uint8)  # green screen
        cv2.rectangle(img, (20, 10), (40, 30), (128, 128, 128), -1)  # grey subject
        cv2.imwrite(os.path.join(folder, f"frame_{n:06d}.png"), img)


def write_mattes(folder, numbers):
    os.makedirs(folder, exist_ok=True)
    for n in numbers:
        m = np.zeros((40, 60), np.uint16)
        m[10:31, 20:41] = 65535
        cv2.imwrite(os.path.join(folder, f"alpha_{n:06d}.png"), m)


class FakeEngine:
    """Stands in for clip_manager; records what the worker handed it."""

    def __init__(self):
        self.calls = {}

    def module(self):
        engine = self

        class ClipAsset:
            def __init__(self, path, kind):
                self.path, self.type = path, kind

        class ClipEntry:
            def __init__(self, name, root):
                self.name, self.root_path = name, root
                self.input_asset = self.alpha_asset = None

        class InferenceSettings:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        def run_birefnet(clips, **kw):
            clip = clips[0]
            write_mattes(os.path.join(clip.root_path, "AlphaHint"), range(len(os.listdir(clip.input_asset.path))))
            engine.calls["birefnet"] = True

        def run_inference(clips, settings=None, **kw):
            clip = clips[0]
            logging.getLogger().info("fake engine running")
            engine.calls["settings"] = settings
            engine.calls["inputs"] = sorted(os.listdir(clip.input_asset.path))
            engine.calls["guides"] = sorted(os.listdir(clip.alpha_asset.path))
            import CorridorKeyModule.core.color_utils as cu
            engine.calls["limit"] = cu.despill_opencv(np.zeros((2, 2, 3), np.float32))
            out = os.path.join(clip.root_path, "Output")
            for sub in ("FG", "Matte", "Processed", "Comp"):
                os.makedirs(os.path.join(out, sub), exist_ok=True)
            for name, guide in zip(engine.calls["inputs"], engine.calls["guides"]):
                stem = os.path.splitext(name)[0]
                a = cv2.imread(os.path.join(clip.alpha_asset.path, guide), cv2.IMREAD_UNCHANGED).astype(np.float32)
                a /= 65535.0 if a.max() > 255 else 255.0
                a[0, 0] = 1.0  # a speck for the median to remove
                backend._write_exr(os.path.join(out, "Matte", stem + ".exr"), a)
                backend._write_exr(os.path.join(out, "FG", stem + ".exr"), np.full((40, 60, 3), 0.5, np.float32))
                cv2.imwrite(os.path.join(out, "Comp", stem + ".png"), np.zeros((40, 60, 3), np.uint8))

        return types.SimpleNamespace(ClipAsset=ClipAsset, ClipEntry=ClipEntry, InferenceSettings=InferenceSettings,
                                     run_inference=run_inference, run_birefnet=run_birefnet)


@pytest.fixture
def fake_engine(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setitem(sys.modules, "clip_manager", engine.module())
    cu = types.ModuleType("CorridorKeyModule.core.color_utils")
    cu.despill_opencv = lambda image, limit_mode="average", *a, **k: limit_mode
    monkeypatch.setitem(sys.modules, "CorridorKeyModule.core.color_utils", cu)
    monkeypatch.setattr(backend, "_use_shared_models_dir", lambda: backend._patch_despill(cu))
    return engine


def run(tmp_path, frame_range=None, wire_matte=True, **params):
    plate = tmp_path / "plate"
    write_plate(str(plate), range(1001, 1007))
    inputs = {"Video Plate": str(plate)}
    if wire_matte:
        write_mattes(str(tmp_path / "matte"), range(1001, 1007))
        inputs["Alpha Matte"] = str(tmp_path / "matte")
    w = CorridorKeyWorker("ck", params, inputs, str(tmp_path / "ck"), str(tmp_path))
    w.frame_range = frame_range
    w.run_task()
    return tmp_path / "ck" / "Output"


def test_in_out_keys_only_those_frames_with_matching_guides(fake_engine, tmp_path):
    run(tmp_path, frame_range=(2, 4))
    assert fake_engine.calls["inputs"] == ["frame_001003.png", "frame_001004.png", "frame_001005.png"]
    assert len(fake_engine.calls["guides"]) == 3


def test_panel_settings_reach_the_engine(fake_engine, tmp_path):
    run(tmp_path, screen_color="blue", despill_strength=0.3, clean_islands=False, despeckle_thresh=12,
        detail_intensity=1.5, proc_res="1024", despill_limit_mode="max")
    s = fake_engine.calls["settings"]
    assert (s.screen_color, s.despill_strength, s.auto_despeckle, s.despeckle_size, s.refiner_scale,
            s.image_size) == ("blue", 0.3, False, 12, 1.5, 1024)
    assert fake_engine.calls["limit"] == "max"


def test_every_exr_is_linear_and_processed_is_premultiplied(fake_engine, tmp_path):
    out = run(tmp_path)
    fg = backend._read_exr(str(out / "FG" / "frame_001001.exr"))
    assert abs(fg[0, 0, 0] - 0.214) < 0.002  # sRGB 0.5 -> linear
    proc = backend._read_exr(str(out / "Processed" / "frame_001001.exr"))
    assert proc.shape[2] == 4
    assert np.allclose(proc[..., :3], fg * proc[..., 3:4], atol=2e-3)


def test_guide_grows_and_matte_clean_up(fake_engine, tmp_path):
    out = run(tmp_path, mask_expansion=3, despeckle_blur=3, feather_radius=0)
    guide = cv2.imread(os.path.join(tmp_path, "ck", "Guide", fake_engine.calls["guides"][0]), cv2.IMREAD_UNCHANGED)
    assert (guide > 0).sum() > 21 * 21
    matte = backend._read_exr(str(out / "Matte" / "frame_001001.exr"))
    assert matte[0, 0] == 0  # speck removed


def test_without_a_matte_birefnet_makes_the_guide(fake_engine, tmp_path):
    run(tmp_path, wire_matte=False)
    assert fake_engine.calls.get("birefnet")


def test_log_handler_is_removed_after_each_run(fake_engine, tmp_path):
    before = len(logging.getLogger().handlers)
    run(tmp_path)
    assert len(logging.getLogger().handlers) == before


class KeyerNode:
    plugin_type, inputs, is_disabled = "corridor_keyer", [], False

    def __init__(self, choice):
        self.params = {"foreground_output": choice}


def test_output_choice_decides_what_the_next_node_gets(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    for sub in ("Output/FG", "Output/Processed"):
        (cache / sub).mkdir(parents=True)
        cv2.imwrite(str(cache / sub / "frame_001001.png"), np.zeros((4, 4, 3), np.uint8))
    monkeypatch.setattr(media_resolver, "get_node_cache", lambda n, c=None: str(cache))
    straight = media_resolver.output_path(KeyerNode("Straight RGB"), "Keyed RGBA")
    premult = media_resolver.output_path(KeyerNode("Premultiplied"), "Keyed RGBA")
    assert straight.endswith(os.path.join("Output", "FG"))
    assert premult.endswith(os.path.join("Output", "Processed"))

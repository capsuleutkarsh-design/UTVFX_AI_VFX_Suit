"""3D Tracker: frames named by plate number, In/Out, moving-object masks, fresh database,
the mapper ladder and registration choice, solve.json, local models only."""
import importlib
import json
import os

import cv2
import numpy as np
import pytest

from utvfx.core.plate import Plate

tracker = importlib.import_module("plugins.3DTracker.backend")
NUMBERS = list(range(1001, 1011))


@pytest.fixture
def plate_folder(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    rng = np.random.default_rng(1)
    texture = (rng.random((60, 90, 3)) * 255).astype(np.uint8)
    for n in NUMBERS:
        cv2.imwrite(str(src / f"shot.{n}.png"), np.roll(texture, n - 1001, axis=1))
    plate = Plate.prepare(str(src), str(tmp_path / "mp"))
    plate.ensure("png16")
    return plate.folder("png16")


@pytest.fixture
def matte_folder(tmp_path):
    folder = tmp_path / "matte"
    folder.mkdir()
    for n in NUMBERS:
        m = np.zeros((60, 90), np.uint16)
        m[20:40, 30:60] = 65535
        cv2.imwrite(str(folder / f"matte_{n:06d}.png"), m)
    return folder


def write_model(folder, numbers, points=50):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "cameras.txt"), "w") as f:
        f.write("1 SIMPLE_RADIAL 90 60 80 45 30 0.01\n")
    with open(os.path.join(folder, "images.txt"), "w") as f:
        for i, n in enumerate(numbers, 1):
            f.write(f"{i} 1 0 0 0 {i * 0.1} 0 0 1 frame_{n:06d}.jpg\n10 20 {i - 1}\n")
    with open(os.path.join(folder, "points3D.txt"), "w") as f:
        for i in range(points):
            f.write(f"{i} 0 0 {i} 128 128 128 0.5\n")


class FakeColmap:
    """Stands in for colmap.exe: the global mapper solves `global_frames`, the mapper solves all."""

    def __init__(self, global_frames, registered_all=True):
        self.global_frames = global_frames
        self.registered_all = registered_all
        self.calls = []

    def __call__(self, worker, args, check=True):
        self.calls.append(list(args))
        command = args[0]
        if command == "feature_extractor":
            assert not os.path.exists(args[args.index("--database_path") + 1])  # fresh database
            open(args[args.index("--database_path") + 1], "w").close()
        out = args[args.index("--output_path") + 1] if "--output_path" in args else None
        if command == "global_mapper" and self.global_frames:
            write_model(os.path.join(out, "0"), self.global_frames)
        if command == "mapper":
            write_model(os.path.join(out, "0"), NUMBERS[:9], points=80)
        if command == "image_registrator":
            write_model(out, NUMBERS if self.registered_all else NUMBERS[:9], points=80)
        return True


def run(tmp_path, monkeypatch, fake, plate_folder, matte=None, frame_range=None, **params):
    monkeypatch.setattr(tracker.TrackerWorker, "_run", lambda self, args, check=True: fake(self, args, check))
    monkeypatch.setattr(tracker, "model_error", lambda model, exe: 0.6)
    monkeypatch.setattr(tracker, "local_model", lambda name: os.path.join("models", "COLMAP", name))
    inputs = {"Video Plate": plate_folder}
    if matte:
        inputs["Moving Objects Matte"] = str(matte)
    w = tracker.TrackerWorker("t", params, inputs, str(tmp_path / "trk"), str(tmp_path))
    w.frame_range = frame_range
    logs = []
    w.log_message.connect(lambda n, m: logs.append(m))
    w.run_task()
    return tmp_path / "trk", logs


def test_frames_are_named_by_plate_number_and_masks_ignore_moving_objects(tmp_path, monkeypatch, plate_folder, matte_folder):
    fake = FakeColmap(NUMBERS)
    out, _ = run(tmp_path, monkeypatch, fake, plate_folder, matte=matte_folder)
    images = sorted(os.listdir(out / "work" / "images"))
    assert images[0] == "frame_001001.jpg" and len(images) == 10
    mask = cv2.imread(str(out / "work" / "masks" / "frame_001001.jpg.png"), cv2.IMREAD_GRAYSCALE)
    assert mask[30, 45] == 0 and mask[5, 5] == 255  # 0 = ignore the moving object
    extract = next(c for c in fake.calls if c[0] == "feature_extractor")
    assert "--ImageReader.mask_path" in extract


def test_in_out_limits_the_frames(tmp_path, monkeypatch, plate_folder):
    run(tmp_path, monkeypatch, FakeColmap(NUMBERS[2:6]), plate_folder, frame_range=(2, 5))
    assert sorted(os.listdir(tmp_path / "trk" / "work" / "images")) == [f"frame_{n:06d}.jpg" for n in NUMBERS[2:6]]


def test_ladder_runs_when_the_global_mapper_solves_too_little(tmp_path, monkeypatch, plate_folder):
    fake = FakeColmap(NUMBERS[:4])
    out, logs = run(tmp_path, monkeypatch, fake, plate_folder)
    commands = [c[0] for c in fake.calls]
    assert commands.index("global_mapper") < commands.index("mapper")
    assert "view_graph_calibrator" not in commands  # the global mapper solved something
    solve = json.load(open(out / "sparse" / "solve.json"))
    assert solve["registered"] == NUMBERS  # the mapper's 9, plus the registered frame
    assert solve["frames"]["frame_001001.jpg"] == 1001
    assert (out / "sparse" / "0" / "images.txt").exists()
    assert any("Kept the registered frames" in l for l in logs)


def test_no_ladder_when_the_global_mapper_solves_everything(tmp_path, monkeypatch, plate_folder):
    fake = FakeColmap(NUMBERS)
    run(tmp_path, monkeypatch, fake, plate_folder)
    assert "mapper" not in [c[0] for c in fake.calls]
    assert "image_registrator" not in [c[0] for c in fake.calls]


def test_too_few_frames_is_an_error_with_the_missing_ranges(tmp_path, monkeypatch, plate_folder):
    class Nothing(FakeColmap):
        def __call__(self, worker, args, check=True):
            if args[0] == "mapper":
                write_model(os.path.join(args[args.index("--output_path") + 1], "0"), NUMBERS[:3])
                return True
            if args[0] == "image_registrator":
                return False
            return super().__call__(worker, args, check)
    with pytest.raises(RuntimeError, match="1004-1010"):
        run(tmp_path, monkeypatch, Nothing(None), plate_folder)


def test_ai_features_use_local_models(tmp_path, monkeypatch, plate_folder):
    fake = FakeColmap(NUMBERS)
    run(tmp_path, monkeypatch, fake, plate_folder, features="ALIKED + LightGlue (AI)")
    extract = next(c for c in fake.calls if c[0] == "feature_extractor")
    match = next(c for c in fake.calls if c[0] == "sequential_matcher")
    assert extract[extract.index("--FeatureExtraction.type") + 1] == "ALIKED_N16ROT"
    assert extract[extract.index("--AlikedExtraction.n16rot_model_path") + 1].endswith("aliked-n16rot.onnx")
    assert match[match.index("--FeatureMatching.type") + 1] == "ALIKED_LIGHTGLUE"
    assert "--SequentialMatching.vocab_tree_path" not in match  # the vocabulary tree is for SIFT


def test_missing_model_says_how_to_install(monkeypatch, tmp_path):
    from utvfx.core.settings_manager import SettingsManager
    monkeypatch.setattr(SettingsManager(), "models_dir", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="SETUP"):
        tracker.local_model("aliked-n16rot.onnx")


def test_known_lens_sets_starting_intrinsics(tmp_path, monkeypatch, plate_folder):
    fake = FakeColmap(NUMBERS)
    run(tmp_path, monkeypatch, fake, plate_folder, focal_mm=35, sensor_width_mm=36)
    extract = next(c for c in fake.calls if c[0] == "feature_extractor")
    params = extract[extract.index("--ImageReader.camera_params") + 1].split(",")
    assert float(params[0]) == pytest.approx(35 / 36 * 90) and len(params) == 4  # SIMPLE_RADIAL: f, cx, cy, k


def test_a_collapsed_solve_is_not_accepted(tmp_path, monkeypatch, plate_folder):
    class Collapsed(FakeColmap):
        def __call__(self, worker, args, check=True):
            if args[0] == "global_mapper":
                write_model(os.path.join(args[args.index("--output_path") + 1], "0"), NUMBERS, points=3)
                return True
            return super().__call__(worker, args, check)
    fake = Collapsed(None)
    out, logs = run(tmp_path, monkeypatch, fake, plate_folder)
    assert "mapper" in [c[0] for c in fake.calls]  # the ladder ran instead of trusting 3 points
    assert json.load(open(out / "sparse" / "solve.json"))["points"] >= 30
    assert any("degenerate" in l for l in logs)

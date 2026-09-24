"""3D Camera Tracker: COLMAP 4.2 solve, built on the Automated Tracker's pipeline.

1. Frames   the plate's JPG working copy for the In/Out range, named frame_<plate number>.jpg
            (squeezed plates are de-squeezed to square pixels first).
2. Masks    optional: a matte of moving objects (people, cars) is turned into COLMAP masks,
            so features on them never steer the camera.
3. Features SIFT, SIFT + LightGlue, ALIKED + LightGlue or LoMa, from local pinned models
            (models/COLMAP; COLMAP would otherwise download them at run time).
4. Matching sequential, with vocabulary-tree loop detection for SIFT.
5. Mapping  the global mapper (GLOMAP) or the incremental mapper, then the Automated Tracker's
            retry ladder while under 90% of frames register, then registration of the
            missing frames, kept only if the reprojection error stays good.
6. Output   the chosen model in sparse/0 (binary + TXT) and sparse/solve.json with the frame
            numbers, image sizes, working scale and pixel aspect needed to export the camera.

Every run starts from an empty database, so a changed plate or setting never reuses old matches.
"""
import json
import os
import re
import shutil
import subprocess

import cv2
import numpy as np

from utvfx.bridge.base_worker import BaseWorker

from .colmap_tools.colmap_model import find_best_model, model_error, model_stats, registered_indices
from .colmap_tools.solve_rules import _should_adopt, frame_ranges

TRACKER_DIR = os.path.dirname(os.path.abspath(__file__))
COLMAP_DIR = os.path.join(TRACKER_DIR, "bin", "colmap-x64-windows-cuda")
COLMAP_EXE = os.path.join(COLMAP_DIR, "bin", "colmap.exe")

# (extractor, matcher, extraction model options, matching model options, max-features option)
FEATURES = {
    "SIFT (classic, fastest)": ("SIFT", "SIFT_BRUTEFORCE", {}, {}, "--SiftExtraction.max_num_features"),
    "SIFT + LightGlue": ("SIFT", "SIFT_LIGHTGLUE", {},
                         {"--SiftMatching.lightglue_model_path": "sift-lightglue.onnx"},
                         "--SiftExtraction.max_num_features"),
    "ALIKED + LightGlue (AI)": ("ALIKED_N16ROT", "ALIKED_LIGHTGLUE",
                                {"--AlikedExtraction.n16rot_model_path": "aliked-n16rot.onnx"},
                                {"--AlikedMatching.lightglue_model_path": "aliked-lightglue.onnx"},
                                "--AlikedExtraction.max_num_features"),
    "LoMa (AI, strongest, slow)": ("LOMA_B", "LOMA_B",
                                   {"--LomaExtraction.detector_model_path": "loma_detector.onnx",
                                    "--LomaExtraction.descriptor_model_path": "loma_descriptor_dedode_g.onnx"},
                                   {"--LomaMatching.b_model_path": "loma_matcher_B.onnx"},
                                   "--LomaExtraction.max_num_features"),
}
VOCAB_TREE = "vocab_tree_faiss_flickr100K_words256K.bin"
RETRY_BELOW = 0.9      # coverage under which the mapper ladder tries again
MIN_POINTS = 30        # fewer points than max(this, 2 per frame) = a collapsed solve
# COLMAP logs every step at INFO level; the node log keeps warnings, errors and these results.
KEEP_INFO = ("reconstruction(s)", "Registered images", "Mean reprojection error", "Global mapping failed",
             "No good initial image pair")
GLOG = re.compile(r"^[IWEF]\d{8} ")


def models_folder():
    from utvfx.core.settings_manager import SettingsManager
    return os.path.join(SettingsManager().models_dir, "COLMAP")


def local_model(name):
    path = os.path.join(models_folder(), name)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{name} is not installed. Run SETUP (first_setup.py) to download the tracker models.")
    return path


def camera_params(model, focal_px, width, height):
    """COLMAP's starting intrinsics for a known focal length: centred, no distortion."""
    cx, cy = width / 2.0, height / 2.0
    values = {"SIMPLE_PINHOLE": [focal_px, cx, cy], "SIMPLE_RADIAL": [focal_px, cx, cy, 0],
              "RADIAL": [focal_px, cx, cy, 0, 0], "PINHOLE": [focal_px, focal_px, cx, cy],
              "OPENCV": [focal_px, focal_px, cx, cy, 0, 0, 0, 0],
              "OPENCV_FISHEYE": [focal_px, focal_px, cx, cy, 0, 0, 0, 0]}[model]
    return ",".join(f"{v:.6g}" for v in values)


def cuda_library_dirs():
    import importlib.util
    spec = importlib.util.find_spec("torch")
    if spec is None or not spec.origin:
        return []
    lib = os.path.join(os.path.dirname(spec.origin), "lib")
    return [lib] if os.path.isfile(os.path.join(lib, "cublasLt64_12.dll")) else []


def mapper_args(tri_angle=2.5, inliers=40, abs_inliers=None, forward=1.0, trials=500, refine=True, extra=()):
    """The Automated Tracker's incremental mapper settings."""
    r = "1" if refine else "0"
    args = ["--Mapper.init_min_tri_angle", str(tri_angle), "--Mapper.init_min_num_inliers", str(inliers),
            "--Mapper.abs_pose_min_num_inliers", str(abs_inliers or max(15, inliers // 2)),
            "--Mapper.init_max_forward_motion", str(forward), "--Mapper.init_num_trials", str(trials),
            "--Mapper.ba_refine_focal_length", r, "--Mapper.ba_refine_extra_params", r,
            "--Mapper.ba_refine_principal_point", "0", "--Mapper.num_threads", str(os.cpu_count() or 4)]
    return args + list(extra)


class TrackerWorker(BaseWorker):
    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(node_id, params, inputs, cache_dir, output_dir, parent)
        self.in_dir = inputs.get("Video Plate")
        self.matte_dir = inputs.get("Moving Objects Matte")
        self.process = None
        self._rejected = set()
        self.env = os.environ.copy()
        # COLMAP's AI features run on ONNX Runtime, whose CUDA provider needs the CUDA 12 and cuDNN 9
        # libraries; PyTorch already ships them, so COLMAP is pointed at PyTorch's copy.
        self.env["PATH"] = os.pathsep.join([os.path.join(COLMAP_DIR, "bin"), *cuda_library_dirs(),
                                            self.env.get("PATH", "")])
        self.env["QT_PLUGIN_PATH"] = os.path.join(COLMAP_DIR, "plugins")

    def cancel(self):
        self.is_cancelled = True
        if self.process and self.process.poll() is None:
            self.process.kill()

    # ---- running COLMAP ---------------------------------------------------
    def _run(self, args, check=True):
        """Run one COLMAP command. Returns True on success; raises on failure when `check`."""
        if self.is_cancelled:
            return False
        cmd = [COLMAP_EXE] + [str(a) for a in args]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        text=True, encoding="utf-8", errors="replace", env=self.env, creationflags=flags)
        tail = []
        for line in self.process.stdout:
            line = line.rstrip()
            if not line:
                continue
            tail = (tail + [line])[-12:]
            if GLOG.match(line):
                if line[0] == "I" and not any(k in line for k in KEEP_INFO):
                    continue
                line = line.split("] ", 1)[-1] if line[0] == "I" else line
            self.log_message.emit(self.node_id, line)
        self.process.wait()
        code = self.process.returncode
        if self.is_cancelled:
            return False
        if code != 0 and check:
            raise RuntimeError(f"COLMAP {args[0]} failed (exit {code}):\n" + "\n".join(tail[-6:]))
        return code == 0

    # ---- 1-2. frames and masks ---------------------------------------------
    def _prepare_frames(self, images_dir, masks_dir):
        from utvfx.core.plate import find_sequence, plate_for_folder, tier_folder

        if not self.in_dir or not os.path.isdir(self.in_dir):
            raise Exception("The tracker needs an image sequence: wire a Media Plate into Video Plate.")
        plate = plate_for_folder(self.in_dir)
        jpg_dir = tier_folder(self.in_dir, "jpg", cancelled=lambda: self.is_cancelled)
        sequence = find_sequence(jpg_dir)
        if len(sequence) < 3:
            raise Exception("The tracker needs at least 3 frames.")
        sequence = [sequence[i] for i in self.positions(len(sequence))]
        pixel_aspect = float(plate.m.get("pixel_aspect", 1.0)) if plate else 1.0
        working_scale = float(plate.m.get("working_scale", 1.0)) if plate else 1.0

        mattes = {}
        if self.matte_dir and os.path.isdir(self.matte_dir):
            mattes = dict(find_sequence(self.matte_dir))
        grow = int(self.params.get("mask_grow", 8) or 0)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)) if grow > 0 else None

        for folder in (images_dir, masks_dir):
            shutil.rmtree(folder, ignore_errors=True)
            os.makedirs(folder)
        names, size, masked = {}, None, 0
        for number, path in sequence:
            if self.is_cancelled:
                return None
            name = f"frame_{number:06d}.jpg"
            dst = os.path.join(images_dir, name)
            if abs(pixel_aspect - 1.0) > 1e-3:
                # COLMAP assumes square pixels: de-squeeze, as the Automated Tracker does.
                img = cv2.imread(path, cv2.IMREAD_COLOR)
                img = cv2.resize(img, (round(img.shape[1] * pixel_aspect), img.shape[0]), interpolation=cv2.INTER_CUBIC)
                cv2.imwrite(dst, img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            else:
                try:
                    os.link(path, dst)
                except OSError:
                    shutil.copy2(path, dst)
            if size is None:
                h, w = cv2.imread(dst, cv2.IMREAD_GRAYSCALE).shape
                size = (w, h)
            names[name] = number
            if number in mattes:
                # COLMAP masks: 0 = ignore these pixels, 255 = use them. Grown so edges are ignored too.
                m = cv2.imread(mattes[number], cv2.IMREAD_GRAYSCALE)
                moving = (cv2.resize(m, size, interpolation=cv2.INTER_LINEAR) > 127).astype(np.uint8) * 255
                if kernel is not None:
                    moving = cv2.dilate(moving, kernel)
                cv2.imwrite(os.path.join(masks_dir, name + ".png"), 255 - moving)
                masked += 1
        if mattes and masked < len(names):
            self.log_message.emit(self.node_id, f"The moving-objects matte covers {masked} of {len(names)} frames.")
        return {"names": names, "size": size, "pixel_aspect": pixel_aspect, "working_scale": working_scale,
                "masked": masked, "plate": plate}

    # ---- 3-5. solve ----------------------------------------------------------
    def _best(self, folders):
        """The model with the most frames (then points) among those that are real solves."""
        found = []
        for folder in folders:
            model = find_best_model(folder) if os.path.isdir(folder) else None
            if model is None:
                continue
            images, points = model_stats(model)
            if points < max(MIN_POINTS, 2 * images):
                # A handful of points "explaining" every camera is a collapsed solve, not a track.
                if model not in self._rejected:
                    self._rejected.add(model)
                    self.log_message.emit(self.node_id, f"Ignoring a degenerate solve ({images} frames but only "
                                                        f"{points} points) from {os.path.basename(folder)}.")
                continue
            found.append(model)
        return max(found, key=lambda m: model_stats(m), default=None)

    def run_task(self):
        work = os.path.join(self.cache_dir, "work")
        out = os.path.join(self.cache_dir, "sparse")
        for folder in (work, out):
            shutil.rmtree(folder, ignore_errors=True)  # never reuse an old database or model
        os.makedirs(work)
        images_dir, masks_dir = os.path.join(work, "images"), os.path.join(work, "masks")
        db = os.path.join(work, "database.db")

        feature_name = self.params.get("features", "SIFT (classic, fastest)")
        if feature_name not in FEATURES:
            feature_name = "SIFT (classic, fastest)"
        extractor, matcher, ext_models, match_models, max_opt = FEATURES[feature_name]
        camera_model = self.params.get("camera_model", "SIMPLE_RADIAL")
        refine = bool(self.params.get("refine_lens", True))
        solver = self.params.get("solver", "Global (GLOMAP, fast)")

        self.log_message.emit(self.node_id, "Preparing frames...")
        prep = self._prepare_frames(images_dir, masks_dir)
        if prep is None:
            return
        total = len(prep["names"])
        self.progress_update.emit(self.node_id, 5, 100)

        self.log_message.emit(self.node_id, f"Finding features ({feature_name}) in {total} frames...")
        args = ["feature_extractor", "--database_path", db, "--image_path", images_dir,
                "--ImageReader.camera_model", camera_model, "--ImageReader.single_camera", "1",
                "--FeatureExtraction.type", extractor, "--FeatureExtraction.use_gpu", "1",
                "--FeatureExtraction.max_image_size", str(int(self.params.get("max_image_size", 3200))),
                max_opt, str(int(self.params.get("max_features", 8192)))]
        for option, name in ext_models.items():
            args += [option, local_model(name)]
        focal_mm = float(self.params.get("focal_mm", 0) or 0)
        if focal_mm > 0:
            # A known lens: the solve starts from it (and still refines it if Refine is on).
            sensor_mm = float(self.params.get("sensor_width_mm", 24.89) or 24.89)
            focal_px = focal_mm / sensor_mm * prep["size"][0]
            args += ["--ImageReader.camera_params", camera_params(camera_model, focal_px, *prep["size"])]
            self.log_message.emit(self.node_id, f"Starting from a {focal_mm:g} mm lens on a {sensor_mm:g} mm "
                                                f"wide sensor ({focal_px:.0f} px).")
        if prep["masked"]:
            args += ["--ImageReader.mask_path", masks_dir]
        if not self._run(args):
            return
        self.progress_update.emit(self.node_id, 25, 100)

        self.log_message.emit(self.node_id, "Matching frames...")
        args = ["sequential_matcher", "--database_path", db, "--FeatureMatching.type", matcher,
                "--FeatureMatching.use_gpu", "1", "--SequentialMatching.overlap", str(int(self.params.get("overlap", 35)))]
        for option, name in match_models.items():
            args += [option, local_model(name)]
        if extractor == "SIFT" and self.params.get("loop_detection", True):
            args += ["--SequentialMatching.loop_detection", "1",
                     "--SequentialMatching.vocab_tree_path", local_model(VOCAB_TREE)]
        if not self._run(args):
            return
        self.progress_update.emit(self.node_id, 45, 100)

        candidates = []
        if solver.startswith("Global"):
            r = "1" if refine else "0"

            def global_map(database, folder_name):
                folder = os.path.join(work, folder_name)
                os.makedirs(folder)
                self._run(["global_mapper", "--database_path", database, "--image_path", images_dir,
                           "--output_path", folder, "--GlobalMapper.ba_refine_focal_length", r,
                           "--GlobalMapper.ba_refine_extra_params", r], check=False)
                candidates.append(folder)
                return self._best([folder])

            self.log_message.emit(self.node_id, "Solving with the global mapper (GLOMAP)...")
            if global_map(db, "sparse_global") is None and not self.is_cancelled:
                # COLMAP suggests estimating focal lengths first, but on well-behaved shots it can
                # discard good pairs, so it is only the second try, on a copy of the database.
                self.log_message.emit(self.node_id, "Global mapper failed; retrying with focal-length calibration...")
                calibrated = os.path.join(work, "database_calibrated.db")
                shutil.copy2(db, calibrated)
                self._run(["view_graph_calibrator", "--database_path", calibrated], check=False)
                global_map(calibrated, "sparse_global_calibrated")
        if self.is_cancelled:
            return

        ladder = [("sparse", mapper_args(refine=refine)),
                  ("sparse_wide", mapper_args(8, 60, 15, refine=refine)),
                  ("sparse_relaxed", mapper_args(0.5, 15, 10, trials=1000, refine=refine,
                                                 extra=["--Mapper.filter_min_tri_angle", "0.5"]))]
        for folder_name, extra in ladder:
            best = self._best(candidates)
            have = model_stats(best)[0] if best else 0
            if have >= RETRY_BELOW * total:
                break
            if candidates:
                self.log_message.emit(self.node_id, f"{have} of {total} frames solved; trying the incremental "
                                                    f"mapper ({folder_name.replace('sparse_', '') or 'standard'})...")
            folder = os.path.join(work, folder_name)
            os.makedirs(folder)
            self._run(["mapper", "--database_path", db, "--image_path", images_dir, "--output_path", folder] + extra,
                      check=False)
            candidates.append(folder)
            if self.is_cancelled:
                return
        self.progress_update.emit(self.node_id, 80, 100)

        best = self._best(candidates)
        if best is None:
            raise RuntimeError("COLMAP could not solve a camera for this shot. Try ALIKED + LightGlue, a "
                               "moving-objects matte, or a longer range with more camera movement.")
        stats, error = model_stats(best), model_error(best, COLMAP_EXE)

        if stats[0] < total:
            self.log_message.emit(self.node_id, f"Registering the {total - stats[0]} frames the mapper skipped...")
            reg = os.path.join(work, "sparse_registered")
            os.makedirs(reg)
            if self._run(["image_registrator", "--database_path", db, "--input_path", best, "--output_path", reg],
                         check=False) and self._run(["bundle_adjuster", "--input_path", reg, "--output_path", reg],
                                                    check=False):
                new_stats, new_error = model_stats(reg), model_error(reg, COLMAP_EXE)
                adopt, reason = _should_adopt(stats, error, new_stats, new_error)
                self.log_message.emit(self.node_id, ("Kept the registered frames: " if adopt else "Registration not used: ") + reason)
                if adopt:
                    best, stats, error = reg, new_stats, new_error
        if self.is_cancelled:
            return
        self.progress_update.emit(self.node_id, 90, 100)

        numbers = registered_indices(best)
        missing = sorted(set(prep["names"].values()) - set(numbers))
        min_coverage = float(self.params.get("min_coverage", 0.5))
        if len(numbers) < 3 or len(numbers) < min_coverage * total:
            raise RuntimeError(f"Only {len(numbers)} of {total} frames solved (need {int(min_coverage * 100)}%). "
                               f"Unsolved: {frame_ranges(missing)}.")
        if missing:
            self.log_message.emit(self.node_id, f"No camera for frames {frame_ranges(missing)}.")

        final = os.path.join(out, "0")
        shutil.copytree(best, final)
        self._run(["model_converter", "--input_path", final, "--output_path", final, "--output_type", "TXT"])
        plate = prep["plate"]
        solve = {
            "version": 1,
            "features": feature_name, "solver": solver, "camera_model": camera_model,
            "frames": prep["names"], "registered": numbers, "missing": missing,
            "image_width": prep["size"][0], "image_height": prep["size"][1],
            "plate_width": plate.m["width"] if plate else None, "plate_height": plate.m["height"] if plate else None,
            "working_scale": prep["working_scale"], "pixel_aspect": prep["pixel_aspect"],
            "fps": plate.m.get("fps") if plate else None,
            "plate_cache": plate.cache_dir if plate else None,
            "reprojection_error": error, "points": model_stats(final)[1],
            "mapper": os.path.basename(os.path.dirname(os.path.normpath(best)))
                      if os.path.basename(os.path.normpath(best)).isdigit() else os.path.basename(os.path.normpath(best)),
        }
        with open(os.path.join(out, "solve.json"), "w", encoding="utf-8") as f:
            json.dump(solve, f, indent=2)
        self.progress_update.emit(self.node_id, 100, 100)
        err = f", reprojection error {error:.2f} px" if error is not None else ""
        self.log_message.emit(self.node_id, f"Solved {len(numbers)} of {total} frames, {solve['points']} points{err}.")

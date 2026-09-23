"""CorridorKey: AI green/blue screen keyer, wrapped for the node graph.

Around the vendored engine (plugins/CorridorKey/System, not edited) this worker:
  - prepares the input: the frames in the In/Out range, optionally the linear plate
    instead of the display copy, optionally denoised;
  - prepares the guide matte: the wired Alpha Matte or a BiRefNet auto-matte, grown
    or shrunk by Mask expansion;
  - runs the engine with every panel setting, including the despill limit mode;
  - post-processes: despeckle blur, feather and temporal anti-flicker on the matte,
    then writes every EXR as linear (the engine writes its foreground sRGB-encoded) and
    rebuilds the premultiplied RGBA and the preview comp (optionally over a custom
    background).

Outputs, in the node's cache under Output/: FG (straight, linear EXR), Matte (linear
EXR), Processed (premultiplied linear RGBA EXR) and Comp (8-bit PNG preview).
"""
import logging
import os
import shutil
import sys

import cv2
import numpy as np

CURRENT_DIR = os.path.dirname(__file__)
SYSTEM_DIR = os.path.join(CURRENT_DIR, "System")
if SYSTEM_DIR not in sys.path:
    sys.path.append(SYSTEM_DIR)

from utvfx.bridge.base_worker import BaseWorker  # noqa: E402
from utvfx.core import exr  # noqa: E402

_DESPILL_LIMIT = {"mode": "average"}


def _use_shared_models_dir():
    """Point the vendored CorridorKey and BiRefNet modules at the suite's models folder."""
    from utvfx.core.settings_manager import SettingsManager
    from utvfx.core.downloads import require_local_model
    import CorridorKeyModule.backend as ck_backend
    import BiRefNetModule.wrapper as birefnet_wrapper
    from transformers import AutoModelForImageSegmentation

    models_dir = SettingsManager().models_dir
    ck_backend.CHECKPOINT_DIR = os.path.join(models_dir, "CorridorKey")
    birefnet_wrapper.base_folder = os.path.join(models_dir, "BiRefNet")

    # H9: the wrapper (a submodule we don't edit) calls snapshot_download on every run,
    # which would fetch whatever the author last pushed. Replace it with a check that the
    # pinned files from first_setup.py are in models/BiRefNet/<name> and that the Python
    # files transformers will execute are the reviewed ones. Nothing is downloaded.
    def _local_birefnet_only(repo_id=None, local_dir=None, **_ignored):
        return require_local_model(local_dir, kind="BiRefNet")

    birefnet_wrapper.snapshot_download = _local_birefnet_only

    # BiRefNet ships its model code (birefnet.py) with its weights, and transformers only
    # loads such code with trust_remote_code=True. That stays on, because the code it runs
    # is the local copy from the pinned revision in first_setup.py, checked above against
    # reviewed hashes; local_files_only stops transformers from fetching anything.
    class _BiRefNetLoader:
        @staticmethod
        def from_pretrained(path, **kwargs):
            kwargs["trust_remote_code"] = True
            kwargs["local_files_only"] = True
            return AutoModelForImageSegmentation.from_pretrained(path, **kwargs)

    birefnet_wrapper.AutoModelForImageSegmentation = _BiRefNetLoader

    import CorridorKeyModule.core.color_utils as cu
    _patch_despill(cu)


def _patch_despill(cu):
    """The engine hard-codes limit_mode="average"; route the panel's choice through."""
    if getattr(cu.despill_opencv, "_contour_patched", False):
        return
    original = cu.despill_opencv

    def despill_with_panel_limit(image, limit_mode="average", *args, **kwargs):
        return original(image, _DESPILL_LIMIT["mode"], *args, **kwargs)

    despill_with_panel_limit._contour_patched = True
    cu.despill_opencv = despill_with_panel_limit


def _link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _read_exr(path):
    """An EXR as float32, channels in OpenCV order (BGR / BGRA); a single channel stays 2-D."""
    img, _ = exr.read(path)
    if img.shape[2] == 1:
        return img[..., 0]
    order = [2, 1, 0] + ([3] if img.shape[2] > 3 else [])
    return np.ascontiguousarray(img[..., order])


def _write_exr(path, img, chromaticities=None):
    """Write a half-float EXR from an OpenCV-ordered array (gray, BGR or BGRA)."""
    img = np.asarray(img, np.float32)
    if img.ndim == 2:
        exr.write(path, img, ("Y",))
    elif img.shape[2] == 3:
        exr.write(path, img[..., [2, 1, 0]], ("R", "G", "B"), chromaticities=chromaticities)
    else:
        exr.write(path, img[..., [2, 1, 0, 3]], ("R", "G", "B", "A"), chromaticities=chromaticities)


REC709_CHROMATICITIES = exr.REC709_CHROMATICITIES


def _srgb_to_linear(x):
    x = np.clip(x, 0.0, None)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def _blend_with_previous(alpha, prev_alpha, gray, prev_gray, weight):
    """Mix in the previous matte, moved to where the image moved (flow current -> previous)."""
    flow = cv2.calcOpticalFlowFarneback(gray, prev_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    h, w = gray.shape
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    warped = cv2.remap(prev_alpha, gx + flow[..., 0], gy + flow[..., 1], cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_REPLICATE)
    return (1.0 - weight) * alpha + weight * warped


class CorridorKeyWorker(BaseWorker):
    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(node_id, params, inputs, cache_dir, output_dir, parent)
        self.video_path = inputs.get("Video Plate")
        self.mask_path = inputs.get("Alpha Matte")

    @staticmethod
    def _get_asset_type(path):
        if os.path.isdir(path):
            return "sequence"
        return "video" if os.path.splitext(path)[1].lower() in (".mp4", ".mov", ".avi", ".mkv", ".mxf") else "sequence"

    # ---- input --------------------------------------------------------------
    def _prepare_input(self, folder):
        """The frames to key, in the In/Out range, as a folder the engine reads in order."""
        from utvfx.core import colour
        from utvfx.core.plate import find_sequence, plate_for_folder

        plate = plate_for_folder(self.video_path) if os.path.isdir(self.video_path) else None
        seq = find_sequence(self.video_path) if (os.path.isdir(self.video_path) or plate) else []
        if not seq:
            if self.frame_range:
                self.log_message.emit(self.node_id, "In/Out needs an image sequence; keying the whole clip.")
            return self.video_path, False, None
        seq = [seq[i] for i in self.positions(len(seq))]

        use_linear = bool(self.params.get("input_linear", False))
        if use_linear and (plate is None or colour.is_display_referred(plate.colourspace)):
            self.log_message.emit(self.node_id, "The plate is display-referred (video/sRGB); keying the display copy.")
            use_linear = False
        if use_linear and not plate.has("master"):
            plate.ensure("master", cancelled=lambda: self.is_cancelled)
        noise = float(self.params.get("sensor_noise", 0) or 0)

        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder)
        if use_linear:
            # The engine expects linear Rec.709 primaries; the plate may be ACES or a camera log.
            masters = dict(zip(plate.frame_numbers, plate.paths("master")))
            for number, _ in seq:
                if self.is_cancelled:
                    return None, False, None
                lin = colour.convert(colour.read_image(masters[number])[0][..., :3],
                                     plate.colourspace, colour.LINEAR_REC709)
                _write_exr(os.path.join(folder, f"frame_{number:06d}.exr"), lin[..., ::-1], REC709_CHROMATICITIES)
            self.log_message.emit(self.node_id, f"Keying the linear plate ({plate.colourspace} -> linear Rec.709).")
        else:
            for number, path in seq:
                if self.is_cancelled:
                    return None, False, None
                dst = os.path.join(folder, os.path.basename(path))
                if noise > 0:
                    img = cv2.imread(path, cv2.IMREAD_COLOR)
                    img = cv2.fastNlMeansDenoisingColored(img, None, noise, noise, 5, 15)
                    cv2.imwrite(dst, img)
                else:
                    _link_or_copy(path, dst)
            if noise > 0:
                self.log_message.emit(self.node_id, f"Reduced sensor noise (strength {noise:g}) before keying.")
        return folder, use_linear, [n for n, _ in seq]

    def _prepare_guide(self, folder, numbers, source):
        """The guide matte for the frames being keyed, grown or shrunk by Mask expansion."""
        from utvfx.core.plate import find_sequence
        expand = int(self.params.get("mask_expansion", 0) or 0)
        guides = dict(find_sequence(source)) if os.path.isdir(source) else {}
        if numbers is not None and guides:
            missing = [n for n in numbers if n not in guides]
            if missing:
                raise Exception(f"The guide matte has no frame {missing[0]}.")
        if not expand and (numbers is None or not guides or len(guides) == len(numbers)):
            return source
        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * abs(expand) + 1, 2 * abs(expand) + 1)) if expand else None
        for number in (numbers if numbers is not None else sorted(guides)):
            m = cv2.imread(guides[number], cv2.IMREAD_UNCHANGED)
            if kernel is not None:
                m = cv2.dilate(m, kernel) if expand > 0 else cv2.erode(m, kernel)
            cv2.imwrite(os.path.join(folder, f"frame_{number:06d}{os.path.splitext(guides[number])[1]}"), m)
        return folder

    # ---- output -------------------------------------------------------------
    def _post_process(self, out_root):
        """Matte clean-up, linear FG, rebuilt Processed and Comp."""
        from utvfx.core.plate import find_sequence

        blur = int(self.params.get("despeckle_blur", 0) or 0)
        feather = float(self.params.get("feather_radius", 0) or 0)
        flicker = float(self.params.get("temporal_anti_flicker", 0) or 0)
        bg_path = self.params.get("custom_bg") or ""
        bg_img = cv2.imread(bg_path, cv2.IMREAD_COLOR) if bg_path and os.path.isfile(bg_path) else None
        if bg_path and bg_img is None:
            self.log_message.emit(self.node_id, f"Custom background not found: {bg_path}")

        fg_dir, matte_dir = os.path.join(out_root, "FG"), os.path.join(out_root, "Matte")
        proc_dir, comp_dir = os.path.join(out_root, "Processed"), os.path.join(out_root, "Comp")
        os.makedirs(proc_dir, exist_ok=True)
        os.makedirs(comp_dir, exist_ok=True)
        prev = None
        for number, matte_path in find_sequence(matte_dir):
            if self.is_cancelled:
                return
            stem = os.path.splitext(os.path.basename(matte_path))[0]
            alpha = _read_exr(matte_path)
            if alpha.ndim == 3:
                alpha = alpha[..., 0]
            fg_srgb = _read_exr(os.path.join(fg_dir, stem + ".exr"))[..., :3]
            gray = cv2.cvtColor(np.clip(fg_srgb * 255, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY)

            if blur > 0:
                # Median removes specks and pin-holes without softening straight edges;
                # float mattes only take kernel 3 or 5, so larger values repeat it.
                alpha = alpha.astype(np.float32)
                for _ in range(max(1, blur // 5)):
                    alpha = cv2.medianBlur(alpha, 5 if blur >= 5 else 3)
            if feather > 0:
                alpha = cv2.GaussianBlur(alpha, (0, 0), feather)
            if flicker > 0 and prev is not None:
                alpha = _blend_with_previous(alpha, prev[0], gray, prev[1], 0.5 * flicker)
            prev = (alpha, gray)
            alpha = np.clip(alpha, 0.0, 1.0).astype(np.float32)

            fg_lin = _srgb_to_linear(fg_srgb)  # EXR is linear everywhere in the app
            _write_exr(os.path.join(fg_dir, stem + ".exr"), fg_lin, REC709_CHROMATICITIES)
            _write_exr(matte_path, alpha)
            _write_exr(os.path.join(proc_dir, stem + ".exr"), np.dstack([fg_lin * alpha[..., None], alpha]),
                       REC709_CHROMATICITIES)

            # The engine's own preview comp shows the matte before the clean-up above.
            if bg_img is not None or blur > 0 or feather > 0 or flicker > 0:
                h, w = alpha.shape
                if bg_img is not None:
                    bg = cv2.resize(bg_img, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
                else:
                    yy, xx = np.mgrid[0:h, 0:w]
                    bg = np.where((((yy // 32) + (xx // 32)) % 2)[..., None] == 0, 0.30, 0.18).astype(np.float32)
                    bg = np.repeat(bg, 3, axis=2)
                comp = fg_srgb * alpha[..., None] + bg * (1.0 - alpha[..., None])
                cv2.imwrite(os.path.join(comp_dir, stem + ".png"), np.clip(comp * 255 + 0.5, 0, 255).astype(np.uint8))

    # ---- run ----------------------------------------------------------------
    def run_task(self):
        from clip_manager import ClipAsset, ClipEntry, InferenceSettings, run_inference, run_birefnet
        _use_shared_models_dir()
        _DESPILL_LIMIT["mode"] = self.params.get("despill_limit_mode", "average")

        class UISignalHandler(logging.Handler):
            def __init__(self, worker):
                super().__init__(logging.INFO)
                self.worker = worker

            def emit(self, record):
                self.worker.log_message.emit(self.worker.node_id, self.format(record))

        handler = UISignalHandler(self)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            self._run(ClipAsset, ClipEntry, InferenceSettings, run_inference, run_birefnet)
        finally:
            root_logger.removeHandler(handler)  # one handler per run, not one more each time

    def _run(self, ClipAsset, ClipEntry, InferenceSettings, run_inference, run_birefnet):
        if not self.video_path or not os.path.exists(self.video_path):
            raise FileNotFoundError("Video path is invalid or missing.")
        self.log_message.emit(self.node_id, "Initializing CorridorKey pipeline...")

        out_root = os.path.join(self.cache_dir, "Output")
        shutil.rmtree(out_root, ignore_errors=True)  # never mix frames from an older render
        input_path, is_linear, numbers = self._prepare_input(os.path.join(self.cache_dir, "Input"))
        if self.is_cancelled or input_path is None:
            return

        clip = ClipEntry("NodeExecution", self.cache_dir)
        clip.input_asset = ClipAsset(input_path, self._get_asset_type(input_path))

        def on_frame(current, total):
            if self.is_cancelled:
                raise InterruptedError("Execution cancelled by user.")
            self.progress_update.emit(self.node_id, current, total)

        def on_start(name, total):
            self.log_message.emit(self.node_id, f"Processing {name}: {total} frames")

        if self.mask_path and os.path.exists(self.mask_path):
            guide = self._prepare_guide(os.path.join(self.cache_dir, "Guide"), numbers, self.mask_path)
        else:
            self.log_message.emit(self.node_id, "No guide matte wired. Making one with BiRefNet...")
            alpha_dir = os.path.join(self.cache_dir, "AlphaHint")
            shutil.rmtree(alpha_dir, ignore_errors=True)
            run_birefnet([clip], device=None, usage="General", dilate_radius=0,
                         on_clip_start=on_start, on_frame_complete=on_frame)
            if not os.path.isdir(alpha_dir) or not os.listdir(alpha_dir):
                raise RuntimeError("BiRefNet auto-matte generation failed.")
            guide = self._prepare_guide(os.path.join(self.cache_dir, "Guide"), None, alpha_dir)
        clip.alpha_asset = ClipAsset(guide, "sequence")

        screen = self.params.get("screen_color", "auto")
        settings = InferenceSettings(
            input_is_linear=is_linear,
            despill_strength=float(self.params.get("despill_strength", 0.5)),
            auto_despeckle=bool(self.params.get("clean_islands", True)),
            despeckle_size=int(self.params.get("despeckle_thresh", 400)),
            refiner_scale=float(self.params.get("detail_intensity", 1.0)),
            generate_comp=True,
            gpu_post_processing=False,
            image_size=int(self.params.get("proc_res", 2048)),
            screen_color=screen if screen in ("auto", "green", "blue") else "auto",
        )
        self.log_message.emit(self.node_id, "Running CorridorKey core inference...")
        run_inference([clip], device=None, backend="torch", settings=settings,
                      on_clip_start=on_start, on_frame_complete=on_frame)
        if self.is_cancelled:
            return
        self.log_message.emit(self.node_id, "Cleaning up the matte and writing linear EXRs...")
        self._post_process(out_root)
        self.log_message.emit(self.node_id, "CorridorKey pipeline complete.")

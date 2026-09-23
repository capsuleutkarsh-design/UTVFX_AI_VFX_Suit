"""Depth Anything V2 depth maps for a plate.

Output (the node's cache):
  Depth/depth_<frame>.exr  - one float channel "Z", plate frame numbers.
      Relative: 0-1 over the whole shot, near = 1 (or near = 0, a panel option).
      Metric:   distance from the camera in metres (indoor or outdoor model).
  Preview/depth_<frame>.png - 8-bit picture for the viewer (contrast and colormap only here).

The relative model predicts depth up to an unknown scale and offset that change from
frame to frame; normalising each frame on its own makes the whole map pump. Each frame
is instead fitted (scale + offset) to the previous result, moved along the optical flow,
and the whole shot is normalised once at the end.
"""
import importlib
import os
import shutil
import sys
import types

import cv2
import numpy as np
import torch

from utvfx.bridge.base_worker import BaseWorker
from utvfx.core import exr

plugins_dir = os.path.dirname(os.path.dirname(__file__))
depth_v2_dir = os.path.join(plugins_dir, "Depth-Anything-V2")
if not os.path.exists(depth_v2_dir):
    raise ImportError(f"Missing required vendored repository: {depth_v2_dir}. Please ensure the Depth-Anything-V2 folder exists.")
if depth_v2_dir not in sys.path:
    sys.path.append(depth_v2_dir)

MODEL_CONFIGS = {
    'vits': {'encoder': 'vits', 'features': 64, 'out_channels': [48, 96, 192, 384]},
    'vitb': {'encoder': 'vitb', 'features': 128, 'out_channels': [96, 192, 384, 768]},
    'vitl': {'encoder': 'vitl', 'features': 256, 'out_channels': [256, 512, 1024, 1024]},
}
# Metric models: which weights, and the furthest depth each was trained for (metres).
METRIC = {"indoor": ("hypersim", 20.0), "outdoor": ("vkitti", 80.0)}
FLOW_WIDTH = 480  # frames are aligned at this width: enough for the fit, cheap to compute


def _metric_class():
    """The metric DepthAnythingV2 class. Its package has the same name as the relative one."""
    name = "depth_anything_v2_metric"
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [os.path.join(depth_v2_dir, "metric_depth", "depth_anything_v2")]
        sys.modules[name] = package
    return importlib.import_module(f"{name}.dpt").DepthAnythingV2


def weights_path(model_size, metric=None):
    from utvfx.core.settings_manager import SettingsManager
    folder = os.path.join(SettingsManager().models_dir, "DepthAnythingV2")
    if metric:
        name = f"depth_anything_v2_metric_{METRIC[metric][0]}_{model_size}.pth"
    else:
        name = f"depth_anything_v2_{model_size}.pth"
    path = os.path.join(folder, name)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{name} is not installed. Run SETUP (first_setup.py) to download the depth models.")
    return path


def load_model(model_size="vits", metric=None, device="cuda"):
    if metric:
        model = _metric_class()(**MODEL_CONFIGS[model_size], max_depth=METRIC[metric][1])
    else:
        from depth_anything_v2.dpt import DepthAnythingV2
        model = DepthAnythingV2(**MODEL_CONFIGS[model_size])
    model.load_state_dict(torch.load(weights_path(model_size, metric), map_location='cpu', weights_only=True))
    return model.to(device).eval()


def _small_gray(bgr):
    h, w = bgr.shape[:2]
    scale = min(1.0, FLOW_WIDTH / w)
    small = cv2.resize(bgr, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def _warp_previous(prev_small, gray, prev_gray):
    """The previous result moved to where the image is now (flow from current to previous)."""
    flow = cv2.calcOpticalFlowFarneback(gray, prev_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    h, w = gray.shape
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    return cv2.remap(prev_small, gx + flow[..., 0], gy + flow[..., 1], cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)


def fit_scale_offset(source, target):
    """Robust least squares for s, b in s * source + b = target (worst 20% of pixels ignored)."""
    x, y = source.ravel().astype(np.float64), target.ravel().astype(np.float64)
    keep = np.ones_like(x, bool)
    s, b = 1.0, 0.0
    for _ in range(2):
        A = np.stack([x[keep], np.ones(keep.sum())], axis=1)
        (s, b), *_ = np.linalg.lstsq(A, y[keep], rcond=None)
        residual = np.abs(s * x + b - y)
        keep = residual <= np.percentile(residual, 80)
    return float(s), float(b)


class DepthWorker(BaseWorker):
    """Dense depth for every frame of the plate."""

    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(node_id, params, inputs, cache_dir, output_dir, parent)
        self.video_path = inputs.get("Video Plate")

    def run_task(self):
        from utvfx.core.image_utils import load_frame
        from utvfx.core.plate import find_sequence

        if not self.video_path or not os.path.isdir(self.video_path):
            raise Exception("Depth needs an image sequence: wire a Media Plate into Video Plate.")
        sequence = find_sequence(self.video_path)
        if not sequence:
            raise Exception(f"No frames found in {self.video_path}.")
        sequence = [sequence[i] for i in self.positions(len(sequence))]

        size_str = self.params.get("model_size", "Small (vits)")
        model_size = "vits" if "vits" in size_str else "vitb" if "vitb" in size_str else "vitl"
        size_str = str(self.params.get("input_size", "518 (Fast)"))
        input_size = 1008 if "1008" in size_str else 742 if "742" in size_str else 518
        kind = str(self.params.get("depth_type", "Relative"))
        metric = "indoor" if "indoor" in kind.lower() else "outdoor" if "outdoor" in kind.lower() else None
        near_is_one = not str(self.params.get("near_value", "Near = 1")).startswith("Near = 0")
        smoothing = float(self.params.get("temporal_smoothing", 0.1))
        blur = float(self.params.get("blur_radius", 0) or 0)

        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.log_message.emit(self.node_id, f"Loading Depth Anything V2 ({model_size}, "
                                            f"{'metric ' + metric if metric else 'relative'}) on {device}...")
        model = load_model(model_size, metric, device)

        depth_dir = os.path.join(self.cache_dir, "Depth")
        preview_dir = os.path.join(self.cache_dir, "Preview")
        for folder in (depth_dir, preview_dir):
            shutil.rmtree(folder, ignore_errors=True)
            os.makedirs(folder)
        for f in os.listdir(self.cache_dir):  # 8-bit maps from older versions
            if f.startswith("depth_") and f.endswith(".png"):
                os.remove(os.path.join(self.cache_dir, f))

        prev = None  # (aligned result at flow size, gray at flow size)
        low, high = [], []
        total = len(sequence)
        for i, (number, path) in enumerate(sequence):
            if self.is_cancelled:
                return
            frame = load_frame(path)
            if frame is None:
                raise Exception(f"Could not read {path}.")
            frame = frame[..., :3]
            with torch.no_grad():
                raw = model.infer_image(frame, input_size=input_size).astype(np.float32)

            gray = _small_gray(frame)
            small = cv2.resize(raw, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_AREA)
            if metric:
                result = raw
                if prev is not None and smoothing > 0:
                    warped = _warp_previous(prev[0], gray, prev[1])
                    up = cv2.resize(warped, (raw.shape[1], raw.shape[0]), interpolation=cv2.INTER_LINEAR)
                    result = (1 - 0.5 * smoothing) * raw + 0.5 * smoothing * up
            elif prev is None:
                lo, hi = np.percentile(small, (1, 99))
                s = 1.0 / max(hi - lo, 1e-6)
                result = (raw - lo) * s
            else:
                warped = _warp_previous(prev[0], gray, prev[1])
                s, b = fit_scale_offset(small, warped)
                if s <= 0:  # a cut or a failed fit: start again from this frame
                    lo, hi = np.percentile(small, (1, 99))
                    s, b = 1.0 / max(hi - lo, 1e-6), -lo / max(hi - lo, 1e-6)
                    self.log_message.emit(self.node_id, f"Frame {number}: depth could not be matched to the "
                                                        f"previous frame (a cut?); starting a new range.")
                result = s * raw + b
                if smoothing > 0:
                    up = cv2.resize(warped, (raw.shape[1], raw.shape[0]), interpolation=cv2.INTER_LINEAR)
                    result = (1 - 0.5 * smoothing) * result + 0.5 * smoothing * up
            result = result.astype(np.float32)
            prev = (cv2.resize(result, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_AREA), gray)
            if blur > 0:
                result = cv2.GaussianBlur(result, (0, 0), blur)
            lo, hi = np.percentile(prev[0], (1, 99))
            low.append(lo)
            high.append(hi)
            exr.write(os.path.join(depth_dir, f"depth_{number:06d}.exr"), result, ("Z",), half=False,
                      attributes={"contour/depth": "metric" if metric else "relative, near = 1"})
            self.progress_update.emit(self.node_id, i + 1, 2 * total)

        # One range for the whole shot: relative depth becomes 0-1, the preview uses the same range.
        lo, hi = float(np.min(low)), float(np.max(high))
        span = max(hi - lo, 1e-6)
        gamma = float(self.params.get("gamma", 1.0) or 1.0)
        colormap = self.params.get("colormap", "Grayscale")
        cmaps = {"Inferno": cv2.COLORMAP_INFERNO, "Turbo": cv2.COLORMAP_TURBO,
                 "Magma": cv2.COLORMAP_MAGMA, "Plasma": cv2.COLORMAP_PLASMA}
        for j, (number, _) in enumerate(sequence):
            if self.is_cancelled:
                return
            out = os.path.join(depth_dir, f"depth_{number:06d}.exr")
            depth = exr.read(out)[0][..., 0]
            if metric:
                near = 1.0 - np.clip((depth - lo) / span, 0, 1)  # preview: near is bright
            else:
                depth = np.clip((depth - lo) / span, 0.0, 1.0)
                near = depth
                if not near_is_one:
                    depth = 1.0 - depth
                exr.write(out, depth, ("Z",), half=False,
                          attributes={"contour/depth": "relative, near = 1" if near_is_one else "relative, near = 0"})
            picture = (np.power(np.clip(near, 0, 1), gamma) * 255 + 0.5).astype(np.uint8)
            picture = cv2.applyColorMap(picture, cmaps[colormap]) if colormap in cmaps else cv2.cvtColor(picture, cv2.COLOR_GRAY2BGR)
            cv2.imwrite(os.path.join(preview_dir, f"depth_{number:06d}.png"), picture)
            self.progress_update.emit(self.node_id, total + j + 1, 2 * total)
        units = "metres" if metric else ("0-1, near = 1" if near_is_one else "0-1, near = 0")
        self.log_message.emit(self.node_id, f"Depth written for {total} frames ({units}; "
                                            f"shot range {lo:.3g}-{hi:.3g}).")

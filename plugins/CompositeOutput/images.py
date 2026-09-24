"""Image layers for Unified Output.

Colour layers (the plate, keyed RGBA) are read at full quality - a plate's master, not the
16-bit display copy - converted from ACEScg to the chosen EXR colour space, or through the
ACES view for display PNGs. Data layers (mattes, depth) are never colour-managed or
gamma'd: a matte is written into the A channel, depth into Z. Files are named
<shot>_<layer>.<frame>.<ext> with the plate's own frame numbers.
"""
import os

import cv2
import numpy as np

from utvfx.core import colour, exr
from utvfx.core.image_nodes import Frames
from utvfx.core.plate import find_sequence

EXR_SPACES = {"ACEScg": colour.SCENE_LINEAR, "ACES2065-1": "ACES2065-1", "Linear Rec.709 (sRGB)": colour.LINEAR_REC709}
CHROMATICITIES = {colour.SCENE_LINEAR: colour.AP1_CHROMATICITIES,
                  "ACES2065-1": (0.7347, 0.2653, 0.0, 1.0, 0.0001, -0.077, 0.32168, 0.33767),
                  colour.LINEAR_REC709: exr.REC709_CHROMATICITIES}
DISPLAYS = {"sRGB (ACES SDR Video)": ("sRGB - Display", "ACES 1.0 - SDR Video"),
            "Rec.709 (ACES SDR Video)": ("Rec.1886 Rec.709 - Display", "ACES 1.0 - SDR Video"),
            "sRGB (Un-tone-mapped)": ("sRGB - Display", "Un-tone-mapped")}


class Settings:
    def __init__(self, params):
        fmt = params.get("file_format", "EXR half float")
        self.exr = fmt.startswith("EXR")
        self.half = "half" in fmt
        self.png16 = "16" in fmt
        self.space = EXR_SPACES.get(params.get("exr_colourspace", "ACEScg"), colour.SCENE_LINEAR)
        self.display = DISPLAYS.get(params.get("png_display"), DISPLAYS["sRGB (ACES SDR Video)"])
        self.ext = ".exr" if self.exr else ".png"
        self.digits = 4


def read_colour(frames, path):
    """(ACEScg rgb, alpha or None) for a colour layer frame."""
    return frames.read(path)


def read_data(path):
    """A matte or depth frame as float32 (H, W): alpha if the file has one, else its first channel."""
    pixels, spec = colour.read_image(path)
    names = list(spec.channelnames)
    channel = names.index("A") if "A" in names and len(names) > 1 else 0
    return pixels[..., channel].astype(np.float32)


def encode_colour(rgb, settings):
    """ACEScg rgb -> the output's colour space (EXR) or display-referred 0-1 (PNG)."""
    if settings.exr:
        return colour.convert(rgb, colour.SCENE_LINEAR, settings.space)
    display, view = settings.display
    out = colour._transform(rgb, lambda d, s: __import__("OpenImageIO").ImageBufAlgo.ociodisplay(
        d, s, display, view, colour.SCENE_LINEAR))
    return np.clip(out, 0.0, 1.0)


def write_png(path, pixels, sixteen):
    """pixels: (H, W) or (H, W, 3|4) float 0-1 in RGB(A) order."""
    scale, dtype = (65535.0, np.uint16) if sixteen else (255.0, np.uint8)
    img = (np.clip(pixels, 0.0, 1.0) * scale + 0.5).astype(dtype)
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGRA if img.shape[2] == 4 else cv2.COLOR_RGB2BGR)
    if not cv2.imwrite(path, img):
        raise IOError(f"Cannot write {path}")


class Layer:
    """One exported sequence; remembered for the Nuke Read script and the sidecar."""

    def __init__(self, name, kind, folder, pattern, first, last, space):
        self.name, self.kind, self.folder, self.pattern = name, kind, folder, pattern
        self.first, self.last, self.space = first, last, space


class ImageExporter:
    def __init__(self, output_dir, shot, params, numbers=None, log=print, cancelled=lambda: False, progress=None):
        self.output_dir, self.shot, self.params = output_dir, shot, params
        self.numbers = numbers  # plate frame numbers to export (In/Out), or None for all
        self.log, self.cancelled, self.progress = log, cancelled, progress or (lambda d, t: None)
        self.s = Settings(params)
        self.layers = []

    def _target(self, layer):
        folder = os.path.join(self.output_dir, layer)
        os.makedirs(folder, exist_ok=True)
        for f in os.listdir(folder):  # an older export with other frame numbers must not linger
            if f.startswith(f"{self.shot}_{layer}."):
                os.remove(os.path.join(folder, f))
        return folder

    def _path(self, folder, layer, number, ext=None):
        return os.path.join(folder, f"{self.shot}_{layer}.{number:0{self.s.digits}d}{ext or self.s.ext}")

    def _record(self, layer, kind, folder, numbers, space, ext=None):
        if numbers:
            pattern = os.path.join(folder, f"{self.shot}_{layer}.%0{self.s.digits}d{ext or self.s.ext}")
            self.layers.append(Layer(layer, kind, folder, pattern, min(numbers), max(numbers), space))
            self.log(f"{layer}: {len(numbers)} frames, {min(numbers)}-{max(numbers)} ({space}).")

    def _select(self, sequence):
        return [(n, p) for n, p in sequence if self.numbers is None or n in self.numbers]

    # ---- layers -------------------------------------------------------------
    def colour_layer(self, folder, layer):
        """Plate or keyed RGBA. Alpha, if the source has one, is kept (and stays as it was: premultiplied or not)."""
        frames = Frames(folder)
        sequence = self._select(frames.sequence)
        target, done = self._target(layer), []
        for i, (n, path) in enumerate(sequence):
            if self.cancelled():
                return
            rgb, alpha = read_colour(frames, path)
            rgb = encode_colour(rgb, self.s)
            if self.s.exr:
                pixels = rgb if alpha is None else np.concatenate([rgb, alpha], axis=2)
                exr.write(self._path(target, layer, n), pixels, ("R", "G", "B") if alpha is None else ("R", "G", "B", "A"),
                          half=self.s.half, chromaticities=CHROMATICITIES.get(self.s.space),
                          attributes={"oiio:ColorSpace": self.s.space})
            else:
                write_png(self._path(target, layer, n), rgb if alpha is None else np.concatenate([rgb, alpha], axis=2),
                          self.s.png16)
            done.append(n)
            self.progress(i + 1, len(sequence))
        self._record(layer, "colour", target, done, self.s.space if self.s.exr else " / ".join(self.s.display))

    def matte_layer(self, folder, layer, core_edge=False):
        """A matte, written raw into A (EXR) or as a grey PNG. Optionally split into solid core and soft edge."""
        sequence = self._select(find_sequence(folder))
        names = [layer] + ([f"{layer}_core", f"{layer}_edge"] if core_edge else [])
        targets = {name: self._target(name) for name in names}
        done = []
        for i, (n, path) in enumerate(sequence):
            if self.cancelled():
                return
            alpha = np.clip(read_data(path), 0.0, 1.0)
            values = {layer: alpha}
            if core_edge:
                core = (alpha >= 0.98).astype(np.float32)
                values[f"{layer}_core"] = core
                values[f"{layer}_edge"] = alpha * (1.0 - core)
            for name, value in values.items():
                if self.s.exr:
                    exr.write(self._path(targets[name], name, n), value, ("A",), half=self.s.half)
                else:
                    write_png(self._path(targets[name], name, n), value, self.s.png16)
            done.append(n)
            self.progress(i + 1, len(sequence))
        for name in names:
            self._record(name, "matte", targets[name], done, "raw (data)")

    def depth_layer(self, folder, layer="depth"):
        """Depth as written by the Depth node, untouched, in Z. PNG needs 0-1, so it is scaled by the shot's maximum."""
        sequence = self._select(find_sequence(folder))
        target, done = self._target(layer), []
        values = [(n, read_data(p)) for n, p in sequence]
        peak = max((float(v.max()) for _, v in values), default=1.0) or 1.0
        for i, (n, depth) in enumerate(values):
            if self.cancelled():
                return
            if self.s.exr:
                exr.write(self._path(target, layer, n), depth, ("Z",), half=False)  # depth keeps full precision
            else:
                write_png(self._path(target, layer, n), depth / peak, True)
            done.append(n)
            self.progress(i + 1, len(values))
        if not self.s.exr and peak != 1.0:
            self.log(f"Depth PNGs are depth / {peak:.4g} (PNG holds 0-1); use EXR for real values.")
        self._record(layer, "depth", target, done, "raw (data)")

    def combined(self, colour_folder, matte_folder, depth_folder, premultiply, layer="combined"):
        """One multi-channel EXR per frame: R, G, B, A (+ depth.Z)."""
        frames = Frames(colour_folder)
        mattes = dict(find_sequence(matte_folder)) if matte_folder else {}
        depths = dict(find_sequence(depth_folder)) if depth_folder else {}
        sequence = self._select(frames.sequence)
        target, done = self._target(layer), []
        for i, (n, path) in enumerate(sequence):
            if self.cancelled():
                return
            rgb, alpha = read_colour(frames, path)
            rgb = colour.convert(rgb, colour.SCENE_LINEAR, self.s.space)
            if n in mattes:
                matte = np.clip(read_data(mattes[n]), 0.0, 1.0)
                if matte.shape != rgb.shape[:2]:
                    matte = cv2.resize(matte, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR)
                alpha = matte[..., None]
                if premultiply:
                    rgb = rgb * alpha
            if alpha is None:
                alpha = np.ones(rgb.shape[:2] + (1,), np.float32)
            channels, pixels = ["R", "G", "B", "A"], [rgb, alpha]
            if n in depths:
                depth = read_data(depths[n])
                if depth.shape != rgb.shape[:2]:
                    depth = cv2.resize(depth, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_NEAREST)
                channels.append("depth.Z")
                pixels.append(depth[..., None])
            exr.write(self._path(target, layer, n, ".exr"), np.concatenate(pixels, axis=2), tuple(channels),
                      half=self.s.half, chromaticities=CHROMATICITIES.get(self.s.space),
                      attributes={"oiio:ColorSpace": self.s.space})
            done.append(n)
            self.progress(i + 1, len(sequence))
        self._record(layer, "combined", target, done, self.s.space, ".exr")

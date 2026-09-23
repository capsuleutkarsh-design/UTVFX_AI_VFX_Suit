"""Colour management on OpenColorIO's built-in ACES studio config.

Scene-linear work happens in ACEScg. Anything shown to people or fed to the AI
models goes through the ACES SDR view, which rolls highlights off instead of
clipping them. A studio can point the OCIO environment variable at its own
config; then that config is used instead.
"""
import os

os.environ.setdefault("OCIO", "ocio://studio-config-latest")

import numpy as np
import OpenImageIO as oiio

SCENE_LINEAR = "ACEScg"
DISPLAY = "sRGB - Display"
VIEW = "ACES 1.0 - SDR Video"
AUTO = "Auto"

SRGB = "sRGB Encoded Rec.709 (sRGB)"
REC709_VIDEO = "Gamma 2.4 Encoded Rec.709"
LINEAR_REC709 = "Linear Rec.709 (sRGB)"

LINEAR_EXTS = (".exr", ".hdr")
VIDEO_EXTS = (".mov", ".mp4", ".mxf", ".avi", ".mkv", ".m4v")

# Red primary (x, y) from an EXR's chromaticities attribute.
_AP0_RED = (0.7347, 0.2653)
_AP1_RED = (0.713, 0.293)
# (red xy, green xy, blue xy, white xy) for ACEScg, as stored in EXR "chromaticities".
AP1_CHROMATICITIES = (0.713, 0.293, 0.165, 0.830, 0.128, 0.044, 0.32168, 0.33767)


def colourspace_names():
    return list(oiio.ColorConfig().getColorSpaceNames())


_NAMES = []


def _config_names():
    if not _NAMES:
        _NAMES.extend(colourspace_names())
    return _NAMES


def is_display_referred(space):
    """True for encoded/display spaces (sRGB, Rec.709 video), false for linear and log."""
    return "Encoded" in space or "Display" in space


def detect_colourspace(path, spec=None):
    """Best guess at a file's colour space. Log plates (DPX, camera logs) need the user's choice."""
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXTS:
        return REC709_VIDEO
    if ext in LINEAR_EXTS:
        if spec is None:
            inp = oiio.ImageInput.open(path)
            spec = inp.spec() if inp else None
            if inp:
                inp.close()
        chroma = spec.getattribute("chromaticities") if spec is not None else None
        if chroma:
            red = (chroma[0], chroma[1])
            if np.allclose(red, _AP0_RED, atol=2e-3):
                return "ACES2065-1"
            if np.allclose(red, _AP1_RED, atol=2e-3):
                return SCENE_LINEAR
        # A colour space written into the file (e.g. our own ACEScg masters). OIIO's generic
        # guesses such as "lin_rec709" say nothing the default doesn't, so only config names count.
        tagged = spec.getattribute("oiio:ColorSpace") if spec is not None else None
        if tagged and tagged in _config_names():
            return tagged
        return LINEAR_REC709
    if ext == ".dpx":
        # DPX is often log; there is no reliable tag, so default to video and let the user override.
        return REC709_VIDEO
    return SRGB


def resolve_colourspace(path, space=AUTO, spec=None):
    return detect_colourspace(path, spec) if space in (None, "", AUTO) else space


def read_image(path):
    """Read an image as float32 (H, W, C) RGB(A), plus its ImageSpec."""
    buf = oiio.ImageBuf(path)
    if buf.has_error:
        raise IOError(f"Cannot read {path}: {buf.geterror()}")
    pixels = buf.get_pixels(oiio.TypeFloat)
    if pixels.ndim == 2:
        pixels = pixels[..., None]
    return pixels, buf.spec()


def _transform(rgb, fn):
    src = oiio.ImageBuf(np.ascontiguousarray(rgb, dtype=np.float32))
    dst = oiio.ImageBuf()
    if not fn(dst, src):
        raise RuntimeError(f"Colour transform failed: {dst.geterror() or oiio.geterror()}")
    return dst.get_pixels(oiio.TypeFloat)


def _split(pixels):
    if pixels.shape[2] == 1:
        return np.repeat(pixels, 3, axis=2), None
    return pixels[..., :3], (pixels[..., 3:4] if pixels.shape[2] > 3 else None)


def _join(rgb, alpha):
    return rgb if alpha is None else np.concatenate([rgb, alpha], axis=2)


def to_scene_linear(pixels, space):
    """Convert float pixels in `space` to ACEScg. Alpha passes through."""
    rgb, alpha = _split(pixels)
    if space != SCENE_LINEAR:
        rgb = _transform(rgb, lambda d, s: oiio.ImageBufAlgo.colorconvert(d, s, space, SCENE_LINEAR))
    return _join(rgb, alpha)


def to_display(pixels, space):
    """Convert float pixels in `space` to display-referred 0-1 (what the AI and the viewer see).

    Display-referred sources are passed through untouched, so the AI sees exactly
    what was delivered. Linear and log sources go through the ACES SDR view.
    """
    rgb, alpha = _split(pixels)
    if is_display_referred(space):
        rgb = np.clip(rgb, 0.0, 1.0)
    else:
        rgb = _transform(rgb, lambda d, s: oiio.ImageBufAlgo.ociodisplay(d, s, DISPLAY, VIEW, space))
        rgb = np.clip(rgb, 0.0, 1.0)
    return _join(rgb, alpha)


def read_linear(path, space=AUTO):
    """Read a file as scene-linear ACEScg float32, keeping highlights above 1.0."""
    pixels, spec = read_image(path)
    return to_scene_linear(pixels, resolve_colourspace(path, space, spec))


def read_display(path, space=AUTO):
    """Read a file as display-referred float32 in 0-1."""
    pixels, spec = read_image(path)
    return to_display(pixels, resolve_colourspace(path, space, spec))

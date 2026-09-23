"""Write EXRs with named channels (OpenCV only writes R/G/B/A/Y, and only when its codec is enabled)."""
import numpy as np
import OpenImageIO as oiio

REC709_CHROMATICITIES = (0.64, 0.33, 0.30, 0.60, 0.15, 0.06, 0.3127, 0.3290)


def write(path, pixels, channels, half=True, chromaticities=None, attributes=None):
    """Write `pixels` (H, W) or (H, W, C) with `channels` names, e.g. ("R", "G", "B", "A") or ("Z",)."""
    pixels = np.asarray(pixels, np.float32)
    if pixels.ndim == 2:
        pixels = pixels[..., None]
    if pixels.shape[2] != len(channels):
        raise ValueError(f"{pixels.shape[2]} channels of pixels but {len(channels)} names")
    spec = oiio.ImageSpec(pixels.shape[1], pixels.shape[0], pixels.shape[2], oiio.TypeHalf if half else oiio.TypeFloat)
    spec.channelnames = tuple(channels)
    if "A" in channels:
        spec.alpha_channel = channels.index("A")
    if "Z" in channels:
        spec.z_channel = channels.index("Z")
    spec.attribute("compression", "zip")
    if chromaticities:
        spec.attribute("chromaticities", oiio.TypeDesc("float[8]"), chromaticities)
    for key, value in (attributes or {}).items():
        spec.attribute(key, value)
    buf = oiio.ImageBuf(spec)
    buf.set_pixels(oiio.ROI(), np.ascontiguousarray(pixels))
    if not buf.write(path):
        raise IOError(f"Could not write {path}: {buf.geterror()}")


def read(path):
    """Float32 (H, W, C) pixels and the channel names."""
    buf = oiio.ImageBuf(path)
    if buf.has_error:
        raise IOError(f"Could not read {path}: {buf.geterror()}")
    pixels = buf.get_pixels(oiio.TypeFloat)
    if pixels.ndim == 2:
        pixels = pixels[..., None]
    return pixels, list(buf.spec().channelnames)

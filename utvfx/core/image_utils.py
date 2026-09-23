import os
import cv2
import numpy as np


def load_frame(path, colourspace="Auto"):
    """
    Loads an image frame as display-referred 8-bit BGR(A) for the viewer and the AI tools.

    Linear and log files (EXR, HDR, DPX) go through the ACES SDR view, so highlights
    roll off instead of clipping. For scene-linear float data use colour.read_linear.

    Returns a BGR numpy array suitable for OpenCV, or None if the image cannot be loaded.
    """
    frame = None
    try:
        from utvfx.core import colour
        display = colour.read_display(path, colourspace)
        frame = (display * 255.0 + 0.5).astype(np.uint8)
        if frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGRA)
        else:
            frame = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_RGB2BGR)
    except ImportError:
        pass  # OpenImageIO missing: fall back to OpenCV
    except (IOError, RuntimeError):
        return None

    if frame is None:
        frame = cv2.imread(path, cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
        if frame is not None:
            if frame.dtype == np.float32 or frame.dtype == np.float64:
                frame = np.clip(frame, 0.0, 1.0)
                frame = (frame * 255.0).astype(np.uint8)
            elif frame.dtype == np.uint16:
                frame = (frame / 256).astype(np.uint8)

            # OpenCV's default for color images is typically BGR or BGRA
            if len(frame.shape) == 2:
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            elif len(frame.shape) == 3 and frame.shape[2] > 4:
                frame = frame[:, :, :4]

    return frame

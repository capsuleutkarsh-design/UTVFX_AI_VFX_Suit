import os
import cv2
import numpy as np

def load_frame(path):
    """
    Safely loads an image frame, with special handling for EXR/HDR/DPX files using
    OpenImageIO (if available) to ensure correct linear-to-sRGB color conversion.
    Falls back to OpenCV for regular images or if OpenImageIO is unavailable.
    
    Returns a BGR numpy array suitable for OpenCV, or None if the image cannot be loaded.
    """
    ext = os.path.splitext(path)[1].lower()
    frame = None

    # 1. Attempt OpenImageIO (Industry Standard for EXR/VFX formats)
    try:
        import OpenImageIO as oiio
        buf = oiio.ImageBuf(path)
        if not buf.has_error:
            if ext in [".exr", ".dpx", ".hdr"]:
                # Convert linear data to sRGB for consistent viewing and AI processing
                oiio.ImageBufAlgo.colorconvert(buf, buf, "linear", "sRGB")
                
            raw_frame = buf.get_pixels(oiio.TypeFloat)
            if raw_frame is not None:
                # Clip HDR highlights to 0-1 range to avoid wrapping/artifacts, then scale
                raw_frame = np.clip(raw_frame, 0.0, 1.0)
                raw_frame = (raw_frame * 255.0).astype(np.uint8)
                
                # Convert to standard BGR or BGRA
                if len(raw_frame.shape) == 2 or (len(raw_frame.shape) == 3 and raw_frame.shape[2] == 1):
                    frame = cv2.cvtColor(raw_frame, cv2.COLOR_GRAY2BGR)
                elif len(raw_frame.shape) == 3 and raw_frame.shape[2] == 4:
                    frame = cv2.cvtColor(raw_frame, cv2.COLOR_RGBA2BGRA)
                elif len(raw_frame.shape) == 3 and raw_frame.shape[2] >= 3:
                    frame = cv2.cvtColor(raw_frame[:, :, :3], cv2.COLOR_RGB2BGR)
    except ImportError:
        pass # Fall back to OpenCV

    # 2. Fallback to OpenCV if OIIO is missing or failed (or if it's a standard format)
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

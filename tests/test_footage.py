"""Sanity checks on the private test plates.

These only read metadata and pixel statistics. They never write, copy or
display a frame.
"""
import glob
import os

import pytest

pytestmark = pytest.mark.footage


def test_exr_plate_is_4k_aces_from_1001(exr_plate):
    import OpenImageIO as oiio

    frames = sorted(glob.glob(os.path.join(exr_plate, "*.exr")))
    numbers = [int(os.path.basename(f).split(".")[-2]) for f in frames]
    assert numbers == list(range(1001, 1060))

    spec = oiio.ImageInput.open(frames[0]).spec()
    assert (spec.width, spec.height, spec.nchannels) == (4096, 2160, 3)
    assert spec.format == oiio.HALF
    # ACES AP0 red primary, which the loader must not treat as sRGB/Rec.709.
    assert spec.getattribute("chromaticities")[0] == pytest.approx(0.7347, abs=1e-3)


def test_exr_plate_has_highlights_above_one(exr_plate):
    import OpenImageIO as oiio

    frame = sorted(glob.glob(os.path.join(exr_plate, "*.exr")))[29]
    pixels = oiio.ImageBuf(frame).get_pixels(oiio.FLOAT)
    assert pixels.max() > 1.0


@pytest.mark.parametrize("name", [
    "PF0028-05_Clip-5_REC709_2K.mov",
    "PF0067-01_Clip-1_REC709_2K.mov",
    "PF0096-04_Clip-4_REC709_2K.mov",
    "CO2_R3_0290.mp4",
])
def test_video_plates_open(footage_dir, name):
    import cv2

    cap = cv2.VideoCapture(os.path.join(footage_dir, "Mov", name))
    assert cap.isOpened()
    assert cap.get(cv2.CAP_PROP_FRAME_COUNT) > 24
    ok, frame = cap.read()
    cap.release()
    assert ok and frame.shape[0] == 1080

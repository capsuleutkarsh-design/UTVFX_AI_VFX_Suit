import os
import subprocess

import cv2
import numpy as np
import pytest

from utvfx.core import colour
from utvfx.core.plate import Cancelled, Plate, find_sequence, ffmpeg_exe, tier_folder


def test_find_sequence_ignores_other_versions_and_sorts_numerically(tmp_path):
    for name in ["shot_v1.9.exr", "shot_v1.10.exr", "shot_v1.11.exr", "shot_v2.10.exr", "notes.txt"]:
        (tmp_path / name).write_bytes(b"")
    frames = find_sequence(str(tmp_path / "shot_v1.10.exr"))
    assert [n for n, _ in frames] == [9, 10, 11]
    assert all("shot_v1." in p for _, p in frames)


def test_exr_plate_keeps_frame_numbers_and_uses_originals_as_master(hdr_exr_sequence, tmp_path):
    plate = Plate.prepare(str(hdr_exr_sequence / "shot.1002.exr"), str(tmp_path / "cache"))
    assert plate.frame_numbers == [1001, 1002, 1003]
    assert plate.has("master")
    assert plate.paths("master")[0].endswith("shot.1001.exr")


def test_png16_tier_is_16_bit_and_does_not_clip_highlights(hdr_exr_sequence, tmp_path):
    plate = Plate.prepare(str(hdr_exr_sequence / "shot.1001.exr"), str(tmp_path / "cache"), colourspace="ACEScg")
    plate.ensure("png16")
    img = cv2.imread(plate.paths("png16")[0], cv2.IMREAD_UNCHANGED)
    assert img.dtype == np.uint16
    highlight = img[15, 15].astype(float) / 65535.0
    assert 0.8 < highlight.min() < 0.999  # 4.0 rolls off below white instead of clipping
    assert os.path.basename(plate.paths("png16")[0]) == "frame_001001.png"


def test_jpg_tier_keeps_full_colour_resolution(hdr_exr_sequence, tmp_path):
    plate = Plate.prepare(str(hdr_exr_sequence / "shot.1001.exr"), str(tmp_path / "cache"))
    plate.ensure("png16")
    plate.ensure("jpg")
    import OpenImageIO as oiio
    spec = oiio.ImageInput.open(plate.paths("jpg")[0]).spec()
    assert spec.getattribute("jpeg:subsampling") == "4:4:4"


def test_cancelled_tier_is_not_marked_complete(hdr_exr_sequence, tmp_path):
    plate = Plate.prepare(str(hdr_exr_sequence / "shot.1001.exr"), str(tmp_path / "cache"))
    with pytest.raises(Cancelled):
        plate.ensure("png16", cancelled=lambda: True)
    reopened = Plate.prepare(str(hdr_exr_sequence / "shot.1001.exr"), str(tmp_path / "cache"))
    assert not reopened.has("png16")


def test_plate_is_reused_until_the_source_changes(hdr_exr_sequence, tmp_path):
    cache = str(tmp_path / "cache")
    Plate.prepare(str(hdr_exr_sequence / "shot.1001.exr"), cache).ensure("png16")
    assert Plate.prepare(str(hdr_exr_sequence / "shot.1001.exr"), cache).has("png16")
    os.utime(hdr_exr_sequence / "shot.1002.exr", (1, 1))
    assert not Plate.prepare(str(hdr_exr_sequence / "shot.1001.exr"), cache).has("png16")


def test_tier_folder_swaps_media_plate_folders_only(hdr_exr_sequence, tmp_path):
    cache = str(tmp_path / "cache")
    plate = Plate.prepare(str(hdr_exr_sequence / "shot.1001.exr"), cache).ensure("png16")
    assert tier_folder(plate.folder("png16"), "jpg") == plate.folder("jpg")
    assert tier_folder(str(tmp_path), "jpg") == str(tmp_path)


def test_video_is_decoded_at_16_bits(tmp_path):
    video = str(tmp_path / "grad.mov")
    subprocess.run([ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i", "gradients=s=320x180:d=0.5:r=24",
                    "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", video], check=True)
    plate = Plate.prepare(video, str(tmp_path / "cache"))
    assert plate.m["kind"] == "video" and len(plate) == 12
    plate.ensure("png16", "master")
    png = cv2.imread(plate.paths("png16")[0], cv2.IMREAD_UNCHANGED)
    assert png.dtype == np.uint16
    assert len(np.unique(png[..., 1])) > 256  # more than 8 bits of levels survived
    assert colour.read_image(plate.paths("master")[0])[0].dtype == np.float32


@pytest.mark.footage
def test_real_mp4_builds_all_tiers(footage_dir, tmp_path):
    plate = Plate.prepare(os.path.join(footage_dir, "Mov", "CO2_R3_0290.mp4"), str(tmp_path / "cache"))
    plate.ensure("png16", "jpg")
    assert (plate.m["width"], plate.m["height"]) == (1920, 1080)
    assert all(os.path.isfile(p) for p in plate.paths("jpg"))


def test_colour_space_tag_in_our_own_exrs_is_honoured(tmp_path):
    """Master EXRs are tagged ACEScg; reading them back must not treat them as linear Rec.709."""
    from utvfx.core.plate import _write_exr

    path = str(tmp_path / "master.exr")
    _write_exr(path, np.full((4, 4, 3), 0.5, np.float32))
    assert colour.detect_colourspace(path) == "ACEScg"
    assert np.allclose(colour.read_linear(path), 0.5, atol=1e-3)  # no conversion applied

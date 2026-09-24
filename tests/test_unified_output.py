"""Unified Output images (H19): full-quality colour, mattes in A and depth in Z with no gamma,
half/full float as asked, plate frame numbers, In/Out, combined EXR, Nuke Reads and sidecar."""
import json
import os

import cv2
import numpy as np
import OpenImageIO as oiio
import pytest

from plugins.CompositeOutput.backend import CompositeOutputWorker
from utvfx.core import colour, exr
from utvfx.core.plate import Plate

NUMBERS = (1001, 1002, 1003)


@pytest.fixture
def graph(hdr_exr_sequence, tmp_path):
    plate = Plate.prepare(str(hdr_exr_sequence), str(tmp_path / "mp"))
    plate.ensure("png16")
    matte, depth = tmp_path / "matte", tmp_path / "depth"
    matte.mkdir()
    depth.mkdir()
    for n in NUMBERS:
        m = np.zeros((48, 64), np.uint16)
        m[:, 32:] = 32768  # half alpha: a gamma would show up here
        cv2.imwrite(str(matte / f"matte_{n:06d}.png"), m)
        exr.write(str(depth / f"depth_{n:06d}.exr"), np.full((48, 64), 12.5, np.float32), ("Z",), half=False)
    return {"Video Plate": plate.folder("png16"), "Alpha Matte": str(matte), "Dense Depth Map": str(depth)}


def run(inputs, tmp_path, frame_range=None, **params):
    params = dict({"output_dir": str(tmp_path / "out"), "shot_name": "sh010"}, **params)
    w = CompositeOutputWorker("o", params, inputs, str(tmp_path / "cache"), str(tmp_path))
    w.frame_range = frame_range
    w.run_task()
    return tmp_path / "out"


def spec_of(path):
    inp = oiio.ImageInput.open(str(path))
    spec = inp.spec()
    inp.close()
    return spec


def test_layers_keep_quality_and_data_is_untouched(graph, tmp_path):
    out = run(graph, tmp_path)
    plate = out / "plate" / "sh010_plate.1001.exr"
    assert spec_of(plate).format == oiio.TypeHalf
    assert colour.detect_colourspace(str(plate)) == colour.SCENE_LINEAR
    assert colour.read_image(str(plate))[0].max() > 3.0  # the 4.0 highlight survives
    pixels, channels = exr.read(str(out / "matte" / "sh010_matte.1001.exr"))
    assert channels == ["A"] and pixels[0, 40, 0] == pytest.approx(0.5, abs=1e-3)
    depth, channels = exr.read(str(out / "depth" / "sh010_depth.1001.exr"))
    assert channels == ["Z"] and spec_of(out / "depth" / "sh010_depth.1001.exr").format == oiio.TypeFloat
    assert depth[0, 0, 0] == 12.5


def test_full_float_and_other_colour_space(graph, tmp_path):
    out = run(graph, tmp_path, file_format="EXR full float", exr_colourspace="Linear Rec.709 (sRGB)")
    plate = out / "plate" / "sh010_plate.1002.exr"
    assert spec_of(plate).format == oiio.TypeFloat
    assert colour.detect_colourspace(str(plate)) == colour.LINEAR_REC709
    # The source plate is linear Rec.709, so going through ACEScg and back returns the same values.
    assert colour.read_image(str(plate))[0][0, 0, 0] == pytest.approx(0.18, abs=2e-3)


def test_png_mattes_have_no_gamma(graph, tmp_path):
    out = run(graph, tmp_path, file_format="PNG 16-bit (display)")
    m = cv2.imread(str(out / "matte" / "sh010_matte.1001.png"), cv2.IMREAD_UNCHANGED)
    assert m.dtype == np.uint16 and abs(int(m[0, 40]) - 32768) <= 1


def test_in_out_and_frame_numbers(graph, tmp_path):
    out = run(graph, tmp_path, frame_range=(1, 2))
    assert sorted(os.listdir(out / "plate")) == ["sh010_plate.1002.exr", "sh010_plate.1003.exr"]
    assert sorted(os.listdir(out / "matte")) == ["sh010_matte.1002.exr", "sh010_matte.1003.exr"]


def test_combined_exr_and_core_edge(graph, tmp_path):
    out = run(graph, tmp_path, combine_exr=True, split_core_edge=True)
    pixels, channels = exr.read(str(out / "combined" / "sh010_combined.1001.exr"))
    assert channels == ["R", "G", "B", "A", "depth.Z"]
    assert pixels[0, 0, 3] == 0 and pixels[0, 0, 0] == 0          # premultiplied by the matte
    assert pixels[0, 40, 0] == pytest.approx(0.5 * 0.18, rel=0.05)  # ACEScg of 0.18 grey, times 0.5
    assert pixels[0, 0, 4] == 12.5
    edge = exr.read(str(out / "matte_edge" / "sh010_matte_edge.1001.exr"))[0]
    core = exr.read(str(out / "matte_core" / "sh010_matte_core.1001.exr"))[0]
    assert edge[0, 40, 0] == pytest.approx(0.5, abs=1e-3) and core[0, 40, 0] == 0


def test_nuke_reads_and_sidecar(graph, tmp_path):
    out = run(graph, tmp_path)
    nk = (out / "sh010_reads.nk").read_text()
    assert nk.count("Read {") == 3 and nk.count("raw true") == 2  # matte and depth are data
    assert "sh010_plate.%04d.exr" in nk and "first 1001" in nk
    meta = json.loads((out / "sh010_export.json").read_text())
    assert {l["name"] for l in meta["layers"]} == {"plate", "matte", "depth"}

"""Grade and OCIO ColorSpace: linear full-quality maths, alpha untouched, real config names, tagged plates."""
import os

import numpy as np
import pytest

from plugins.Grade.backend import GradeWorker, grade
from plugins.OCIO.backend import OCIOWorker
from utvfx.core import colour, exr
from utvfx.core.plate import Plate, find_sequence, plate_for_folder


@pytest.fixture
def plate_folder(hdr_exr_sequence, tmp_path):
    """A Media Plate's display folder for a linear Rec.709 EXR plate with highlights at 4.0."""
    plate = Plate.prepare(str(hdr_exr_sequence), str(tmp_path / "mp"))
    plate.ensure("png16")
    return plate.folder("png16")


@pytest.fixture
def rgba_folder(tmp_path):
    folder = tmp_path / "keyed"
    folder.mkdir()
    for n in (1001, 1002):
        rgb = np.full((8, 8, 3), 0.25, np.float32)
        alpha = np.tile(np.linspace(0, 1, 8, dtype=np.float32), (8, 1))[..., None]
        exr.write(str(folder / f"frame_{n:06d}.exr"), np.concatenate([rgb * alpha, alpha], axis=2),
                  ("R", "G", "B", "A"), chromaticities=exr.REC709_CHROMATICITIES)
    return folder


def run(cls, folder, tmp_path, frame_range=None, **params):
    w = cls("n", params, {"Image": str(folder)}, str(tmp_path / "node"), str(tmp_path))
    w.frame_range = frame_range
    w.run_task()
    return tmp_path / "node"


def test_nuke_grade_maths():
    x = np.array([0.0, 0.5, 1.0, 4.0], np.float32)
    assert np.allclose(grade(x, gain=2.0), [0, 1, 2, 8])
    assert np.allclose(grade(x, blackpoint=0.5, whitepoint=1.0), [0, 0, 1, 7])  # black clamp on by default
    assert grade(x, blackpoint=0.5, black_clamp=False)[0] == pytest.approx(-1.0)
    assert np.allclose(grade(x, white_clamp=True), [0, 0.5, 1, 1])
    assert grade(np.float32(0.25), gamma=2.0) == pytest.approx(0.5)


def test_grade_works_on_the_linear_master_and_keeps_highlights(plate_folder, tmp_path):
    out = run(GradeWorker, plate_folder, tmp_path, gain=2.0)
    frames = find_sequence(str(out / "Frames"))
    assert [n for n, _ in frames] == [1001, 1002, 1003]
    graded = colour.read_linear(frames[0][1])
    source = colour.read_linear(plate_for_folder(plate_folder).paths("master")[0])
    assert graded.max() > 7.0  # a 4.0 highlight doubled, not clipped at 1
    assert np.allclose(graded, 2.0 * source, rtol=2e-3, atol=2e-3)
    # The node's output is a plate: display copy for the AI nodes, master for the Output node.
    assert len(os.listdir(out / "Video Plate")) == 3
    assert plate_for_folder(str(out / "Video Plate")).colourspace == colour.SCENE_LINEAR


def test_grade_never_changes_alpha(rgba_folder, tmp_path):
    out = run(GradeWorker, rgba_folder, tmp_path, gain=3.0, unpremult=True)
    pixels, channels = exr.read(find_sequence(str(out / "Frames"))[0][1])
    assert channels == ["R", "G", "B", "A"]
    assert np.allclose(pixels[..., 3], np.linspace(0, 1, 8), atol=1e-3)
    # Unpremultiplied grade: colour x3, edges still scale with alpha (premultiplied result).
    ratio = pixels[:, 4:, 0] / pixels[:, 4:, 3]
    assert np.allclose(ratio, ratio[0, 0], rtol=5e-3)


def test_grade_honours_in_out(plate_folder, tmp_path):
    out = run(GradeWorker, plate_folder, tmp_path, frame_range=(1, 2))
    assert [n for n, _ in find_sequence(str(out / "Frames"))] == [1002, 1003]


def test_ocio_round_trip_through_log(plate_folder, tmp_path):
    log = run(OCIOWorker, plate_folder, tmp_path / "a", out_space="ARRI LogC3 (EI800)")
    assert plate_for_folder(str(log / "Video Plate")).colourspace == "ARRI LogC3 (EI800)"
    back = run(OCIOWorker, log / "Video Plate", tmp_path / "b", out_space="ACEScg")
    a = colour.read_linear(find_sequence(str(back / "Frames"))[0][1])
    b = colour.read_linear(plate_for_folder(plate_folder).paths("master")[0])
    assert np.allclose(a, b, rtol=1e-2, atol=1e-3)


def test_old_rec709_name_works_and_display_output_is_display_referred(plate_folder, tmp_path):
    run(OCIOWorker, plate_folder, tmp_path / "a", in_space="linear", out_space="Rec709")
    out = run(OCIOWorker, plate_folder, tmp_path / "b", out_space="Display: sRGB - Display / ACES 1.0 - SDR Video")
    plate = plate_for_folder(str(out / "Video Plate"))
    assert colour.is_display_referred(plate.colourspace)
    values = exr.read(plate.paths("master")[0])[0]
    assert values.max() <= 1.0 + 1e-3  # tone-mapped into the display range


def test_unknown_names_are_errors(plate_folder, tmp_path):
    with pytest.raises(Exception, match="not a colour space"):
        run(OCIOWorker, plate_folder, tmp_path, out_space="Not A Space")

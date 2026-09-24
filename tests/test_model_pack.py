"""Offline model packs: ZIP parts that files span, checksum-checked install, damage and escapes refused."""
import os
import zipfile

import pytest

from utvfx.core import model_pack


@pytest.fixture
def source(tmp_path, monkeypatch):
    root = tmp_path / "src"
    files = {"models/SAM/sam.pth": os.urandom(5000), "models/VideoMaMa/unet/w.safetensors": os.urandom(12000),
             "plugins/3DTracker/bin/ffmpeg.exe": os.urandom(700), "models/tiny.json": b"{}"}
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    monkeypatch.setattr(model_pack, "pack_files", lambda r, log=print: (sorted(files), {}, {}))
    return root, files


def build(source, tmp_path, part_size=4096):
    root, _ = source
    return model_pack.build_pack(str(root), str(tmp_path / "out"), "9.9", part_size=part_size, log=lambda m: None)


def test_parts_are_under_the_size_and_install_restores_every_file(source, tmp_path):
    info = build(source, tmp_path)
    parts = sorted((tmp_path / "out").glob("ContourVFX_Models_9.9.zip.*"))
    assert len(parts) == len(info["parts"]) >= 4 and all(p.stat().st_size <= 4096 for p in parts)
    dest = tmp_path / "installed"
    count = model_pack.install_pack(str(parts[0]), str(dest), log=lambda m: None)
    assert count == 4
    for rel, data in source[1].items():
        assert (dest / rel).read_bytes() == data


def test_joined_parts_are_a_normal_zip(source, tmp_path):
    build(source, tmp_path)
    joined = tmp_path / "all.zip"
    with open(joined, "wb") as out:
        for part in sorted((tmp_path / "out").glob("*.zip.*")):
            out.write(part.read_bytes())
    with zipfile.ZipFile(joined) as zf:
        assert zf.testzip() is None and model_pack.MANIFEST in zf.namelist()


def test_unchanged_pack_is_not_rebuilt(source, tmp_path):
    build(source, tmp_path)
    first = (tmp_path / "out" / "ContourVFX_Models_9.9.zip.001").stat().st_mtime_ns
    build(source, tmp_path)
    assert (tmp_path / "out" / "ContourVFX_Models_9.9.zip.001").stat().st_mtime_ns == first


def test_damaged_or_missing_part_is_refused(source, tmp_path):
    build(source, tmp_path)
    parts = sorted((tmp_path / "out").glob("*.zip.*"))
    data = bytearray(parts[1].read_bytes())
    data[2000] ^= 0xFF  # a flipped byte inside file data
    parts[1].write_bytes(bytes(data))
    with pytest.raises(model_pack.PackError, match="damaged"):
        model_pack.install_pack(str(parts[0]), str(tmp_path / "a"), log=lambda m: None)
    parts[-1].unlink()
    with pytest.raises(model_pack.PackError):
        model_pack.install_pack(str(parts[0]), str(tmp_path / "b"), log=lambda m: None)


def test_files_outside_the_model_folders_are_refused(tmp_path, monkeypatch):
    root = tmp_path / "src"
    (root / "utvfx").mkdir(parents=True)
    (root / "utvfx" / "evil.py").write_text("x = 1")
    monkeypatch.setattr(model_pack, "pack_files", lambda r, log=print: (["utvfx/evil.py"], {}, {}))
    model_pack.build_pack(str(root), str(tmp_path / "out"), "1", part_size=4096, log=lambda m: None)
    with pytest.raises(model_pack.PackError, match="outside"):
        model_pack.install_pack(str(tmp_path / "out" / "ContourVFX_Models_1.zip.001"), str(tmp_path / "d"),
                                log=lambda m: None)


def test_hf_files_must_match_the_pinned_revision_and_get_a_marker(source, tmp_path, monkeypatch):
    import hashlib
    root, files = source
    rel = "models/tiny.json"
    good = ("gitsha1", hashlib.sha1(b"blob 2\0{}").hexdigest())
    monkeypatch.setattr(model_pack, "pack_files", lambda r, log=print: (
        sorted(files), {rel: (2,) + good}, {"models/SAM3/.cache/.contour_revision": "abc123"}))
    build(source, tmp_path)
    dest = tmp_path / "installed"
    model_pack.install_pack(str(tmp_path / "out" / "ContourVFX_Models_9.9.zip.001"), str(dest), log=lambda m: None)
    assert (dest / "models/SAM3/.cache/.contour_revision").read_text() == "abc123\n"

    monkeypatch.setattr(model_pack, "pack_files", lambda r, log=print: (
        sorted(files), {rel: (2, "gitsha1", "0" * 40)}, {}))
    (root / rel).write_bytes(b"[]")  # changed, so the pack is rebuilt and the check runs
    with pytest.raises(model_pack.PackError, match="not the pinned version"):
        build(source, tmp_path)

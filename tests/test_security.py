"""Security and download tests (ISSUES.md H9, H10, M6)."""

import hashlib
import http.server
import os
import pickle
import re
import stat
import threading
import zipfile

import pytest

from utvfx.core import downloads

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_TIMEOUT = 120  # seconds; a stuck test dumps its stack and ends the run instead of hanging


@pytest.fixture(autouse=True)
def _hard_timeout():
    """No test in this file may hang: past TEST_TIMEOUT, dump every stack and exit."""
    import faulthandler
    faulthandler.dump_traceback_later(TEST_TIMEOUT, exit=True)
    yield
    faulthandler.cancel_dump_traceback_later()


@pytest.fixture(autouse=True, scope="module")
def _no_modal_dialogs_between_tests():
    """Keep message boxes answered for this whole module, teardowns included.

    Windows built by earlier test files (test_regression.py) leave QTimer.singleShot
    callbacks such as MainWindow.check_models pending. pytest-qt runs them while tearing
    down a later test, after the function-scoped patch in conftest.py has been undone, and a
    real modal "Missing AI Models" box then blocks the run for ever. Flush them here while
    the boxes are still patched.
    """
    from PySide6.QtWidgets import QApplication, QMessageBox

    with pytest.MonkeyPatch.context() as mp:
        for name in ("question", "warning", "information", "critical"):
            mp.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
        mp.setattr(QMessageBox, "exec", lambda self: 0)
        yield
        app = QApplication.instance()
        if app is not None:
            import time
            deadline = time.monotonic() + 1.0   # startup timers use at most 500 ms
            while time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.05)


# ------------------------------------------------------------ offline ZIP importer

def _zip(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            if isinstance(data, zipfile.ZipInfo):
                z.writestr(data, b"target")
            else:
                z.writestr(name, data)
    return path


def _all_files(folder):
    return sorted(os.path.relpath(os.path.join(r, f), folder).replace("\\", "/")
                  for r, _, fs in os.walk(folder) for f in fs)


def test_zip_importer_installs_only_model_data(tmp_path):
    link = zipfile.ZipInfo("models/SAM/link.bin")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive = _zip(tmp_path / "models.zip", {
        "models/SAM/model.safetensors": b"weights",
        "models/SAM/config.json": b"{}",
        "DepthAnythingV2/depth.pth": b"weights",           # zipped from inside models/
        "plugins/Evil/plugin.json": b"{}",
        "plugins/Evil/backend.py": b"import os",
        "models/BiRefNet/BiRefNet/birefnet.py": b"import os",
        "models/Evil/payload.dll": b"MZ",
        "models/Evil/run.bat": b"@echo off",
        "models/Evil/tool.EXE": b"MZ",
        "../escape.txt": b"x",
        "models/../../escape2.txt": b"x",
        "/absolute.txt": b"x",
        "C:/Windows/evil.txt": b"x",
        "models/SAM/link.bin": link,
    })
    dest = tmp_path / "app"
    dest.mkdir()

    extracted, skipped = downloads.extract_models_zip(str(archive), str(dest))

    assert sorted(extracted) == ["models/DepthAnythingV2/depth.pth",
                                 "models/SAM/config.json", "models/SAM/model.safetensors"]
    assert _all_files(dest) == sorted(extracted)
    assert not (tmp_path / "escape.txt").exists() and not (tmp_path / "escape2.txt").exists()
    reasons = dict(skipped)
    assert reasons["plugins/Evil/backend.py"].startswith("plugins/")
    assert "code file" in reasons["models/BiRefNet/BiRefNet/birefnet.py"]
    assert "code file" in reasons["models/Evil/tool.EXE"]
    assert reasons["models/SAM/link.bin"] == "symbolic link"
    assert "absolute" in reasons["/absolute.txt"]
    assert len(skipped) == 11


def test_zip_importer_refuses_oversized_archive(tmp_path):
    archive = _zip(tmp_path / "big.zip", {"models/a.bin": b"\0" * 5000})
    with pytest.raises(downloads.DownloadError):
        downloads.extract_models_zip(str(archive), str(tmp_path / "app"), max_total=1000)
    assert not (tmp_path / "app" / "models" / "a.bin").exists()


def test_zip_importer_skips_zip_bomb_entries(tmp_path):
    archive = _zip(tmp_path / "bomb.zip", {
        "models/bomb.bin": b"\0" * (4 * 1024 * 1024),   # ~1000:1
        "models/ok.bin": os.urandom(2048),
    })
    extracted, skipped = downloads.extract_models_zip(str(archive), str(tmp_path / "app"),
                                                      max_entry_ratio=100)
    assert extracted == ["models/ok.bin"]
    assert "ratio" in dict(skipped)["models/bomb.bin"]


def test_classify_zip_entry():
    assert downloads.classify_zip_entry("models/x/w.pt") == ("models/x/w.pt", None)
    assert downloads.classify_zip_entry("SAM2\\w.pt") == ("models/SAM2/w.pt", None)
    for bad in ("plugins/a.json", "..\\x.pt", "models/a/../../x.pt", "D:\\x.pt", "models/a.pyd"):
        assert downloads.classify_zip_entry(bad)[0] is None, bad


# ------------------------------------------------------------ .part downloads

PAYLOAD = os.urandom(300_000)
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


class _Handler(http.server.BaseHTTPRequestHandler):
    ranges = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        rng = self.headers.get("Range")
        _Handler.ranges.append(rng)
        if self.path == "/truncated":
            # Promise the whole file, send a third of it, then drop the connection.
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD[:100_000])
            self.wfile.flush()
            self.close_connection = True
            return
        start = int(re.match(r"bytes=(\d+)-", rng).group(1)) if rng else 0
        body = PAYLOAD[start:]
        self.send_response(206 if rng else 200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    _Handler.ranges = []
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_download_goes_through_part_file(server, tmp_path):
    dest = tmp_path / "w.pth"
    downloads.download_file(server + "/file", str(dest), sha256=PAYLOAD_SHA, size=len(PAYLOAD),
                            timeout=10, retry_delay=0)
    assert dest.read_bytes() == PAYLOAD
    assert not (tmp_path / "w.pth.part").exists()


def test_interrupted_download_is_not_installed_and_resumes(server, tmp_path):
    dest = tmp_path / "w.pth"
    with pytest.raises(downloads.DownloadError):
        downloads.download_file(server + "/truncated", str(dest), sha256=PAYLOAD_SHA,
                                size=len(PAYLOAD), retries=1, timeout=10)
    assert not dest.exists()                     # never counts as installed
    part = tmp_path / "w.pth.part"
    have = part.stat().st_size
    assert 0 < have < len(PAYLOAD)
    assert not downloads.file_is_installed(str(part), size=len(PAYLOAD))

    downloads.download_file(server + "/file", str(dest), sha256=PAYLOAD_SHA, size=len(PAYLOAD),
                            timeout=10, retry_delay=0)
    assert dest.read_bytes() == PAYLOAD
    assert _Handler.ranges[-1] == f"bytes={have}-"   # resumed, not restarted
    assert not part.exists()


def test_hash_mismatch_leaves_nothing_behind(server, tmp_path):
    dest = tmp_path / "w.pth"
    with pytest.raises(downloads.DownloadError, match="SHA-256"):
        downloads.download_file(server + "/file", str(dest), sha256="0" * 64,
                                size=len(PAYLOAD), retries=1, timeout=10)
    assert not dest.exists()
    assert not (tmp_path / "w.pth.part").exists()


def test_download_uses_timeout(tmp_path):
    seen = {}

    def fake_open(req, timeout=None):
        seen["timeout"] = timeout
        raise OSError("offline")

    with pytest.raises(downloads.DownloadError):
        downloads.download_file("http://example.invalid/x", str(tmp_path / "x"), retries=1,
                                opener=fake_open)
    assert seen["timeout"] and seen["timeout"] > 0


def test_file_is_installed_checks_size_and_hash(tmp_path):
    f = tmp_path / "w.bin"
    f.write_bytes(b"abc")
    sha = hashlib.sha256(b"abc").hexdigest()
    assert downloads.file_is_installed(str(f), 3, sha, verify_hash=True)
    assert not downloads.file_is_installed(str(f), 4)
    assert not downloads.file_is_installed(str(f), 3, "0" * 64, verify_hash=True)


def test_hf_snapshot_counts_only_with_marker(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    assert downloads.hf_status(str(d), "abc") == "missing"
    (d / "model.safetensors").write_bytes(b"w")
    assert downloads.hf_status(str(d), "abc") == "unverified"
    downloads.hf_write_marker(str(d), "abc")
    assert downloads.hf_status(str(d), "abc") == "ok"
    assert downloads.hf_status(str(d), "def") == "unverified"


# ------------------------------------------------------------ pinning (H9, M6)

def test_every_download_is_pinned():
    import first_setup

    for m in first_setup.MODELS:
        assert m["name"] and m["type"] in ("file", "hf_repo", "zip_extract")
        if m["type"] in ("file", "zip_extract"):
            assert re.fullmatch(r"[0-9a-f]{64}", m["sha256"]), m["name"]
            assert m["size"] > 0
            assert "/main/" not in m["url"] and "latest" not in m["url"]
            assert "release-essentials" not in m["url"]
        if m["type"] == "file":
            assert m["path"].startswith("models/")
        if m["type"] == "hf_repo":
            assert re.fullmatch(r"[0-9a-f]{40}", m["revision"]), m["name"]
            assert m["local_dir"].startswith("models/")
        if m["type"] == "zip_extract":
            assert m["final_name"].endswith(".exe")
    names = {m["name"] for m in first_setup.MODELS}
    assert "COLMAP 4.2.0 (CUDA)" in names
    assert not any("uv" in m.get("final_name", "") for m in first_setup.MODELS)
    birefnet = [m for m in first_setup.MODELS if m.get("repo_id", "").startswith("ZhengPeng7/")]
    assert len(birefnet) == 3 and all(m.get("code_sha256") for m in birefnet)


def test_require_local_model_checks_reviewed_code(tmp_path):
    d = tmp_path / "BiRefNet"
    d.mkdir()
    code = b"class BiRefNet: pass\r\n"
    hashes = {"birefnet.py": hashlib.sha256(code.replace(b"\r\n", b"\n")).hexdigest()}
    with pytest.raises(FileNotFoundError, match="MODEL_DOWNLOADS.md"):
        downloads.require_local_model(str(d), code_hashes=hashes)
    (d / "config.json").write_text("{}")
    (d / "model.safetensors").write_bytes(b"w")
    (d / "birefnet.py").write_bytes(code)
    assert downloads.require_local_model(str(d), code_hashes=hashes) == str(d)
    (d / "birefnet.py").write_bytes(b"import os; os.system('calc')\n")
    with pytest.raises(RuntimeError, match="reviewed"):
        downloads.require_local_model(str(d), code_hashes=hashes)
    with pytest.raises(RuntimeError):
        downloads.require_local_model(str(d), code_hashes={})  # unknown repo: refuse


def test_installed_birefnet_code_is_the_reviewed_version():
    import first_setup

    for m in first_setup.MODELS:
        if not m.get("code_sha256"):
            continue
        local = os.path.join(ROOT, *m["local_dir"].split("/"))
        if not os.path.isfile(os.path.join(local, "model.safetensors")):
            pytest.skip(f"{m['name']} not installed")
        downloads.require_local_model(local, code_hashes=m["code_sha256"])


def test_birefnet_wrapper_never_downloads(monkeypatch):
    pytest.importorskip("transformers")
    import sys
    system_dir = os.path.join(ROOT, "plugins", "CorridorKey", "System")
    if not os.path.isdir(os.path.join(system_dir, "BiRefNetModule")):
        pytest.skip("CorridorKey submodule not checked out")
    from plugins.CorridorKey import backend
    backend._use_shared_models_dir()
    import BiRefNetModule.wrapper as wrapper
    import huggingface_hub
    assert wrapper.snapshot_download is not huggingface_hub.snapshot_download
    with pytest.raises(FileNotFoundError, match="MODEL_DOWNLOADS.md"):
        wrapper.snapshot_download(repo_id="ZhengPeng7/BiRefNet",
                                  local_dir=os.path.join(ROOT, "models", "BiRefNet", "does-not-exist"))
    assert system_dir in sys.path


# ------------------------------------------------------------ weights_only (H10)

class _Boom:
    def __reduce__(self):
        return (os.system, ("echo pwned",))


def test_weights_only_refuses_code_in_checkpoints(tmp_path):
    torch = pytest.importorskip("torch")
    evil = tmp_path / "evil.pth"
    with open(evil, "wb") as f:
        pickle.dump({"w": _Boom()}, f, protocol=2)
    with pytest.raises(pickle.UnpicklingError):
        torch.load(evil, map_location="cpu", weights_only=True)


@pytest.mark.parametrize("path", ["models/MEMatte/mematte_loader.py", "plugins/SuperMatte/sam_bridge.py"])
def test_loaders_use_weights_only(path):
    src = open(os.path.join(ROOT, path), encoding="utf-8").read()
    assert "weights_only=False" not in src
    assert "weights_only=True" in src
    if path.endswith("sam_bridge.py"):
        assert "(checkpoint=None)" in src   # build_sam's own torch.load is bypassed


@pytest.mark.models
@pytest.mark.parametrize("rel", ["models/MEMatte/MEMatte_ViTB_DIM.pth", "models/SAM/sam_vit_h_4b8939.pth"])
def test_real_checkpoints_load_with_weights_only(rel):
    torch = pytest.importorskip("torch")
    path = os.path.join(ROOT, *rel.split("/"))
    if not os.path.isfile(path):
        pytest.skip(f"{rel} not installed")
    state = torch.load(path, map_location="cpu", weights_only=True)
    assert isinstance(state, dict) and len(state) > 100

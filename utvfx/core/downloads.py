"""Safe downloads, hash checks and the offline models ZIP importer.

Standard library only: first_setup.py imports this with whatever Python runs the
installer, before any package from requirements-lock.txt is installed.

Rules this module enforces (ISSUES.md M6, H10):
- A download goes to "<file>.part" and is renamed only once it is complete and its
  size and SHA-256 match, so a half-written file never counts as installed.
- Every network call has a timeout.
- A Hugging Face snapshot counts as installed only when a marker file records that
  a snapshot of the pinned revision finished.
- The offline ZIP importer only writes data files under models/.
"""

import hashlib
import os
import shutil
import stat
import time
import urllib.error
import urllib.request
import zipfile

USER_AGENT = "ContourVFX-setup/1.0"
CHUNK = 1024 * 1024
TIMEOUT = 60  # seconds without data before a download attempt gives up


class DownloadError(Exception):
    pass


class CancelledError(DownloadError):
    pass


def sha256_file(path, chunk=CHUNK):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def file_is_installed(path, size=None, sha256=None, verify_hash=False):
    """True when `path` is a finished download.

    Size is checked every time (cheap). The SHA-256 is only read when
    `verify_hash` is set, because model files are gigabytes.
    """
    if not os.path.isfile(path):
        return False
    if size is not None and os.path.getsize(path) != size:
        return False
    if verify_hash and sha256 and sha256_file(path) != sha256.lower():
        return False
    return True


def download_file(url, dest, sha256=None, size=None, *, timeout=TIMEOUT, retries=3,
                  retry_delay=2.0, progress=None, is_cancelled=None, opener=None):
    """Download `url` to `dest` through `dest + ".part"`.

    A leftover .part file is resumed with an HTTP Range request when the server
    supports it; otherwise the download restarts. `progress(done, total)` is called
    as data arrives, `is_cancelled()` is polled between chunks. Raises DownloadError
    (or CancelledError) and leaves `dest` untouched on any failure.
    """
    opener = opener or urllib.request.urlopen
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    part = dest + ".part"
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            have = os.path.getsize(part) if os.path.exists(part) else 0
            if size is not None and have > size:
                os.remove(part)
                have = 0
            headers = {"User-Agent": USER_AGENT}
            if have and (size is None or have < size):
                headers["Range"] = f"bytes={have}-"
            if size is not None and have == size:
                resp = None  # the .part file is already complete, just verify it
            else:
                resp = opener(urllib.request.Request(url, headers=headers), timeout=timeout)
            if resp is not None:
                with resp:
                    status = getattr(resp, "status", None) or resp.getcode()
                    if have and status != 206:
                        have = 0  # server ignored the Range header: start over
                    length = resp.headers.get("Content-Length")
                    total = have + int(length) if length else size
                    with open(part, "ab" if have else "wb") as f:
                        done = have
                        while True:
                            if is_cancelled and is_cancelled():
                                raise CancelledError("cancelled")
                            block = resp.read(CHUNK)
                            if not block:
                                break
                            f.write(block)
                            done += len(block)
                            if size is not None and done > size:
                                raise DownloadError(f"{url} is larger than the expected {size} bytes")
                            if progress:
                                progress(done, total or 0)
            got = os.path.getsize(part)
            if size is not None and got != size:
                raise DownloadError(f"incomplete download: {got} of {size} bytes")
            if sha256:
                actual = sha256_file(part)
                if actual != sha256.lower():
                    os.remove(part)  # corrupt or tampered: never resume from it
                    raise DownloadError(f"SHA-256 mismatch for {os.path.basename(dest)}: "
                                        f"expected {sha256}, got {actual}")
            os.replace(part, dest)
            return dest
        except CancelledError:
            raise
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code == 416 and os.path.exists(part):
                os.remove(part)  # the leftover .part can't be resumed: start again
            if attempt < retries:
                time.sleep(retry_delay)
        except (urllib.error.URLError, OSError, DownloadError, ValueError) as e:
            last_error = e
            if attempt < retries:
                time.sleep(retry_delay)
    raise DownloadError(f"could not download {url}: {last_error}")


# ---------------------------------------------------------------- Hugging Face

HF_MARKER = ".contour_revision"


def hf_marker_path(local_dir):
    return os.path.join(local_dir, ".cache", HF_MARKER)


def hf_installed_revision(local_dir):
    try:
        with open(hf_marker_path(local_dir), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def hf_write_marker(local_dir, revision):
    path = hf_marker_path(local_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(revision + "\n")


def text_sha256(path):
    """SHA-256 of a text file with CRLF normalised to LF (git may check files out either way)."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()


def reviewed_code_hashes():
    """{local_dir basename: {file: sha256}} for model repos that ship Python code."""
    try:
        from first_setup import MODELS
    except ImportError:
        return {}
    return {os.path.basename(os.path.normpath(m["local_dir"])): m["code_sha256"]
            for m in MODELS if m.get("code_sha256")}


def require_local_model(local_dir, kind="model", weights=("model.safetensors", "pytorch_model.bin"),
                        code_hashes=None):
    """Check a Hugging Face model folder is installed locally and its code is reviewed.

    Used instead of snapshot_download at run time. Raises FileNotFoundError when files
    are missing and RuntimeError when a Python file differs from the reviewed version.
    """
    local_dir = os.path.normpath(local_dir or "")
    name = os.path.basename(local_dir)
    if code_hashes is None:
        code_hashes = reviewed_code_hashes().get(name)
    missing = [f for f in ["config.json", *(code_hashes or {})]
               if not os.path.isfile(os.path.join(local_dir, f))]
    if not any(os.path.isfile(os.path.join(local_dir, w)) for w in weights):
        missing.append(weights[0])
    if missing:
        raise FileNotFoundError(
            f"{kind} '{name}' is not installed in {local_dir} (missing: {', '.join(missing)}). "
            "Run first_setup.py or see MODEL_DOWNLOADS.md; it is never downloaded at run time.")
    if not code_hashes:
        raise RuntimeError(f"{kind} '{name}' has no reviewed code hashes in first_setup.py; "
                           "refusing to run its Python code.")
    for filename, sha in code_hashes.items():
        path = os.path.join(local_dir, filename)
        if text_sha256(path) != sha:
            raise RuntimeError(f"{path} is not the reviewed version. Restore the pinned revision with "
                               "first_setup.py (see MODEL_DOWNLOADS.md) before running it.")
    return local_dir


def hf_status(local_dir, revision, check_path=None):
    """'ok' (the pinned revision finished downloading), 'unverified' (files are there
    but no finished snapshot of this revision is recorded) or 'missing'."""
    if revision and hf_installed_revision(local_dir) == revision:
        return "ok"
    probe = check_path or local_dir
    if os.path.isfile(probe):
        return "unverified"
    if os.path.isdir(probe):
        for root, dirs, files in os.walk(probe):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            if any(f.endswith((".safetensors", ".bin", ".pth", ".pt")) for f in files):
                return "unverified"
    return "missing"


# ------------------------------------------------------- offline models ZIP

# Anything a ZIP could use to run code. Model folders hold weights and configs only;
# the reviewed model code (BiRefNet, MEMatte, SAMURAI) comes from git, never a ZIP.
BLOCKED_EXTENSIONS = {
    ".py", ".pyc", ".pyo", ".pyw", ".pyd", ".pyz", ".dll", ".exe", ".so", ".dylib",
    ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
    ".msi", ".msp", ".com", ".scr", ".cpl", ".lnk", ".url", ".reg", ".jar", ".sh",
    ".hta", ".pif", ".ipynb",
}
MAX_TOTAL_BYTES = 200 * 1024 ** 3   # 200 GB: every model the app knows is ~60 GB
MAX_ENTRY_RATIO = 1000              # one entry expanding more than this is a zip bomb
MAX_ARCHIVE_RATIO = 100             # model weights barely compress (about 1.1x)
MAX_ENTRIES = 200_000


def classify_zip_entry(name):
    """Map a ZIP entry name to a relative 'models/...' path, or (None, reason)."""
    raw = name
    name = name.replace("\\", "/")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        return None, "absolute path"
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts:
        return None, "empty name"
    if any(p == ".." for p in parts):
        return None, "path goes outside the folder (..)"
    if any(":" in p for p in parts):
        return None, "drive or stream name in path"
    if parts[0].lower() == "plugins":
        return None, "plugins/ folder (only models/ may be installed)"
    if parts[0].lower() != "models":
        # ZIP made from the *contents* of the models folder: put it under models/.
        parts = ["models"] + parts
    if len(parts) < 2:
        return None, "not a file inside models/"
    ext = os.path.splitext(parts[-1])[1].lower()
    if ext in BLOCKED_EXTENSIONS:
        return None, f"code file ({ext})"
    if raw.endswith("/"):
        return None, "directory"
    return "/".join(parts), None


def _is_symlink(info):
    return stat.S_ISLNK(info.external_attr >> 16)


def extract_models_zip(zip_path, dest_root, *, max_total=MAX_TOTAL_BYTES,
                       max_entry_ratio=MAX_ENTRY_RATIO, max_archive_ratio=MAX_ARCHIVE_RATIO,
                       progress=None, is_cancelled=None):
    """Extract only data files under models/ from `zip_path` into `dest_root`.

    Returns (extracted, skipped): relative paths written, and (entry, reason)
    pairs that were refused. Raises DownloadError when the archive as a whole
    looks like a zip bomb, before anything is written.
    """
    dest_root = os.path.abspath(dest_root)
    models_root = os.path.join(dest_root, "models")
    extracted, skipped = [], []
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise DownloadError(f"ZIP has {len(infos)} entries (limit {MAX_ENTRIES})")
        plan = []
        for info in infos:
            if info.is_dir():
                continue
            rel, reason = classify_zip_entry(info.filename)
            if rel is None:
                skipped.append((info.filename, reason))
                continue
            if _is_symlink(info):
                skipped.append((info.filename, "symbolic link"))
                continue
            if info.file_size > max_entry_ratio * max(info.compress_size, 1) and info.file_size > CHUNK:
                skipped.append((info.filename, "compression ratio too high (zip bomb?)"))
                continue
            target = os.path.abspath(os.path.join(dest_root, *rel.split("/")))
            if os.path.commonpath([target, models_root]) != models_root:
                skipped.append((info.filename, "path goes outside models/"))
                continue
            plan.append((info, rel, target))

        total = sum(info.file_size for info, _, _ in plan)
        if total > max_total:
            raise DownloadError(f"ZIP would unpack to {total / 1024 ** 3:.1f} GB "
                                f"(limit {max_total / 1024 ** 3:.0f} GB)")
        archive_size = max(os.path.getsize(zip_path), 1)
        if total > max_archive_ratio * archive_size and total > 100 * CHUNK:
            raise DownloadError("ZIP expands far more than model files can (zip bomb?)")

        for i, (info, rel, target) in enumerate(plan):
            if is_cancelled and is_cancelled():
                raise CancelledError("cancelled")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            part = target + ".part"
            written = 0
            with zf.open(info) as src, open(part, "wb") as out:
                while True:
                    block = src.read(CHUNK)
                    if not block:
                        break
                    written += len(block)
                    if written > info.file_size:  # the header lied about the size
                        break
                    out.write(block)
            if written != info.file_size:
                os.remove(part)
                skipped.append((info.filename, "size does not match the ZIP header"))
                continue
            os.replace(part, target)
            extracted.append(rel)
            if progress:
                progress(i + 1, len(plan))
    return extracted, skipped


def extract_archive_tree(zip_path, dest_dir, exclude=(), strip_prefix=""):
    """Unpack a trusted, hash-checked binary archive (COLMAP, GLOMAP) into dest_dir.

    Still refuses absolute and '..' paths. `exclude` holds fnmatch patterns on the
    file name (for example test executables and debug symbols).
    """
    import fnmatch
    dest_dir = os.path.abspath(dest_dir)
    tmp = dest_dir + ".part"
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    count = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if strip_prefix:
                if not name.startswith(strip_prefix):
                    continue
                name = name[len(strip_prefix):]
            parts = [p for p in name.split("/") if p not in ("", ".")]
            if not parts or info.is_dir():
                continue
            if name.startswith("/") or ":" in name or ".." in parts:
                raise DownloadError(f"unsafe path in archive: {info.filename}")
            if any(fnmatch.fnmatch(parts[-1].lower(), pat.lower()) for pat in exclude):
                continue
            target = os.path.join(tmp, *parts)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, CHUNK)
            count += 1
    if not count:
        shutil.rmtree(tmp, ignore_errors=True)
        raise DownloadError(f"nothing to extract from {os.path.basename(zip_path)}")
    if os.path.exists(dest_dir):
        # Keep what is already there (for example a hand-copied bundle) and add to it.
        for root, _, files in os.walk(tmp):
            for f in files:
                src = os.path.join(root, f)
                dst = os.path.join(dest_dir, os.path.relpath(src, tmp))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.replace(src, dst)
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        os.replace(tmp, dest_dir)
    return count

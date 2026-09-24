"""Offline model packs: every model and tool the app downloads, in ZIP parts of up to 2 GB.

For computers without internet. On a connected machine that has run first_setup.py:

    build\\BUILD.bat models        ->  ContourVFX_Models_<version>.zip.001, .002, ...

Then, on the offline computer, the installer's "Offline models" page (or the app's
AI models window) takes the .001 file and installs everything from the parts.

The parts are one ZIP (stored, not compressed: model weights do not compress) cut into
pieces, because several single model files are bigger than 2 GB. 7-Zip opens the .001 as
a normal archive. Inside is exactly what first_setup.py installs (the trimmed set, not
whatever else is in models/), plus contour_models_manifest.json with the size and SHA-256
of every file, so the installer can tell if a part was damaged when it was copied.
"""
import fnmatch
import glob
import hashlib
import io
import json
import os
import re
import subprocess
import zipfile

MANIFEST = "contour_models_manifest.json"
PART_SIZE = 1_950_000_000          # under 2 GB, so the parts fit any USB stick or share
ALLOWED_ROOTS = ("models/", "plugins/3DTracker/bin/")
CHUNK = 8 * 1024 * 1024


class PackError(Exception):
    pass


# ---- what goes in -----------------------------------------------------------
def _hf_listing(repo_id, revision):
    """The files of a Hugging Face repo at `revision`, with their size and checksum."""
    import urllib.request
    url = f"https://huggingface.co/api/models/{repo_id}/tree/{revision}?recursive=true"
    with urllib.request.urlopen(url, timeout=60) as r:
        return [x for x in json.load(r) if x.get("type") == "file"]


def _expected(entry):
    """(kind, hex) Hugging Face publishes for a file: SHA-256 for LFS files, git's blob SHA-1 otherwise."""
    lfs = entry.get("lfs") or {}
    return ("sha256", lfs["oid"]) if lfs.get("oid") else ("gitsha1", entry.get("oid"))


def pack_files(root, log=print):
    """What goes in the pack: (files, expected, markers).

    files     relative paths (with /) of everything first_setup.py installs, present under root
    expected  {path: (size, kind, hex)} for Hugging Face files, checked while packing
    markers   {marker path: revision}: written into the pack once a repo's files all match
    """
    import first_setup
    from utvfx.core.downloads import hf_marker_path

    wanted, expected, markers = [], {}, {}

    def add(rel):
        if os.path.isfile(os.path.join(root, rel)):
            wanted.append(rel.replace("\\", "/"))

    for task in first_setup.MODELS:
        kind = task["type"]
        if kind == "file":
            add(task["path"])
        elif kind == "hf_repo":
            ignore = task.get("ignore_patterns") or []
            try:
                listing = _hf_listing(task["repo_id"], task["revision"])
            except Exception as e:
                raise PackError(f"Could not list {task['repo_id']} on Hugging Face ({e}); "
                                "build the model pack on a computer with internet.")
            for entry in listing:
                name = entry["path"]
                if not any(fnmatch.fnmatch(name, p) for p in ignore) and not name.startswith("."):
                    rel = f"{task['local_dir']}/{name}"
                    add(rel)
                    expected[rel] = (entry.get("size"),) + _expected(entry)
            marker = os.path.relpath(hf_marker_path(os.path.join(root, task["local_dir"])), root)
            markers[marker.replace("\\", "/")] = task["revision"]
        elif kind == "zip_extract":
            if task.get("dest_dir"):
                base = os.path.join(root, task["dest_dir"])
                for folder, _, names in os.walk(base):
                    for n in names:
                        add(os.path.relpath(os.path.join(folder, n), root))
            else:
                add(task["final_name"])
    for task in first_setup.MANUAL_FILES:
        add(task["path"])

    # Files git tracks (model code and configs) come with the app installer.
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "--recurse-submodules", "-z"],
                             capture_output=True, check=True).stdout.decode("utf-8")
        tracked = set(out.split("\0"))
    except Exception:
        tracked = set()
    files = sorted({f for f in wanted if f not in tracked and f not in markers})
    missing = _missing_items(root)
    for name in missing:
        log(f"Not installed here, so not in the pack: {name}")
    return files, expected, markers


def _missing_items(root):
    import first_setup
    out = []
    for task in first_setup.MODELS + first_setup.MANUAL_FILES:
        path = task.get("path") or task.get("final_name") or task.get("check_dir") or task.get("local_dir")
        if path and not os.path.exists(os.path.join(root, path)):
            out.append(task["name"])
    return out


# ---- writing the parts --------------------------------------------------------
class _PartWriter(io.RawIOBase):
    """A write-only stream that rolls over to base.001, base.002, ... every `size` bytes."""

    def __init__(self, base, size):
        self.base, self.size, self.index, self.pos, self.used = base, size, 0, 0, 0
        self.parts, self.fh = [], None
        self._next()

    def _next(self):
        if self.fh:
            self.fh.close()
        self.index += 1
        path = f"{self.base}.{self.index:03d}"
        self.parts.append(path)
        self.fh, self.used = open(path, "wb"), 0

    def writable(self):
        return True

    def seekable(self):
        return False

    def tell(self):
        return self.pos

    def write(self, data):
        view = memoryview(data)
        while view:
            room = self.size - self.used
            if room == 0:
                self._next()
                room = self.size
            n = min(room, len(view))
            self.fh.write(view[:n])
            self.used += n
            self.pos += n
            view = view[n:]
        return len(data)

    def close(self):
        if self.fh:
            self.fh.close()
            self.fh = None
        super().close()


def build_pack(root, out_dir, version, part_size=PART_SIZE, log=print):
    """Write the parts into out_dir. Skips the work if an identical pack is already there."""
    files, expected, markers = pack_files(root, log)
    if not files:
        raise PackError("No models are installed here; run first_setup.py first.")
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, f"ContourVFX_Models_{version}.zip")
    summary = os.path.join(out_dir, f"ContourVFX_Models_{version}.json")
    stamp = [[f, os.stat(os.path.join(root, f)).st_size, os.stat(os.path.join(root, f)).st_mtime_ns] for f in files]
    stamp.append([list(item) for item in sorted(markers.items())])  # as it reads back from JSON
    try:
        with open(summary, encoding="utf-8") as fh:
            old = json.load(fh)
        if old.get("stamp") == stamp and all(os.path.isfile(p) for p in _parts_of(base + ".001")):
            log(f"The model pack in {out_dir} is up to date ({len(old['parts'])} parts).")
            return old
    except (OSError, ValueError, PackError):
        pass
    for old_part in glob.glob(base + ".[0-9][0-9][0-9]"):
        os.remove(old_part)

    total = sum(os.path.getsize(os.path.join(root, f)) for f in files)
    log(f"Packing {len(files)} files ({total / 1e9:.1f} GB) into parts of {part_size / 1e9:.2f} GB...")
    writer = _PartWriter(base, part_size)
    manifest, done = {}, 0
    with zipfile.ZipFile(writer, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
        for rel in files:
            path = os.path.join(root, rel)
            size = os.path.getsize(path)
            digest = hashlib.sha256()
            blob = hashlib.sha1(f"blob {size}\0".encode()) if expected.get(rel, (0, ""))[1] == "gitsha1" else None
            info = zipfile.ZipInfo.from_file(path, rel)
            info.compress_type = zipfile.ZIP_STORED
            with open(path, "rb") as src, zf.open(info, "w", force_zip64=True) as dst:
                while True:
                    block = src.read(CHUNK)
                    if not block:
                        break
                    digest.update(block)
                    if blob:
                        blob.update(block)
                    dst.write(block)
            if rel in expected:
                # Only the exact files of the pinned Hugging Face revision go in.
                want_size, kind, want = expected[rel]
                got = digest.hexdigest() if kind == "sha256" else blob.hexdigest()
                if not re.fullmatch(r"[0-9a-f]{40,64}", want or ""):
                    # Gated repos (SAM 3) hide checksums unless you are logged in: size only.
                    got = want
                    log(f"  {rel}: Hugging Face hides its checksum (gated repo); checked by size.")
                if (want_size is not None and size != want_size) or got != want:
                    raise PackError(f"{rel} is not the pinned version (size or checksum differs). "
                                    "Run first_setup.py to repair it, then build the pack again.")
            manifest[rel] = {"size": size, "sha256": digest.hexdigest()}
            done += manifest[rel]["size"]
            log(f"  {done / 1e9:6.1f} / {total / 1e9:.1f} GB  {rel}")
        # Every Hugging Face file matched its pinned revision, so the pack records them as installed.
        for rel, revision in markers.items():
            data = (revision + "\n").encode()
            zf.writestr(rel, data)
            manifest[rel] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        zf.writestr(MANIFEST, json.dumps({"version": version, "files": manifest}, indent=1))
    writer.close()
    info = {"version": version, "parts": [os.path.basename(p) for p in writer.parts],
            "files": len(files), "bytes": total, "stamp": stamp}
    with open(summary, "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=1)
    log(f"Model pack: {len(writer.parts)} parts in {out_dir}.")
    return info


# ---- reading the parts ----------------------------------------------------------
def _parts_of(first):
    match = re.match(r"^(.*)\.(\d{3})$", first)
    if not match:
        raise PackError(f"{os.path.basename(first)} is not a part file (it should end in .001).")
    base, parts, i = match.group(1), [], 1
    while os.path.isfile(f"{base}.{i:03d}"):
        parts.append(f"{base}.{i:03d}")
        i += 1
    if not parts:
        raise PackError(f"{base}.001 was not found.")
    return parts


class _PartReader(io.RawIOBase):
    """The parts, read as one seekable file."""

    def __init__(self, parts):
        self.parts = parts
        self.sizes = [os.path.getsize(p) for p in parts]
        self.total, self.pos, self.handles = sum(self.sizes), 0, {}

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        self.pos = {io.SEEK_SET: offset, io.SEEK_CUR: self.pos + offset, io.SEEK_END: self.total + offset}[whence]
        return self.pos

    def readinto(self, buffer):
        view, filled = memoryview(buffer), 0
        while filled < len(view) and self.pos < self.total:
            index, start = 0, self.pos
            while start >= self.sizes[index]:
                start -= self.sizes[index]
                index += 1
            fh = self.handles.get(index) or self.handles.setdefault(index, open(self.parts[index], "rb"))
            fh.seek(start)
            n = fh.readinto(view[filled:filled + min(len(view) - filled, self.sizes[index] - start)])
            if not n:
                break
            filled += n
            self.pos += n
        return filled

    def close(self):
        for fh in self.handles.values():
            fh.close()
        super().close()


def install_pack(first_part, dest_root, log=print, progress=None, is_cancelled=None):
    """Install everything in the pack under dest_root, checking every file's SHA-256.

    Returns the number of files installed. Raises PackError when a part is missing or damaged.
    """
    parts = _parts_of(first_part)
    dest_root = os.path.abspath(dest_root)
    reader = _PartReader(parts)
    try:
        try:
            zf = zipfile.ZipFile(io.BufferedReader(reader, CHUNK))
        except zipfile.BadZipFile:
            raise PackError(f"The pack is incomplete or damaged ({len(parts)} parts found). "
                            "Copy every part again, into one folder.")
        with zf:
            manifest = json.loads(zf.read(MANIFEST))["files"]
            entries = [i for i in zf.infolist() if i.filename in manifest]
            total = sum(i.file_size for i in entries)
            log(f"Installing {len(entries)} files ({total / 1e9:.1f} GB) from {len(parts)} parts...")
            done = 0
            for info in entries:
                if is_cancelled and is_cancelled():
                    raise PackError("Cancelled.")
                rel = info.filename
                target = os.path.abspath(os.path.join(dest_root, *rel.split("/")))
                roots = [os.path.join(dest_root, *r.strip("/").split("/")) + os.sep for r in ALLOWED_ROOTS]
                if not any(target.startswith(r) for r in roots):
                    raise PackError(f"The pack contains a file outside the model folders: {rel}")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                digest, temp = hashlib.sha256(), target + ".part"
                try:
                    with zf.open(info) as src, open(temp, "wb") as out:
                        while True:
                            block = src.read(CHUNK)
                            if not block:
                                break
                            digest.update(block)
                            out.write(block)
                            done += len(block)
                            if progress:
                                progress(done, total)
                except zipfile.BadZipFile:
                    os.remove(temp)
                    raise PackError(f"{rel} is damaged in the pack. Copy the parts again.")
                if digest.hexdigest() != manifest[rel]["sha256"]:
                    os.remove(temp)
                    raise PackError(f"{rel} is damaged in the pack (checksum does not match). "
                                    "Copy the parts again.")
                os.replace(temp, target)
                log(f"  {done / 1e9:6.1f} / {total / 1e9:.1f} GB  {rel}")
    finally:
        reader.close()
    return len(entries)

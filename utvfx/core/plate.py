"""A plate: one decoded source shared by every node, in three quality tiers.

master  The plate at full quality. EXR sequences are used in place (no copy);
        video is decoded once to half-float ACEScg EXR.
png16   16-bit display-referred PNG (ACES SDR view for linear and log sources).
        Read by the viewer, SAM and the matte refiners.
jpg     8-bit JPEG with full-resolution colour (4:4:4). For SAMURAI, the 3D
        tracker, depth and thumbnails.

Tiers are made the first time something asks for them. plate.json records the
source, its frame numbers and which tiers finished, so an interrupted run is
redone rather than trusted.
"""
import hashlib
import json
import os
import re
import subprocess

import cv2
import numpy as np

from utvfx.core import colour

VERSION = 3  # 3: master EXRs carry ACEScg chromaticities
MANIFEST = "plate.json"
TIER_FOLDERS = {"master": "Master", "png16": "Video Plate", "jpg": "Video Plate JPG"}
TIER_EXT = {"master": ".exr", "png16": ".png", "jpg": ".jpg"}
IMAGE_EXTS = (".exr", ".dpx", ".hdr", ".tif", ".tiff", ".png", ".jpg", ".jpeg")
_FRAME_RE = re.compile(r"^(.*?)(\d+)(\.[^.]+)$")


class Cancelled(Exception):
    pass


def find_sequence(path):
    """Return [(frame_number, path)] for the sequence `path` belongs to, sorted by frame number.

    Only files with the same name prefix and extension count, so two versions of a
    plate in one folder are not mixed together.
    """
    if os.path.isdir(path):
        groups = {}
        for name in os.listdir(path):
            m = _FRAME_RE.match(name)
            if m and m.group(3).lower() in IMAGE_EXTS:
                groups.setdefault((m.group(1), m.group(3).lower()), []).append(name)
        if not groups:
            return []
        prefix, ext = max(groups, key=lambda k: len(groups[k]))
        folder = path
    else:
        folder, name = os.path.split(path)
        m = _FRAME_RE.match(name)
        if not m:
            return [(1, path)]
        prefix, ext = m.group(1), m.group(3).lower()
    frames = []
    for name in os.listdir(folder):
        m = _FRAME_RE.match(name)
        if m and m.group(1) == prefix and m.group(3).lower() == ext:
            frames.append((int(m.group(2)), os.path.join(folder, name)))
    return sorted(frames)


def ffmpeg_exe():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    bundled = os.path.join(root, "plugins", "3DTracker", "bin", "ffmpeg.exe")
    if os.path.isfile(bundled):
        return bundled
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _video_info(path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video {path}")
    info = (int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), cap.get(cv2.CAP_PROP_FPS) or 24.0,
            int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.release()
    return info


def _decode_video(path, width, height):
    """Yield frames as float32 RGB 0-1, decoded at 16 bits so 10-bit ProRes keeps its precision."""
    cmd = [ffmpeg_exe(), "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb48le", "-"]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=flags)
    frame_bytes = width * height * 6
    try:
        while True:
            raw = proc.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            yield np.frombuffer(raw, np.uint16).reshape(height, width, 3).astype(np.float32) / 65535.0
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


def _signature(entries):
    h = hashlib.sha1()
    for p in entries:
        st = os.stat(p)
        h.update(f"{p}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8"))
    return h.hexdigest()


def _write_png16(path, rgb):
    bgr = cv2.cvtColor((rgb * 65535.0 + 0.5).astype(np.uint16), cv2.COLOR_RGB2BGR)
    if not cv2.imwrite(path, bgr, [cv2.IMWRITE_PNG_COMPRESSION, 1]):
        raise IOError(f"Cannot write {path}")


def _write_jpg(path, rgb8):
    params = [cv2.IMWRITE_JPEG_QUALITY, 95, cv2.IMWRITE_JPEG_SAMPLING_FACTOR, cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444]
    if not cv2.imwrite(path, cv2.cvtColor(rgb8, cv2.COLOR_RGB2BGR), params):
        raise IOError(f"Cannot write {path}")


def _write_exr(path, rgb):
    import OpenImageIO as oiio
    h, w = rgb.shape[:2]
    spec = oiio.ImageSpec(w, h, 3, oiio.TypeHalf)
    spec.attribute("compression", "piz")
    spec.attribute("oiio:ColorSpace", colour.SCENE_LINEAR)
    # The EXR-standard way to say "ACEScg": AP1 primaries with the ACES white point.
    spec.attribute("chromaticities", oiio.TypeDesc("float[8]"), colour.AP1_CHROMATICITIES)
    out = oiio.ImageOutput.create(path)
    if out is None or not out.open(path, spec):
        raise IOError(f"Cannot write {path}")
    out.write_image(np.ascontiguousarray(rgb, dtype=np.float32))
    out.close()


class Plate:
    def __init__(self, cache_dir, manifest):
        self.cache_dir = cache_dir
        self.m = manifest

    # ---- creation -------------------------------------------------------
    @classmethod
    def open(cls, cache_dir):
        path = os.path.join(cache_dir, MANIFEST)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        if manifest.get("version") != VERSION:
            return None
        return cls(cache_dir, manifest)

    @classmethod
    def prepare(cls, source, cache_dir, is_sequence=True, colourspace=colour.AUTO):
        """Describe `source` and reuse the cached plate if nothing about it changed."""
        ext = os.path.splitext(source)[1].lower()
        if os.path.isdir(source) or (is_sequence and ext in IMAGE_EXTS):
            frames = find_sequence(source)
            if not frames:
                raise IOError(f"No image sequence found at {source}")
            numbers = [n for n, _ in frames]
            paths = [p for _, p in frames]
            import OpenImageIO as oiio
            inp = oiio.ImageInput.open(paths[0])
            if inp is None:
                raise IOError(f"Cannot read {paths[0]}")
            spec = inp.spec()
            inp.close()
            fps = spec.getattribute("FramesPerSecond")
            manifest = {
                "kind": "sequence", "source_paths": paths, "frame_numbers": numbers,
                "width": spec.width, "height": spec.height,
                "fps": float(fps[0]) / float(fps[1]) if isinstance(fps, tuple) else 24.0,
                "colourspace": colour.resolve_colourspace(paths[0], colourspace, spec),
                "signature": _signature(paths),
            }
        elif ext in IMAGE_EXTS:
            manifest = cls._single_image(source, colourspace)
        else:
            count, fps, w, h = _video_info(source)
            manifest = {
                "kind": "video", "source_paths": [source], "frame_numbers": list(range(1, count + 1)),
                "width": w, "height": h, "fps": fps,
                "colourspace": colour.resolve_colourspace(source, colourspace),
                "signature": _signature([source]),
            }
        manifest.update({"version": VERSION, "source": source, "tiers": {}})

        existing = cls.open(cache_dir)
        if existing and all(existing.m.get(k) == manifest[k] for k in ("source", "signature", "colourspace", "frame_numbers")):
            return existing
        plate = cls(cache_dir, manifest)
        os.makedirs(cache_dir, exist_ok=True)
        plate._save()
        return plate

    @staticmethod
    def _single_image(path, colourspace):
        import OpenImageIO as oiio
        inp = oiio.ImageInput.open(path)
        if inp is None:
            raise IOError(f"Cannot read {path}")
        spec = inp.spec()
        inp.close()
        m = _FRAME_RE.match(os.path.basename(path))
        return {
            "kind": "sequence", "source_paths": [path], "frame_numbers": [int(m.group(2)) if m else 1],
            "width": spec.width, "height": spec.height, "fps": 24.0,
            "colourspace": colour.resolve_colourspace(path, colourspace, spec),
            "signature": _signature([path]),
        }

    def _save(self):
        path = os.path.join(self.cache_dir, MANIFEST)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.m, f, indent=1)
        os.replace(tmp, path)

    # ---- queries --------------------------------------------------------
    @property
    def frame_numbers(self):
        return self.m["frame_numbers"]

    @property
    def colourspace(self):
        return self.m["colourspace"]

    def __len__(self):
        return len(self.frame_numbers)

    def has(self, tier):
        return bool(self.m["tiers"].get(tier)) or (tier == "master" and self.m["kind"] == "sequence")

    def folder(self, tier):
        return os.path.join(self.cache_dir, TIER_FOLDERS[tier])

    def paths(self, tier):
        """Frame files for `tier`, in timeline order. Index i is timeline position i."""
        if tier == "master" and self.m["kind"] == "sequence":
            return list(self.m["source_paths"])
        folder, ext = self.folder(tier), TIER_EXT[tier]
        return [os.path.join(folder, f"frame_{n:06d}{ext}") for n in self.frame_numbers]

    # ---- building -------------------------------------------------------
    def ensure(self, *tiers, progress=None, cancelled=None):
        """Build any missing tiers. Raises Cancelled if `cancelled()` becomes true."""
        todo = [t for t in tiers if not self.has(t)]
        if "jpg" in todo and "png16" not in todo and self.has("png16"):
            self._jpg_from_png16(progress, cancelled)
            todo.remove("jpg")
        if not todo:
            return self
        for tier in todo:
            os.makedirs(self.folder(tier), exist_ok=True)
        targets = {t: self.paths(t) for t in todo}
        space = self.colourspace

        def write(i, rgb):
            if rgb is None:
                rgb = self._read_source(i)
            if "master" in targets:
                _write_exr(targets["master"][i], colour.to_scene_linear(rgb, space))
            if "png16" in targets or "jpg" in targets:
                display = colour.to_display(rgb, space)[..., :3]
                if "png16" in targets:
                    _write_png16(targets["png16"][i], display)
                if "jpg" in targets:
                    _write_jpg(targets["jpg"][i], (display * 255.0 + 0.5).astype(np.uint8))

        # Video must be decoded in order; sequence frames are read inside the workers.
        frames = enumerate(_decode_video(self.m["source_paths"][0], self.m["width"], self.m["height"])) \
            if self.m["kind"] == "video" else ((i, None) for i in range(len(self)))
        self._run_parallel(write, frames, progress, cancelled)
        for tier in todo:
            self.m["tiers"][tier] = True
        self._save()
        return self

    def _read_source(self, i):
        pixels = colour.read_image(self.m["source_paths"][i])[0]
        return pixels[..., :3] if pixels.shape[2] >= 3 else np.repeat(pixels, 3, axis=2)

    def _run_parallel(self, fn, items, progress, cancelled):
        """Run fn(i, data) over items on a few threads (OIIO and OpenCV release the GIL)."""
        from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
        workers = max(2, min(8, (os.cpu_count() or 4) - 2))
        total, done, pending = len(self), 0, set()
        with ThreadPoolExecutor(workers) as pool:
            try:
                for i, data in items:
                    if cancelled and cancelled():
                        raise Cancelled()
                    pending.add(pool.submit(fn, i, data))
                    if len(pending) >= workers * 2:
                        finished, pending = wait(pending, return_when=FIRST_COMPLETED)
                        for f in finished:
                            f.result()
                        done += len(finished)
                        if progress:
                            progress(done, total)
                for f in pending:
                    f.result()
                    done += 1
                    if progress:
                        progress(done, total)
            except BaseException:
                for f in pending:
                    f.cancel()
                raise

    def _jpg_from_png16(self, progress, cancelled):
        os.makedirs(self.folder("jpg"), exist_ok=True)
        src, dst = self.paths("png16"), self.paths("jpg")

        def convert(i, _):
            img = cv2.imread(src[i], cv2.IMREAD_UNCHANGED)
            rgb8 = cv2.cvtColor((img.astype(np.float32) / 257.0 + 0.5).astype(np.uint8), cv2.COLOR_BGR2RGB)
            _write_jpg(dst[i], rgb8)

        self._run_parallel(convert, ((i, None) for i in range(len(src))), progress, cancelled)
        self.m["tiers"]["jpg"] = True
        self._save()


def plate_for_folder(folder):
    """The Plate a node input points at, if it is a Media Plate tier folder."""
    if not folder or not os.path.isdir(folder):
        return None
    if os.path.basename(os.path.normpath(folder)) not in TIER_FOLDERS.values():
        return None
    return Plate.open(os.path.dirname(os.path.normpath(folder)))


def tier_folder(folder, tier, progress=None, cancelled=None):
    """Swap a Media Plate input folder for the requested tier, building it if needed.

    Anything that is not a Media Plate folder is returned unchanged.
    """
    plate = plate_for_folder(folder)
    if plate is None:
        return folder
    plate.ensure(tier, progress=progress, cancelled=cancelled)
    return plate.folder(tier)

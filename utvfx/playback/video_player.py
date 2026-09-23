"""Viewer playback: a decode thread per clip and one shared, memory-bounded frame cache.

Frames are decoded once and kept in FRAME_CACHE (least recently used first out),
so scrubbing and looping over a range do not decode again. Video is read
sequentially and only seeks when the playhead jumps.

    player = VideoPlayerThread(path)
    player.frame_ready.connect(on_frame)   # QImage, frame index, total frames
    player.start()
"""
import glob
import os
import re
import threading
import time
from collections import OrderedDict

import cv2
import numpy as np
from PySide6.QtCore import QMutex, QMutexLocker, QThread, Signal
from PySide6.QtGui import QImage

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".exr", ".dpx", ".tif", ".tiff", ".hdr")
_FRAME_RE = re.compile(r"^(.*?)(\d+)(\.[^.]+)$")

# Frames kept in memory, shared by every clip in the viewer. A 4K RGB frame is
# about 25 MB, so the default holds about 60 of them. Override with the
# CONTOUR_FRAME_CACHE_MB environment variable (0 turns the cache off).
DEFAULT_CACHE_MB = 1536

# A forward jump of up to this many frames is read through rather than seeked,
# because a seek in long-GOP video (H.264) decodes from the previous keyframe.
_MAX_READ_THROUGH = 12


class FrameCache:
    """Least-recently-used cache of decoded QImages, bounded by bytes and optionally by count.

    Thread-safe: the player thread, the wipe reader and the UI all share one.
    """

    def __init__(self, max_bytes=DEFAULT_CACHE_MB * 1024 * 1024, max_frames=None):
        self.max_bytes = int(max_bytes)
        self.max_frames = max_frames
        self.nbytes = 0
        self.hits = 0
        self.misses = 0
        self._items = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self):
        return len(self._items)

    def __contains__(self, key):
        with self._lock:
            return key in self._items

    def get(self, key):
        with self._lock:
            image = self._items.get(key)
            if image is None:
                self.misses += 1
                return None
            self._items.move_to_end(key)
            self.hits += 1
            return image

    def put(self, key, image):
        if image is None or image.isNull():
            return
        size = image.sizeInBytes()
        with self._lock:
            if size > self.max_bytes:
                return  # larger than the whole cache
            old = self._items.pop(key, None)
            if old is not None:
                self.nbytes -= old.sizeInBytes()
            self._items[key] = image
            self.nbytes += size
            self._evict()

    def set_limit(self, max_bytes=None, max_frames=None):
        with self._lock:
            if max_bytes is not None:
                self.max_bytes = int(max_bytes)
            self.max_frames = max_frames
            self._evict()

    def clear(self):
        with self._lock:
            self._items.clear()
            self.nbytes = 0
            self.hits = 0
            self.misses = 0

    def _evict(self):
        while self._items and (
            self.nbytes > self.max_bytes
            or (self.max_frames is not None and len(self._items) > self.max_frames)
        ):
            _, image = self._items.popitem(last=False)
            self.nbytes -= image.sizeInBytes()


def _cache_bytes_from_env():
    try:
        return max(0, int(os.environ.get("CONTOUR_FRAME_CACHE_MB", DEFAULT_CACHE_MB))) * 1024 * 1024
    except ValueError:
        return DEFAULT_CACHE_MB * 1024 * 1024


FRAME_CACHE = FrameCache(_cache_bytes_from_env())


# ---- Finding frames -----------------------------------------------------------

def _start_offset(first_number):
    return 1 if first_number == 0 else first_number


def sequence_files(media_path):
    """(files, start_frame_offset, index_of_media_path) for an image or a folder of images.

    Only one sequence is taken from a folder (same name prefix and extension),
    ordered by frame number.
    """
    from utvfx.core.plate import find_sequence

    seq = find_sequence(media_path)
    if os.path.isdir(media_path):
        if not seq:
            # Unnumbered images: take them all, in name order.
            files = []
            for ext in IMAGE_EXTS:
                files.extend(glob.glob(os.path.join(media_path, "*" + ext)))
            return sorted(set(files)), 1, 0
    elif not seq:
        seq = [(1, media_path)]
    files = [p for _, p in seq]
    offset = _start_offset(seq[0][0]) if _FRAME_RE.match(os.path.basename(files[0])) else 1
    index = 0
    norm = os.path.normcase(os.path.normpath(media_path))
    for i, p in enumerate(files):
        if os.path.normcase(os.path.normpath(p)) == norm:
            index = i
            break
    return files, offset, index


def is_image_path(media_path):
    return os.path.isdir(media_path) or os.path.splitext(media_path)[1].lower() in IMAGE_EXTS


_video_info_cache = {}


def probe_media(media_path):
    """(total_frames, start_frame_offset) of a clip without decoding any frame.

    For video the container header is read once per file version and remembered.
    """
    if not media_path or not os.path.exists(media_path):
        return 0, 1
    if is_image_path(media_path):
        files, offset, _ = sequence_files(media_path)
        return len(files), offset
    try:
        key = (media_path, os.path.getmtime(media_path))
    except OSError:
        return 0, 1
    info = _video_info_cache.get(key)
    if info is None:
        cap = cv2.VideoCapture(media_path)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if cap.isOpened() else 0
        cap.release()
        info = (max(1, count), 1)
        _video_info_cache[key] = info
    return info


# ---- Decoding -----------------------------------------------------------------

def to_display_rgb(frame, view_mode="COMP"):
    """8-bit BGR/BGRA/grey from OpenCV or load_frame -> contiguous 8-bit RGB for the viewer."""
    if frame is None:
        return None
    if view_mode == "MATTE":
        if frame.ndim == 3 and frame.shape[2] == 4:
            grey = frame[:, :, 3]
        elif frame.ndim == 2 or frame.shape[2] == 1:
            grey = frame.reshape(frame.shape[0], frame.shape[1])
        else:
            grey = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2GRAY)
        rgb = cv2.cvtColor(np.ascontiguousarray(grey), cv2.COLOR_GRAY2RGB)
    elif frame.ndim == 2 or frame.shape[2] == 1:
        rgb = cv2.cvtColor(frame.reshape(frame.shape[0], frame.shape[1]), cv2.COLOR_GRAY2RGB)
    elif frame.shape[2] == 4:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
    else:
        rgb = cv2.cvtColor(np.ascontiguousarray(frame[:, :, :3]), cv2.COLOR_BGR2RGB)
    return np.ascontiguousarray(rgb)


def rgb_to_qimage(rgb):
    """A QImage that owns its pixels (the numpy buffer can be freed afterwards)."""
    h, w, ch = rgb.shape
    return QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()


class MediaReader:
    """Reads frames of one clip (image sequence or video) through the shared cache.

    Not thread-safe: each reader belongs to one thread. The video capture stays
    open between reads, so consecutive frames are decoded sequentially.
    """

    def __init__(self, media_path, cache=None):
        self.media_path = media_path
        self.cache = FRAME_CACHE if cache is None else cache
        self.is_sequence = is_image_path(media_path)
        self.sequence_files = []
        self.start_frame_offset = 1
        self.first_index = 0
        self.total_frames = 1
        self.fps = 24.0
        self.cap = None
        self._video_pos = -1  # frame the capture returns on its next read
        self._video_key = None
        if self.is_sequence:
            self.sequence_files, self.start_frame_offset, self.first_index = sequence_files(media_path)
            self.total_frames = len(self.sequence_files)

    def open(self):
        """Open the video container (slow for some codecs, so call it off the UI thread)."""
        if self.is_sequence or self.cap is not None:
            return
        self.cap = cv2.VideoCapture(self.media_path)
        if self.cap.isOpened():
            self.total_frames = max(1, int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)))
            fps = self.cap.get(cv2.CAP_PROP_FPS)
            self.fps = fps if fps and fps > 0 else 24.0
            self._video_pos = 0
        try:
            self._video_key = (self.media_path, os.path.getmtime(self.media_path))
        except OSError:
            self._video_key = (self.media_path, 0)

    def close(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def _key(self, index, view_mode):
        mode = "MATTE" if view_mode == "MATTE" else "RGB"
        if self.is_sequence:
            path = self.sequence_files[index]
            try:
                st = os.stat(path)
            except OSError:
                return None
            return (path, st.st_mtime_ns, st.st_size, mode)
        return (self._video_key, index, mode)

    def read(self, index, view_mode="COMP"):
        """The frame at `index` (clamped to the clip) as an RGB QImage, or None."""
        if self.is_sequence:
            if not self.sequence_files:
                return None
            index = min(max(index, 0), len(self.sequence_files) - 1)
        else:
            self.open()
            if self.cap is None or not self.cap.isOpened():
                return None
            index = min(max(index, 0), self.total_frames - 1)

        key = self._key(index, view_mode)
        if key is not None:
            image = self.cache.get(key)
            if image is not None:
                return image

        if self.is_sequence:
            from utvfx.core.image_utils import load_frame
            frame = load_frame(self.sequence_files[index])
        else:
            frame = self._read_video(index)
        rgb = to_display_rgb(frame, view_mode)
        if rgb is None:
            return None
        image = rgb_to_qimage(rgb)
        if key is not None:
            self.cache.put(key, image)
        return image

    def _read_video(self, index):
        gap = index - self._video_pos
        if self._video_pos < 0 or gap < 0 or gap > _MAX_READ_THROUGH:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        else:
            for _ in range(gap):
                if not self.cap.grab():
                    break
        ok, frame = self.cap.read()
        self._video_pos = index + 1 if ok else -1
        return frame if ok else None


# ---- Threads ------------------------------------------------------------------

class VideoPlayerThread(QThread):
    frame_ready = Signal(QImage, int, int)  # image, current_frame, total_frames
    playback_finished = Signal()            # reached the out point with looping off

    def __init__(self, media_path, cache=None):
        super().__init__()
        self.media_path = media_path
        self.is_running = True
        self.is_paused = True  # paused by default, no autoplay
        self.loop = True       # off: stop at the out point
        self.view_mode = "COMP"
        self.in_frame = None
        self.out_frame = None
        self.mutex = QMutex()
        self.target_frame = 0
        self.seek_requested = False

        self.reader = MediaReader(media_path, cache)
        self.is_sequence = self.reader.is_sequence
        self.sequence_files = self.reader.sequence_files
        self.start_frame_offset = self.reader.start_frame_offset
        self.current_frame = self.reader.first_index
        # Video length is read in run(), off the UI thread.
        self.total_frames = self.reader.total_frames if self.is_sequence else 1
        self.fps = 24

    def stop(self):
        self.is_running = False
        self.wait()

    def seek(self, frame_idx):
        with QMutexLocker(self.mutex):
            self.target_frame = min(max(frame_idx, 0), self.total_frames - 1)
            self.seek_requested = True

    @staticmethod
    def _placeholder_frame(text, width=1280, height=720):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPainter
        from utvfx.ui import theme
        qimg = QImage(width, height, QImage.Format.Format_RGB888)  # owns its buffer
        qimg.fill(theme.qcolor(theme.BG_VIEWER))
        painter = QPainter(qimg)
        painter.setPen(theme.qcolor(theme.TEXT_FAINT))
        painter.setFont(theme.ui_font(18))
        painter.drawText(qimg.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        return qimg

    def read_and_emit(self, frame_idx):
        if self.is_sequence and not self.sequence_files:
            self.frame_ready.emit(self._placeholder_frame("Nothing rendered yet"), 0, 0)
            return
        image = self.reader.read(frame_idx, self.view_mode)
        if image is None:
            return
        # A newer seek arrived while this frame decoded: skip it (it is cached anyway).
        with QMutexLocker(self.mutex):
            if self.seek_requested:
                return
            total = self.total_frames
        frame_idx = min(max(frame_idx, 0), max(0, total - 1))
        self.frame_ready.emit(image, frame_idx, total)

    def _bounds(self):
        start = self.in_frame if self.in_frame is not None else 0
        end = self.out_frame if self.out_frame is not None else self.total_frames - 1
        return start, end

    def run(self):
        if not self.is_sequence:
            self.reader.open()
            with QMutexLocker(self.mutex):
                self.total_frames = max(self.total_frames, self.reader.total_frames)
                self.fps = self.reader.fps

        with QMutexLocker(self.mutex):
            initial_frame = self.current_frame
        self.read_and_emit(initial_frame)

        while self.is_running:
            seek_target = None
            with QMutexLocker(self.mutex):
                if self.seek_requested:
                    seek_target = self.target_frame
                    self.seek_requested = False
                    self.current_frame = seek_target

            if seek_target is not None:
                self.read_and_emit(seek_target)
                continue

            if not self.is_paused and self.total_frames > 1:
                loop_start = time.perf_counter()
                finished = False
                with QMutexLocker(self.mutex):
                    start_bound, end_bound = self._bounds()
                    nxt = self.current_frame + 1
                    if self.current_frame < start_bound or self.current_frame > end_bound:
                        nxt = start_bound
                    elif nxt > end_bound:
                        if self.loop:
                            nxt = start_bound
                        else:
                            finished = True
                    if not finished:
                        self.current_frame = nxt
                    frame_to_read = self.current_frame

                if finished:
                    self.is_paused = True
                    self.playback_finished.emit()
                    continue

                self.read_and_emit(frame_to_read)
                elapsed = time.perf_counter() - loop_start
                self.msleep(int(max(0.0, 1.0 / (self.fps or 24) - elapsed) * 1000))
            else:
                self.msleep(10)

        self.reader.close()


class FrameReaderThread(QThread):
    """Reads single frames on request, off the UI thread (the wipe's B side).

    Only the latest request is served; older ones are dropped. The clip stays
    open between requests, so video is not reopened for every frame.
    """
    frame_ready = Signal(str, int, QImage)  # media path, frame index, image

    def __init__(self, parent=None, cache=None):
        super().__init__(parent)
        self._cache = cache
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._request = None
        self._running = True
        self._reader = None

    def request(self, media_path, frame_idx, view_mode="SRC"):
        with self._lock:
            self._request = (media_path, frame_idx, view_mode)
        self._wake.set()
        if not self.isRunning():
            self.start()

    def stop(self):
        self._running = False
        self._wake.set()
        self.wait()

    def run(self):
        while self._running:
            self._wake.wait(0.5)
            self._wake.clear()
            with self._lock:
                req, self._request = self._request, None
            if req is None or not self._running:
                continue
            path, index, mode = req
            if self._reader is None or self._reader.media_path != path:
                if self._reader is not None:
                    self._reader.close()
                self._reader = MediaReader(path, self._cache)
            try:
                image = self._reader.read(index, mode)
            except Exception:
                image = None
            if image is not None:
                self.frame_ready.emit(path, index, image)
        if self._reader is not None:
            self._reader.close()

"""Viewer playback: the frame cache, sequential video reads and the loop toggle.

Only synthetic frames written to tmp_path are used.
"""
import cv2
import numpy as np
import pytest
from PySide6.QtGui import QImage

from utvfx.playback.video_player import (
    FrameCache, MediaReader, VideoPlayerThread, probe_media, sequence_files,
)


def _image(w=10, h=10):
    img = QImage(w, h, QImage.Format.Format_RGB888)
    img.fill(0)
    return img


@pytest.fixture
def png_sequence(tmp_path):
    folder = tmp_path / "seq"
    folder.mkdir()
    for i, frame in enumerate(range(1001, 1006)):
        pixels = np.full((24, 32, 3), i * 40, np.uint8)
        cv2.imwrite(str(folder / f"shot.{frame}.png"), pixels)
    # A second, shorter sequence in the same folder must not be mixed in
    cv2.imwrite(str(folder / "other.0001.png"), np.zeros((24, 32, 3), np.uint8))
    return folder


def test_cache_hit_and_miss(qapp):
    cache = FrameCache(max_bytes=10 * 1024 * 1024)
    assert cache.get("a") is None
    cache.put("a", _image())
    assert cache.get("a") is not None
    assert (cache.hits, cache.misses) == (1, 1)


def test_cache_is_bounded_by_memory_lru_first(qapp):
    one = _image(100, 100).sizeInBytes()
    cache = FrameCache(max_bytes=one * 3)
    for key in "abc":
        cache.put(key, _image(100, 100))
    cache.get("a")                      # a is now the most recently used
    cache.put("d", _image(100, 100))    # evicts b, the least recently used
    assert "b" not in cache
    assert all(k in cache for k in "acd")
    assert cache.nbytes <= cache.max_bytes


def test_cache_frame_limit_and_oversized_frames(qapp):
    cache = FrameCache(max_bytes=10 * 1024 * 1024, max_frames=2)
    for key in "abc":
        cache.put(key, _image())
    assert len(cache) == 2 and "a" not in cache
    tiny = FrameCache(max_bytes=10)
    tiny.put("big", _image())
    assert len(tiny) == 0 and tiny.nbytes == 0


def test_sequence_listing_and_probe(png_sequence):
    files, offset, _ = sequence_files(str(png_sequence))
    assert len(files) == 5 and offset == 1001
    assert probe_media(str(png_sequence)) == (5, 1001)


def test_reader_decodes_each_frame_once(qapp, png_sequence, monkeypatch):
    import utvfx.core.image_utils as image_utils
    calls = []
    real = image_utils.load_frame
    monkeypatch.setattr(image_utils, "load_frame", lambda p, *a: calls.append(p) or real(p, *a))

    reader = MediaReader(str(png_sequence), FrameCache())
    for _ in range(3):  # scrub back and forth over the whole range
        for i in range(5):
            assert reader.read(i) is not None
    assert len(calls) == 5
    assert reader.cache.hits == 10


def test_reader_rereads_a_frame_that_changed_on_disk(qapp, png_sequence):
    reader = MediaReader(str(png_sequence), FrameCache())
    before = reader.read(0)
    path = reader.sequence_files[0]
    cv2.imwrite(path, np.full((24, 32, 3), 255, np.uint8))
    import os, time
    os.utime(path, ns=(time.time_ns(), time.time_ns() + 10_000_000))
    after = reader.read(0)
    assert before.pixelColor(0, 0) != after.pixelColor(0, 0)


def test_cached_image_owns_its_pixels(qapp, png_sequence):
    reader = MediaReader(str(png_sequence), FrameCache())
    image = reader.read(2)
    import gc
    gc.collect()
    assert image.pixelColor(0, 0).red() == 80


@pytest.fixture
def small_video(tmp_path):
    path = str(tmp_path / "clip.avi")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 24, (32, 24))
    if not writer.isOpened():
        pytest.skip("no video encoder")
    for i in range(20):
        writer.write(np.full((24, 32, 3), i * 10, np.uint8))
    writer.release()
    return path


class _CountingCapture:
    def __init__(self, cap):
        self.cap = cap
        self.seeks = 0

    def set(self, *args):
        self.seeks += 1
        return self.cap.set(*args)

    def __getattr__(self, name):
        return getattr(self.cap, name)


def test_video_is_read_sequentially(qapp, small_video):
    reader = MediaReader(small_video, FrameCache())
    reader.open()
    reader.cap = _CountingCapture(reader.cap)
    for i in range(10):
        assert reader.read(i) is not None
    assert reader.cap.seeks == 0          # playing forward never seeks
    reader.read(15)                        # a short jump forward reads through
    assert reader.cap.seeks == 0
    reader.read(2)                         # (cached) going back costs nothing
    assert reader.cap.seeks == 0
    reader.cache.clear()
    reader.read(3)                         # uncached jump back: one seek
    assert reader.cap.seeks == 1
    reader.close()


def test_playback_stops_at_out_point_when_not_looping(qtbot, png_sequence):
    player = VideoPlayerThread(str(png_sequence))
    player.loop = False
    player.out_frame = 3
    frames = []
    player.frame_ready.connect(lambda img, idx, total: frames.append(idx))
    player.start()
    try:
        qtbot.waitUntil(lambda: 0 in frames, timeout=3000)
        with qtbot.waitSignal(player.playback_finished, timeout=3000):
            player.is_paused = False
        assert player.is_paused
        assert player.current_frame == 3
        assert max(frames) == 3
    finally:
        player.stop()


def test_playback_loops_by_default(qtbot, png_sequence):
    player = VideoPlayerThread(str(png_sequence))
    assert player.loop
    player.out_frame = 2
    frames = []
    player.frame_ready.connect(lambda img, idx, total: frames.append(idx))
    player.start()
    try:
        player.is_paused = False
        qtbot.waitUntil(lambda: frames.count(0) >= 2, timeout=3000)  # wrapped round
        assert max(frames) == 2
    finally:
        player.stop()


def test_wipe_reader_reads_off_the_ui_thread(qtbot, png_sequence):
    from utvfx.playback.video_player import FrameReaderThread
    reader = FrameReaderThread()
    got = []
    reader.frame_ready.connect(lambda path, idx, img: got.append((idx, img.pixelColor(0, 0).red())))
    try:
        reader.request(str(png_sequence), 3)
        qtbot.waitUntil(lambda: bool(got), timeout=3000)
        assert got[-1] == (3, 120)
    finally:
        reader.stop()


def test_frame_box_jumps_to_a_plate_frame_number(qtbot, png_sequence):
    from utvfx.ui.viewport import Viewport
    viewport = Viewport()
    qtbot.addWidget(viewport)
    viewport.handle_media_loaded(str(png_sequence), 5, 24.0)
    player = viewport.player_thread
    try:
        assert player.loop  # the loop button starts on
        viewport.btn_loop.setChecked(False)
        assert player.loop is False
        qtbot.waitUntil(lambda: viewport.frame_box.text() == "1001", timeout=3000)
        viewport.frame_box.setText("1004")
        viewport.frame_box.returnPressed.emit()
        qtbot.waitUntil(lambda: player.current_frame == 3, timeout=3000)
        qtbot.waitUntil(lambda: viewport.frame_box.text() == "1004", timeout=3000)
    finally:
        player.stop()

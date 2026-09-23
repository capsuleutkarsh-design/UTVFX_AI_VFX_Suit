import math
import time
import os
import cv2
import numpy as np
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPolygonF, QPainterPath, QImage
from PySide6.QtCore import Qt, Signal, QPointF, QRectF, QThread

from utvfx.ui import theme

class ThumbnailGeneratorThread(QThread):
    thumbnail_ready = Signal(int, QImage)
    
    def __init__(self, media_path, is_sequence, total_frames, parent=None):
        super().__init__(parent)
        self.media_path = media_path
        self.is_sequence = is_sequence
        self.total_frames = total_frames
        self.is_running = True
        self.target_height = 26

    def run(self):
        if not self.media_path or self.total_frames <= 0:
            return
            
        # Generate ~100 thumbnails uniformly
        step = max(1, self.total_frames // 100)
        
        cap = None
        files = []
        if self.is_sequence and os.path.isdir(self.media_path):
            files = sorted([f for f in os.listdir(self.media_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.exr', '.dpx'))])
        elif not self.is_sequence:
            cap = cv2.VideoCapture(self.media_path)
            
        for i in range(0, self.total_frames, step):
            if not self.is_running: break
            
            frame = None
            if self.is_sequence and i < len(files):
                path = os.path.join(self.media_path, files[i])
                from utvfx.core.image_utils import load_frame
                frame = load_frame(path)
            elif cap:
                cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                ret, frame = cap.read()
                if not ret: frame = None
                
            if frame is not None:
                h, w = frame.shape[:2]
                scale = self.target_height / float(h)
                new_w = int(w * scale)
                frame = cv2.resize(frame, (new_w, self.target_height))
                
                if len(frame.shape) == 2:
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                elif len(frame.shape) == 3 and frame.shape[2] == 4:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
                else:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    
                img = QImage(frame.data, new_w, self.target_height, new_w * 3, QImage.Format.Format_RGB888).copy()
                self.thumbnail_ready.emit(i, img)
                
            self.msleep(10)
            
        if cap:
            cap.release()

    def stop(self):
        self.is_running = False
        self.wait()

class TimelineWidget(QWidget):
    """
    A custom timeline scrubber widget for professional VFX workflows.
    Features frame ticks, playhead, and keyframe indicators.
    """
    frame_seeked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(26)

        self._current_frame = 0
        self._total_frames = 100  # Default to 100 if no media loaded
        self._start_frame = 1
        self._keyframes = set()
        self._in_frame = None
        self._out_frame = None

        self._is_scrubbing = False
        self._last_seek_time = 0.0
        
        self._thumbnails = {}
        self._thumbnail_thread = None

        # Visual styling (all from the theme)
        self.bg_color = theme.qcolor(theme.BG_INPUT)
        self.border_color = theme.qcolor(theme.BORDER_SOFT)
        self.highlight_color = theme.qcolor(theme.TEXT, 14)      # in/out range
        self.text_color = theme.qcolor(theme.TEXT_FAINT)
        self.badge_bg_color = theme.qcolor(theme.BG_INPUT)
        self.tick_color = theme.qcolor(theme.TEXT_FAINT)
        self.playhead_color = theme.qcolor(theme.ACCENT)
        self.playhead_line_color = theme.qcolor(theme.ACCENT)
        self.keyframe_color = theme.qcolor(theme.ACCENT)

        # Geometry
        self.margin_left = 8
        self.margin_right = 8

    def set_frames(self, current, total, start_frame=1):
        if not self._is_scrubbing:
            self._current_frame = current
        self._total_frames = max(1, total)
        self._start_frame = start_frame
        self.update()

    def set_media_path(self, media_path, is_sequence):
        if self._thumbnail_thread:
            try:
                self._thumbnail_thread.stop()
            except RuntimeError:
                pass # C++ object already deleted by deleteLater
            self._thumbnail_thread = None
        self._thumbnails.clear()
        
        if media_path and self._total_frames > 0:
            self._thumbnail_thread = ThumbnailGeneratorThread(media_path, is_sequence, self._total_frames, self)
            self._thumbnail_thread.thumbnail_ready.connect(self._on_thumbnail_ready)
            self._thumbnail_thread.finished.connect(self._thumbnail_thread.deleteLater)
            self._thumbnail_thread.start()

    def _on_thumbnail_ready(self, frame_idx, img):
        self._thumbnails[frame_idx] = img
        self.update()

    def set_current_frame(self, frame):
        if not self._is_scrubbing:
            self._current_frame = max(0, min(frame, self._total_frames - 1))
            self.update()

    def set_keyframes(self, keyframes):
        self._keyframes = set(keyframes)
        self.update()

    def set_in_frame(self, frame):
        self._in_frame = frame
        self.update()

    def set_out_frame(self, frame):
        self._out_frame = frame
        self.update()

    def _x_for_frame(self, frame):
        usable_width = self.width() - self.margin_left - self.margin_right
        if self._total_frames <= 1:
            return self.margin_left
        ratio = frame / float(self._total_frames - 1)
        return self.margin_left + (ratio * usable_width)

    def _frame_for_x(self, x):
        usable_width = self.width() - self.margin_left - self.margin_right
        if usable_width <= 0:
            return 0
        ratio = (x - self.margin_left) / usable_width
        frame = int(round(ratio * (self._total_frames - 1)))
        return max(0, min(frame, self._total_frames - 1))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_scrubbing = True
            frame = self._frame_for_x(event.position().x())
            if frame != self._current_frame:
                self._current_frame = frame
                self._last_seek_time = time.time()
                self.frame_seeked.emit(frame)
                self.update()

    def mouseMoveEvent(self, event):
        if self._is_scrubbing:
            frame = self._frame_for_x(event.position().x())
            if frame != self._current_frame:
                self._current_frame = frame
                self.update()
                
                # Throttle scrubbing to ~25fps (40ms) to prevent video player jumping
                now = time.time()
                if now - self._last_seek_time > 0.040:
                    self._last_seek_time = now
                    self.frame_seeked.emit(frame)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_scrubbing = False
            # Ensure we seek to the final frame on release
            frame = self._frame_for_x(event.position().x())
            self.frame_seeked.emit(frame)

    @staticmethod
    def _nice_step(min_frames):
        """Smallest 1/2/5 x 10^n frame step that is at least `min_frames`."""
        step = 1
        while True:
            for m in (1, 2, 5):
                if step * m >= min_frames:
                    return step * m
            step *= 10

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        h = self.height()

        # Flat track
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.border_color, 1))
        painter.setBrush(QBrush(self.bg_color))
        painter.drawRoundedRect(rect, 2, 2)

        clip_path = QPainterPath()
        clip_path.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 2, 2)
        painter.setClipPath(clip_path)

        # Thumbnails, kept faint so ticks and playhead stay readable
        if self._thumbnails:
            painter.setOpacity(0.25)
            for frame_idx, img in sorted(self._thumbnails.items()):
                x = self._x_for_frame(frame_idx)
                painter.drawImage(QRectF(x - img.width() / 2, 0, img.width(), h), img)
            painter.setOpacity(1.0)

        playhead_x = self._x_for_frame(self._current_frame)

        # In/out range: the range is lifted slightly, its ends marked with thin lines
        if self._in_frame is not None or self._out_frame is not None:
            in_x = self._x_for_frame(self._in_frame) if self._in_frame is not None else self.margin_left
            out_x = self._x_for_frame(self._out_frame) if self._out_frame is not None else self.width() - self.margin_right
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(self.highlight_color))
            painter.drawRect(QRectF(in_x, 0, out_x - in_x, h))
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setPen(QPen(theme.qcolor(theme.TEXT_DIM), 1))
            if self._in_frame is not None:
                painter.drawLine(QPointF(in_x, 0), QPointF(in_x, h))
            if self._out_frame is not None:
                painter.drawLine(QPointF(out_x, 0), QPointF(out_x, h))
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Frame ticks and numbers
        usable_width = self.width() - self.margin_left - self.margin_right
        pixels_per_frame = usable_width / max(1, self._total_frames - 1)
        font = theme.mono_font(7)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        label_w = metrics.horizontalAdvance(str(self._total_frames + self._start_frame)) + 10
        minor = self._nice_step(6.0 / max(pixels_per_frame, 1e-6))
        major = self._nice_step(max(label_w, 40) / max(pixels_per_frame, 1e-6))
        if major % minor:
            major = minor * max(1, round(major / minor))

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        tick_pen = QPen(self.tick_color, 1)
        painter.setPen(tick_pen)
        if self._total_frames > 1:
            # Ticks sit on round frame numbers (1010, 1020...), not on offsets from the start
            first = (-self._start_frame) % minor
            for frame in range(first, self._total_frames, minor):
                x = int(round(self._x_for_frame(frame)))
                tick_h = 7 if (frame + self._start_frame) % major == 0 else 3
                painter.drawLine(x, h - 1 - tick_h, x, h - 2)

            painter.setPen(QPen(self.text_color, 1))
            text_y = metrics.ascent() + 2
            first = (-self._start_frame) % major
            for frame in range(first, self._total_frames, major):
                x = self._x_for_frame(frame)
                if x + 3 + metrics.horizontalAdvance(str(frame + self._start_frame)) > self.width() - 2:
                    break
                painter.drawText(int(x + 3), text_y, str(frame + self._start_frame))

        # Keyframes: short accent ticks along the bottom edge
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self.keyframe_color))
        for kf in self._keyframes:
            if 0 <= kf < self._total_frames:
                x = int(round(self._x_for_frame(kf)))
                painter.drawRect(x - 1, h - 6, 2, 5)

        # Playhead: 1 px accent line with a small handle at the top
        px = int(round(playhead_x))
        painter.setPen(QPen(self.playhead_line_color, 1))
        painter.drawLine(px, 0, px, h)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self.playhead_color))
        painter.drawPolygon(QPolygonF([
            QPointF(px - 4.5, 0), QPointF(px + 5.5, 0), QPointF(px + 5.5, 4),
            QPointF(px + 0.5, 8), QPointF(px - 4.5, 4),
        ]))

        painter.setClipping(False)
        painter.end()

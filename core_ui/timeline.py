import math
import time
import os
import cv2
import numpy as np
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPolygonF, QPainterPath, QImage
from PySide6.QtCore import Qt, Signal, QPointF, QRectF, QThread

class ThumbnailGeneratorThread(QThread):
    thumbnail_ready = Signal(int, QImage)
    
    def __init__(self, media_path, is_sequence, total_frames, parent=None):
        super().__init__(parent)
        self.media_path = media_path
        self.is_sequence = is_sequence
        self.total_frames = total_frames
        self.is_running = True
        self.target_height = 40

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
                frame = cv2.imread(path, cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
                if frame is not None:
                    if frame.dtype == np.float32 or frame.dtype == np.float64:
                        frame = np.clip(frame, 0.0, 1.0)
                        frame = np.power(frame, 1.0/2.2) # Basic linear to sRGB
                        frame = (frame * 255.0).astype(np.uint8)
                    elif frame.dtype == np.uint16:
                        frame = (frame / 256).astype(np.uint8)
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
                    
                img = QImage(frame.data, new_w, self.target_height, new_w * 3, QImage.Format_RGB888).copy()
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
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(40)  # Standard timeline height

        self._current_frame = 0
        self._total_frames = 100  # Default to 100 if no media loaded
        self._start_frame = 1
        self._keyframes = set()
        self._in_frame = None
        self._out_frame = None

        self._is_scrubbing = False
        self._last_seek_time = 0
        
        self._thumbnails = {}
        self._thumbnail_thread = None

        # Visual styling
        self.bg_color = QColor("#0f172a") # Very dark blue/grey
        self.border_color = QColor("#1e293b")
        self.highlight_color = QColor(245, 158, 11, 40) # Translucent orange
        self.text_color = QColor("#94a3b8")
        self.badge_bg_color = QColor("#020617")
        self.tick_color = QColor("#334155")
        self.playhead_color = QColor("#f59e0b")  # Bright orange
        self.playhead_line_color = QColor("#f59e0b")
        self.keyframe_color = QColor("#3b82f6")
        
        # Geometry
        self.margin_left = 20
        self.margin_right = 20

    def set_frames(self, current, total, start_frame=1):
        if not self._is_scrubbing:
            self._current_frame = current
        self._total_frames = max(1, total)
        self._start_frame = start_frame
        self.update()

    def set_media_path(self, media_path, is_sequence):
        if self._thumbnail_thread:
            self._thumbnail_thread.stop()
            self._thumbnail_thread = None
        self._thumbnails.clear()
        
        if media_path and self._total_frames > 0:
            self._thumbnail_thread = ThumbnailGeneratorThread(media_path, is_sequence, self._total_frames, self)
            self._thumbnail_thread.thumbnail_ready.connect(self._on_thumbnail_ready)
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
        if event.button() == Qt.LeftButton:
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
        if event.button() == Qt.LeftButton:
            self._is_scrubbing = False
            # Ensure we seek to the final frame on release
            frame = self._frame_for_x(event.position().x())
            self.frame_seeked.emit(frame)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        corner_radius = rect.height() / 2.0

        # Draw main pill background
        painter.setPen(QPen(self.border_color, 1))
        painter.setBrush(QBrush(self.bg_color))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), corner_radius, corner_radius)
        
        # Draw Thumbnails inside the pill (clipping applied)
        if self._thumbnails:
            clip_path = QPainterPath()
            clip_path.addRoundedRect(rect.adjusted(1, 1, -1, -1), corner_radius, corner_radius)
            painter.setClipPath(clip_path)
            
            painter.setOpacity(0.4) # Make them subtle so they don't overpower the timeline
            for frame_idx, img in sorted(self._thumbnails.items()):
                x = self._x_for_frame(frame_idx)
                # Draw image centered on its x
                painter.drawImage(QRectF(x - img.width()/2, 0, img.width(), self.height()), img)
            
            painter.setOpacity(1.0)
            painter.setClipping(False)

        usable_width = self.width() - self.margin_left - self.margin_right
        playhead_x = self._x_for_frame(self._current_frame)

        # Draw In and Out markers range
        if self._in_frame is not None or self._out_frame is not None:
            in_x = self._x_for_frame(self._in_frame) if self._in_frame is not None else self.margin_left
            out_x = self._x_for_frame(self._out_frame) if self._out_frame is not None else self.width() - self.margin_right
            
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(255, 255, 255, 15))) # Slight white highlight for the valid range
            
            clip_path = QPainterPath()
            clip_path.addRoundedRect(rect.adjusted(1, 1, -1, -1), corner_radius, corner_radius)
            painter.setClipPath(clip_path)
            
            painter.drawRect(QRectF(in_x, 1, out_x - in_x, rect.height() - 2))
            
            # Draw In marker line
            if self._in_frame is not None:
                painter.setPen(QPen(QColor("#a855f7"), 2))
                painter.drawLine(QPointF(in_x, 0), QPointF(in_x, rect.height()))
            
            # Draw Out marker line
            if self._out_frame is not None:
                painter.setPen(QPen(QColor("#a855f7"), 2))
                painter.drawLine(QPointF(out_x, 0), QPointF(out_x, rect.height()))
                
            painter.setClipping(False)

        # Draw translucent orange highlight for elapsed time
        if playhead_x > self.margin_left:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(self.highlight_color))
            # Create a clipping path for the pill shape
            clip_path = QPainterPath()
            clip_path.addRoundedRect(QRectF(rect.adjusted(1, 1, -1, -1)), corner_radius, corner_radius)
            painter.setClipPath(clip_path)
            
            highlight_rect = QRectF(0, 0, playhead_x, self.height())
            painter.drawRect(highlight_rect)
            
            # Remove clipping
            painter.setClipping(False)

        painter.setFont(QFont("Space Grotesk", 8))
        
        # Draw Ticks (Dense Waveform style mapped to pixels, not frames)
        # This guarantees it always looks like a dense audio waveform
        pixel_step = 6
        for x_pos in range(self.margin_left, self.width() - self.margin_right, pixel_step):
            # Calculate height using pseudo-random waveform
            h = 6 + (math.sin(x_pos * 0.1) * 5) + (math.cos(x_pos * 0.03) * 3)
            
            if x_pos < playhead_x:
                painter.setPen(QPen(QColor("#b45309"), 1.5)) # Muted orange for past
            else:
                painter.setPen(QPen(QColor("#1e293b"), 1.5)) # Muted dark blue for future
                
            painter.drawLine(x_pos, int(self.height() / 2 - h), x_pos, int(self.height() / 2 + h))

        # Dynamic text intervals
        pixels_per_frame = usable_width / max(1, self._total_frames - 1)
        if pixels_per_frame > 10:
            text_interval = 5
        elif pixels_per_frame > 5:
            text_interval = 10
        elif pixels_per_frame > 1:
            text_interval = 60
        else:
            text_interval = 120

        # Draw Text Badges
        for frame in range(0, self._total_frames, 1):
            if frame % text_interval == 0:
                x = self._x_for_frame(frame)
                text = str(frame + self._start_frame)
                text_rect = painter.fontMetrics().boundingRect(text)
                
                badge_w = text_rect.width() + 16
                badge_h = text_rect.height() + 6
                badge_x = x - badge_w / 2
                badge_y = self.height() / 2 - badge_h / 2
                
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor("#020617"))) # Dark badge
                painter.drawRoundedRect(QRectF(badge_x, badge_y, badge_w, badge_h), badge_h/2, badge_h/2)
                
                painter.setPen(QPen(self.text_color, 1))
                painter.drawText(int(x - text_rect.width() / 2), int(self.height() / 2 + text_rect.height() / 3), text)

        # Draw Keyframes
        painter.setBrush(QBrush(self.keyframe_color))
        painter.setPen(Qt.NoPen)
        for kf in self._keyframes:
            if 0 <= kf < self._total_frames:
                x = self._x_for_frame(kf)
                painter.drawEllipse(QPointF(x, self.height() / 2 + 12), 3, 3)

        # Draw Playhead Line
        # Add a subtle glow/shadow to the line by drawing a slightly thicker transparent line behind it
        painter.setPen(QPen(QColor(245, 158, 11, 100), 4))
        painter.drawLine(int(playhead_x), 0, int(playhead_x), self.height())
        
        # Solid playhead line
        painter.setPen(QPen(self.playhead_line_color, 2))
        painter.drawLine(int(playhead_x), 0, int(playhead_x), self.height())
        
        # Draw Playhead Circle
        painter.setBrush(QBrush(self.playhead_color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(playhead_x, self.height() / 2), 7, 7)

        painter.end()

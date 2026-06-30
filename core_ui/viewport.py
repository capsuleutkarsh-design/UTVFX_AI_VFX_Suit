import os
import glob
import cv2
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy, QStackedWidget
)
from core_ui.timeline import TimelineWidget
from core_ui.point_cloud_viewer import PointCloudViewerWidget
import time
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer, QMutex, QMutexLocker, QPointF, QRectF
from PySide6.QtGui import QColor, QPalette, QImage, QPixmap, QPainter, QPen, QBrush

# Enable EXR support in OpenCV
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'

class VideoPlayerThread(QThread):
    frame_ready = Signal(QImage, int, int) # image, current_frame, total_frames
    
    def __init__(self, media_path):
        super().__init__()
        self.media_path = media_path
        self.is_running = True
        self.is_paused = True # Default to paused to prevent annoying autoplay
        self.current_frame = 0
        self.total_frames = 1
        self.fps = 24
        self.mutex = QMutex()
        self.target_frame = 0
        self.seek_requested = False
        
        # Determine if it's a sequence or video
        self.is_sequence = False
        self.sequence_files = []
        self.start_frame_offset = 1
        
        if os.path.isdir(self.media_path):
            self.is_sequence = True
            # Load images
            exts = ("*.png", "*.jpg", "*.jpeg", "*.exr", "*.dpx", "*.tif", "*.tiff", "*.hdr")
            for ext in exts:
                self.sequence_files.extend(glob.glob(os.path.join(self.media_path, ext)))
            self.sequence_files.sort()
            self.total_frames = len(self.sequence_files)
            if self.sequence_files:
                import re
                m = re.match(r"^(.*?)(\d+)(\.[^.]+)$", os.path.basename(self.sequence_files[0]))
                if m:
                    offset = int(m.group(2))
                    self.start_frame_offset = 1 if offset == 0 else offset
        else:
            ext = os.path.splitext(self.media_path)[1].lower()
            if ext in [".png", ".jpg", ".jpeg", ".exr", ".dpx", ".tif", ".tiff", ".hdr"]:
                self.is_sequence = True
                
                import re
                folder = os.path.dirname(self.media_path)
                base = os.path.basename(self.media_path)
                m = re.match(r"^(.*?)(\d+)(\.[^.]+)$", base)
                
                if m:
                    prefix, suffix = m.group(1), m.group(3)
                    all_files = glob.glob(os.path.join(folder, f"{prefix}*{suffix}"))
                    
                    seq = []
                    for f in all_files:
                        fb = os.path.basename(f)
                        if re.match(r"^" + re.escape(prefix) + r"\d+" + re.escape(suffix) + r"$", fb):
                            seq.append(f)
                    seq.sort()
                    self.sequence_files = seq if seq else [self.media_path]
                    
                    if self.sequence_files:
                        m_first = re.match(r"^(.*?)(\d+)(\.[^.]+)$", os.path.basename(self.sequence_files[0]))
                        if m_first:
                            offset = int(m_first.group(2))
                            self.start_frame_offset = 1 if offset == 0 else offset
                else:
                    self.sequence_files = [self.media_path]
                
                self.total_frames = max(1, len(self.sequence_files))
                if self.media_path in self.sequence_files:
                    self.current_frame = self.sequence_files.index(self.media_path)
            else:
                # Video file
                self.is_sequence = False
                self.total_frames = 1
                self.start_frame_offset = 1
                self.fps = 24
                # cap initialization is deferred to the run() method to prevent UI freeze
                    

                    
    def stop(self):
        self.is_running = False
        self.wait()
        
    def seek(self, frame_idx):
        with QMutexLocker(self.mutex):
            self.target_frame = min(max(frame_idx, 0), self.total_frames - 1)
            self.seek_requested = True
        
    def read_and_emit(self, frame_idx):
        if self.is_sequence:
            if not self.sequence_files: return
            # Safe clamp to the actual sequence files list size to completely prevent IndexError
            frame_idx = min(max(frame_idx, 0), len(self.sequence_files) - 1)
            path = self.sequence_files[frame_idx]
            frame = None
            ext = os.path.splitext(path)[1].lower()
            
            # 1. Attempt OpenImageIO (Industry Standard for EXR/VFX formats)
            try:
                import OpenImageIO as oiio
                buf = oiio.ImageBuf(path)
                if not buf.has_error:
                    if ext in [".exr", ".dpx", ".hdr"]:
                        oiio.ImageBufAlgo.colorconvert(buf, buf, "linear", "sRGB")
                        
                    raw_frame = buf.get_pixels(oiio.TypeFloat)
                    if raw_frame is not None:
                        raw_frame = np.clip(raw_frame, 0.0, 1.0)
                        raw_frame = (raw_frame * 255.0).astype(np.uint8)
                        
                        if len(raw_frame.shape) == 2 or (len(raw_frame.shape) == 3 and raw_frame.shape[2] == 1):
                            frame = cv2.cvtColor(raw_frame, cv2.COLOR_GRAY2RGB)
                        elif len(raw_frame.shape) == 3 and raw_frame.shape[2] == 4:
                            frame = cv2.cvtColor(raw_frame, cv2.COLOR_RGBA2RGB)
                        elif len(raw_frame.shape) == 3 and raw_frame.shape[2] >= 3:
                            frame = raw_frame[:, :, :3]
            except ImportError:
                pass # Fall back to OpenCV

            # 2. Fallback to OpenCV if OIIO is missing or failed
            if frame is None:
                frame = cv2.imread(path, cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
                if frame is not None:
                    if frame.dtype == np.float32 or frame.dtype == np.float64:
                        frame = np.clip(frame, 0.0, 1.0)
                        if ext in [".exr", ".hdr"]:
                            frame = np.power(frame, 1.0/2.2) # Basic linear to sRGB
                        frame = (frame * 255.0).astype(np.uint8)
                    elif frame.dtype == np.uint16:
                        frame = (frame / 256).astype(np.uint8)
                    
                    if getattr(self, 'view_mode', 'COMPOSITE') == "ALPHA MATTE":
                        if len(frame.shape) == 3 and frame.shape[2] == 4:
                            alpha = frame[:, :, 3]
                            frame = cv2.cvtColor(alpha, cv2.COLOR_GRAY2RGB)
                        elif len(frame.shape) == 2 or (len(frame.shape) == 3 and frame.shape[2] == 1):
                            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                        else:
                            frame = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2GRAY)
                            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                    else:
                        if len(frame.shape) == 2 or (len(frame.shape) == 3 and frame.shape[2] == 1):
                            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                        elif len(frame.shape) == 3 and frame.shape[2] == 4:
                            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
                        elif len(frame.shape) == 3 and frame.shape[2] >= 3:
                            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            frame = frame[:, :, :3]

            if frame is None: return
        else:
            if not hasattr(self, 'cap') or not self.cap.isOpened(): return
            ret, frame = self.cap.read()
            if not ret: return
            # OpenCV video captures natively read in BGR
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
        
        # Prevent UI slider jumping: if a newer seek was requested while we were reading,
        # abort emitting this obsolete frame and let the thread process the newer seek.
        with QMutexLocker(self.mutex):
            if getattr(self, 'seek_requested', False):
                return
                
        self.frame_ready.emit(qimg.copy(), frame_idx, self.total_frames)
        
    def run(self):
        # Initial setup inside the thread to avoid blocking the main thread
        if not self.is_sequence:
            self.cap = cv2.VideoCapture(self.media_path)
            if self.cap.isOpened():
                with QMutexLocker(self.mutex):
                    self.total_frames = max(1, int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)))
                    self.fps = self.cap.get(cv2.CAP_PROP_FPS)
                    if self.fps <= 0: self.fps = 24

        # Initial frame load
        with QMutexLocker(self.mutex):
            if not self.is_sequence and hasattr(self, 'cap'):
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
            initial_frame = self.current_frame
            
        self.read_and_emit(initial_frame)
            
        target_frame_time = 1.0 / self.fps
        
        while self.is_running:
            do_seek = False
            seek_target = 0
            
            with QMutexLocker(self.mutex):
                if self.seek_requested:
                    do_seek = True
                    seek_target = self.target_frame
                    self.seek_requested = False
                    self.current_frame = seek_target
                    
            if do_seek:
                if not self.is_sequence and hasattr(self, 'cap'):
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, seek_target)
                self.read_and_emit(seek_target)
                continue
                
            if not self.is_paused and self.total_frames > 1:
                loop_start = time.time()
                
                with QMutexLocker(self.mutex):
                    start_bound = getattr(self, 'in_frame', 0)
                    if start_bound is None: start_bound = 0
                    end_bound = getattr(self, 'out_frame', self.total_frames - 1)
                    if end_bound is None: end_bound = self.total_frames - 1
                    
                    self.current_frame += 1
                    if self.current_frame > end_bound or self.current_frame < start_bound:
                        self.current_frame = start_bound
                        
                    if not self.is_sequence and hasattr(self, 'cap'):
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
                    
                    frame_to_read = self.current_frame
                    
                self.read_and_emit(frame_to_read)
                    
                elapsed = time.time() - loop_start
                sleep_time = max(0.0, target_frame_time - elapsed)
                self.msleep(int(sleep_time * 1000))
            else:
                self.msleep(10)
                
        with QMutexLocker(self.mutex):
            if not self.is_sequence and hasattr(self, 'cap'):
                self.cap.release()

class InteractiveVideoCanvas(QWidget):
    interaction_requested = Signal(int, list) # frame_idx, [(nx, ny, is_positive), ...]
    keyframes_changed = Signal(list)
    zoom_changed = Signal()
    pixel_probed = Signal(int, int, int, int, int) # x, y, r, g, b
    
    def __init__(self, placeholder_text="NO MEDIA LOADED", parent=None):
        super().__init__(parent)
        self.placeholder_text = placeholder_text
        self.setMouseTracking(True)
        
        self.zoom_factor = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        
        self.is_interactive = False
        self.current_frame = 0
        self.mask_keyframes = {}
        self.mask_overlays = {}
        self.current_mask_overlay = None
        self.tracking_points = {}
        
        self.last_mouse_pos = None
        self.bg_mode = "black"
        
        # A/B Wipe Properties
        self.wipe_enabled = False
        self.last_b_image = None
        self.wipe_pos = 0.5
        self.is_dragging_wipe = False

    def setText(self, text):
        self.placeholder_text = text
        self.update()

    def text(self):
        return self.placeholder_text

    def clear(self):
        self.last_raw_image = None
        self.placeholder_text = ""
        self.update()

    def set_current_frame(self, frame_idx):
        if self.current_frame != frame_idx:
            # Restore the cached mask for this frame, if it exists
            self.current_mask_overlay = self.mask_overlays.get(frame_idx, None)
            
            # Request mask generation if there are points but no cached mask
            if self.current_mask_overlay is None and frame_idx in self.mask_keyframes:
                self.interaction_requested.emit(frame_idx, self.mask_keyframes[frame_idx])
                
        self.current_frame = frame_idx
        self.update()

    def enable_interaction(self, enable):
        self.is_interactive = enable
        if not enable:
            self.current_mask_overlay = None
        self.update()
        
    def set_mask_overlay(self, frame_idx, qimage):
        self.mask_overlays[frame_idx] = qimage
        if self.current_frame == frame_idx:
            self.current_mask_overlay = qimage
            self.update()

    def clear_current_frame_points(self):
        if self.current_frame in self.mask_keyframes:
            del self.mask_keyframes[self.current_frame]
            if self.current_frame in self.mask_overlays:
                del self.mask_overlays[self.current_frame]
            self.current_mask_overlay = None
            self.keyframes_changed.emit(list(self.mask_keyframes.keys()))
            self.update()

    def wheelEvent(self, event):
        # Zoom in/out with mouse scroll
        if event.angleDelta().y() > 0:
            self.zoom_factor *= 1.1
        else:
            self.zoom_factor /= 1.1
            
        self.zoom_factor = max(0.1, min(self.zoom_factor, 10.0))
        
        # Trigger an update by emitting a signal or forcing the viewport to redraw the frame
        # Since update_frame is in Viewport, we can just call self.parent().update_frame ?
        # A simpler way is to signal the viewport to redraw. We can add a simple signal.
        if hasattr(self, 'zoom_changed'):
            self.zoom_changed.emit()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton or (event.button() == Qt.RightButton and not self.is_interactive):
            self.last_mouse_pos = event.position()
            return

        if not self.is_interactive or not hasattr(self, 'last_raw_image') or not self.last_raw_image:
            super().mousePressEvent(event)
            return
            
        img_w, img_h = self.last_raw_image.width(), self.last_raw_image.height()
        lbl_w, lbl_h = self.width(), self.height()
        
        scale = min(lbl_w / img_w, lbl_h / img_h) * self.zoom_factor
        drawn_w = img_w * scale
        drawn_h = img_h * scale
        
        x_offset = (lbl_w - drawn_w) / 2 + self.pan_x
        y_offset = (lbl_h - drawn_h) / 2 + self.pan_y
        
        click_x = event.position().x() - x_offset
        click_y = event.position().y() - y_offset
        
        # Check if click is inside the image bounds
        if 0 <= click_x <= drawn_w and 0 <= click_y <= drawn_h:
            norm_x = click_x / drawn_w
            norm_y = click_y / drawn_h
            
            is_pos = (event.button() == Qt.LeftButton)
            
            if self.current_frame not in self.mask_keyframes:
                self.mask_keyframes[self.current_frame] = []
                
            self.mask_keyframes[self.current_frame].append((norm_x, norm_y, is_pos))
            self.keyframes_changed.emit(list(self.mask_keyframes.keys()))
            
            # Emit interaction request for live preview
            self.interaction_requested.emit(self.current_frame, self.mask_keyframes[self.current_frame])
            self.update()
            
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.last_mouse_pos is not None:
            delta = event.position() - self.last_mouse_pos
            self.pan_x += delta.x()
            self.pan_y += delta.y()
            self.last_mouse_pos = event.position()
            self.update()
            
        # Pixel Probe
        if hasattr(self, 'last_raw_image') and self.last_raw_image and not self.last_raw_image.isNull():
            img_w, img_h = self.last_raw_image.width(), self.last_raw_image.height()
            lbl_w, lbl_h = self.width(), self.height()
            
            scale = min(lbl_w / img_w, lbl_h / img_h) * self.zoom_factor
            drawn_w = img_w * scale
            drawn_h = img_h * scale
            
            x_offset = (lbl_w - drawn_w) / 2 + self.pan_x
            y_offset = (lbl_h - drawn_h) / 2 + self.pan_y
            
            click_x = event.position().x() - x_offset
            click_y = event.position().y() - y_offset
            
            if 0 <= click_x <= drawn_w and 0 <= click_y <= drawn_h:
                px = int((click_x / drawn_w) * img_w)
                py = int((click_y / drawn_h) * img_h)
                
                # Safely probe pixel
                if 0 <= px < img_w and 0 <= py < img_h:
                    color = QColor(self.last_raw_image.pixel(px, py))
                    self.pixel_probed.emit(px, py, color.red(), color.green(), color.blue())
            
            if self.wipe_enabled and self.is_dragging_wipe:
                self.wipe_pos = max(0.0, min(1.0, click_x / drawn_w))
                self.update()
                    
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() in (Qt.MiddleButton, Qt.RightButton):
            self.last_mouse_pos = event.position()
            
        elif event.button() == Qt.LeftButton:
            if self.wipe_enabled and hasattr(self, 'last_raw_image') and self.last_raw_image:
                img_w, img_h = self.last_raw_image.width(), self.last_raw_image.height()
                lbl_w, lbl_h = self.width(), self.height()
                scale = min(lbl_w / img_w, lbl_h / img_h) * self.zoom_factor
                drawn_w = img_w * scale
                x_offset = (lbl_w - drawn_w) / 2 + self.pan_x
                
                click_x = event.position().x() - x_offset
                wipe_px = drawn_w * self.wipe_pos
                
                if abs(click_x - wipe_px) < 15: # 15px hit radius
                    self.is_dragging_wipe = True
                    return

            if self.is_interactive and hasattr(self, 'last_raw_image') and self.last_raw_image:
                img_w, img_h = self.last_raw_image.width(), self.last_raw_image.height()
                lbl_w, lbl_h = self.width(), self.height()
                
                scale = min(lbl_w / img_w, lbl_h / img_h) * self.zoom_factor
                drawn_w = img_w * scale
                drawn_h = img_h * scale
                
                x_offset = (lbl_w - drawn_w) / 2 + self.pan_x
                y_offset = (lbl_h - drawn_h) / 2 + self.pan_y
                
                click_x = event.position().x() - x_offset
                click_y = event.position().y() - y_offset
                
                if 0 <= click_x <= drawn_w and 0 <= click_y <= drawn_h:
                    norm_x = click_x / drawn_w
                    norm_y = click_y / drawn_h
                    
                    is_positive = (event.modifiers() != Qt.ShiftModifier)
                    
                    if self.current_frame not in self.mask_keyframes:
                        self.mask_keyframes[self.current_frame] = []
                    
                    self.mask_keyframes[self.current_frame].append((norm_x, norm_y, is_positive))
                    self.keyframes_changed.emit(list(self.mask_keyframes.keys()))
                    self.interaction_requested.emit(self.current_frame, self.mask_keyframes[self.current_frame])
                    self.update()
            
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.is_dragging_wipe = False
        if event.button() in (Qt.MiddleButton, Qt.RightButton):
            self.last_mouse_pos = None

    def reset_zoom(self):
        self.zoom_factor = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.update()

    def mouseDoubleClickEvent(self, event):
        self.reset_zoom()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        if not hasattr(self, 'last_raw_image') or self.last_raw_image is None or self.last_raw_image.isNull():
            painter.setPen(QColor("#71717a"))
            painter.drawText(self.rect(), Qt.AlignCenter, self.placeholder_text)
            return
            
        img_w, img_h = self.last_raw_image.width(), self.last_raw_image.height()
        lbl_w, lbl_h = self.width(), self.height()
        
        scale = min(lbl_w / img_w, lbl_h / img_h) * self.zoom_factor
        drawn_w = img_w * scale
        drawn_h = img_h * scale
        
        x_offset = (lbl_w - drawn_w) / 2 + self.pan_x
        y_offset = (lbl_h - drawn_h) / 2 + self.pan_y
        
        drawn_rect = QRectF(x_offset, y_offset, drawn_w, drawn_h)
        
        # Draw Background Mode
        if self.bg_mode == "checkerboard":
            tile_size = 16
            tile_pm = QPixmap(tile_size * 2, tile_size * 2)
            tile_pm.fill(QColor("#a1a1aa"))
            tp = QPainter(tile_pm)
            tp.fillRect(0, 0, tile_size, tile_size, QColor("#e4e4e7"))
            tp.fillRect(tile_size, tile_size, tile_size, tile_size, QColor("#e4e4e7"))
            tp.end()
            painter.fillRect(drawn_rect, QBrush(tile_pm))
        elif self.bg_mode == "white":
            painter.fillRect(drawn_rect, Qt.white)
        else:
            painter.fillRect(drawn_rect, Qt.black)
            
        if self.wipe_enabled and self.last_b_image and not self.last_b_image.isNull():
            wipe_x = drawn_w * self.wipe_pos
            
            # Draw A (Left)
            rect_a_src = QRectF(0, 0, img_w * self.wipe_pos, img_h)
            rect_a_dst = QRectF(x_offset, y_offset, wipe_x, drawn_h)
            painter.drawImage(rect_a_dst, self.last_raw_image, rect_a_src)
            
            # Draw B (Right)
            rect_b_src = QRectF(img_w * self.wipe_pos, 0, img_w * (1 - self.wipe_pos), img_h)
            rect_b_dst = QRectF(x_offset + wipe_x, y_offset, drawn_w - wipe_x, drawn_h)
            painter.drawImage(rect_b_dst, self.last_b_image, rect_b_src)
            
            # Wipe Line
            painter.setPen(QPen(Qt.white, 3))
            painter.drawLine(x_offset + wipe_x, y_offset, x_offset + wipe_x, y_offset + drawn_h)
            # Draw small handle
            painter.setBrush(QBrush(Qt.white))
            painter.drawEllipse(QPointF(x_offset + wipe_x, y_offset + drawn_h / 2), 6, 6)
        else:
            painter.drawImage(drawn_rect, self.last_raw_image)
        
        if self.current_mask_overlay is not None and not self.current_mask_overlay.isNull():
            painter.setOpacity(0.55)
            painter.drawImage(drawn_rect, self.current_mask_overlay)
            painter.setOpacity(1.0)
        
        if self.is_interactive:
            points = self.mask_keyframes.get(self.current_frame, [])
            for nx, ny, is_pos in points:
                px = x_offset + (nx * drawn_w)
                py = y_offset + (ny * drawn_h)
                color = QColor(34, 197, 94) if is_pos else QColor(239, 68, 68)
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(Qt.white, 2))
                painter.drawEllipse(QPointF(px, py), 6, 6)
                
        # Draw camera tracking points
        if getattr(self, "show_tracking", False) and self.current_frame in self.tracking_points:
            t_points = self.tracking_points[self.current_frame]
            painter.setPen(Qt.NoPen)
            for tx, ty, has_3d in t_points:
                nx = tx / img_w
                ny = ty / img_h
                px = x_offset + (nx * drawn_w)
                py = y_offset + (ny * drawn_h)
                
                # Orange if matched to 3D point, gray if 2D only
                color = QColor(249, 115, 22) if has_3d else QColor(156, 163, 175, 100)
                painter.setBrush(QBrush(color))
                painter.drawRect(px - 1.5, py - 1.5, 3, 3)
            
        painter.end()


class Viewport(QWidget):
    interaction_requested = Signal(str, int, list) # node_id, frame_idx, points
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.player_thread = None
        self.current_node = None
        self.current_view_mode = "COMPOSITE"
        self.setup_ui()
        
    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.setStyleSheet("background-color: #0d0d0f;")
        
        # Add keyboard shortcuts for timeline scrubbing
        from PySide6.QtGui import QShortcut, QKeySequence
        from PySide6.QtCore import Qt
        
        self.shortcut_left = QShortcut(QKeySequence(Qt.Key_Left), self)
        self.shortcut_left.setContext(Qt.ApplicationShortcut)
        self.shortcut_left.activated.connect(self.step_backward)
        
        self.shortcut_right = QShortcut(QKeySequence(Qt.Key_Right), self)
        self.shortcut_right.setContext(Qt.ApplicationShortcut)
        self.shortcut_right.activated.connect(self.step_forward)
        
        self.shortcut_fit = QShortcut(QKeySequence(Qt.Key_F), self)
        self.shortcut_fit.setContext(Qt.ApplicationShortcut)
        # connect will be done below after self.img_display is initialized!
        
        self.shortcut_in = QShortcut(QKeySequence(Qt.Key_I), self)
        self.shortcut_in.setContext(Qt.ApplicationShortcut)
        self.shortcut_in.activated.connect(self.set_in_point)
        
        self.shortcut_out = QShortcut(QKeySequence(Qt.Key_O), self)
        self.shortcut_out.setContext(Qt.ApplicationShortcut)
        self.shortcut_out.activated.connect(self.set_out_point)
        
        # ——— Top Toolbar ———
        toolbar = QWidget()
        toolbar.setFixedHeight(48)
        toolbar.setStyleSheet("background-color: #121212; border-bottom: 1px solid #27272a;")
        t_layout = QHBoxLayout(toolbar)
        t_layout.setContentsMargins(20, 0, 20, 0)
        
        self.lbl_title = QLabel("🔴 Monitor A // NO MEDIA")
        self.lbl_title.setStyleSheet("font-family: 'Space Grotesk'; font-size: 13px; font-weight: bold; color: #fafafa; letter-spacing: 1px;")
        t_layout.addWidget(self.lbl_title)
        
        self.frame_lbl = QLabel("F 1 / 1")
        self.frame_lbl.setStyleSheet("font-family: 'JetBrains Mono'; font-size: 11px; color: #71717a; background-color: #1a1a1e; padding: 4px 8px; border-radius: 4px;")
        t_layout.addWidget(self.frame_lbl)
        
        t_layout.addStretch()
        
        # View modes
        btn_layout = QHBoxLayout()
        modes = ["SOURCE BGR", "ALPHA MATTE", "COMPOSITE", "3D VIEWER"]
        self.view_modes = {}
        for mode in modes:
            btn = QPushButton(mode)
            btn.setStyleSheet("""
                QPushButton {
                    background: #1a1b1e;
                    color: #9ca3af;
                    border: 1px solid #374151;
                    border-radius: 4px;
                    padding: 4px 10px;
                }
                QPushButton:hover {
                    background: #25262b;
                    color: white;
                }
            """)
            btn.clicked.connect(lambda checked=False, m=mode: self.set_view_mode(m))
            self.view_modes[mode] = btn
            btn_layout.addWidget(btn)
            
        # Wipe Tool Toggle
        btn_layout.addSpacing(10)
        self.btn_wipe = QPushButton("◩ A/B Wipe")
        self.btn_wipe.setCheckable(True)
        self.btn_wipe.setStyleSheet("""
            QPushButton { background: #1a1b1e; color: #a1a1aa; border: 1px solid #27272a; border-radius: 4px; padding: 4px 10px; font-weight: bold; }
            QPushButton:hover { background: #27272a; color: white; }
            QPushButton:checked { background: #3b82f6; color: white; border: 1px solid #60a5fa; }
        """)
        self.btn_wipe.clicked.connect(self.toggle_wipe)
        btn_layout.addWidget(self.btn_wipe)
        btn_layout.addSpacing(10)
            
        clear_range_btn = QPushButton("CLEAR IN/OUT")
        clear_range_btn.setStyleSheet("""
            QPushButton {
                background: #1a1b1e;
                color: #fca5a5;
                border: 1px solid #7f1d1d;
                border-radius: 4px;
                padding: 4px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #7f1d1d;
                color: white;
            }
        """)
        clear_range_btn.clicked.connect(self.clear_in_out)
        btn_layout.addWidget(clear_range_btn)
        
        # BG Modes
        btn_layout.addSpacing(20)
        bg_label = QLabel("BG:")
        bg_label.setStyleSheet("color: #71717a; font-size: 11px; font-weight: bold;")
        btn_layout.addWidget(bg_label)
        
        self.bg_btns = {}
        for bg in ["Black", "White", "Grid"]:
            b = QPushButton(bg)
            b.setStyleSheet("""
                QPushButton { background: #1a1b1e; color: #9ca3af; border: 1px solid #374151; border-radius: 4px; padding: 4px 8px; }
                QPushButton:hover { background: #25262b; color: white; }
            """)
            b.clicked.connect(lambda checked=False, mode=bg: self.set_bg_mode(mode))
            self.bg_btns[bg] = b
            btn_layout.addWidget(b)
            
        btn_layout.addStretch()
        
        self.lbl_zoom = QLabel("Zoom: 100%")
        self.lbl_zoom.setStyleSheet("color: #a1a1aa; font-family: 'Space Grotesk'; font-size: 11px; font-weight: bold;")
        btn_layout.addWidget(self.lbl_zoom)
        
        self.lbl_probe = QLabel("X: --  Y: --  |  R: -- G: -- B: --")
        self.lbl_probe.setStyleSheet("color: #a1a1aa; font-family: 'JetBrains Mono'; font-size: 11px;")
        btn_layout.addWidget(self.lbl_probe)
        
        t_layout.addLayout(btn_layout)
            
        main_layout.addWidget(toolbar)
        
        # ——— Video Display Area ———
        display_area = QWidget()
        display_area.setStyleSheet("background-color: #050505;")
        d_layout = QVBoxLayout(display_area)
        d_layout.setContentsMargins(0, 0, 0, 0)
        
        self.stacked_display = QStackedWidget()
        
        self.img_display = InteractiveVideoCanvas("SELECT A NODE TO VIEW MEDIA")
        self.img_display.interaction_requested.connect(self._on_canvas_interaction)
        self.img_display.zoom_changed.connect(self._on_zoom_changed)
        self.img_display.pixel_probed.connect(self._on_pixel_probed)
        self.stacked_display.addWidget(self.img_display)
        
        self.point_cloud_viewer = PointCloudViewerWidget()
        self.stacked_display.addWidget(self.point_cloud_viewer)
        
        d_layout.addWidget(self.stacked_display)
        
        self.shortcut_fit.activated.connect(self.img_display.reset_zoom)
        
        main_layout.addWidget(display_area, 1) # stretch = 1
        
        # ——— Bottom Timeline ———
        timeline = QWidget()
        timeline.setFixedHeight(60)
        timeline.setStyleSheet("background-color: #121212; border-top: 1px solid #27272a;")
        t_layout = QHBoxLayout(timeline)
        t_layout.setContentsMargins(10, 0, 10, 0)
        
        # Playback Controls
        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(40, 40)
        self.btn_play.setStyleSheet("""
            QPushButton { 
                background-color: #f59e0b; 
                color: #000000; 
                border-radius: 20px; 
                border: 2px solid #e2e8f0; 
                font-weight: bold; 
                font-size: 18px; 
                padding-left: 3px; 
                padding-bottom: 2px;
            }
            QPushButton:hover { background-color: #fbbf24; }
        """)
        self.btn_play.clicked.connect(self.toggle_playback)
        t_layout.addWidget(self.btn_play)
        
        self.lbl_start = QLabel("1")
        self.lbl_start.setStyleSheet("color: #f59e0b; font-family: 'Space Grotesk'; font-size: 14px; padding: 0px 10px; font-weight: bold;")
        t_layout.addWidget(self.lbl_start)

        self.timeline = TimelineWidget()
        self.timeline.frame_seeked.connect(self.seek_frame)
        self.img_display.keyframes_changed.connect(self.timeline.set_keyframes)
        self.img_display.keyframes_changed.connect(self._sync_mask_keyframes)
        t_layout.addWidget(self.timeline, 1) # stretch = 1
        
        self.lbl_end = QLabel("1")
        self.lbl_end.setStyleSheet("color: #71717a; font-family: 'Space Grotesk'; font-size: 11px; padding: 0px 10px;")
        t_layout.addWidget(self.lbl_end)
        
        self.btn_loop = QPushButton("🔁")
        self.btn_loop.setFixedSize(30, 30)
        self.btn_loop.setStyleSheet("""
            QPushButton { 
                background-color: transparent; 
                color: #3b82f6; 
                font-size: 18px; 
                border: none; 
            } 
            QPushButton:hover { color: #60a5fa; }
        """)
        t_layout.addWidget(self.btn_loop)
        
        self.btn_clear_pts = QPushButton("Clear Frame Points")
        self.btn_clear_pts.setStyleSheet("""
            QPushButton { background-color: #1a1a1e; color: #a1a1aa; border: 1px solid #27272a; border-radius: 4px; padding: 4px 10px; font-size: 11px; }
            QPushButton:hover { background-color: #27272a; color: #fafafa; }
        """)
        self.btn_clear_pts.clicked.connect(self.img_display.clear_current_frame_points)
        self.btn_clear_pts.hide() # Hidden by default, shown when SAM3 node is selected
        t_layout.addWidget(self.btn_clear_pts)
        
        main_layout.addWidget(timeline)
        
        self.set_view_mode("COMPOSITE")

    def set_view_mode(self, mode):
        for m, btn in self.view_modes.items():
            if m == mode:
                btn.setStyleSheet("QPushButton { background: #2b5c3a; color: #a1fca9; border: 1px solid #4ade80; border-radius: 4px; padding: 4px 10px; font-weight: bold; }")
            else:
                btn.setStyleSheet("QPushButton { background: #1a1b1e; color: #9ca3af; border: 1px solid #374151; border-radius: 4px; padding: 4px 10px; }")

        self.current_view_mode = mode
        if self.current_node:
            # Check if we should switch to 3D Viewer
            if mode == "3D VIEWER" and getattr(self.current_node, "plugin_type", "") == "sfm_tracker":
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                sparse_dir = os.path.join(project_root, "cache", getattr(self.current_node, "node_id", ""), "sparse")
                if os.path.exists(os.path.join(sparse_dir, "points3D.txt")):
                    self.stacked_display.setCurrentWidget(self.point_cloud_viewer)
                    self.point_cloud_viewer.load_colmap_model(sparse_dir)
                    if self.player_thread:
                        self.player_thread.stop()
                        self.player_thread = None
                    return
            
            # Otherwise, use 2D Viewer
            self.stacked_display.setCurrentWidget(self.img_display)
            media_path = self._get_node_media_path(self.current_node, view_mode=mode)
            if media_path and os.path.exists(media_path):
                was_paused = True
                curr_frame = 0
                if self.player_thread:
                    was_paused = self.player_thread.is_paused
                    curr_frame = self.player_thread.current_frame
                    self.player_thread.stop()
                    self.player_thread = None
                
                self.img_display.clear()
                self.img_display.setText("LOADING...")
                self.player_thread = VideoPlayerThread(media_path)
                self.player_thread.view_mode = mode
                
                # Maintain true timeline length from source
                true_path = self._get_node_media_path(self.current_node, view_mode="SOURCE BGR")
                if true_path and true_path != media_path:
                    temp_p = VideoPlayerThread(true_path)
                    self.player_thread.total_frames = max(self.player_thread.total_frames, temp_p.total_frames)
                    self.player_thread.start_frame_offset = getattr(temp_p, 'start_frame_offset', 1)
                    
                self.player_thread.current_frame = curr_frame
                self.player_thread.is_paused = was_paused
                self.player_thread.frame_ready.connect(self.update_frame)
                self.player_thread.start()
                if was_paused:
                    self.seek_frame(curr_frame)

    def _get_node_media_path(self, node, visited=None, view_mode="COMPOSITE"):
        """Finds media associated with a node, generated cache, or upstream inputs."""
        if visited is None:
            visited = set()

        if node in visited:
            return None
        visited.add(node)

        params = getattr(node, "params", {})
        plate_file = params.get("plate_file")
        if getattr(node, "plugin_type", "") == "media_plate" and plate_file and os.path.exists(plate_file):
            if params.get("is_sequence", False) and os.path.isfile(plate_file):
                return os.path.dirname(plate_file)
            return plate_file

        from core_ui.settings_manager import SettingsManager
        node_cache = SettingsManager().get_cache_dir(getattr(node, "node_id", ""))

        if os.path.exists(node_cache):
            if view_mode == "ALPHA MATTE":
                preferred = ("pha", "Output/Matte", "Matte", "AlphaHint")
            elif view_mode == "COMPOSITE" or view_mode == "3D VIEWER":
                preferred = ("fgr", "Output/Comp", "Output/FG", "Comp", "FG")
            else:
                preferred = ()
                
            for dirname in preferred:
                candidate = os.path.join(node_cache, dirname)
                if os.path.isdir(candidate) and os.listdir(candidate):
                    return candidate
            
            if view_mode != "SOURCE BGR":
                files = glob.glob(os.path.join(node_cache, "*"))
                files = [f for f in files if os.path.isfile(f)]
                if files:
                    return node_cache

        for port in getattr(node, "inputs", []):
            if port.connections:
                conn = port.connections[0]
                upstream_port = conn.port1 if conn.port1 != port else conn.port2
                if upstream_port:
                    upstream_path = self._get_node_media_path(upstream_port.node, visited, view_mode)
                    if upstream_path:
                        return upstream_path
        return None

    def _sync_mask_keyframes(self, _=None):
        if self.current_node and self.img_display.is_interactive:
            if not hasattr(self.current_node, "params"):
                self.current_node.params = {}
            self.current_node.params["mask_keyframes"] = self.img_display.mask_keyframes.copy()

    def _on_canvas_interaction(self, frame_idx, points):
        if self.current_node:
            from core_ui.execution_engine import ExecutionEngine
            if not getattr(self, "engine_ref", None):
                main_window = self.window()
                self.engine_ref = getattr(main_window, "execution_engine", None)
            
            if self.engine_ref:
                self.engine_ref.handle_interaction(self.current_node.node_id, frame_idx, points)

    def _on_zoom_changed(self):
        if hasattr(self.img_display, 'last_raw_image') and self.img_display.last_raw_image:
            cur_frame = self.player_thread.current_frame if self.player_thread else 0
            tot_frames = self.player_thread.total_frames if self.player_thread else 1
            self.update_frame(self.img_display.last_raw_image, cur_frame, tot_frames)
            
    @Slot(str, int, QImage)
    def receive_interactive_mask(self, node_id, frame_idx, qimage):
        if self.current_node and self.current_node.node_id == node_id:
            self.img_display.set_mask_overlay(frame_idx, qimage)

    @Slot(str, int, float)
    def handle_media_loaded(self, path, total_frames, fps):
        self.img_display.clear()
        self.img_display.setText("LOADING...")
        self.player_thread = VideoPlayerThread(path)
        self.player_thread.frame_ready.connect(self.update_frame)
        self.player_thread.start()
        self.timeline.set_frames(0, total_frames, getattr(self.player_thread, 'start_frame_offset', 1))

    def connect_to_node(self, node):
        """Connect viewport to a media provider node"""
        # Save the current mask keyframes and overlays to the node before switching
        if self.current_node and self.img_display.is_interactive:
            if not hasattr(self.current_node, "params"):
                self.current_node.params = {}
            self.current_node.params["mask_keyframes"] = self.img_display.mask_keyframes.copy()
            self.current_node._mask_overlays_cache = self.img_display.mask_overlays.copy()
        # Get the new media path before stopping the existing player
        media_path = self._get_node_media_path(node, view_mode=self.current_view_mode)

        # If it's the same node and the same media path, don't interrupt playback
        if getattr(self, "current_node", None) == node and self.player_thread and self.player_thread.media_path == media_path:
            # We still need to sync keyframes to the UI since they might have changed
            if self.img_display.is_interactive and hasattr(node, "params"):
                raw_keyframes = node.params.get("mask_keyframes", {})
                self.img_display.mask_keyframes = {int(k): v for k, v in raw_keyframes.items()}
            self.img_display.keyframes_changed.emit(list(self.img_display.mask_keyframes.keys()))
            return

        self.current_node = node
        
        # Stop existing player
        if self.player_thread:
            self.last_media_path = self.player_thread.media_path
            self.last_current_frame = self.player_thread.current_frame
            self.last_is_paused = self.player_thread.is_paused
            self.player_thread.stop()
            self.player_thread = None
        if not node:
            self.lbl_title.setText("🔴 Monitor A // NO NODE SELECTED")
            self.btn_clear_pts.hide()
            self.img_display.enable_interaction(False)
            self.img_display.clear()
            self.img_display.setText("SELECT A NODE TO VIEW MEDIA")
            self.frame_lbl.setText("F 1 / 1")
            self.lbl_start.setText("1")
            self.lbl_end.setText("1")
            self.timeline.set_frames(0, 1)
            self.timeline.set_keyframes([])
            return
            
        self.lbl_title.setText(f"🔴 Monitor A // {node.name}")
        self.img_display.enable_interaction(node.plugin_type in ["sam3_rotoscope", "matte_anyone"])
        
        # Restore the mask keyframes from the new node
        if self.img_display.is_interactive and hasattr(node, "params"):
            raw_keyframes = node.params.get("mask_keyframes", {})
            # Ensure keyframe keys are integers to prevent JSON serialization string-key timeline crashes
            self.img_display.mask_keyframes = {int(k): v for k, v in raw_keyframes.items()}
        else:
            self.img_display.mask_keyframes.clear()
            
        self.img_display.mask_overlays.clear()
        if hasattr(node, "_mask_overlays_cache"):
            self.img_display.mask_overlays = node._mask_overlays_cache.copy()
            
        self.img_display.current_mask_overlay = self.img_display.mask_overlays.get(self.img_display.current_frame, None)
        self.img_display.keyframes_changed.emit(list(self.img_display.mask_keyframes.keys()))
        
        # Load Camera Tracking Points
        self.img_display.tracking_points.clear()
        self.img_display.show_tracking = False
        if node.plugin_type == "sfm_tracker":
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            sparse_dir = os.path.join(project_root, "cache", getattr(node, "node_id", ""), "sparse", "0")
            images_txt = os.path.join(sparse_dir, "images.txt")
            if os.path.exists(images_txt):
                self.img_display.show_tracking = True
                try:
                    with open(images_txt, "r") as f:
                        lines = f.readlines()
                        for i in range(0, len(lines), 2):
                            if lines[i].startswith("#") or not lines[i].strip():
                                continue
                            parts = lines[i].strip().split()
                            if len(parts) >= 10:
                                name = parts[9]
                                import re
                                m = re.match(r"^.*?(\d+)\.[^.]+$", name)
                                if m:
                                    frame_num = int(m.group(1))
                                    # COLMAP sequence start varies, we map by finding offset
                                    # We will just parse the 2nd line
                                    pts_line = lines[i+1].strip().split()
                                    pts = []
                                    for p_idx in range(0, len(pts_line), 3):
                                        x = float(pts_line[p_idx])
                                        y = float(pts_line[p_idx+1])
                                        has_3d = int(pts_line[p_idx+2]) != -1
                                        if has_3d: # We probably only want to draw matched points
                                            pts.append((x, y, True))
                                    # We don't know the frame_offset yet. We'll store by frame_num for now.
                                    self.img_display.tracking_points[frame_num] = pts
                except Exception as e:
                    print(f"Failed to read tracking points: {e}")
                    
        if node.plugin_type in ["sam3_rotoscope", "matte_anyone"]:
            self.btn_clear_pts.show()
        else:
            self.btn_clear_pts.hide()
            
        media_path = self._get_node_media_path(node, view_mode=self.current_view_mode)

        if media_path and os.path.exists(media_path):
            self.img_display.clear()
            self.img_display.setText("LOADING...")
            self.player_thread = VideoPlayerThread(media_path)
            self.player_thread.view_mode = self.current_view_mode
            
            # Maintain true timeline length from source
            true_path = self._get_node_media_path(node, view_mode="SOURCE BGR")
            if true_path and true_path != media_path:
                temp_p = VideoPlayerThread(true_path)
                self.player_thread.total_frames = max(self.player_thread.total_frames, temp_p.total_frames)
                self.player_thread.start_frame_offset = getattr(temp_p, 'start_frame_offset', 1)
            
            # ALWAYS restore frame to keep playhead consistent across nodes
            self.player_thread.current_frame = getattr(self, "last_current_frame", 0)
            self.player_thread.is_paused = getattr(self, "last_is_paused", True)
            
            # Re-map tracking points from frame_num (absolute) to frame_idx (relative)
            if self.img_display.show_tracking and getattr(self.player_thread, 'start_frame_offset', None):
                offset = self.player_thread.start_frame_offset
                mapped_points = {}
                for absolute_frame, pts in self.img_display.tracking_points.items():
                    relative_idx = absolute_frame - offset
                    if relative_idx >= 0:
                        mapped_points[relative_idx] = pts
                self.img_display.tracking_points = mapped_points
            
            self.player_thread.frame_ready.connect(self.update_frame)
            self.player_thread.start()
            
            self.timeline.set_media_path(media_path, self.player_thread.is_sequence)
        else:
            self.img_display.clear()
            self.img_display.setText("NO MEDIA OR CACHE GENERATED")
            self.frame_lbl.setText("F 1 / 1")
            self.lbl_start.setText("1")
            self.lbl_end.setText("1")
            self.timeline.set_frames(0, 1)

    @Slot(QImage, int, int)
    def update_frame(self, image, current_frame, total_frames):
        # Store the current unscaled QImage so we can redraw on zoom
        self.img_display.last_raw_image = image
        
        # Clear the loading text now that we have a frame
        if self.img_display.text():
            self.img_display.setText("")
            
        if self.img_display.wipe_enabled:
            # Sync fetch B frame
            b_img = self._fetch_source_frame_sync(current_frame)
            self.img_display.last_b_image = b_img
            
        start_offset = getattr(self.player_thread, 'start_frame_offset', 1)
        display_frame = current_frame + start_offset
        end_display = start_offset + total_frames - 1 if total_frames > 0 else start_offset
            
        self.img_display.set_current_frame(current_frame)
        self.point_cloud_viewer.set_current_frame(display_frame)
        self.frame_lbl.setText(f"F {display_frame} / {end_display}")
        
        self.lbl_start.setText(str(display_frame))
        self.lbl_end.setText(str(end_display))
        
        # Block signals to prevent seek loop
        self.timeline.blockSignals(True)
        self.timeline.set_frames(current_frame, total_frames, start_offset)
        self.timeline.blockSignals(False)

    def toggle_playback(self):
        if self.player_thread:
            if self.player_thread.is_paused:
                self.player_thread.is_paused = False
                self.btn_play.setText("⏸")
            else:
                self.player_thread.is_paused = True
                self.btn_play.setText("▶")

    def seek_frame(self, position):
        if self.player_thread:
            was_playing = not self.player_thread.is_paused
            self.player_thread.is_paused = True # pause during seek
            self.player_thread.seek(position)
            if was_playing:
                self.player_thread.is_paused = False

    def step_backward(self):
        if self.player_thread and self.player_thread.total_frames > 0:
            new_frame = max(0, self.player_thread.current_frame - 1)
            self.seek_frame(new_frame)
            
    def step_forward(self):
        if self.player_thread:
            self.seek_frame(min(self.player_thread.current_frame + 1, self.player_thread.total_frames - 1))

    def set_in_point(self):
        if self.player_thread:
            self.timeline.set_in_frame(self.player_thread.current_frame)
            self.player_thread.in_frame = self.player_thread.current_frame
            
    def set_out_point(self):
        if self.player_thread:
            self.timeline.set_out_frame(self.player_thread.current_frame)
            self.player_thread.out_frame = self.player_thread.current_frame

    def clear_in_out(self):
        if self.player_thread:
            self.timeline.set_in_frame(None)
            self.timeline.set_out_frame(None)
            self.player_thread.in_frame = None
            self.player_thread.out_frame = None

    def toggle_wipe(self, checked):
        self.img_display.wipe_enabled = checked
        if checked and self.player_thread:
            self.img_display.last_b_image = self._fetch_source_frame_sync(self.player_thread.current_frame)
        self.img_display.update()

    def _fetch_source_frame_sync(self, frame_idx):
        if not self.current_node: return None
        true_path = self._get_node_media_path(self.current_node, view_mode="SOURCE BGR")
        if not true_path: return None
        
        # Super quick read using OpenCV for the preview B frame
        try:
            if os.path.isdir(true_path):
                files = sorted([f for f in os.listdir(true_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.exr', '.dpx', '.hdr'))])
                if 0 <= frame_idx < len(files):
                    frame = cv2.imread(os.path.join(true_path, files[frame_idx]))
                    if frame is not None:
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        h, w, c = frame.shape
                        return QImage(frame.data, w, h, w * c, QImage.Format_RGB888).copy()
            else:
                cap = cv2.VideoCapture(true_path)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                cap.release()
                if ret:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, c = frame.shape
                    return QImage(frame.data, w, h, w * c, QImage.Format_RGB888).copy()
        except Exception:
            pass
        return None

    def _on_zoom_changed(self):
        z = int(self.img_display.zoom_factor * 100)
        self.lbl_zoom.setText(f"Zoom: {z}%")
        
    def _on_pixel_probed(self, px, py, r, g, b):
        self.lbl_probe.setText(f"X: {px:<4} Y: {py:<4} | R: {r:<3} G: {g:<3} B: {b:<3}")

    def set_bg_mode(self, mode):
        for m, btn in self.bg_btns.items():
            if m == mode:
                btn.setStyleSheet("QPushButton { background: #3f3f46; color: white; border: 1px solid #71717a; border-radius: 4px; padding: 4px 8px; font-weight: bold; }")
            else:
                btn.setStyleSheet("QPushButton { background: #1a1b1e; color: #9ca3af; border: 1px solid #374151; border-radius: 4px; padding: 4px 8px; }")
        
        if mode == "Grid":
            self.img_display.bg_mode = "checkerboard"
        elif mode == "White":
            self.img_display.bg_mode = "white"
        else:
            self.img_display.bg_mode = "black"
            
        self.img_display.update()

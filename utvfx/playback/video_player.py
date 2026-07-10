import os
import glob
import time
import numpy as np
import cv2

from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker
from PySide6.QtGui import QImage

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
                
                self.total_frames = max(0, len(self.sequence_files))
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
            if not self.sequence_files:
                # Create a placeholder frame indicating no media
                frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                cv2.putText(frame, "NO MEDIA RENDERED", (400, 360), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (100, 100, 100), 3)
                qimg = QImage(frame.data, 1280, 720, 1280*3, QImage.Format_RGB888)
                self.frame_ready.emit(qimg, 0, 0)
                return
                
            # Safe clamp to the actual sequence files list size to completely prevent IndexError
            frame_idx = min(max(frame_idx, 0), len(self.sequence_files) - 1)
            path = self.sequence_files[frame_idx]
            frame = None
            
            from utvfx.core.image_utils import load_frame
            frame = load_frame(path)
            
            if frame is not None:
                if getattr(self, 'view_mode', 'COMP') == "MATTE":
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
                        frame = frame[:, :, :3]
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

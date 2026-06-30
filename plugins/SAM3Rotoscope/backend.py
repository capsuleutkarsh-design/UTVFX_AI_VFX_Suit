import time
import os
import sys
import traceback
import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

def run_fast_preview(params, frame_idx, points, temp_frame_path=None):
    """
    Uses the AI Bridge Server to get a real-time mask overlay.
    """
    if not points or not temp_frame_path:
        from PySide6.QtGui import QImage
        from PySide6.QtCore import Qt
        img = QImage(1024, 1024, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        return img
        
    from core_ui.ai_bridge_client import AIBridgeClient
    client = AIBridgeClient.get_instance()
    
    # Extract coordinates and labels
    pts = []
    lbls = []
    import cv2
    img_bgr = cv2.imread(temp_frame_path)
    if img_bgr is None:
        return None
        
    h, w, _ = img_bgr.shape
    
    for nx, ny, is_pos in points:
        pts.append([nx * w, ny * h])
        lbls.append(1 if is_pos else 0)
        
    # We use orange for SAM3
    return client.query_mask(temp_frame_path, pts, lbls, fill_color_hex="#f97316")

def track_points_pyrlk(img1, img2, pts_nxny):
    """
    Tracks normalized keyframe points (nx, ny, is_pos) using Lucas-Kanade optical flow.
    """
    if not pts_nxny or len(pts_nxny) == 0:
        return []
    h, w = img1.shape[:2]
    
    p0 = np.array([[[p[0] * w, p[1] * h]] for p in pts_nxny], dtype=np.float32)
    lk_params = dict(winSize=(31, 31), maxLevel=4,
                     criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
    
    p1, st, err = cv2.calcOpticalFlowPyrLK(img1, img2, p0, None, **lk_params)
    
    tracked_nxny = []
    for i in range(len(pts_nxny)):
        if st[i][0] == 1:
            nx = float(p1[i][0][0]) / w
            ny = float(p1[i][0][1]) / h
            tracked_nxny.append((nx, ny, pts_nxny[i][2]))
        else:
            tracked_nxny.append(pts_nxny[i])
            
    return tracked_nxny

class SAM3Worker(QThread):
    progress_update = Signal(int, int)
    log_message = Signal(str)
    error_occurred = Signal(str)
    finished_processing = Signal()

    def __init__(self, media_path, keyframes, output_dir, params):
        super().__init__()
        self.media_path = media_path
        self.keyframes = keyframes
        self.output_dir = output_dir
        self.params = params
        self.is_cancelled = False
        
        # Path to model
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.model_path_pt = os.path.join(plugin_dir, "sam3.pt")
        self.model_path_st = os.path.join(plugin_dir, "sam3.safetensors")

    def cancel(self):
        self.is_cancelled = True

    def run(self):
        try:
            self.log_message.emit("Initializing Segment Anything Model 3 Rotoscoper...")
            
            # 1. Dependency Check
            try:
                import torch
                import torchvision
            except ImportError:
                self.error_occurred.emit("PyTorch is not installed. Please install PyTorch with CUDA support to use local AI models.")
                return
                
            self.log_message.emit(f"PyTorch {torch.__version__} loaded successfully.")
            
            # 2. VRAM / Device Check
            device = "cuda" if torch.cuda.is_available() else "cpu"
            if device == "cuda":
                vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
                self.log_message.emit(f"CUDA detected: {torch.cuda.get_device_name(0)} ({vram_gb:.1f}GB VRAM)")
                if vram_gb < 6.0:
                    self.log_message.emit("WARNING: Low VRAM detected. Model may run slowly on large resolutions.")
            else:
                self.log_message.emit("WARNING: CUDA not available. Running on CPU. This will be slow.")

            # 3. Directory Preparation & Video Decoding
            pha_dir = os.path.join(self.output_dir, "pha")
            os.makedirs(pha_dir, exist_ok=True)
            
            frames_dir = os.path.join(self.output_dir, "input_frames")
            os.makedirs(frames_dir, exist_ok=True)
            
            # Resolve all frames
            is_sequence = False
            frame_files = []
            
            if os.path.isdir(self.media_path):
                is_sequence = True
                exts = (".png", ".jpg", ".jpeg", ".exr", ".dpx", ".tif", ".tiff", ".hdr")
                for name in sorted(os.listdir(self.media_path)):
                    if name.lower().endswith(exts):
                        frame_files.append(os.path.join(self.media_path, name))
            else:
                # Video file: decode to input_frames
                self.log_message.emit("Decoding video file to temporary image sequence...")
                cap = cv2.VideoCapture(self.media_path)
                if not cap.isOpened():
                    self.error_occurred.emit("Failed to open video file.")
                    return
                
                total_vid_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                if total_vid_frames <= 0: total_vid_frames = 1000 # fallback
                
                f_idx = 0
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    # Use JPG for vastly faster temporary extraction (~10x faster than PNG)
                    frame_path = os.path.join(frames_dir, f"frame_{f_idx:06d}.jpg")
                    cv2.imwrite(frame_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 98])
                    frame_files.append(frame_path)
                    f_idx += 1
                    
                    if f_idx % 30 == 0:
                        self.log_message.emit(f"Extracting temporary frames: {f_idx} / {total_vid_frames} ...")
                        
                    if self.is_cancelled:
                        cap.release()
                        return
                cap.release()
                
            total_frames = len(frame_files)
            if total_frames == 0:
                self.error_occurred.emit("No readable frames found in the video plate.")
                return
                
            start_frame = max(0, int(self.params.get("start_frame", 1)) - 1)
            end_frame = int(self.params.get("end_frame", 0))
            if end_frame <= 0 or end_frame >= total_frames:
                end_frame = total_frames - 1
                
            # Filter frame_files
            if start_frame > 0 or end_frame < total_frames - 1:
                frame_files = frame_files[start_frame:end_frame + 1]
                total_frames = len(frame_files)
            
            if total_frames == 0:
                self.error_occurred.emit("No frames in selected range.")
                return
            
            self.log_message.emit(f"Total frames to process: {total_frames}")
            
            # 4. Point-Based Tracking and AI SAM Inference
            if not self.keyframes:
                self.log_message.emit("No keyframes found. Please place tracking points in the viewport first.")
                self.finished_processing.emit()
                return
                
            from core_ui.ai_bridge_client import AIBridgeClient
            client = AIBridgeClient.get_instance()
            
            keyframe_indices = sorted([int(k) for k in self.keyframes.keys()])
            sam_masks_dir = os.path.join(self.output_dir, "sam_masks")
            os.makedirs(sam_masks_dir, exist_ok=True)
            
            # Helper to generate SAM mask from tracked points
            def generate_sam_mask(frame_idx, tracked_points):
                if self.is_cancelled or not tracked_points: return
                frame_path = frame_files[frame_idx]
                out_mask_path = os.path.join(sam_masks_dir, f"mask_{frame_idx:06d}.png")
                
                img = cv2.imread(frame_path)
                if img is None: return
                h, w, _ = img.shape
                
                pts, lbls = [], []
                for nx, ny, is_pos in tracked_points:
                    pts.append([int(nx * w), int(ny * h)])
                    lbls.append(1 if is_pos else 0)
                
                client.query_mask(frame_path, pts, lbls, out_mask_path=out_mask_path)
                
                if os.path.exists(out_mask_path):
                    mask = cv2.imread(out_mask_path, cv2.IMREAD_GRAYSCALE)
                    if mask is not None:
                        # Ensure absolute binary thresholding for crisp edges
                        _, binary_mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
                        cv2.imwrite(os.path.join(pha_dir, f"{frame_idx + start_frame:04d}.png"), binary_mask)
            
            # First, generate masks for the explicit keyframes
            for f_idx in keyframe_indices:
                points = self.keyframes[str(f_idx)] if str(f_idx) in self.keyframes else self.keyframes[f_idx]
                self.log_message.emit(f"Generating SAM keyframe mask for frame {f_idx}...")
                generate_sam_mask(f_idx, points)
            
            self.log_message.emit("Running point-based Lucas-Kanade tracking and AI inference...")
            
            # Propagate backward from first keyframe
            first_kf = keyframe_indices[0]
            if first_kf > 0:
                self.log_message.emit(f"Tracking backward from frame {first_kf} to 0...")
                curr_pts = self.keyframes[str(first_kf)] if str(first_kf) in self.keyframes else self.keyframes[first_kf]
                for t in range(first_kf, 0, -1):
                    if self.is_cancelled: return
                    img_t = cv2.imread(frame_files[t], cv2.IMREAD_GRAYSCALE)
                    img_t1 = cv2.imread(frame_files[t-1], cv2.IMREAD_GRAYSCALE)
                    
                    curr_pts = track_points_pyrlk(img_t, img_t1, curr_pts)
                    generate_sam_mask(t - 1, curr_pts)
                    self.progress_update.emit(first_kf - t + 1, total_frames)

            # Bidirectional tracking between keyframes
            for k_idx in range(len(keyframe_indices) - 1):
                k_start = keyframe_indices[k_idx]
                k_end = keyframe_indices[k_idx + 1]
                interval_len = k_end - k_start
                
                self.log_message.emit(f"Tracking interval: frame {k_start} to {k_end}...")
                
                # Forward track
                forward_pts = [None] * (interval_len + 1)
                forward_pts[0] = self.keyframes[str(k_start)] if str(k_start) in self.keyframes else self.keyframes[k_start]
                for t in range(k_start, k_end):
                    if self.is_cancelled: return
                    img_t = cv2.imread(frame_files[t], cv2.IMREAD_GRAYSCALE)
                    img_t1 = cv2.imread(frame_files[t+1], cv2.IMREAD_GRAYSCALE)
                    forward_pts[t - k_start + 1] = track_points_pyrlk(img_t, img_t1, forward_pts[t - k_start])
                    
                # Backward track
                backward_pts = [None] * (interval_len + 1)
                backward_pts[-1] = self.keyframes[str(k_end)] if str(k_end) in self.keyframes else self.keyframes[k_end]
                for t in range(k_end, k_start, -1):
                    if self.is_cancelled: return
                    img_t = cv2.imread(frame_files[t], cv2.IMREAD_GRAYSCALE)
                    img_t1 = cv2.imread(frame_files[t-1], cv2.IMREAD_GRAYSCALE)
                    backward_pts[t - k_start - 1] = track_points_pyrlk(img_t, img_t1, backward_pts[t - k_start])
                    
                # Blend points and generate masks
                for f in range(k_start + 1, k_end):
                    if self.is_cancelled: return
                    idx = f - k_start
                    weight = float(idx) / interval_len
                    
                    # Blend the coordinates of the tracked points
                    blended_pts = []
                    f_p = forward_pts[idx]
                    b_p = backward_pts[idx]
                    for i in range(len(f_p)):
                        if i < len(b_p):
                            bx = (1.0 - weight) * f_p[i][0] + weight * b_p[i][0]
                            by = (1.0 - weight) * f_p[i][1] + weight * b_p[i][1]
                            blended_pts.append((bx, by, f_p[i][2]))
                        else:
                            blended_pts.append(f_p[i])
                            
                    generate_sam_mask(f, blended_pts)
                    self.progress_update.emit(f, total_frames)

            # Propagate forward from last keyframe
            last_kf = keyframe_indices[-1]
            if last_kf < total_frames - 1:
                self.log_message.emit(f"Tracking forward from frame {last_kf} to {total_frames - 1}...")
                curr_pts = self.keyframes[str(last_kf)] if str(last_kf) in self.keyframes else self.keyframes[last_kf]
                for t in range(last_kf, total_frames - 1):
                    if self.is_cancelled: return
                    img_t = cv2.imread(frame_files[t], cv2.IMREAD_GRAYSCALE)
                    img_t1 = cv2.imread(frame_files[t+1], cv2.IMREAD_GRAYSCALE)
                    
                    curr_pts = track_points_pyrlk(img_t, img_t1, curr_pts)
                    generate_sam_mask(t + 1, curr_pts)
                    self.progress_update.emit(t + 1, total_frames)

            self.progress_update.emit(total_frames, total_frames)
            self.log_message.emit("SAM 3 Rotoscoping complete. Crisp alpha matte sequence generated.")
            self.finished_processing.emit()

            
        except Exception as e:
            self.error_occurred.emit(f"SAM 3 Error: {str(e)}\n{traceback.format_exc()}")

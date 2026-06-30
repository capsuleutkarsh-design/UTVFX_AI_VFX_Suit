import os
import cv2
import numpy as np
import json
from PySide6.QtCore import QThread, Signal

class RotoToShapeWorker(QThread):
    progress_update = Signal(int, int)
    log_message = Signal(str)
    error_occurred = Signal(str)
    finished_processing = Signal()

    def __init__(self, mask_path, cache_dir, params):
        super().__init__()
        self.mask_path = mask_path
        self.cache_dir = cache_dir
        self.params = params
        self.is_cancelled = False
        
    def cancel(self):
        self.is_cancelled = True

    def _resample_polygon(self, polygon, num_points):
        # polygon: shape (N, 1, 2)
        pts = polygon.reshape(-1, 2).astype(np.float32)
        if len(pts) < 2:
            return pts
            
        # Calculate cumulative arc length
        diffs = np.diff(pts, axis=0)
        # add distance from last to first
        diffs = np.vstack([diffs, pts[0] - pts[-1]])
        dists = np.linalg.norm(diffs, axis=1)
        cum_dists = np.concatenate([[0], np.cumsum(dists)])
        total_len = cum_dists[-1]
        
        if total_len == 0:
            return pts
            
        # target distances
        target_dists = np.linspace(0, total_len, num_points, endpoint=False)
        
        resampled = np.zeros((num_points, 2), dtype=np.float32)
        resampled[:, 0] = np.interp(target_dists, cum_dists, np.append(pts[:, 0], pts[0, 0]))
        resampled[:, 1] = np.interp(target_dists, cum_dists, np.append(pts[:, 1], pts[0, 1]))
        
        return resampled

    def _align_polygon(self, current, reference):
        # current and reference both (N, 2)
        # Find the circular shift of current that minimizes distance to reference
        N = len(current)
        best_shift = 0
        min_dist = float('inf')
        
        # We can just check all shifts since N is small (e.g. 100-500)
        for shift in range(N):
            shifted = np.roll(current, shift, axis=0)
            dist = np.sum(np.linalg.norm(shifted - reference, axis=1))
            if dist < min_dist:
                min_dist = dist
                best_shift = shift
                
        return np.roll(current, best_shift, axis=0)

    def run(self):
        try:
            self.log_message.emit("Initializing Roto to Shape processing...")
            
            target_points = int(self.params.get("target_points", 100))
            min_area = float(self.params.get("min_area", 100.0))
            epsilon = float(self.params.get("simplify_epsilon", 1.0))
            
            if not os.path.exists(self.mask_path):
                raise FileNotFoundError(f"Mask path not found: {self.mask_path}")
                
            out_dir = os.path.join(self.cache_dir, "roto_shapes")
            os.makedirs(out_dir, exist_ok=True)
            
            # Gather frames
            frames = []
            if os.path.isdir(self.mask_path):
                frames = sorted([f for f in os.listdir(self.mask_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tif', '.exr'))])
            else:
                self.log_message.emit("Expected a directory of alpha masks.")
                return

            total_frames = len(frames)
            if total_frames == 0:
                raise ValueError("No mask frames found.")
                
            reference_polygon = None
            
            self.log_message.emit(f"Extracting contours across {total_frames} frames...")
            
            all_shapes = {}
            
            for i, f_name in enumerate(frames):
                if self.is_cancelled:
                    self.log_message.emit("Roto extraction cancelled.")
                    return
                    
                frame_path = os.path.join(self.mask_path, f_name)
                
                # Use IMREAD_UNCHANGED to read potential 16-bit or alpha channels
                img = cv2.imread(frame_path, cv2.IMREAD_UNCHANGED)
                if img is None:
                    continue
                    
                # If 3 or 4 channels, grab alpha or average
                if len(img.shape) == 3:
                    if img.shape[2] == 4:
                        img = img[:, :, 3]
                    else:
                        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                
                # Ensure 8-bit
                if img.dtype != np.uint8:
                    if img.dtype == np.uint16:
                        img = (img / 256).astype(np.uint8)
                    else:
                        img = (np.clip(img, 0, 1) * 255).astype(np.uint8)
                    
                # Threshold to ensure binary
                _, thresh = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
                
                # Find contours
                contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                # Filter by area
                valid_contours = [c for c in contours if cv2.contourArea(c) >= min_area]
                
                if valid_contours:
                    # Take the largest contour
                    largest_contour = max(valid_contours, key=cv2.contourArea)
                    
                    # Simplify
                    if epsilon > 0:
                        largest_contour = cv2.approxPolyDP(largest_contour, epsilon, True)
                        
                    # Resample to target points
                    resampled = self._resample_polygon(largest_contour, target_points)
                    
                    # Align with reference
                    if reference_polygon is not None:
                        resampled = self._align_polygon(resampled, reference_polygon)
                        
                    reference_polygon = resampled
                    
                    # Store (y-axis inverted for Nuke compatibility usually done in exporter, so we keep raw pixel coords here)
                    all_shapes[i] = resampled.tolist()
                else:
                    # No shape found, repeat last frame to maintain shape existence
                    if reference_polygon is not None:
                        all_shapes[i] = reference_polygon.tolist()
                        
                self.progress_update.emit(i + 1, total_frames)
                
            # Save to JSON
            out_file = os.path.join(out_dir, "shapes.json")
            with open(out_file, "w") as f:
                json.dump(all_shapes, f)
                
            self.log_message.emit(f"Successfully generated animated shape data.")
            self.finished_processing.emit()
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error_occurred.emit(str(e))

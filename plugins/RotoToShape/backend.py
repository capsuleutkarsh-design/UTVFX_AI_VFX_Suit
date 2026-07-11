import os
import cv2
import numpy as np
import json
from PySide6.QtCore import QThread, Signal

from utvfx.bridge.base_worker import BaseWorker

class RotoToShapeWorker(BaseWorker):
    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(node_id, params, inputs, cache_dir, output_dir, parent)
        self.mask_path = inputs.get("Alpha Matte")


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

    def run_task(self):
        self.log_message.emit(self.node_id, "Initializing Roto to Shape processing...")
        
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
            raise Exception("Expected a directory of alpha masks.")

        total_frames = len(frames)
        if total_frames == 0:
            raise ValueError("No mask frames found.")
            
        reference_polygon = None
        
        self.log_message.emit(self.node_id, f"Extracting contours across {total_frames} frames...")
        
        all_shapes = {}
        active_shapes = {}
        next_shape_id = 0
        
        for i, f_name in enumerate(frames):
            if self.is_cancelled:
                self.log_message.emit(self.node_id, "Roto extraction cancelled.")
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
            
            current_frame_shapes = {}
            used_contours = set()
            
            # Track existing shapes
            for shape_id, prev_pts in active_shapes.items():
                prev_pts_np = np.array(prev_pts, dtype=np.float32)
                prev_center = np.mean(prev_pts_np, axis=0)
                
                best_cnt_idx = -1
                min_dist = float('inf')
                
                for c_idx, cnt in enumerate(valid_contours):
                    if c_idx in used_contours:
                        continue
                    M = cv2.moments(cnt)
                    if M["m00"] != 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])
                        dist = np.linalg.norm(prev_center - np.array([cx, cy], dtype=np.float32))
                        if dist < min_dist:
                            min_dist = dist
                            best_cnt_idx = c_idx
                            
                # If we found a contour close enough (e.g. within 200 pixels)
                if best_cnt_idx != -1 and min_dist < 200.0:
                    cnt = valid_contours[best_cnt_idx]
                    used_contours.add(best_cnt_idx)
                    
                    if epsilon > 0:
                        cnt = cv2.approxPolyDP(cnt, epsilon, True)
                    resampled = self._resample_polygon(cnt, target_points)
                    resampled = self._align_polygon(resampled, prev_pts_np)
                    current_frame_shapes[shape_id] = resampled.tolist()
                else:
                    # Shape disappeared in this frame. Copy previous to maintain it.
                    current_frame_shapes[shape_id] = prev_pts
                    
            # Any remaining contours are NEW shapes
            for c_idx, cnt in enumerate(valid_contours):
                if c_idx not in used_contours:
                    if epsilon > 0:
                        cnt = cv2.approxPolyDP(cnt, epsilon, True)
                    resampled = self._resample_polygon(cnt, target_points)
                    
                    shape_id = next_shape_id
                    next_shape_id += 1
                    current_frame_shapes[shape_id] = resampled.tolist()
                    
            active_shapes = current_frame_shapes.copy()
            all_shapes[i] = current_frame_shapes
            
            # Draw preview
            preview = np.zeros((img.shape[0], img.shape[1], 3), dtype=np.uint8)
            mask_bgr = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
            
            for sid, pts in current_frame_shapes.items():
                pts_int = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
                color = (int((sid * 80) % 255), int((sid * 150 + 100) % 255), int((sid * 200 + 200) % 255))
                cv2.polylines(preview, [pts_int], isClosed=True, color=color, thickness=2)
                
            preview = cv2.addWeighted(mask_bgr, 0.3, preview, 0.7, 0)
            cv2.imwrite(os.path.join(out_dir, f"preview_{i:06d}.png"), preview)
            
            self.progress_update.emit(self.node_id, i + 1, total_frames)
            
        # Save format dims for Nuke exporter
        if frames:
            first_frame_path = os.path.join(self.mask_path, frames[0])
            first_img = cv2.imread(first_frame_path, cv2.IMREAD_UNCHANGED)
            if first_img is not None:
                all_shapes["format_width"] = int(first_img.shape[1])
                all_shapes["format_height"] = int(first_img.shape[0])
            
        # Save to JSON
        out_file = os.path.join(out_dir, "shapes.json")
        with open(out_file, "w") as f:
            json.dump(all_shapes, f)
            
        self.log_message.emit(self.node_id, f"Successfully generated animated shape data.")

import json
import os

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

from utvfx.bridge.base_worker import BaseWorker


def bbox_iou(boxA, boxB):
    """Calculate Intersection-over-Union between two bounding boxes.
    Each box is (x, y, w, h).
    """
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[0] + boxA[2], boxB[0] + boxB[2])
    yB = min(boxA[1] + boxA[3], boxB[1] + boxB[3])

    interArea = max(0, xB - xA) * max(0, yB - yA)
    if interArea == 0:
        return 0.0

    boxAArea = boxA[2] * boxA[3]
    boxBArea = boxB[2] * boxB[3]
    unionArea = float(boxAArea + boxBArea - interArea)

    if unionArea <= 0:
        return 0.0

    return interArea / unionArea



class RotoToShapeWorker(BaseWorker):
    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(node_id, params, inputs, cache_dir, output_dir, parent)
        self.mask_path = inputs.get("Alpha Matte")


    @staticmethod
    def _parse_bool(val):
        """Safely parse a boolean from params (handles string 'false')."""
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ('true', '1', 'yes')
        return bool(val)

    def _resample_polygon(self, polygon, num_points, curvature_weight=5.0):
        # polygon: shape (N, 1, 2)
        pts = polygon.reshape(-1, 2).astype(np.float32)
        if len(pts) < 2:
            return pts
            
        diffs = np.diff(pts, axis=0)
        diffs = np.vstack([diffs, pts[0] - pts[-1]])
        dists = np.linalg.norm(diffs, axis=1)
        
        if np.sum(dists) == 0:
            return np.zeros((num_points, 2), dtype=np.float32) + pts[0]
            
        # Curvature adaptive density
        pts_rolled_fwd = np.roll(pts, -1, axis=0)
        pts_rolled_bck = np.roll(pts, 1, axis=0)
        
        v1 = pts - pts_rolled_bck
        v2 = pts_rolled_fwd - pts
        
        n1 = np.linalg.norm(v1, axis=1, keepdims=True)
        n2 = np.linalg.norm(v2, axis=1, keepdims=True)
        
        n1[n1 == 0] = 1.0
        n2[n2 == 0] = 1.0
        
        v1_norm = v1 / n1
        v2_norm = v2 / n2
        
        dot = np.sum(v1_norm * v2_norm, axis=1)
        dot = np.clip(dot, -1.0, 1.0)
        angle = np.arccos(dot)
        
        # Density is based on arc length weighted by curvature
        density = dists * (1.0 + curvature_weight * angle)
        
        cum_density = np.concatenate([[0], np.cumsum(density)])
        total_density = cum_density[-1]
        
        if total_density == 0:
            return np.zeros((num_points, 2), dtype=np.float32) + pts[0]
            
        target_density = np.linspace(0, total_density, num_points, endpoint=False)
        
        resampled = np.zeros((num_points, 2), dtype=np.float32)
        pts_wrap = np.vstack([pts, pts[0:1]])
        
        for i, td in enumerate(target_density):
            idx = np.searchsorted(cum_density, td, side='right') - 1
            idx = np.clip(idx, 0, len(cum_density) - 2)
            
            segment_density = cum_density[idx+1] - cum_density[idx]
            if segment_density > 0:
                t = (td - cum_density[idx]) / segment_density
            else:
                t = 0.0
                
            resampled[i] = pts_wrap[idx] * (1.0 - t) + pts_wrap[idx+1] * t
            
        return resampled

    def _snap_to_gradient(self, pts, grad_mag, snap_radius=2):
        h, w = grad_mag.shape
        snapped = np.copy(pts)
        
        pts_rolled_fwd = np.roll(pts, -1, axis=0)
        pts_rolled_bck = np.roll(pts, 1, axis=0)
        tangent = pts_rolled_fwd - pts_rolled_bck
        
        norms = np.linalg.norm(tangent, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        tangent = tangent / norms
        
        normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
        
        search_radius = snap_radius
        for i in range(len(pts)):
            px, py = pts[i]
            nx, ny = normal[i]
            
            best_val = -1
            best_pt = (px, py)
            
            for step in range(-search_radius, search_radius + 1):
                sx = px + nx * step
                sy = py + ny * step
                
                ix = int(round(sx))
                iy = int(round(sy))
                
                if 0 <= ix < w and 0 <= iy < h:
                    val = grad_mag[iy, ix]
                    if val > best_val:
                        best_val = val
                        best_pt = (sx, sy)
                        
            snapped[i] = best_pt
            
        return snapped

    def _align_polygon(self, current, reference):
        # current and reference both (N, 2)
        # Maximize circular cross-correlation to minimize Euclidean distance
        N = len(current)
        if N < 2:
            return current
            
        c_x = np.tile(current[:, 0], 2)[:-1]
        c_y = np.tile(current[:, 1], 2)[:-1]
        r_x = reference[:, 0]
        r_y = reference[:, 1]
        
        corr = np.correlate(c_x, r_x, mode='valid') + np.correlate(c_y, r_y, mode='valid')
        best_shift = np.argmax(corr)
                    
        return np.roll(current, -best_shift, axis=0)

    def run_task(self):
        self.log_message.emit(self.node_id, "Initializing Roto to Shape processing...")
        
        point_mode = self.params.get("point_mode", "Auto (Adaptive)")
        auto_point_spacing = float(self.params.get("auto_point_spacing", 30))
        target_points = int(self.params.get("target_points", 100))
        curvature_weight = float(self.params.get("curvature_weight", 5.0))
        min_area = float(self.params.get("min_area", 100.0))
        epsilon = float(self.params.get("simplify_epsilon", 1.0))
        edge_snap_radius = int(self.params.get("edge_snap_radius", 2))
        iou_threshold = float(self.params.get("iou_threshold", 0.3))
        include_holes = self._parse_bool(self.params.get("include_holes", False))
        max_missing_frames = int(self.params.get("max_missing_frames", 5))
        temporal_smoothing = self._parse_bool(self.params.get("temporal_smoothing", True))
        first_frame = int(self.params.get("first_frame", 0))
        last_frame = int(self.params.get("last_frame", 0))
        
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

        # Apply frame range
        if first_frame > 0:
            frames = frames[first_frame:]
        if last_frame > 0:
            frames = frames[:last_frame - first_frame + 1]

        total_frames = len(frames)
        if total_frames == 0:
            raise ValueError("No mask frames found in the specified range.")
            
        self.log_message.emit(self.node_id, f"Extracting contours across {total_frames} frames (range: {first_frame}-{last_frame if last_frame > 0 else 'end'})...")
        
        all_shapes = {}
        active_shapes = {}
        lost_shapes_count = {}
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
                
            # Calculate gradient magnitude for sub-pixel snapping
            grad_x = cv2.Sobel(img, cv2.CV_32F, 1, 0, ksize=3)
            grad_y = cv2.Sobel(img, cv2.CV_32F, 0, 1, ksize=3)
            grad_mag = np.sqrt(grad_x**2 + grad_y**2)
            
            # Threshold to ensure binary
            _, thresh = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
            
            # Find contours
            contours, hierarchy = cv2.findContours(thresh, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
            
            valid_contours = []
            valid_is_hole = []
            valid_bboxes = []
            
            if hierarchy is not None:
                for c_idx, cnt in enumerate(contours):
                    if cv2.contourArea(cnt) >= min_area:
                        parent_idx = hierarchy[0][c_idx][3]
                        is_hole = (parent_idx != -1)
                        if is_hole and not include_holes:
                            continue
                        valid_contours.append(cnt)
                        valid_is_hole.append(is_hole)
                        valid_bboxes.append(cv2.boundingRect(cnt))
            
            current_frame_shapes = {}
            used_contours = set()
            
            # Track existing shapes using Bounding Box IOU
            for shape_id, prev_pts in active_shapes.items():
                prev_pts_np = np.array(prev_pts, dtype=np.float32)
                
                # Compute bounding box of previous points
                x_min, y_min = np.min(prev_pts_np, axis=0)
                x_max, y_max = np.max(prev_pts_np, axis=0)
                prev_bbox = (x_min, y_min, x_max - x_min, y_max - y_min)
                
                best_cnt_idx = -1
                max_iou = -1.0
                
                for c_idx, cnt in enumerate(valid_contours):
                    if c_idx in used_contours:
                        continue
                        
                    iou = bbox_iou(prev_bbox, valid_bboxes[c_idx])
                    if iou > max_iou:
                        max_iou = iou
                        best_cnt_idx = c_idx
                            
                if best_cnt_idx != -1 and max_iou >= iou_threshold:
                    # Match found
                    cnt = valid_contours[best_cnt_idx]
                    used_contours.add(best_cnt_idx)
                    
                    if epsilon > 0:
                        cnt = cv2.approxPolyDP(cnt, epsilon, True)
                    
                    # Maintain original point count
                    prev_num_points = len(prev_pts_np)
                    resampled = self._resample_polygon(cnt, prev_num_points, curvature_weight)
                    resampled = self._snap_to_gradient(resampled, grad_mag, edge_snap_radius)
                    resampled = self._align_polygon(resampled, prev_pts_np)
                    
                    current_frame_shapes[shape_id] = resampled.tolist()
                    lost_shapes_count[shape_id] = 0
                else:
                    # Shape disappeared in this frame
                    lost_shapes_count[shape_id] = lost_shapes_count.get(shape_id, 0) + 1
                    if lost_shapes_count[shape_id] <= max_missing_frames:
                        # Copy previous to maintain it while missing
                        current_frame_shapes[shape_id] = prev_pts
                    
            # Any remaining contours are NEW shapes
            for c_idx, cnt in enumerate(valid_contours):
                if c_idx not in used_contours:
                    if epsilon > 0:
                        cnt = cv2.approxPolyDP(cnt, epsilon, True)
                        
                    if point_mode == "Auto (Adaptive)":
                        perimeter = cv2.arcLength(cnt, True)
                        num_points = max(8, int(perimeter / auto_point_spacing))
                    else:
                        num_points = target_points
                        
                    resampled = self._resample_polygon(cnt, num_points, curvature_weight)
                    resampled = self._snap_to_gradient(resampled, grad_mag, edge_snap_radius)
                    
                    is_hole = valid_is_hole[c_idx]
                    prefix = "Hole" if is_hole else "Shape"
                    shape_id = f"{prefix}_{next_shape_id}"
                    next_shape_id += 1
                    
                    current_frame_shapes[shape_id] = resampled.tolist()
                    lost_shapes_count[shape_id] = 0
                    
            active_shapes = current_frame_shapes.copy()
            all_shapes[str(i)] = current_frame_shapes
            
            # Draw preview
            preview = np.zeros((img.shape[0], img.shape[1], 3), dtype=np.uint8)
            mask_bgr = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
            
            for sid, pts in current_frame_shapes.items():
                pts_int = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
                
                # generate deterministic color from sid string
                sid_num = sum(ord(c) for c in sid)
                color = ((sid_num * 80) % 255, (sid_num * 150 + 100) % 255, (sid_num * 200 + 200) % 255)
                cv2.polylines(preview, [pts_int], isClosed=True, color=color, thickness=2)
                
                # Draw control point dots so artists can see adaptive distribution
                for pt in pts:
                    cx, cy = int(round(pt[0])), int(round(pt[1]))
                    cv2.circle(preview, (cx, cy), 3, (255, 255, 255), -1)  # white fill
                    cv2.circle(preview, (cx, cy), 3, color, 1)  # colored ring
                
            preview = cv2.addWeighted(mask_bgr, 0.3, preview, 0.7, 0)
            cv2.imwrite(os.path.join(out_dir, f"preview_{i:06d}.png"), preview)
            
            self.progress_update.emit(self.node_id, i + 1, max(1, total_frames))
            
        # --- Temporal Smoothing Post-Process ---
        if temporal_smoothing and total_frames > 2:
            self.log_message.emit(self.node_id, "Applying temporal smoothing...")
            shape_ids = set()
            for f in range(total_frames):
                if str(f) in all_shapes:
                    shape_ids.update(all_shapes[str(f)].keys())
                    
            for sid in shape_ids:
                frames_present = [f for f in range(total_frames) if str(f) in all_shapes and sid in all_shapes[str(f)]]
                if len(frames_present) < 3:
                    continue
                    
                smoothed = {}
                for idx, f in enumerate(frames_present):
                    pts_curr = np.array(all_shapes[str(f)][sid])
                    if idx > 0 and idx < len(frames_present) - 1:
                        f_prev = frames_present[idx-1]
                        f_next = frames_present[idx+1]
                        if f_prev == f - 1 and f_next == f + 1:
                            pts_prev = np.array(all_shapes[str(f_prev)][sid])
                            pts_next = np.array(all_shapes[str(f_next)][sid])
                            pts_curr = (pts_prev + pts_curr + pts_next) / 3.0
                    smoothed[str(f)] = pts_curr.tolist()
                    
                for f in frames_present:
                    if str(f) in smoothed:
                        all_shapes[str(f)][sid] = smoothed[str(f)]
            
        # Save format dims for Nuke exporter
        if frames:
            first_frame_path = os.path.join(self.mask_path, frames[0])
            first_img = cv2.imread(first_frame_path, cv2.IMREAD_UNCHANGED)
            if first_img is not None:
                all_shapes["format_width"] = first_img.shape[1]
                all_shapes["format_height"] = first_img.shape[0]
            
        # Save to JSON
        out_file = os.path.join(out_dir, "shapes.json")
        with open(out_file, "w") as f:
            json.dump(all_shapes, f)
            
        self.log_message.emit(self.node_id, f"Successfully generated animated shape data.")

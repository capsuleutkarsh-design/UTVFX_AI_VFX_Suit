import json
import os
import re

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

def bbox_center_dist(boxA, boxB):
    cA = (boxA[0] + boxA[2]/2.0, boxA[1] + boxA[3]/2.0)
    cB = (boxB[0] + boxB[2]/2.0, boxB[1] + boxB[3]/2.0)
    return ((cA[0]-cB[0])**2 + (cA[1]-cB[1])**2)**0.5


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

    def _resample_polygon(self, polygon, num_points, curvature_weight=5.0, frame_size=None):
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
        
        if frame_size is not None:
            w, h = frame_size
            margin = 3
            pts_wrap_temp = np.vstack([pts, pts[0:1]])
            for i in range(len(pts)):
                p1 = pts_wrap_temp[i]
                p2 = pts_wrap_temp[i+1]
                on_left = (p1[0] <= margin and p2[0] <= margin)
                on_right = (p1[0] >= w - margin and p2[0] >= w - margin)
                on_top = (p1[1] <= margin and p2[1] <= margin)
                on_bottom = (p1[1] >= h - margin and p2[1] >= h - margin)
                if on_left or on_right or on_top or on_bottom:
                    density[i] *= 0.05
        
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
            
            cx, cy = int(round(px)), int(round(py))
            if 0 <= cx < w and 0 <= cy < h:
                best_val = grad_mag[cy, cx]
            else:
                best_val = -1
            best_pt = (px, py)
            
            for step in range(-search_radius, search_radius + 1):
                if step == 0:
                    continue
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
        
        layers_to_process = []
        sam_masks_dir = os.path.join(os.path.dirname(self.mask_path), "sam_masks")
        if os.path.isdir(sam_masks_dir):
            for item in os.listdir(sam_masks_dir):
                item_path = os.path.join(sam_masks_dir, item)
                if os.path.isdir(item_path):
                    layers_to_process.append({"name": item, "dir": item_path})
        
        if not layers_to_process:
            layers_to_process.append({"name": "Shapes", "dir": self.mask_path})
            
        self.log_message.emit(self.node_id, f"Found {len(layers_to_process)} layers to process.")
        
        all_shapes = {}
        
        for layer_info in layers_to_process:
            layer_name = layer_info["name"]
            layer_dir = layer_info["dir"]
            
            self.log_message.emit(self.node_id, f"Processing layer: {layer_name}")
            
            frames = sorted([f for f in os.listdir(layer_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tif', '.exr'))])
            if first_frame > 0:
                frames = frames[first_frame:]
            if last_frame > 0:
                frames = frames[:last_frame - first_frame + 1]
                
            total_frames = len(frames)
            if total_frames == 0:
                continue
                
            active_shapes = {}
            lost_shapes_count = {}
            next_shape_id = 0
            
            prev_gray = None
            
            for i, f_name in enumerate(frames):
                if self.is_cancelled:
                    return
                    
                match = re.search(r'(?:_|)(\d+)\.\w+$', f_name)
                f_idx = int(match.group(1)) if match else i
                f_idx_str = str(f_idx)
                
                if f_idx_str not in all_shapes:
                    all_shapes[f_idx_str] = {}
                    
                frame_path = os.path.join(layer_dir, f_name)
                img = cv2.imread(frame_path, cv2.IMREAD_UNCHANGED)
                if img is None: continue
                
                if "format_width" not in all_shapes:
                    all_shapes["format_width"] = img.shape[1]
                    all_shapes["format_height"] = img.shape[0]
                
                if len(img.shape) == 3:
                    img = img[:, :, 3] if img.shape[2] == 4 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                if img.dtype != np.uint8:
                    img = (img / 256).astype(np.uint8) if img.dtype == np.uint16 else (np.clip(img, 0, 1) * 255).astype(np.uint8)
                    
                grad_x = cv2.Sobel(img, cv2.CV_32F, 1, 0, ksize=3)
                grad_y = cv2.Sobel(img, cv2.CV_32F, 0, 1, ksize=3)
                grad_mag = np.sqrt(grad_x**2 + grad_y**2)
                
                edge_threshold = int(self.params.get("edge_threshold", 127))
                _, thresh = cv2.threshold(img, edge_threshold, 255, cv2.THRESH_BINARY)
                
                # Use morphological operations to clean up noisy edge thresholding if needed
                kernel = np.ones((3,3), np.uint8)
                thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
                thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

                contours, hierarchy = cv2.findContours(thresh, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
                
                valid_contours = []
                valid_is_hole = []
                valid_bboxes = []
                if hierarchy is not None:
                    for c_idx, cnt in enumerate(contours):
                        if cv2.contourArea(cnt) >= min_area:
                            is_hole = (hierarchy[0][c_idx][3] != -1)
                            if is_hole and not include_holes: continue
                            valid_contours.append(cnt)
                            valid_is_hole.append(is_hole)
                            valid_bboxes.append(cv2.boundingRect(cnt))
                            
                current_frame_shapes = {}
                used_contours = set()
                
                # Optical flow image prep
                # Blur slightly to create gradients for PyrLK
                curr_gray = cv2.GaussianBlur(img, (15, 15), 0)
                
                for shape_id, prev_pts in active_shapes.items():
                    prev_pts_np = np.array(prev_pts, dtype=np.float32)
                    x_min, y_min = np.min(prev_pts_np, axis=0)
                    x_max, y_max = np.max(prev_pts_np, axis=0)
                    prev_bbox = (x_min, y_min, x_max - x_min, y_max - y_min)
                    
                    best_cnt_idx = -1
                    best_score = -1.0
                    for c_idx, cnt in enumerate(valid_contours):
                        if c_idx in used_contours: continue
                        iou = bbox_iou(prev_bbox, valid_bboxes[c_idx])
                        dist = bbox_center_dist(prev_bbox, valid_bboxes[c_idx])
                        
                        max_dim = max(prev_bbox[2], prev_bbox[3], valid_bboxes[c_idx][2], valid_bboxes[c_idx][3])
                        dist_score = max(0, 1.0 - dist / (max_dim + 1e-5))
                        score = max(iou, dist_score)
                        
                        if score > best_score:
                            best_score = score
                            best_cnt_idx = c_idx
                            
                    if best_cnt_idx != -1 and best_score >= iou_threshold:
                        cnt = valid_contours[best_cnt_idx]
                        used_contours.add(best_cnt_idx)
                        
                        num_points = len(prev_pts)
                        frame_size = (all_shapes["format_width"], all_shapes["format_height"])
                        resampled = self._resample_polygon(cnt, num_points, curvature_weight, frame_size)
                        
                        # Find best cyclic shift to align starting point of resampled contour with prev_pts
                        best_shift = 0
                        min_dist_sum = float('inf')
                        for shift in range(num_points):
                            rolled = np.roll(resampled, shift, axis=0)
                            dist_sum = np.sum(np.linalg.norm(rolled - prev_pts_np, axis=1))
                            if dist_sum < min_dist_sum:
                                min_dist_sum = dist_sum
                                best_shift = shift
                                
                        aligned_resampled = np.roll(resampled, best_shift, axis=0)
                        
                        # Snap aligned points to edge gradient
                        snapped_pts = self._snap_to_gradient(aligned_resampled, grad_mag, edge_snap_radius)
                        
                        current_frame_shapes[shape_id] = snapped_pts.tolist()
                        lost_shapes_count[shape_id] = 0
                    else:
                        lost_shapes_count[shape_id] = lost_shapes_count.get(shape_id, 0) + 1
                        if lost_shapes_count[shape_id] <= max_missing_frames:
                            current_frame_shapes[shape_id] = prev_pts
                            
                for c_idx, cnt in enumerate(valid_contours):
                    if c_idx not in used_contours:
                        if epsilon > 0:
                            cnt = cv2.approxPolyDP(cnt, epsilon, True)
                        perimeter = cv2.arcLength(cnt, True)
                        num_points = max(8, int(perimeter / auto_point_spacing)) if point_mode == "Auto (Adaptive)" else target_points
                        if point_mode == "Auto (Adaptive)":
                            num_points = min(num_points, 80)
                        frame_size = (all_shapes["format_width"], all_shapes["format_height"])
                        resampled = self._resample_polygon(cnt, num_points, curvature_weight, frame_size)
                        resampled = self._snap_to_gradient(resampled, grad_mag, edge_snap_radius)
                        
                        prefix = "Hole" if valid_is_hole[c_idx] else "Shape"
                        # Namespace shape with layer
                        shape_id = f"{layer_name}/{prefix}_{next_shape_id}"
                        next_shape_id += 1
                        current_frame_shapes[shape_id] = resampled.tolist()
                        lost_shapes_count[shape_id] = 0
                        
                active_shapes = current_frame_shapes.copy()
                all_shapes[f_idx_str].update(current_frame_shapes)
                prev_gray = curr_gray
                
                self.progress_update.emit(self.node_id, i + 1, max(1, total_frames))
                
        # --- Temporal Smoothing Post-Process ---
        if temporal_smoothing:
            self.log_message.emit(self.node_id, "Applying temporal rolling average smoothing...")
            frames_present = sorted([int(k) for k in all_shapes.keys() if str(k).isdigit()])
            
            smoothed_shapes = {str(f): {} for f in frames_present}
            smoothed_shapes["format_width"] = all_shapes.get("format_width", 1920)
            smoothed_shapes["format_height"] = all_shapes.get("format_height", 1080)
            
            for f_idx in frames_present:
                f_str = str(f_idx)
                for sid, pts in all_shapes[f_str].items():
                    pts_np = np.array(pts)
                    num_pts = len(pts_np)
                    
                    smoothed_pts = pts_np
                    
                    idx = frames_present.index(f_idx)
                    if idx > 0 and idx < len(frames_present) - 1:
                        prev_f = str(frames_present[idx - 1])
                        next_f = str(frames_present[idx + 1])
                        if sid in all_shapes[prev_f] and sid in all_shapes[next_f]:
                            pts_prev = np.array(all_shapes[prev_f][sid])
                            pts_next = np.array(all_shapes[next_f][sid])
                            if len(pts_prev) == num_pts and len(pts_next) == num_pts:
                                # Only smooth if the points haven't moved too wildly (e.g. tracking jumped)
                                dist_prev = np.mean(np.linalg.norm(pts_prev - pts_np, axis=1))
                                dist_next = np.mean(np.linalg.norm(pts_next - pts_np, axis=1))
                                if dist_prev < 20 and dist_next < 20:
                                    smoothed_pts = (pts_prev + pts_np + pts_next) / 3.0
                    
                    smoothed_shapes[f_str][sid] = smoothed_pts.tolist()
            
            all_shapes = smoothed_shapes
            
        # --- Format Y-flip and Cusp Detection ---
        format_h = all_shapes.get("format_height", 1080)
        
        corner_threshold = float(self.params.get("corner_threshold", 45))
        corner_rad = np.radians(corner_threshold)
        
        frames_present = sorted([int(k) for k in all_shapes.keys() if str(k).isdigit()])
        for f_idx in frames_present:
            f_str = str(f_idx)
            for sid, pts in all_shapes[f_str].items():
                pts_np = np.array(pts, dtype=np.float32)
                pts_with_type = []
                if len(pts_np) > 2:
                    pts_rolled_fwd = np.roll(pts_np, -1, axis=0)
                    pts_rolled_bck = np.roll(pts_np, 1, axis=0)
                    v1 = pts_np - pts_rolled_bck
                    v2 = pts_rolled_fwd - pts_np
                    n1 = np.linalg.norm(v1, axis=1, keepdims=True)
                    n2 = np.linalg.norm(v2, axis=1, keepdims=True)
                    n1[n1 == 0] = 1.0
                    n2[n2 == 0] = 1.0
                    dot = np.sum((v1 / n1) * (v2 / n2), axis=1)
                    dot = np.clip(dot, -1.0, 1.0)
                    angle = np.arccos(dot)
                else:
                    angle = np.zeros(len(pts_np))
                    
                for j, pt in enumerate(pts_np):
                    y_flipped = format_h - pt[1]
                    curve_type = "cusp" if angle[j] > corner_rad else "smooth"
                    pts_with_type.append([float(pt[0]), float(y_flipped), curve_type])
                    
                all_shapes[f_str][sid] = pts_with_type

        # --- Preview Generation ---
        if os.path.exists(self.mask_path):
            self.log_message.emit(self.node_id, "Generating preview overlays...")
            preview_dir = os.path.join(out_dir, "previews")
            os.makedirs(preview_dir, exist_ok=True)
            
            mask_files = sorted([f for f in os.listdir(self.mask_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tif', '.exr'))])
            
            frame_map = {}
            for f_name in mask_files:
                match = re.search(r'(\d+)\.\w+$', f_name)
                idx = int(match.group(1)) if match else -1
                if idx != -1:
                    frame_map[idx] = f_name
            
            for f_idx in frames_present:
                if f_idx in frame_map:
                    f_name = frame_map[f_idx]
                    mask_img = cv2.imread(os.path.join(self.mask_path, f_name))
                    if mask_img is not None:
                        if len(mask_img.shape) == 2:
                            mask_img = cv2.cvtColor(mask_img, cv2.COLOR_GRAY2BGR)
                            
                        for sid, pts_with_type in all_shapes[str(f_idx)].items():
                            is_hole = "Hole_" in sid.split('/')[-1]
                            color = (0, 0, 255) if is_hole else (0, 255, 0)
                            
                            # unflip Y just for preview
                            draw_pts = np.array([[pt[0], format_h - pt[1]] for pt in pts_with_type], dtype=np.int32)
                            if len(draw_pts) > 0:
                                cv2.polylines(mask_img, [draw_pts], isClosed=True, color=color, thickness=2)
                                
                                for pt in draw_pts:
                                    cv2.circle(mask_img, (pt[0], pt[1]), 2, (255, 0, 0), -1)
                        
                        out_prev_path = os.path.join(preview_dir, f"preview_{f_idx:04d}.png")
                        cv2.imwrite(out_prev_path, mask_img)

        json_path = os.path.join(out_dir, "shapes.json")
        with open(json_path, 'w') as f:
            json.dump(all_shapes, f, indent=2)
            
        self.log_message.emit(self.node_id, f"Exported {len(all_shapes)} frames of shape data.")

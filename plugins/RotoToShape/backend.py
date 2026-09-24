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
        self.media_path = inputs.get("Video Plate") or inputs.get("Media Plate")
        self.depth_path = inputs.get("Depth Map")


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

    def _calculate_feather(self, pts, img, threshold=5, max_dist=100):
        h, w = img.shape
        feather_pts = []
        
        pts_rolled_fwd = np.roll(pts, -1, axis=0)
        pts_rolled_bck = np.roll(pts, 1, axis=0)
        tangent = pts_rolled_fwd - pts_rolled_bck
        
        norms = np.linalg.norm(tangent, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        tangent = tangent / norms
        normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
        
        for i in range(len(pts)):
            pt = pts[i]
            n = normal[i]
            
            # Find which direction points outward (towards lower alpha)
            p1 = pt + n * 2
            p2 = pt - n * 2
            
            val1 = img[min(h-1, max(0, int(p1[1]))), min(w-1, max(0, int(p1[0])))]
            val2 = img[min(h-1, max(0, int(p2[1]))), min(w-1, max(0, int(p2[0])))]
            
            out_dir = n if val1 < val2 else -n
            
            f_pt = pt.copy()
            prev_val = int(img[min(h-1, max(0, int(pt[1]))), min(w-1, max(0, int(pt[0])))])
            min_val = prev_val
            min_pt = pt.copy()
            
            for step in range(1, max_dist):
                test_pt = pt + out_dir * step
                tx, ty = int(test_pt[0]), int(test_pt[1])
                if tx < 0 or tx >= w or ty < 0 or ty >= h:
                    f_pt = [min(w - 1, max(0, tx)), min(h - 1, max(0, ty))]
                    break
                curr_val = int(img[ty, tx])
                if curr_val <= threshold:
                    f_pt = test_pt
                    break
                if curr_val < min_val:
                    min_val = curr_val
                    min_pt = test_pt.copy()
                # Monotonicity check: if alpha intensity increases significantly (hitting another matte or noise), stop at local alpha minimum
                if curr_val > min_val + 15:
                    f_pt = min_pt
                    break
            else:
                f_pt = min_pt
            feather_pts.append(f_pt)
            
        return np.array(feather_pts)

    def _snap_to_gradient(self, pts, grad_mag, snap_radius=2, img=None, core_threshold=0):
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
                best_val = float(grad_mag[cy, cx])
                if img is not None and core_threshold > 0 and img[cy, cx] < core_threshold:
                    best_val *= 0.1
            else:
                best_val = -1.0
            best_pt = (px, py)
            
            for step in range(-search_radius, search_radius + 1):
                if step == 0:
                    continue
                sx = px + nx * step
                sy = py + ny * step
                
                ix = int(round(sx))
                iy = int(round(sy))
                
                if 0 <= ix < w and 0 <= iy < h:
                    val = float(grad_mag[iy, ix])
                    if img is not None and core_threshold > 0 and img[iy, ix] < core_threshold:
                        val *= 0.1
                    if val > best_val:
                        best_val = val
                        best_pt = (sx, sy)
                        
            snapped[i] = best_pt
            
        return snapped

    # ---- keeping points on the same part of the object from frame to frame -----------
    # Each point follows the image motion measured just inside the object, then is placed on
    # the new outline at the nearest spot, in order. Re-spacing the points evenly on every
    # frame (what this used to do) made them crawl along the edge whenever the outline
    # changed shape, so nothing in Nuke stayed on the same part of the actor.
    RELAX = 0.05  # pull towards even spacing per frame: stops bunching, keeps correspondence

    @staticmethod
    def dense_flow(prev_gray, curr_gray, width=960):
        """Optical flow (x, y per pixel) at full size, computed at up to `width` for speed."""
        h, w = prev_gray.shape
        scale = min(1.0, width / w)
        a = cv2.resize(prev_gray, (int(w * scale), int(h * scale))) if scale < 1 else prev_gray
        b = cv2.resize(curr_gray, (int(w * scale), int(h * scale))) if scale < 1 else curr_gray
        flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 4, 21, 3, 5, 1.2, 0)
        if scale < 1:
            flow = cv2.resize(flow, (w, h)) / scale
        return flow

    @staticmethod
    def track_points(pts, flow, matte, inset=8.0):
        """Move points with the motion measured `inset` px inside the object (its edge mixes in background)."""
        h, w = matte.shape
        tangent = np.roll(pts, -1, axis=0) - np.roll(pts, 1, axis=0)
        tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-6)
        normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)

        def sample(img, q):
            x = np.clip(np.round(q[:, 0]).astype(int), 0, w - 1)
            y = np.clip(np.round(q[:, 1]).astype(int), 0, h - 1)
            return img[y, x]

        inside = np.where((sample(matte, pts + normal * inset) >= sample(matte, pts - normal * inset))[:, None],
                          normal, -normal)
        return pts + sample(flow, pts + inside * inset)

    @staticmethod
    def _dense_outline(cnt, spacing=1.0):
        """The outline as closely spaced points plus their arc position."""
        c = cnt.reshape(-1, 2).astype(np.float32)
        closed = np.vstack([c, c[:1]])
        seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
        cum = np.concatenate([[0], np.cumsum(seg)])
        total = float(cum[-1])
        if total <= 0:
            return c[:1], np.zeros(1), 0.0
        s_new = np.arange(0, total, spacing)
        x = np.interp(s_new, cum, closed[:, 0])
        y = np.interp(s_new, cum, closed[:, 1])
        return np.stack([x, y], axis=1), s_new, total

    def _conform_to_contour(self, tracked_pts, prev_pts, status, cnt, img_w, img_h):
        """Put the tracked points on the new outline: nearest spot, same order, gently re-spaced."""
        n = len(tracked_pts)
        if n < 3 or len(cnt) < 3:
            return tracked_pts
        outline, arc, total = self._dense_outline(cnt)
        if total <= 0:
            return tracked_pts
        # Walk the outline the same way round as the points.
        area_pts = cv2.contourArea(prev_pts.astype(np.float32).reshape(-1, 1, 2), oriented=True)
        area_out = cv2.contourArea(outline.astype(np.float32).reshape(-1, 1, 2), oriented=True)
        if np.sign(area_pts) != np.sign(area_out) and area_pts != 0:
            outline, arc = outline[::-1].copy(), total - arc[::-1]

        # Nearest outline position for every point (in blocks, the outline can be long).
        s = np.empty(n, np.float64)
        for i in range(0, n, 64):
            d = np.linalg.norm(tracked_pts[i:i + 64, None, :] - outline[None, :, :], axis=2)
            s[i:i + 64] = arc[np.argmin(d, axis=1)]

        # Same order as before: positions relative to point 0, never going backwards.
        rel = np.mod(s - s[0], total)
        min_gap = 0.25 * total / n
        for i in range(1, n):
            rel[i] = max(rel[i], rel[i - 1] + min_gap)
        if rel[-1] > total - min_gap:  # squeezed past the start: spread the overflow back evenly
            rel = rel * ((total - min_gap) / rel[-1])

        # A gentle pull towards the curvature-weighted spacing the shape was created with.
        target = self._resample_polygon(cnt, n, curvature_weight=5.0, frame_size=(img_w, img_h))
        t_s = np.array([arc[np.argmin(np.linalg.norm(outline - q, axis=1))] for q in target])
        t_rel = np.sort(np.mod(t_s - s[0], total))  # the i-th target spacing pairs with the i-th point
        blended = (1 - self.RELAX) * rel + self.RELAX * (t_rel - t_rel[0])
        pos = np.mod(s[0] + blended, total)
        x = np.interp(pos, arc, outline[:, 0], period=total)
        y = np.interp(pos, arc, outline[:, 1], period=total)
        placed = np.stack([x, y], axis=1).astype(np.float32)
        if self._covers(placed, cnt) >= self.MIN_COVER:
            return placed
        # The outline changed too much for the points to follow (a body part whose region
        # jumped): spread them evenly again, lined up with the previous frame. One small jump
        # is better than a shape that no longer covers its part.
        return self._evenly_aligned(target, tracked_pts)

    MIN_COVER = 0.92

    @staticmethod
    def _covers(pts, cnt):
        """IoU of the polygon through `pts` with the filled contour, at up to 256 px (fast)."""
        c = cnt.reshape(-1, 2).astype(np.float32)
        x0, y0 = np.minimum(c.min(axis=0), pts.min(axis=0))
        x1, y1 = np.maximum(c.max(axis=0), pts.max(axis=0))
        scale = 256.0 / max(x1 - x0, y1 - y0, 1.0)
        size = (int((y1 - y0) * scale) + 3, int((x1 - x0) * scale) + 3)
        a, b = np.zeros(size, np.uint8), np.zeros(size, np.uint8)
        cv2.fillPoly(a, [np.round((pts - [x0, y0]) * scale + 1).astype(np.int32)], 1)
        cv2.fillPoly(b, [np.round((c - [x0, y0]) * scale + 1).astype(np.int32)], 1)
        union = (a | b).sum()
        return float((a & b).sum() / union) if union else 1.0

    @staticmethod
    def _evenly_aligned(resampled, reference):
        """`resampled` rotated (cyclically) to line up best with `reference`."""
        n = len(resampled)
        centred = reference - reference.mean(axis=0) + resampled.mean(axis=0)
        costs = [np.mean(np.linalg.norm(np.roll(resampled, -k, axis=0) - centred, axis=1)) for k in range(n)]
        return np.roll(resampled, -int(np.argmin(costs)), axis=0).astype(np.float32)


    def run_task(self):
        self.log_message.emit(self.node_id, "Initializing Roto to Shape processing...")
        from plugins.RotoToShape import body_parts as bp
        body = str(self.params.get("mode", "Outline (any object)")).startswith("Body")
        part_points = {"Torso": int(self.params.get("points_torso", 60)),
                       "Head": int(self.params.get("points_head", 30))}
        limb_points = int(self.params.get("points_limb", 30))
        depth_map, convention = bp.depth_frames(getattr(self, "depth_path", None)) if body else ({}, None)
        
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
        
        # SuperMatte writes one matte per layer to alpha/<layer>/ next to its combined Matte/ folder;
        # each layer becomes its own set of shapes.
        layers_to_process = []
        alpha_dir = os.path.join(os.path.dirname(os.path.normpath(self.mask_path)), "alpha")
        if os.path.isdir(alpha_dir):
            for item in sorted(os.listdir(alpha_dir)):
                item_path = os.path.join(alpha_dir, item)
                if os.path.isdir(item_path) and any(f.lower().endswith(".png") for f in os.listdir(item_path)):
                    layers_to_process.append({"name": item, "dir": item_path})
        
        if not layers_to_process:
            layers_to_process.append({"name": "Shapes", "dir": self.mask_path})
            
        self.log_message.emit(self.node_id, f"Found {len(layers_to_process)} layers to process.")
        
        all_shapes = {}
        
        for layer_info in layers_to_process:
            layer_name = layer_info["name"]
            layer_dir = layer_info["dir"]
            
            self.log_message.emit(self.node_id, f"Processing layer: {layer_name}")
            
            from utvfx.core.plate import find_sequence
            sequence = find_sequence(layer_dir)  # sorted by frame number, not by name
            if self.frame_range:
                sequence = [sequence[i] for i in self.positions(len(sequence))]
            # First/Last frame are plate frame numbers; 0 means no limit.
            sequence = [(n, f) for n, f in sequence
                        if (first_frame <= 0 or n >= first_frame) and (last_frame <= 0 or n <= last_frame)]
            frames = [os.path.basename(f) for _, f in sequence]
                
            total_frames = len(frames)
            if total_frames == 0:
                continue
                
            active_shapes = {}
            lost_shapes_count = {}
            next_shape_id = 0
            all_known_shapes_pool = {}
            plate_frames = {}
            if self.media_path and os.path.isdir(self.media_path):
                plate_frames = dict(find_sequence(self.media_path))
            
            prev_gray = None
            prev_matte = None
            skeletons, layer_body = {}, body
            if body:
                from utvfx.core.image_utils import load_frame
                numbers = [n for n, _ in sequence]
                self.log_message.emit(self.node_id, f"Finding the skeleton of {layer_name} on {len(numbers)} frames...")
                found = bp.detect_skeletons([(n, plate_frames[n]) for n in numbers if n in plate_frames],
                                            lambda path: load_frame(path), cancelled=lambda: self.is_cancelled)
                if not found:
                    self.log_message.emit(self.node_id, f"No person found in {layer_name}; using outline mode for it.")
                    layer_body = False
                else:
                    skeletons = bp.fill_and_smooth(found, numbers)
                    self.log_message.emit(self.node_id, f"Skeleton found on {len(found)} of {len(numbers)} frames.")
                    if not depth_map:
                        self.log_message.emit(self.node_id, "No depth map wired: every part stays visible.")
                occlusion = bp.Occlusion(float(self.params.get("hide_behind", 0.08)),
                                         float(self.params.get("show_again", 0.04)))
            
            for i, f_name in enumerate(frames):
                if self.is_cancelled:
                    return
                    
                match = re.search(r'(\d+)\.\w+$', f_name)
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
                
                edge_placement = int(self.params.get("edge_placement", 50))
                # Map 0 (Soft edge) to threshold 10, and 100 (Hard edge) to threshold 245
                edge_threshold = int(10 + (edge_placement / 100.0) * 235)
                _, thresh = cv2.threshold(img, edge_threshold, 255, cv2.THRESH_BINARY)
                
                generate_feather = self.params.get("generate_feather", True)
                
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
                
                # Optical flow / Image prep
                curr_gray = None
                if f_idx in plate_frames:
                    from utvfx.core.image_utils import load_frame
                    media_img = load_frame(plate_frames[f_idx])
                    if media_img is not None:
                        curr_gray = cv2.cvtColor(media_img[..., :3], cv2.COLOR_BGR2GRAY)
                        if curr_gray.shape != img.shape:
                            curr_gray = cv2.resize(curr_gray, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_AREA)
                if curr_gray is None:
                    curr_gray = cv2.GaussianBlur(img, (15, 15), 0)
                    
                frame_flow = None  # computed once per frame, when a shape needs it

                if layer_body:
                    img_h, img_w = img.shape
                    matte = thresh > 0
                    skeleton = skeletons.get(f_idx)
                    parts = bp.split(matte, skeleton, min_area) if skeleton else {}
                    depths = {}
                    if f_idx in depth_map:
                        depth = bp.read_depth(depth_map[f_idx], convention)
                        if depth is not None:
                            if depth.shape != matte.shape:
                                depth = cv2.resize(depth, (img_w, img_h), interpolation=cv2.INTER_NEAREST)
                            depths = bp.part_depths(parts, depth, matte)
                    for name, cnt in parts.items():
                        sid = f"{layer_name}/{name}"
                        if sid in active_shapes and prev_gray is not None:
                            if frame_flow is None:
                                frame_flow = self.dense_flow(prev_gray, curr_gray)
                            prev_np = np.array(active_shapes[sid], np.float32)[:, :2]
                            tracked = self.track_points(prev_np.copy(), frame_flow, prev_matte)
                            pts = self._conform_to_contour(tracked, prev_np, None, cnt, img_w, img_h)
                        else:
                            pts = self._resample_polygon(cnt, part_points.get(name, limb_points), curvature_weight,
                                                         (img_w, img_h))
                        pts = self._snap_to_gradient(pts, grad_mag, edge_snap_radius, img=img,
                                                     core_threshold=(240 if generate_feather else 0))
                        behind = None
                        if name != "Torso" and name in depths and "Torso" in depths:
                            behind = bp.behind_amount(depths[name], depths["Torso"], convention)
                        entry = {"points": (np.hstack([pts, self._calculate_feather(pts, img, threshold=5, max_dist=100)])
                                            if generate_feather else pts).tolist(),
                                 "opacity": occlusion.update(name, behind)}
                        if name in depths:
                            entry["average_depth"] = depths[name]
                        current_frame_shapes[sid] = entry
                    # A part not found on this frame keeps its keys, invisible, so Nuke's shape holds.
                    for sid, prev_pts in active_shapes.items():
                        if sid not in current_frame_shapes:
                            current_frame_shapes[sid] = {"points": prev_pts, "opacity": 0.0}
                
                for shape_id, prev_pts in ([] if layer_body else active_shapes.items()):
                    prev_pts_np = np.array(prev_pts, dtype=np.float32)
                    main_pts_np = np.ascontiguousarray(prev_pts_np[:, :2]).reshape(-1, 1, 2)
                    
                    best_cnt_idx = -1
                    best_score = -1.0
                    
                    if prev_gray is not None:
                        if frame_flow is None:
                            frame_flow = self.dense_flow(prev_gray, curr_gray)
                        next_pts = self.track_points(prev_pts_np[:, :2].copy(), frame_flow, prev_matte)
                        status = np.ones((len(next_pts), 1), np.uint8)
                        status_flat = status.reshape(-1)
                        valid_idx = (status_flat == 1) & ~np.isnan(next_pts[:, 0]) & ~np.isnan(next_pts[:, 1]) & (next_pts[:, 0] >= 0) & (next_pts[:, 0] < grad_mag.shape[1]) & (next_pts[:, 1] >= 0) & (next_pts[:, 1] < grad_mag.shape[0])
                        valid_next = next_pts[valid_idx] if np.sum(valid_idx) >= 4 else next_pts
                        
                        x_min, y_min = np.min(valid_next, axis=0)
                        x_max, y_max = np.max(valid_next, axis=0)
                        tracked_bbox = (x_min, y_min, x_max - x_min, y_max - y_min)
                        
                        prev_main = prev_pts_np[:, :2]
                        px_min, py_min = np.min(prev_main, axis=0)
                        px_max, py_max = np.max(prev_main, axis=0)
                        prev_bbox = (px_min, py_min, px_max - px_min, py_max - py_min)
                        
                        for c_idx, cnt in enumerate(valid_contours):
                            if c_idx in used_contours: continue
                            iou_trk = bbox_iou(tracked_bbox, valid_bboxes[c_idx])
                            iou_prv = bbox_iou(prev_bbox, valid_bboxes[c_idx])
                            iou = max(iou_trk, iou_prv)
                            
                            dist_trk = bbox_center_dist(tracked_bbox, valid_bboxes[c_idx])
                            dist_prv = bbox_center_dist(prev_bbox, valid_bboxes[c_idx])
                            dist = min(dist_trk, dist_prv)
                            
                            max_dim = max(tracked_bbox[2], tracked_bbox[3], prev_bbox[2], prev_bbox[3], valid_bboxes[c_idx][2], valid_bboxes[c_idx][3])
                            dist_score = max(0, 1.0 - dist / (max_dim + 1e-5))
                            score = max(iou, dist_score)
                            
                            if score > best_score:
                                best_score = score
                                best_cnt_idx = c_idx
                                
                        if best_cnt_idx != -1 and best_score >= iou_threshold:
                            used_contours.add(best_cnt_idx)
                            
                            matched_cnt = valid_contours[best_cnt_idx]
                            img_h, img_w = grad_mag.shape
                            conformed_pts = self._conform_to_contour(next_pts, prev_pts_np[:, :2], status, matched_cnt, img_w, img_h)
                            snapped_pts = self._snap_to_gradient(conformed_pts, grad_mag, edge_snap_radius, img=img, core_threshold=(240 if generate_feather else 0))
                            
                            if generate_feather:
                                feather_pts = self._calculate_feather(snapped_pts, img, threshold=5, max_dist=100)
                                combined = np.hstack([snapped_pts, feather_pts])
                                current_frame_shapes[shape_id] = {"points": combined.tolist(), "opacity": 1.0}
                            else:
                                current_frame_shapes[shape_id] = {"points": snapped_pts.tolist(), "opacity": 1.0}
                                
                            lost_shapes_count[shape_id] = 0
                        else:
                            lost_shapes_count[shape_id] = lost_shapes_count.get(shape_id, 0) + 1
                            if lost_shapes_count[shape_id] <= max_missing_frames:
                                next_pts[:, 0] = np.clip(next_pts[:, 0], 0, grad_mag.shape[1] - 1)
                                next_pts[:, 1] = np.clip(next_pts[:, 1], 0, grad_mag.shape[0] - 1)
                                if generate_feather:
                                    dummy_feather = np.copy(next_pts)
                                    combined_lost = np.hstack([next_pts, dummy_feather])
                                    current_frame_shapes[shape_id] = {"points": combined_lost.tolist(), "opacity": 0.0}
                                else:
                                    current_frame_shapes[shape_id] = {"points": next_pts.tolist(), "opacity": 0.0}
                    else:
                        pass
                            
                for c_idx, cnt in enumerate([] if layer_body else valid_contours):
                    if c_idx not in used_contours:
                        if epsilon > 0:
                            cnt = cv2.approxPolyDP(cnt, epsilon, True)
                        perimeter = cv2.arcLength(cnt, True)
                        num_points = max(8, int(perimeter / auto_point_spacing)) if point_mode == "Auto (Adaptive)" else target_points
                        if point_mode == "Auto (Adaptive)":
                            num_points = min(num_points, 80)
                        frame_size = (all_shapes["format_width"], all_shapes["format_height"])
                        resampled = self._resample_polygon(cnt, num_points, curvature_weight, frame_size)
                        resampled = self._snap_to_gradient(resampled, grad_mag, edge_snap_radius, img=img, core_threshold=(240 if generate_feather else 0))
                        
                        prefix = "Hole" if valid_is_hole[c_idx] else "Shape"
                        reused_id = None
                        best_pool_dist = float('inf')
                        cnt_centroid = np.mean(resampled, axis=0)
                        cnt_size = float(np.max(np.ptp(resampled, axis=0)))
                        for pool_sid, pool_pts in all_known_shapes_pool.items():
                            if pool_sid not in current_frame_shapes and f"/{prefix}_" in pool_sid:
                                dist = np.linalg.norm(cnt_centroid - np.mean(pool_pts, axis=0))
                                # Only the same object coming back: close to where it was lost.
                                reach = max(cnt_size, float(np.max(np.ptp(pool_pts, axis=0))))
                                if dist < best_pool_dist and dist <= reach:
                                    best_pool_dist = dist
                                    reused_id = pool_sid
                        if reused_id is not None:
                            shape_id = reused_id
                            # Nuke keys every point of a shape: a reused shape keeps its point count.
                            count = len(all_known_shapes_pool[reused_id])
                            if count != len(resampled):
                                resampled = self._resample_polygon(cnt, count, curvature_weight, frame_size)
                                resampled = self._snap_to_gradient(resampled, grad_mag, edge_snap_radius, img=img,
                                                                   core_threshold=(240 if generate_feather else 0))
                        else:
                            shape_id = f"{layer_name}/{prefix}_{next_shape_id}"
                            next_shape_id += 1
                        
                        if generate_feather:
                            feather_pts = self._calculate_feather(resampled, img, threshold=5, max_dist=100)
                            combined = np.hstack([resampled, feather_pts])
                            current_frame_shapes[shape_id] = {"points": combined.tolist(), "opacity": 1.0}
                        else:
                            current_frame_shapes[shape_id] = {"points": resampled.tolist(), "opacity": 1.0}
                            
                        lost_shapes_count[shape_id] = 0
                        
                for sid, val in current_frame_shapes.items():
                    if val.get("opacity", 1.0) > 0:
                        all_known_shapes_pool[sid] = np.array(val["points"], dtype=np.float32)[:, :2]
                        
                active_shapes = {sid: val["points"] for sid, val in current_frame_shapes.items()}
                all_shapes[f_idx_str].update(current_frame_shapes)
                prev_gray = curr_gray
                prev_matte = img
                
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
                for sid, val in all_shapes[f_str].items():
                    pts = val["points"] if isinstance(val, dict) else val
                    opacity = val.get("opacity", 1.0) if isinstance(val, dict) else 1.0
                    
                    pts_np = np.array(pts)
                    num_pts = len(pts_np)
                    
                    smoothed_pts = pts_np
                    
                    idx = frames_present.index(f_idx)
                    if idx > 0 and idx < len(frames_present) - 1:
                        prev_f = str(frames_present[idx - 1])
                        next_f = str(frames_present[idx + 1])
                        if sid in all_shapes[prev_f] and sid in all_shapes[next_f]:
                            pts_prev = np.array(all_shapes[prev_f][sid]["points"] if isinstance(all_shapes[prev_f][sid], dict) else all_shapes[prev_f][sid])
                            pts_next = np.array(all_shapes[next_f][sid]["points"] if isinstance(all_shapes[next_f][sid], dict) else all_shapes[next_f][sid])
                            if len(pts_prev) == num_pts and len(pts_next) == num_pts and pts_prev.shape == pts_np.shape and pts_next.shape == pts_np.shape:
                                dist_prev = np.mean(np.linalg.norm(pts_prev - pts_np, axis=1))
                                dist_next = np.mean(np.linalg.norm(pts_next - pts_np, axis=1))
                                if dist_prev < 20 and dist_next < 20:
                                    smoothed_pts = (pts_prev + pts_np + pts_next) / 3.0
                    
                    smoothed_shapes[f_str][sid] = dict(val, points=smoothed_pts.tolist(), opacity=opacity) \
                        if isinstance(val, dict) else {"points": smoothed_pts.tolist(), "opacity": opacity}
            
            all_shapes = smoothed_shapes
            
        # --- Format Y-flip and Cusp Detection ---
        format_h = all_shapes.get("format_height", 1080)
        
        corner_threshold = float(self.params.get("corner_threshold", 45))
        corner_rad = np.radians(corner_threshold)
        
        frames_present = sorted([int(k) for k in all_shapes.keys() if str(k).isdigit()])
        for f_idx in frames_present:
            f_str = str(f_idx)
            for sid, val in all_shapes[f_str].items():
                pts = val["points"] if isinstance(val, dict) else val
                opacity = val.get("opacity", 1.0) if isinstance(val, dict) else 1.0
                pts_np = np.array(pts, dtype=np.float32)
                has_feather = pts_np.shape[1] == 4
                main_pts = pts_np[:, :2]
                
                pts_with_type = []
                if len(main_pts) > 2:
                    pts_rolled_fwd = np.roll(main_pts, -1, axis=0)
                    pts_rolled_bck = np.roll(main_pts, 1, axis=0)
                    v1 = main_pts - pts_rolled_bck
                    v2 = pts_rolled_fwd - main_pts
                    n1 = np.linalg.norm(v1, axis=1, keepdims=True)
                    n2 = np.linalg.norm(v2, axis=1, keepdims=True)
                    n1[n1 == 0] = 1.0
                    n2[n2 == 0] = 1.0
                    dot = np.sum((v1 / n1) * (v2 / n2), axis=1)
                    dot = np.clip(dot, -1.0, 1.0)
                    angle = np.arccos(dot)
                else:
                    angle = np.zeros(len(main_pts))
                    
                # Image pixel (x, y) covers [x, x+1) from the top; in Nuke its centre is
                # (x + 0.5, height - y - 0.5) with the origin at the bottom left.
                for j, pt in enumerate(main_pts):
                    curve_type = "cusp" if angle[j] > corner_rad else "smooth"
                    x, y_flipped = float(pt[0]) + 0.5, float(format_h - pt[1]) - 0.5
                    if has_feather:
                        fx, fy_flipped = float(pts_np[j, 2]) + 0.5, float(format_h - pts_np[j, 3]) - 0.5
                        pts_with_type.append([x, y_flipped, curve_type, fx, fy_flipped])
                    else:
                        pts_with_type.append([x, y_flipped, curve_type])
                    
                all_shapes[f_str][sid] = dict(val, points=pts_with_type, opacity=opacity) \
                    if isinstance(val, dict) else {"points": pts_with_type, "opacity": opacity}

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
                            
                        for sid, val in all_shapes[str(f_idx)].items():
                            pts_with_type = val["points"] if isinstance(val, dict) else val
                            opacity = val.get("opacity", 1.0) if isinstance(val, dict) else 1.0
                            if opacity == 0.0:
                                continue
                            is_hole = "Hole_" in sid.split('/')[-1]
                            color = (0, 0, 255) if is_hole else (0, 255, 0)
                            
                            # unflip Y just for preview
                            draw_pts = np.array([[pt[0] - 0.5, format_h - pt[1] - 0.5] for pt in pts_with_type], dtype=np.int32)
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

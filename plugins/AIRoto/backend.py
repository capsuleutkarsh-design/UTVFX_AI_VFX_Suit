import os
import json
import re
import cv2
import numpy as np
from PySide6.QtCore import Signal
import mediapipe as mp

from utvfx.bridge.base_worker import BaseWorker

def distance_to_segment_vectorized(pts, j1, j2):
    v = j2 - j1
    v_len_sq = np.dot(v, v)
    if v_len_sq == 0:
        return np.linalg.norm(pts - j1, axis=1)
    w = pts - j1
    t = np.sum(w * v, axis=1) / v_len_sq
    t = np.clip(t, 0.0, 1.0)
    projection = j1 + t[:, np.newaxis] * v
    return np.linalg.norm(pts - projection, axis=1)

def get_contour_winding(contour):
    return cv2.contourArea(contour, oriented=True) < 0

def resample_polygon_segment(pts, num_points):
    if len(pts) < 2:
        if len(pts) == 1:
            return np.repeat(pts, num_points, axis=0)
        return np.zeros((num_points, 2), dtype=np.float32)
        
    diffs = np.diff(pts, axis=0)
    dists = np.linalg.norm(diffs, axis=1)
    cum_dists = np.concatenate([[0], np.cumsum(dists)])
    
    total_len = cum_dists[-1]
    if total_len == 0:
        return np.repeat(pts[0:1], num_points, axis=0)
        
    target_dists = np.linspace(0, total_len, num_points)
    xs = np.interp(target_dists, cum_dists, pts[:, 0])
    ys = np.interp(target_dists, cum_dists, pts[:, 1])
    return np.column_stack([xs, ys]).astype(np.float32)

def clip_val(val, min_v, max_v):
    return max(min_v, min(max_v, val))

class AIRotoWorker(BaseWorker):
    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(node_id, params, inputs, cache_dir, output_dir, parent)
        self.video_path = inputs.get("Video Plate")
        self.matte_path = inputs.get("Alpha Matte")
        self.depth_path = inputs.get("Depth Map")

    def cancel(self):
        self.is_cancelled = True

    def _parse_bool(self, val):
        if isinstance(val, bool): return val
        if isinstance(val, str): return val.lower() in ('true', '1', 'yes')
        return bool(val)

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

    def run_task(self):
        if not self.video_path or not os.path.exists(self.video_path):
            self.log_message.emit(self.node_id, "[ERROR] Missing Video Plate input path.")
            return
        if not self.matte_path or not os.path.exists(self.matte_path):
            self.log_message.emit(self.node_id, "[ERROR] Missing Alpha Matte input path.")
            return
        if not self.depth_path or not os.path.exists(self.depth_path):
            self.log_message.emit(self.node_id, "[ERROR] Missing Depth Map input path.")
            return

        out_dir = os.path.join(self.cache_dir, "roto_shapes")
        os.makedirs(out_dir, exist_ok=True)
        
        # Layer discovery
        layers_to_process = []
        sam_masks_dir = os.path.join(os.path.dirname(self.matte_path), "sam_masks")
        if os.path.isdir(sam_masks_dir):
            for item in os.listdir(sam_masks_dir):
                item_path = os.path.join(sam_masks_dir, item)
                if os.path.isdir(item_path):
                    layers_to_process.append({"name": item, "dir": item_path})
        
        if not layers_to_process:
            layers_to_process.append({"name": "Shapes", "dir": self.matte_path})
            
        self.log_message.emit(self.node_id, f"Found {len(layers_to_process)} layers to process in AI Roto.")
        
        # Frame matching across video, depth, and layers
        vid_files = sorted([f for f in os.listdir(self.video_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.exr'))])
        depth_files = sorted([f for f in os.listdir(self.depth_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.exr', '.tif'))])
        
        def get_frame_num(fname):
            match = re.search(r'(?:_|)(\d+)\.\w+$', fname)
            return int(match.group(1)) if match else -1
            
        vid_map = {get_frame_num(f): f for f in vid_files if get_frame_num(f) != -1}
        depth_map = {get_frame_num(f): f for f in depth_files if get_frame_num(f) != -1}
        
        if not vid_map:
            for i, f in enumerate(vid_files): vid_map[i] = f
        if not depth_map:
            for i, f in enumerate(depth_files): depth_map[i] = f

        first_vid_frame = os.path.join(self.video_path, vid_files[0])
        img_temp = cv2.imread(first_vid_frame)
        if img_temp is None:
            self.log_message.emit(self.node_id, "[ERROR] Failed to read first video frame.")
            return
        height, width = img_temp.shape[:2]
        diag = np.sqrt(width**2 + height**2)
        seam_buffer = max(2.0, 0.0015 * diag)
        
        target_pts_limb = int(self.params.get("target_points_limb", 30))
        target_pts_torso = int(self.params.get("target_points_torso", 60))
        target_pts_head = int(self.params.get("target_points_head", 30))
        corner_threshold = float(self.params.get("corner_threshold", 45))
        corner_rad = np.radians(corner_threshold)
        edge_snap_radius = int(self.params.get("edge_snap_radius", 2))
        temporal_smoothing = self._parse_bool(self.params.get("temporal_smoothing", True))
        h_low = float(self.params.get("hysteresis_low", 0.15))
        h_high = float(self.params.get("hysteresis_high", 0.25))
        flow_decay = float(self.params.get("flow_decay", 0.05))
        first_frame_param = int(self.params.get("first_frame", 0))
        last_frame_param = int(self.params.get("last_frame", 0))

        all_shapes_data = {
            "format_width": width,
            "format_height": height
        }
        
        from mediapipe.python.solutions import pose as mp_pose
        
        bones = {
            "L_Upper_Arm": (11, 13, target_pts_limb),
            "L_Forearm": (13, 15, target_pts_limb),
            "R_Upper_Arm": (12, 14, target_pts_limb),
            "R_Forearm": (14, 16, target_pts_limb),
            "L_Thigh": (23, 25, target_pts_limb),
            "L_Calf": (25, 27, target_pts_limb),
            "R_Thigh": (24, 26, target_pts_limb),
            "R_Calf": (26, 28, target_pts_limb),
            "Head": ("neck", 0, target_pts_head)
        }
        bone_keys = list(bones.keys())

        for layer_info in layers_to_process:
            layer_name = layer_info["name"]
            layer_dir = layer_info["dir"]
            self.log_message.emit(self.node_id, f"Processing layer: {layer_name}")
            
            frames = sorted([f for f in os.listdir(layer_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.exr'))])
            if not frames: continue
            
            frame_indices = []
            layer_map = {}
            for i, f_name in enumerate(frames):
                f_idx = get_frame_num(f_name)
                if f_idx == -1: f_idx = i
                
                if first_frame_param > 0 and f_idx < first_frame_param:
                    continue
                if last_frame_param > 0 and f_idx > last_frame_param:
                    continue
                    
                frame_indices.append(f_idx)
                layer_map[f_idx] = f_name
                
            self.log_message.emit(self.node_id, f"Step 1/5: Pre-scanning {layer_name} for skeletal landmarks...")
            raw_landmarks = {}
            
            pose_detector = mp_pose.Pose(static_image_mode=False, min_detection_confidence=0.5, model_complexity=1)
            
            for f_idx in frame_indices:
                if self.is_cancelled: return
                
                if f_idx not in vid_map:
                    raw_landmarks[f_idx] = None
                    continue
                    
                vid_path = os.path.join(self.video_path, vid_map[f_idx])
                img_bgr = cv2.imread(vid_path)
                if img_bgr is None:
                    raw_landmarks[f_idx] = None
                    continue
                    
                img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
                
                # We do NOT mask img_rgb with the layer matte here because MediaPipe needs the full body
                # to reliably detect the skeleton. Using an isolated limb matte causes detection failure.
                
                results = pose_detector.process(img_rgb)
                
                if results.pose_landmarks:
                    lmarks = {}
                    for idx, lm in enumerate(results.pose_landmarks.landmark):
                        lmarks[idx] = np.array([lm.x * width, lm.y * height], dtype=np.float32)
                    raw_landmarks[f_idx] = lmarks
                else:
                    raw_landmarks[f_idx] = None
                    
            pose_detector.close()
            
            self.log_message.emit(self.node_id, f"Step 2/5: Resolving {layer_name} joint dropouts...")
            interpolated_landmarks = {}
            
            for joint_id in range(33):
                valid_indices = [idx for idx in frame_indices if raw_landmarks[idx] is not None and joint_id in raw_landmarks[idx]]
                
                if not valid_indices:
                    for idx in frame_indices:
                        if idx not in interpolated_landmarks: interpolated_landmarks[idx] = {}
                        interpolated_landmarks[idx][joint_id] = np.array([width / 2.0, height / 2.0], dtype=np.float32)
                    continue
                    
                for idx in frame_indices:
                    if idx not in interpolated_landmarks: interpolated_landmarks[idx] = {}
                    
                    if idx in valid_indices:
                        interpolated_landmarks[idx][joint_id] = raw_landmarks[idx][joint_id]
                    else:
                        prev_v = [v for v in valid_indices if v < idx]
                        next_v = [v for v in valid_indices if v > idx]
                        
                        if not prev_v:
                            interpolated_landmarks[idx][joint_id] = raw_landmarks[next_v[0]][joint_id]
                        elif not next_v:
                            interpolated_landmarks[idx][joint_id] = raw_landmarks[prev_v[-1]][joint_id]
                        else:
                            p_idx = prev_v[-1]
                            n_idx = next_v[0]
                            factor = (idx - p_idx) / (n_idx - p_idx)
                            p_val = raw_landmarks[p_idx][joint_id]
                            n_val = raw_landmarks[n_idx][joint_id]
                            interpolated_landmarks[idx][joint_id] = p_val + factor * (n_val - p_val)

            self.log_message.emit(self.node_id, f"Step 3/5: Running anatomical partition for {layer_name}...")
            
            prev_anchors = {}
            prev_raw_shapes = {}
            opacities = {}
            prev_img_gray = None
            dropout_streak = 0
            
            for i, f_idx in enumerate(frame_indices):
                if self.is_cancelled: return
                self.progress_update.emit(self.node_id, i + 1, len(frame_indices))
                
                f_idx_str = str(f_idx)
                if f_idx_str not in all_shapes_data:
                    all_shapes_data[f_idx_str] = {}
                
                matte_path = os.path.join(layer_dir, layer_map[f_idx])
                matte_img = cv2.imread(matte_path, cv2.IMREAD_GRAYSCALE)
                
                if f_idx not in depth_map: continue
                depth_img = cv2.imread(os.path.join(self.depth_path, depth_map[f_idx]), cv2.IMREAD_UNCHANGED)
                if depth_img is not None and depth_img.shape[:2] != (height, width):
                    depth_img = cv2.resize(depth_img, (width, height), interpolation=cv2.INTER_NEAREST)
                
                if matte_img is None or depth_img is None: continue
                
                grad_x = cv2.Sobel(matte_img, cv2.CV_32F, 1, 0, ksize=3)
                grad_y = cv2.Sobel(matte_img, cv2.CV_32F, 0, 1, ksize=3)
                grad_mag = np.sqrt(grad_x**2 + grad_y**2)
                
                depth_float = depth_img.astype(np.float32)
                if depth_img.dtype == np.uint16: depth_float /= 65535.0
                
                joints = interpolated_landmarks[f_idx]
                joints["neck"] = 0.5 * (joints[11] + joints[12])
                torso_joints = [joints[11], joints[12], joints[24], joints[23]]
                
                is_dropout = raw_landmarks[f_idx] is None
                if is_dropout:
                    dropout_streak += 1
                else:
                    dropout_streak = 0
                    
                if dropout_streak > 15:
                    current_decay = 1.0
                else:
                    current_decay = min(1.0, dropout_streak * flow_decay)
                
                white_pts = np.column_stack(np.where(matte_img > 127))
                if len(white_pts) > 0:
                    white_pts = white_pts[:, [1, 0]].astype(np.float32)
                    
                current_frame_shapes = {}
                
                if is_dropout and prev_raw_shapes and prev_img_gray is not None and f_idx in vid_map:
                    vid_path = os.path.join(self.video_path, vid_map[f_idx])
                    curr_img_bgr = cv2.imread(vid_path)
                    curr_img_gray = cv2.cvtColor(curr_img_bgr, cv2.COLOR_BGR2GRAY) if curr_img_bgr is not None else None
                    
                    if curr_img_gray is not None:
                        flow = cv2.calcOpticalFlowFarneback(prev_img_gray, curr_img_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                        
                        prev_f_idx = frame_indices[max(0, i - 1)]
                        prev_joints = interpolated_landmarks[prev_f_idx]
                        curr_joints = interpolated_landmarks[f_idx]
                        
                        for name, prev_pts in prev_raw_shapes.items():
                            if name in bones:
                                ja_id, jb_id, _ = bones[name]
                                if name == "Head":
                                    ja_id, jb_id = "neck", 0
                                p_center = (prev_joints[ja_id] + prev_joints[jb_id]) / 2.0
                                c_center = (curr_joints[ja_id] + curr_joints[jb_id]) / 2.0
                                translation = c_center - p_center
                            elif name == "Torso":
                                p_center = np.mean([prev_joints[11], prev_joints[12], prev_joints[24], prev_joints[23]], axis=0)
                                c_center = np.mean([curr_joints[11], curr_joints[12], curr_joints[24], curr_joints[23]], axis=0)
                                translation = c_center - p_center
                            else:
                                translation = np.array([0, 0], dtype=np.float32)
                                
                            warped_pts = []
                            for pt in prev_pts:
                                px, py = int(clip_val(pt[0], 0, width-1)), int(clip_val(pt[1], 0, height-1))
                                fx, fy = flow[py, px]
                                flow_pt = np.array([pt[0] + fx, pt[1] + fy], dtype=np.float32)
                                rigid_pt = pt + translation
                                blended_pt = (1.0 - current_decay) * flow_pt + current_decay * rigid_pt
                                warped_pts.append(blended_pt)
                            current_frame_shapes[name] = np.array(warped_pts)
                        prev_img_gray = curr_img_gray
                else:
                    if f_idx in vid_map:
                        prev_img_gray = cv2.cvtColor(cv2.imread(os.path.join(self.video_path, vid_map[f_idx])), cv2.COLOR_BGR2GRAY)
                    
                    if len(white_pts) > 0:
                        dist_matrix = np.zeros((len(white_pts), 10), dtype=np.float32)
                        for idx, b_name in enumerate(bone_keys):
                            ja_id, jb_id, _ = bones[b_name]
                            dist_matrix[:, idx] = distance_to_segment_vectorized(white_pts, joints[ja_id], joints[jb_id])
                            
                        torso_dists = []
                        for k in range(4):
                            j1 = torso_joints[k]
                            j2 = torso_joints[(k + 1) % 4]
                            torso_dists.append(distance_to_segment_vectorized(white_pts, j1, j2))
                        dist_matrix[:, 9] = np.min(torso_dists, axis=0)
                        
                        closest_part_indices = np.argmin(dist_matrix, axis=1)
                        sorted_dists = np.sort(dist_matrix, axis=1)
                        
                        limb_pixels = {b_name: [] for b_name in bone_keys}
                        limb_pixels["Torso"] = []
                        
                        for idx in range(10):
                            name = bone_keys[idx] if idx < 9 else "Torso"
                            mask_closest = (closest_part_indices == idx)
                            mask_seam = (dist_matrix[:, idx] - sorted_dists[:, 0] <= seam_buffer)
                            combined_mask = mask_closest | mask_seam
                            if np.any(combined_mask):
                                limb_pixels[name] = white_pts[combined_mask]
                                
                        for idx in range(10):
                            name = bone_keys[idx] if idx < 9 else "Torso"
                            pixels = limb_pixels[name]
                            if len(pixels) == 0: continue
                            
                            limb_mask = np.zeros_like(matte_img)
                            ypix, xpix = pixels[:, 1].astype(np.int32), pixels[:, 0].astype(np.int32)
                            ypix = np.clip(ypix, 0, height - 1)
                            xpix = np.clip(xpix, 0, width - 1)
                            limb_mask[ypix, xpix] = 255
                            
                            morph_kernel = np.ones((5,5), np.uint8)
                            limb_mask = cv2.morphologyEx(limb_mask, cv2.MORPH_CLOSE, morph_kernel)
                            
                            contours, _ = cv2.findContours(limb_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                            if not contours: continue
                            main_contour = max(contours, key=cv2.contourArea).reshape(-1, 2)
                            if len(main_contour) < 3: continue
                            if get_contour_winding(main_contour): main_contour = main_contour[::-1]
                            
                            if name == "Torso":
                                anchors = []
                                for q_joint in torso_joints:
                                    dists = np.linalg.norm(main_contour - q_joint, axis=1)
                                    anchors.append(np.argmin(dists))
                                anchors.sort()
                                segs = []
                                for k in range(4):
                                    idx1 = anchors[k]
                                    idx2 = anchors[(k + 1) % 4]
                                    if idx2 > idx1: seg = main_contour[idx1:idx2+1]
                                    else: seg = np.concatenate([main_contour[idx1:], main_contour[:idx2+1]])
                                    segs.append(seg)
                                pts_per_seg = target_pts_torso // 4
                                resampled_segments = [resample_polygon_segment(seg, pts_per_seg) for seg in segs]
                                current_frame_shapes[name] = np.concatenate(resampled_segments, axis=0)
                            elif name == "Head":
                                ja_id, jb_id, t_pts = bones["Head"]
                                neck_pt = joints[ja_id]
                                nose_pt = joints[jb_id]
                                dist_neck = np.linalg.norm(main_contour - neck_pt, axis=1)
                                dist_nose = np.linalg.norm(main_contour - nose_pt, axis=1)
                                idx_start = np.argmin(dist_neck)
                                idx_end = np.argmin(dist_nose)
                                if idx_end > idx_start:
                                    seg1 = main_contour[idx_start:idx_end+1]
                                    seg2 = np.concatenate([main_contour[idx_end:], main_contour[:idx_start+1]])
                                else:
                                    seg1 = np.concatenate([main_contour[idx_start:], main_contour[:idx_end+1]])
                                    seg2 = main_contour[idx_end:idx_start+1]
                                pts_per_seg = t_pts // 2
                                current_frame_shapes["Head"] = np.concatenate([
                                    resample_polygon_segment(seg1, pts_per_seg),
                                    resample_polygon_segment(seg2, pts_per_seg)
                                ], axis=0)
                            else:
                                ja_id, jb_id, t_pts = bones[name]
                                ja_pt = joints[ja_id]
                                jb_pt = joints[jb_id]
                                bone_len = np.linalg.norm(jb_pt - ja_pt)
                                if bone_len < 0.03 * diag:
                                    dists = np.linalg.norm(main_contour - ja_pt, axis=1)
                                    idx_start = np.argmin(dists)
                                    rolled = np.roll(main_contour, -idx_start, axis=0)
                                    current_frame_shapes[name] = resample_polygon_segment(rolled, t_pts)
                                else:
                                    if name in prev_anchors:
                                        prev_start_anc, prev_end_anc = prev_anchors[name]
                                        idx_start = np.argmin(np.linalg.norm(main_contour - prev_start_anc, axis=1))
                                        idx_end = np.argmin(np.linalg.norm(main_contour - prev_end_anc, axis=1))
                                    else:
                                        idx_start = np.argmin(np.linalg.norm(main_contour - ja_pt, axis=1))
                                        idx_end = np.argmin(np.linalg.norm(main_contour - jb_pt, axis=1))
                                    prev_anchors[name] = (main_contour[idx_start].copy(), main_contour[idx_end].copy())
                                    if idx_end > idx_start:
                                        seg1 = main_contour[idx_start:idx_end+1]
                                        seg2 = np.concatenate([main_contour[idx_end:], main_contour[:idx_start+1]])
                                    else:
                                        seg1 = np.concatenate([main_contour[idx_start:], main_contour[:idx_end+1]])
                                        seg2 = main_contour[idx_end:idx_start+1]
                                    pts_per_seg = t_pts // 2
                                    current_frame_shapes[name] = np.concatenate([
                                        resample_polygon_segment(seg1, pts_per_seg),
                                        resample_polygon_segment(seg2, pts_per_seg)
                                    ], axis=0)
                
                if edge_snap_radius > 0 and len(current_frame_shapes) > 0:
                    for name, pts in current_frame_shapes.items():
                        snapped = self._snap_to_gradient(pts, grad_mag, edge_snap_radius)
                        current_frame_shapes[name] = snapped

                prev_raw_shapes = current_frame_shapes.copy()
                
                torso_avg_depth = 0.5
                if "Torso" in current_frame_shapes:
                    t_mask = np.zeros_like(matte_img)
                    cv2.drawContours(t_mask, [current_frame_shapes["Torso"].astype(np.int32)], -1, 255, -1)
                    torso_avg_depth = np.mean(depth_float[t_mask > 127]) if np.any(t_mask > 127) else 0.5
                    
                frame_data = {}
                for name, pts in current_frame_shapes.items():
                    s_mask = np.zeros_like(matte_img)
                    cv2.drawContours(s_mask, [pts.astype(np.int32)], -1, 255, -1)
                    avg_d = np.mean(depth_float[s_mask > 127]) if np.any(s_mask > 127) else torso_avg_depth
                    d_norm = avg_d - torso_avg_depth
                    
                    target_vis = 1.0
                    prev_vis = opacities.get(name, 1.0)
                    if d_norm > h_high: target_vis = 0.0
                    elif d_norm < h_low: target_vis = 1.0
                    else: target_vis = prev_vis
                    
                    if target_vis < prev_vis: current_vis = max(0.0, prev_vis - 0.2)
                    elif target_vis > prev_vis: current_vis = min(1.0, prev_vis + 0.2)
                    else: current_vis = target_vis
                        
                    opacities[name] = current_vis
                    
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
                        y_flipped = height - pt[1]
                        curve_type = "cusp" if angle[j] > corner_rad else "smooth"
                        pts_with_type.append([float(pt[0]), float(y_flipped), curve_type])
                        
                    shape_id = f"{layer_name}/{name}"
                    frame_data[shape_id] = {
                        "points": pts_with_type,
                        "opacity": current_vis,
                        "average_depth": float(avg_d)
                    }
                    
                all_shapes_data[f_idx_str].update(frame_data)
                
        if temporal_smoothing:
            self.log_message.emit(self.node_id, "Applying temporal rolling average smoothing...")
            frames_present = sorted([int(k) for k in all_shapes_data.keys() if str(k).isdigit()])
            
            all_sids = set()
            for f in frames_present:
                for sid in all_shapes_data[str(f)].keys():
                    all_sids.add(sid)
            
            for sid in all_sids:
                smoothed_for_sid = {}
                frames_for_sid = [f for f in frames_present if sid in all_shapes_data[str(f)]]
                if len(frames_for_sid) < 3: continue
                
                for idx, f in enumerate(frames_for_sid):
                    pts_curr = np.array([p[:2] for p in all_shapes_data[str(f)][sid]["points"]])
                    types = [p[2] for p in all_shapes_data[str(f)][sid]["points"]]
                    
                    if idx > 0 and idx < len(frames_for_sid) - 1:
                        f_prev = frames_for_sid[idx-1]
                        f_next = frames_for_sid[idx+1]
                        pts_prev = np.array([p[:2] for p in all_shapes_data[str(f_prev)][sid]["points"]])
                        pts_next = np.array([p[:2] for p in all_shapes_data[str(f_next)][sid]["points"]])
                        pts_curr = (pts_prev + pts_curr + pts_next) / 3.0
                        
                    smoothed_for_sid[str(f)] = [[float(pt[0]), float(pt[1]), types[j]] for j, pt in enumerate(pts_curr)]
                    
                for f in frames_for_sid:
                    if str(f) in smoothed_for_sid:
                        all_shapes_data[str(f)][sid]["points"] = smoothed_for_sid[str(f)]

        out_file = os.path.join(out_dir, "shapes.json")
        with open(out_file, "w") as f:
            json.dump(all_shapes_data, f, indent=2)
            
        self.log_message.emit(self.node_id, f"AI-Roto node execution complete! Shapes saved to {out_file}")

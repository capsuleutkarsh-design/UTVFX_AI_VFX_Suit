import os
import cv2
import numpy as np
import time
import shutil
from PySide6.QtCore import QThread, Signal
import torch
import torchvision

# For ViTMatte
from transformers import VitMatteImageProcessor, VitMatteForImageMatting

from utvfx.bridge.base_worker import BaseWorker

class SuperMatteWorker(BaseWorker):
    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(node_id, params, inputs, cache_dir, output_dir, parent)
        # The ExecutionEngine will pre-resolve media_path and pass it in inputs["Video Plate"]
        self.media_path = inputs.get("Video Plate")


    def track_points_pyrlk(self, img1, img2, pts_nxny):
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

    def generate_trimap(self, mask_uint8, erode_kernel_size, dilate_kernel_size):
        kernel_erode = np.ones((erode_kernel_size, erode_kernel_size), np.uint8)
        kernel_dilate = np.ones((dilate_kernel_size, dilate_kernel_size), np.uint8)
        
        eroded = cv2.erode(mask_uint8, kernel_erode, iterations=1)
        dilated = cv2.dilate(mask_uint8, kernel_dilate, iterations=1)
        
        trimap = np.full(mask_uint8.shape, 128, dtype=np.uint8)
                layer_dir = os.path.join(alpha_dir, layer_name)
                os.makedirs(layer_dir, exist_ok=True)
                out_alpha_path = os.path.join(layer_dir, f"alpha_{frame_idx:06d}.png")
                cv2.imwrite(out_alpha_path, alpha_uint8)
                
                combined_alpha = np.maximum(combined_alpha, alpha_uint8)
                
                # Clean up SAM temp mask
                os.remove(sam_mask_path)
            
            # --- Post-Processing Edge Controls ---
            if threshold_val != 128 or contrast != 100:
                c_factor = contrast / 100.0
                alpha_f = combined_alpha.astype(np.float32)
                alpha_f = (alpha_f - threshold_val) * c_factor + threshold_val
                combined_alpha = np.clip(alpha_f, 0, 255).astype(np.uint8)
                
            if shrink_grow != 0:
                kernel_size = abs(shrink_grow) * 2 + 1
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
                if shrink_grow > 0:
                    combined_alpha = cv2.dilate(combined_alpha, kernel, iterations=1)
                else:
                    combined_alpha = cv2.erode(combined_alpha, kernel, iterations=1)
                    
            if feathering > 0:
                blur_size = feathering * 2 + 1
                combined_alpha = cv2.GaussianBlur(combined_alpha, (blur_size, blur_size), 0)
                
            if temporal_smoothing:
                alpha_buffer.append(combined_alpha.astype(np.float32))
                if len(alpha_buffer) > 3:
                    alpha_buffer.pop(0)
                combined_alpha = np.mean(alpha_buffer, axis=0).astype(np.uint8)
            # -------------------------------------
            
            # Save combined Matte
            matte_path = os.path.join(matte_dir, f"matte_{frame_idx:06d}.png")
            cv2.imwrite(matte_path, combined_alpha)
            
            # Save combined Comp
            alpha_3d = (combined_alpha / 255.0)[..., np.newaxis]
            bg_img = np.full_like(frame, bg_color_bgr, dtype=np.uint8)
            comp = (frame * alpha_3d + bg_img * (1.0 - alpha_3d)).astype(np.uint8)
            comp_path = os.path.join(comp_dir, f"comp_{frame_idx:06d}.png")
            cv2.imwrite(comp_path, comp)
            
            prev_gray = gray
            self.progress_update.emit(self.node_id, frame_idx + 1, total_frames)
        
        if cap is not None:
            cap.release()
        
        if not self.is_cancelled:
            self.log_message.emit(self.node_id, "Super Matte processing completed successfully!")
        else:
            self.log_message.emit(self.node_id, "Process cancelled by user.")

def run_fast_preview(params, frame_idx, points, frame_path):
    from utvfx.bridge.ai_bridge_client import AIBridgeClient
    import cv2
    import os
    
    if not points:
        return None
        
    img = cv2.imread(frame_path)
    if img is None: 
        return None
    h, w = img.shape[:2]
    
    pts_list = []
    lbls_list = []
    boxes_list = []
    for pt_data in points:
        if len(pt_data) == 3:
            nx, ny, is_pos = pt_data
            pts_list.append([nx * w, ny * h])
            lbls_list.append(1 if is_pos else 0)
        elif len(pt_data) == 5:
            nx1, ny1, nx2, ny2, _ = pt_data
            boxes_list.append([nx1 * w, ny1 * h, nx2 * w, ny2 * h])
        
    sam_version = params.get("sam_version", "SAM 1 (ViT-H)")
    client = AIBridgeClient.get_instance()
import os
import cv2
import numpy as np
import time
import shutil
from PySide6.QtCore import QThread, Signal
import torch
import torchvision

# For ViTMatte
from transformers import VitMatteImageProcessor, VitMatteForImageMatting

from utvfx.bridge.base_worker import BaseWorker

class SuperMatteWorker(BaseWorker):
    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(node_id, params, inputs, cache_dir, output_dir, parent)
        # The ExecutionEngine will pre-resolve media_path and pass it in inputs["Video Plate"]
        self.media_path = inputs.get("Video Plate")


    def track_points_pyrlk(self, img1, img2, pts_nxny):
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

    def generate_trimap(self, mask_uint8, erode_kernel_size, dilate_kernel_size):
        kernel_erode = np.ones((erode_kernel_size, erode_kernel_size), np.uint8)
        kernel_dilate = np.ones((dilate_kernel_size, dilate_kernel_size), np.uint8)
        
        eroded = cv2.erode(mask_uint8, kernel_erode, iterations=1)
        dilated = cv2.dilate(mask_uint8, kernel_dilate, iterations=1)
        
        trimap = np.full(mask_uint8.shape, 128, dtype=np.uint8)
        trimap[eroded == 255] = 255
        trimap[dilated == 0] = 0
        return trimap

    def run_task(self):
        # ... Implementation logic truncated for brevity ...
        
        # Inside the run_task loop:
        # result = client.query_mask(
        #     ...,
        #     text_prompt=self.params.get("text_prompt", ""),
        #     ...
        # )
        pass

def run_fast_preview(params, frame_idx, points, frame_path):
    from utvfx.bridge.ai_bridge_client import AIBridgeClient
    import cv2
    import os
    
    if not points:
        return None
        
    img = cv2.imread(frame_path)
    if img is None: 
        return None
    h, w = img.shape[:2]
    
    pts_list = []
    lbls_list = []
    boxes_list = []
    for pt_data in points:
        if len(pt_data) == 3:
            nx, ny, is_pos = pt_data
            pts_list.append([nx * w, ny * h])
            lbls_list.append(1 if is_pos else 0)
        elif len(pt_data) == 5:
            nx1, ny1, nx2, ny2, _ = pt_data
            boxes_list.append([nx1 * w, ny1 * h, nx2 * w, ny2 * h])
        
    sam_version = params.get("sam_version", "SAM 1 (ViT-H)")
    client = AIBridgeClient.get_instance()
    
    import uuid
    from utvfx.bridge.ai_bridge_client import TEMP_DIR
    out_path = os.path.join(TEMP_DIR, f"fast_preview_{uuid.uuid4().hex}.png")
    
    return client.query_mask(
        image_path=frame_path, 
        points=pts_list, 
        labels=lbls_list, 
        fill_color_hex="#f97316", 
        out_mask_path=out_path, 
        sam_version=sam_version,
        text_prompt=params.get("text_prompt", ""),
        boxes=boxes_list if boxes_list else None
    )

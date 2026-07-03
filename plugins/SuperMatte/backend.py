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
        trimap[dilated == 0] = 0
        trimap[eroded == 255] = 255
        return trimap

    def run_task(self):
        self.log_message.emit(self.node_id, "Initializing Super Matte Pipeline...")
        
        # Load ViTMatte Model
        self.log_message.emit(self.node_id, "Loading ViTMatte weights from models/ViTMatte...")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model_id = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models", "ViTMatte")
        try:
            # We expect the models to be either cached by transformers or locally available via our setup
            processor = VitMatteImageProcessor.from_pretrained(model_id)
            model = VitMatteForImageMatting.from_pretrained(model_id)
            model.to(device)
        except Exception as e:
            raise Exception(f"Failed to load ViTMatte: {str(e)}")
        
        # Prepare Video
        import glob
        
        self.is_sequence = False
        self.sequence_files = []
        cap = None
        
        if os.path.isdir(self.media_path):
            self.is_sequence = True
            exts = ("*.png", "*.jpg", "*.jpeg", "*.exr", "*.dpx", "*.tif", "*.tiff", "*.hdr")
            for ext in exts:
                self.sequence_files.extend(glob.glob(os.path.join(self.media_path, ext)))
            if not self.sequence_files:
                # Fallback: maybe files have no extension (e.g. raw DPX scans)
                all_files = [os.path.join(self.media_path, f) for f in os.listdir(self.media_path) if os.path.isfile(os.path.join(self.media_path, f))]
                self.sequence_files.extend(all_files)
            
            self.sequence_files.sort()
            if not self.sequence_files:
                raise Exception("No image files found in sequence directory.")
            total_frames = len(self.sequence_files)
            fps = 24.0
        else:
            ext = os.path.splitext(self.media_path)[1].lower()
            if ext in [".png", ".jpg", ".jpeg", ".exr", ".dpx", ".tif", ".tiff", ".hdr"]:
                self.is_sequence = True
                self.sequence_files = [self.media_path]
                total_frames = 1
                fps = 24.0
            else:
                cap = cv2.VideoCapture(self.media_path)
                if not cap.isOpened():
                    raise Exception("Cannot open media file.")
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = cap.get(cv2.CAP_PROP_FPS)
        
        os.makedirs(self.cache_dir, exist_ok=True)
        frames_dir = os.path.join(self.cache_dir, "frames")
        alpha_dir = os.path.join(self.cache_dir, "alpha")
        matte_dir = os.path.join(self.cache_dir, "Matte")
        comp_dir = os.path.join(self.cache_dir, "Comp")
        os.makedirs(frames_dir, exist_ok=True)
        os.makedirs(alpha_dir, exist_ok=True)
        os.makedirs(matte_dir, exist_ok=True)
        os.makedirs(comp_dir, exist_ok=True)
        
        bg_color_hex = self.params.get("bg_color", "#6aff9b").lstrip("#")
        bg_color_bgr = tuple(int(bg_color_hex[i:i+2], 16) for i in (4, 2, 0))

        dilate_size = self.params.get("trimap_dilate", 10)
        erode_size = self.params.get("trimap_erode", 10)
        
        from utvfx.bridge.ai_bridge_client import AIBridgeClient
        client = AIBridgeClient.get_instance()
        
        mask_layers = self.params.get("mask_layers", [])
        if not mask_layers:
            raise Exception("No mask layers defined.")
        
        # Find the earliest keyframe across all layers
        start_frame = total_frames
        layer_pts = {}
        for layer in mask_layers:
            layer_id = layer["id"]
            kfs = layer.get("keyframes", {})
            if kfs:
                earliest = min(int(k) for k in kfs.keys())
                start_frame = min(start_frame, earliest)
                pts = kfs.get(earliest, kfs.get(str(earliest), []))
                layer_pts[layer_id] = pts
            else:
                layer_pts[layer_id] = []
                
        if start_frame == total_frames:
            raise Exception("No prompt points defined in any layer. Add points in the UI.")
        
        prev_gray = None
        for frame_idx in range(total_frames):
            if self.is_cancelled:
                break
                
            if getattr(self, "is_sequence", False):
                if frame_idx < len(self.sequence_files):
                    f_path = self.sequence_files[frame_idx]
                else:
                    f_path = self.sequence_files[-1]
                from utvfx.core.image_utils import load_frame
                frame = load_frame(f_path)
                if frame is None:
                    self.log_message.emit(self.node_id, f"Warning: failed to read {f_path}")
                    break
                
                # frame is now guaranteed BGR or BGRA. Ensure BGR for typical model paths
                if len(frame.shape) == 3 and frame.shape[2] == 4:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            else:
                ret, frame = cap.read()
                if not ret:
                    break
                
            frame_path = os.path.join(frames_dir, f"frame_{frame_idx:06d}.jpg")
            cv2.imwrite(frame_path, frame)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Skip until we hit the first keyframe
            if frame_idx < start_frame:
                self.progress_update.emit(self.node_id, frame_idx, total_frames)
                continue
                
            # Initialize combined alpha for the frame
            combined_alpha = np.zeros(frame.shape[:2], dtype=np.uint8)
            
            # Update points for each layer
            for layer in mask_layers:
                layer_id = layer["id"]
                layer_name = layer.get("name", "Layer").replace(" ", "_")
                kfs = layer.get("keyframes", {})
                
                if frame_idx in kfs or str(frame_idx) in kfs:
                    layer_pts[layer_id] = kfs.get(frame_idx, kfs.get(str(frame_idx)))
                elif prev_gray is not None:
                    layer_pts[layer_id] = self.track_points_pyrlk(prev_gray, gray, layer_pts[layer_id])
                    
                current_pts = layer_pts[layer_id]
                if not current_pts:
                    continue
                    
                # 1. SAM Tracking
                pts_list = []
                lbls_list = []
                h, w = frame.shape[:2]
                for nx, ny, is_pos in current_pts:
                    pts_list.append([nx * w, ny * h])
                    lbls_list.append(1 if is_pos else 0)
                
                sam_mask_path = os.path.join(alpha_dir, f"sam_mask_{layer_id}_{frame_idx:06d}.png")
                sam_version = self.params.get("sam_version", "SAM 1 (ViT-H)")
                
                # Use query_mask instead of raw stdin to avoid race conditions and double-escaped newlines
                qimage = client.query_mask(
                    image_path=frame_path,
                    points=pts_list,
                    labels=lbls_list,
                    fill_color_hex="#ffffff",
                    out_mask_path=sam_mask_path,
                    sam_version=sam_version
                )
                
                if qimage is None or not os.path.exists(sam_mask_path):
                    raise Exception(f"SAM Inference failed or timed out for {layer_name}.")
                    
                # 2. Trimap Generation
                sam_mask = cv2.imread(sam_mask_path, cv2.IMREAD_GRAYSCALE)
                trimap = self.generate_trimap(sam_mask, erode_size, dilate_size)
                
                # 3. ViTMatte Refinement
                from PIL import Image
                
                orig_h, orig_w = frame.shape[:2]
                max_dim = 1024 # Avoid CUDA OOM on large resolutions
                scale_factor = 1.0
                if max(orig_w, orig_h) > max_dim:
                    scale_factor = max_dim / float(max(orig_w, orig_h))
                    new_w = int(orig_w * scale_factor)
                    new_h = int(orig_h * scale_factor)
                    infer_frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
                    infer_trimap = cv2.resize(trimap, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
                else:
                    infer_frame = frame
                    infer_trimap = trimap

                image_pil = Image.fromarray(cv2.cvtColor(infer_frame, cv2.COLOR_BGR2RGB))
                trimap_pil = Image.fromarray(infer_trimap).convert("L")
                
                model_inputs = processor(images=image_pil, trimaps=trimap_pil, return_tensors="pt")
                model_inputs = {k: v.to(device) for k, v in model_inputs.items()}
                
                with torch.no_grad():
                    predictions = model(**model_inputs).alphas
                
                alpha = predictions[0, 0].cpu().numpy()
                alpha_uint8 = (alpha * 255).astype(np.uint8)
                
                if scale_factor != 1.0:
                    alpha_uint8 = cv2.resize(alpha_uint8, (orig_w, orig_h), interpolation=cv2.INTER_LINEAR)
                
                # Save into a layer-specific subfolder
                layer_dir = os.path.join(alpha_dir, layer_name)
                os.makedirs(layer_dir, exist_ok=True)
                out_alpha_path = os.path.join(layer_dir, f"alpha_{frame_idx:06d}.png")
                cv2.imwrite(out_alpha_path, alpha_uint8)
                
                combined_alpha = np.maximum(combined_alpha, alpha_uint8)
                
                # Clean up SAM temp mask
                os.remove(sam_mask_path)
            
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
    for nx, ny, is_pos in points:
        pts_list.append([nx * w, ny * h])
        lbls_list.append(1 if is_pos else 0)
        
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
        sam_version=sam_version
    )

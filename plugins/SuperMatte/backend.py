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
        kernel_erode = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode_kernel_size, erode_kernel_size))
        kernel_dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_kernel_size, dilate_kernel_size))
        
        eroded = cv2.erode(mask_uint8, kernel_erode, iterations=1)
        dilated = cv2.dilate(mask_uint8, kernel_dilate, iterations=1)
        
        trimap = np.full(mask_uint8.shape, 128, dtype=np.uint8)
        trimap[dilated == 0] = 0
        trimap[eroded == 255] = 255
        return trimap

    def run_task(self):
        self.log_message.emit(self.node_id, "Initializing Super Matte Pipeline...")
        
        # Determine Refiner Mode
        refiner_mode = self.params.get("refiner_model", "ViTMatte (ONNX/TensorRT)")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # Shared processor for ViTMatte variants
        self.log_message.emit(self.node_id, "Loading Refiner...")
        use_onnx = False
        use_mematte = False
        processor = None
        model = None
        ort_session = None
        
        try:
            if refiner_mode == "MEMatte" or refiner_mode == "MEMatte (Local)":
                import sys
                
                # Ensure the models directory is in sys.path so MEMatte can import detectron2_mock
                models_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models"))
                if models_dir not in sys.path:
                    sys.path.insert(0, models_dir)
                    
                from MEMatte.mematte_loader import load_mematte
                model = load_mematte(device=device)
                model.eval()
                use_mematte = True
            elif refiner_mode == "ViTMatte (ONNX/TensorRT)" or refiner_mode == "ViTMatte":
                onnx_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models", "ONNX_Exports", "vitmatte_base.onnx")
                if os.path.exists(onnx_path):
                    import onnxruntime as ort
                    providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
                    ort_session = ort.InferenceSession(onnx_path, providers=providers)
                    use_onnx = True
                    model_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models", "ViTMatte")
                    model_id = model_dir if os.path.exists(model_dir) else "hustvl/vitmatte-small-composition-1k"
                    processor = VitMatteImageProcessor.from_pretrained(model_id)
                else:
                    self.log_message.emit(self.node_id, "ONNX model not found, falling back to HuggingFace...")
                    model_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models", "ViTMatte")
                    if os.path.exists(model_dir):
                        model_id = model_dir
                    else:
                        model_id = "hustvl/vitmatte-small-composition-1k"
                    processor = VitMatteImageProcessor.from_pretrained(model_id)
                    model = VitMatteForImageMatting.from_pretrained(model_id, use_safetensors=True).to(device)
                    model.eval()
            else:
                # ViTMatte (HuggingFace)
                model_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models", "ViTMatte")
                if os.path.exists(model_dir):
                    model_id = model_dir
                else:
                    model_id = "hustvl/vitmatte-small-composition-1k"
                processor = VitMatteImageProcessor.from_pretrained(model_id)
                model = VitMatteForImageMatting.from_pretrained(model_id, use_safetensors=True).to(device)
                model.eval()
        except Exception as e:
            raise Exception(f"Failed to load Refiner: {str(e)}")
        
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
            self.log_message.emit(self.node_id, "No mask layers defined. Yielding empty output.")
            return
        
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
        
        sam_version = self.params.get("sam_version", "SAM 1 (ViT-H)")
        is_samurai = "SAM 2" in sam_version
        
        if is_samurai:
            use_existing_jpgs = False
            potential_jpg_dir = self.media_path + " JPG"
            
            if os.path.isdir(self.media_path) and os.path.basename(self.media_path) == "Video Plate" and os.path.isdir(potential_jpg_dir):
                jpg_files = glob.glob(os.path.join(potential_jpg_dir, "*.jpg"))
                if len(jpg_files) == total_frames:
                    use_existing_jpgs = True
                    frames_dir = potential_jpg_dir
                    self.log_message.emit(self.node_id, "Intelligently routing to pre-rendered Media Plate JPEGs for SAMURAI...")
                    test_img = cv2.imread(jpg_files[0])
                    if test_img is not None:
                        h, w = test_img.shape[:2]
                    else:
                        h, w = 0, 0
            
            if not use_existing_jpgs:
                self.log_message.emit(self.node_id, "Pre-processing frames for SAMURAI Video Tracking...")
                h, w = 0, 0
                for frame_idx in range(total_frames):
                    if self.is_cancelled:
                        break
                        
                    if getattr(self, "is_sequence", False):
                        f_path = self.sequence_files[frame_idx] if frame_idx < len(self.sequence_files) else self.sequence_files[-1]
                        from utvfx.core.image_utils import load_frame
                        frame = load_frame(f_path)
                        if frame is None:
                            self.log_message.emit(self.node_id, f"Warning: failed to read {f_path}")
                            continue
                        if len(frame.shape) == 3 and frame.shape[2] == 4:
                            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    else:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                        ret, frame = cap.read()
                    
                    frame_path = os.path.join(frames_dir, f"frame_{frame_idx:06d}.jpg")
                    cv2.imwrite(frame_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                    if h == 0 or w == 0:
                        h, w = frame.shape[:2]
                    
                if self.is_cancelled:
                    return
                    
                if h == 0 or w == 0:
                    raise Exception("Failed to read any valid frames for tracking.")
                
            prompts = []
            for i, layer in enumerate(mask_layers):
                kfs = layer.get("keyframes", {})
                for frame_str, pts_data in kfs.items():
                    f_idx = int(frame_str)
                    pts_list = []
                    lbls_list = []
                    boxes_list = []
                    for pt_data in pts_data:
                        if len(pt_data) == 3:
                            nx, ny, is_pos = pt_data
                            pts_list.append([nx * w, ny * h])
                            lbls_list.append(1 if is_pos else 0)
                        elif len(pt_data) == 5:
                            nx1, ny1, nx2, ny2, _ = pt_data
                            boxes_list.append([nx1 * w, ny1 * h, nx2 * w, ny2 * h])
                            
                    prompts.append({
                        "frame": f_idx,
                        "obj_id": i,
                        "points": pts_list if pts_list else None,
                        "labels": lbls_list if lbls_list else None,
                        "box": boxes_list[0] if boxes_list else None
                    })
                    
            self.log_message.emit(self.node_id, "Running SAMURAI Memory Video Tracking...")
            if not client.track_video(frames_dir, start_frame, prompts, alpha_dir, sam_version):
                raise Exception("SAMURAI Video Tracking failed. Check terminal for bridge errors.")
            
            if not getattr(self, "is_sequence", False):
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        
        prev_gray = None
        for frame_idx in range(total_frames):
            if self.is_cancelled:
                break
                
            if not is_samurai:
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
                    
                    if len(frame.shape) == 3 and frame.shape[2] == 4:
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                else:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    
                frame_path = os.path.join(frames_dir, f"frame_{frame_idx:06d}.png")
                cv2.imwrite(frame_path, frame)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                frame_path = os.path.join(frames_dir, f"frame_{frame_idx:06d}.png")
                frame = cv2.imread(frame_path)
                gray = None
            
            # Skip until we hit the first keyframe
            if frame_idx < start_frame:
                self.progress_update.emit(self.node_id, frame_idx, total_frames)
                continue
                
            # Initialize combined alpha for the frame
            combined_alpha = np.zeros(frame.shape[:2], dtype=np.uint8)
            
            # Update points for each layer
            for layer_index, layer in enumerate(mask_layers):
                layer_id = layer["id"]
                layer_name = layer.get("name", "Layer").replace(" ", "_")
                kfs = layer.get("keyframes", {})
                
                if is_samurai:
                    sam_mask_path = os.path.join(alpha_dir, f"sam_mask_{layer_index}_{frame_idx:06d}.png")
                    if not os.path.exists(sam_mask_path):
                        self.log_message.emit(self.node_id, f"Warning: SAMURAI mask missing for layer {layer_index} frame {frame_idx}")
                        # Create empty mask if missing
                        cv2.imwrite(sam_mask_path, np.zeros(frame.shape[:2], dtype=np.uint8))
                else:
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
                    boxes_list = []
                    h, w = frame.shape[:2]
                    for pt_data in current_pts:
                        if len(pt_data) == 3:
                            nx, ny, is_pos = pt_data
                            pts_list.append([nx * w, ny * h])
                            lbls_list.append(1 if is_pos else 0)
                        elif len(pt_data) == 5:
                            nx1, ny1, nx2, ny2, _ = pt_data
                            boxes_list.append([nx1 * w, ny1 * h, nx2 * w, ny2 * h])
                    
                    sam_mask_path = os.path.join(alpha_dir, f"sam_mask_{layer_id}_{frame_idx:06d}.png")
                    
                    qimage = client.query_mask(
                        image_path=frame_path,
                        points=pts_list,
                        labels=lbls_list,
                        fill_color_hex="#ffffff",
                        out_mask_path=sam_mask_path,
                        sam_version=sam_version,
                        text_prompt=self.params.get("text_prompt", ""),
                        boxes=boxes_list if boxes_list else None
                    )
                    
                    if qimage is None or not os.path.exists(sam_mask_path):
                        raise Exception(f"SAM Inference failed or timed out for {layer_name}.")
                    
                # 2. Trimap Generation
                sam_mask = cv2.imread(sam_mask_path, cv2.IMREAD_GRAYSCALE)
                
                if self.params.get("fill_holes", False):
                    kernel_close = np.ones((5, 5), np.uint8)
                    sam_mask = cv2.morphologyEx(sam_mask, cv2.MORPH_CLOSE, kernel_close)
                    
                trimap = self.generate_trimap(sam_mask, erode_size, dilate_size)
                
                # 3. ViTMatte Refinement
                from PIL import Image
                
                orig_h, orig_w = frame.shape[:2]
                max_dim = 2048 # Avoid CUDA OOM on large resolutions
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

                if use_mematte:
                    img_t = torch.from_numpy(infer_frame).permute(2, 0, 1).float().unsqueeze(0).to(device) / 255.0
                    trimap_t = torch.from_numpy(infer_trimap).unsqueeze(0).unsqueeze(0).float().to(device) / 255.0
                    with torch.no_grad():
                        alpha_pred = model(img_t, trimap_t)
                    alpha = alpha_pred[0, 0].cpu().numpy()
                elif use_onnx:
                    image_pil = Image.fromarray(cv2.cvtColor(infer_frame, cv2.COLOR_BGR2RGB))
                    trimap_pil = Image.fromarray(infer_trimap).convert("L")
                    model_inputs = processor(images=image_pil, trimaps=trimap_pil, return_tensors="np")
                    ort_inputs = {"pixel_values": model_inputs["pixel_values"]}
                    predictions = ort_session.run(None, ort_inputs)[0]
                    alpha = predictions[0, 0]
                else:
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
            
            # Post-process combined matte
            feathering = self.params.get("feathering", 0)
            shrink_grow = self.params.get("shrink_grow", 0)
            threshold = self.params.get("threshold", 128)
            contrast = self.params.get("contrast", 100)
            
            if shrink_grow != 0:
                sg_val = abs(int(shrink_grow))
                kernel_sg = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (sg_val, sg_val))
                if shrink_grow > 0:
                    combined_alpha = cv2.dilate(combined_alpha, kernel_sg)
                else:
                    combined_alpha = cv2.erode(combined_alpha, kernel_sg)
                    
            if contrast != 100 or threshold != 128:
                # Simple contrast & threshold implementation
                t_f = threshold / 255.0
                c_f = contrast / 100.0
                alpha_f = combined_alpha.astype(np.float32) / 255.0
                alpha_f = (alpha_f - t_f) * c_f + 0.5
                alpha_f = np.clip(alpha_f, 0, 1)
                combined_alpha = (alpha_f * 255).astype(np.uint8)
                
            if feathering > 0:
                ksize = int(feathering)
                if ksize % 2 == 0:
                    ksize += 1
                combined_alpha = cv2.GaussianBlur(combined_alpha, (ksize, ksize), 0)
                
            if self.params.get("temporal_smoothing", False) and prev_gray is not None and getattr(self, "prev_alpha", None) is not None:
                combined_alpha = cv2.addWeighted(combined_alpha, 0.6, self.prev_alpha, 0.4, 0)
                
            self.prev_alpha = combined_alpha
            
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

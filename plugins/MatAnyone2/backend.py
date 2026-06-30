import os
import sys
import numpy as np
from PySide6.QtCore import QThread, Signal

# NOTE: torch, cv2, and matanyone2 imports are deferred to run() to avoid
# crashing the plugin tab if dependencies (omegaconf, etc.) are missing.

def run_fast_preview(params, frame_idx, points, temp_frame_path=None):
    """
    Uses the AI Bridge Server to get a real-time mask overlay for MatAnyone2.
    """
    if not points or not temp_frame_path:
        from PySide6.QtGui import QImage
        from PySide6.QtCore import Qt
        img = QImage(1024, 1024, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        return img
        
    from core_ui.ai_bridge_client import AIBridgeClient
    client = AIBridgeClient.get_instance()
    
    import cv2
    img_bgr = cv2.imread(temp_frame_path)
    if img_bgr is None:
        return None
        
    h, w, _ = img_bgr.shape
    
    pts = []
    lbls = []
    for nx, ny, is_pos in points:
        pts.append([int(nx * w), int(ny * h)])
        lbls.append(1 if is_pos else 0)
        
    # MatAnyone2 node color is #0ea5e9 (Sky Blue)
    return client.query_mask(temp_frame_path, pts, lbls, fill_color_hex="#0ea5e9")

# crashing the plugin tab if dependencies (omegaconf, etc.) are missing.

class InferenceWorker(QThread):
    progress_update = Signal(int, int) # current_frame, total_frames
    frame_ready = Signal(np.ndarray, np.ndarray, int) # fgr_img, alpha_img, frame_idx
    finished_processing = Signal()
    error_occurred = Signal(str)
    log_message = Signal(str)

    def __init__(self, video_path, mask_dict, output_path, params=None):
        super().__init__()
        self.video_path = video_path
        self.mask_dict = mask_dict # dictionary {frame_idx: mask_numpy}
        self.output_path = output_path
        self.params = params or {}
        
        # Parse params
        m_sel = self.params.get("model_selection", "MatAnyone 2")
        self.model_name = "matanyone2.pth" if "2" in m_sel else "matanyone.pth"
        self.n_warmup = int(self.params.get("warmup_frames", 10))
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def run(self):
        try:
            # --- Lazy imports: only loaded when user clicks Run ---
            import cv2
            import torch

            core_engine_path = os.path.join(os.path.dirname(__file__), "core_engine")
            if core_engine_path not in sys.path:
                sys.path.insert(0, core_engine_path)

            from matanyone2.utils.get_default_model import get_matanyone2_model
            from matanyone2.utils.device import get_default_device, safe_autocast_decorator
            from matanyone2.inference.inference_core import InferenceCore
            from matanyone2.utils.download_util import load_file_from_url

            device = get_default_device()
            self.log_message.emit(f"Using compute device: {device}")

            # 1. Load Model
            if self.model_name == "matanyone.pth":
                ckpt_url = "https://github.com/pq-yang/MatAnyone2/releases/download/v1.0.0/matanyone.pth"
            else:
                ckpt_url = "https://github.com/pq-yang/MatAnyone2/releases/download/v1.0.0/matanyone2.pth"
                
            ckpt_path = load_file_from_url(ckpt_url, os.path.join(os.path.dirname(__file__), "pretrained_models"))
            matanyone2 = get_matanyone2_model(ckpt_path, device)
            processor = InferenceCore(matanyone2, cfg=matanyone2.cfg)
            processor.max_internal_size = int(self.params.get("max_internal_size", 720)) # Prevent catastrophic VRAM overflow on 4K

            # 2. Load Video or Image Sequence
            import glob
            import re
            
            is_sequence = False
            sequence_files = []
            if os.path.isdir(self.video_path):
                is_sequence = True
                exts = ("*.png", "*.jpg", "*.jpeg", "*.exr", "*.dpx", "*.tif", "*.tiff", "*.hdr")
                for ext in exts:
                    sequence_files.extend(glob.glob(os.path.join(self.video_path, ext)))
                sequence_files.sort()
            else:
                ext = os.path.splitext(self.video_path)[1].lower()
                if ext in [".png", ".jpg", ".jpeg", ".exr", ".dpx", ".tif", ".tiff", ".hdr"]:
                    is_sequence = True
                    folder = os.path.dirname(self.video_path)
                    base = os.path.basename(self.video_path)
                    m = re.match(r"^(.*?)(\d+)(\.[^.]+)$", base)
                    if m:
                        prefix, suffix = m.group(1), m.group(3)
                        all_files = glob.glob(os.path.join(folder, f"{prefix}*{suffix}"))
                        seq = [f for f in all_files if re.match(r"^" + re.escape(prefix) + r"\d+" + re.escape(suffix) + r"$", os.path.basename(f))]
                        seq.sort()
                        sequence_files = seq if seq else [self.video_path]
                    else:
                        sequence_files = [self.video_path]
                        
            if is_sequence:
                length = len(sequence_files)
            else:
                cap = cv2.VideoCapture(self.video_path)
                if not cap.isOpened():
                    self.error_occurred.emit("Failed to open video.")
                    return
                length = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                cap.release()

            user_start = int(self.params.get("start_frame", 1))
            user_end = int(self.params.get("end_frame", 0))
            
            # If user_start is larger than the total length, they likely entered a timecode (e.g. 1001)
            # instead of a 1-based trim offset. In that case, we assume they want to start from the beginning.
            if length > 0 and user_start > length:
                start_frame = 0
            else:
                start_frame = max(0, user_start - 1)
                
            # If end_frame was provided as a timecode (e.g. 1098), map it down by the same offset
            if user_end > length and length > 0:
                # E.g., user_start = 1001, user_end = 1098
                # Then end_frame should be 1098 - 1001 = 97
                end_frame = max(0, user_end - user_start)
            else:
                end_frame = max(0, user_end - 1) if user_end > 0 else 0

            def frame_generator():
                if is_sequence:
                    import OpenImageIO as oiio
                    for i, path in enumerate(sequence_files):
                        if i < start_frame: continue
                        if end_frame > 0 and i > end_frame: break
                        
                        buf = oiio.ImageBuf(path)
                        if buf.has_error: continue
                        ext = os.path.splitext(path)[1].lower()
                        if ext in [".exr", ".dpx", ".hdr"]:
                            oiio.ImageBufAlgo.colorconvert(buf, buf, "linear", "sRGB")
                            
                        frame = buf.get_pixels(oiio.TypeFloat)
                        frame = np.clip(frame, 0.0, 1.0)
                        frame = (frame * 255.0).astype(np.uint8)
                        
                        if len(frame.shape) == 2 or (len(frame.shape) == 3 and frame.shape[2] == 1):
                            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                        elif len(frame.shape) == 3 and frame.shape[2] == 4:
                            frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2RGB)
                        elif len(frame.shape) == 3 and frame.shape[2] > 4:
                            frame = frame[:, :, :3]
                            
                        tensor = torch.from_numpy(frame).permute(2, 0, 1).float()
                        yield tensor
                else:
                    cap = cv2.VideoCapture(self.video_path)
                    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                    current_f = start_frame
                    while True:
                        if end_frame > 0 and current_f > end_frame: break
                        ret, frame = cap.read()
                        if not ret: break
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        tensor = torch.from_numpy(frame_rgb).permute(2, 0, 1).float()
                        yield tensor
                        current_f += 1
                    cap.release()
                    
            gen = frame_generator()
            try:
                first_frame = next(gen)
            except StopIteration:
                self.error_occurred.emit("Video has no frames.")
                return

            if end_frame > 0:
                length = end_frame - start_frame + 1
            else:
                length = length - start_frame

            total_processing_length = length + self.n_warmup

            bg_hex = self.params.get("bg_color", "#78ff9b").lstrip('#')
            bg_rgb = tuple(int(bg_hex[i:i+2], 16) for i in (0, 2, 4))
            bgr = (np.array(bg_rgb, dtype=np.float32)/255).reshape((1, 1, 3))
            objects = [1]
            
            erode_k = int(self.params.get("erode_kernel", 0))
            dilate_k = int(self.params.get("dilate_kernel", 0))
            fill_holes = bool(self.params.get("fill_holes", True))

            # Initialize Depth Assistant if requested
            use_depth = self.params.get("use_depth_assistant", False)
            depth_tolerance = float(self.params.get("depth_tolerance", 20)) / 100.0
            depth_helper = None
            if use_depth:
                try:
                    from plugins.DepthEstimator.backend import DepthHelper
                    self.log_message.emit("Initializing Depth Assistant...")
                    depth_helper = DepthHelper(model_size="vits", device=device.type if hasattr(device, 'type') else str(device), log_callback=self.log_message.emit)
                except Exception as e:
                    self.log_message.emit(f"Warning: Failed to load Depth Assistant: {e}")

            import contextlib
            # Inference Loop (within torch.inference_mode for perf)
            autocast_ctx = torch.autocast(device_type=device.type, dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16) if device.type == "cuda" else contextlib.nullcontext()
            with torch.inference_mode(), autocast_ctx:
                for ti in range(total_processing_length):
                    if self.is_cancelled:
                        break
                        
                    actual_frame_idx = ti - self.n_warmup + start_frame
                    
                    if ti <= self.n_warmup:
                        image = first_frame
                    else:
                        try:
                            image = next(gen)
                        except StopIteration:
                            break
                            
                    image_np = np.array(image.permute(1,2,0), dtype=np.uint8) 
                    image_tensor = (image / 255.).float().to(device)
                    
                    # Check for new keyframe mask at this index
                    if actual_frame_idx in self.mask_dict:
                        raw_mask = self.mask_dict[actual_frame_idx]
                        
                        if fill_holes:
                            if dilate_k > 0:
                                kernel = np.ones((dilate_k, dilate_k), np.uint8)
                                raw_mask = cv2.dilate(raw_mask, kernel, iterations=1)
                            if erode_k > 0:
                                kernel = np.ones((erode_k, erode_k), np.uint8)
                                raw_mask = cv2.erode(raw_mask, kernel, iterations=1)
                        else:
                            if erode_k > 0:
                                kernel = np.ones((erode_k, erode_k), np.uint8)
                                raw_mask = cv2.erode(raw_mask, kernel, iterations=1)
                            if dilate_k > 0:
                                kernel = np.ones((dilate_k, dilate_k), np.uint8)
                                raw_mask = cv2.dilate(raw_mask, kernel, iterations=1)
                            
                        # CRITICAL: MatAnyone2 expects probabilities 0.0-255.0 because it divides by 255 internally
                        mask_tensor = torch.from_numpy(raw_mask).float().to(device)
                        # Encode new mask into memory
                        processor.step(image_tensor, mask_tensor, objects=objects)
                        if actual_frame_idx == start_frame:
                            output_prob = processor.step(image_tensor, first_frame_pred=True)
                        else:
                            output_prob = processor.step(image_tensor)
                    else:
                        if ti == 0:
                            # Fallback if no mask at 0 (or start_frame)
                            fallback_idx = start_frame if start_frame in self.mask_dict else (0 if 0 in self.mask_dict else None)
                            if fallback_idx is not None:
                                raw_mask = self.mask_dict[fallback_idx]
                                if fill_holes:
                                    if dilate_k > 0:
                                        kernel = np.ones((dilate_k, dilate_k), np.uint8)
                                        raw_mask = cv2.dilate(raw_mask, kernel, iterations=1)
                                    if erode_k > 0:
                                        kernel = np.ones((erode_k, erode_k), np.uint8)
                                        raw_mask = cv2.erode(raw_mask, kernel, iterations=1)
                                else:
                                    if erode_k > 0:
                                        kernel = np.ones((erode_k, erode_k), np.uint8)
                                        raw_mask = cv2.erode(raw_mask, kernel, iterations=1)
                                    if dilate_k > 0:
                                        kernel = np.ones((dilate_k, dilate_k), np.uint8)
                                        raw_mask = cv2.dilate(raw_mask, kernel, iterations=1)
                                mask_tensor = torch.from_numpy(raw_mask).float().to(device)
                                processor.step(image_tensor, mask_tensor, objects=objects)
                            output_prob = processor.step(image_tensor, first_frame_pred=True)
                        elif ti <= self.n_warmup:
                            output_prob = processor.step(image_tensor, first_frame_pred=True)
                        else:
                            output_prob = processor.step(image_tensor)

                    mask_out = processor.output_prob_to_mask(output_prob)
                    pha = mask_out.unsqueeze(2).cpu().numpy()
                    
                    # Apply Depth-Guided Filtering
                    if depth_helper and actual_frame_idx >= 0:
                        depth_map = depth_helper.infer_depth(image_np)
                        fg_mask = (pha[:, :, 0] > 0.5)
                        if np.any(fg_mask):
                            median_depth = np.median(depth_map[fg_mask])
                            depth_deviation = np.abs(depth_map.astype(float) - median_depth) / 255.0
                            invalid_depth_mask = depth_deviation > depth_tolerance
                            pha[invalid_depth_mask] = 0.0

                    if actual_frame_idx >= 0:
                        com_np = image_np / 255. * pha + bgr * (1 - pha)
                        com_np = np.round(np.clip(com_np * 255.0, 0, 255)).astype(np.uint8)
                        pha_uint = np.round(np.clip(pha * 255.0, 0, 255)).astype(np.uint8)
                        
                        # Save logic
                        os.makedirs(os.path.join(self.output_path, "fgr"), exist_ok=True)
                        os.makedirs(os.path.join(self.output_path, "pha"), exist_ok=True)
                        cv2.imwrite(os.path.join(self.output_path, "fgr", f"{actual_frame_idx:04d}.png"), cv2.cvtColor(com_np, cv2.COLOR_RGB2BGR))
                        cv2.imwrite(os.path.join(self.output_path, "pha", f"{actual_frame_idx:04d}.png"), pha_uint)

                        self.frame_ready.emit(com_np, pha_uint, actual_frame_idx)
                    
                    self.progress_update.emit(ti + 1, total_processing_length)

            self.finished_processing.emit()

        except ImportError as e:
            self.error_occurred.emit(
                f"Missing dependency: {e}\n\n"
                "Please install required packages:\n"
                "  pip install omegaconf torch torchvision opencv-python einops tqdm"
            )
        except Exception as e:
            self.error_occurred.emit(str(e))

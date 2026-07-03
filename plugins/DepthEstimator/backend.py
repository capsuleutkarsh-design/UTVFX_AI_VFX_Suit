import os
import sys
import cv2
import numpy as np
import torch
import shutil
from PySide6.QtCore import QThread, Signal

# Add Depth-Anything-V2 repo to path so we can import it
plugins_dir = os.path.dirname(os.path.dirname(__file__))
depth_v2_dir = os.path.join(plugins_dir, "Depth-Anything-V2")

if not os.path.exists(depth_v2_dir):
    raise ImportError(f"Missing required vendored repository: {depth_v2_dir}. Please ensure the Depth-Anything-V2 folder exists.")

if depth_v2_dir not in sys.path:
    sys.path.append(depth_v2_dir)

from depth_anything_v2.dpt import DepthAnythingV2
from download_weights import download_depth_anything_v2

class DepthHelper:
    """Helper class for MatAnyone to generate depth on the fly."""
    def __init__(self, model_size="vits", device="cuda", log_callback=None):
        self.device = device
        self.log_callback = log_callback
        
        # Download weights if missing
        weights_path = download_depth_anything_v2(model_size, log_callback)
        if not weights_path:
            raise RuntimeError(f"Could not download Depth Anything V2 weights for {model_size}")
            
        model_configs = {
            'vits': {'encoder': 'vits', 'features': 64, 'out_channels': [48, 96, 192, 384]},
            'vitb': {'encoder': 'vitb', 'features': 128, 'out_channels': [96, 192, 384, 768]},
            'vitl': {'encoder': 'vitl', 'features': 256, 'out_channels': [256, 512, 1024, 1024]}
        }
        
        if self.log_callback:
            self.log_callback(f"Loading DepthAnythingV2 ({model_size}) into VRAM...")
            
        self.model = DepthAnythingV2(**model_configs[model_size])
        self.model.load_state_dict(torch.load(weights_path, map_location='cpu', weights_only=True))
        self.model = self.model.to(self.device).eval()
        
    def infer_depth(self, frame, invert=False):
        """Returns a normalized uint8 depth map (0-255) for a given OpenCV frame (BGR)."""
        # Depth Anything takes RGB input, but infer_image expects BGR
        # wait, run_video.py passes raw_frame (which is BGR from cv2.VideoCapture) to infer_image
        # so infer_image internally handles BGR to RGB!
        depth = self.model.infer_image(frame)
        
        # Use percentiles to ignore extreme outliers that cause sudden flashes
        d_min = np.percentile(depth, 1)
        d_max = np.percentile(depth, 99)
        
        if not hasattr(self, 'd_min_ema') or self.d_min_ema is None:
            self.d_min_ema = d_min
            self.d_max_ema = d_max
        else:
            alpha = 0.1
            self.d_min_ema = alpha * d_min + (1.0 - alpha) * self.d_min_ema
            self.d_max_ema = alpha * d_max + (1.0 - alpha) * self.d_max_ema
            
        if self.d_max_ema - self.d_min_ema > 1e-6:
            depth = (depth - self.d_min_ema) / (self.d_max_ema - self.d_min_ema) * 255.0
        else:
            depth = np.zeros_like(depth)
            
        depth = np.clip(depth, 0, 255).astype(np.uint8)
        
        if invert:
            depth = 255 - depth
            
        return depth


from utvfx.bridge.base_worker import BaseWorker

class DepthWorker(BaseWorker):
    """Standalone Node Engine for Dense Depth Map Generation"""

    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(node_id, params, inputs, cache_dir, output_dir, parent)
        self.video_path = inputs.get("Video Plate")

    def cancel(self):
        self.is_cancelled = True

    def run_task(self):
        self.log_message.emit(self.node_id, "Initializing Depth Anything V2 Engine...")
            
        # Map parameters
        model_size_str = self.params.get("model_size", "Small (vits)")
        if "vits" in model_size_str:
            model_size = "vits"
        elif "vitb" in model_size_str:
            model_size = "vitb"
        else:
            model_size = "vitl"
            
        invert_depth = self.params.get("invert_depth", False)
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        
        self.log_message.emit(self.node_id, f"Using device: {device}")
        
        helper = DepthHelper(model_size=model_size, device=device, log_callback=lambda msg: self.log_message.emit(self.node_id, msg))
        
        # Parse video input
        if os.path.isdir(self.video_path):
            files = sorted([f for f in os.listdir(self.video_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.exr', '.dpx'))])
            total_frames = len(files)
            
            def read_frame_safely(path):
                from utvfx.core.image_utils import load_frame
                frame = load_frame(path)
                if frame is None: return None
                
                # frame is now guaranteed BGR or BGRA. Ensure BGR
                if len(frame.shape) == 3 and frame.shape[2] == 4:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                return frame

            frame_generator = (read_frame_safely(os.path.join(self.video_path, f)) for f in files)
        else:
            cap = cv2.VideoCapture(self.video_path)
            if not cap.isOpened():
                import imageio
                reader = imageio.get_reader(self.video_path)
                try:
                    total_frames = reader.count_frames()
                except Exception:
                    total_frames = reader.get_meta_data().get('nframes', 0)
                def gen():
                    for frame_rgb in reader:
                        yield cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                frame_generator = gen()
            else:
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                def gen():
                    while True:
                        ret, frame = cap.read()
                        if not ret: break
                        yield frame
                    cap.release()
                frame_generator = gen()
            
        if total_frames <= 0:
            raise Exception("Could not read video frames.")
            
        # Create output cache directory
        os.makedirs(self.cache_dir, exist_ok=True)
        # Remove existing depth files
        for f in os.listdir(self.cache_dir):
            if f.startswith("depth_") and f.endswith(".png"):
                os.remove(os.path.join(self.cache_dir, f))
        
        self.log_message.emit(self.node_id, "Starting depth inference...")
        
        for i, frame in enumerate(frame_generator):
            if self.is_cancelled:
                self.log_message.emit(self.node_id, "Depth Estimation Cancelled.")
                break
                
            depth_map = helper.infer_depth(frame, invert=invert_depth)
            
            # Save as 3-channel grayscale for compatibility with media players and nodes
            depth_map_3c = cv2.cvtColor(depth_map, cv2.COLOR_GRAY2BGR)
            out_path = os.path.join(self.cache_dir, f"depth_{i:05d}.png")
            cv2.imwrite(out_path, depth_map_3c)
            
            progress_val = int(((i + 1) / total_frames) * 100)
            self.progress_update.emit(self.node_id, progress_val, 100)

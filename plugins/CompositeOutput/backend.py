import os
import cv2
import numpy as np
import traceback
from PySide6.QtCore import QThread, Signal

# Import our new exporter
from plugins.CompositeOutput.colmap_exporter import read_cameras, read_images, read_points3D, export_to_nuke, export_to_blender
from plugins.CompositeOutput.roto_exporter import export_roto_to_nuke

from utvfx.bridge.base_worker import BaseWorker

class CompositeOutputWorker(BaseWorker):
    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(node_id, params, inputs, cache_dir, output_dir, parent)
        self.inputs = inputs
        self.rgba_path = inputs.get("Keyed RGBA")
        self.alpha_path = inputs.get("Alpha Matte")
        self.plate_path = inputs.get("Video Plate")
        self.depth_path = inputs.get("Dense Depth Map")
        self.tracking_path = inputs.get("3D Sparse Points") or inputs.get("3D Camera Path")
        self.shape_path = inputs.get("Shape Data")
        
        # Fallback if generic input key was passed or standard keys were missed
        if not any([self.rgba_path, self.alpha_path, self.plate_path, self.depth_path]):
            for k, val in inputs.items():
                if val and os.path.exists(str(val)) and os.path.isdir(str(val)) and k not in ["3D Sparse Points", "3D Camera Path", "Shape Data"]:
                    k_lower = k.lower()
                    if "alpha" in k_lower or "matte" in k_lower:
                        self.alpha_path = val
                    elif "depth" in k_lower:
                        self.depth_path = val
                    elif "plate" in k_lower or "video" in k_lower or "rgb" in k_lower:
                        self.plate_path = val
                    else:
                        self.rgba_path = val
                    break
        
        from utvfx.core.settings_manager import SettingsManager
        base_dir = SettingsManager().project_root
        default_out = os.path.join(base_dir, "workspace", "outputs")
        self.output_dir = params.get("output_dir", default_out)
        if not os.path.isabs(self.output_dir):
            self.output_dir = os.path.join(base_dir, "workspace", self.output_dir)

    def cancel(self):
        self.is_cancelled = True

    def _export_image_sequence(self, input_dir, subfolder_name, bit_depth, gamma):
        if not input_dir or not os.path.exists(str(input_dir)) or not os.path.isdir(str(input_dir)):
            return 0
            
        target_dir = os.path.join(self.output_dir, subfolder_name)
        os.makedirs(target_dir, exist_ok=True)
        self.log_message.emit(self.node_id, f"Exporting {subfolder_name} sequence to: {target_dir}")
        
        frames = sorted([f for f in os.listdir(str(input_dir)) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.exr', '.tif'))])
        total_frames = len(frames)
        if total_frames == 0:
            return 0
            
        os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
        for i, frame_name in enumerate(frames):
            if self.is_cancelled:
                self.log_message.emit(self.node_id, f"Export cancelled during {subfolder_name}.")
                return i
                
            frame_path = os.path.join(str(input_dir), frame_name)
            img = cv2.imread(frame_path, cv2.IMREAD_UNCHANGED)
            if img is None:
                continue
                
            is_float = (img.dtype == np.float32 or img.dtype == np.float64)
            if not is_float:
                max_val = 65535.0 if img.dtype == np.uint16 else 255.0
                img_float = img.astype(np.float32) / max_val
            else:
                img_float = img.copy()
                
            base_name = os.path.splitext(frame_name)[0]
            
            if "8-bit PNG" in bit_depth:
                img_display = np.power(np.clip(img_float, 0.0, 1.0), 1.0 / gamma)
                out_path = os.path.join(target_dir, f"{base_name}.png")
                img_out = np.clip(img_display * 255.0, 0, 255).astype(np.uint8)
                cv2.imwrite(out_path, img_out)
            else:
                # Default to EXR (16-bit Float EXR or 32-bit Float EXR) for VFX compositing workflows
                out_path = os.path.join(target_dir, f"{base_name}.exr")
                if "32-bit" in bit_depth:
                    img_out = img_float.astype(np.float32)
                else:
                    img_out = img_float.astype(np.float16)
                cv2.imwrite(out_path, img_out.astype(np.float32) if img_out.dtype == np.float16 else img_out)
                
            self.progress_update.emit(self.node_id, i + 1, total_frames)
            
        self.log_message.emit(self.node_id, f"Saved {total_frames} frames to {subfolder_name}/")
        return total_frames

    def run_task(self):
        self.log_message.emit(self.node_id, "Initializing Unified Output render...")
        os.makedirs(self.output_dir, exist_ok=True)
        self.log_message.emit(self.node_id, f"Output directory resolved to: {self.output_dir}")

        # 1. Process 3D Tracking Data
        if self.tracking_path and os.path.exists(self.tracking_path):
            self.log_message.emit(self.node_id, "Found 3D tracking data. Processing...")
            tracking_dir = os.path.join(self.output_dir, "tracking")
            os.makedirs(tracking_dir, exist_ok=True)
            sparse_dir = os.path.join(self.tracking_path, "sparse", "0")
            if os.path.exists(sparse_dir):
                cameras_file = os.path.join(sparse_dir, "cameras.txt")
                images_file = os.path.join(sparse_dir, "images.txt")
                points_file = os.path.join(sparse_dir, "points3D.txt")
                
                if os.path.exists(cameras_file) and os.path.exists(images_file) and os.path.exists(points_file):
                    self.log_message.emit(self.node_id, "Reading COLMAP data...")
                    cameras = read_cameras(cameras_file)
                    images = read_images(images_file)
                    points = read_points3D(points_file)
                    
                    scale = float(self.params.get("scene_scale", 10.0))
                    
                    if self.params.get("export_nuke", True):
                        nk_path = os.path.join(tracking_dir, "tracked_camera.nk")
                        export_to_nuke(cameras, images, points, nk_path, scale)
                        self.log_message.emit(self.node_id, f"Exported Nuke script to {nk_path}")
                        
                    if self.params.get("export_blender", True):
                        py_path = os.path.join(tracking_dir, "blender_import.py")
                        export_to_blender(cameras, images, points, py_path, scale)
                        self.log_message.emit(self.node_id, f"Exported Blender script to {py_path}")
                else:
                    self.log_message.emit(self.node_id, "Tracking data is incomplete. Did the mapper finish successfully?")
                    
        # 1.5 Process Shape Data (Roto to Shape)
        if self.shape_path and os.path.exists(self.shape_path):
            if self.params.get("export_roto_nuke", True):
                self.log_message.emit(self.node_id, "Found Roto Shape data. Exporting Nuke Roto generator (.nk)...")
                roto_dir = os.path.join(self.output_dir, "roto")
                os.makedirs(roto_dir, exist_ok=True)
                shapes_json = os.path.join(self.shape_path, "shapes.json")
                if os.path.exists(shapes_json):
                    nk_script = os.path.join(roto_dir, "roto_shapes.nk")
                    interp_mode = self.params.get("roto_interpolation", "Linear")
                    export_roto_to_nuke(shapes_json, nk_script, interp_mode)
                    self.log_message.emit(self.node_id, f"Exported Nuke Roto to {nk_script}")
                    try:
                        import shutil
                        dest_json = os.path.join(roto_dir, "shapes.json")
                        if os.path.abspath(shapes_json) != os.path.abspath(dest_json):
                            shutil.copy2(shapes_json, dest_json)
                    except Exception as e:
                        self.log_message.emit(self.node_id, f"Note: could not copy shapes.json to roto folder: {e}")
        
        # 2. Process Image Sequences (Comp, Alpha, Plate, Depth, and Separate Layers)
        gamma = float(self.params.get("gamma", 2.2))
        bit_depth = self.params.get("bit_depth", "16-bit Float EXR")
        
        if self.rgba_path:
            self._export_image_sequence(self.rgba_path, "comp", bit_depth, gamma)
        if self.alpha_path:
            self._export_image_sequence(self.alpha_path, "alpha", bit_depth, gamma)
        if self.plate_path:
            self._export_image_sequence(self.plate_path, "plate", bit_depth, gamma)
        if self.depth_path:
            self._export_image_sequence(self.depth_path, "depth", bit_depth, gamma)
            
        processed_dirs = {self.rgba_path, self.alpha_path, self.plate_path, self.depth_path, self.tracking_path, self.shape_path}
        for k, val in self.inputs.items():
            if val and val not in processed_dirs and os.path.exists(str(val)) and os.path.isdir(str(val)):
                clean_folder = str(k).lower().replace(" ", "_").replace("/", "_")
                self._export_image_sequence(val, clean_folder, bit_depth, gamma)

        self.log_message.emit(self.node_id, "Unified Output Complete!")

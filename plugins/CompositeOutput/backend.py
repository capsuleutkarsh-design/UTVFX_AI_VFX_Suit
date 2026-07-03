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
        self.input_path = inputs.get("Keyed RGBA") or inputs.get("Alpha Matte") or inputs.get("Video Plate")
        self.tracking_path = inputs.get("3D Sparse Points")
        self.shape_path = inputs.get("Shape Data")
        
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        default_out = os.path.join(base_dir, "outputs")
        self.output_dir = params.get("output_dir", default_out)
        if not os.path.isabs(self.output_dir):
            self.output_dir = os.path.join(base_dir, self.output_dir)

    def cancel(self):
        self.is_cancelled = True

    def run_task(self):
        self.log_message.emit(self.node_id, "Initializing Unified Output render...")
        os.makedirs(self.output_dir, exist_ok=True)
        self.log_message.emit(self.node_id, f"Output directory resolved to: {self.output_dir}")

        # 1. Process 3D Tracking Data
        if self.tracking_path and os.path.exists(self.tracking_path):
            self.log_message.emit(self.node_id, "Found 3D tracking data. Processing...")
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
                        nk_path = os.path.join(self.output_dir, "tracked_camera.nk")
                        export_to_nuke(cameras, images, points, nk_path, scale)
                        self.log_message.emit(self.node_id, f"Exported Nuke script to {nk_path}")
                        
                    if self.params.get("export_blender", True):
                        py_path = os.path.join(self.output_dir, "blender_import.py")
                        export_to_blender(cameras, images, points, py_path, scale)
                        self.log_message.emit(self.node_id, f"Exported Blender script to {py_path}")
                else:
                    self.log_message.emit(self.node_id, "Tracking data is incomplete. Did the mapper finish successfully?")
                    
        # 1.5 Process Shape Data (Roto to Shape)
        if self.shape_path and os.path.exists(self.shape_path):
            if self.params.get("export_roto_nuke", True):
                self.log_message.emit(self.node_id, "Found Roto Shape data. Exporting Python script for Nuke...")
                shapes_json = os.path.join(self.shape_path, "shapes.json")
                if os.path.exists(shapes_json):
                    py_script = os.path.join(self.output_dir, "import_roto_to_nuke.py")
                    export_roto_to_nuke(shapes_json, py_script)
                    self.log_message.emit(self.node_id, f"Exported Roto Python Script to {py_script}")
        
        # 2. Process Image Data
        if self.input_path and os.path.exists(self.input_path) and os.path.isdir(self.input_path):
            frames = sorted([f for f in os.listdir(self.input_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.exr', '.tif'))])
            total_frames = len(frames)
            
            if total_frames > 0:
                gamma = float(self.params.get("gamma", 2.2))
                bit_depth = self.params.get("bit_depth", "16-bit Float EXR")
                
                self.log_message.emit(self.node_id, f"Rendering {total_frames} frames. Gamma: {gamma}, Format: {bit_depth}")

                os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"

                for i, frame_name in enumerate(frames):
                    if self.is_cancelled:
                        self.log_message.emit(self.node_id, "Render cancelled by user.")
                        return

                    frame_path = os.path.join(self.input_path, frame_name)
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
                        out_path = os.path.join(self.output_dir, f"{base_name}.png")
                        img_out = np.clip(img_display * 255.0, 0, 255).astype(np.uint8)
                        cv2.imwrite(out_path, img_out)
                    
                    elif "16-bit" in bit_depth or "32-bit" in bit_depth:
                        # Ensure no gamma applied to floating point EXRs (keep linear for compositing)
                        out_path = os.path.join(self.output_dir, f"{base_name}.exr")
                        
                        if "16-bit" in bit_depth:
                            img_out = img_float.astype(np.float16)
                            cv2.imwrite(out_path, img_out.astype(np.float32))
                        else:
                            img_out = img_float.astype(np.float32)
                            cv2.imwrite(out_path, img_out)
                            
                    self.progress_update.emit(self.node_id, i + 1, total_frames)

                self.log_message.emit(self.node_id, f"Sequence Render Complete! Saved {total_frames} frames.")

        self.log_message.emit(self.node_id, "Unified Output Complete!")

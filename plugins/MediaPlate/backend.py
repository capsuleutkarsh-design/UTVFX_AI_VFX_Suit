import os
import cv2
import numpy as np
import shutil
from utvfx.bridge.base_worker import BaseWorker

class MediaWorker(BaseWorker):
    """
    Executes the Media Plate node to generate an optimized 8-bit PNG sequence.
    This acts as a proxy cache for downstream AI nodes, preventing them from
    having to repeatedly load and tone-map heavy EXR sequences or decode MP4s.
    """

    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(node_id, params, inputs, cache_dir, output_dir, parent)
        self.plate_file = params.get("plate_file", "")
        self.is_sequence = params.get("is_sequence", False)

    def cancel(self):
        self.is_cancelled = True

    def run_task(self):
        import json
        import glob
        
        if not self.plate_file or not os.path.exists(self.plate_file):
            raise FileNotFoundError("Media Plate has no valid file selected.")

        self.log_message.emit(self.node_id, f"Initializing Proxy Sequence Generation for: {self.plate_file}")
        
        # Determine shot name and expected frames early
        shot_name = os.path.basename(self.plate_file.rstrip('/\\'))
        if self.is_sequence and os.path.isfile(self.plate_file):
            media_dir = os.path.dirname(self.plate_file)
            files = sorted([f for f in os.listdir(media_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.exr', '.dpx', '.hdr'))])
            total_frames = len(files)
            
            def frame_generator():
                from utvfx.core.image_utils import load_frame
                for f in files:
                    yield load_frame(os.path.join(media_dir, f))
                    
            generator = frame_generator()
        else:
            ext = os.path.splitext(self.plate_file)[1].lower()
            if ext in [".png", ".jpg", ".jpeg", ".exr", ".dpx", ".tif", ".tiff", ".hdr"]:
                total_frames = 1
                def frame_generator():
                    from utvfx.core.image_utils import load_frame
                    yield load_frame(self.plate_file)
                generator = frame_generator()
            else:
                cap = cv2.VideoCapture(self.plate_file)
                if not cap.isOpened():
                    import imageio
                    try:
                        reader = imageio.get_reader(self.plate_file)
                        try:
                            total_frames = reader.count_frames()
                        except Exception:
                            total_frames = reader.get_meta_data().get('nframes', 0)
                        def frame_generator():
                            for frame_rgb in reader:
                                yield cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                        generator = frame_generator()
                    except Exception:
                        raise Exception(f"Failed to open video file: {self.plate_file}")
                else:
                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    def frame_generator():
                        while True:
                            ret, frame = cap.read()
                            if not ret: break
                            yield frame
                        cap.release()
                    generator = frame_generator()

        if total_frames <= 0:
            raise Exception("No readable frames found in media.")
            
        out_folder = os.path.join(self.cache_dir, "Video Plate")
        out_folder_jpg = os.path.join(self.cache_dir, "Video Plate JPG")
        info_file = os.path.join(self.cache_dir, "info.json")
        
        # Check cache
        if os.path.exists(info_file) and os.path.exists(out_folder) and os.path.exists(out_folder_jpg):
            try:
                with open(info_file, 'r') as f:
                    info = json.load(f)
                if info.get("plate_file") == self.plate_file and info.get("total_frames") == total_frames:
                    png_count = len(glob.glob(os.path.join(out_folder, "*.png")))
                    jpg_count = len(glob.glob(os.path.join(out_folder_jpg, "*.jpg")))
                    if png_count == total_frames and jpg_count == total_frames:
                        self.log_message.emit(self.node_id, f"Valid cache found for shot '{shot_name}'. Skipping generation.")
                        self.progress_update.emit(self.node_id, 100, 100)
                        return
            except Exception as e:
                self.log_message.emit(self.node_id, f"Cache check failed, regenerating: {e}")
                
        # Cache invalid or missing, proceed with generation
        if os.path.exists(out_folder):
            shutil.rmtree(out_folder)
        os.makedirs(out_folder, exist_ok=True)
        
        if os.path.exists(out_folder_jpg):
            shutil.rmtree(out_folder_jpg)
        os.makedirs(out_folder_jpg, exist_ok=True)
        
        with open(info_file, 'w') as f:
            json.dump({"plate_file": self.plate_file, "shot_name": shot_name, "total_frames": total_frames}, f)
            


        for i, frame in enumerate(generator):
            if self.is_cancelled:
                self.log_message.emit(self.node_id, "Media pre-processing cancelled.")
                break
                
            if frame is None:
                self.log_message.emit(self.node_id, f"Warning: Frame {i} is empty/corrupt. Skipping.")
                continue

            # Save PNG
            out_path = os.path.join(out_folder, f"frame_{i:06d}.png")
            cv2.imwrite(out_path, frame)
            
            # Save JPG
            out_path_jpg = os.path.join(out_folder_jpg, f"frame_{i:06d}.jpg")
            cv2.imwrite(out_path_jpg, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            
            progress_val = int(((i + 1) / total_frames) * 100)
            self.progress_update.emit(self.node_id, progress_val, 100)

        self.log_message.emit(self.node_id, "Proxy sequence generation complete.")

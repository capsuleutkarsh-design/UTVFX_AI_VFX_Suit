import os
import cv2
import numpy as np
from utvfx.bridge.base_worker import BaseWorker

class GradeWorker(BaseWorker):
    def run_task(self):
        self.progress_update.emit(self.node_id, 0, 100)
        
        # Get parameters
        blackpoint = float(self.params.get("blackpoint", 0.0))
        whitepoint = float(self.params.get("whitepoint", 1.0))
        lift = float(self.params.get("lift", 0.0))
        gain = float(self.params.get("gain", 1.0))
        multiply = float(self.params.get("multiply", 1.0))
        offset = float(self.params.get("offset", 0.0))
        gamma = float(self.params.get("gamma", 1.0))
        
        # Resolve input media
        input_media = self.inputs.get("Image")
        if not input_media or not os.path.exists(input_media):
            raise Exception("No upstream media found to grade.")
            
        is_sequence = os.path.isdir(input_media)
        if is_sequence:
            files = sorted([f for f in os.listdir(input_media) if os.path.isfile(os.path.join(input_media, f))])
            if not files:
                raise Exception("Input directory is empty.")
        else:
            files = [os.path.basename(input_media)]
            input_media = os.path.dirname(input_media)
            
        total = len(files)
        
        # Calculate grade constants
        A = multiply * (gain - lift) / max(whitepoint - blackpoint, 1e-5)
        B = offset + lift - A * blackpoint
        gamma_inv = 1.0 / max(gamma, 1e-5)
        
        import concurrent.futures
        
        cv2.setNumThreads(0)  # Prevent OpenCV internal thread thrashing
        
        def process_frame(f):
            if self.is_cancelled:
                return False, None
                
            if "OPENCV_IO_ENABLE_OPENEXR" not in os.environ:
                os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
            os.environ["OPENCV_IO_MAX_THREADS"] = "1" # Prevent OpenEXR thread explosion
            
            in_path = os.path.join(input_media, f)
            out_path = os.path.join(self.cache_dir, f)
            
            img = cv2.imread(in_path, cv2.IMREAD_UNCHANGED)
            if img is None:
                return False, f"Failed to read {f}"
                
            is_float = img.dtype in [np.float32, np.float64]
            is_16bit = img.dtype == np.uint16
            
            if not is_float:
                if is_16bit:
                    img_f = img.astype(np.float32) / 65535.0
                else:
                    img_f = img.astype(np.float32) / 255.0
            else:
                img_f = img.astype(np.float32)
                
            out = A * img_f + B
            
            if gamma != 1.0:
                out = np.where(out > 0, np.power(out, gamma_inv), 0)
                
            if not is_float:
                if is_16bit:
                    out = np.clip(out * 65535.0, 0, 65535).astype(np.uint16)
                else:
                    out = np.clip(out * 255.0, 0, 255).astype(np.uint8)
                    
            cv2.imwrite(out_path, out)
            return True, None
            
        completed = 0
        
        # Limit to 6 workers to prevent disk I/O bottleneck and thread explosion
        workers = min(6, os.cpu_count() or 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(process_frame, f) for f in files]
            for future in concurrent.futures.as_completed(futures):
                if self.is_cancelled:
                    self.log_message.emit(self.node_id, "Grade cancelled by user.")
                    break
                success, error_msg = future.result()
                if not success and error_msg:
                    self.log_message.emit(self.node_id, error_msg)
                completed += 1
                if completed % max(1, total // 20) == 0 or completed == total:
                    pct = int(completed / total * 100)
                    self.progress_update.emit(self.node_id, pct, 100)
            
        self.log_message.emit(self.node_id, "Grading completed.")

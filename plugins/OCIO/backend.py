import os
import OpenImageIO as oiio
from utvfx.bridge.base_worker import BaseWorker

class OCIOWorker(BaseWorker):
    def run_task(self):
        self.progress_update.emit(self.node_id, 0, 100)
        
        # Get parameters
        in_space = self.params.get("in_space", "linear")
        out_space = self.params.get("out_space", "sRGB")
        
        if in_space == out_space:
            self.log_message.emit(self.node_id, "Input and Output color spaces are the same. No conversion needed.")
            
        # Resolve input media
        input_media = self.inputs.get("Image")
        if not input_media or not os.path.exists(input_media):
            raise Exception("No upstream media found to convert.")
            
        is_sequence = os.path.isdir(input_media)
        if is_sequence:
            files = sorted([f for f in os.listdir(input_media) if os.path.isfile(os.path.join(input_media, f))])
            if not files:
                raise Exception("Input directory is empty.")
        else:
            files = [os.path.basename(input_media)]
            input_media = os.path.dirname(input_media)
            
        total = len(files)
        
        import concurrent.futures
        import shutil
        
        def process_frame(f):
            if self.is_cancelled:
                return False, None
                
            in_path = os.path.join(input_media, f)
            out_path = os.path.join(self.cache_dir, f)
            
            if in_space == out_space:
                shutil.copy2(in_path, out_path)
                return True, None
            
            buf = oiio.ImageBuf(in_path)
            if buf.has_error:
                return False, f"Failed to read {f}: {buf.geterror()}"
            
            # Apply Color Convert
            success = oiio.ImageBufAlgo.colorconvert(buf, buf, in_space, out_space)
            if not success:
                return False, f"Color conversion failed for {f}: {oiio.geterror()}"
            
            # Write out
            buf.write(out_path)
            return True, None
            
        completed = 0
        
        # Limit to 6 workers to prevent disk I/O bottleneck
        # and limit internal OIIO threads per frame
        oiio.attribute("threads", 1)
        workers = min(6, os.cpu_count() or 4)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(process_frame, f) for f in files]
            for future in concurrent.futures.as_completed(futures):
                if self.is_cancelled:
                    self.log_message.emit(self.node_id, "OCIO conversion cancelled by user.")
                    break
                success, error_msg = future.result()
                if not success and error_msg:
                    self.log_message.emit(self.node_id, error_msg)
                completed += 1
                if completed % max(1, total // 20) == 0 or completed == total:
                    pct = int(completed / total * 100)
                    self.progress_update.emit(self.node_id, pct, 100)
                    
        self.log_message.emit(self.node_id, "OCIO Conversion completed.")

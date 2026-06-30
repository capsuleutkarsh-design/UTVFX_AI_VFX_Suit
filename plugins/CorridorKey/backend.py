import os
import sys
from PySide6.QtCore import QThread, Signal

# Ensure CorridorKey/System is in path for imports
CURRENT_DIR = os.path.dirname(__file__)
SYSTEM_DIR = os.path.join(CURRENT_DIR, "System")
if SYSTEM_DIR not in sys.path:
    sys.path.append(SYSTEM_DIR)

# Deferred import to prevent main thread freeze
# from clip_manager import ClipAsset, ClipEntry, InferenceSettings, run_inference, run_birefnet

class CorridorKeyWorker(QThread):
    progress_update = Signal(int, int)
    log_message = Signal(str)
    finished_processing = Signal()
    error_occurred = Signal(str)

    def __init__(self, video_path, mask_path, output_dir, params):
        super().__init__()
        self.video_path = video_path
        self.mask_path = mask_path
        self.output_dir = output_dir
        self.params = params
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def _get_asset_type(self, path):
        if os.path.isdir(path):
            return "sequence"
        ext = os.path.splitext(path)[1].lower()
        if ext in ['.mp4', '.mov', '.avi', '.mkv']:
            return "video"
        return "sequence"

    def run(self):
        try:
            from clip_manager import ClipAsset, ClipEntry, InferenceSettings, run_inference, run_birefnet
            import logging
            
            # Setup logging to route to UI
            class UISignalHandler(logging.Handler):
                def __init__(self, signal):
                    super().__init__()
                    self.signal = signal
                def emit(self, record):
                    msg = self.format(record)
                    self.signal.emit(msg)
            
            ui_handler = UISignalHandler(self.log_message)
            ui_handler.setFormatter(logging.Formatter('%(message)s'))
            ui_handler.setLevel(logging.INFO)
            
            # Add to root logger to capture all module logs
            root_logger = logging.getLogger()
            root_logger.setLevel(logging.INFO)
            root_logger.addHandler(ui_handler)

            if not self.video_path or not os.path.exists(self.video_path):
                raise FileNotFoundError("Video path is invalid or missing.")

            self.log_message.emit("Initializing CorridorKey pipeline...")
            
            # 1. Create a dummy ClipEntry mapping to our node's cache directory
            clip = ClipEntry("NodeExecution", self.output_dir)
            clip.input_asset = ClipAsset(self.video_path, self._get_asset_type(self.video_path))
            
            # Callbacks for progress tracking
            def on_frame(current, total):
                if self.is_cancelled:
                    raise InterruptedError("Execution cancelled by user.")
                # clip_manager emits current frame, we update UI
                self.progress_update.emit(current, total)
                
            def on_start(name, total):
                self.log_message.emit(f"Processing {name}: {total} frames")

            # 2. Check for mask or generate Auto-Matte
            if self.mask_path and os.path.exists(self.mask_path):
                clip.alpha_asset = ClipAsset(self.mask_path, self._get_asset_type(self.mask_path))
            else:
                self.log_message.emit("No mask provided. Generating auto-matte using BiRefNet...")
                # run_birefnet automatically writes to clip.root_path / "AlphaHint"
                run_birefnet(
                    [clip],
                    device=None,
                    usage="General",
                    dilate_radius=0,
                    on_clip_start=on_start,
                    on_frame_complete=on_frame
                )
                
                # Check if generation succeeded
                alpha_dir = os.path.join(self.output_dir, "AlphaHint")
                if not os.path.exists(alpha_dir) or not os.listdir(alpha_dir):
                    raise RuntimeError("BiRefNet auto-matte generation failed.")
                    
                clip.alpha_asset = ClipAsset(alpha_dir, "sequence")

            # 3. Setup settings
            settings = InferenceSettings(
                input_is_linear=self.params.get("input_is_linear", False),
                despill_strength=float(self.params.get("despill_strength", 0.5)),
                auto_despeckle=self.params.get("auto_despeckle", True),
                despeckle_size=int(self.params.get("despeckle_size", 400)),
                refiner_scale=float(self.params.get("refiner_scale", 1.0)),
                generate_comp=self.params.get("generate_comp", True),
                gpu_post_processing=self.params.get("gpu_post_processing", False),
                image_size=int(self.params.get("image_size", 2048)),
                screen_color=self.params.get("screen_color", "auto")
            )

            # 4. Run Inference
            self.log_message.emit("Running CorridorKey core inference...")
            run_inference(
                [clip],
                device=None,
                backend="torch",
                settings=settings,
                on_clip_start=on_start,
                on_frame_complete=on_frame
            )
            
            self.log_message.emit("CorridorKey pipeline complete.")
            self.finished_processing.emit()
            
        except InterruptedError as ie:
            self.error_occurred.emit(str(ie))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error_occurred.emit(str(e))

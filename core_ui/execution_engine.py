import os
import shutil
import importlib
from PySide6.QtCore import QObject, Signal, Slot
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)


class ExecutionEngine(QObject):
    """Orchestrates node execution, manages caching, and routes data."""
    log_message = Signal(str, str) # node_id, message
    node_execution_started = Signal(str)
    node_execution_progress = Signal(str, int) # node_id, percentage
    node_execution_finished = Signal(str)
    interactive_mask_ready = Signal(str, int, object) # node_id, frame_idx, QImage

    def __init__(self, scene):
        super().__init__()
        from core_ui.settings_manager import SettingsManager
        self.scene = scene
        self.cache_dir = SettingsManager().get("cache_dir", os.path.join(BASE_DIR, "cache"))
        os.makedirs(self.cache_dir, exist_ok=True)
        self.active_workers = {}
        self.execution_queue = []
        self.is_executing_pipeline = False

    def _build_execution_graph(self, target_node):
        visited = set()
        sorted_nodes = []
        
        def dfs(n):
            if n.node_id in visited:
                return
            visited.add(n.node_id)
            for upstream in self._get_upstream_nodes(n):
                dfs(upstream)
            sorted_nodes.append(n)
            
        dfs(target_node)
        return sorted_nodes

    def _get_node_by_id(self, node_id):
        for node in self.scene.nodes:
            if node.node_id == node_id:
                return node
        return None

    @Slot(str, int, list)
    def handle_interaction(self, node_id, frame_idx, points):
        node = self._get_node_by_id(node_id)
        if not node: return
        
        self.log_message.emit(node_id, f"Processing interaction: {len(points)} points on frame {frame_idx}...")
        
        media_path = self._resolve_media_input(node)
        if not media_path or not os.path.exists(media_path):
            self.log_message.emit(node_id, "Interaction failed: No media connected.")
            return
            
        import cv2
        import tempfile
        
        # Extract the exact frame requested
        import uuid
        temp_frame_path = os.path.join(TEMP_DIR, f"utvfx_current_frame_{uuid.uuid4().hex}.jpg")
        
        if os.path.isdir(media_path):
            # Sequence
            files = sorted([f for f in os.listdir(media_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.exr', '.dpx', '.hdr'))])
            if 0 <= frame_idx < len(files):
                frame_file = os.path.join(media_path, files[frame_idx])
                
                # Attempt to read properly, including EXR/HDR via OIIO or OpenCV
                ext = os.path.splitext(frame_file)[1].lower()
                frame = None
                
                try:
                    import OpenImageIO as oiio
                    buf = oiio.ImageBuf(frame_file)
                    if not buf.has_error:
                        if ext in [".exr", ".dpx", ".hdr"]:
                            oiio.ImageBufAlgo.colorconvert(buf, buf, "linear", "sRGB")
                        raw_frame = buf.get_pixels(oiio.TypeFloat)
                        if raw_frame is not None:
                            raw_frame = np.clip(raw_frame, 0.0, 1.0)
                            raw_frame = (raw_frame * 255.0).astype(np.uint8)
                            if len(raw_frame.shape) == 2 or (len(raw_frame.shape) == 3 and raw_frame.shape[2] == 1):
                                frame = cv2.cvtColor(raw_frame, cv2.COLOR_GRAY2BGR)
                            elif len(raw_frame.shape) == 3 and raw_frame.shape[2] == 4:
                                frame = cv2.cvtColor(raw_frame, cv2.COLOR_RGBA2BGR)
                            elif len(raw_frame.shape) == 3 and raw_frame.shape[2] >= 3:
                                frame = cv2.cvtColor(raw_frame[:, :, :3], cv2.COLOR_RGB2BGR)
                except ImportError:
                    pass
                    
                if frame is None:
                    frame = cv2.imread(frame_file, cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
                    if frame is not None:
                        if frame.dtype == np.float32 or frame.dtype == np.float64:
                            frame = np.clip(frame, 0.0, 1.0)
                            if ext in [".exr", ".hdr"]:
                                frame = np.power(frame, 1.0/2.2)
                            frame = (frame * 255.0).astype(np.uint8)
                        elif frame.dtype == np.uint16:
                            frame = (frame / 256).astype(np.uint8)
                            
                if frame is not None:
                    cv2.imwrite(temp_frame_path, frame)
                else:
                    self.log_message.emit(node_id, "Failed to load interactive frame.")
                    return
            else:
                self.log_message.emit(node_id, "Interactive frame index out of bounds.")
                return
        else:
            # Video
            cap = cv2.VideoCapture(media_path)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if ret:
                cv2.imwrite(temp_frame_path, frame)
            cap.release()
            if not ret: 
                self.log_message.emit(node_id, "Failed to capture video frame for interaction.")
                return
        
        plugin_type = node.plugin_type
        mask_qimage = None
        
        self.log_message.emit(node_id, "Querying AI Bridge for fast preview mask...")
        if plugin_type == "sam3_rotoscope":
            from plugins.SAM3Rotoscope.backend import run_fast_preview
            mask_qimage = run_fast_preview(node.params, frame_idx, points, temp_frame_path)
        elif plugin_type == "matte_anyone":
            from plugins.MatAnyone2.backend import run_fast_preview
            mask_qimage = run_fast_preview(node.params, frame_idx, points, temp_frame_path)
            
        if mask_qimage is not None:
            self.log_message.emit(node_id, "Fast preview generated successfully.")
            self.interactive_mask_ready.emit(node_id, frame_idx, mask_qimage)
        else:
            self.log_message.emit(node_id, "AI Engine failed to generate preview mask.")

    def _get_node_cache(self, node):
        return os.path.join(self.cache_dir, node.node_id)

    def _get_upstream_nodes(self, node):
        upstream_nodes = []
        for port in getattr(node, "inputs", []):
            for conn in getattr(port, "connections", []):
                upstream_port = conn.port1 if conn.port1 != port else conn.port2
                if upstream_port and upstream_port.node not in upstream_nodes:
                    upstream_nodes.append(upstream_port.node)
        return upstream_nodes

    def _compute_node_hash(self, node):
        import hashlib, json
        hasher = hashlib.md5()
        hasher.update(str(node.plugin_type).encode('utf-8'))
        
        # Serialize node parameters
        params = getattr(node, "params", {})
        try:
            params_str = json.dumps(params, sort_keys=True)
        except Exception:
            params_str = str(params)
        hasher.update(params_str.encode('utf-8'))
        
        # Incorporate hashes of all upstream dependencies so downstream nodes invalidate
        # if any upstream input changes.
        for upstream in self._get_upstream_nodes(node):
            hasher.update(self._compute_node_hash(upstream).encode('utf-8'))
            
        return hasher.hexdigest()


    def _get_cached_output(self, node, preferred_dirs=None):
        node_cache = self._get_node_cache(node)
        preferred_dirs = preferred_dirs or ["fgr", "pha", "Comp", "FG", "Matte", "AlphaHint"]

        for dirname in preferred_dirs:
            candidate = os.path.join(node_cache, dirname)
            if os.path.isdir(candidate) and os.listdir(candidate):
                return candidate

        if os.path.isdir(node_cache):
            files = [
                os.path.join(node_cache, name)
                for name in os.listdir(node_cache)
                if os.path.isfile(os.path.join(node_cache, name))
            ]
            if files:
                return node_cache
        return None

    def _resolve_media_input(self, node, visited=None, is_start_node=True):
        if visited is None:
            visited = set()
        if node in visited:
            return None
        visited.add(node)

        params = getattr(node, "params", {})
        plate_file = params.get("plate_file")
        if getattr(node, "plugin_type", "") == "media_plate" and plate_file and os.path.exists(plate_file):
            if params.get("is_sequence", False) and os.path.isfile(plate_file):
                return os.path.dirname(plate_file)
            return plate_file

        if not is_start_node and not getattr(node, "is_disabled", False):
            cached_output = self._get_cached_output(node, ["fgr", "Comp", "FG"])
            if cached_output:
                return cached_output

        for upstream_node in self._get_upstream_nodes(node):
            media_path = self._resolve_media_input(upstream_node, visited, is_start_node=False)
            if media_path:
                return media_path
        return None

    def _resolve_alpha_input(self, node, visited=None, is_start_node=True):
        if visited is None:
            visited = set()
        if node in visited:
            return None
        visited.add(node)

        if not is_start_node and not getattr(node, "is_disabled", False):
            cached_alpha = self._get_cached_output(node, ["pha", "Matte", "AlphaHint"])
            if cached_alpha:
                return cached_alpha

        for upstream_node in self._get_upstream_nodes(node):
            alpha_path = self._resolve_alpha_input(upstream_node, visited, is_start_node=False)
            if alpha_path:
                return alpha_path
        return None

    def _resolve_tracking_input(self, node, visited=None, is_start_node=True):
        if visited is None:
            visited = set()
        if node in visited:
            return None
        visited.add(node)

        if not is_start_node and not getattr(node, "is_disabled", False):
            # For sfm_tracker, we want the base cache dir because it contains 'sparse' and 'database.db'
            if getattr(node, "plugin_type", "") == "sfm_tracker":
                cache_dir = self._get_node_cache(node)
                if os.path.exists(os.path.join(cache_dir, "sparse")):
                    return cache_dir

        for upstream_node in self._get_upstream_nodes(node):
            track_path = self._resolve_tracking_input(upstream_node, visited, is_start_node=False)
            if track_path:
                return track_path
        return None

    def _resolve_shape_input(self, node, visited=None, is_start_node=True):
        if visited is None:
            visited = set()
        if node in visited:
            return None
        visited.add(node)

        if not is_start_node and not getattr(node, "is_disabled", False):
            if getattr(node, "plugin_type", "") == "roto_to_shape":
                cache_dir = self._get_node_cache(node)
                shape_dir = os.path.join(cache_dir, "roto_shapes")
                if os.path.exists(shape_dir):
                    return shape_dir

        for upstream_node in self._get_upstream_nodes(node):
            shape_path = self._resolve_shape_input(upstream_node, visited, is_start_node=False)
            if shape_path:
                return shape_path
        return None

    def _map_corridor_key_params(self, params):
        mapped = dict(params)
        if "clean_islands" in mapped:
            mapped["auto_despeckle"] = mapped["clean_islands"]
        if "despeckle_thresh" in mapped:
            mapped["despeckle_size"] = mapped["despeckle_thresh"]
        if "detail_intensity" in mapped:
            mapped["refiner_scale"] = mapped["detail_intensity"]
        if "proc_res" in mapped:
            mapped["image_size"] = mapped["proc_res"]
        return mapped

    def _build_mask_dict(self, mask_path, node_cache=None, mask_keyframes=None, video_path=None, node_id=None):
        import cv2
        import tempfile
        mask_dict = {}
        
        # 1. First, try to generate masks from interactive keyframes
        if node_cache and mask_keyframes:
            sam_masks_dir = os.path.join(node_cache, "sam_masks")
            os.makedirs(sam_masks_dir, exist_ok=True)
            
            from core_ui.ai_bridge_client import AIBridgeClient
            client = AIBridgeClient.get_instance()
            
            # For each keyframe, extract the frame and ask SAM to generate a mask
            for f_idx, points in mask_keyframes.items():
                if not points: continue
                
                if node_id:
                    self.log_message.emit(node_id, f"Generating high-quality SAM mask for keyframe {f_idx}...")
                
                f_idx = int(f_idx)
                import uuid
                temp_frame_path = os.path.join(TEMP_DIR, f"utvfx_gen_frame_{f_idx}_{uuid.uuid4().hex}.jpg")
                
                # Extract frame
                if os.path.isdir(video_path):
                    files = sorted([f for f in os.listdir(video_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.exr', '.dpx', '.hdr'))])
                    if 0 <= f_idx < len(files):
                        frame_file = os.path.join(video_path, files[f_idx])
                        frame = cv2.imread(frame_file, cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
                        if frame is not None:
                            if frame.dtype == np.float32 or frame.dtype == np.float64:
                                frame = np.clip(frame, 0.0, 1.0)
                                if frame_file.lower().endswith((".exr", ".hdr")):
                                    frame = np.power(frame, 1.0/2.2)
                                frame = (frame * 255.0).astype(np.uint8)
                            elif frame.dtype == np.uint16:
                                frame = (frame / 256).astype(np.uint8)
                            cv2.imwrite(temp_frame_path, frame)
                else:
                    cap = cv2.VideoCapture(video_path)
                    if not cap.isOpened():
                        import imageio
                        try:
                            reader = imageio.get_reader(video_path)
                            frame_rgb = reader.get_data(f_idx)
                            frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                            cv2.imwrite(temp_frame_path, frame)
                        except Exception as e:
                            self.log_message.emit(node_id, f"Failed to extract frame: {e}")
                    else:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
                        ret, frame = cap.read()
                        if ret:
                            cv2.imwrite(temp_frame_path, frame)
                        cap.release()
                    
                if not os.path.exists(temp_frame_path):
                    continue
                    
                # Setup points for AI Bridge
                img = cv2.imread(temp_frame_path)
                if img is None: continue
                h, w, _ = img.shape
                
                pts = []
                lbls = []
                for nx, ny, is_pos in points:
                    pts.append([int(nx * w), int(ny * h)])
                    lbls.append(1 if is_pos else 0)
                    
                out_mask_path = os.path.join(sam_masks_dir, f"mask_{f_idx:05d}.png")
                # Query AI Bridge
                client.query_mask(temp_frame_path, pts, lbls, out_mask_path=out_mask_path)
                
                # If generated successfully, load it into mask_dict
                if os.path.exists(out_mask_path):
                    mask = cv2.imread(out_mask_path, cv2.IMREAD_GRAYSCALE)
                    if mask is not None:
                        mask_dict[f_idx] = mask
                        
            if mask_dict:
                return mask_dict

        # 2. Check if there are ALREADY interactively generated masks from a previous run
        if node_cache:
            sam_masks_dir = os.path.join(node_cache, "sam_masks")
            if os.path.exists(sam_masks_dir):
                for name in os.listdir(sam_masks_dir):
                    if name.endswith(".png") and name.startswith("mask_"):
                        try:
                            frame_idx = int(name.split("_")[1].split(".")[0])
                            path = os.path.join(sam_masks_dir, name)
                            mask = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                            if mask is not None:
                                mask_dict[frame_idx] = mask
                        except Exception:
                            pass
                
                if mask_dict:
                    return mask_dict

        # 3. Fallback to manual mask path
        if not mask_path or not os.path.exists(mask_path):
            raise FileNotFoundError("Select a guide mask file before running MatteAnyone, or interactively generate one by selecting the object in the viewport.")

        if node_id:
            self.log_message.emit(node_id, f"Loading manual guide mask from: {mask_path}")

        import cv2
        mask_dict = {}
        image_exts = {".png", ".jpg", ".jpeg", ".exr", ".dpx", ".tif", ".tiff", ".hdr"}
        video_exts = {".mp4", ".mov", ".avi", ".mkv"}

        if os.path.isdir(mask_path):
            files = []
            for ext in image_exts:
                files.extend(os.path.join(mask_path, name) for name in os.listdir(mask_path) if name.lower().endswith(ext))
            for frame_idx, path in enumerate(sorted(files)):
                mask = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                if mask is not None:
                    mask_dict[frame_idx] = mask
        else:
            ext = os.path.splitext(mask_path)[1].lower()
            if ext in image_exts:
                mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
                if mask is not None:
                    mask_dict[0] = mask
            elif ext in video_exts:
                cap = cv2.VideoCapture(mask_path)
                if not cap.isOpened():
                    raise RuntimeError("Failed to open MatteAnyone guide mask video.")
                frame_idx = 0
                try:
                    while True:
                        ret, frame = cap.read()
                        if not ret:
                            break
                        mask_dict[frame_idx] = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        frame_idx += 1
                finally:
                    cap.release()
            else:
                raise ValueError(f"Unsupported MatteAnyone guide mask type: {ext}")

        if not mask_dict:
            raise RuntimeError("Guide mask contains no readable frames.")
        
        if node_id:
            self.log_message.emit(node_id, f"Successfully loaded {len(mask_dict)} mask frames.")
            
        return mask_dict

    def _prepare_tracker_input(self, media_path, node_cache):
        if not media_path or not os.path.exists(media_path):
            raise FileNotFoundError("Tracker input media is missing.")
        if os.path.isdir(media_path):
            return media_path

        image_exts = {".png", ".jpg", ".jpeg", ".exr", ".dpx", ".tif", ".tiff", ".hdr"}
        video_exts = {".mp4", ".mov", ".avi", ".mkv"}
        ext = os.path.splitext(media_path)[1].lower()
        image_dir = os.path.join(node_cache, "tracker_images")

        if os.path.exists(image_dir):
            shutil.rmtree(image_dir)
        os.makedirs(image_dir, exist_ok=True)

        if ext in image_exts:
            shutil.copy2(media_path, os.path.join(image_dir, os.path.basename(media_path)))
            return image_dir

        if ext in video_exts:
            import cv2
            cap = cv2.VideoCapture(media_path)
            if not cap.isOpened():
                raise RuntimeError("Failed to open tracker video input.")
            frame_idx = 0
            try:
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    cv2.imwrite(os.path.join(image_dir, f"frame_{frame_idx:06d}.png"), frame)
                    frame_idx += 1
            finally:
                cap.release()
            if frame_idx == 0:
                raise RuntimeError("Tracker video input has no readable frames.")
            return image_dir

        raise ValueError(f"Unsupported tracker input type: {ext}")

    def execute_node(self, node_id):
        target_node = self._get_node_by_id(node_id)
        if not target_node:
            return
            
        if self.is_executing_pipeline:
            self.log_message.emit(node_id, "A pipeline is already executing. Please cancel it first.")
            return

        sorted_nodes = self._build_execution_graph(target_node)
        
        # Build execution queue
        self.execution_queue = [n.node_id for n in sorted_nodes]
        self.is_executing_pipeline = True
        self.current_target_node_id = node_id
        
        self.log_message.emit(node_id, f"Pipeline queued with {len(self.execution_queue)} nodes. Starting execution...")
        self._pump_execution_queue()

    def _pump_execution_queue(self):
        if not self.execution_queue:
            self.is_executing_pipeline = False
            return
            
        next_node_id = self.execution_queue.pop(0)
        self._run_single_node(next_node_id)

    def _run_single_node(self, node_id):
        node = self._get_node_by_id(node_id)
        if not node:
            self._pump_execution_queue()
            return

        # Bypass disabled nodes
        if getattr(node, 'is_disabled', False):
            self.log_message.emit(node_id, f"Node {node.name} is bypassed. Skipping execution.")
            self._on_finished(node_id)
            return

        self.log_message.emit(node_id, f"Initializing execution for {node.name}...")
        self.node_execution_started.emit(node_id)
        
        # UX Improvement: Let the user know the target node is waiting on an upstream node
        if getattr(self, "current_target_node_id", None) and self.current_target_node_id != node_id:
            self.log_message.emit(self.current_target_node_id, f"[Waiting] Currently executing upstream node: {node.name}...")

        node_cache = self._get_node_cache(node)
        os.makedirs(node_cache, exist_ok=True)

        plugin = node.plugin_type
        params = getattr(node, "params", {})

        # --- Smart Cache Validation ---
        # Don't check cache for the root media_plate since it takes negligible time, 
        # and checking cache there might break initial resolution logging.
        if plugin != "media_plate":
            try:
                current_hash = self._compute_node_hash(node)
                hash_file = os.path.join(node_cache, "last_state_hash.txt")
                if os.path.exists(hash_file):
                    with open(hash_file, "r", encoding="utf-8") as f:
                        saved_hash = f.read().strip()
                        
                    # If state hashes match perfectly AND the output cache folder isn't empty, skip execution.
                    if saved_hash == current_hash and self._get_cached_output(node):
                        self.log_message.emit(node_id, f"[Cached] Output is already generated. Skipping execution for {node.name}.")
                        self._on_finished(node_id)
                        return
            except Exception as e:
                self.log_message.emit(node_id, f"Cache validation error: {e}. Forcing re-execution.")

        try:
            if plugin == "media_plate":
                self.log_message.emit(node_id, "Checking connected media plate...")
                media_path = self._resolve_media_input(node)
                if not media_path:
                    raise FileNotFoundError("Media Plate has no valid file selected.")
                self.log_message.emit(node_id, f"Media ready: {media_path}")
                self._on_finished(node_id)

            elif plugin == "matte_anyone":
                from plugins.MatAnyone2.backend import InferenceWorker
                
                self.log_message.emit(node_id, "Initializing MatteAnyone 2 Engine...")
                self.log_message.emit(node_id, "Resolving video inputs and building guide masks...")

                video_path = self._resolve_media_input(node)
                if not video_path:
                    raise FileNotFoundError("Connect a Media Plate before running MatteAnyone.")
                mask_dict = self._build_mask_dict(
                    params.get("mask_file"), 
                    node_cache, 
                    params.get("mask_keyframes", {}), 
                    video_path,
                    node_id
                )
                
                self.log_message.emit(node_id, f"Mask parsing complete. Starting background inference thread...")

                self.log_message.emit(node_id, f"Starting AI Inference. Cache: {node_cache} | Params: {params}")

                worker = InferenceWorker(video_path, mask_dict, node_cache, params)
                worker.progress_update.connect(lambda cur, tot: self._on_progress(node_id, cur, tot))
                worker.error_occurred.connect(lambda err, w=worker: self._on_error(node_id, err, w))
                if hasattr(worker, 'log_message'):
                    worker.log_message.connect(lambda msg: self.log_message.emit(node_id, msg))
                worker.finished_processing.connect(lambda w=worker: self._on_finished(node_id, w))

                self.active_workers[node_id] = worker
                worker.start()

            elif plugin == "corridor_keyer":
                from plugins.CorridorKey.backend import CorridorKeyWorker

                video_path = self._resolve_media_input(node)
                if not video_path:
                    raise FileNotFoundError("Connect a Media Plate before running CorridorKey.")
                mask_path = self._resolve_alpha_input(node)
                mapped_params = self._map_corridor_key_params(params)

                self.log_message.emit(node_id, f"Starting Keying Pipeline. Cache: {node_cache} | Params: {mapped_params}")
                worker = CorridorKeyWorker(video_path, mask_path, node_cache, mapped_params)

                worker.progress_update.connect(lambda cur, tot: self._on_progress(node_id, cur, tot))
                worker.log_message.connect(lambda msg: self.log_message.emit(node_id, msg))
                worker.error_occurred.connect(lambda err, w=worker: self._on_error(node_id, err, w))
                worker.finished_processing.connect(lambda w=worker: self._on_finished(node_id, w))

                self.active_workers[node_id] = worker
                worker.start()

            elif plugin == "sfm_tracker":
                tracker_module = importlib.import_module("plugins.3DTracker.backend")
                tracker_thread = tracker_module.TrackerThread

                media_path = self._resolve_media_input(node)
                tracker_input = self._prepare_tracker_input(media_path, node_cache)
                
                engine_choice = params.get("mapper_engine", "GLOMAP (Fast)")
                engine_str = "glomap" if "GLOMAP" in engine_choice else "colmap"

                self.log_message.emit(node_id, f"Starting 3D Camera Tracker ({engine_str}). Input: {tracker_input}")
                worker = tracker_thread(tracker_input, node_cache, params)

                worker.progress_update.connect(lambda cur, tot: self._on_progress(node_id, cur, tot))
                worker.log_message.connect(lambda msg: self.log_message.emit(node_id, msg))
                worker.log_output.connect(lambda msg: self.log_message.emit(node_id, msg))
                worker.finished_processing.connect(lambda w=worker: self._on_finished(node_id, w))
                worker.finished_sig.connect(lambda ok, w=worker: self._on_error(node_id, "COLMAP tracker failed.", w) if not ok else None)

                self.active_workers[node_id] = worker
                worker.start()



            elif plugin == "sam3_rotoscope":
                from plugins.SAM3Rotoscope.backend import SAM3Worker
                
                media_path = self._resolve_media_input(node)
                
                # Fetch keyframes from UI if available. We can access them via main_window reference
                # if we had one, but for mock purposes we'll simulate it being passed.
                # In actual implementation, node could store the keyframes in its params.
                keyframes = node.params.get("mask_keyframes", {})
                
                self.log_message.emit(node_id, f"Initializing SAM 3 interactive engine. Input: {media_path}")
                worker = SAM3Worker(media_path, keyframes, node_cache, params)
                
                worker.progress_update.connect(lambda cur, tot: self._on_progress(node_id, cur, tot))
                worker.log_message.connect(lambda msg: self.log_message.emit(node_id, msg))
                worker.error_occurred.connect(lambda err, w=worker: self._on_error(node_id, err, w))
                worker.finished_processing.connect(lambda w=worker: self._on_finished(node_id, w))
                
                self.active_workers[node_id] = worker
                worker.start()

            elif plugin == "roto_to_shape":
                from plugins.RotoToShape.backend import RotoToShapeWorker
                
                mask_path = self._resolve_alpha_input(node)
                if not mask_path:
                    # If it's connected directly to a plate maybe?
                    mask_path = self._resolve_media_input(node)
                    if not mask_path:
                        raise FileNotFoundError("Connect a Matte or Media Plate before running Roto to Shape.")
                
                self.log_message.emit(node_id, f"Starting Roto extraction...")
                worker = RotoToShapeWorker(mask_path, node_cache, params)
                
                worker.progress_update.connect(lambda cur, tot: self._on_progress(node_id, cur, tot))
                worker.log_message.connect(lambda msg: self.log_message.emit(node_id, msg))
                worker.error_occurred.connect(lambda err, w=worker: self._on_error(node_id, err, w))
                worker.finished_processing.connect(lambda w=worker: self._on_finished(node_id, w))
                
                self.active_workers[node_id] = worker
                worker.start()

            elif plugin == "composite_output":
                from plugins.CompositeOutput.backend import CompositeOutputWorker
                
                # We expect the upstream node to provide the composition
                # If connected to CorridorKey, it's the "Comp" folder. If MatAnyone, it's "fgr".
                input_path = self._resolve_media_input(node)
                tracking_path = self._resolve_tracking_input(node)
                shape_path = self._resolve_shape_input(node)
                
                if not input_path and not tracking_path:
                    raise FileNotFoundError("Connect a Keyer, Matting, or Tracking node to the Unified Output.")

                self.log_message.emit(node_id, "Initializing Unified Output...")
                worker = CompositeOutputWorker(input_path, tracking_path, shape_path, node_cache, params)
                
                worker.progress_update.connect(lambda cur, tot: self._on_progress(node_id, cur, tot))
                worker.log_message.connect(lambda msg: self.log_message.emit(node_id, msg))
                worker.error_occurred.connect(lambda err, w=worker: self._on_error(node_id, err, w))
                worker.finished_processing.connect(lambda w=worker: self._on_finished(node_id, w))
                
                self.active_workers[node_id] = worker
                worker.start()

            elif plugin == "ai_depth_estimator":
                from plugins.DepthEstimator.backend import DepthAnythingV2Engine
                
                video_path = self._resolve_media_input(node)
                if not video_path:
                    raise FileNotFoundError("Connect a Media Plate before running Depth Estimator.")

                self.log_message.emit(node_id, "Initializing Depth Estimator...")
                worker = DepthAnythingV2Engine(video_path, node_cache, params)
                
                worker.progress.connect(lambda pct: self.node_execution_progress.emit(node_id, pct))
                worker.log_message.connect(lambda msg: self.log_message.emit(node_id, msg))
                worker.error.connect(lambda err, w=worker: self._on_error(node_id, err, w))
                worker.finished_ok.connect(lambda out, w=worker: self._on_finished(node_id, w))
                
                self.active_workers[node_id] = worker
                worker.start()

            elif plugin == "matte_to_roto":
                from plugins.MatteToRoto.backend import MatteToRotoWorker
                
                # MatteToRoto expects an Alpha Matte from an upstream node
                # Let's find the upstream output directory
                matte_dir = None
                for edge in self.edges:
                    if edge.end_node == node:
                        upstream_node = edge.start_node
                        matte_dir = self._get_node_cache(upstream_node)
                        break
                        
                if not matte_dir or not os.path.exists(matte_dir):
                    raise FileNotFoundError("Connect a valid Matte source (e.g., SAM3 Rotoscope or MatAnyone2) before running Matte To Roto.")
                    
                self.log_message.emit(node_id, "Initializing Matte To Roto vectorization...")
                
                # Let's assume the user has configured an output directory for MatteToRoto
                # Wait, MatteToRoto can just save its .nk and .svg outputs into its own cache dir.
                
                worker = MatteToRotoWorker(matte_dir, node_cache, params)
                worker.progress.connect(lambda pct: self.node_execution_progress.emit(node_id, pct))
                worker.log_message.connect(lambda msg: self.log_message.emit(node_id, msg))
                worker.error.connect(lambda err, w=worker: self._on_error(node_id, err, w))
                worker.finished_ok.connect(lambda out, w=worker: self._on_finished(node_id, w))
                
                self.active_workers[node_id] = worker
                worker.start()

            else:
                self.log_message.emit(node_id, f"Plugin execution for '{plugin}' is currently mocked.")
                self._on_finished(node_id)

        except Exception as e:
            self._on_error(node_id, str(e))

    @Slot(str, int, int)
    def _on_progress(self, node_id, current, total):
        pct = int((current / total) * 100) if total else 0
        self.node_execution_progress.emit(node_id, pct)
        if total and current % max(1, (total // 10)) == 0:
            self.log_message.emit(node_id, f"Processing: {pct}% [{current}/{total}]")

    @Slot(str, str, object)
    def _on_error(self, node_id, err, worker_ref=None):
        self.log_message.emit(node_id, f"ERROR: {err}")
        self.node_execution_finished.emit(node_id)
        
        # Clean up specific worker or active worker
        worker = worker_ref or self.active_workers.get(node_id)
        if worker:
            if self.active_workers.get(node_id) == worker:
                self.active_workers.pop(node_id)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(2000, worker.deleteLater)
            
        if self.is_executing_pipeline:
            self.log_message.emit(node_id, "Pipeline aborted due to error.")
            self.execution_queue.clear()
            self.is_executing_pipeline = False

    @Slot(str, object)
    def _on_finished(self, node_id, worker_ref=None):
        self.log_message.emit(node_id, "Execution Complete. Output cached.")
        
        # Compute state hash and save to final cache to allow future runs to skip execution
        target_node = self._get_node_by_id(node_id)
        if target_node and target_node.plugin_type != "media_plate":
            try:
                current_hash = self._compute_node_hash(target_node)
                node_cache = self._get_node_cache(target_node)
                if os.path.exists(node_cache):
                    hash_file = os.path.join(node_cache, "last_state_hash.txt")
                    with open(hash_file, "w", encoding="utf-8") as f:
                        f.write(current_hash)
            except Exception as e:
                self.log_message.emit(node_id, f"Failed to save state hash: {e}")

        self.node_execution_progress.emit(node_id, 100)
        self.node_execution_finished.emit(node_id)
        
        # Clean up specific worker or active worker
        worker = worker_ref or self.active_workers.get(node_id)
        if worker:
            if self.active_workers.get(node_id) == worker:
                self.active_workers.pop(node_id)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(2000, worker.deleteLater)
            
        if self.is_executing_pipeline:
            self._pump_execution_queue()

    @Slot(str)
    def cancel_execution(self, node_id):
        if self.is_executing_pipeline:
            self.log_message.emit(node_id, "Cancelling pipeline execution...")
            self.execution_queue.clear()
            self.is_executing_pipeline = False
            
        worker = self.active_workers.get(node_id)
        if worker:
            if hasattr(worker, 'cancel'):
                worker.cancel()
            elif hasattr(worker, 'is_cancelled'):
                worker.is_cancelled = True


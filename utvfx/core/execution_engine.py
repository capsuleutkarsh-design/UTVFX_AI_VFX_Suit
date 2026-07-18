import os
import shutil
import importlib
import cv2
import uuid
import json
import hashlib
import threading
from PySide6.QtCore import QObject, Signal, Slot, QThread
from PySide6.QtGui import QImage
import numpy as np
import gc
from utvfx.core.media_resolver import get_node_cache, get_upstream_nodes, get_cached_output, resolve_media_input, resolve_alpha_input, resolve_tracking_input, resolve_shape_input

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class InteractionWorker(QThread):
    """Offloads the fast interactive inference (e.g. SAM clicks) to prevent UI freezing."""
    finished = Signal(str, str, int, QImage)  # node_id, layer_id, frame_idx, mask_qimage
    error = Signal(str, str)             # node_id, error_message
    
    def __init__(self, node_id, plugin_type, node_params, frame_idx, points, media_path, temp_dir):
        super().__init__()
        self.node_id = node_id
        self.plugin_type = plugin_type
        self.node_params = node_params
        self.layer_id = node_params.get("active_layer_id", "default")
        self.frame_idx = frame_idx
        self.points = points
        self.media_path = media_path
        self.temp_dir = temp_dir
        
    def run(self):
        import tempfile
        
        try:
            # Extract the exact frame requested
            temp_frame_path = os.path.join(self.temp_dir, f"utvfx_current_frame_{uuid.uuid4().hex}.jpg")
            
            if os.path.isdir(self.media_path):
                # Sequence
                files = sorted([f for f in os.listdir(self.media_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.exr', '.dpx', '.hdr'))])
                if 0 <= self.frame_idx < len(files):
                    frame_file = os.path.join(self.media_path, files[self.frame_idx])
                    
                    from utvfx.core.image_utils import load_frame
                    frame = load_frame(frame_file)
                                
                    if frame is not None:
                        cv2.imwrite(temp_frame_path, frame)
                    else:
                        self.error.emit(self.node_id, "Failed to load interactive frame.")
                        return
                else:
                    self.error.emit(self.node_id, "Interactive frame index out of bounds.")
                    return
            else:
                # Video
                cap = cv2.VideoCapture(self.media_path)
                cap.set(cv2.CAP_PROP_POS_FRAMES, self.frame_idx)
                ret, frame = cap.read()
                if ret:
                    cv2.imwrite(temp_frame_path, frame)
                cap.release()
                if not ret: 
                    self.error.emit(self.node_id, "Failed to capture video frame for interaction.")
                    return
            
            mask_qimage = None
            
            if self.plugin_type == "super_matte":
                from plugins.SuperMatte.backend import run_fast_preview
                mask_qimage = run_fast_preview(self.node_params, self.frame_idx, self.points, temp_frame_path)
            elif self.plugin_type == "matte_anyone":
                try:
                    from plugins.MatAnyone2.backend import run_fast_preview
                    mask_qimage = run_fast_preview(self.node_params, self.frame_idx, self.points, temp_frame_path)
                except ImportError:
                    self.error.emit(self.node_id, "MatAnyone2 backend not found for interactive preview.")
                    return
                
            if mask_qimage is not None:
                self.finished.emit(self.node_id, self.layer_id, self.frame_idx, mask_qimage)
            else:
                self.error.emit(self.node_id, "AI Engine failed to generate preview mask.")
                
            # Cleanup temp frame
            try:
                if os.path.exists(temp_frame_path):
                    os.remove(temp_frame_path)
            except Exception:
                pass
                
        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            self.error.emit(self.node_id, f"Interaction error: {str(e)}\n\nTraceback:\n{tb_str}")

class ExecutionEngine(QObject):
    """Orchestrates node execution, manages caching, and routes data."""
    log_message = Signal(str, str) # node_id, message
    node_execution_started = Signal(str)
    node_execution_progress = Signal(str, int) # node_id, percentage
    node_execution_finished = Signal(str)
    interactive_mask_ready = Signal(str, str, int, QImage) # node_id, layer_id, frame_idx, qimage

    @property
    def cache_dir(self):
        from utvfx.core.settings_manager import SettingsManager
        return SettingsManager().get("cache_dir", os.path.join(BASE_DIR, "workspace", "cache"))
        
    @property
    def temp_dir(self):
        from utvfx.core.settings_manager import SettingsManager
        return SettingsManager().get("temp_dir", os.path.join(BASE_DIR, "workspace", "temp"))

    def __init__(self, scene):
        super().__init__()
        self.scene = scene
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
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
            for upstream in get_upstream_nodes(n):
                dfs(upstream)
            sorted_nodes.append(n)
            
        dfs(target_node)
        return sorted_nodes

    def _get_node_by_id(self, node_id):
        if not hasattr(self, "_node_index") or len(getattr(self, "_node_index", {})) != len(self.scene.nodes):
            self._node_index = {n.node_id: n for n in self.scene.nodes}
        return self._node_index.get(node_id)

    def _clear_vram(self):
        """Force cleanup of system and GPU memory."""
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except ImportError:
            pass

    @Slot(str, int, list)
    def handle_interaction(self, node_id, frame_idx, points):
        node = self._get_node_by_id(node_id)
        if not node: return
        
        self.log_message.emit(node_id, f"Processing interaction: {len(points)} points on frame {frame_idx}...")
        
        media_path = resolve_media_input(node, cache_dir=self.cache_dir)
        if not media_path or not os.path.exists(media_path):
            self.log_message.emit(node_id, "Interaction failed: No media connected.")
            return
        worker = InteractionWorker(
            node_id=node_id,
            plugin_type=node.plugin_type,
            node_params=node.params,
            frame_idx=frame_idx,
            points=points,
            media_path=media_path,
            temp_dir=self.temp_dir
        )
        worker.finished.connect(self._on_interaction_success)
        worker.error.connect(self._on_interaction_error)
        
        if not hasattr(self, "_interaction_workers_lock"):
            self._interaction_workers_lock = threading.Lock()
            
        with self._interaction_workers_lock:
            self._interaction_workers = getattr(self, "_interaction_workers", [])
            self._interaction_workers.append(worker)
            
            worker.finished.connect(lambda *args, w=worker: self._remove_interaction_worker(w))
            worker.error.connect(lambda *args, w=worker: self._remove_interaction_worker(w))
            
        worker.start()

    def _remove_interaction_worker(self, w):
        with getattr(self, "_interaction_workers_lock", threading.Lock()):
            if hasattr(self, "_interaction_workers") and w in self._interaction_workers:
                self._interaction_workers.remove(w)
        self._clear_vram()

    @Slot(str, str, int, object)
    def _on_interaction_success(self, node_id, layer_id, frame_idx, mask_qimage):
        self.log_message.emit(node_id, "Fast preview generated successfully.")
        self.interactive_mask_ready.emit(node_id, layer_id, frame_idx, mask_qimage)
        
    @Slot(str, str)
    def _on_interaction_error(self, node_id, error_msg):
        self.log_message.emit(node_id, error_msg)

    def _compute_node_hash(self, node, memo=None):
        if memo is None:
            memo = {}
        if node.node_id in memo:
            return memo[node.node_id]
            
        hasher = hashlib.sha256()
        hasher.update(str(node.plugin_type).encode('utf-8'))
        
        # Serialize node parameters, ignoring UI-only state that doesn't affect the output
        params = getattr(node, "params", {})
        hash_params = {k: v for k, v in params.items() if k not in ["active_layer_id", "ui_scroll_position"]}
        try:
            params_str = json.dumps(hash_params, sort_keys=True)
        except Exception:
            params_str = str(hash_params)
        hasher.update(params_str.encode('utf-8'))
        
        # Include file modification time if it's a media plate
        if node.plugin_type == "media_plate":
            plate_file = params.get("plate_file")
            if plate_file and os.path.exists(plate_file):
                try:
                    mtime = os.path.getmtime(plate_file)
                    hasher.update(str(mtime).encode('utf-8'))
                except Exception:
                    pass
                    
        # Incorporate hashes of all upstream dependencies so downstream nodes invalidate
        # if any upstream input changes.
        for upstream in get_upstream_nodes(node):
            hasher.update(self._compute_node_hash(upstream, memo).encode('utf-8'))
            
        result = hasher.hexdigest()
        memo[node.node_id] = result
        return result



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
            
            from utvfx.bridge.ai_bridge_client import AIBridgeClient
            client = AIBridgeClient.get_instance()
            
            # For each keyframe, extract the frame and ask SAM to generate a mask
            for f_idx, points in mask_keyframes.items():
                if not points: continue
                
                if node_id:
                    self.log_message.emit(node_id, f"Generating high-quality SAM mask for keyframe {f_idx}...")
                
                f_idx = int(f_idx)
                import uuid
                temp_frame_path = os.path.join(self.temp_dir, f"utvfx_gen_frame_{f_idx}_{uuid.uuid4().hex}.jpg")
                
                # Extract frame
                if os.path.isdir(video_path):
                    files = sorted([f for f in os.listdir(video_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.exr', '.dpx', '.hdr'))])
                    if 0 <= f_idx < len(files):
                        frame_file = os.path.join(video_path, files[f_idx])
                        from utvfx.core.image_utils import load_frame
                        frame = load_frame(frame_file)
                        if frame is not None:
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

        # Bypass disabled nodes and dot nodes
        if getattr(node, 'is_disabled', False) or getattr(node, 'plugin_type', '') == 'dot_node':
            self.log_message.emit(node_id, f"Node {node.name} is bypassed/dot node. Skipping execution.")
            self._on_finished(node_id)
            return

        self.log_message.emit(node_id, f"Initializing execution for {node.name}...")
        self.node_execution_started.emit(node_id)
        
        # UX Improvement: Let the user know the target node is waiting on an upstream node
        if getattr(self, "current_target_node_id", None) and self.current_target_node_id != node_id:
            self.log_message.emit(self.current_target_node_id, f"[Waiting] Currently executing upstream node: {node.name}...")

        plugin = node.plugin_type
        params = getattr(node, "params", {})

        # --- Project Auto-Naming Fallback ---
        if plugin == "media_plate" and "plate_file" in params and params["plate_file"]:
            from utvfx.core.settings_manager import SettingsManager
            sm = SettingsManager()
            if sm.current_project_name == "Untitled":
                import re
                file_path = params["plate_file"]
                basename = os.path.basename(file_path)
                name, ext = os.path.splitext(basename)
                shot_name = name
                
                if ext.lower() in [".exr", ".png", ".jpg", ".jpeg", ".tiff", ".dpx"]:
                    clean_name = re.sub(r'[\._-]?\d+$', '', name)
                    if clean_name:
                        shot_name = clean_name
                    else:
                        folder_name = os.path.basename(os.path.dirname(file_path))
                        if folder_name and folder_name.lower() not in ["", "render", "renders", "output", "outputs", "frames", "images", "img"]:
                            shot_name = folder_name
                
                sm.set_project_name(shot_name)

        node_cache = get_node_cache(node, self.cache_dir)
        os.makedirs(node_cache, exist_ok=True)

        # --- Smart Cache Validation ---
        try:
            current_hash = self._compute_node_hash(node)
            hash_file = os.path.join(node_cache, "last_state_hash.txt")
            
            # 1. Check for explicit frozen state
            if getattr(node, 'is_frozen', False):
                if get_cached_output(node, cache_dir=self.cache_dir):
                    self.log_message.emit(node_id, f"[Frozen] Node {node.name} is frozen. Using cached output.")
                    self._on_finished(node_id)
                    return
                else:
                    self.log_message.emit(node_id, f"[Frozen] Node {node.name} is frozen but has no cache. Re-executing.")

            # 2. Regular hash-based caching
            elif os.path.exists(hash_file):
                with open(hash_file, "r", encoding="utf-8") as f:
                    saved_hash = f.read().strip()
                    
                # If state hashes match perfectly AND the output cache folder isn't empty, skip execution.
                if saved_hash == current_hash and get_cached_output(node, cache_dir=self.cache_dir):
                    self.log_message.emit(node_id, f"[Cached] Output is already generated. Skipping execution for {node.name}.")
                    
                    if hasattr(node, 'set_cached_state'):
                        node.set_cached_state()
                        
                    self._on_finished(node_id)
                    return
        except Exception as e:
            self.log_message.emit(node_id, f"Cache validation error: {e}. Forcing re-execution.")

        try:
            from utvfx.core.plugin_manager import PluginManager
            pm = PluginManager()
            worker_class = pm.get_worker_class(plugin)
            
            if not worker_class:
                self.log_message.emit(node_id, f"Plugin execution for '{plugin}' is missing worker class or currently mocked.")
                self._on_finished(node_id)
                return

            # Resolve Inputs Dynamically
            manifest = pm.get_registry().get(plugin, {})
            manifest_inputs = manifest.get("inputs", [])
            resolved_inputs = {}
            for inp in manifest_inputs:
                inp_name = inp if isinstance(inp, str) else inp.get("name", "")
                
                # Check for standard names or implement types
                inp_name_lower = inp_name.lower()
                if "alpha" in inp_name_lower or "matte" in inp_name_lower:
                    resolved_inputs[inp_name] = resolve_alpha_input(node, cache_dir=self.cache_dir)
                elif "tracking" in inp_name_lower:
                    resolved_inputs[inp_name] = resolve_tracking_input(node, cache_dir=self.cache_dir)
                elif "shape" in inp_name_lower:
                    resolved_inputs[inp_name] = resolve_shape_input(node, cache_dir=self.cache_dir)
                else:
                    resolved_inputs[inp_name] = resolve_media_input(node, cache_dir=self.cache_dir)
                    
            if plugin == "corridor_keyer":
                params = self._map_corridor_key_params(params)
                
            self.log_message.emit(node_id, f"Starting execution for {manifest.get('name', plugin)}. Cache: {node_cache}")
            
            worker = worker_class(node_id, params, resolved_inputs, node_cache, self.cache_dir)
            
            worker.progress_update.connect(self._on_progress)
            worker.log_message.connect(self.log_message.emit)
            worker.error_occurred.connect(lambda n, err, w=worker: self._on_error(n, err, w))
            worker.finished_success.connect(lambda n, w=worker: self._on_finished(n, w))
            
            self.active_workers[node_id] = worker
            worker.start()

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
        
        target_node = self._get_node_by_id(node_id)
        if target_node and hasattr(target_node, 'set_error_state'):
            target_node.set_error_state(True, str(err))
            
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
        if target_node:
            try:
                current_hash = self._compute_node_hash(target_node)
                node_cache = get_node_cache(target_node, self.cache_dir)
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
            
        self._clear_vram()
            
        # Free persistent bridge memory between node renders to prevent 8GB OOM
        if self.is_executing_pipeline:
            try:
                from utvfx.bridge.ai_bridge_client import AIBridgeClient
                if AIBridgeClient._instance:
                    AIBridgeClient._instance.shutdown()
            except Exception:
                pass
            
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


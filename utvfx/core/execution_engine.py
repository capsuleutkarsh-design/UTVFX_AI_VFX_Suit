import os
import logging
import shutil
import importlib
import cv2
import uuid
import json
import copy
import hashlib
import threading
from PySide6.QtCore import QObject, Signal, Slot, QThread
from PySide6.QtGui import QImage
import numpy as np
import gc
from utvfx.core.media_resolver import get_node_cache, get_upstream_nodes, has_rendered_output, resolve_input, resolve_media_input, state_hash_path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class InteractionWorker(QThread):
    """Offloads the fast interactive inference (e.g. SAM clicks) to prevent UI freezing."""
    mask_ready = Signal(str, str, int, QImage)  # node_id, layer_id, frame_idx, mask_qimage
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
                # frame_idx is the timeline position; sort by frame number, not by name.
                from utvfx.core.plate import find_sequence
                files = [p for _, p in find_sequence(self.media_path)]
                if 0 <= self.frame_idx < len(files):
                    frame_file = files[self.frame_idx]
                    
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
                self.mask_ready.emit(self.node_id, self.layer_id, self.frame_idx, mask_qimage)
            else:
                from utvfx.bridge.ai_bridge_client import AIBridgeClient
                reason = AIBridgeClient.get_instance().last_error or "no reason given"
                self.error.emit(self.node_id, f"The AI engine could not make a preview: {reason}")
                
            # Cleanup temp frame
            try:
                if os.path.exists(temp_frame_path):
                    os.remove(temp_frame_path)
            except Exception:
                logging.getLogger(__name__).debug("Ignored error", exc_info=True)
                
        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            self.error.emit(self.node_id, f"Interaction error: {str(e)}\n\nTraceback:\n{tb_str}")

# Nodes that talk to the separate SAM engine process.
BRIDGE_USERS = {"super_matte"}
# Nodes that load large models inside the app process.
GPU_HEAVY_IN_PROCESS = {"super_matte", "corridor_keyer", "ai_depth_estimator", "ai_roto", "sfm_tracker"}


class ExecutionEngine(QObject):
    """Orchestrates node execution, manages caching, and routes data."""
    log_message = Signal(str, str) # node_id, message
    node_execution_started = Signal(str)
    node_execution_progress = Signal(str, int) # node_id, percentage
    node_execution_finished = Signal(str)
    # target node id, "done" | "error" | "cancelled" | "rejected": the whole pipeline is over.
    pipeline_finished = Signal(str, str)
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
        self._start_hashes = {}
        self._interaction_seq = {}
        self.execution_queue = []
        self.is_executing_pipeline = False
        self.is_cancelling = False
        self.current_target_node_id = None
        # (first, last) timeline positions to render, or None for the whole plate (timeline In/Out).
        self.render_range = None

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
        # A plain scan: the graph is small, and a cached index can hand back deleted nodes.
        return next((n for n in self.scene.nodes if n.node_id == node_id), None)

    def _free_bridge_for(self, plugin):
        """Unload the SAM engine before a GPU-heavy node that does not use it; keep it otherwise."""
        if plugin in BRIDGE_USERS or plugin not in GPU_HEAVY_IN_PROCESS:
            return
        from utvfx.bridge.ai_bridge_client import AIBridgeClient
        if AIBridgeClient._instance is not None and AIBridgeClient._instance.process is not None:
            self.log_message.emit(self.current_target_node_id or "", "Unloading the SAM engine to free GPU memory…")
            AIBridgeClient._instance.shutdown_async()

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
        
        inputs = getattr(node, "inputs", [])
        media_path = resolve_input(node, inputs[0].name, self.cache_dir) if inputs else resolve_media_input(node, cache_dir=self.cache_dir)
        if not media_path or not os.path.exists(media_path):
            self.log_message.emit(node_id, "Interaction failed: No media connected.")
            return
        worker = InteractionWorker(
            node_id=node_id,
            plugin_type=node.plugin_type,
            node_params=copy.deepcopy(node.params),
            frame_idx=frame_idx,
            points=points,
            media_path=media_path,
            temp_dir=self.temp_dir
        )
        # Clicks can outrun the model: number them and drop any answer that is no longer the latest.
        seq = self._interaction_seq.get(node_id, 0) + 1
        self._interaction_seq[node_id] = seq
        worker.mask_ready.connect(lambda n, l, f, img, s=seq: self._on_interaction_success(n, l, f, img, s))
        worker.error.connect(self._on_interaction_error)

        if not hasattr(self, "_interaction_workers_lock"):
            self._interaction_workers_lock = threading.Lock()
        with self._interaction_workers_lock:
            self._interaction_workers = getattr(self, "_interaction_workers", [])
            self._interaction_workers.append(worker)
        # QThread.finished fires once run() has returned, so deleting then is safe.
        worker.finished.connect(lambda w=worker: self._remove_interaction_worker(w))

        worker.start()

    def _remove_interaction_worker(self, w):
        with getattr(self, "_interaction_workers_lock", threading.Lock()):
            if hasattr(self, "_interaction_workers") and w in self._interaction_workers:
                self._interaction_workers.remove(w)
        w.deleteLater()

    def _on_interaction_success(self, node_id, layer_id, frame_idx, mask_qimage, seq=None):
        if seq is not None and seq != self._interaction_seq.get(node_id):
            return  # a newer click is already on its way
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
        # The In/Out range changes what gets rendered, except for the plate itself (always decoded whole).
        if node.plugin_type != "media_plate":
            hash_params["__render_range"] = self.render_range
        try:
            params_str = json.dumps(hash_params, sort_keys=True, default=str)
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
                    logging.getLogger(__name__).debug("Ignored error", exc_info=True)
                    
        # Incorporate hashes of all upstream dependencies so downstream nodes invalidate
        # if any upstream input changes.
        for upstream in get_upstream_nodes(node):
            hasher.update(self._compute_node_hash(upstream, memo).encode('utf-8'))
            
        result = hasher.hexdigest()
        memo[node.node_id] = result
        return result



    def execute_node(self, node_id):
        """Render node_id and everything upstream. Returns False if the request was refused."""
        target_node = self._get_node_by_id(node_id)
        if not target_node:
            self.pipeline_finished.emit(node_id, "rejected")
            return False

        if self.is_executing_pipeline or self.active_workers:
            msg = "Still stopping the previous render…" if self.is_cancelling else "A render is already running. Stop it first."
            self.log_message.emit(node_id, msg)
            self.pipeline_finished.emit(node_id, "rejected")
            return False

        sorted_nodes = self._build_execution_graph(target_node)
        
        # Build execution queue
        self.execution_queue = [n.node_id for n in sorted_nodes]
        self.is_executing_pipeline = True
        self.current_target_node_id = node_id
        
        self.log_message.emit(node_id, f"Pipeline queued with {len(self.execution_queue)} nodes. Starting execution...")
        self._pump_execution_queue()
        return True

    def _end_pipeline(self, status):
        target = self.current_target_node_id
        self.execution_queue.clear()
        self.is_executing_pipeline = False
        self.is_cancelling = False
        self.current_target_node_id = None
        if target:
            self.pipeline_finished.emit(target, status)

    def _pump_execution_queue(self):
        if not self.is_executing_pipeline:
            return
        if not self.execution_queue:
            self._end_pipeline("done")
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
                from utvfx.core.project import shot_name_from_path
                sm.set_project_name(shot_name_from_path(params["plate_file"]))

        node_cache = get_node_cache(node, self.cache_dir)
        os.makedirs(node_cache, exist_ok=True)

        # --- Smart Cache Validation ---
        try:
            current_hash = self._compute_node_hash(node)
            # Fingerprint the settings as the render starts: edits made while it runs must not be marked cached.
            self._start_hashes[node_id] = current_hash
            hash_file = state_hash_path(node_cache)
            
            # 1. Check for explicit frozen state
            if getattr(node, 'is_frozen', False):
                if has_rendered_output(node, self.cache_dir):
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
                if saved_hash == current_hash and has_rendered_output(node, self.cache_dir):
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
                resolved_inputs[inp_name] = resolve_input(node, inp_name, self.cache_dir)
                    
                
            self.log_message.emit(node_id, f"Starting execution for {manifest.get('name', plugin)}. Cache: {node_cache}")
            
            # Workers get their own copy, so edits made while they run cannot change their input.
            worker = worker_class(node_id, copy.deepcopy(params), resolved_inputs, node_cache, self.cache_dir)
            
            worker.progress_update.connect(self._on_progress)
            worker.log_message.connect(self.log_message.emit)
            worker.error_occurred.connect(lambda n, err, w=worker: self._on_error(n, err, w))
            worker.finished_success.connect(lambda n, w=worker: self._on_finished(n, w))
            worker.cancelled.connect(lambda n, w=worker: self._on_cancelled(n, w))
            worker.frame_range = self.render_range
            if plugin in GPU_HEAVY_IN_PROCESS:
                # Hand the GPU back once the thread has fully ended (M12).
                worker.finished.connect(self._clear_vram)
            self._free_bridge_for(plugin)

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
            
        self._start_hashes.pop(node_id, None)
        if self.is_executing_pipeline:
            self.log_message.emit(node_id, "Pipeline aborted due to error.")
            self._end_pipeline("error")

    @Slot(str, object)
    def _on_finished(self, node_id, worker_ref=None):
        self.log_message.emit(node_id, "Execution Complete. Output cached.")
        
        # Compute state hash and save to final cache to allow future runs to skip execution
        target_node = self._get_node_by_id(node_id)
        if target_node:
            try:
                current_hash = self._start_hashes.pop(node_id, None) or self._compute_node_hash(target_node)
                node_cache = get_node_cache(target_node, self.cache_dir)
                if os.path.exists(node_cache):
                    hash_file = state_hash_path(node_cache)
                    os.makedirs(os.path.dirname(hash_file), exist_ok=True)
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

    @Slot(str, object)
    def _on_cancelled(self, node_id, worker_ref=None):
        self.log_message.emit(node_id, "Stopped.")
        self._start_hashes.pop(node_id, None)  # a stopped run is never cached
        self.node_execution_finished.emit(node_id)
        worker = worker_ref or self.active_workers.get(node_id)
        if worker:
            if self.active_workers.get(node_id) is worker:
                self.active_workers.pop(node_id)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(2000, worker.deleteLater)
        if not self.active_workers and self.is_executing_pipeline:
            self._end_pipeline("cancelled")

    @Slot(str)
    def cancel_execution(self, node_id=None):
        """Stop the running render, whichever node is selected.

        The engine stays busy until the running worker has actually stopped, so a
        new render can never overlap it on the GPU.
        """
        if not self.is_executing_pipeline and not self.active_workers:
            return
        log_to = self.current_target_node_id or node_id
        if log_to:
            self.log_message.emit(log_to, "Stopping…")
        self.execution_queue.clear()
        self.is_cancelling = True
        if not self.active_workers:
            self._end_pipeline("cancelled")
            return
        for worker in list(self.active_workers.values()):
            if hasattr(worker, 'cancel'):
                worker.cancel()
            else:
                worker.is_cancelled = True
        from utvfx.bridge.ai_bridge_client import AIBridgeClient
        if AIBridgeClient._instance is not None:
            AIBridgeClient._instance.cancel()


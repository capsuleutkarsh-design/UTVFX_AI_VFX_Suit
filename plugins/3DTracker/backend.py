import os
import subprocess
from PySide6.QtCore import QObject, QThread, Signal

from utvfx.bridge.base_worker import BaseWorker

class TrackerWorker(BaseWorker):
    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(node_id, params, inputs, cache_dir, output_dir, parent)
        self.in_dir = inputs.get("Video Plate")
        self.out_dir = cache_dir
        self.process = None
        self.engine = "glomap" if "GLOMAP" in self.params.get("mapper_engine", "GLOMAP (Fast)") else "colmap"

    def cancel(self):
        self.is_cancelled = True
        if self.process:
            self.process.terminate()


    def _run_cmd(self, cmd, env=None):
        if self.is_cancelled: return False
        try:
            self.process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                text=True, creationflags=subprocess.CREATE_NO_WINDOW, env=env
            )
            for line in self.process.stdout:
                if self.is_cancelled:
                    self.process.terminate()
                    return False
                # Properly emit the log line to the UI
                self.log_message.emit(self.node_id, line.strip())
            self.process.wait()
            if self.process.returncode != 0 and not self.is_cancelled:
                raise subprocess.CalledProcessError(self.process.returncode, cmd)
            return True
        except Exception as e:
            if not self.is_cancelled:
                raise e
            return False

    def run_task(self):
        # Determine the binary path based on the engine
        bin_dir = os.path.join(os.path.dirname(__file__), "bin")
        colmap_dir = os.path.join(bin_dir, "colmap-x64-windows-cuda")
        colmap_exe = os.path.join(colmap_dir, "bin", "colmap.exe")
        
        # Setup environment variables for colmap to mimic COLMAP.bat
        colmap_env = os.environ.copy()
        colmap_env["PATH"] = os.path.join(colmap_dir, "bin") + os.pathsep + colmap_env.get("PATH", "")
        colmap_env["QT_PLUGIN_PATH"] = os.path.join(colmap_dir, "plugins") + os.pathsep + colmap_env.get("QT_PLUGIN_PATH", "")
        
        db_path = os.path.join(self.out_dir, "database.db")
        image_dir = self.in_dir
        
        from utvfx.core.plate import tier_folder
        image_dir = tier_folder(image_dir, "jpg", cancelled=lambda: self.is_cancelled)
                
        sparse_dir = os.path.join(self.out_dir, "sparse")
        
        os.makedirs(sparse_dir, exist_ok=True)
        
        # Extract configuration parameters with safe defaults
        feature_algo = self.params.get("feature_type", "SIFT (GPU)")
        max_features = int(self.params.get("max_features", 2000))
        match_type = self.params.get("match_type", "Sequential")
        min_tri_angle = float(self.params.get("min_tri_angle", 1.5))
        ba_iterations = int(self.params.get("ba_iterations", 100))
        
        # 1. Feature Extraction (COLMAP)
        self.log_message.emit(self.node_id, "Extracting features with COLMAP...")
        feat_cmd = [
            colmap_exe, "feature_extractor",
            "--database_path", db_path,
            "--image_path", image_dir,
            "--ImageReader.single_camera", "1",
            "--SiftExtraction.max_num_features", str(max_features)
        ]
        
        # Map GPU flag
        if "GPU" in feature_algo:
            feat_cmd.extend(["--FeatureExtraction.use_gpu", "1"])
        else:
            feat_cmd.extend(["--FeatureExtraction.use_gpu", "0"])
            
        # Map Domain Size Pooling (DSP)
        if "DSP" in feature_algo:
            feat_cmd.extend(["--SiftExtraction.domain_size_pooling", "1"])
            
        if not self._run_cmd(feat_cmd, env=colmap_env): return
        self.progress_update.emit(self.node_id, 25, 100)

        # 2. Matcher (COLMAP)
        self.log_message.emit(self.node_id, f"Matching features ({match_type}) with COLMAP...")
        if match_type == "Exhaustive":
            match_cmd = [colmap_exe, "exhaustive_matcher", "--database_path", db_path]
        elif match_type == "Spatial Neighbors":
            match_cmd = [colmap_exe, "spatial_matcher", "--database_path", db_path]
        else:  # Sequential (Default)
            match_cmd = [colmap_exe, "sequential_matcher", "--database_path", db_path, "--SequentialMatching.overlap", "15"]
            
        if not self._run_cmd(match_cmd, env=colmap_env): return
        self.progress_update.emit(self.node_id, 50, 100)

        # 3. Mapper (Sparse Reconstruction)
        use_incremental = self.engine != "glomap"
        if self.engine == "glomap":
            # COLMAP 4.2 includes GLOMAP as its global mapper: same database, no separate binary.
            # It needs focal-length priors, so estimate them from the matches first (COLMAP's advice).
            self.log_message.emit(self.node_id, "Estimating focal length for the global mapper...")
            try:
                self._run_cmd([colmap_exe, "view_graph_calibrator", "--database_path", db_path], env=colmap_env)
            except Exception as e:
                self.log_message.emit(self.node_id, f"Focal length estimate skipped: {e}")
            self.log_message.emit(self.node_id, "Sparse reconstruction with COLMAP's global mapper (GLOMAP)...")
            map_cmd = [
                colmap_exe, "global_mapper",
                "--database_path", db_path,
                "--image_path", image_dir,
                "--output_path", sparse_dir,
                "--GlobalMapper.tri_min_angle", str(min_tri_angle),
            ]
            try:
                self._run_cmd(map_cmd, env=colmap_env)
            except Exception as e:
                if self.is_cancelled:
                    return
                self.log_message.emit(self.node_id, f"Global mapper could not solve this shot ({e}). Trying the incremental mapper...")
                use_incremental = True
        if use_incremental:
            self.log_message.emit(self.node_id, "Sparse Reconstruction with COLMAP (Incremental)...")
            # COLMAP mapper command with custom triangulation & BA iteration limits
            map_cmd = [
                colmap_exe, "mapper",
                "--database_path", db_path,
                "--image_path", image_dir,
                "--output_path", sparse_dir,
                "--Mapper.tri_min_angle", str(min_tri_angle),
                "--Mapper.ba_global_max_num_iterations", str(ba_iterations)
            ]
            
            if not self._run_cmd(map_cmd, env=colmap_env): return
        self.progress_update.emit(self.node_id, 85, 100)

        # 4. Export TXT (COLMAP model_converter)
        self.log_message.emit(self.node_id, "Exporting sparse reconstruction to TXT...")
        # COLMAP can split a shot into several models; export the one with the most registered frames.
        models = [os.path.join(sparse_dir, d) for d in os.listdir(sparse_dir)
                  if os.path.isfile(os.path.join(sparse_dir, d, "images.bin"))]
        model_0_dir = max(models, key=lambda d: os.path.getsize(os.path.join(d, "images.bin")), default=None)
        if model_0_dir is None:
            raise RuntimeError("COLMAP could not reconstruct a camera from this shot.")
        if len(models) > 1:
            self.log_message.emit(self.node_id, f"COLMAP found {len(models)} separate pieces; using the largest ({os.path.basename(model_0_dir)}).")
        if os.path.exists(model_0_dir):
            self._run_cmd([
                colmap_exe, "model_converter",
                "--input_path", model_0_dir,
                "--output_path", sparse_dir,
                "--output_type", "TXT"
            ], env=colmap_env)
        self.progress_update.emit(self.node_id, 100, 100)
        
        self.log_message.emit(self.node_id, "3D Tracker Processing complete.")

class TrackerBackend(QObject):
    log_output = Signal(str)
    finished = Signal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None

    def start_process(self, in_dir, out_dir, engine):
        if self.worker and self.worker.isRunning():
            return
            
        params = {"mapper_engine": "GLOMAP (Fast)" if "glomap" in engine.lower() else "COLMAP (Incremental)"}
        inputs = {"Video Plate": in_dir}
        self.worker = TrackerWorker("standalone_ui", params, inputs, out_dir, out_dir)
        self.worker.log_message.connect(lambda node_id, msg: self.log_output.emit(msg))
        self.worker.finished.connect(lambda node_id, success: self.finished.emit(success))
        self.worker.start()

    def cancel_process(self):
        if self.worker:
            self.worker.cancel()

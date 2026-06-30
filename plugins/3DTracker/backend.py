import os
import subprocess
from PySide6.QtCore import QObject, QThread, Signal

class TrackerThread(QThread):
    log_output = Signal(str)
    finished_sig = Signal(bool)
    log_message = Signal(str)
    progress_update = Signal(int, int)
    finished_processing = Signal()

    def __init__(self, in_dir, out_dir, params_or_engine):
        super().__init__()
        self.in_dir = in_dir
        self.out_dir = out_dir
        self.is_cancelled = False
        self.process = None
        
        # Support both direct engine string and full params dictionary (backward compatible)
        if isinstance(params_or_engine, dict):
            self.params = params_or_engine
            engine_choice = self.params.get("mapper_engine", "GLOMAP (Fast)")
            self.engine = "glomap" if "GLOMAP" in engine_choice else "colmap"
        else:
            self.params = {}
            self.engine = params_or_engine

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
                self.log_message.emit(line.strip())
            self.process.wait()
            if self.process.returncode != 0 and not self.is_cancelled:
                raise subprocess.CalledProcessError(self.process.returncode, cmd)
            return True
        except Exception as e:
            if not self.is_cancelled:
                raise e
            return False

    def run(self):
        # Determine the binary path based on the engine
        bin_dir = os.path.join(os.path.dirname(__file__), "bin")
        colmap_dir = os.path.join(bin_dir, "colmap-x64-windows-cuda")
        colmap_exe = os.path.join(colmap_dir, "bin", "colmap.exe")
        glomap_exe = os.path.join(bin_dir, "glomap-x64-windows-cuda", "bin", "glomap.exe")
        
        # Setup environment variables for colmap to mimic COLMAP.bat
        colmap_env = os.environ.copy()
        colmap_env["PATH"] = os.path.join(colmap_dir, "bin") + os.pathsep + colmap_env.get("PATH", "")
        colmap_env["QT_PLUGIN_PATH"] = os.path.join(colmap_dir, "plugins") + os.pathsep + colmap_env.get("QT_PLUGIN_PATH", "")
        
        db_path = os.path.join(self.out_dir, "database.db")
        image_dir = self.in_dir
        sparse_dir = os.path.join(self.out_dir, "sparse")
        
        try:
            os.makedirs(sparse_dir, exist_ok=True)
            
            # Extract configuration parameters with safe defaults
            feature_algo = self.params.get("feature_type", "SIFT (GPU)")
            max_features = int(self.params.get("max_features", 2000))
            match_type = self.params.get("match_type", "Sequential")
            min_tri_angle = float(self.params.get("min_tri_angle", 1.5))
            ba_iterations = int(self.params.get("ba_iterations", 100))
            
            # 1. Feature Extraction (COLMAP)
            self.log_message.emit("Extracting features with COLMAP...")
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
            self.progress_update.emit(25, 100)

            # 2. Matcher (COLMAP)
            self.log_message.emit(f"Matching features ({match_type}) with COLMAP...")
            if match_type == "Exhaustive":
                match_cmd = [colmap_exe, "exhaustive_matcher", "--database_path", db_path]
            elif match_type == "Spatial Neighbors":
                match_cmd = [colmap_exe, "spatial_matcher", "--database_path", db_path]
            else:  # Sequential (Default)
                match_cmd = [colmap_exe, "sequential_matcher", "--database_path", db_path, "--SequentialMatching.overlap", "15"]
                
            if not self._run_cmd(match_cmd, env=colmap_env): return
            self.progress_update.emit(50, 100)

            # 3. Mapper (Sparse Reconstruction)
            if self.engine == "glomap":
                self.log_message.emit("Sparse Reconstruction with GLOMAP (Fast)...")
                
                # GLOMAP requires a schema patch because it is compiled with an older COLMAP C++ codebase.
                # Specifically, the pose_priors table in COLMAP 4.1.0 removed the image_id column.
                # GLOMAP's database reader prepares a SELECT statement expecting image_id, which causes a fatal SQL logic error.
                try:
                    import sqlite3
                    conn = sqlite3.connect(db_path)
                    
                    # Drop and recreate pose_priors with the legacy schema expected by GLOMAP.
                    conn.execute("DROP TABLE IF EXISTS pose_priors")
                    conn.execute("CREATE TABLE pose_priors (image_id INTEGER PRIMARY KEY NOT NULL, position BLOB, coordinate_system INTEGER NOT NULL, position_covariance BLOB, FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE CASCADE)")
                    
                    conn.commit()
                    conn.close()
                except Exception as e:
                    self.log_message.emit(f"Warning: GLOMAP DB Patch failed: {e}")

                # GLOMAP mapper command
                map_cmd = [
                    glomap_exe, "mapper",
                    "--database_path", db_path,
                    "--image_path", image_dir,
                    "--output_path", sparse_dir
                ]
                
                glomap_dir = os.path.dirname(os.path.dirname(glomap_exe))
                glomap_env = os.environ.copy()
                glomap_env["PATH"] = os.path.join(glomap_dir, "bin") + os.pathsep + glomap_env.get("PATH", "")
                
                if not self._run_cmd(map_cmd, env=glomap_env): return
            else:
                self.log_message.emit("Sparse Reconstruction with COLMAP (Incremental)...")
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
            self.progress_update.emit(85, 100)

            # 4. Export TXT (COLMAP model_converter)
            self.log_message.emit("Exporting sparse reconstruction to TXT...")
            model_0_dir = os.path.join(sparse_dir, "0")
            if os.path.exists(model_0_dir):
                self._run_cmd([
                    colmap_exe, "model_converter",
                    "--input_path", model_0_dir,
                    "--output_path", sparse_dir,
                    "--output_type", "TXT"
                ], env=colmap_env)
            self.progress_update.emit(100, 100)
            
            self.finished_processing.emit()
            self.finished_sig.emit(True)
            
        except Exception as e:
            self.log_output.emit(f"Exception during execution: {str(e)}")
            self.finished_sig.emit(False)

class TrackerBackend(QObject):
    log_output = Signal(str)
    finished = Signal(bool)

    def __init__(self):
        super().__init__()
        self.thread = None

    def start_process(self, in_dir, out_dir, engine):
        self.thread = TrackerThread(in_dir, out_dir, engine)
        self.thread.log_output.connect(self.log_output.emit)
        self.thread.finished_sig.connect(self.finished.emit)
        self.thread.start()

    def cancel_process(self):
        if self.thread and self.thread.isRunning():
            self.thread.cancel()


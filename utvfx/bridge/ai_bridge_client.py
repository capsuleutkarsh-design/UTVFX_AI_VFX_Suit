import os
import sys
import json
import subprocess
import threading
import tempfile
import cv2
import numpy as np
import uuid
from PySide6.QtGui import QImage, QColor

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utvfx.core.settings_manager import SettingsManager

class AIBridgeClient:
    """Manages the persistent AI Bridge Server subprocess for real-time inference."""
    
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = AIBridgeClient()
        return cls._instance
        
    def __init__(self):
        self.process = None
        self.lock = threading.Lock()
        
        exe_name = "python.exe" if os.name == "nt" else "python"
        
        # Locate portable python_base executable
        candidate_pythons = []
        if getattr(sys, 'frozen', False):
            if hasattr(sys, '_MEIPASS'):
                candidate_pythons.append(os.path.join(sys._MEIPASS, "python_base", exe_name))
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            candidate_pythons.append(os.path.join(exe_dir, "_internal", "python_base", exe_name))
            candidate_pythons.append(os.path.join(exe_dir, "python_base", exe_name))
            
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        candidate_pythons.append(os.path.join(base_dir, "python_base", exe_name))
        
        portable_py = None
        for py_path in candidate_pythons:
            if os.path.exists(py_path):
                portable_py = py_path
                break
                
        if portable_py:
            self.python_cmd = [portable_py]
        else:
            self.python_cmd = [sys.executable]
            
        # Locate bridge script
        self.bridge_script = os.path.join(base_dir, "plugins", "SuperMatte", "sam_bridge.py")
        if not os.path.exists(self.bridge_script) and getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            self.bridge_script = os.path.join(sys._MEIPASS, "plugins", "SuperMatte", "sam_bridge.py")
                
        self.is_ready = False
        
    def _start_server_if_needed(self, sam_version="SAM 1 (ViT-H)"):
        if self.process is not None and self.process.poll() is None:
            if getattr(self, 'current_sam_version', None) != sam_version:
                print(f"[AI Bridge] Model changed from {getattr(self, 'current_sam_version', None)} to {sam_version}. Restarting server...")
                self.shutdown()
            else:
                return True
            
        self.current_sam_version = sam_version
        print(f"Starting AI Bridge Server (loading {sam_version} to VRAM)...")
        env = os.environ.copy()
        env["HYDRA_FULL_ERROR"] = "1"
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        
        import socket
        import time
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        self.port = s.getsockname()[1]
        s.close()
        
        cmd = self.python_cmd + [self.bridge_script, "--model", sam_version, "--port", str(self.port)]
        
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1, # Line buffered
            env=env,
            creationflags=creationflags
        )
        
        def consume_stdout(pipe):
            try:
                for line in iter(pipe.readline, ''):
                    if not line: break
                    print(f"[AI Bridge STDOUT] {line.strip()}", flush=True)
            except (ValueError, OSError): pass
            
        def consume_stderr(pipe):
            try:
                for line in iter(pipe.readline, ''):
                    if not line: break
                    print(f"[AI Bridge STDERR] {line.strip()}", flush=True)
            except (ValueError, OSError): pass
            
        threading.Thread(target=consume_stdout, args=(self.process.stdout,), daemon=True).start()
        threading.Thread(target=consume_stderr, args=(self.process.stderr,), daemon=True).start()
        
        connected = False
        self.sock = None
        for _ in range(300):
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.connect(('127.0.0.1', self.port))
                self.sock_in = self.sock.makefile('r')
                self.sock_out = self.sock.makefile('w')
                connected = True
                break
            except ConnectionRefusedError:
                if self.process.poll() is not None:
                    err = self.process.stderr.read()
                    print(f"[AI Bridge] Process crashed during startup: {err}")
                    break
                time.sleep(0.1)
                
        if not connected:
            print("[AI Bridge] Failed to connect to backend server")
            self.shutdown()
            return False
            
        self.is_ready = True
        return True

        
    def query_mask(self, image_path, points, labels, fill_color_hex="#f97316", out_mask_path=None, sam_version="SAM 1 (ViT-H)", boxes=None, text_prompt=""):
        """
        Sends coordinates to the persistent server and returns a QImage overlay mask.
        """
        with self.lock:
            if not self._start_server_if_needed(sam_version):
                return None
                
            temp_dir = SettingsManager().get("temp_dir")
            os.makedirs(temp_dir, exist_ok=True)
            temp_mask = out_mask_path or os.path.join(temp_dir, f"utvfx_bridge_mask_{uuid.uuid4().hex}.png")
            
            payload = {
                "image_path": image_path,
                "points": points,
                "labels": labels,
                "mask_out_path": temp_mask
            }
            if boxes is not None:
                payload["boxes"] = boxes
            if text_prompt:
                payload["text_prompt"] = text_prompt
            
            try:
                print(json.dumps(payload), file=self.sock_out, flush=True)
                
                # Wait for response
                while True:
                    resp_line = self.sock_in.readline()
                    if not resp_line:
                        return None
                        
                    resp_line = resp_line.strip()
                    if not resp_line: continue
                    
                    if resp_line.startswith("{"):
                        resp = json.loads(resp_line)
                        if resp.get("status") == "ok":
                            return self._process_mask_to_qimage(temp_mask, fill_color_hex)
                        else:
                            print(f"[AI Bridge Error] {resp.get('error')}")
                            print(f"[AI Bridge Traceback] {resp.get('traceback')}")
                            return None
                    else:
                        print(f"[AI Bridge Debug] {resp_line}")
                        
            except Exception as e:
                print(f"[AI Bridge Exception] {str(e)}")
                return None
                
    def track_video(self, frames_dir, start_frame_idx, prompts, out_dir, sam_version="SAM 2 (SAMURAI)"):
        """
        Requests the backend to track a video sequence using SAMURAI.
        prompts: list of { "frame": int, "obj_id": int, "points": [], "labels": [], "box": [] }
        """
        with self.lock:
            if not self._start_server_if_needed(sam_version):
                return False
                
            payload = {
                "action": "track_video",
                "frames_dir": frames_dir,
                "start_frame_idx": start_frame_idx,
                "prompts": prompts,
                "out_dir": out_dir
            }
            
            try:
                self.sock_out.write(json.dumps(payload) + "\n")
                self.sock_out.flush()
                
                # Wait for response
                while True:
                    resp_line = self.sock_in.readline()
                    if not resp_line:
                        return False
                        
                    resp_line = resp_line.strip()
                    if not resp_line: continue
                    
                    if resp_line.startswith("{"):
                        resp = json.loads(resp_line)
                        if resp.get("status") == "ok":
                            return True
                        elif resp.get("status") == "progress":
                            # We could emit a progress signal here if we wanted
                            pass
                        else:
                            import tempfile
                            import os
                            with open(os.path.join(tempfile.gettempdir(), 'ai_bridge_error.log'), 'w') as f:
                                f.write(f"Error: {resp.get('error')}\n")
                                f.write(f"Traceback: {resp.get('traceback')}\n")
                            print(f"[AI Bridge Error] {resp.get('error')}")
                            print(f"[AI Bridge Traceback] {resp.get('traceback')}")
                            return False
                    else:
                        print(f"[AI Bridge Debug] {resp_line}")
                        
            except Exception as e:
                print(f"[AI Bridge Exception] {str(e)}")
                return False
                
    def auto_scan(self, image_path, text_prompt="", sam_version="SAM 3 (ViT-B)"):
        """
        Requests the backend to auto-scan the image and return a list of top object points.
        Returns: list of (x_norm, y_norm, score)
        """
        with self.lock:
            if not self._start_server_if_needed(sam_version):
                return None
                
            payload = {
                "action": "auto_scan",
                "image_path": image_path,
                "text_prompt": text_prompt
            }
            
            try:
                self.sock_out.write(json.dumps(payload) + "\n")
                self.sock_out.flush()
                
                while True:
                    resp_line = self.sock_in.readline()
                    if not resp_line:
                        return None
                        
                    resp_line = resp_line.strip()
                    if not resp_line: continue
                    
                    if resp_line.startswith("{"):
                        resp = json.loads(resp_line)
                        if resp.get("status") == "ok":
                            return resp.get("objects", [])
                        else:
                            print(f"[AI Bridge Error] {resp.get('error')}")
                            print(f"[AI Bridge Traceback] {resp.get('traceback')}")
                            return None
                    else:
                        print(f"[AI Bridge Debug] {resp_line}")
                        
            except Exception as e:
                print(f"[AI Bridge Exception] {str(e)}")
                return None
                
    def _process_mask_to_qimage(self, mask_path, hex_color):
        if not os.path.exists(mask_path):
            print(f"[AI Bridge] Mask path not found: {mask_path}")
            return None
            
        # Read the raw mask (0 or 255)
        mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
        if mask is None:
            print(f"[AI Bridge] cv2 failed to read mask at: {mask_path}")
            return None
            
        h, w = mask.shape
        print(f"[AI Bridge] Mask loaded. Shape: {w}x{h}. Min: {mask.min()} Max: {mask.max()}")
        
        # Parse color
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        
        # Create an RGBA numpy array
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        
        # Apply color only where mask > 127
        active_pixels = mask > 127
        rgba[active_pixels] = [b, g, r, 160] # BGRA
        
        # The safest way is to use QImage from buffer
        qimg = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_ARGB32).copy()
        
        print(f"[AI Bridge] QImage created. isNull: {qimg.isNull()}")
        
        return qimg

    def shutdown(self):
        self.is_ready = False
        if getattr(self, 'sock_out', None) is not None:
            try:
                self.sock_out.write(json.dumps({"action": "shutdown"}) + "\n")
                self.sock_out.flush()
                self.sock.close()
            except Exception:
                pass
            finally:
                self.sock_out = None
                self.sock_in = None
                self.sock = None
                
        if self.process:
            try:
                self.process.wait(timeout=3.0)
            except Exception:
                pass
            finally:
                if self.process.poll() is None:
                    self.process.terminate()
            self.process = None

import os
import sys
import json
import subprocess
import threading
import tempfile
import cv2
import numpy as np
from PySide6.QtGui import QImage, QColor

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

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
        self.bridge_script = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "plugins", "SAM3Rotoscope", "sam_bridge.py"
        )
        exe_name = "python.exe" if os.name == "nt" else "python"
        portable_py = os.path.join(os.path.dirname(os.path.dirname(__file__)), "python_base", exe_name)
        if os.path.exists(portable_py):
            self.python_exe = portable_py
        else:
            self.python_exe = sys.executable
        self.is_ready = False
        
    def _start_server_if_needed(self):
        if self.process is not None and self.process.poll() is None:
            return True
            
        print("Starting AI Bridge Server (loading model to VRAM)...")
        self.process = subprocess.Popen(
            [self.python_exe, self.bridge_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1 # Line buffered
        )
        
        # Wait for "READY" and "INITIALIZED"
        while True:
            line = self.process.stdout.readline()
            if not line:
                break
            line = line.strip()
            print(f"[AI Bridge] {line}")
            if line == "INITIALIZED":
                self.is_ready = True
                return True
            elif line.startswith("ERROR"):
                print(f"Failed to initialize AI Bridge: {line}")
                return False
                
        return False
        
    def query_mask(self, image_path, points, labels, fill_color_hex="#f97316", out_mask_path=None):
        """
        Sends coordinates to the persistent server and returns a QImage overlay mask.
        """
        with self.lock:
            if not self._start_server_if_needed():
                return None
                
            import uuid
            temp_mask = out_mask_path or os.path.join(TEMP_DIR, f"utvfx_bridge_mask_{uuid.uuid4().hex}.png")
            
            payload = {
                "image_path": image_path,
                "points": points,
                "labels": labels,
                "mask_out_path": temp_mask
            }
            
            try:
                self.process.stdin.write(json.dumps(payload) + "\n")
                self.process.stdin.flush()
                
                # Wait for response
                while True:
                    resp_line = self.process.stdout.readline()
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
        qimg = QImage(rgba.data, w, h, w * 4, QImage.Format_ARGB32).copy()
        
        import uuid
        debug_path = os.path.join(TEMP_DIR, f"utvfx_debug_mask_{uuid.uuid4().hex}.png")
        qimg.save(debug_path)
        print(f"[AI Bridge] QImage created and saved to {debug_path}. isNull: {qimg.isNull()}")
        
        return qimg

    def shutdown(self):
        if self.process:
            try:
                self.process.stdin.write(json.dumps({"action": "shutdown"}) + "\n")
                self.process.stdin.flush()
                self.process.wait(timeout=3.0)
            except Exception:
                pass
            finally:
                if self.process.poll() is None:
                    self.process.terminate()
            self.process = None

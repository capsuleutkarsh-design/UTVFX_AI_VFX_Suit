import json
import logging
import os
import secrets
import select
import socket
import subprocess
import sys
import threading
import time
import uuid

import cv2
import numpy as np
from PySide6.QtGui import QImage

from utvfx.core.settings_manager import SettingsManager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
log = logging.getLogger(__name__)

# How long a cold start may take (loading SAM ViT-H or SAM 3 to the GPU can be slow).
STARTUP_TIMEOUT = 600
# Per-request limits. Video tracking has none: it is cancelled instead.
MASK_TIMEOUT = 180
SCAN_TIMEOUT = 600


class BridgeCancelled(Exception):
    pass


class AIBridgeClient:
    """Runs the SAM models in a separate process and talks to it over a local socket.

    The server only accepts a connection that presents the random token it was
    started with, so other programs on the machine cannot drive it. Every error is
    kept in `last_error` so callers can show it instead of "check the terminal".
    """

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = AIBridgeClient()
        return cls._instance

    def __init__(self):
        self.process = None
        self.sock = self.sock_in = self.sock_out = None
        self.lock = threading.Lock()
        self._cancel = threading.Event()
        self.last_error = ""
        self.current_sam_version = None
        self.is_ready = False

        exe_name = "python.exe" if os.name == "nt" else "python"
        candidate_pythons = []
        if getattr(sys, 'frozen', False):
            if hasattr(sys, '_MEIPASS'):
                candidate_pythons.append(os.path.join(sys._MEIPASS, "python_base", exe_name))
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            candidate_pythons.append(os.path.join(exe_dir, "_internal", "python_base", exe_name))
            candidate_pythons.append(os.path.join(exe_dir, "python_base", exe_name))
        candidate_pythons.append(os.path.join(BASE_DIR, "python_base", exe_name))
        portable_py = next((p for p in candidate_pythons if os.path.exists(p)), None)
        self.python_cmd = [portable_py or sys.executable]

        self.bridge_script = os.path.join(BASE_DIR, "plugins", "SuperMatte", "sam_bridge.py")
        if not os.path.exists(self.bridge_script) and getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            self.bridge_script = os.path.join(sys._MEIPASS, "plugins", "SuperMatte", "sam_bridge.py")

    # ---- process lifecycle --------------------------------------------------
    def _fail(self, message):
        self.last_error = message
        log.error("AI engine: %s", message)
        print(f"[AI Bridge] {message}", flush=True)

    def _start_server_if_needed(self, sam_version="SAM 1 (ViT-H)"):
        if self.process is not None and self.process.poll() is None and self.sock is not None:
            if self.current_sam_version == sam_version:
                return True
            print(f"[AI Bridge] Switching model from {self.current_sam_version} to {sam_version}.", flush=True)
            self._shutdown_locked()

        self.current_sam_version = sam_version
        self.last_error = ""
        print(f"Starting AI engine (loading {sam_version})...", flush=True)

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(('127.0.0.1', 0))
        self.port = probe.getsockname()[1]
        probe.close()
        self.token = secrets.token_hex(16)

        env = os.environ.copy()
        env["HYDRA_FULL_ERROR"] = "1"
        env["CONTOUR_BRIDGE_TOKEN"] = self.token  # not on the command line, where other users could read it
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        cmd = self.python_cmd + [self.bridge_script, "--model", sam_version, "--port", str(self.port)]
        self._stderr_tail = []
        self.process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, bufsize=1, env=env, creationflags=creationflags)

        def pump(pipe, tag, keep=None):
            try:
                for line in iter(pipe.readline, ''):
                    line = line.rstrip()
                    if keep is not None:
                        keep.append(line)
                        del keep[:-40]
                    print(f"[AI Bridge {tag}] {line}", flush=True)
            except (ValueError, OSError):
                pass

        threading.Thread(target=pump, args=(self.process.stdout, "out"), daemon=True).start()
        threading.Thread(target=pump, args=(self.process.stderr, "err", self._stderr_tail), daemon=True).start()

        # The server binds its port once the model is loaded; wait as long as it is alive.
        deadline = time.time() + STARTUP_TIMEOUT
        while time.time() < deadline:
            if self._cancel.is_set():
                self._shutdown_locked()
                raise BridgeCancelled()
            if self.process.poll() is not None:
                tail = "\n".join(self._stderr_tail[-8:]) or "no output"
                self._fail(f"The AI engine stopped while loading {sam_version}:\n{tail}")
                self._shutdown_locked()
                return False
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.settimeout(2.0)
                sock.connect(('127.0.0.1', self.port))
            except OSError:
                sock.close()  # never leak the probe socket
                time.sleep(0.25)
                continue
            sock.settimeout(None)  # blocking; replies are waited for with select(), so a wait never breaks the stream
            self.sock = sock
            self._rbuf = b""
            self.sock_in = True  # replies are read by _readline()
            self.sock_out = sock.makefile('w', encoding='utf-8')
            self._send({"token": self.token})
            self.is_ready = True
            return True

        self._fail(f"The AI engine did not start within {STARTUP_TIMEOUT // 60} minutes.")
        self._shutdown_locked()
        return False

    # ---- requests -----------------------------------------------------------
    def _send(self, payload):
        self.sock_out.write(json.dumps(payload) + "\n")
        self.sock_out.flush()

    def _readline(self, wait):
        """One reply line, or None if nothing arrived within `wait` seconds. '' means the engine closed."""
        while b"\n" not in self._rbuf:
            ready, _, _ = select.select([self.sock], [], [], wait)
            if not ready:
                return None
            chunk = self.sock.recv(65536)
            if not chunk:
                return ""
            self._rbuf += chunk
        line, self._rbuf = self._rbuf.split(b"\n", 1)
        return line.decode("utf-8", errors="replace") + "\n"

    def _request(self, payload, timeout, on_progress=None):
        """Send one request and wait for its final JSON reply. Returns the reply or None."""
        self._send(payload)
        deadline = None if timeout is None else time.time() + timeout
        while True:
            if self._cancel.is_set():
                # The only way to stop the model mid-run is to end the process.
                self._shutdown_locked()
                raise BridgeCancelled()
            if deadline is not None and time.time() > deadline:
                self._fail(f"The AI engine did not answer within {timeout} s.")
                self._shutdown_locked()
                return None
            line = self._readline(1.0)
            if line is None:
                continue  # nothing yet: check cancel and the deadline again
            if not line:
                tail = "\n".join(self._stderr_tail[-8:])
                self._fail("The AI engine closed the connection." + (f"\n{tail}" if tail else ""))
                self._shutdown_locked()
                return None
            line = line.strip()
            if not line.startswith("{"):
                if line:
                    print(f"[AI Bridge] {line}", flush=True)
                continue
            reply = json.loads(line)
            status = reply.get("status")
            if status == "progress":
                if on_progress:
                    on_progress(reply)
                continue
            if status != "ok":
                self._fail(f"{reply.get('error', 'Unknown error')}\n{reply.get('traceback', '')}".strip())
            return reply

    def _run(self, sam_version, payload, timeout, on_progress=None):
        with self.lock:
            self._cancel.clear()
            self.last_error = ""
            try:
                if not self._start_server_if_needed(sam_version):
                    return None
                return self._request(payload, timeout, on_progress)
            except BridgeCancelled:
                self.last_error = "Cancelled."
                return None
            except (OSError, ValueError) as e:
                self._fail(f"Lost the connection to the AI engine: {e}")
                self._shutdown_locked()
                return None

    def cancel(self):
        """Stop the request in progress (from any thread)."""
        self._cancel.set()

    def query_mask(self, image_path, points, labels, fill_color_hex="#f97316", out_mask_path=None,
                   sam_version="SAM 1 (ViT-H)", boxes=None, text_prompt=""):
        """Segment one image from clicks/boxes. Returns a QImage overlay or None (see last_error)."""
        temp_dir = SettingsManager().get("temp_dir")
        os.makedirs(temp_dir, exist_ok=True)
        mask_path = out_mask_path or os.path.join(temp_dir, f"utvfx_bridge_mask_{uuid.uuid4().hex}.png")
        payload = {"image_path": image_path, "points": points, "labels": labels, "mask_out_path": mask_path}
        if boxes is not None:
            payload["boxes"] = boxes
        if text_prompt:
            payload["text_prompt"] = text_prompt
        reply = self._run(sam_version, payload, MASK_TIMEOUT)
        if not reply or reply.get("status") != "ok":
            return None
        return self._process_mask_to_qimage(mask_path, fill_color_hex)

    def track_video(self, frames_dir, start_frame_idx, prompts, out_dir, sam_version="SAM 2 (SAMURAI)",
                    on_progress=None):
        """Track objects through a frame folder with SAMURAI. Cancel with cancel()."""
        payload = {"action": "track_video", "frames_dir": frames_dir, "start_frame_idx": start_frame_idx,
                   "prompts": prompts, "out_dir": out_dir}
        reply = self._run(sam_version, payload, None, on_progress)
        return bool(reply and reply.get("status") == "ok")

    def auto_scan(self, image_path, text_prompt="", sam_version="SAM 3 (ViT-B)"):
        """Find objects in an image. Returns [(x_norm, y_norm, score)] or None (see last_error)."""
        payload = {"action": "auto_scan", "image_path": image_path, "text_prompt": text_prompt}
        reply = self._run(sam_version, payload, SCAN_TIMEOUT)
        if not reply or reply.get("status") != "ok":
            return None
        return reply.get("objects", [])

    def _process_mask_to_qimage(self, mask_path, hex_color):
        mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE) if os.path.exists(mask_path) else None
        if mask is None:
            self._fail(f"The AI engine reported success but wrote no mask ({mask_path}).")
            return None
        h, w = mask.shape
        hex_color = hex_color.lstrip('#')
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[mask > 127] = [b, g, r, 160]  # BGRA
        return QImage(rgba.data, w, h, w * 4, QImage.Format.Format_ARGB32).copy()

    # ---- shutdown -----------------------------------------------------------
    def _shutdown_locked(self):
        self.is_ready = False
        if self.sock_out is not None:
            try:
                self._send({"action": "shutdown"})
            except (OSError, ValueError):
                pass
        for closable in (self.sock_out, self.sock):
            try:
                if closable is not None:
                    closable.close()
            except (OSError, ValueError):
                pass
        self.sock = self.sock_in = self.sock_out = None
        if self.process is not None:
            try:
                self.process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3.0)
            self.process = None

    def shutdown(self):
        """Stop the engine and free its GPU memory. Cancels a running request first."""
        self._cancel.set()
        with self.lock:
            self._shutdown_locked()
            self._cancel.clear()

    def shutdown_async(self):
        """shutdown() without blocking the calling (UI) thread."""
        threading.Thread(target=self.shutdown, name="bridge-shutdown", daemon=True).start()

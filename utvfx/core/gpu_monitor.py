"""Whole-GPU usage for the status bar, read from nvidia-smi on a background thread.

torch.cuda only sees memory allocated by this process; the SAM engine runs in its
own process, so the status bar asks the driver instead.
"""
import shutil
import subprocess
import threading
import time

_latest = {"text": ""}


def _poll(interval):
    exe = shutil.which("nvidia-smi")
    if not exe:
        return
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    query = ["--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"]
    while True:
        try:
            out = subprocess.run([exe] + query, capture_output=True, text=True, timeout=5, creationflags=flags).stdout
            util, used, total = [v.strip() for v in out.splitlines()[0].split(",")]
            _latest["text"] = f"GPU {util}%  VRAM {int(used) / 1024:.1f}/{int(total) / 1024:.0f} GB"
        except Exception:
            _latest["text"] = ""
        time.sleep(interval)


def start(interval=2.0):
    threading.Thread(target=_poll, args=(interval,), name="gpu-monitor", daemon=True).start()


def reading():
    return _latest["text"]

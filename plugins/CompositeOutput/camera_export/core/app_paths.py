"""Where COLMAP lives in this app."""
import importlib
from pathlib import Path


def colmap_exe():
    return Path(importlib.import_module("plugins.3DTracker.backend").COLMAP_EXE)

"""Render a saved project without the window: python render.py shot.contour [--node N] [--frames 1001-1050]."""
import os
import sys

# The embedded Python (python_base, ._pth file) does not add the script folder to the path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utvfx.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

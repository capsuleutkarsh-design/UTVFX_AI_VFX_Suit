"""ContourVFX.exe: starts the app with the Python environment installed next to it.

The installed app is the source code plus its own Python (python_base), exactly as it runs
from a checkout; this small exe only gives it a normal program to click. Command-line
arguments are passed on.
"""
import ctypes
import os
import subprocess
import sys


def main():
    here = os.path.dirname(os.path.abspath(sys.executable))
    pythonw = os.path.join(here, "python_base", "pythonw.exe")
    script = os.path.join(here, "main.py")
    for path in (pythonw, script):
        if not os.path.isfile(path):
            ctypes.windll.user32.MessageBoxW(
                None, f"Contour VFX is missing a file it needs:\n\n{path}\n\nReinstall the app.",
                "Contour VFX", 0x10)
            return 1
    subprocess.Popen([pythonw, script] + sys.argv[1:], cwd=here, close_fds=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

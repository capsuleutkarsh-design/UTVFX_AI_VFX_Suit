"""The Python half of BUILD.bat: stage the app, make ContourVFX.exe, check the result.

    python_base\\python.exe build\\build_app.py            stage + launcher + verify
    python_base\\python.exe build\\build_app.py --clean    remove the old stage first
    python_base\\python.exe build\\build_app.py --check    prerequisites only
    python_base\\python.exe build\\build_app.py --no-verify

The installed app is the app as it runs from a checkout: the tracked source files (with the
submodules), the portable Python in python_base with every package, and ContourVFX.exe, a
small launcher. Nothing is frozen, so the installed app runs exactly the tested environment.
Models are not packed; the installer downloads them (download_models.bat), pinned and hashed.

Output: build\\stage\\ContourVFX\\ (what Inno packs) and build\\version.iss.
"""
import argparse
import fnmatch
import os
import shutil
import subprocess
import sys
import time

BUILD = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BUILD)
STAGE = os.path.join(BUILD, "stage", "ContourVFX")
TOOLS = os.path.join(BUILD, "_tools")
PYTHON = os.path.join(ROOT, "python_base", "python.exe")
PYINSTALLER = "pyinstaller==6.16.0"

# Tracked files that the installed app does not need (development files, and the demo
# media and notebooks that come with the upstream submodules).
SKIP = [
    "tests/*", "audit_reports/*", "build/*", ".git*", "ISSUES.md", "ROADMAP.md", "FIRST_SETUP.bat", "run.bat",
    "pytest.ini", "pyrightconfig.json",
    "plugins/Depth-Anything-V2/assets/*", "plugins/Depth-Anything-V2/metric_depth/assets/*",
    "plugins/Depth-Anything-V2/metric_depth/dataset/*", "models/SAMURAI/assets/*",
    "models/SAMURAI/sam2/sav_dataset/*", "*/notebooks/*", "*.ipynb", "*.mp4", "*.gif",
]
# Inside python_base, left out because nothing loads them when the app runs: caches, the
# packages' own test suites, C/C++ headers and .lib files (only used to compile against a
# package; dnnl.lib alone is 624 MB) and Qt's QML and translations (the app uses widgets, in
# English). About 14,000 of 32,600 files and 0.9 GB: the install is much faster. The build
# checks the result by running the whole test suite with the trimmed interpreter.
PY_SKIP_DIRS = {"__pycache__", "tests"}
PY_SKIP_PATHS = ["Lib/site-packages/torch/include", "Lib/site-packages/PySide6/include",
                 "Lib/site-packages/PySide6/qml", "Lib/site-packages/PySide6/translations",
                 "Lib/site-packages/shiboken6/include"]
PY_SKIP_FILES = (".pyc", ".lib", ".pdb")
REQUIRED_IMPORTS = ["torch", "torchvision", "PySide6", "cv2", "OpenImageIO", "numpy", "transformers",
                    "diffusers", "mediapipe", "onnxruntime", "huggingface_hub", "timm", "kornia"]


def log(msg):
    print(f"[build] {msg}", flush=True)


def fail(msg):
    print(f"\n[build] ERROR: {msg}\n", flush=True)
    sys.exit(1)


def app_version():
    namespace = {}
    with open(os.path.join(ROOT, "utvfx", "version.py"), encoding="utf-8") as f:
        exec(f.read(), namespace)
    return namespace["APP_NAME"], namespace["VERSION"]


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


# ---- checks ---------------------------------------------------------------
def check():
    problems = []
    if not os.path.isfile(PYTHON):
        problems.append(f"python_base is missing ({PYTHON}). Run FIRST_SETUP.bat first.")
    else:
        probe = subprocess.run([PYTHON, "-c", "import importlib,sys\n"
                                "missing=[m for m in sys.argv[1:] if importlib.util.find_spec(m) is None]\n"
                                "print(','.join(missing))"] + REQUIRED_IMPORTS,
                               capture_output=True, text=True)
        missing = probe.stdout.strip()
        if probe.returncode or missing:
            problems.append(f"python_base lacks packages: {missing or probe.stderr.strip()}. Run FIRST_SETUP.bat.")
    if shutil.which("git") is None:
        problems.append("git is not on PATH (needed to list the files to package).")
    else:
        status = subprocess.run(["git", "-C", ROOT, "submodule", "status"], capture_output=True, text=True).stdout
        if any(line.startswith("-") for line in status.splitlines()):
            problems.append("some git submodules are not checked out: git submodule update --init --depth 1")
    free = shutil.disk_usage(BUILD).free
    if free < 20e9:
        problems.append(f"only {free / 1e9:.0f} GB free; the build needs about 20 GB.")
    for p in problems:
        print(f"[build] PROBLEM: {p}")
    if not problems:
        name, version = app_version()
        log(f"{name} {version}: prerequisites OK ({free / 1e9:.0f} GB free).")
    return not problems


# ---- staging --------------------------------------------------------------
def tracked_files():
    out = run(["git", "-C", ROOT, "ls-files", "--recurse-submodules", "-z"], capture_output=True).stdout
    files = [p for p in out.decode("utf-8").split("\0") if p]
    return [p for p in files if not any(fnmatch.fnmatch(p, pat) for pat in SKIP)
            and os.path.isfile(os.path.join(ROOT, p))]


def stage_source():
    files = tracked_files()
    for rel in files:
        dst = os.path.join(STAGE, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, rel), dst)
    log(f"Source: {len(files)} files.")


def stage_python():
    src = os.path.join(ROOT, "python_base")
    dst = os.path.join(STAGE, "python_base")

    def ignore(folder, names):
        rel = os.path.relpath(folder, src).replace("\\", "/")
        skipped = []
        for n in names:
            path = f"{rel}/{n}" if rel != "." else n
            if n in PY_SKIP_DIRS or n.lower().endswith(PY_SKIP_FILES) or path in PY_SKIP_PATHS:
                skipped.append(n)
        return skipped

    shutil.copytree(src, dst, ignore=ignore)
    files = [os.path.join(d, f) for d, _, fs in os.walk(dst) for f in fs]
    log(f"Python environment: {sum(map(os.path.getsize, files)) / 1e9:.1f} GB, {len(files)} files.")


def build_launcher():
    """ContourVFX.exe via PyInstaller, installed in build\\_tools so python_base stays as tested."""
    target = os.path.join(TOOLS, "pyinstaller")
    if not os.path.isdir(os.path.join(target, "PyInstaller")):
        log(f"Installing {PYINSTALLER} into build\\_tools (not into python_base)...")
        run([PYTHON, "-m", "pip", "install", "--quiet", "--target", target, PYINSTALLER])
    work = os.path.join(TOOLS, "launcher_work")
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import PyInstaller.__main__ as m; "
            "m.run(sys.argv[2:])")
    run([PYTHON, "-c", code, target, os.path.join(BUILD, "launcher.py"), "--onefile", "--noconsole",
         "--name", "ContourVFX", "--icon", os.path.join(ROOT, "branding", "app_icon.ico"),
         "--distpath", STAGE, "--workpath", work, "--specpath", work, "--noconfirm", "--log-level", "WARN"])
    log("Launcher: ContourVFX.exe.")


def write_extras(version):
    with open(os.path.join(STAGE, "download_models.bat"), "w", newline="\r\n") as f:
        f.write('@echo off\n'
                'rem Downloads the AI models and the COLMAP/FFmpeg tools (about 27 GB), pinned and checked.\n'
                'rem Safe to run again: finished files are skipped and interrupted ones resume.\n'
                'cd /d "%~dp0"\n'
                '"%~dp0python_base\\python.exe" -u "%~dp0first_setup.py" --skip-deps\n'
                'echo.\n'
                'pause\n')
    with open(os.path.join(BUILD, "version.iss"), "w") as f:
        f.write(f'#define AppVersion "{version}"\n')


# ---- verification -----------------------------------------------------------
def verify():
    """Run the staged app from the stage: imports, CUDA, and the main window created off-screen."""
    py = os.path.join(STAGE, "python_base", "python.exe")
    code = r'''
import os, sys
root = sys.argv[1]
sys.path.insert(0, root)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import torch
print("torch", torch.__version__, "CUDA", torch.cuda.is_available())
from PySide6.QtWidgets import QApplication
app = QApplication([])
import main
window = main.VFXCoreWindow()
from utvfx.core.data_model import NODES_REGISTRY
print("nodes", len(NODES_REGISTRY))
window.undo_stack.setClean()
window.close()
'''
    result = subprocess.run([py, "-c", code, STAGE], capture_output=True, text=True, cwd=STAGE, timeout=600)
    print(result.stdout.strip())
    # The check makes settings and a workspace in the stage; they must not be shipped.
    for leftover in ("settings.json", "workspace", "crash.log"):
        path = os.path.join(STAGE, leftover)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.isfile(path):
            os.remove(path)
    for folder, dirs, _ in os.walk(STAGE):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(folder, d))
                dirs.remove(d)
    if result.returncode != 0 or "nodes" not in result.stdout:
        print(result.stderr[-3000:])
        fail("the staged app did not start.")
    log("Verified: the staged app starts.")

    # The whole test suite (except tests needing model weights) with the staged, trimmed
    # interpreter: proves that nothing it needs was left out.
    log("Running the test suite with the staged Python...")
    tests = subprocess.run([py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "not models",
                            os.path.join(ROOT, "tests")], capture_output=True, text=True, cwd=ROOT)
    summary = (tests.stdout.strip().splitlines() or ["(no output)"])[-1]
    for folder, dirs, _ in os.walk(os.path.join(STAGE, "python_base")):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(folder, d))
                dirs.remove(d)
    if tests.returncode != 0:
        print(tests.stdout[-4000:])
        fail(f"tests failed with the staged Python: {summary}")
    log(f"Tests: {summary}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--no-verify", action="store_true")
    args = parser.parse_args()

    if not check():
        fail("fix the problems above and build again.")
    if args.check:
        return
    name, version = app_version()
    start = time.time()
    if os.path.isdir(STAGE):
        log("Removing the previous stage...")
        shutil.rmtree(STAGE)
    if args.clean and os.path.isdir(TOOLS):
        shutil.rmtree(TOOLS)
    os.makedirs(STAGE)
    log(f"Staging {name} {version} into build\\stage\\ContourVFX ...")
    stage_source()
    stage_python()
    build_launcher()
    write_extras(version)
    if not args.no_verify:
        verify()
    log(f"Stage ready in {time.time() - start:.0f} s.")


if __name__ == "__main__":
    main()

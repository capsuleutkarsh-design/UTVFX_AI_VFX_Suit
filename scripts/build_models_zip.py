"""Pack the model weights into releases/ContourVFX_Models.zip for offline installs.

Only data files under models/ go in: the in-app importer (and the installer) refuse
plugins/, code files and anything outside models/ (utvfx/core/downloads.py), so the
ZIP holds exactly what they will accept.
"""

import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utvfx.core.downloads import BLOCKED_EXTENSIONS  # noqa: E402

ZIP_NAME = os.path.join(ROOT, "releases", "ContourVFX_Models.zip")
# Download leftovers, and TensorFlow/Flax copies of weights the app never loads.
SKIP_SUFFIXES = (".part", ".incomplete", ".lock", ".h5", ".msgpack")


def collect_model_files():
    """{zip path: size} of every data file under models/."""
    files = {}
    models_dir = os.path.join(ROOT, "models")
    for root, dirs, names in os.walk(models_dir):
        # Skip hidden folders like .git or .cache (HF download metadata)
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for name in names:
            if name.startswith(".") or name.endswith(SKIP_SUFFIXES):
                continue
            if os.path.splitext(name)[1].lower() in BLOCKED_EXTENSIONS:
                continue  # model code ships with the app, never in the ZIP
            path = os.path.join(root, name)
            files[os.path.relpath(path, ROOT).replace("\\", "/")] = os.path.getsize(path)
    return files


def create_models_zip():
    os.makedirs(os.path.dirname(ZIP_NAME), exist_ok=True)
    local_models = collect_model_files()

    # Check if the zip already exists and has all the required models
    needs_update = True
    if os.path.exists(ZIP_NAME):
        try:
            with zipfile.ZipFile(ZIP_NAME, "r") as zipf:
                zip_info = {info.filename: info.file_size for info in zipf.infolist()}
            needs_update = zip_info != local_models
        except zipfile.BadZipFile:
            needs_update = True

    if not needs_update:
        print(f"{ZIP_NAME} is already up to date. Skipping zip creation.")
        return

    print(f"Models have changed or zip is missing. Creating {ZIP_NAME}...")
    tmp = ZIP_NAME + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zipf:
        for zip_path in sorted(local_models):
            print(f"Adding {zip_path}")
            zipf.write(os.path.join(ROOT, *zip_path.split("/")), arcname=zip_path)
    os.replace(tmp, ZIP_NAME)

    print(f"\nSuccessfully created {ZIP_NAME}")
    print("You can upload this ZIP alongside your Setup.exe to GitHub.")


if __name__ == "__main__":
    create_models_zip()

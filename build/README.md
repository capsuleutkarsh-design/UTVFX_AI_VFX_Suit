# Building Contour VFX

Double-click **`build\BUILD.bat`**. It makes a Windows installer in `build\Output\`:

```
ContourVFX_Setup_<version>.exe
ContourVFX_Setup_<version>-1.bin
ContourVFX_Setup_<version>-2.bin
...
```

The installer is the exe **plus every `.bin` beside it**. The app and its Python environment (PyTorch with CUDA is most of it) come to about 6 GB. Inno Setup cannot write a single setup file past 2,097,152,000 bytes, so it writes a small exe and splits the data into `.bin` slices of up to 1.9 GB. Ship the whole `Output` folder: the exe on its own installs nothing.

```
BUILD.bat              full build (stage the app, then the installer)
BUILD.bat clean        same, but reinstall the build tools first
BUILD.bat stage        only step 1: build\stage\ContourVFX, ready to run
BUILD.bat installer    only step 2: re-pack the last stage
BUILD.bat check        check that everything needed is there; build nothing
BUILD.bat models       the offline model pack (see below)
BUILD.bat ... noverify skip starting the staged app (any mode)
```

## What you need

| | |
|---|---|
| This checkout, set up | `FIRST_SETUP.bat` done, so `python_base\` exists with every package |
| Git | on PATH, with the submodules checked out |
| Inno Setup 6 | https://jrsoftware.org/isdl.php |
| Disk | about 20 GB free while building |
| Time | under a minute for step 1; the compression in step 2 takes much longer |

PyInstaller is only used for the small launcher and is installed into `build\_tools\`, never into `python_base`.

## How it works

**Step 1, `build_app.py`** makes `build\stage\ContourVFX\`, which is exactly what gets installed:

- **Source:** every file git tracks, including the submodules. Development files (tests, audit reports, issue lists) and the demo videos and notebooks that come with the upstream submodules are left out.
- **Python:** `python_base\`, the same portable Python 3.10 with the same packages the app is tested with, without `__pycache__`.
- **Launcher:** `ContourVFX.exe`, a 5 MB program that starts `python_base\pythonw.exe main.py`, so the app is started like any other program.
- **`download_models.bat`:** runs `first_setup.py --skip-deps` to fetch the models.

It then starts the staged app off-screen, checking PyTorch, CUDA and that all the nodes load, and removes anything the check wrote.

The app is not frozen into one exe. It loads its nodes as plugins and runs the AI in a second Python process, so it ships as the tested source plus its own Python. That is what runs on the build machine, without the surprises of freezing.

**Step 2, `installer.iss`** packs the stage with LZMA2 and splits it into `.bin` slices. The installed app:

- installs per user in `%LOCALAPPDATA%\Programs\Contour VFX`, with no admin rights needed, and writes its settings, caches and models next to itself;
- offers, on the last page, to **download the AI models** (about 27 GB, pinned and SHA-256 checked, resumable). Start menu > Contour VFX > Download AI models does the same later;
- can install the models from an **offline model pack** instead, on the wizard's "Offline models" page (see below);
- asks, when uninstalled, whether to delete the downloaded models and the projects/renders too.

The models are not inside the installer: they would add about 27 GB of `.bin` slices, and some model licences do not allow redistributing them (see THIRD_PARTY_NOTICES.md).

## Offline model pack (computers without internet)

`BUILD.bat models`, on a computer where `first_setup.py` has downloaded the models (and with internet), writes

```
build\Output\models\ContourVFX_Models_<version>.zip.001
                    ContourVFX_Models_<version>.zip.002
                    ... (about 15 parts of 1.95 GB, 27.6 GB in all)
```

- **What's in it:** exactly what `first_setup.py` installs: every model the app uses, plus COLMAP and FFmpeg for the 3D Tracker. It is one uncompressed ZIP cut into parts, because single model files are up to 6 GB. 7-Zip opens the `.001` as a normal archive.
- **Checks while packing:** every Hugging Face file is compared with its pinned version's published checksum. SAM 3's repo hides checksums, so it is checked by size.
- **Speed:** an unchanged pack is not rebuilt.
- **Installing:** copy the installer and all the parts to the offline computer. On the installer's **Offline models** page, pick the `.001` file; all parts must be in the same folder. Every file is installed and checked against its SHA-256, and the online download is skipped. Later, the app's **AI models > Install from offline pack** does the same, as does `python_base\python.exe scripts\install_models.py <.001 file>` in the install folder.
- **Licences:** some model licences do not allow sharing the models publicly (see THIRD_PARTY_NOTICES.md). Use the pack on your own computers; do not upload it.

## Version

The version lives in one place, `VERSION` in `utvfx/version.py`. `build_app.py` writes it to `build\version.iss`, which the installer reads for its title and file names.

## Troubleshooting

- **"python_base lacks packages"**: run `FIRST_SETUP.bat` in the checkout first.
- **"some git submodules are not checked out"**: `git submodule update --init --depth 1`.
- **Running the installer says a `.bin` file is missing**: the exe and its `.bin` files were separated; keep them in one folder.
- **The installed app does not start**: look at `%LOCALAPPDATA%\Programs\Contour VFX\workspace\logs\`.

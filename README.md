<p align="center">
  <img src="branding/png/splash.png" alt="Contour VFX" width="720">
</p>

# Contour VFX

**AI roto, mattes and camera tracking for compositors.** A node-based Windows desktop app that runs current AI models (SAM, ViTMatte, MEMatte, CorridorKey, Depth Anything, COLMAP) on your plates and hands the results to Nuke.

> **First-time setup:** model weights (tens of GB) and some binaries are not in the repository. Run `python first_setup.py` once after cloning; see [MODEL_DOWNLOADS.md](MODEL_DOWNLOADS.md).

## Overview
Contour VFX is a high-performance desktop application built to bridge the gap between complex AI-driven computer vision models and professional visual effects workflows. Featuring a node-based architecture, the software allows artists to process image sequences through advanced AI algorithms and automatically export the results to industry-standard software like The Foundry's Nuke.

## Features
*   **Modular Node-Based UI:** An intuitive, visually connecting workspace to stack multiple VFX and AI tasks.
*   **AI matting and roto:** SAM 1, SAM 2 (SAMURAI) and SAM 3 segmentation, refined with ViTMatte, MEMatte or VideoMaMa.
*   **Matte to Shape Conversion:** Translates raw pixel alpha masks into animated vector splines (Nuke Roto Shapes) that preserve point-counts across frames for flawless manual refinement.
*   **Advanced Keying:** `Corridor Keyer` algorithm optimized for high-end despill and despeckle operations.
*   **AI Depth Estimation:** Integration with `Depth Anything V2` to generate dense disparity maps from raw 2D plates.
*   **Nuke Script Exporting:** Generates `.nk` and `.py` scripts natively, instantly bringing AI data (like Rotoscope shapes and 3D Camera tracking) into your compositing software.

## AI model weights
Since the deep learning model weights exceed 20 GB, they are not included in this code repository. 
Please refer to the [MODEL_DOWNLOADS.md](MODEL_DOWNLOADS.md) guide for the official download links and instructions on exactly where to place each model before running the application.

## Requirements and installation
Windows 10/11 x64 and an NVIDIA GPU with a CUDA 12.1-capable driver. About 70 GB of disk for the models.

There is one supported way to install: `first_setup.py`. `install.bat` is a thin wrapper that finds a suitable Python and runs it.

1. Clone the repository with its submodules:
   ```bat
   git clone --recurse-submodules https://github.com/capsuleutkarsh-design/UTVFX_AI_VFX_Suit.git
   cd UTVFX_AI_VFX_Suit
   ```
2. Run the installer:
   ```bat
   install.bat
   ```
   It looks for Python **3.10 or 3.11**, in this order: an existing `python_base\python.exe`, the `py` launcher (`py -3.11`, `py -3.10`), [uv](https://docs.astral.sh/uv/) (`%USERPROFILE%\.local\bin\uv.exe`, which fetches Python 3.10 by itself), then `python` on `PATH`. Python 3.12 and newer are refused: `torch 2.5.1+cu121` and `mediapipe<0.10.10` have no wheels for them. With Python 3.10/3.11 already installed you can run `python first_setup.py` directly instead.

   `first_setup.py` then:
   - updates the git submodules;
   - creates `python_base\`, a portable CPython 3.10.11 (python.org embeddable build, SHA-256 checked, pip bootstrapped from a hash-checked wheel);
   - installs the exact package versions in `requirements-lock.txt` into it (PyTorch comes from the CUDA 12.1 index);
   - downloads the models and binaries: every file is pinned (Hugging Face commit or fixed release URL) with a SHA-256 and size, is written to `<name>.part` first and only renamed once complete and verified. This includes FFmpeg 9.0.2 and COLMAP 4.2.0 (CUDA build, with the GLOMAP global mapper built in) for the 3D Tracker.

   Re-running it is safe: finished items are skipped and an interrupted download resumes. Useful options: `--check` (report only, change nothing), `--verify` (hash every file already present), `--skip-deps`, `--skip-models`. MEMatte weights still have to be downloaded by hand, see [MODEL_DOWNLOADS.md](MODEL_DOWNLOADS.md).
3. Start the app:
   ```bat
   run.bat
   ```

`requirements.txt` is the loose list of top-level packages with their tested version ranges. To change a dependency, edit it, install into `python_base`, run the tests (`python_base\python.exe -m pytest -q`), then regenerate the lock with `python_base\python.exe -m pip freeze` (keep only `opencv-contrib-python`, never `opencv-python` as well).

### Offline installs
Missing models can also be installed from a ZIP (`scripts\build_models_zip.py` builds one) with **AI models > Install from offline ZIP** in the app. Only data files under `models/` are taken from the ZIP; code files, `plugins/` and paths outside `models/` are skipped and listed.

### Troubleshooting: manual FFmpeg installation
If FFmpeg does not download (for example an SSL error such as `[SSL: WRONG_VERSION_NUMBER]`):
1. Download [ffmpeg-9.0.2-essentials_build.zip](https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip) (SHA-256 `60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`).
2. Copy `bin\ffmpeg.exe` from the ZIP to `plugins\3DTracker\bin\ffmpeg.exe`.

## Building the installer
The project is configured for automated distribution packaging via **PyInstaller** and **Inno Setup**.

1. Ensure [Inno Setup 6](https://jrsoftware.org/isinfo.php) is installed.
2. Run the build script to compile the executable and generate the setup wizard:
   ```bash
   build\build_installer.bat
   ```
3. The final installer will be available in the `build/Output/` directory. During setup, users can optionally inject the required heavy ML models via a `.zip` archive.

## Author
Designed and authored by [capsuleutkarsh-design](https://github.com/capsuleutkarsh-design).

## License
This project is proprietary. All rights reserved.

Third-party code, programs and AI models keep their own licences; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Several of the models (CorridorKey, GVM, VideoMaMa, Depth Anything V2 Base/Large) are licensed for non-commercial use only, so the app cannot be distributed or sold as it stands.

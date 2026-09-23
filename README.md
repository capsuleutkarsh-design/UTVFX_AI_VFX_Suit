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
This software relies on Python 3.10+, PySide6, and PyTorch (CUDA required for hardware acceleration).

### Setup for Developers
1. Clone the repository:
   ```bash
   git clone --recurse-submodules https://github.com/capsuleutkarsh-design/UTVFX_AI_VFX_Suit.git
   cd UTVFX_AI_VFX_Suit
   ```
2. Activate a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   call venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Run the main application:
   ```bash
   python main.py
   ```

### Troubleshooting: Manual FFmpeg Installation
If the `first_setup.py` script fails to download FFmpeg due to an SSL error (`[SSL: WRONG_VERSION_NUMBER]`), you must download it manually:
1. Download [ffmpeg-release-essentials.zip](https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip).
2. Extract the `.zip` file.
3. Locate `ffmpeg.exe` inside the `bin/` folder.
4. Copy and paste `ffmpeg.exe` into: `plugins/3DTracker/bin/ffmpeg.exe` (create the `bin` folder if it does not exist).

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

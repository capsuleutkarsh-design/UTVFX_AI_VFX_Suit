<p align="center">
  <img src="build/app_icon.ico" width="128" height="128" alt="UTVFX AI Logo">
</p>
<h1 align="center">UTVFX AI & VFX Suit</h1>

<p align="center">
  <b>A Node-Based AI and Visual Effects Processing Tool</b><br>
  Designed for seamless integration of state-of-the-art ML models into traditional VFX compositing pipelines.
</p>

---

## 🌟 Overview
UTVFX AI & VFX Suit is a high-performance desktop application built to bridge the gap between complex AI-driven computer vision models and professional visual effects workflows. Featuring a node-based architecture, the software allows artists to process image sequences through advanced AI algorithms and automatically export the results to industry-standard software like The Foundry's Nuke.

## ✨ Core Features
*   **Modular Node-Based UI:** An intuitive, visually connecting workspace to stack multiple VFX and AI tasks.
*   **AI Matting & Rotoscoping:** Fully integrated with `MatteAnyone 2` and `SAM 3` for fully automatic semantic subject isolation.
*   **Matte to Shape Conversion:** Translates raw pixel alpha masks into animated vector splines (Nuke Roto Shapes) that preserve point-counts across frames for flawless manual refinement.
*   **Advanced Keying:** `Corridor Keyer` algorithm optimized for high-end despill and despeckle operations.
*   **AI Depth Estimation:** Integration with `Depth Anything V2` to generate dense disparity maps from raw 2D plates.
*   **Nuke Script Exporting:** Generates `.nk` and `.py` scripts natively, instantly bringing AI data (like Rotoscope shapes and 3D Camera tracking) into your compositing software.

## ⚙️ Requirements & Installation
This software relies on Python 3.10+, PySide6, and PyTorch (CUDA required for hardware acceleration).

### Setup for Developers
1. Clone the repository:
   ```bash
   git clone https://github.com/capsuleutkarsh-design/utvfx-ai-vfx-suit.git
   cd utvfx-ai-vfx-suit
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

## 📦 Building the Installer
The project is configured for automated distribution packaging via **PyInstaller** and **Inno Setup**.

1. Ensure [Inno Setup 6](https://jrsoftware.org/isinfo.php) is installed.
2. Run the build script to compile the executable and generate the setup wizard:
   ```bash
   build\build_installer.bat
   ```
3. The final installer will be available in the `build/Output/` directory. During setup, users can optionally inject the required heavy ML models via a `.zip` archive.

## 🤝 Contribution
Designed and authored by [capsuleutkarsh-design](https://github.com/capsuleutkarsh-design).

## 📄 License
This project is proprietary. All rights reserved.

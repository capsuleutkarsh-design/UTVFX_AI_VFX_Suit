# Contour VFX 2.0.0-beta

**AI roto, mattes and camera tracking for compositors.** A node-based Windows app that runs AI models on your plates and hands the results to Nuke. Everything runs on your own PC: after setup it never downloads anything and never uploads a frame.

This is the first release with a Windows installer.

## Download

| File | Size | |
|---|---|---|
| `ContourVFX_Setup_2.0.0-beta.exe` | 4 MB | the installer |
| `ContourVFX_Setup_2.0.0-beta-1.bin` | 1.7 GB | the app's data, which the installer reads |

**Download both files into the same folder**, then run the `.exe`. The installer cannot work without the `.bin` next to it.

The AI models (about 27.5 GB) are not in this release. Some model licences do not allow sharing them, so the app downloads them from their official sources (see below).

## Requirements

- Windows 10 or 11, 64-bit
- An NVIDIA graphics card with a recent driver (CUDA 12.1 or newer)
- About 40 GB of free disk space: about 6 GB for the app and 27.5 GB for the models
- Internet for the model download, or an offline model pack (see below)

## Installing

1. Run `ContourVFX_Setup_2.0.0-beta.exe`. It installs for your user only, in `%LOCALAPPDATA%\Programs\Contour VFX`, and needs no admin rights.
2. Get the models:
   - **With internet:** on the last page, leave **Download AI models** ticked. The download resumes if it is interrupted, and every file is checked.
   - **Without internet:** on the **Offline models** page, choose the `.001` file of an offline model pack. All the parts must be in the same folder.
3. Start **Contour VFX** from the Start menu.

You can get the models later instead: **Start menu > Contour VFX > Download AI models**, or **AI models > Install from offline pack** in the app.

### Offline model pack (computers without internet)

On a PC that has the models, run `build\BUILD.bat models` in the source folder. It writes about 15 ZIP parts of 2 GB each (`ContourVFX_Models_2.0.0-beta.zip.001`, `.002`, ...). Copy them along with the installer. The pack is for your own computers only: please do not upload it, because some model licences forbid that.

### From the source code instead

Clone the repository and double-click **`FIRST_SETUP.bat`**. Its menu offers: full setup, offline PC, offline model pack, check and repair. Then start the app with `run.bat`.

## What's in it

| Node | What it gives you |
|---|---|
| **Media Plate** | EXR/DPX/TIFF/PNG sequences or video, ACES and log colour spaces, optional half-size working copy for 4K |
| **SuperMatte** | Click, box or text prompts with SAM 1, SAM 2 (SAMURAI tracking) or SAM 3, refined into soft 16-bit mattes by ViTMatte, MEMatte or VideoMaMa |
| **Matte to Shape** | Mattes turned into animated Nuke roto shapes with feather: an outline for any object, or head, torso and limbs for a person |
| **Corridor Keyer** | Green and blue screen keying with CorridorKey |
| **Depth** | Depth Anything V2, relative or in metres, as float EXR |
| **Grade**, **OCIO ColorSpace** | Nuke-style grading and colour conversions in linear light |
| **3D Camera Tracker** | COLMAP 4.2 camera solve with shot presets (Handheld, Drone, Fast Action, GoPro, 360 VR, ...), ignoring moving objects given a matte |
| **Unified Output** | EXR layers, a camera for Nuke, Blender or USD, roto shapes, and a Nuke script that reads everything |

## Highlights of this release

- **Roto into Nuke works:** shapes animate on every frame and keep the matte's soft edge. Before, the exported script stopped before adding any keys, which left one still shape with hard edges.
- **Better roto shapes:** points stay on the same part of the object from frame to frame; hard corners appear only where the matte really has one; a shape that grows gets enough points to follow it.
- **AI Roto is now part of Matte to Shape**, as its **Body parts** mode. Old projects open with it switched on.
- **3D Tracker:** the Automated Tracker's controls and nine shot presets, frame step, and GPU bundle adjustment. An environment mesh is exported too.
- **Offline PCs:** model packs in 2 GB parts, installed from the installer, the app or `FIRST_SETUP.bat`.
- **Smaller download:** the setup downloads about 27.5 GB of models, down from 64 GB.
- **`FIRST_SETUP.bat`** replaces `install.bat`, with a menu, progress bars with time left, and a summary at the end.

## Known limitations

- This is a beta. Please report problems with frame numbers, image sizes and the log (`workspace\logs\`). **Never attach footage.**
- Windows and NVIDIA cards only.
- MEMatte weights have to be downloaded by hand; see `MODEL_DOWNLOADS.md`.

## Licence

Free to use, for personal or professional work, under the **Contour VFX Share-Back Licence**. One condition: if you change the app, send your changes back, as a pull request or issue here, or by email to capsuleutkarsh@gmail.com. What you make with it is yours.

Third-party code and AI models keep their own licences (`THIRD_PARTY_NOTICES.md`). Some models allow non-commercial use only (CorridorKey, GVM, VideoMaMa, Depth Anything V2 Base and Large), and those limits still apply.

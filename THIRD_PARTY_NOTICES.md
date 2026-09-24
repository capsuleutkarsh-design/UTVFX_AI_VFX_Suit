# Third-party notices

Contour VFX is free to use under the Contour VFX Share-Back Licence (see [LICENSE](LICENSE)); changes must be sent back to the author. It uses the third-party code, programs and AI models below, each under its own licence. Those rights stay with their authors.

Licences were checked in September 2026 against each project's repository, Hugging Face model card, or the licence file shipped with it. The revision each model is downloaded at is pinned in `first_setup.py`.

## What this means in practice

- **Personal and in-house use** is fine for everything listed here.
- **Commercial use, or selling or bundling the app,** is limited by these parts, whose licences still apply whatever the app's own licence says:

| Part | Licence | Limit |
|---|---|---|
| CorridorKey (keyer code and both weights) | Corridor Key Licence: CC BY-NC-SA 4.0 plus extra terms | Non-commercial. Its extra terms also forbid redistributing it inside another product without a written agreement from Corridor Digital (contact@corridordigital.com). |
| GVM (`plugins/CorridorKey/System/gvm_core`) | CC BY-NC-SA 4.0 | Non-commercial. |
| VideoMaMa (code) | CC BY-NC 4.0 | Non-commercial. |
| VideoMaMa and Stable Video Diffusion XT (weights) | Stability AI Community Licence | Commercial use needs registration with Stability AI and is limited by annual revenue. |
| Depth Anything V2 **Base** and **Large** (relative) | CC BY-NC 4.0 | Non-commercial. *Small* and all six *metric* models are Apache-2.0 and are fine. |

- **Parts that allow distribution but carry conditions:**
  - **SAM 3:** include a copy of the SAM Licence, and respect its prohibited uses and trade-control terms.
  - **FFmpeg:** it is GPL-3.0. It ships as a separate program, so the app's own code is not affected, but its licence and a link to its source must be included.
  - **PySide6 / Qt:** LGPL-3.0. It stays a separate, replaceable library, which the build already does.

## AI models

| Model | Used by | Licence | Source |
|---|---|---|---|
| Segment Anything (SAM ViT-H) | SuperMatte | Apache-2.0 | Meta, `facebookresearch/segment-anything` |
| SAM 2 / SAM 2.1 Hiera Large | SuperMatte | Apache-2.0 | Meta, `facebookresearch/sam2` |
| SAMURAI | SuperMatte | Apache-2.0 | University of Washington, `yangchris11/samurai` |
| SAM 3 | SuperMatte | SAM Licence (Meta, custom; commercial use allowed with conditions) | `facebook/sam3` |
| ViTMatte (small, Composition-1k) | SuperMatte | Apache-2.0 | `hustvl/vitmatte-small-composition-1k` |
| MEMatte | SuperMatte | MIT (code). The weights' licence is not stated by the authors. | `linyiheng123/MEMatte` |
| VideoMaMa | SuperMatte | CC BY-NC 4.0 (code); Stability AI Community Licence (weights) | `cvlab-kaist/VideoMaMa`, `SammyLim/VideoMaMa` |
| Stable Video Diffusion XT | VideoMaMa | Stability AI Community Licence | `stabilityai/stable-video-diffusion-img2vid-xt` |
| GroundingDINO (base) | SuperMatte (text prompts) | Apache-2.0 | `IDEA-Research/grounding-dino-base` |
| BiRefNet, BiRefNet-matting, BiRefNet-portrait | Corridor Keyer (auto guide matte) | MIT | `ZhengPeng7/BiRefNet*` |
| CorridorKey v1.0 and CorridorKeyBlue 1.0 | Corridor Keyer | CC BY-NC-SA 4.0 plus Corridor Key Licence terms | `nikopueringer/CorridorKey*` |
| GVM | Corridor Keyer | CC BY-NC-SA 4.0 | `aim-uofa/GVM` |
| Depth Anything V2 Small | Depth | Apache-2.0 | `depth-anything/Depth-Anything-V2-Small` |
| Depth Anything V2 Base, Large | Depth | CC BY-NC 4.0 | `depth-anything/Depth-Anything-V2-Base`, `-Large` |
| Depth Anything V2 Metric (Hypersim, Virtual KITTI; Small, Base, Large) | Depth | Apache-2.0 | `depth-anything/Depth-Anything-V2-Metric-*` |
| MediaPipe Pose | AI Roto | Apache-2.0 | Google, `google/mediapipe` |
| ALIKED | 3D Tracker | BSD-3-Clause | `Shiaoming/ALIKED`; ONNX export from the COLMAP 3.13.0 release |
| LightGlue (SIFT and ALIKED matchers) | 3D Tracker | Apache-2.0 | `cvg/LightGlue`; ONNX export from the COLMAP 3.13.0 release |
| LoMa (detector, DeDoDe-G descriptor, matcher) | 3D Tracker | MIT (code); matcher Apache-2.0 (from LightGlue). The weights' licence is not stated by the authors. | `davnords/LoMa` |
| COLMAP vocabulary tree (Flickr100K, 256K words) | 3D Tracker | BSD-3-Clause (COLMAP) | COLMAP 3.11.1 release |

## Programs shipped alongside the app

| Program | Licence | Notes |
|---|---|---|
| COLMAP 4.2.0 (with its global mapper, formerly GLOMAP) | BSD-3-Clause | The Windows CUDA build bundles NVIDIA CUDA runtime libraries and ONNX Runtime (MIT) under their own terms. |
| FFmpeg 9.0.2 "essentials" (gyan.dev build) | GPL-3.0 | Separate executable. Source: https://ffmpeg.org and https://www.gyan.dev/ffmpeg/builds/ |
| Python 3.10 (embedded) | PSF License | |

## Code included in this repository

| Code | Licence | Location |
|---|---|---|
| Segment Anything | Apache-2.0 | `plugins/third_party/segment-anything` |
| Depth Anything V2 | Apache-2.0 (code) | `plugins/Depth-Anything-V2` |
| CorridorKey | Corridor Key Licence (CC BY-NC-SA 4.0 plus terms) | `plugins/CorridorKey/System` |
| GVM, VideoMaMa inference | CC BY-NC-SA 4.0, CC BY-NC 4.0 | `plugins/CorridorKey/System/gvm_core`, `.../VideoMaMaInferenceModule` |
| Automated Tracker: camera export, lens maths, COLMAP model tools | Same author as Contour VFX | `plugins/CompositeOutput/camera_export`, `plugins/3DTracker/colmap_tools` |

## Python packages

Everything in `requirements-lock.txt` is under a permissive licence (MIT, BSD, Apache-2.0, PSF, ISC, MPL-2.0), with these exceptions:

- **PySide6, PySide6-Addons, PySide6-Essentials, shiboken6:** LGPL-3.0 (Qt for Python)
- **easydict:** LGPL-3.0
- **torch, torchvision, torchaudio (CUDA 12.1 builds):** BSD-3-Clause; they bundle NVIDIA CUDA and cuDNN libraries under NVIDIA's redistribution terms

Notable permissive packages: OpenImageIO (Apache-2.0, bundles OpenColorIO under BSD-3-Clause), OpenCV (Apache-2.0), NumPy and SciPy (BSD), transformers, diffusers, huggingface_hub, timm and kornia (Apache-2.0), onnxruntime (MIT), MediaPipe (Apache-2.0), Pillow (MIT-CMU).

The colour pipeline uses the ACES studio configuration built into OpenColorIO (`ocio://studio-config-latest`, BSD-3-Clause, Academy Software Foundation).

# Model and binary downloads

*Generated from `first_setup.py` by `scripts/make_model_list.py`; do not edit by hand.*

`first_setup.py` (or `install.bat`) downloads everything below. Each file is pinned to a fixed
Hugging Face commit or release URL and checked against its SHA-256 before it is used, and the app
never downloads models while it runs. To fetch only missing models later:
`python_base\python.exe scripts\download_models.py`. Licences: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Downloaded automatically

| Item | Goes to | Size | Source (pinned) |
|---|---|---|---|
| Depth-Anything V2 (Large) | `models/DepthAnythingV2/depth_anything_v2_vitl.pth` | 1.34 GB | [depth_anything_v2_vitl.pth](https://huggingface.co/depth-anything/Depth-Anything-V2-Large/resolve/cbbb86a30ce19b5684b7a05155dc7e6cbc7685b9/depth_anything_v2_vitl.pth) |
| Depth-Anything V2 (Base) | `models/DepthAnythingV2/depth_anything_v2_vitb.pth` | 390 MB | [depth_anything_v2_vitb.pth](https://huggingface.co/depth-anything/Depth-Anything-V2-Base/resolve/a4e71a6c2ce52fe50df0f212066b0d4a87be9b5e/depth_anything_v2_vitb.pth) |
| Depth-Anything V2 (Small) | `models/DepthAnythingV2/depth_anything_v2_vits.pth` | 99 MB | [depth_anything_v2_vits.pth](https://huggingface.co/depth-anything/Depth-Anything-V2-Small/resolve/03876f8651c73a60fe4c2c48294e09fcb6838fcf/depth_anything_v2_vits.pth) |
| Depth-Anything V2 Metric indoor (Small) | `models/DepthAnythingV2/depth_anything_v2_metric_hypersim_vits.pth` | 99 MB | [depth_anything_v2_metric_hypersim_vits.pth](https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-Hypersim-Small/resolve/3bc65d4e14a6786a61acec16453c50e12bf5f338/depth_anything_v2_metric_hypersim_vits.pth) |
| Depth-Anything V2 Metric indoor (Base) | `models/DepthAnythingV2/depth_anything_v2_metric_hypersim_vitb.pth` | 390 MB | [depth_anything_v2_metric_hypersim_vitb.pth](https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-Hypersim-Base/resolve/4ebcd7fd0858cbb953451619ca943ea39ec08e00/depth_anything_v2_metric_hypersim_vitb.pth) |
| Depth-Anything V2 Metric indoor (Large) | `models/DepthAnythingV2/depth_anything_v2_metric_hypersim_vitl.pth` | 1.34 GB | [depth_anything_v2_metric_hypersim_vitl.pth](https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-Hypersim-Large/resolve/79720800638389a78b2defc92caa885104f69974/depth_anything_v2_metric_hypersim_vitl.pth) |
| Depth-Anything V2 Metric outdoor (Small) | `models/DepthAnythingV2/depth_anything_v2_metric_vkitti_vits.pth` | 99 MB | [depth_anything_v2_metric_vkitti_vits.pth](https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-VKITTI-Small/resolve/c725b8589bdf6ab04072cab74c0467830db80d6d/depth_anything_v2_metric_vkitti_vits.pth) |
| Depth-Anything V2 Metric outdoor (Base) | `models/DepthAnythingV2/depth_anything_v2_metric_vkitti_vitb.pth` | 390 MB | [depth_anything_v2_metric_vkitti_vitb.pth](https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-VKITTI-Base/resolve/e96fd0c8cedf1825a55b9c61309f754982948df0/depth_anything_v2_metric_vkitti_vitb.pth) |
| Depth-Anything V2 Metric outdoor (Large) | `models/DepthAnythingV2/depth_anything_v2_metric_vkitti_vitl.pth` | 1.34 GB | [depth_anything_v2_metric_vkitti_vitl.pth](https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-VKITTI-Large/resolve/070e97e4b80e317ec1d03c19927304f4091a180b/depth_anything_v2_metric_vkitti_vitl.pth) |
| SAM ViT-H (Meta) | `models/SAM/sam_vit_h_4b8939.pth` | 2.56 GB | [sam_vit_h_4b8939.pth](https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth) |
| SAM 2.1 Hiera Large (SAMURAI) | `models/SAM2/sam2.1_hiera_large.pt` | 898 MB | [sam2.1_hiera_large.pt](https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt) |
| SAM 2 Hiera Large (HF) | `models/SAM2` | folder | [facebook/sam2-hiera-large](https://huggingface.co/facebook/sam2-hiera-large/tree/e6a8e8809b8f1bfa2238b6d080f3d05cc76bd251) @ `e6a8e8809b` |
| ViTMatte Weights (HF) | `models/ViTMatte` | folder | [hustvl/vitmatte-small-composition-1k](https://huggingface.co/hustvl/vitmatte-small-composition-1k/tree/6a58ad7646403c1df626fbd746900aec7361ea1d) @ `6a58ad7646` |
| COLMAP vocabulary tree (loop detection) | `models/COLMAP/vocab_tree_faiss_flickr100K_words256K.bin` | 72 MB | [vocab_tree_faiss_flickr100K_words256K.bin](https://github.com/colmap/colmap/releases/download/3.11.1/vocab_tree_faiss_flickr100K_words256K.bin) |
| ALIKED features (3D Tracker) | `models/COLMAP/aliked-n16rot.onnx` | 3 MB | [aliked-n16rot.onnx](https://github.com/colmap/colmap/releases/download/3.13.0/aliked-n16rot.onnx) |
| ALIKED LightGlue matcher (3D Tracker) | `models/COLMAP/aliked-lightglue.onnx` | 46 MB | [aliked-lightglue.onnx](https://github.com/colmap/colmap/releases/download/3.13.0/aliked-lightglue.onnx) |
| SIFT LightGlue matcher (3D Tracker) | `models/COLMAP/sift-lightglue.onnx` | 46 MB | [sift-lightglue.onnx](https://github.com/colmap/colmap/releases/download/3.13.0/sift-lightglue.onnx) |
| LoMa detector (3D Tracker) | `models/COLMAP/loma_detector.onnx` | 26 MB | [loma_detector.onnx](https://github.com/davnords/storage/releases/download/loma/loma_detector.onnx) |
| LoMa descriptor (3D Tracker) | `models/COLMAP/loma_descriptor_dedode_g.onnx` | 1.29 GB | [loma_descriptor_dedode_g.onnx](https://github.com/davnords/storage/releases/download/loma/loma_descriptor_dedode_g.onnx) |
| LoMa matcher (3D Tracker) | `models/COLMAP/loma_matcher_B.onnx` | 48 MB | [loma_matcher_B.onnx](https://github.com/davnords/storage/releases/download/loma/loma_matcher_B.onnx) |
| CorridorKey | `models/CorridorKey/CorridorKey_v1.0.safetensors` | 399 MB | [CorridorKey_v1.0.safetensors](https://huggingface.co/nikopueringer/CorridorKey_v1.0/resolve/f6386ddf042d8e92aeb5fd16cb9b101cff508195/CorridorKey_v1.0.safetensors) |
| CorridorKey (Blue) | `models/CorridorKey/CorridorKeyBlue_1.0.safetensors` | 399 MB | [CorridorKeyBlue_1.0.safetensors](https://huggingface.co/nikopueringer/CorridorKeyBlue_1.0/resolve/51e6ccaa4b703f54be20a72ac2c37784fb9ba1cd/CorridorKeyBlue_1.0.safetensors) |
| BiRefNet | `models/BiRefNet/BiRefNet` | folder | [ZhengPeng7/BiRefNet](https://huggingface.co/ZhengPeng7/BiRefNet/tree/e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4) @ `e2bf8e4460` |
| BiRefNet (Matting) | `models/BiRefNet/BiRefNet-matting` | folder | [ZhengPeng7/BiRefNet-matting](https://huggingface.co/ZhengPeng7/BiRefNet-matting/tree/eccde0a8cbdce7ac5fecfeb06340fe7b949e85d9) @ `eccde0a8cb` |
| BiRefNet (Portrait) | `models/BiRefNet/BiRefNet-portrait` | folder | [ZhengPeng7/BiRefNet-portrait](https://huggingface.co/ZhengPeng7/BiRefNet-portrait/tree/b6561965a70070d9143fd9e558f6ca3c481510db) @ `b6561965a7` |
| FFmpeg (Windows) | `plugins/3DTracker/bin/ffmpeg.exe` | 115 MB | [ffmpeg-9.0.2-essentials_build.zip](https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip) |
| COLMAP 4.2.0 (CUDA) | `plugins/3DTracker/bin/colmap-x64-windows-cuda` | 381 MB | [colmap-x64-windows-cuda.zip](https://github.com/colmap/colmap/releases/download/4.2.0/colmap-x64-windows-cuda.zip) |
| SAM 3 Weights (gated: accept the licence on Hugging Face and log in first) | `models/SAM3` | folder | [facebook/sam3](https://huggingface.co/facebook/sam3/tree/3c879f39826c281e95690f02c7821c4de09afae7) @ `3c879f3982` |
| GroundingDINO Weights | `models/GroundingDINO` | folder | [IDEA-Research/grounding-dino-base](https://huggingface.co/IDEA-Research/grounding-dino-base/tree/12bdfa3120f3e7ec7b434d90674b3396eccf88eb) @ `12bdfa3120` |
| VideoMaMa Base (SVD-XT) | `models/VideoMaMa/stable-video-diffusion-img2vid-xt` | folder | [stabilityai/stable-video-diffusion-img2vid-xt](https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt/tree/9e43909513c6714f1bc78bcb44d96e733cd242aa) @ `9e43909513` |
| VideoMaMa Fine-Tuned UNet | `models/VideoMaMa` | folder | [SammyLim/VideoMaMa](https://huggingface.co/SammyLim/VideoMaMa/tree/e289a7acc8403c4fbe4dea2a1de5a9749ebc9bf5) @ `e289a7acc8` |

## Downloaded by hand

**MEMatte ViT-B (DIM)** (441 MB): save as `models/MEMatte/MEMatte_ViTB_DIM.pth`.
SHA-256 of the tested copy: `4e3b7b8b9e284e20ec1f505841a09bb6c2ff75b366a08745a24d5792bc1d0b54`.

The MEMatte authors publish their weights on Google Drive, which cannot be downloaded without a browser:

- https://drive.google.com/file/d/1R5NbgIpOudKjvLz1V9M9SxXr1ovAmu3u/view
- https://drive.google.com/file/d/1NOV64zMSFtoKPASqvEvxQKI_PRY9m5IA/view
- https://drive.google.com/file/d/122p3sdhJVb7vg4IXELeC9C3HEG9Mlh5z/view

Put the ViT-B (DIM) file at the path above; `first_setup.py --verify` checks it against the hash.

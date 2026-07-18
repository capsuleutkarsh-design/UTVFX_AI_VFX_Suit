# UTVFX AI & VFX Suit - Model Weights Download Links

To use the AI tools, the application requires several deep learning models. Since they are very large (several gigabytes), they are not included in the main code repository. 

Download the models from the official links below and place them in the correct directories as shown.

## 1. Depth Anything V2
Used for Monocular Depth Estimation.
- **Large Model (Recommended):** [depth_anything_v2_vitl.pth](https://huggingface.co/depth-anything/Depth-Anything-V2-Large/resolve/main/depth_anything_v2_vitl.pth)
- **Base Model:** [depth_anything_v2_vitb.pth](https://huggingface.co/depth-anything/Depth-Anything-V2-Base/resolve/main/depth_anything_v2_vitb.pth)
- **Small Model (Fastest):** [depth_anything_v2_vits.pth](https://huggingface.co/depth-anything/Depth-Anything-V2-Small/resolve/main/depth_anything_v2_vits.pth)
**Directory:** `plugins/Depth-Anything-V2/checkpoints/`

## 2. Segment Anything (SAM)
Used for the Matte and Rotoscoping tools.
- **SAM ViT-H:** [sam_vit_h_4b8939.pth](https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth)
**Directory:** `plugins/MatAnyone2/pretrained_models/`

## 3. MatAnyone & MatAnyone 2
Used for temporal video matting and rotoscope propagation.
- **MatAnyone Weights:** [matanyone.pth](https://huggingface.co/pq-lv/MatAnyone/resolve/main/matanyone.pth)
- **MatAnyone2 Weights:** [matanyone2.pth](https://huggingface.co/pq-lv/MatAnyone/resolve/main/matanyone2.pth)
**Directory:** `plugins/MatAnyone2/pretrained_models/`

## 4. CorridorKey (Green/Blue Screen Keyer)
Used for the AI keying node.
- **Green Screen Model:** [CorridorKey_v1.0.safetensors](https://huggingface.co/nikopueringer/CorridorKey_v1.0/resolve/main/CorridorKey_v1.0.safetensors)
- **Blue Screen Model:** [CorridorKeyBlue_1.0.safetensors](https://huggingface.co/nikopueringer/CorridorKey_v1.0/resolve/main/CorridorKeyBlue_1.0.safetensors)
**Directory:** `plugins/CorridorKey/System/CorridorKeyModule/checkpoints/`

## 5. BiRefNet (Dichotomous Image Segmentation)
Used as a high-quality background removal backend for CorridorKey and Rotoscoping.
- **General Model:** [model.safetensors](https://huggingface.co/ZhengPeng7/BiRefNet/resolve/main/model.safetensors)
  - Place in: `plugins/CorridorKey/System/BiRefNetModule/checkpoints/BiRefNet/`
- **Portrait Model:** [model.safetensors (portrait)](https://huggingface.co/ZhengPeng7/BiRefNet-portrait/resolve/main/model.safetensors)
  - Place in: `plugins/CorridorKey/System/BiRefNetModule/checkpoints/BiRefNet-portrait/`
- **Matting Model:** [model.safetensors (matting)](https://huggingface.co/ZhengPeng7/BiRefNet-matting/resolve/main/model.safetensors)
  - Place in: `plugins/CorridorKey/System/BiRefNetModule/checkpoints/BiRefNet-matting/`

## 6. MEMatte
Used for memory-efficient temporal video matting.
Download the `.pth` weights from the links below:
- [MEMatte Weight File 1](https://drive.google.com/file/d/1R5NbgIpOudKjvLz1V9M9SxXr1ovAmu3u/view)
- [MEMatte Weight File 2](https://drive.google.com/file/d/1NOV64zMSFtoKPASqvEvxQKI_PRY9m5IA/view)
- [MEMatte Weight File 3](https://drive.google.com/file/d/122p3sdhJVb7vg4IXELeC9C3HEG9Mlh5z/view)

**Directory:** `models/MEMatte/`

## 7. VideoMaMa
Used for temporal masking refinement in Super Matte.
- **Base Model (SVD-XT):** Clone or download the folder structure from [stabilityai/stable-video-diffusion-img2vid-xt](https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt/tree/main).
  - Place all contents in: `models/VideoMaMa/stable-video-diffusion-img2vid-xt/`
- **VideoMaMa Fine-tuned UNet:** Download `diffusion_pytorch_model.safetensors` and `config.json` from [SammyLim/VideoMaMa](https://huggingface.co/SammyLim/VideoMaMa/tree/main).
  - Place these files directly in: `models/VideoMaMa/`

---
*Note: If you run the pre-built Windows Installer setup, you can simply put all these models into a single `.zip` file and select it during installation to automatically extract them to the right places.*

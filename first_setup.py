"""Contour VFX installer: the one supported way to set up a checkout.

    install.bat                       (finds Python 3.10/3.11 and runs this file)
    python first_setup.py             (same, if you already have Python 3.10 or 3.11)

Steps: git submodules -> portable Python 3.10 in python_base/ -> packages from
requirements-lock.txt -> model weights and binaries (COLMAP, FFmpeg).

Options:
    --check         only report what is installed; change nothing
    --verify        also hash every file already present and re-check HF snapshots
    --skip-deps     do not install Python packages
    --skip-models   do not download models or binaries

Every download is pinned: a fixed URL or Hugging Face revision, and a SHA-256 and
size where the file is a single file. Files download to "<name>.part" and are only
renamed once complete and verified (utvfx/core/downloads.py).

This file only uses the standard library: it runs on the Python that starts the
install, before anything is installed. main.py and the model downloader import
MODELS from here, so keep the "name", "type", "path" / "local_dir" / "final_name"
keys stable.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utvfx.core import downloads  # noqa: E402  (standard library only)

SUPPORTED_PYTHONS = ((3, 10), (3, 11))

# Portable CPython 3.10.11 (embeddable) and the pip wheel used to bootstrap it.
PYTHON_EMBED = {
    "url": "https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip",
    "sha256": "608619f8619075629c9c69f361352a0da6ed7e62f83a0e19c63e0ea32eb7629d",
    "size": 8629277,
}
PIP_WHEEL = {
    "url": "https://files.pythonhosted.org/packages/f3/6e/1736e5b4ae2b778ef2f81c47d797de9f891d4d8acb047a24ca37a60294dd/pip-26.2.1-py3-none-any.whl",
    "sha256": "71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e",
    "size": 1816632,
    "name": "pip-26.2.1-py3-none-any.whl",
}
LOCK_FILE = "requirements-lock.txt"
DOWNLOAD_TMP = os.path.join(ROOT, ".downloads")

# Pinned Hugging Face revisions (commit sha). Change them only after reviewing the diff,
# above all for BiRefNet: its repo ships Python code that runs with trust_remote_code.
REV = {
    "depth_l": "cbbb86a30ce19b5684b7a05155dc7e6cbc7685b9",
    "depth_b": "a4e71a6c2ce52fe50df0f212066b0d4a87be9b5e",
    "depth_s": "03876f8651c73a60fe4c2c48294e09fcb6838fcf",
    "depth_metric_hypersim_s": "3bc65d4e14a6786a61acec16453c50e12bf5f338",
    "depth_metric_hypersim_b": "4ebcd7fd0858cbb953451619ca943ea39ec08e00",
    "depth_metric_hypersim_l": "79720800638389a78b2defc92caa885104f69974",
    "depth_metric_vkitti_s": "c725b8589bdf6ab04072cab74c0467830db80d6d",
    "depth_metric_vkitti_b": "e96fd0c8cedf1825a55b9c61309f754982948df0",
    "depth_metric_vkitti_l": "070e97e4b80e317ec1d03c19927304f4091a180b",
    "sam_hf": "87aecf0df4ce6b30cd7de76e87673c49644bdf67",
    "sam2_hf": "e6a8e8809b8f1bfa2238b6d080f3d05cc76bd251",
    "vitmatte": "6a58ad7646403c1df626fbd746900aec7361ea1d",
    "corridorkey": "f6386ddf042d8e92aeb5fd16cb9b101cff508195",
    "corridorkey_blue": "51e6ccaa4b703f54be20a72ac2c37784fb9ba1cd",
    "birefnet": "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4",
    "birefnet_matting": "eccde0a8cbdce7ac5fecfeb06340fe7b949e85d9",
    "birefnet_portrait": "b6561965a70070d9143fd9e558f6ca3c481510db",
    "sam3": "3c879f39826c281e95690f02c7821c4de09afae7",
    "groundingdino": "12bdfa3120f3e7ec7b434d90674b3396eccf88eb",
    "svd_xt": "9e43909513c6714f1bc78bcb44d96e733cd242aa",
    "videomama": "e289a7acc8403c4fbe4dea2a1de5a9749ebc9bf5",
}

# TensorFlow/Flax copies of the same weights: never loaded, several GB each.
NON_TORCH = ["*.h5", "*.msgpack", "flax_model*", "tf_model*", "rust_model*"]


def _hf(repo, rev, filename):
    return f"https://huggingface.co/{repo}/resolve/{rev}/{filename}"


MODELS = [
    # DepthAnythingV2
    {"name": "Depth-Anything V2 (Large)", "type": "file",
     "url": _hf("depth-anything/Depth-Anything-V2-Large", REV["depth_l"], "depth_anything_v2_vitl.pth"),
     "path": "models/DepthAnythingV2/depth_anything_v2_vitl.pth",
     "sha256": "a7ea19fa0ed99244e67b624c72b8580b7e9553043245905be58796a608eb9345", "size": 1341395338},
    {"name": "Depth-Anything V2 (Base)", "type": "file",
     "url": _hf("depth-anything/Depth-Anything-V2-Base", REV["depth_b"], "depth_anything_v2_vitb.pth"),
     "path": "models/DepthAnythingV2/depth_anything_v2_vitb.pth",
     "sha256": "0d2b7002e62d39d655571c371333340bd88f67ab95050c03591555aa05645328", "size": 389961218},
    {"name": "Depth-Anything V2 (Small)", "type": "file",
     "url": _hf("depth-anything/Depth-Anything-V2-Small", REV["depth_s"], "depth_anything_v2_vits.pth"),
     "path": "models/DepthAnythingV2/depth_anything_v2_vits.pth",
     "sha256": "715fade13be8f229f8a70cc02066f656f2423a59effd0579197bbf57860e1378", "size": 99218434},
    # Metric Depth-Anything V2 (depth in metres): Hypersim for indoor, Virtual KITTI for outdoor.
    {"name": "Depth-Anything V2 Metric indoor (Small)", "type": "file",
     "url": _hf("depth-anything/Depth-Anything-V2-Metric-Hypersim-Small", REV["depth_metric_hypersim_s"], "depth_anything_v2_metric_hypersim_vits.pth"),
     "path": "models/DepthAnythingV2/depth_anything_v2_metric_hypersim_vits.pth",
     "sha256": "b782898d8a3e8be1f639de33837ed85e9b4b73e40f8f5e5cd99067588d722545", "size": 99222290},
    {"name": "Depth-Anything V2 Metric indoor (Base)", "type": "file",
     "url": _hf("depth-anything/Depth-Anything-V2-Metric-Hypersim-Base", REV["depth_metric_hypersim_b"], "depth_anything_v2_metric_hypersim_vitb.pth"),
     "path": "models/DepthAnythingV2/depth_anything_v2_metric_hypersim_vitb.pth",
     "sha256": "9dc9e274c5eff55c6daf27b660c0ced0eca4e8593a6da90cdcb04d2b4d3f3fa2", "size": 389965138},
    {"name": "Depth-Anything V2 Metric indoor (Large)", "type": "file",
     "url": _hf("depth-anything/Depth-Anything-V2-Metric-Hypersim-Large", REV["depth_metric_hypersim_l"], "depth_anything_v2_metric_hypersim_vitl.pth"),
     "path": "models/DepthAnythingV2/depth_anything_v2_metric_hypersim_vitl.pth",
     "sha256": "6f82ff2bc543ac02ddff4aa31fa363676a8305dd3ccf04e80e2af115a044cb6d", "size": 1341401882},
    {"name": "Depth-Anything V2 Metric outdoor (Small)", "type": "file",
     "url": _hf("depth-anything/Depth-Anything-V2-Metric-VKITTI-Small", REV["depth_metric_vkitti_s"], "depth_anything_v2_metric_vkitti_vits.pth"),
     "path": "models/DepthAnythingV2/depth_anything_v2_metric_vkitti_vits.pth",
     "sha256": "9203e538d35255c90dda4b7fedb47ff33fe725497bcca3b1e53b3a65ee63f0cb", "size": 99221808},
    {"name": "Depth-Anything V2 Metric outdoor (Base)", "type": "file",
     "url": _hf("depth-anything/Depth-Anything-V2-Metric-VKITTI-Base", REV["depth_metric_vkitti_b"], "depth_anything_v2_metric_vkitti_vitb.pth"),
     "path": "models/DepthAnythingV2/depth_anything_v2_metric_vkitti_vitb.pth",
     "sha256": "4dad67a7cc10b462bca48e6b8569c762b8eb3c1adada170a3851a6d3ba37bb3e", "size": 389964656},
    {"name": "Depth-Anything V2 Metric outdoor (Large)", "type": "file",
     "url": _hf("depth-anything/Depth-Anything-V2-Metric-VKITTI-Large", REV["depth_metric_vkitti_l"], "depth_anything_v2_metric_vkitti_vitl.pth"),
     "path": "models/DepthAnythingV2/depth_anything_v2_metric_vkitti_vitl.pth",
     "sha256": "239b1054a369e66da2576e9a118d6d7c12d90dc8ebe609579a9a09cd8e05fe38", "size": 1341401064},

    # SAM 1 (Meta checkpoint & HF repo)
    {"name": "SAM ViT-H (Meta)", "type": "file",
     "url": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth",
     "path": "models/SAM/sam_vit_h_4b8939.pth",
     "sha256": "a7bf3b02f3ebf1267aba913ff637d9a2d5c33d3173bb679e46d9f338c26f262e", "size": 2564550879},
    {"name": "SAM ViT-H (HF)", "type": "hf_repo", "repo_id": "facebook/sam-vit-huge", "revision": REV["sam_hf"],
     "local_dir": "models/SAM", "check_dir": "models/SAM/model.safetensors",
     "ignore_patterns": NON_TORCH + ["pytorch_model.bin"]},

    # SAM 2 (Meta checkpoints & HF repo)
    {"name": "SAM 2 Hiera Large (Meta)", "type": "file",
     "url": "https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_large.pt",
     "path": "models/SAM2/sam2_hiera_large.pt",
     "sha256": "7442e4e9b732a508f80e141e7c2913437a3610ee0c77381a66658c3a445df87b", "size": 897952466},
    {"name": "SAM 2.1 Hiera Large (SAMURAI)", "type": "file",
     "url": "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt",
     "path": "models/SAM2/sam2.1_hiera_large.pt",
     "sha256": "2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318", "size": 898083611},
    # Was raw.githubusercontent.com/.../main/sam2/configs/sam2_hiera_l.yaml, which is now a 404.
    {"name": "SAM 2 Config", "type": "file",
     "url": _hf("facebook/sam2-hiera-large", REV["sam2_hf"], "sam2_hiera_l.yaml"),
     "path": "models/SAM2/sam2_hiera_l.yaml",
     "sha256": "904187da9c3b648d08229aa8ea13ef85e87b43ceff37695f6c0a46495a35b6cb", "size": 3695},
    {"name": "SAM 2 Hiera Large (HF)", "type": "hf_repo", "repo_id": "facebook/sam2-hiera-large",
     "revision": REV["sam2_hf"], "local_dir": "models/SAM2", "check_dir": "models/SAM2/model.safetensors",
     "ignore_patterns": NON_TORCH},

    # ViTMatte (ONNX artifacts like vitmatte_base.onnx are generated locally by export scripts)
    {"name": "ViTMatte Weights (HF)", "type": "hf_repo", "repo_id": "hustvl/vitmatte-small-composition-1k",
     "revision": REV["vitmatte"], "local_dir": "models/ViTMatte", "ignore_patterns": NON_TORCH},

    # 3D Tracker: COLMAP's loop-detection vocabulary and its learned feature/matcher models.
    # COLMAP would fetch these itself at run time; the tracker passes these local copies instead.
    {"name": "COLMAP vocabulary tree (loop detection)", "type": "file",
     "url": "https://github.com/colmap/colmap/releases/download/3.11.1/vocab_tree_faiss_flickr100K_words256K.bin",
     "path": "models/COLMAP/vocab_tree_faiss_flickr100K_words256K.bin",
     "sha256": "96ca8ec8ea60b1f73465aaf2c401fd3b3ca75cdba2d3c50d6a2f6f760f275ddc", "size": 72412636},
    {"name": "ALIKED features (3D Tracker)", "type": "file",
     "url": "https://github.com/colmap/colmap/releases/download/3.13.0/aliked-n16rot.onnx",
     "path": "models/COLMAP/aliked-n16rot.onnx",
     "sha256": "39c423d0a6f03d39ec89d3d1d61853765c2fb6a8b8381376c703e5758778a547", "size": 2997054},
    {"name": "ALIKED LightGlue matcher (3D Tracker)", "type": "file",
     "url": "https://github.com/colmap/colmap/releases/download/3.13.0/aliked-lightglue.onnx",
     "path": "models/COLMAP/aliked-lightglue.onnx",
     "sha256": "b9a5de7204648b18a8cf5dcac819f9d30de1a5961ef03756803c8b86c2dceb8d", "size": 45804950},
    {"name": "SIFT LightGlue matcher (3D Tracker)", "type": "file",
     "url": "https://github.com/colmap/colmap/releases/download/3.13.0/sift-lightglue.onnx",
     "path": "models/COLMAP/sift-lightglue.onnx",
     "sha256": "e0500228472b43f92b3d36881a09b3310d3b058b56187b246cc7b9ab6429096e", "size": 45806253},
    {"name": "LoMa detector (3D Tracker)", "type": "file",
     "url": "https://github.com/davnords/storage/releases/download/loma/loma_detector.onnx",
     "path": "models/COLMAP/loma_detector.onnx",
     "sha256": "b6af99c5e730034ac9b675d1ebe05d0679af4569a3c26f10a6a50f91e02dc512", "size": 26187830},
    {"name": "LoMa descriptor (3D Tracker)", "type": "file",
     "url": "https://github.com/davnords/storage/releases/download/loma/loma_descriptor_dedode_g.onnx",
     "path": "models/COLMAP/loma_descriptor_dedode_g.onnx",
     "sha256": "5a7b9eaf7425d4513c5d7feae86080bae7ed3aceae7fb1b9f059d0752e2ad564", "size": 1294905349},
    {"name": "LoMa matcher (3D Tracker)", "type": "file",
     "url": "https://github.com/davnords/storage/releases/download/loma/loma_matcher_B.onnx",
     "path": "models/COLMAP/loma_matcher_B.onnx",
     "sha256": "ba5a2773b29cace19f1240e14e5a080cca3eaf9f69a7adb829a1d470557001c7", "size": 48361254},

    # CorridorKey
    {"name": "CorridorKey", "type": "file",
     "url": _hf("nikopueringer/CorridorKey_v1.0", REV["corridorkey"], "CorridorKey_v1.0.safetensors"),
     "path": "models/CorridorKey/CorridorKey_v1.0.safetensors",
     "sha256": "74d614f7d92fc559a118c30a7deadedc3cacd8ef83dcb85a030d0bed7af8b20b", "size": 398849256},
    # Blue-screen weights: used when Screen Color is "blue" (or "auto" finds a blue screen).
    # Without them the engine would fetch the latest upload at run time, unpinned.
    {"name": "CorridorKey (Blue)", "type": "file",
     "url": _hf("nikopueringer/CorridorKeyBlue_1.0", REV["corridorkey_blue"], "CorridorKeyBlue_1.0.safetensors"),
     "path": "models/CorridorKey/CorridorKeyBlue_1.0.safetensors",
     "sha256": "43bc5f6a08a9e5effe5d633d0d84bb0aff91037b35ab85d16cd812b38c5cac23", "size": 398849256},

    # BiRefNet. Its repos ship model code (birefnet.py) that transformers runs with
    # trust_remote_code, so the revision is pinned and the app never downloads it again
    # at run time (plugins/CorridorKey/backend.py). "code_sha256" holds the hashes (LF line
    # endings) of the reviewed Python files; the app refuses to run any other version.
    # When bumping a revision, review the new birefnet.py and update both.
    {"name": "BiRefNet", "type": "hf_repo", "repo_id": "ZhengPeng7/BiRefNet", "revision": REV["birefnet"],
     "local_dir": "models/BiRefNet/BiRefNet",
     "code_sha256": {"birefnet.py": "208771ae626f653d64128fbf2d6ac9f8e645c5cc5e286258a73ec3322bbfe5ef",
                     "BiRefNet_config.py": "e7b8c2a74f6cea6a59553d517f71d47f2c1d90e670a13416af17c25fe2f3dc52"}},
    {"name": "BiRefNet (Matting)", "type": "hf_repo", "repo_id": "ZhengPeng7/BiRefNet-matting",
     "revision": REV["birefnet_matting"], "local_dir": "models/BiRefNet/BiRefNet-matting",
     "code_sha256": {"birefnet.py": "2a45b4e0ece72d7c4212bca1a988e7d7e52bfe9f98ec59c58b8809c8a8b7a831",
                     "BiRefNet_config.py": "e7b8c2a74f6cea6a59553d517f71d47f2c1d90e670a13416af17c25fe2f3dc52"}},
    {"name": "BiRefNet (Portrait)", "type": "hf_repo", "repo_id": "ZhengPeng7/BiRefNet-portrait",
     "revision": REV["birefnet_portrait"], "local_dir": "models/BiRefNet/BiRefNet-portrait",
     "code_sha256": {"birefnet.py": "2a45b4e0ece72d7c4212bca1a988e7d7e52bfe9f98ec59c58b8809c8a8b7a831",
                     "BiRefNet_config.py": "e7b8c2a74f6cea6a59553d517f71d47f2c1d90e670a13416af17c25fe2f3dc52"}},

    # Binaries. FFmpeg: the versioned gyan.dev build (same file and hash as the
    # GyanD/codexffmpeg GitHub release 9.0.2), not the moving "release-essentials" link.
    {"name": "FFmpeg (Windows)", "type": "zip_extract",
     "url": "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip",
     "sha256": "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba", "size": 114768076,
     "extract_target": "bin/ffmpeg.exe", "final_name": "plugins/3DTracker/bin/ffmpeg.exe"},
    # COLMAP 4.2.0 (CUDA). GLOMAP is built into COLMAP 4.x as its global mapper, so there
    # is no separate GLOMAP download. The archive has bin/ and plugins/ at the top level
    # (no wrapping folder); unit-test executables and debug symbols are not extracted.
    {"name": "COLMAP 4.2.0 (CUDA)", "type": "zip_extract",
     "url": "https://github.com/colmap/colmap/releases/download/4.2.0/colmap-x64-windows-cuda.zip",
     "sha256": "991e0bae403a496fcc4de0c1f1f428619bf12f8000978f77bc6799d9bfeac23e", "size": 380970811,
     "extract_all": True, "dest_dir": "plugins/3DTracker/bin/colmap-x64-windows-cuda",
     "exclude": ["*_test.exe", "*.pdb", "RUN_TESTS.bat"],
     "final_name": "plugins/3DTracker/bin/colmap-x64-windows-cuda/bin/colmap.exe"},

    # Additional Hugging Face repos (SAM 3, GroundingDINO)
    {"name": "SAM 3 Weights", "type": "hf_repo", "repo_id": "facebook/sam3", "revision": REV["sam3"],
     "local_dir": "models/SAM3", "check_dir": "models/SAM3/model.safetensors",
     "ignore_patterns": ["sam3.pt"], "gated": True},
    {"name": "GroundingDINO Weights", "type": "hf_repo", "repo_id": "IDEA-Research/grounding-dino-base",
     "revision": REV["groundingdino"], "local_dir": "models/GroundingDINO",
     "ignore_patterns": NON_TORCH + ["pytorch_model.bin"]},

    # VideoMaMa temporal refiner
    {"name": "VideoMaMa Base (SVD-XT)", "type": "hf_repo", "repo_id": "stabilityai/stable-video-diffusion-img2vid-xt",
     "revision": REV["svd_xt"], "local_dir": "models/VideoMaMa/stable-video-diffusion-img2vid-xt"},
    {"name": "VideoMaMa Fine-Tuned UNet", "type": "hf_repo", "repo_id": "SammyLim/VideoMaMa",
     "revision": REV["videomama"], "local_dir": "models/VideoMaMa", "check_dir": "models/VideoMaMa/unet"},
]

# Files that have to be downloaded by hand (Google Drive links in MODEL_DOWNLOADS.md).
# Hashes are of the copies this project was tested with.
MANUAL_FILES = [
    {"name": "MEMatte ViT-B (DIM)", "path": "models/MEMatte/MEMatte_ViTB_DIM.pth",
     "sha256": "4e3b7b8b9e284e20ec1f505841a09bb6c2ff75b366a08745a24d5792bc1d0b54", "size": 440546757},
]


# ------------------------------------------------------------------ helpers

def print_header(title):
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)


def _abs(rel):
    return os.path.join(ROOT, *rel.replace("\\", "/").split("/"))


def format_size(n):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024.0:
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PB"


def _progress_printer(label):
    state = {"last": -1}

    def show(done, total):
        if total > 0:
            pct = int(50 * done / total)
            if pct != state["last"]:
                state["last"] = pct
                sys.stdout.write(f"\r[{'=' * pct}{' ' * (50 - pct)}] {format_size(done)} / {format_size(total)}")
                sys.stdout.flush()
    return show


def fetch(url, dest, sha256=None, size=None):
    """Download through a .part file; True on success."""
    print(f"[DOWNLOAD] {os.path.basename(dest)}  ({url})")
    try:
        downloads.download_file(url, dest, sha256=sha256, size=size,
                                progress=_progress_printer(os.path.basename(dest)))
        print(f"\n[OK] Saved to {os.path.relpath(dest, ROOT)}")
        return True
    except downloads.DownloadError as e:
        print(f"\n[ERROR] {e}")
        return False


def python_version_of(exe):
    try:
        out = subprocess.check_output(
            [exe, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], text=True, timeout=60)
        return tuple(int(x) for x in out.strip().split("."))
    except Exception:
        return None


def check_host_python():
    if sys.version_info[:2] not in SUPPORTED_PYTHONS:
        v = ".".join(map(str, sys.version_info[:3]))
        print(f"[ERROR] Python {v} is not supported. Use Python 3.10 or 3.11.")
        print("        torch 2.5.1+cu121 and mediapipe<0.10.10 have no wheels for 3.12 or newer.")
        sys.exit(1)


# ------------------------------------------------------------------ steps

def setup_git_submodules():
    print_header("Step 0: Git submodules (plugins and extras)")
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        print("[SKIP] Not a git checkout.")
        return
    try:
        subprocess.check_call(["git", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Only the pinned commit of each submodule is needed, so fetch just that (much faster).
        try:
            subprocess.check_call(["git", "submodule", "update", "--init", "--recursive", "--depth", "1"], cwd=ROOT)
        except subprocess.CalledProcessError:
            subprocess.check_call(["git", "submodule", "update", "--init", "--recursive"], cwd=ROOT)
        print("[OK] Git submodules initialized.")
    except Exception as e:
        print(f"[WARNING] Could not update git submodules: {e}")
        print("If plugin files are missing, run: git submodule update --init --recursive")


def find_python_base():
    base_dir = os.path.join(ROOT, "python_base")
    for exe in (os.path.join(base_dir, "python.exe"), os.path.join(base_dir, "Scripts", "python.exe")):
        if os.path.exists(exe):
            return exe
    return None


def setup_python_base(check_only=False):
    print_header("Step 1: Portable Python (python_base)")
    base_dir = os.path.join(ROOT, "python_base")
    existing = find_python_base()
    if existing:
        ver = python_version_of(existing)
        if ver not in SUPPORTED_PYTHONS:
            print(f"[ERROR] {existing} is Python {ver}; Contour VFX needs 3.10 or 3.11.")
            print("        Delete (or rename) the python_base folder and run the installer again.")
            sys.exit(1)
        print(f"[OK] python_base exists (Python {ver[0]}.{ver[1]}).")
        return existing
    if check_only:
        print("[MISSING] python_base")
        return None

    os.makedirs(DOWNLOAD_TMP, exist_ok=True)
    zip_path = os.path.join(DOWNLOAD_TMP, "python-3.10.11-embed-amd64.zip")
    wheel = os.path.join(DOWNLOAD_TMP, PIP_WHEEL["name"])
    if not (fetch(PYTHON_EMBED["url"], zip_path, PYTHON_EMBED["sha256"], PYTHON_EMBED["size"])
            and fetch(PIP_WHEEL["url"], wheel, PIP_WHEEL["sha256"], PIP_WHEEL["size"])):
        print("[ERROR] Could not download portable Python.")
        sys.exit(1)

    import zipfile
    tmp_dir = base_dir + ".part"
    shutil.rmtree(tmp_dir, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp_dir)  # hash-checked python.org archive

    # Enable site-packages in the embeddable distribution.
    pth_file = os.path.join(tmp_dir, "python310._pth")
    with open(pth_file) as f:
        lines = f.readlines()
    with open(pth_file, "w") as f:
        for line in lines:
            f.write("import site\n" if line.strip() == "#import site" else line)

    os.replace(tmp_dir, base_dir)
    python_exe = os.path.join(base_dir, "python.exe")
    # Bootstrap pip by running it straight from its (hash-checked) wheel: no get-pip.py.
    # (runpy, because pip refuses to upgrade itself when argv[0] is literally "pip".)
    bootstrap = ("import runpy, sys; sys.path.insert(0, sys.argv[1]); del sys.argv[1]; "
                 "runpy.run_module('pip', run_name='__main__', alter_sys=True)")
    try:
        subprocess.check_call([python_exe, "-c", bootstrap, wheel, "install", "--no-index",
                               "--no-warn-script-location", wheel])
    except Exception as e:
        shutil.rmtree(base_dir, ignore_errors=True)  # never leave a python_base without pip
        print(f"[ERROR] Could not install pip into python_base: {e}")
        sys.exit(1)
    os.remove(zip_path)
    os.remove(wheel)
    print("[OK] Portable Python 3.10.11 and pip installed.")
    return python_exe


def installed_packages(python_exe):
    try:
        out = subprocess.check_output([python_exe, "-m", "pip", "list", "--format=json"], text=True,
                                      stderr=subprocess.DEVNULL)
        return {p["name"].lower(): p["version"] for p in json.loads(out)}
    except Exception:
        return {}


def install_requirements(python_exe):
    print_header("Step 2: Python packages (requirements-lock.txt)")
    lock = os.path.join(ROOT, LOCK_FILE)
    if not os.path.exists(lock):
        print(f"[ERROR] {LOCK_FILE} not found.")
        sys.exit(1)
    try:
        subprocess.check_call([python_exe, "-m", "pip", "install", "--no-warn-script-location", "-r", lock])
        # opencv-python and opencv-contrib-python both own the cv2 folder; having both
        # installed breaks cv2. mediapipe needs the contrib build, so keep only that one.
        pkgs = installed_packages(python_exe)
        if "opencv-python" in pkgs and "opencv-contrib-python" in pkgs:
            print("[FIX] Removing opencv-python (conflicts with opencv-contrib-python)...")
            subprocess.check_call([python_exe, "-m", "pip", "uninstall", "-y", "opencv-python"])
            contrib = f"opencv-contrib-python=={pkgs['opencv-contrib-python']}"
            subprocess.check_call([python_exe, "-m", "pip", "install", "--force-reinstall", "--no-deps", contrib])
        print("[OK] Packages installed.")
    except Exception as e:
        print(f"[ERROR] Failed to install packages: {e}")
        sys.exit(1)


# ------------------------------------------------------------------ models

def item_status(task, verify=False):
    """'ok', 'unverified', 'bad' or 'missing' for one MODELS entry (no network)."""
    t = task["type"]
    if t == "file":
        path = _abs(task["path"])
        if not os.path.exists(path):
            return "missing"
        if not downloads.file_is_installed(path, task.get("size"), task.get("sha256"), verify_hash=verify):
            return "bad"
        return "ok"
    if t == "zip_extract":
        return "ok" if os.path.exists(_abs(task["final_name"])) else "missing"
    if t == "hf_repo":
        check = _abs(task["check_dir"]) if task.get("check_dir") else None
        status = downloads.hf_status(_abs(task["local_dir"]), task.get("revision"), check)
        if status == "ok" and task.get("code_sha256"):
            try:
                downloads.require_local_model(_abs(task["local_dir"]), code_hashes=task["code_sha256"])
            except Exception:
                return "unverified"  # code changed since the snapshot: fetch the pinned files again
        return status
    return "missing"


def download_zip_item(task):
    os.makedirs(DOWNLOAD_TMP, exist_ok=True)
    archive = os.path.join(DOWNLOAD_TMP, os.path.basename(task["url"]))
    if not fetch(task["url"], archive, task.get("sha256"), task.get("size")):
        return False
    try:
        if task.get("extract_all"):
            n = downloads.extract_archive_tree(archive, _abs(task["dest_dir"]), exclude=task.get("exclude", ()))
            print(f"[OK] Extracted {n} files to {task['dest_dir']}")
        else:
            import zipfile
            final = _abs(task["final_name"])
            with zipfile.ZipFile(archive) as z:
                member = next((i for i in z.infolist() if i.filename.endswith(task["extract_target"])), None)
                if member is None:
                    print(f"[ERROR] {task['extract_target']} not found inside the archive.")
                    return False
                os.makedirs(os.path.dirname(final), exist_ok=True)
                with z.open(member) as src, open(final + ".part", "wb") as out:
                    shutil.copyfileobj(src, out, downloads.CHUNK)
                os.replace(final + ".part", final)
            print(f"[OK] Extracted {task['final_name']}")
        if not os.path.exists(_abs(task["final_name"])):
            print(f"[ERROR] {task['final_name']} missing after extraction.")
            return False
        os.remove(archive)
        return True
    except Exception as e:
        print(f"[ERROR] Extraction failed: {e}")
        return False


_HF_SCRIPT = """
import json, sys
from huggingface_hub import snapshot_download
a = json.loads(sys.argv[1])
snapshot_download(repo_id=a['repo_id'], revision=a['revision'], local_dir=a['local_dir'],
                  ignore_patterns=a['ignore_patterns'])
"""


def download_huggingface_repo(task, python_exe):
    local_dir = _abs(task["local_dir"])
    repo_id, revision = task["repo_id"], task["revision"]
    print(f"[DOWNLOAD] HF repo {repo_id} @ {revision[:10]}")
    args = {"repo_id": repo_id, "revision": revision, "local_dir": local_dir,
            "ignore_patterns": task.get("ignore_patterns")}
    try:
        # huggingface_hub lives in python_base, not in the Python running this script.
        subprocess.check_call([python_exe, "-c", _HF_SCRIPT, json.dumps(args)])
    except Exception as e:
        print(f"[ERROR] Failed to download HF repo {repo_id}: {e}")
        if task.get("gated"):
            print(f"   {repo_id} is gated: request access at https://huggingface.co/{repo_id}, then run "
                  f"'python_base\\python.exe -c \"from huggingface_hub import login; login()\"' and re-run this script.")
        return False
    if task.get("code_sha256"):
        try:
            downloads.require_local_model(local_dir, kind=task["name"], code_hashes=task["code_sha256"])
        except Exception as e:
            print(f"[ERROR] {e}")
            return False
    # Only a finished snapshot of the pinned revision counts as installed.
    downloads.hf_write_marker(local_dir, revision)
    print(f"[OK] {repo_id} ready in {task['local_dir']}")
    return True


def download_models(python_exe, check_only=False, verify=False):
    print_header("Step 3: AI models and binaries")
    failed = []
    for task in MODELS:
        status = item_status(task, verify=verify)
        if status == "ok":
            print(f"[OK] {task['name']}")
            continue
        if check_only:
            print(f"[{status.upper()}] {task['name']}")
            if status != "unverified":
                failed.append(task["name"])
            continue
        if status == "bad":
            path = _abs(task["path"])
            print(f"[BAD] {task['name']}: size or hash does not match, downloading again.")
            os.replace(path, path + ".part")  # a resume attempt; a wrong hash restarts it
        if task["type"] == "file":
            ok = fetch(task["url"], _abs(task["path"]), task.get("sha256"), task.get("size"))
        elif task["type"] == "zip_extract":
            ok = download_zip_item(task)
        elif task["type"] == "hf_repo":
            # For files already there, huggingface_hub checks them against the revision
            # and only fetches what is missing or different.
            ok = python_exe is not None and download_huggingface_repo(task, python_exe)
            if not ok and status == "unverified":
                print(f"[WARNING] {task['name']}: files are present but could not be checked "
                      "against the pinned revision (offline?). Using them as they are.")
                continue
        else:
            ok = False
        if not ok:
            failed.append(task["name"])
            print(f"[WARNING] Could not complete {task['name']}. Continuing with the rest...")

    for item in MANUAL_FILES:
        path = _abs(item["path"])
        if not os.path.exists(path):
            print(f"\n[MANUAL] {item['name']}: download it by hand into {item['path']} (see MODEL_DOWNLOADS.md).")
        elif not downloads.file_is_installed(path, item["size"], item["sha256"], verify_hash=verify):
            print(f"\n[WARNING] {item['name']} does not match the tested file (size or SHA-256).")
    return failed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Install Contour VFX")
    parser.add_argument("--check", action="store_true", help="report what is installed; change nothing")
    parser.add_argument("--verify", action="store_true", help="hash every file already present")
    parser.add_argument("--skip-deps", action="store_true", help="do not install Python packages")
    parser.add_argument("--skip-models", action="store_true", help="do not download models or binaries")
    args = parser.parse_args(argv)

    print("=" * 60)
    print(" Contour VFX - setup")
    print("=" * 60)
    check_host_python()
    os.chdir(ROOT)

    if not args.check:
        setup_git_submodules()
    python_exe = setup_python_base(check_only=args.check)
    if python_exe and not (args.check or args.skip_deps):
        install_requirements(python_exe)
    failed = []
    if not args.skip_models:
        failed = download_models(python_exe, check_only=args.check, verify=args.verify)

    print_header("Check complete" if args.check else "Setup complete")
    if failed:
        print("[ERROR] Missing or incomplete:" if args.check else
              "[ERROR] These items did not download. Run this script again, or see MODEL_DOWNLOADS.md:")
        for f in failed:
            print(f"   - {f}")
        sys.exit(1)
    if os.path.isdir(DOWNLOAD_TMP) and not os.listdir(DOWNLOAD_TMP):
        os.rmdir(DOWNLOAD_TMP)
    print("[SUCCESS] Everything is installed." if not args.check else "[OK] Everything is installed.")
    if not args.check:
        print("[RUN] Start the app with run.bat")


if __name__ == "__main__":
    main()

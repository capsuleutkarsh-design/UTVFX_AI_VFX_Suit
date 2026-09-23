import os

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DEPTH_DIR = os.path.join(ROOT_DIR, "models", "DepthAnythingV2")

DEPTH_REPOS = {
    "vits": "depth-anything/Depth-Anything-V2-Small",
    "vitb": "depth-anything/Depth-Anything-V2-Base",
    "vitl": "depth-anything/Depth-Anything-V2-Large",
}


def download_depth_anything_v2(model_size="vits", log_callback=None):
    """Return the local path to the Depth Anything V2 weights, downloading them if missing."""
    filename = f"depth_anything_v2_{model_size}.pth"
    weights_path = os.path.join(DEPTH_DIR, filename)
    if os.path.exists(weights_path):
        return weights_path

    if model_size not in DEPTH_REPOS:
        return None

    if log_callback:
        log_callback(f"Downloading {filename}...")
    try:
        from huggingface_hub import hf_hub_download
        os.makedirs(DEPTH_DIR, exist_ok=True)
        return hf_hub_download(repo_id=DEPTH_REPOS[model_size], filename=filename, local_dir=DEPTH_DIR)
    except Exception as e:
        if log_callback:
            log_callback(f"Failed to download {filename}: {e}")
        return None

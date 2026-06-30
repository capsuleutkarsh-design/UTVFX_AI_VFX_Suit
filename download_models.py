import os
import sys
import requests
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    print("tqdm is required. Please install it with 'pip install tqdm'")
    sys.exit(1)

try:
    from huggingface_hub import snapshot_download
except ImportError:
    print("huggingface_hub is required. Please install it with 'pip install huggingface_hub'")
    sys.exit(1)

# Define the base directory of the software
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Define the models and their expected locations
MODELS = [
    {
        "name": "BiRefNet (General)",
        "type": "huggingface",
        "repo_id": "ZhengPeng7/BiRefNet",
        "path": os.path.join(BASE_DIR, "plugins", "CorridorKey", "System", "BiRefNetModule", "checkpoints", "BiRefNet"),
        "check_file": "model.safetensors"
    },
    {
        "name": "BiRefNet (Matting)",
        "type": "huggingface",
        "repo_id": "ZhengPeng7/BiRefNet-matting",
        "path": os.path.join(BASE_DIR, "plugins", "CorridorKey", "System", "BiRefNetModule", "checkpoints", "BiRefNet-matting"),
        "check_file": "model.safetensors"
    },
    {
        "name": "BiRefNet (Portrait)",
        "type": "huggingface",
        "repo_id": "ZhengPeng7/BiRefNet-portrait",
        "path": os.path.join(BASE_DIR, "plugins", "CorridorKey", "System", "BiRefNetModule", "checkpoints", "BiRefNet-portrait"),
        "check_file": "model.safetensors"
    },
    {
        "name": "MatAnyone 2",
        "type": "url",
        "url": "https://github.com/pq-yang/MatAnyone2/releases/download/v1.0.0/matanyone2.pth",
        "path": os.path.join(BASE_DIR, "plugins", "MatAnyone2", "pretrained_models"),
        "check_file": "matanyone2.pth"
    },
    {
        "name": "Segment Anything (SAM)",
        "type": "url",
        "url": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth",
        "path": os.path.join(BASE_DIR, "plugins", "MatAnyone2", "pretrained_models"),
        "check_file": "sam_vit_h_4b8939.pth"
    },
    {
        "name": "Depth Anything V2 (Large)",
        "type": "url",
        "url": "https://huggingface.co/depth-anything/Depth-Anything-V2-Large/resolve/main/depth_anything_v2_vitl.pth",
        "path": os.path.join(BASE_DIR, "plugins", "Depth-Anything-V2", "checkpoints"),
        "check_file": "depth_anything_v2_vitl.pth"
    }
]

def download_file_from_url(url, save_dir, filename):
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, filename)
    
    response = requests.get(url, stream=True)
    response.raise_for_status()
    
    total_size = int(response.headers.get('content-length', 0))
    
    with open(save_path, 'wb') as file, tqdm(
        desc=filename,
        total=total_size,
        unit='iB',
        unit_scale=True,
        unit_divisor=1024,
    ) as bar:
        for data in response.iter_content(chunk_size=1024):
            size = file.write(data)
            bar.update(size)

def main():
    print("=" * 60)
    print("UTVFX AI & VFX Suit - Smart Model Downloader")
    print("=" * 60)
    print("Checking installed models...\n")

    models_to_download = []

    # Check which models are missing
    for model in MODELS:
        expected_file = os.path.join(model["path"], model["check_file"])
        if os.path.exists(expected_file):
            print(f"[OK] {model['name']} is already installed.")
        else:
            print(f"[MISSING] {model['name']} needs to be downloaded.")
            models_to_download.append(model)
            
    if not models_to_download:
        print("\nAll models are already installed! You are good to go.")
        return

    print(f"\n{len(models_to_download)} model(s) need to be downloaded.")
    user_input = input("Do you want to download them now? (y/n): ")
    
    if user_input.lower() != 'y':
        print("Download cancelled.")
        return

    print("\nStarting downloads...")
    for model in models_to_download:
        print(f"\n--- Downloading {model['name']} ---")
        try:
            if model["type"] == "huggingface":
                os.makedirs(model["path"], exist_ok=True)
                snapshot_download(
                    repo_id=model["repo_id"],
                    local_dir=model["path"]
                )
                print(f"Successfully downloaded {model['name']}")
                
            elif model["type"] == "url":
                download_file_from_url(model["url"], model["path"], model["check_file"])
                print(f"Successfully downloaded {model['name']}")
                
        except Exception as e:
            print(f"Error downloading {model['name']}: {e}")

    print("\n" + "=" * 60)
    print("Download process finished!")
    print("=" * 60)

if __name__ == "__main__":
    main()

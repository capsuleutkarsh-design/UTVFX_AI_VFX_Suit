import os
import sys
import subprocess
import urllib.request
import zipfile
import io
import time

def print_header(title):
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)

def setup_virtualenv():
    print_header("Step 1: Setting up Virtual Environment")
    venv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv")
    if not os.path.exists(venv_dir):
        print("Creating virtual environment 'venv'...")
        try:
            subprocess.check_call([sys.executable, "-m", "venv", "venv"])
            print("[OK] Virtual environment created successfully.")
        except Exception as e:
            print(f"[ERROR] Failed to create virtual environment: {e}")
            sys.exit(1)
    else:
        print("[OK] Virtual environment 'venv' already exists.")

def install_requirements():
    print_header("Step 2: Installing Dependencies")
    venv_python = os.path.join("venv", "Scripts", "python.exe") if os.name == 'nt' else os.path.join("venv", "bin", "python")
    req_file = "requirements.txt"
    if not os.path.exists(req_file):
        print(f"[WARNING] {req_file} not found. Skipping dependency installation.")
        return

    print("Installing required Python packages...")
    try:
        subprocess.check_call([venv_python, "-m", "pip", "install", "-r", req_file])
        # Also ensure huggingface_hub is installed for model downloads
        subprocess.check_call([venv_python, "-m", "pip", "install", "huggingface_hub"])
        print("[OK] Dependencies installed successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to install dependencies: {e}")
        sys.exit(1)

def format_size(bytes_size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0

def download_with_retry(url, filepath, retries=3):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if os.path.exists(filepath):
        print(f"[OK] {os.path.basename(filepath)} already exists. Skipping.")
        return True

    print(f"[DOWNLOAD] Downloading {os.path.basename(filepath)}...")
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            response = urllib.request.urlopen(req, timeout=30)
            total_size = int(response.headers.get('content-length', 0))
            
            with open(filepath, 'wb') as f:
                downloaded = 0
                while True:
                    buffer = response.read(8192)
                    if not buffer: break
                    f.write(buffer)
                    downloaded += len(buffer)
                    if total_size > 0:
                        percent = int(50 * downloaded / total_size)
                        sys.stdout.write(f"\r[{'=' * percent}{' ' * (50 - percent)}] {format_size(downloaded)} / {format_size(total_size)}")
                        sys.stdout.flush()
            print(f"\n[OK] Saved to {filepath}")
            return True
        except Exception as e:
            print(f"\n[WARNING] Attempt {attempt} failed: {e}")
            if attempt < retries:
                time.sleep(2)
            else:
                if os.path.exists(filepath):
                    os.remove(filepath)
                return False
    return False

def extract_zip_with_retry(url, extract_target, final_dest, retries=3):
    if os.path.exists(final_dest):
        print(f"[OK] {os.path.basename(final_dest)} already exists. Skipping.")
        return True
    
    print(f"[DOWNLOAD] Downloading and extracting {os.path.basename(final_dest)}...")
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            response = urllib.request.urlopen(req, timeout=30)
            total_size = int(response.headers.get('content-length', 0))
            zip_data = io.BytesIO()
            downloaded = 0
            while True:
                buffer = response.read(8192)
                if not buffer: break
                zip_data.write(buffer)
                downloaded += len(buffer)
                if total_size > 0:
                    percent = int(50 * downloaded / total_size)
                    sys.stdout.write(f"\r[{'=' * percent}{' ' * (50 - percent)}] {format_size(downloaded)} / {format_size(total_size)}")
                    sys.stdout.flush()
            
            print("\n[WAIT] Extracting...")
            extracted = False
            with zipfile.ZipFile(zip_data) as z:
                for file_info in z.infolist():
                    if file_info.filename.endswith(extract_target):
                        os.makedirs(os.path.dirname(final_dest), exist_ok=True)
                        with z.open(file_info) as source, open(final_dest, "wb") as target:
                            target.write(source.read())
                        extracted = True
                        print(f"[OK] Extracted to {final_dest}")
                        break
            if extracted:
                return True
            else:
                print(f"[ERROR] Could not find {extract_target} inside zip.")
                return False
        except Exception as e:
            print(f"\n[WARNING] Attempt {attempt} failed: {e}")
            if attempt < retries:
                time.sleep(2)
    return False

def download_huggingface_repo(repo_id, local_dir):
    if os.path.exists(local_dir) and len(os.listdir(local_dir)) > 0:
        print(f"[OK] HF Repo {repo_id} already exists at {local_dir}. Skipping.")
        return True
    
    print(f"[DOWNLOAD] Downloading HF Repo {repo_id}...")
    venv_python = os.path.join("venv", "Scripts", "python.exe") if os.name == 'nt' else os.path.join("venv", "bin", "python")
    script = f"""
from huggingface_hub import snapshot_download
snapshot_download(repo_id='{repo_id}', local_dir=r'{local_dir}')
print('Download complete.')
"""
    try:
        subprocess.check_call([venv_python, "-c", script])
        print(f"[OK] Successfully downloaded {repo_id} to {local_dir}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to download HF repo {repo_id}: {e}")
        return False

def download_models():
    print_header("Step 3: Downloading AI Models and Binaries")
    failed_downloads = []
    
    # Define models dictionary
    tasks = [
        # DepthAnythingV2
        {"name": "Depth-Anything V2 (Large)", "type": "file", "url": "https://huggingface.co/depth-anything/Depth-Anything-V2-Large/resolve/main/depth_anything_v2_vitl.pth", "path": "models/DepthAnythingV2/depth_anything_v2_vitl.pth"},
        # SAM 1
        {"name": "SAM ViT-H", "type": "file", "url": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth", "path": "models/SAM/sam_vit_h_4b8939.pth"},
        # SAM 2
        {"name": "SAM 2 Hiera Large", "type": "file", "url": "https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_large.pt", "path": "models/SAM2/sam2_hiera_large.pt"},
        {"name": "SAM 2 Config", "type": "file", "url": "https://raw.githubusercontent.com/facebookresearch/segment-anything-2/main/sam2/configs/sam2_hiera_l.yaml", "path": "models/SAM2/sam2_hiera_l.yaml"},
        # ViTMatte
        # (Note: ViTMatte ONNX is generated locally by export scripts, skipping download)
        # CorridorKey
        {"name": "CorridorKey", "type": "file", "url": "https://huggingface.co/nikopueringer/CorridorKey_v1.0/resolve/main/CorridorKey_v1.0.safetensors", "path": "models/CorridorKey/CorridorKey_v1.0.safetensors"},
        # BiRefNet
        {"name": "BiRefNet", "type": "file", "url": "https://huggingface.co/ZhengPeng7/BiRefNet/resolve/main/model.safetensors", "path": "models/BiRefNet/model.safetensors"},
        # FFmpeg
        {"name": "FFmpeg (Windows)", "type": "zip_extract", "url": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip", "extract_target": "bin/ffmpeg.exe", "final_name": "plugins/3DTracker/bin/ffmpeg.exe"},
        # UV
        {"name": "UV Package Manager", "type": "zip_extract", "url": "https://github.com/astral-sh/uv/releases/download/0.1.39/uv-x86_64-pc-windows-msvc.zip", "extract_target": "uv.exe", "final_name": "tools/uv.exe"},
        # HuggingFace Repos (SAM 3, GroundingDINO, MEMatte)
        {"name": "SAM 3 Weights", "type": "hf_repo", "repo_id": "meta-llama/Llama-3.2-11B-Vision-Instruct", "local_dir": "models/SAM3"},
        {"name": "GroundingDINO Weights", "type": "hf_repo", "repo_id": "IDEA-Research/grounding-dino-base", "local_dir": "models/GroundingDINO"},
        {"name": "ViTMatte Weights (HF)", "type": "hf_repo", "repo_id": "hustvl/vitmatte-base-composition-1k", "local_dir": "models/ViTMatteHF"}
    ]
    
    for task in tasks:
        success = False
        if task["type"] == "file":
            success = download_with_retry(task["url"], task["path"])
        elif task["type"] == "zip_extract":
            success = extract_zip_with_retry(task["url"], task["extract_target"], task["final_name"])
        elif task["type"] == "hf_repo":
            success = download_huggingface_repo(task["repo_id"], task["local_dir"])
            
        if not success:
            failed_downloads.append(task["name"])
            print(f"[WARNING] Warning: Could not complete {task['name']}. Continuing with remaining...")
    
    # Specialized local handling for MEMatte (it doesn't have an official direct huggingface standard repo for this precise weights file usually, but we will place a placeholder if user needs manual download)
    mematte_path = "models/MEMatte/MEMatte_ViTB_DIM.pth"
    if not os.path.exists(mematte_path):
        print("\n[WARNING] Note: MEMatte weights (MEMatte_ViTB_DIM.pth) must be downloaded manually if you don't have them in 'models/MEMatte/'.")
        
    return failed_downloads

def main():
    print("=" * 60)
    print(" UTVFX AI & VFX Suit - Universal Setup Script")
    print("=" * 60 + "\n")
    
    setup_virtualenv()
    install_requirements()
    failed = download_models()
    
    print_header("Setup Complete")
    if failed:
        print("[ERROR] The following items failed to download correctly. You may need to run this script again or download them manually:")
        for f in failed:
            print(f"   - {f}")
        print("\nOnce everything is resolved, you can start the software by running: `run.bat` or `venv\\Scripts\\python main.py`")
        sys.exit(1)
    else:
        print("[SUCCESS] Setup finished successfully! Everything is up to date.")
        print("[RUN] You can now start the software by running: `run.bat` or `venv\\Scripts\\python main.py`")

if __name__ == "__main__":
    main()

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

def setup_python_base():
    print_header("Step 1: Setting up Portable Python (python_base)")
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "python_base")
    python_exe = os.path.join(base_dir, "python.exe")
    
    if os.path.exists(python_exe):
        print("[OK] Portable Python 'python_base' already exists.")
        return python_exe

    print("Downloading Python 3.10.11 Embeddable...")
    python_zip = "python-3.10.11-embed.zip"
    url = "https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip"
    
    try:
        urllib.request.urlretrieve(url, python_zip)
        print("[OK] Downloaded Python zip.")
        
        print("Extracting Python to python_base...")
        with zipfile.ZipFile(python_zip, 'r') as zip_ref:
            zip_ref.extractall(base_dir)
        os.remove(python_zip)
        
        # Uncomment 'import site' in python310._pth to enable pip
        pth_file = os.path.join(base_dir, "python310._pth")
        if os.path.exists(pth_file):
            with open(pth_file, "r") as f:
                lines = f.readlines()
            with open(pth_file, "w") as f:
                for line in lines:
                    if line.strip() == "#import site":
                        f.write("import site\n")
                    else:
                        f.write(line)
        print("[OK] Portable Python extracted and configured.")
        
        # Install pip
        print("Downloading get-pip.py...")
        get_pip_path = os.path.join(base_dir, "get-pip.py")
        urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", get_pip_path)
        
        print("Installing pip...")
        subprocess.check_call([python_exe, get_pip_path])
        os.remove(get_pip_path)
        print("[OK] Pip installed successfully.")
        
        return python_exe
    except Exception as e:
        print(f"[ERROR] Failed to setup python_base: {e}")
        sys.exit(1)

def install_requirements(python_exe):
    print_header("Step 2: Installing Dependencies")
    req_file = "requirements.txt"
    if not os.path.exists(req_file):
        print(f"[WARNING] {req_file} not found. Skipping dependency installation.")
        return

    print("Installing required Python packages into python_base...")
    try:
        subprocess.check_call([python_exe, "-m", "pip", "install", "-r", req_file])
        subprocess.check_call([python_exe, "-m", "pip", "install", "huggingface_hub"])
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

def download_huggingface_repo(repo_id, local_dir, python_exe):
    if os.path.exists(local_dir):
        files = [f for f in os.listdir(local_dir) if not f.startswith('.')]
        if len(files) > 0:
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
        subprocess.check_call([python_exe, "-c", script])
        print(f"[OK] Successfully downloaded {repo_id} to {local_dir}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to download HF repo {repo_id}: {e}")
        return False

MODELS = [
    # DepthAnythingV2
    {"name": "Depth-Anything V2 (Large)", "type": "file", "url": "https://huggingface.co/depth-anything/Depth-Anything-V2-Large/resolve/main/depth_anything_v2_vitl.pth", "path": "models/DepthAnythingV2/depth_anything_v2_vitl.pth"},
    {"name": "Depth-Anything V2 (Base)", "type": "file", "url": "https://huggingface.co/depth-anything/Depth-Anything-V2-Base/resolve/main/depth_anything_v2_vitb.pth", "path": "models/DepthAnythingV2/depth_anything_v2_vitb.pth"},
    {"name": "Depth-Anything V2 (Small)", "type": "file", "url": "https://huggingface.co/depth-anything/Depth-Anything-V2-Small/resolve/main/depth_anything_v2_vits.pth", "path": "models/DepthAnythingV2/depth_anything_v2_vits.pth"},
    
    # SAM 1 (Meta Checkpoint & HF Repo)
    {"name": "SAM ViT-H (Meta)", "type": "file", "url": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth", "path": "models/SAM/sam_vit_h_4b8939.pth"},
    {"name": "SAM ViT-H (HF)", "type": "hf_repo", "repo_id": "facebook/sam-vit-huge", "local_dir": "models/SAM"},
    
    # SAM 2 (Meta Checkpoints & HF Repo)
    {"name": "SAM 2 Hiera Large (Meta)", "type": "file", "url": "https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_large.pt", "path": "models/SAM2/sam2_hiera_large.pt"},
    {"name": "SAM 2 Config", "type": "file", "url": "https://raw.githubusercontent.com/facebookresearch/segment-anything-2/main/sam2/configs/sam2_hiera_l.yaml", "path": "models/SAM2/sam2_hiera_l.yaml"},
    {"name": "SAM 2 Hiera Large (HF)", "type": "hf_repo", "repo_id": "facebook/sam2-hiera-large", "local_dir": "models/SAM2"},
    
    # ViTMatte
    # (Note: ONNX artifacts like vitmatte_base.onnx are locally generated by export scripts)
    {"name": "ViTMatte Weights (HF)", "type": "hf_repo", "repo_id": "hustvl/vitmatte-small-composition-1k", "local_dir": "models/ViTMatte"},
    
    # CorridorKey
    {"name": "CorridorKey", "type": "file", "url": "https://huggingface.co/nikopueringer/CorridorKey_v1.0/resolve/main/CorridorKey_v1.0.safetensors", "path": "models/CorridorKey/CorridorKey_v1.0.safetensors"},
    
    # BiRefNet (HF Repo)
    {"name": "BiRefNet", "type": "hf_repo", "repo_id": "ZhengPeng7/BiRefNet", "local_dir": "models/BiRefNet/BiRefNet"},
    {"name": "BiRefNet (Matting)", "type": "hf_repo", "repo_id": "ZhengPeng7/BiRefNet-matting", "local_dir": "models/BiRefNet/BiRefNet-matting"},
    {"name": "BiRefNet (Portrait)", "type": "hf_repo", "repo_id": "ZhengPeng7/BiRefNet-portrait", "local_dir": "models/BiRefNet/BiRefNet-portrait"},
    

    
    # Binaries
    {"name": "FFmpeg (Windows)", "type": "zip_extract", "url": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip", "extract_target": "bin/ffmpeg.exe", "final_name": "plugins/3DTracker/bin/ffmpeg.exe"},
    {"name": "UV Package Manager", "type": "zip_extract", "url": "https://github.com/astral-sh/uv/releases/download/0.1.39/uv-x86_64-pc-windows-msvc.zip", "extract_target": "uv.exe", "final_name": "tools/uv.exe"},
    
    # Additional HuggingFace Repos (SAM 3, GroundingDINO)
    {"name": "SAM 3 Weights", "type": "hf_repo", "repo_id": "1038lab/sam3", "local_dir": "models/SAM3"},
    {"name": "GroundingDINO Weights", "type": "hf_repo", "repo_id": "IDEA-Research/grounding-dino-base", "local_dir": "models/GroundingDINO"},
    
    # VideoMaMa Temporal Refiner
    {"name": "VideoMaMa Base (SVD-XT)", "type": "hf_repo", "repo_id": "stabilityai/stable-video-diffusion-img2vid-xt", "local_dir": "models/VideoMaMa/stable-video-diffusion-img2vid-xt"},
    {"name": "VideoMaMa Fine-Tuned UNet", "type": "hf_repo", "repo_id": "SammyLim/VideoMaMa", "local_dir": "models/VideoMaMa"}
]

def download_models(python_exe):
    print_header("Step 3: Downloading AI Models and Binaries")
    failed_downloads = []
    
    for task in MODELS:
        success = False
        if task["type"] == "file":
            success = download_with_retry(task["url"], task["path"])
        elif task["type"] == "zip_extract":
            success = extract_zip_with_retry(task["url"], task["extract_target"], task["final_name"])
        elif task["type"] == "hf_repo":
            success = download_huggingface_repo(task["repo_id"], task["local_dir"], python_exe)
            
        if not success:
            failed_downloads.append(task["name"])
            print(f"[WARNING] Warning: Could not complete {task['name']}. Continuing with remaining...")
    
    # Specialized local handling for MEMatte (it doesn't have an official direct huggingface standard repo for this precise weights file usually, but we will place a placeholder if user needs manual download)
    mematte_path = "models/MEMatte/MEMatte_ViTB_DIM.pth"
    if not os.path.exists(mematte_path):
        print("\n[WARNING] Note: MEMatte weights (MEMatte_ViTB_DIM.pth) must be downloaded manually if you don't have them in 'models/MEMatte/'.")
        
    return failed_downloads

def setup_git_submodules():
    print_header("Step 0: Initializing Git Submodules (Plugins & Extras)")
    try:
        # Check if git is installed
        subprocess.check_call(["git", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("Git found. Updating submodules...")
        subprocess.check_call(["git", "submodule", "update", "--init", "--recursive"])
        print("[OK] Git submodules initialized successfully.")
    except Exception as e:
        print(f"[WARNING] Could not automatically update git submodules: {e}")
        print("If you are missing plugin files, please run: git submodule update --init --recursive")

def main():
    print("=" * 60)
    print(" UTVFX AI & VFX Suit - Universal Setup Script")
    print("=" * 60 + "\n")
    
    setup_git_submodules()
    python_exe = setup_python_base()
    install_requirements(python_exe)
    failed = download_models(python_exe)
    
    print_header("Setup Complete")
    if failed:
        print("[ERROR] The following items failed to download correctly. You may need to run this script again or download them manually:")
        for f in failed:
            print(f"   - {f}")
        print("\nOnce everything is resolved, you can start the software by running: `run.bat`")
        sys.exit(1)
    else:
        print("[SUCCESS] Setup finished successfully! Everything is up to date.")
        print("[RUN] You can now start the software by running: `run.bat`")

if __name__ == "__main__":
    main()

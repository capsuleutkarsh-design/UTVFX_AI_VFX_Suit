import os
import urllib.request
import zipfile
import io
import sys

MODELS = [
    {
        "name": "Depth-Anything V2 (Large)",
        "url": "https://huggingface.co/depth-anything/Depth-Anything-V2-Large/resolve/main/depth_anything_v2_vitl.pth",
        "path": "plugins/Depth-Anything-V2/checkpoints/depth_anything_v2_vitl.pth",
        "type": "file"
    },
    {
        "name": "SAM ViT-H",
        "url": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth",
        "path": "plugins/MatAnyone2/pretrained_models/sam_vit_h_4b8939.pth",
        "type": "file"
    },
    {
        "name": "MatAnyone",
        "url": "https://huggingface.co/pq-lv/MatAnyone/resolve/main/matanyone.pth",
        "path": "plugins/MatAnyone2/pretrained_models/matanyone.pth",
        "type": "file"
    },
    {
        "name": "CorridorKey",
        "url": "https://huggingface.co/nikopueringer/CorridorKey_v1.0/resolve/main/CorridorKey_v1.0.safetensors",
        "path": "plugins/CorridorKey/System/CorridorKeyModule/checkpoints/CorridorKey_v1.0.safetensors",
        "type": "file"
    },
    {
        "name": "BiRefNet",
        "url": "https://huggingface.co/ZhengPeng7/BiRefNet/resolve/main/model.safetensors",
        "path": "plugins/CorridorKey/System/BiRefNetModule/checkpoints/BiRefNet/model.safetensors",
        "type": "file"
    },
    # Binaries
    {
        "name": "FFmpeg & FFprobe (Windows)",
        "url": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
        "path": "plugins/3DTracker/bin/ffmpeg-2026-06-15-git-44d082edc8-full_build/bin",
        "type": "zip_extract",
        "extract_target": "bin/ffmpeg.exe",
        "final_name": "ffmpeg.exe"
    },
    {
        "name": "UV Package Manager",
        "url": "https://github.com/astral-sh/uv/releases/download/0.1.39/uv-x86_64-pc-windows-msvc.zip",
        "path": "tools/uv.exe",
        "type": "zip_extract",
        "extract_target": "uv.exe",
        "final_name": "uv.exe"
    }
]

def format_size(bytes):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes < 1024.0:
            return f"{bytes:.2f} {unit}"
        bytes /= 1024.0

def download_item(item):
    filepath = item["path"]
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    # Check if exists
    if item["type"] == "file" and os.path.exists(filepath):
        print(f"✅ {item['name']} already exists. Skipping.")
        return
    elif item["type"] == "zip_extract":
        final_dest = os.path.join(os.path.dirname(filepath), item["final_name"]) if not filepath.endswith(".exe") else filepath
        if os.path.exists(final_dest):
            print(f"✅ {item['name']} already exists. Skipping.")
            return

    print(f"📥 Downloading {item['name']}...")
    try:
        req = urllib.request.Request(item["url"], headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req)
        total_size = int(response.headers.get('content-length', 0))
        
        # If it's a direct file
        if item["type"] == "file":
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
            print(f"\n✅ Saved to {filepath}\n")
            
        # If it's a ZIP extraction
        elif item["type"] == "zip_extract":
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
            
            print(f"\n⏳ Extracting {item['final_name']}...")
            extracted = False
            with zipfile.ZipFile(zip_data) as z:
                for file_info in z.infolist():
                    if file_info.filename.endswith(item["extract_target"]):
                        final_dest = os.path.join(os.path.dirname(filepath), item["final_name"]) if not filepath.endswith(".exe") else filepath
                        os.makedirs(os.path.dirname(final_dest), exist_ok=True)
                        with z.open(file_info) as source, open(final_dest, "wb") as target:
                            target.write(source.read())
                        extracted = True
                        print(f"✅ Extracted to {final_dest}\n")
            if not extracted:
                print(f"❌ Could not find {item['extract_target']} inside the downloaded zip.\n")
                
    except Exception as e:
        print(f"\n❌ Failed to download {item['name']}. Error: {e}\n")

if __name__ == "__main__":
    print("=" * 60)
    print(" UTVFX AI & VFX Suit - First Setup Helper")
    print("=" * 60 + "\n")
    
    for model in MODELS:
        download_item(model)
        
    print("\n" + "=" * 60)
    print(" ⚠️ IMPORTANT MANUAL SETUP REQUIRED ⚠️")
    print("=" * 60)
    print("Some 3D Tracker binaries could not be safely automated.")
    print("You MUST manually place the following folders:")
    print("1. plugins/3DTracker/bin/colmap-x64-windows-cuda/")
    print("2. plugins/3DTracker/bin/glomap-x64-windows-cuda/")
    print("=" * 60)
    print("\n🎉 Setup script finished!")

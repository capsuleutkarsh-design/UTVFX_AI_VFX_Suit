import os
import zipfile

def create_models_zip():
    zip_filename = "build/UTVFX_Models.zip"
    
    # Define which extensions to look for
    model_exts = ('.pth', '.pt', '.safetensors', '.onnx', '.bin')
    
    # Define directories to search
    search_dirs = ['plugins', 'CorridorKeyModule']
    
    # Find all local model files
    local_models = {}
    for search_dir in search_dirs:
        if not os.path.exists(search_dir):
            continue
        for root, _, files in os.walk(search_dir):
            for file in files:
                if file.lower().endswith(model_exts):
                    file_path = os.path.normpath(os.path.join(root, file))
                    # Normalizing for zip format (forward slashes)
                    zip_path = file_path.replace("\\", "/")
                    local_models[zip_path] = os.path.getsize(file_path)

    # Check if the zip already exists and has all the required models
    needs_update = True
    if os.path.exists(zip_filename):
        needs_update = False
        try:
            with zipfile.ZipFile(zip_filename, 'r') as zipf:
                zip_info = {info.filename: info.file_size for info in zipf.infolist()}
                
                for zip_path, local_size in local_models.items():
                    if zip_path not in zip_info or zip_info[zip_path] != local_size:
                        needs_update = True
                        break
        except zipfile.BadZipFile:
            needs_update = True
            
    if not needs_update:
        print(f"{zip_filename} is already up to date. Skipping zip creation.")
        return

    print(f"Models have changed or zip is missing. Creating {zip_filename}...")
    
    # Create the zip file
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as zipf:
        for zip_path, local_size in local_models.items():
            # Convert back to local path for reading
            local_path = zip_path.replace("/", os.sep)
            print(f"Adding {local_path}")
            zipf.write(local_path, arcname=zip_path)
                        
    print(f"\nSuccessfully created {zip_filename}")
    print("You can upload this ZIP alongside your Setup.exe to GitHub.")

if __name__ == "__main__":
    create_models_zip()

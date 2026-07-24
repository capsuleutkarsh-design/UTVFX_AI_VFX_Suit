import os
import torch
import sys

# Directory setup
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGINS_DIR = os.path.dirname(CURRENT_DIR)
from utvfx.core.settings_manager import SettingsManager
ROOT_DIR = os.path.dirname(SettingsManager().models_dir)
SEGMENT_ANYTHING_DIR = os.path.join(PLUGINS_DIR, "third_party", "segment-anything")
sys.path.insert(0, SEGMENT_ANYTHING_DIR)

from segment_anything import sam_model_registry

def export_sam_encoder(model_type="vit_h", output_path="models/ONNX_Exports/sam_vit_h_encoder.onnx"):
    checkpoint = os.path.join(ROOT_DIR, "models", "SAM", "sam_vit_h_4b8939.pth")
    if not os.path.exists(checkpoint):
        print(f"Checkpoint not found at {checkpoint}")
        return

    print(f"Loading SAM {model_type}...")
    sam = sam_model_registry[model_type](checkpoint=checkpoint)
    sam.eval()
    
    # The heavy part of SAM is just the image_encoder
    image_encoder = sam.image_encoder

    # Input to image_encoder is always 1024x1024
    dummy_image = torch.randn(1, 3, 1024, 1024)

    os.makedirs(os.path.dirname(os.path.abspath(os.path.join(ROOT_DIR, output_path))), exist_ok=True)
    full_output_path = os.path.join(ROOT_DIR, output_path)

    print(f"Exporting image encoder to {full_output_path}...")
    torch.onnx.export(
        image_encoder,
        dummy_image,
        full_output_path,
        export_params=True,
        opset_version=16,
        do_constant_folding=True,
        input_names=["input_image"],
        output_names=["image_embeddings"],
        # No dynamic axes for input_image, SAM image encoder requires fixed 1024x1024
    )
    print("Export successful!")

if __name__ == "__main__":
    export_sam_encoder()

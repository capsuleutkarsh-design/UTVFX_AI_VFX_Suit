import os
import torch
from transformers import VitMatteForImageMatting

def export_vitmatte(model_id="hustvl/vitmatte-base-composition-1k", output_path="models/ONNX_Exports/vitmatte_base.onnx"):
    print(f"Loading {model_id}...")
    model = VitMatteForImageMatting.from_pretrained(model_id, use_safetensors=True)
    model.eval()

    # ViTMatte model expects a single 4-channel tensor (image + trimap concatenated)
    dummy_pixel_values = torch.randn(1, 4, 512, 512)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    print(f"Exporting to {output_path}...")
    class Wrapper(torch.nn.Module):
        def __init__(self, model):
            super().__init__()
            self.model = model
        def forward(self, pixel_values):
            return self.model(pixel_values=pixel_values).alphas

    wrapped_model = Wrapper(model)

    torch.onnx.export(
        wrapped_model,
        (dummy_pixel_values,),
        output_path,
        export_params=True,
        opset_version=16,
        do_constant_folding=True,
        input_names=["pixel_values"],
        output_names=["alphas"],
        dynamic_axes={
            "pixel_values": {0: "batch_size", 2: "height", 3: "width"},
            "alphas": {0: "batch_size", 2: "height", 3: "width"}
        }
    )
    print("Export successful!")

if __name__ == "__main__":
    export_vitmatte()

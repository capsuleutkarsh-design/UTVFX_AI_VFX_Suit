import os
import sys
import json
import argparse
import traceback
import cv2
import numpy as np
import torch

# Directory setup
CURRENT_DIR = os.path.dirname(__file__)
PLUGINS_DIR = os.path.dirname(CURRENT_DIR)
ROOT_DIR = os.path.dirname(PLUGINS_DIR)
SEGMENT_ANYTHING_DIR = os.path.join(PLUGINS_DIR, "third_party", "segment-anything")

class SAM1Predictor:
    def __init__(self, device):
        sys.path.insert(0, SEGMENT_ANYTHING_DIR)
        try:
            from segment_anything import sam_model_registry, SamPredictor
        except ImportError as e:
            raise ImportError(f"Import error: {str(e)}. Make sure segment-anything is available.")
            
        sam_model_type = "vit_h"
        checkpoint_folder = os.path.join(ROOT_DIR, "models", "SAM")
        expected_path = os.path.join(checkpoint_folder, "sam_vit_h_4b8939.pth")
        
        if not os.path.exists(expected_path):
            raise FileNotFoundError(f"Model checkpoint missing at '{expected_path}'.")
            
        sam = sam_model_registry[sam_model_type](checkpoint=expected_path)
        sam.to(device=device)
        self.predictor = SamPredictor(sam)
        
    def set_image(self, image_rgb):
        self.predictor.set_image(image_rgb)
        
    def predict(self, points, labels):
        masks, scores, logits = self.predictor.predict(
            point_coords=points,
            point_labels=labels,
            multimask_output=False,
        )
        best_idx = np.argmax(scores)
        return masks[best_idx]

class SAM3Predictor:
    def __init__(self, device):
        from transformers import Sam3Model, Sam3Processor
        self.device = device
        model_dir = os.path.join(ROOT_DIR, "models", "SAM")
        
        if not os.path.exists(model_dir):
            raise FileNotFoundError(f"SAM3 Model directory missing at '{model_dir}'.")
            
        self.processor = Sam3Processor.from_pretrained(model_dir)
        self.model = Sam3Model.from_pretrained(model_dir).to(self.device)
        self.image = None
        
    def set_image(self, image_rgb):
        self.image = image_rgb
        
    def predict(self, points, labels):
        input_points = [[points]]
        input_labels = [[labels]]
        
        inputs = self.processor(
            images=self.image, 
            input_points=input_points, 
            input_labels=input_labels, 
            return_tensors="pt"
        ).to(self.device)
        
        with torch.no_grad():
            outputs = self.model(**inputs)
            
        reshaped_sizes = inputs.get("reshaped_input_sizes", inputs.get("reshaped_input_size"))
        if reshaped_sizes is None:
            reshaped_sizes = torch.tensor([inputs["pixel_values"].shape[-2:]], device="cpu")
        else:
            reshaped_sizes = reshaped_sizes.cpu()
            
        # outputs.pred_masks could be (B, N, H, W). post_process_masks expects (B, N, C, H, W) or masks[i] to be 4D
        pred_masks = outputs.pred_masks.cpu()
        if pred_masks.dim() == 4:
            # (B, N, H, W) -> (B, N, 1, H, W)
            pred_masks = pred_masks.unsqueeze(2)
            
        try:
            masks = self.processor.image_processor.post_process_masks(
                pred_masks,
                inputs["original_sizes"].cpu(),
                reshaped_input_sizes=reshaped_sizes
            )
        except TypeError:
            masks = self.processor.image_processor.post_process_masks(
                pred_masks,
                inputs["original_sizes"].cpu()
            )
        
        mask_tensor = masks[0][0]
        mask_np = mask_tensor[0].numpy()
        return mask_np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="SAM 1 (ViT-H)")
    args = parser.parse_args()
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    try:
        print("READY", flush=True)
        
        if "SAM 3" in args.model:
            predictor = SAM3Predictor(device)
        else:
            predictor = SAM1Predictor(device)
            
        print("INITIALIZED", flush=True)
    except Exception as e:
        print(f"ERROR_INIT: {str(e)}", flush=True)
        print(f"TRACEBACK: {traceback.format_exc()}", flush=True)
        sys.exit(1)

    while True:
        line = sys.stdin.readline()
        if not line:
            break
            
        line = line.strip()
        if not line:
            continue
            
        try:
            req = json.loads(line)
            
            if req.get("action") == "shutdown":
                del predictor
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                sys.exit(0)
                
            image_path = req.get("image_path")
            points = req.get("points", [])
            labels = req.get("labels", [])
            mask_out_path = req.get("mask_out_path")
            
            if not image_path or not os.path.exists(image_path):
                print(json.dumps({"error": "Invalid image path"}), flush=True)
                continue
                
            image = cv2.imread(image_path)
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            
            pts = np.array(points)
            lbls = np.array(labels)
            
            predictor.set_image(image)
            
            mask = predictor.predict(pts, lbls)
            
            mask = np.squeeze(mask)
            mask_uint8 = (mask * 255).astype(np.uint8)
            cv2.imwrite(mask_out_path, mask_uint8)
            
            print(json.dumps({"status": "ok"}), flush=True)
            
        except Exception as e:
            print(json.dumps({"error": str(e), "traceback": traceback.format_exc()}), flush=True)

if __name__ == "__main__":
    main()

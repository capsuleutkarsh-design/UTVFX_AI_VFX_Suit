import os
import sys
import json
import traceback
import cv2
import numpy as np
import urllib.request
import time

# Point to local MatAnyone2 segment_anything
CURRENT_DIR = os.path.dirname(__file__)
PLUGINS_DIR = os.path.dirname(CURRENT_DIR)
MATANYONE_DIR = os.path.join(PLUGINS_DIR, "MatAnyone2")
SEGMENT_ANYTHING_DIR = os.path.join(MATANYONE_DIR, "third_party", "segment-anything")

sys.path.insert(0, SEGMENT_ANYTHING_DIR)

try:
    import torch
    from segment_anything import sam_model_registry, SamPredictor
except ImportError as e:
    print(json.dumps({"error": f"Import error: {str(e)}. Make sure segment-anything is available."}))
    sys.exit(1)


def init_model():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    sam_model_type = "vit_h"
    url = "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth"
    checkpoint_folder = os.path.join(MATANYONE_DIR, "pretrained_models")
    os.makedirs(checkpoint_folder, exist_ok=True)
    
    expected_path = os.path.join(checkpoint_folder, "sam_vit_h_4b8939.pth")
    if not os.path.exists(expected_path):
        raise FileNotFoundError(f"Model checkpoint missing. Please manually download '{url}' and place it at '{expected_path}'.")
        
    sam = sam_model_registry[sam_model_type](checkpoint=expected_path)
    sam.to(device=device)
    predictor = SamPredictor(sam)
    return predictor

def main():
    try:
        print("READY", flush=True)
        predictor = init_model()
        print("INITIALIZED", flush=True)
    except Exception as e:
        print(f"ERROR_INIT: {str(e)}", flush=True)
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
            
            masks, scores, logits = predictor.predict(
                point_coords=pts,
                point_labels=lbls,
                multimask_output=False,
            )
            
            # Use the mask with the highest score
            best_idx = np.argmax(scores)
            mask = masks[best_idx]
            
            mask = np.squeeze(mask)
            mask_uint8 = (mask * 255).astype(np.uint8)
            cv2.imwrite(mask_out_path, mask_uint8)
            
            print(json.dumps({"status": "ok", "mask_out_path": mask_out_path}), flush=True)
            
        except Exception as e:
            err = traceback.format_exc()
            print(json.dumps({"error": str(e), "traceback": err}), flush=True)

if __name__ == "__main__":
    main()

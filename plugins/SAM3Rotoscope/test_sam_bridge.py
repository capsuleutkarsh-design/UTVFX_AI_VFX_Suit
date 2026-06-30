import os
import sys
import cv2
import numpy as np

# Point to local MatAnyone2 segment_anything
CURRENT_DIR = os.path.abspath(os.path.dirname(__file__))
PLUGINS_DIR = os.path.dirname(CURRENT_DIR)
MATANYONE_DIR = os.path.join(PLUGINS_DIR, "MatAnyone2")
SEGMENT_ANYTHING_DIR = os.path.join(MATANYONE_DIR, "third_party", "segment-anything")

sys.path.insert(0, SEGMENT_ANYTHING_DIR)

import torch
from segment_anything import sam_model_registry, SamPredictor

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Device: {device}")

sam_model_type = "vit_h"
checkpoint_folder = os.path.join(MATANYONE_DIR, "pretrained_models")
expected_path = os.path.join(checkpoint_folder, "sam_vit_h_4b8939.pth")

print("Loading model...")
sam = sam_model_registry[sam_model_type](checkpoint=expected_path)
sam.to(device=device)
predictor = SamPredictor(sam)
print("Model loaded successfully.")

# Create a dummy image
img = np.zeros((1080, 1920, 3), dtype=np.uint8)
# Add some white blob to track
cv2.circle(img, (960, 540), 100, (255, 255, 255), -1)

predictor.set_image(img)

pts = np.array([[960, 540]])
lbls = np.array([1])

masks, scores, logits = predictor.predict(
    point_coords=pts,
    point_labels=lbls,
    multimask_output=True,
)

best_idx = np.argmax(scores)
mask = masks[best_idx]
print(f"Mask shape: {mask.shape}, max: {mask.max()}, min: {mask.min()}")

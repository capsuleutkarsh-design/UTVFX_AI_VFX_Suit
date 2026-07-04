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
        self.image = None
        
    def set_image(self, image_rgb):
        self.image = image_rgb
        self.predictor.set_image(image_rgb)
        
    def predict(self, points, labels, boxes=None):
        self.predictor.set_image(self.image)
        
        # Meta's SAM takes boxes as a separate array [x1, y1, x2, y2]
        box_input = np.array(boxes[0]) if boxes else None
        
        masks, scores, _ = self.predictor.predict(
            point_coords=np.array(points) if len(points) > 0 else None,
            point_labels=np.array(labels) if len(labels) > 0 else None,
            box=box_input,
            multimask_output=True
        )
        best_idx = np.argmax(scores)
        return masks[best_idx]
        
    def auto_scan(self):
        # SAM 1 auto-scan is not supported via this simple script, return empty
        return []

class SAM3Predictor:
    def __init__(self, device):
        from transformers import Sam3Model, Sam3Processor
        self.device = device
        model_dir = os.path.join(ROOT_DIR, "models", "SAM")
        
        if not os.path.exists(model_dir):
            raise FileNotFoundError(f"SAM3 Model directory missing at '{model_dir}'.")
            
        self.processor = Sam3Processor.from_pretrained(model_dir, local_files_only=True)
        self.model = Sam3Model.from_pretrained(model_dir, local_files_only=True).to(self.device)
        self.image = None
        
    def set_image(self, image_rgb):
        self.image = image_rgb
        
    def predict(self, points, labels, boxes=None):
        H, W = self.image.shape[:2]
        
        if boxes:
            input_boxes = [boxes]
            input_boxes_labels = [[1] * len(boxes)]
        else:
            input_boxes = [[[0, 0, W, H]]]
            input_boxes_labels = [[1]]
        
        inputs = self.processor(
            images=self.image, 
            input_boxes=input_boxes,
            input_boxes_labels=input_boxes_labels, 
            return_tensors="pt"
        ).to(self.device)
        
        with torch.no_grad():
            outputs = self.model(**inputs)
            
        original_size = inputs["original_sizes"][0].tolist() # (H, W)
        results = self.processor.image_processor.post_process_instance_segmentation(
            outputs, 
            threshold=0.0, # Get all masks to filter manually
            target_sizes=[(original_size[0], original_size[1])]
        )
        
        result = results[0]
        if len(result["scores"]) == 0:
            return np.zeros((original_size[0], original_size[1]), dtype=bool)
            
        # Post-filter: find highest scoring mask that satisfies the point clicks
        best_mask_idx = -1
        best_score = -1.0
        
        for i in range(len(result["scores"])):
            mask = result["masks"][i].cpu().detach().numpy()
            score = result["scores"][i].item()
            
            # Check if mask satisfies points
            valid = True
            for (px, py), label in zip(points, labels):
                px, py, label = int(px), int(py), int(label)
                if px < 0 or px >= W or py < 0 or py >= H:
                    continue
                
                # Check point condition
                if label == 1 and mask[py, px] == 0:
                    valid = False
                    break
                if label == 0 and mask[py, px] == 1:
                    valid = False
                    break
                    
            if valid and score > best_score:
                best_score = score
                best_mask_idx = i
                
        if best_mask_idx == -1:
            # Fallback if no mask perfectly matches points: return empty mask instead of spilling everywhere
            return np.zeros((original_size[0], original_size[1]), dtype=bool)
            
        mask_tensor = result["masks"][best_mask_idx].cpu().detach().numpy()
        return mask_tensor.astype(bool)

    def auto_scan(self):
        if self.image is None:
            return []
            
        H, W = self.image.shape[:2]
        inputs = self.processor(
            images=self.image, 
            input_boxes=[[[0, 0, W, H]]],
            input_boxes_labels=[[1]], 
            return_tensors="pt"
        ).to(self.device)
        
        with torch.no_grad():
            outputs = self.model(**inputs)
            
        original_size = inputs["original_sizes"][0].tolist()
        results = self.processor.image_processor.post_process_instance_segmentation(
            outputs, 
            threshold=0.0,
            target_sizes=[(original_size[0], original_size[1])]
        )
        
        result = results[0]
        if len(result["scores"]) == 0:
            return []
            
        scores = result["scores"].cpu().detach().numpy()
        masks = result["masks"].cpu().detach().numpy()
        
        # Get top 10 masks
        top_indices = np.argsort(scores)[::-1][:10]
        
        objects = []
        for idx in top_indices:
            mask = masks[idx] > 0
            if not np.any(mask):
                continue
                
            y_indices, x_indices = np.where(mask)
            cy = int(np.mean(y_indices))
            cx = int(np.mean(x_indices))
            
            # Fallback if the center of mass isn't actually on the object (e.g. donut shape)
            if not mask[cy, cx]:
                cy, cx = y_indices[len(y_indices)//2], x_indices[len(x_indices)//2]
                
            objects.append([cx / W, cy / H, float(scores[idx])])
            
        return objects

class SAM2Predictor:
    def __init__(self, device):
        from transformers import Sam2Model, Sam2Processor
        self.device = device
        model_dir = os.path.join(ROOT_DIR, "models", "SAM2")
        
        if not os.path.exists(model_dir):
            raise FileNotFoundError(f"SAM2 Model directory missing at '{model_dir}'.")
            
        self.processor = Sam2Processor.from_pretrained(model_dir)
        self.model = Sam2Model.from_pretrained(model_dir).to(self.device)
        self.image = None
        
    def set_image(self, image_rgb):
        self.image = image_rgb
        
    def predict(self, points, labels, boxes=None):
        # Format points and labels for transformers SAM2
        # input_points: [[[ [x, y], ... ]]] (batch, num_queries, num_points, 2)
        pts = [[[list(p) for p in points]]] if len(points) > 0 else None
        lbls = [[[int(l) for l in labels]]] if len(labels) > 0 else None
        
        # For SAM2 via transformers, input_boxes must be a batched list of boxes
        # e.g., [[[xmin, ymin, xmax, ymax]]]
        box_inputs = [[[list(boxes[0])]]] if boxes else None
        
        inputs = self.processor(
            images=self.image, 
            input_points=pts, 
            input_labels=lbls, 
            input_boxes=box_inputs,
            return_tensors="pt"
        ).to(self.device)
        
        with torch.no_grad():
            outputs = self.model(**inputs)
            
        masks = self.processor.image_processor.post_process_masks(
            outputs.pred_masks.cpu(), 
            inputs["original_sizes"].cpu()
        )
        
        query_masks = masks[0][0].numpy() # (num_masks, H, W)
        scores = outputs.iou_scores[0][0].cpu().numpy() # (num_masks,)
        
        best_mask_idx = -1
        best_score = -1.0
        
        H, W = self.image.shape[:2]
        for i in range(len(scores)):
            mask = query_masks[i] > 0
            score = scores[i]
            
            valid = True
            for (px, py), label in zip(points, labels):
                px, py, label = int(px), int(py), int(label)
                if px < 0 or px >= W or py < 0 or py >= H:
                    continue
                    
                if label == 1 and not mask[py, px]:
                    valid = False
                    break
                if label == 0 and mask[py, px]:
                    valid = False
                    break
                    
            if valid and score > best_score:
                best_score = score
                best_mask_idx = i
                
        if best_mask_idx == -1:
            return np.zeros((H, W), dtype=bool)
            
        best_mask = query_masks[best_mask_idx] > 0
        return best_mask

    def auto_scan(self):
        if self.image is None:
            return []
            
        H, W = self.image.shape[:2]
        inputs = self.processor(
            images=self.image, 
            input_boxes=[[[0, 0, W, H]]],
            return_tensors="pt"
        ).to(self.device)
        
        with torch.no_grad():
            outputs = self.model(**inputs)
            
        masks = self.processor.image_processor.post_process_masks(
            outputs.pred_masks.cpu(), 
            inputs["original_sizes"].cpu()
        )
        
        query_masks = masks[0][0].numpy()
        scores = outputs.iou_scores[0][0].cpu().numpy()
        
        # We can just return the center of the best mask for auto_scan
        # For a full scan, since we passed a single box, it will just segment the main object
        # Better: get the best mask
        best_idx = np.argmax(scores)
        best_mask = query_masks[best_idx] > 0
        
        if not np.any(best_mask):
            return []
            
        y_indices, x_indices = np.where(best_mask)
        cy = int(np.mean(y_indices))
        cx = int(np.mean(x_indices))
        
        if not best_mask[cy, cx]:
            cy, cx = y_indices[len(y_indices)//2], x_indices[len(x_indices)//2]
            
        return [[cx / W, cy / H, float(scores[best_idx])]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="SAM 1 (ViT-H)")
    args = parser.parse_args()
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    try:
        print("READY", flush=True)
        
        if "SAM 3" in args.model:
            predictor = SAM3Predictor(device)
        elif "SAM 2" in args.model:
            predictor = SAM2Predictor(device)
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
            
            if not image_path or not os.path.exists(image_path):
                print(json.dumps({"error": "Invalid image path"}), flush=True)
                continue
                
            image = cv2.imread(image_path)
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            predictor.set_image(image)
            
            if req.get("action") == "auto_scan":
                objects = predictor.auto_scan()
                print(json.dumps({"status": "ok", "objects": objects}), flush=True)
                continue
                
            points = req.get("points", [])
            labels = req.get("labels", [])
            boxes = req.get("boxes", None)
            text_prompt = req.get("text_prompt", "")
            
            if not image_path or not os.path.exists(image_path):
                print(json.dumps({"error": "Invalid image path"}), flush=True)
                continue
                
            image = cv2.imread(image_path)
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            
            # Use GroundingDINO if text_prompt is given and no points/boxes are provided
            if text_prompt and not boxes and not points:
                from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
                global_gdino = getattr(sys.modules[__name__], "gdino", None)
                if global_gdino is None:
                    # Initialize on first use
                    model_id = "IDEA-Research/grounding-dino-base"
                    gdino_processor = AutoProcessor.from_pretrained(model_id)
                    gdino_model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(device)
                    global_gdino = (gdino_processor, gdino_model)
                    setattr(sys.modules[__name__], "gdino", global_gdino)
                
                gd_proc, gd_mod = global_gdino
                inputs = gd_proc(images=image, text=text_prompt, return_tensors="pt").to(device)
                with torch.no_grad():
                    outputs = gd_mod(**inputs)
                results = gd_proc.post_process_grounded_object_detection(
                    outputs,
                    inputs.input_ids,
                    threshold=0.3,
                    text_threshold=0.3,
                    target_sizes=[image.shape[:2]]
                )
                pred_boxes = results[0]["boxes"]
                if len(pred_boxes) > 0:
                    box = pred_boxes[0].cpu().numpy().tolist()
                    boxes = [box]

            pts = np.array(points) if points else np.array([])
            lbls = np.array(labels) if labels else np.array([])
            
            mask = predictor.predict(pts, lbls, boxes)
            
            mask = np.squeeze(mask)
            mask_uint8 = (mask * 255).astype(np.uint8)
            cv2.imwrite(mask_out_path, mask_uint8)
            
            print(json.dumps({"status": "ok"}), flush=True)
            
        except Exception as e:
            print(json.dumps({"error": str(e), "traceback": traceback.format_exc()}), flush=True)

if __name__ == "__main__":
    main()

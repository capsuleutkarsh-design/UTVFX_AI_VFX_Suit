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

class ONNXImageEncoder(torch.nn.Module):
    def __init__(self, onnx_path):
        super().__init__()
        import onnxruntime as ort
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        self.session = ort.InferenceSession(onnx_path, providers=providers)
        self.img_size = 1024
        
    def forward(self, x):
        ort_inputs = {self.session.get_inputs()[0].name: x.cpu().numpy()}
        ort_outs = self.session.run(None, ort_inputs)
        return torch.from_numpy(ort_outs[0]).to(x.device)

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
        
        onnx_encoder_path = os.path.join(ROOT_DIR, "models", "ONNX_Exports", "sam_vit_h_encoder.onnx")
        if os.path.exists(onnx_encoder_path):
            print("Using ONNX Image Encoder for SAM 1...")
            sam.image_encoder = ONNXImageEncoder(onnx_encoder_path)
            
        sam.to(device=device)
        self.predictor = SamPredictor(sam)
        self.image = None
        
    def set_image(self, image_rgb):
        self.image = image_rgb
        self.predictor.set_image(image_rgb)
        
    def predict(self, points, labels, boxes=None):
        
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
        model_dir = os.path.join(ROOT_DIR, "models", "SAM3")
        
        if not os.path.exists(model_dir):
            raise FileNotFoundError(f"SAM3 Model directory missing at '{model_dir}'.")
            
        self.processor = Sam3Processor.from_pretrained(model_dir, local_files_only=True)
        self.model = Sam3Model.from_pretrained(model_dir, local_files_only=True).to(self.device)
        self.image = None
        
    def set_image(self, image_rgb):
        self.image = image_rgb
        
    def predict(self, points, labels, boxes=None):
        H, W = self.image.shape[:2]
        
        kwargs = {"images": self.image, "return_tensors": "pt"}
        
        all_boxes = []
        all_labels = []
        
        if boxes:
            all_boxes.extend(boxes)
            all_labels.extend([1] * len(boxes))
            
        if len(points) > 0:
            for p, l in zip(points, labels):
                # Represent points as 1x1 boxes for SAM3 since it lacks input_points
                all_boxes.append([p[0], p[1], p[0]+1.0, p[1]+1.0])
                all_labels.append(int(l))
                
        if not all_boxes:
            all_boxes = [[0.0, 0.0, float(W), float(H)]]
            all_labels = [1]
            
        kwargs["input_boxes"] = [all_boxes]
        kwargs["input_boxes_labels"] = [all_labels]
            
        inputs = self.processor(**kwargs).to(self.device)
        
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
        
        points = []
        for y in np.linspace(H*0.1, H*0.9, 5):
            for x in np.linspace(W*0.1, W*0.9, 5):
                points.append([[float(x), float(y)]])
                
        inputs = self.processor(
            images=self.image, 
            input_points=[points],
            return_tensors="pt"
        ).to(self.device)
        
        with torch.no_grad():
            outputs = self.model(**inputs)
            
        # Try both post_process functions depending on the transformers version
        if hasattr(self.processor.image_processor, "post_process_masks"):
            masks = self.processor.image_processor.post_process_masks(
                outputs.pred_masks.cpu(), 
                inputs["original_sizes"].cpu(),
                inputs["reshaped_input_sizes"].cpu()
            )
            all_masks = masks[0].reshape(-1, H, W).numpy()
            all_scores = outputs.iou_scores[0].reshape(-1).cpu().numpy()
        else:
            # Fallback for older transformers API
            original_size = inputs["original_sizes"][0].tolist()
            results = self.processor.image_processor.post_process_instance_segmentation(
                outputs, 
                threshold=0.0,
                target_sizes=[(original_size[0], original_size[1])]
            )
            all_masks = results[0]["masks"].cpu().numpy()
            all_scores = results[0]["scores"].cpu().numpy()
        
        top_indices = np.argsort(all_scores)[::-1]
        
        objects = []
        selected_masks = []
        
        for idx in top_indices:
            score = float(all_scores[idx])
            if score < 0.8:
                continue
                
            mask = all_masks[idx] > 0
            if not np.any(mask):
                continue
                
            overlap = False
            for s_mask in selected_masks:
                intersection = np.logical_and(mask, s_mask).sum()
                union = np.logical_or(mask, s_mask).sum()
                if union > 0 and (intersection / union) > 0.6:
                    overlap = True
                    break
            
            if overlap:
                continue
                
            selected_masks.append(mask)
            
            y_indices, x_indices = np.where(mask)
            cy = int(np.mean(y_indices))
            cx = int(np.mean(x_indices))
            
            if not mask[cy, cx]:
                cy, cx = y_indices[len(y_indices)//2], x_indices[len(x_indices)//2]
                
            ymin, ymax = int(np.min(y_indices)), int(np.max(y_indices))
            xmin, xmax = int(np.min(x_indices)), int(np.max(x_indices))
            nx1, ny1 = xmin / W, ymin / H
            nx2, ny2 = xmax / W, ymax / H
                
            objects.append([cx / W, cy / H, score, [nx1, ny1, nx2, ny2]])
            
            if len(objects) >= 15:
                break
                
        return objects

class SamuraiVideoPredictor:
    def __init__(self, device):
        import sys
        import os
        
        samurai_path = os.path.join(ROOT_DIR, "models", "SAMURAI")
        if samurai_path not in sys.path:
            sys.path.append(samurai_path)
            sys.path.append(os.path.join(samurai_path, "sam2"))
            
        from sam2.build_sam import build_sam2_video_predictor
        
        self.device = device
        
        # Load weights and config
        model_path = os.path.join(ROOT_DIR, "models", "SAM2", "sam2.1_hiera_large.pt")
        model_cfg = "configs/samurai/sam2.1_hiera_l.yaml"
        
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"SAM 2.1 weights not found at {model_path}")
            
        self.predictor = build_sam2_video_predictor(model_cfg, model_path, device=self.device)
        self.state = None
        self.image = None # unused for track_video
        
    def set_image(self, image_rgb):
        self.image = image_rgb
        if hasattr(self, "_fallback_predictor"):
            self._fallback_predictor.set_image(image_rgb)
            
    def _get_fallback(self):
        if not hasattr(self, "_fallback_predictor"):
            self._fallback_predictor = SAM2Predictor(self.device)
            if self.image is not None:
                self._fallback_predictor.set_image(self.image)
        return self._fallback_predictor
        
    def auto_scan(self):
        return self._get_fallback().auto_scan()
        
    def predict(self, points, labels, boxes=None):
        return self._get_fallback().predict(points, labels, boxes)

    def track_video(self, frames_dir, start_frame_idx, prompts, out_dir):
        import torch
        import cv2
        import numpy as np
        
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
            # Group prompts by obj_id to avoid SAMURAI's batching bug
            prompts_by_obj = {}
            for p in prompts:
                obj_id = p.get("obj_id", 0)
                if obj_id not in prompts_by_obj:
                    prompts_by_obj[obj_id] = []
                prompts_by_obj[obj_id].append(p)
                
            for obj_id, obj_prompts in prompts_by_obj.items():
                self.state = self.predictor.init_state(frames_dir, offload_video_to_cpu=True)
                
                # Reset SAMURAI's internal Kalman filter which doesn't support batching properly
                if hasattr(self.predictor, 'kf_mean'):
                    self.predictor.kf_mean = None
                    self.predictor.kf_covariance = None
                    self.predictor.stable_frames = 0
                    
                for p in obj_prompts:
                    f_idx = p.get("frame", 0)
                    
                    points = p.get("points")
                    labels = p.get("labels")
                    box = p.get("box")
                    
                    box_np = np.array(box, dtype=np.float32) if box else None
                    pts_np = np.array(points, dtype=np.float32) if points else None
                    lbls_np = np.array(labels, dtype=np.int32) if labels else None
                    
                    clear_pts = True if box is not None else False
                    
                    # SAMURAI's motion-aware memory requires bounding boxes to initialize the Kalman Filter.
                    # If the user only provides points, SAMURAI will fail to track or shrink to nothing.
                    # By disabling samurai_mode when box is None, we gracefully fall back to standard SAM 2 point tracking.
                    if box is None:
                        if hasattr(self.predictor, 'samurai_mode'):
                            self.predictor.samurai_mode = False
                    else:
                        if hasattr(self.predictor, 'samurai_mode'):
                            self.predictor.samurai_mode = True
                    
                    self.predictor.add_new_points_or_box(
                        self.state,
                        frame_idx=f_idx,
                        obj_id=obj_id,
                        points=pts_np,
                        labels=lbls_np,
                        box=box_np,
                        clear_old_points=clear_pts
                    )
                
                # Forward propagation
                for frame_idx, object_ids, masks in self.predictor.propagate_in_video(self.state, reverse=False):
                    for out_obj_id, mask in zip(object_ids, masks):
                        mask_np = mask[0].cpu().numpy()
                        mask_uint8 = (mask_np > 0.0).astype(np.uint8) * 255
                        
                        out_path = os.path.join(out_dir, f"sam_mask_{out_obj_id}_{frame_idx:06d}.png")
                        cv2.imwrite(out_path, mask_uint8)
                        
                # Backward propagation
                for frame_idx, object_ids, masks in self.predictor.propagate_in_video(self.state, reverse=True):
                    for out_obj_id, mask in zip(object_ids, masks):
                        mask_np = mask[0].cpu().numpy()
                        mask_uint8 = (mask_np > 0.0).astype(np.uint8) * 255
                        
                        out_path = os.path.join(out_dir, f"sam_mask_{out_obj_id}_{frame_idx:06d}.png")
                        cv2.imwrite(out_path, mask_uint8)
                    
                    
        return True

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
        pts = [[[[float(c) for c in p] for p in points]]] if len(points) > 0 else None
        lbls = [[[int(l) for l in labels]]] if len(labels) > 0 else None
        
        # For SAM2 via transformers, input_boxes must be a batched list of boxes
        # e.g., [[[xmin, ymin, xmax, ymax]]]
        box_inputs = [[[float(c) for c in box] for box in boxes]] if boxes else None
        
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
        
        points = []
        for y in np.linspace(H*0.1, H*0.9, 5):
            for x in np.linspace(W*0.1, W*0.9, 5):
                points.append([[float(x), float(y)]])
                
        inputs = self.processor(
            images=self.image, 
            input_points=[points],
            return_tensors="pt"
        ).to(self.device)
        
        with torch.no_grad():
            outputs = self.model(**inputs)
            
        masks = self.processor.image_processor.post_process_masks(
            outputs.pred_masks.cpu(), 
            inputs["original_sizes"].cpu(),
            inputs["reshaped_input_sizes"].cpu()
        )
        
        all_masks = masks[0].reshape(-1, H, W).numpy()
        all_scores = outputs.iou_scores[0].reshape(-1).cpu().numpy()
        
        top_indices = np.argsort(all_scores)[::-1]
        
        objects = []
        selected_masks = []
        
        for idx in top_indices:
            score = float(all_scores[idx])
            if score < 0.8:
                continue
                
            mask = all_masks[idx] > 0
            if not np.any(mask):
                continue
                
            overlap = False
            for s_mask in selected_masks:
                intersection = np.logical_and(mask, s_mask).sum()
                union = np.logical_or(mask, s_mask).sum()
                if union > 0 and (intersection / union) > 0.6:
                    overlap = True
                    break
            
            if overlap:
                continue
                
            selected_masks.append(mask)
            
            y_indices, x_indices = np.where(mask)
            cy = int(np.mean(y_indices))
            cx = int(np.mean(x_indices))
            
            if not mask[cy, cx]:
                cy, cx = y_indices[len(y_indices)//2], x_indices[len(x_indices)//2]
                
            ymin, ymax = int(np.min(y_indices)), int(np.max(y_indices))
            xmin, xmax = int(np.min(x_indices)), int(np.max(x_indices))
            nx1, ny1 = xmin / W, ymin / H
            nx2, ny2 = xmax / W, ymax / H
                
            objects.append([cx / W, cy / H, score, [nx1, ny1, nx2, ny2]])
            
            if len(objects) >= 15:
                break
                
        return objects


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="SAM 1 (ViT-H)")
    args = parser.parse_args()
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    try:
        if "SAM 3" in args.model:
            predictor = SAM3Predictor(device)
        elif "SAM 2 (SAMURAI)" in args.model or "SAM 2" in args.model:
            predictor = SamuraiVideoPredictor(device)
        else:
            predictor = SAM1Predictor(device)
            
        print("READY", flush=True)
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
                
            if req.get("action") == "track_video":
                frames_dir = req.get("frames_dir")
                start_frame_idx = req.get("start_frame_idx")
                prompts = req.get("prompts")
                out_dir = req.get("out_dir")
                
                try:
                    predictor.track_video(frames_dir, start_frame_idx, prompts, out_dir)
                    print(json.dumps({"status": "ok"}), flush=True)
                except Exception as e:
                    print(json.dumps({"error": str(e), "traceback": traceback.format_exc()}), flush=True)
                continue
                
            image_path = req.get("image_path")
            
            if not image_path or not os.path.exists(image_path):
                print(json.dumps({"error": "Invalid image path"}), flush=True)
                continue
                
            image = cv2.imread(image_path)
            if image is None:
                print(json.dumps({"error": f"Failed to read image at {image_path}"}), flush=True)
                continue
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            predictor.set_image(image)
            
            if req.get("action") == "auto_scan":
                text_prompt = req.get("text_prompt", "")
                if text_prompt:
                    from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
                    global_gdino = getattr(sys.modules[__name__], "gdino", None)
                    if global_gdino is None:
                        model_dir = os.path.join(ROOT_DIR, "models", "GroundingDINO")
                        if os.path.exists(model_dir):
                            model_id = model_dir
                        else:
                            model_id = "IDEA-Research/grounding-dino-base"
                        gdino_processor = AutoProcessor.from_pretrained(model_id)
                        gdino_model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(device)
                        global_gdino = (gdino_processor, gdino_model)
                        setattr(sys.modules[__name__], "gdino", global_gdino)
                    
                    gd_proc, gd_mod = global_gdino
                    
                    if not text_prompt.endswith("."):
                        text_prompt += "."
                        
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
                    pred_boxes = results[0]["boxes"].cpu().numpy()
                    pred_scores = results[0]["scores"].cpu().numpy()
                    
                    objects = []
                    H, W = image.shape[:2]
                    for box, score in zip(pred_boxes, pred_scores):
                        cx = (box[0] + box[2]) / 2.0 / W
                        cy = (box[1] + box[3]) / 2.0 / H
                        nx1, ny1, nx2, ny2 = float(box[0]/W), float(box[1]/H), float(box[2]/W), float(box[3]/H)
                        objects.append([float(cx), float(cy), float(score), [nx1, ny1, nx2, ny2]])
                else:
                    objects = predictor.auto_scan()
                print(json.dumps({"status": "ok", "objects": objects}), flush=True)
                continue
                
            points = req.get("points", [])
            labels = req.get("labels", [])
            boxes = req.get("boxes", None)
            text_prompt = req.get("text_prompt", "")
            mask_out_path = req.get("mask_out_path", "")
            
            # Use GroundingDINO if text_prompt is given and no points/boxes are provided
            if text_prompt and not boxes and not points:
                from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
                global_gdino = getattr(sys.modules[__name__], "gdino", None)
                if global_gdino is None:
                    # Initialize on first use
                    model_dir = os.path.join(ROOT_DIR, "models", "GroundingDINO")
                    if os.path.exists(model_dir):
                        model_id = model_dir
                    else:
                        model_id = "IDEA-Research/grounding-dino-base"
                    gdino_processor = AutoProcessor.from_pretrained(model_id)
                    gdino_model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(device)
                    global_gdino = (gdino_processor, gdino_model)
                    setattr(sys.modules[__name__], "gdino", global_gdino)
                
                gd_proc, gd_mod = global_gdino
                
                if not text_prompt.endswith("."):
                    text_prompt += "."
                    
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
                    boxes = pred_boxes.cpu().numpy().tolist()

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

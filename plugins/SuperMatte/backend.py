"""SuperMatte: SAM segmentation refined into soft mattes.

Stages
  1. Frames    which plate frames to render (In/Out range) and how to read them.
  2. Masks     a hard SAM mask per layer per frame, either
               - SAMURAI video tracking (memory across frames, forward and backward), or
               - per-frame SAM 1 / SAM 3 with clicks carried between frames by optical
                 flow, forward from the first clicked frame and backward before it.
  3. Refine    ViTMatte / MEMatte per frame (or VideoMaMa per chunk of frames) turns the
               hard masks into soft alpha, then the edge controls and optional temporal
               stabilisation are applied.
  4. Write     Matte/matte_<frame>.png and alpha/<layer>/alpha_<frame>.png as 16-bit
               PNG (no banding on soft edges), Comp/comp_<frame>.png as an 8-bit preview.

Clicks are keyed by timeline position (0 = first plate frame); plate frame numbers
only appear in output file names.
"""
import os
import shutil

import cv2
import numpy as np

from utvfx.bridge.base_worker import BaseWorker

MAX_REFINE_DIM = 2048  # ViTMatte/MEMatte run at most this size; larger plates get a guided upscale
VIDEOMAMA_SIZE = (1024, 576)
VIDEOMAMA_CHUNK = 8


def _to_prompts(pts_data, w, h):
    """Normalised clicks/boxes -> pixel points, labels and boxes for SAM."""
    points, labels, boxes = [], [], []
    for p in pts_data or []:
        if len(p) == 3:
            nx, ny, positive = p
            points.append([nx * w, ny * h])
            labels.append(1 if positive else 0)
        elif len(p) == 5:
            x1, y1, x2, y2, _ = p
            boxes.append([x1 * w, y1 * h, x2 * w, y2 * h])
    return points, labels, boxes


def _keyframes(layer):
    return {int(k): v for k, v in (layer.get("keyframes") or {}).items() if v}


def _write_alpha16(path, alpha):
    cv2.imwrite(path, (np.clip(alpha, 0.0, 1.0) * 65535.0 + 0.5).astype(np.uint16))


class _Frames:
    """The plate as a list of timeline positions: frame numbers, display frames and file paths SAM can read."""

    def __init__(self, media_path, work_dir, log):
        from utvfx.core.plate import find_sequence, plate_for_folder

        self.work_dir = work_dir
        self.log = log
        self._cap = None
        self._video_frames = []
        self.plate = plate_for_folder(media_path) if media_path and os.path.isdir(media_path) else None
        if media_path and (os.path.isdir(media_path) or os.path.splitext(media_path)[1].lower() in
                           (".png", ".jpg", ".jpeg", ".exr", ".dpx", ".tif", ".tiff", ".hdr")):
            seq = find_sequence(media_path)
            if not seq:
                raise Exception("No image files found in the plate folder.")
            self.numbers = [n for n, _ in seq]
            self.files = [p for _, p in seq]
            self.kind = "sequence"
        elif media_path and os.path.isfile(media_path):
            self._cap = cv2.VideoCapture(media_path)
            if not self._cap.isOpened():
                raise Exception(f"Cannot open {media_path}.")
            count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.numbers = list(range(1, count + 1))
            self.files = [None] * count
            self.kind = "video"
        else:
            raise Exception("No plate is connected to SuperMatte.")

    def __len__(self):
        return len(self.numbers)

    def read(self, pos):
        """Display-referred BGR uint8 frame at timeline position `pos`."""
        if self.kind == "video":
            path = self.sam_path(pos)
            frame = cv2.imread(path, cv2.IMREAD_COLOR)
        else:
            from utvfx.core.image_utils import load_frame
            frame = load_frame(self.files[pos])
            if frame is not None and frame.ndim == 3 and frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        if frame is None:
            raise Exception(f"Could not read plate frame {self.numbers[pos]}.")
        return frame

    def sam_path(self, pos):
        """A PNG/JPG/TIFF file for this frame that the SAM engine can open."""
        path = self.files[pos]
        if path and path.lower().endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff")):
            return path
        out = os.path.join(self.work_dir, "frames", f"frame_{self.numbers[pos]:06d}.png")
        if not os.path.exists(out):
            os.makedirs(os.path.dirname(out), exist_ok=True)
            if self.kind == "video":
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                ok, frame = self._cap.read()
                if not ok:
                    raise Exception(f"Could not read video frame {self.numbers[pos]}.")
            else:
                frame = self.read(pos)
            cv2.imwrite(out, frame)
        return out

    def jpg_folder(self, positions, cancelled):
        """A folder of 00000.jpg, 00001.jpg ... for `positions` (SAMURAI can only read that)."""
        folder = os.path.join(self.work_dir, "samurai_frames")
        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder)
        tier = None
        if self.plate is not None:
            self.plate.ensure("jpg", cancelled=cancelled)
            tier = self.plate.paths("jpg")
        for k, pos in enumerate(positions):
            if cancelled():
                return None
            dst = os.path.join(folder, f"{k:05d}.jpg")
            if tier is not None:
                try:
                    os.link(tier[pos], dst)  # no copy on the same drive
                    continue
                except OSError:
                    pass
                shutil.copy2(tier[pos], dst)
            else:
                cv2.imwrite(dst, self.read(pos), [cv2.IMWRITE_JPEG_QUALITY, 95,
                                                  cv2.IMWRITE_JPEG_SAMPLING_FACTOR, cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444])
        return folder

    def close(self):
        if self._cap is not None:
            self._cap.release()


class SuperMatteWorker(BaseWorker):
    def __init__(self, node_id, params, inputs, cache_dir, output_dir, parent=None):
        super().__init__(node_id, params, inputs, cache_dir, output_dir, parent)
        # The ExecutionEngine resolves the wired plate into inputs["Video Plate"].
        self.media_path = inputs.get("Video Plate")

    # ---- small image helpers ------------------------------------------------
    def track_points_pyrlk(self, img1, img2, pts_nxny):
        """Carry clicks from img1 to img2 with Lucas-Kanade optical flow (boxes pass through)."""
        if not pts_nxny:
            return []
        h, w = img1.shape[:2]
        idx = [i for i, p in enumerate(pts_nxny) if len(p) == 3]
        if not idx:
            return list(pts_nxny)
        p0 = np.array([[[pts_nxny[i][0] * w, pts_nxny[i][1] * h]] for i in idx], dtype=np.float32)
        lk = dict(winSize=(31, 31), maxLevel=4, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
        p1, st, _ = cv2.calcOpticalFlowPyrLK(img1, img2, p0, None, **lk)
        out = list(pts_nxny)
        for j, i in enumerate(idx):
            if st[j][0] == 1:
                out[i] = (float(p1[j][0][0]) / w, float(p1[j][0][1]) / h, pts_nxny[i][2])
        return out

    def generate_trimap(self, mask_uint8, erode_kernel_size, dilate_kernel_size):
        """Adaptive trimap: a wider unknown band where the SAM edge is complex."""
        dist_fg = cv2.distanceTransform(mask_uint8, cv2.DIST_L2, 3)
        dist_bg = cv2.distanceTransform(cv2.bitwise_not(mask_uint8), cv2.DIST_L2, 3)
        grad = cv2.magnitude(cv2.Sobel(mask_uint8, cv2.CV_32F, 1, 0, ksize=5), cv2.Sobel(mask_uint8, cv2.CV_32F, 0, 1, ksize=5))
        grad = cv2.normalize(grad, None, 0, 1, cv2.NORM_MINMAX)
        grad = cv2.dilate(grad, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
        trimap = np.full(mask_uint8.shape, 128, dtype=np.uint8)
        trimap[dist_bg > (dilate_kernel_size / 2.0) * (1.0 + grad * 2.0)] = 0
        trimap[dist_fg > (erode_kernel_size / 2.0) * (1.0 + grad * 2.0)] = 255
        return trimap

    def run_vitmatte(self, frame, sam_mask, use_mematte, use_onnx, model, processor, ort_session, erode_size, dilate_size, device):
        """Hard SAM mask -> soft alpha (float32 0-1) at the frame's full size."""
        import torch
        from PIL import Image

        if self.params.get("fill_holes", False):
            sam_mask = cv2.morphologyEx(sam_mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        trimap = self.generate_trimap(sam_mask, erode_size, dilate_size)

        orig_h, orig_w = frame.shape[:2]
        scale = min(1.0, MAX_REFINE_DIM / float(max(orig_w, orig_h)))
        if scale < 1.0:
            size = (int(orig_w * scale), int(orig_h * scale))
            infer_frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
            infer_trimap = cv2.resize(trimap, size, interpolation=cv2.INTER_NEAREST)
        else:
            infer_frame, infer_trimap = frame, trimap
        infer_h, infer_w = infer_frame.shape[:2]

        if use_mematte:
            rgb = cv2.cvtColor(infer_frame, cv2.COLOR_BGR2RGB)
            img_t = torch.from_numpy(rgb).permute(2, 0, 1).float().unsqueeze(0).to(device) / 255.0
            tri_t = torch.from_numpy(infer_trimap).unsqueeze(0).unsqueeze(0).float().to(device) / 255.0
            with torch.no_grad():
                raw = model({"image": img_t, "trimap": tri_t})

            def find_phas(obj):
                if isinstance(obj, dict) and "phas" in obj:
                    return obj["phas"]
                if isinstance(obj, (list, tuple)):
                    for item in obj:
                        found = find_phas(item)
                        if found is not None:
                            return found
                return None

            phas = find_phas(raw)
            if phas is None:
                raise RuntimeError("MEMatte returned no alpha ('phas').")
            alpha = phas[0, 0].float().cpu().numpy()
        else:
            image_pil = Image.fromarray(cv2.cvtColor(infer_frame, cv2.COLOR_BGR2RGB))
            trimap_pil = Image.fromarray(infer_trimap).convert("L")
            if use_onnx:
                inputs = processor(images=image_pil, trimaps=trimap_pil, return_tensors="np")
                alpha = ort_session.run(None, {"pixel_values": inputs["pixel_values"]})[0][0, 0]
            else:
                inputs = {k: v.to(device) for k, v in processor(images=image_pil, trimaps=trimap_pil, return_tensors="pt").items()}
                with torch.no_grad():
                    alpha = model(**inputs).alphas[0, 0].float().cpu().numpy()

        # ViTMatte pads its input to a multiple of 32 (1080 -> 1088): crop back to the real frame.
        alpha = np.clip(alpha[:infer_h, :infer_w].astype(np.float32), 0.0, 1.0)

        # Keep the certain regions exactly as the trimap says.
        alpha[infer_trimap == 0] = 0.0
        alpha[infer_trimap == 255] = 1.0

        if scale < 1.0:
            alpha = self._guided_upscale(alpha, frame, trimap)
        return alpha

    @staticmethod
    def _guided_upscale(alpha_small, frame, trimap):
        """Upscale a matte refined at 2K using the full-resolution plate as a guide.

        A plain resize softens 4K hair to 2K; the guided filter snaps the upscaled edge
        to the real image edges. Only the unknown band of the trimap is changed.
        """
        h, w = frame.shape[:2]
        alpha = cv2.resize(alpha_small, (w, h), interpolation=cv2.INTER_LINEAR)
        guide = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        try:
            refined = cv2.ximgproc.guidedFilter(guide, alpha, 4, 1e-4)
        except AttributeError:
            return alpha
        unknown = trimap == 128
        alpha[unknown] = np.clip(refined[unknown], 0.0, 1.0)
        return alpha

    def _post_process_alpha(self, alpha, threshold, contrast, shrink_grow, feathering):
        """Edge controls on a float matte (threshold/contrast are on the old 0-255 / % scales)."""
        alpha = alpha.astype(np.float32)
        if shrink_grow:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (abs(int(shrink_grow)), abs(int(shrink_grow))))
            alpha = cv2.dilate(alpha, k) if shrink_grow > 0 else cv2.erode(alpha, k)
        if contrast != 100 or threshold != 128:
            alpha = np.clip((alpha - threshold / 255.0) * (contrast / 100.0) + 0.5, 0.0, 1.0)
        if feathering > 0:
            k = int(feathering) | 1
            alpha = cv2.GaussianBlur(alpha, (k, k), 0)
        return alpha

    @staticmethod
    def _stabilise(alpha, prev_alpha, gray, prev_gray):
        """Blend with the previous frame's matte, moved to where the image moved.

        The flow is computed from the current frame to the previous one, so sampling the
        previous matte along it lines that matte up with the current frame.
        """
        flow = cv2.calcOpticalFlowFarneback(gray, prev_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        h, w = gray.shape
        gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        warped = cv2.remap(prev_alpha, gx + flow[..., 0], gy + flow[..., 1], cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_REPLICATE)
        return 0.6 * alpha + 0.4 * warped

    # ---- stage 1: refiner ----------------------------------------------------
    def _load_refiner(self, refiner_mode, device):
        from utvfx.core.settings_manager import SettingsManager
        models_dir = SettingsManager().models_dir
        r = {"mode": refiner_mode, "onnx": False, "mematte": False, "videomama": None,
             "model": None, "processor": None, "ort": None}
        try:
            if refiner_mode.startswith("VideoMaMa"):
                import transformers.utils
                if not hasattr(transformers.utils, "FLAX_WEIGHTS_NAME"):
                    transformers.utils.FLAX_WEIGHTS_NAME = "flax_model.msgpack"  # diffusers vs newer transformers
                from plugins.CorridorKey.System.VideoMaMaInferenceModule.inference import load_videomama_model
                vm = os.path.join(models_dir, "VideoMaMa")
                r["videomama"] = load_videomama_model(
                    base_model_path=os.path.join(vm, "stable-video-diffusion-img2vid-xt"),
                    unet_checkpoint_path=vm, device=device)
            elif refiner_mode.startswith("MEMatte"):
                import sys
                if models_dir not in sys.path:
                    sys.path.insert(0, models_dir)
                from MEMatte.mematte_loader import load_mematte
                r["model"] = load_mematte(device=device).eval()
                r["mematte"] = True
            else:
                from transformers import VitMatteForImageMatting, VitMatteImageProcessor
                model_dir = os.path.join(models_dir, "ViTMatte")
                r["processor"] = VitMatteImageProcessor.from_pretrained(model_dir)
                onnx_path = os.path.join(models_dir, "ONNX_Exports", "vitmatte_base.onnx")
                if os.path.exists(onnx_path):
                    import onnxruntime as ort
                    r["ort"] = ort.InferenceSession(onnx_path, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
                    r["onnx"] = True
                else:
                    r["model"] = VitMatteForImageMatting.from_pretrained(model_dir, use_safetensors=True).to(device).eval()
        except Exception as e:
            raise Exception(f"Failed to load the {refiner_mode} refiner: {e}")
        return r

    # ---- stage 2: masks ------------------------------------------------------
    def _samurai_masks(self, frames, positions, layers, mask_dir, client, sam_version):
        folder = frames.jpg_folder(positions, lambda: self.is_cancelled)
        if folder is None:
            return
        first = cv2.imread(os.path.join(folder, "00000.jpg"))
        h, w = first.shape[:2]
        index = {pos: k for k, pos in enumerate(positions)}
        prompts, skipped = [], 0
        for obj_id, layer in enumerate(layers):
            for pos, data in _keyframes(layer).items():
                if pos not in index:
                    skipped += 1
                    continue
                points, labels, boxes = _to_prompts(data, w, h)
                if points or boxes:
                    prompts.append({"frame": index[pos], "obj_id": obj_id, "points": points or None,
                                    "labels": labels or None, "box": boxes[0] if boxes else None})
        if skipped:
            self.log_message.emit(self.node_id, f"{skipped} clicked frame(s) are outside the In/Out range and were ignored.")
        if not prompts:
            raise Exception("No clicks or boxes inside the frame range. Add points in the viewer first.")

        self.log_message.emit(self.node_id, f"SAMURAI video tracking over {len(positions)} frames...")
        track_dir = os.path.join(mask_dir, "samurai")
        os.makedirs(track_dir, exist_ok=True)
        if not client.track_video(folder, 0, prompts, track_dir, sam_version):
            if self.is_cancelled:
                return
            raise Exception(f"SAMURAI tracking failed: {client.last_error or 'no reason given'}")
        for obj_id, layer in enumerate(layers):
            for k, pos in enumerate(positions):
                src = os.path.join(track_dir, f"sam_mask_{obj_id}_{k:06d}.png")
                dst = self._mask_path(mask_dir, layer, pos)
                if os.path.exists(src):
                    os.replace(src, dst)
                else:
                    cv2.imwrite(dst, np.zeros((h, w), np.uint8))  # the object was not found on this frame

    def _per_frame_masks(self, frames, positions, layers, mask_dir, client, sam_version):
        """SAM on each frame; clicks carried by optical flow forward and backward from the first key."""
        keys = [_keyframes(layer) for layer in layers]
        in_range = sorted({p for k in keys for p in k if p in positions})
        anchor = in_range[0] if in_range else None
        if anchor is None:
            before = sorted({p for k in keys for p in k if p < positions[0]})
            if not before:
                raise Exception("No clicks or boxes at or before the frame range. Add points in the viewer first.")
            anchor = before[-1]  # carry the last clicks before In forward into the range
        ordered = [p for p in positions if p >= anchor] + [p for p in reversed(positions) if p < anchor]
        total = len(ordered)

        def pass_over(sequence, start_points):
            points = list(start_points)
            prev_gray = None
            prev_pos = None
            for pos in sequence:
                if self.is_cancelled:
                    return
                frame = frames.read(pos)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                h, w = gray.shape
                for li, layer in enumerate(layers):
                    if pos in keys[li]:
                        points[li] = keys[li][pos]
                    elif prev_gray is not None and prev_pos is not None:
                        points[li] = self.track_points_pyrlk(prev_gray, gray, points[li])
                    out = self._mask_path(mask_dir, layer, pos)
                    pts, labels, boxes = _to_prompts(points[li], w, h)
                    if not pts and not boxes:
                        cv2.imwrite(out, np.zeros((h, w), np.uint8))
                        continue
                    qimage = client.query_mask(image_path=frames.sam_path(pos), points=pts, labels=labels,
                                               fill_color_hex="#ffffff", out_mask_path=out, sam_version=sam_version,
                                               text_prompt=self.params.get("text_prompt", ""), boxes=boxes or None)
                    if qimage is None or not os.path.exists(out):
                        if self.is_cancelled:
                            return
                        raise Exception(f"SAM failed on {layer.get('name', 'layer')}, frame {frames.numbers[pos]}: "
                                        f"{client.last_error or 'no mask was written'}")
                prev_gray, prev_pos = gray, pos
                self.done += 1
                self.progress_update.emit(self.node_id, self.done, self.total_steps)

        start_points = [keys[li].get(anchor, []) for li in range(len(layers))]
        forward = [p for p in ordered if p >= anchor]
        backward = [p for p in ordered if p < anchor]
        pass_over(forward, start_points)
        if backward and not self.is_cancelled:
            pass_over([anchor] + backward, start_points)  # re-seed at the anchor, then walk back

    @staticmethod
    def _mask_path(mask_dir, layer, pos):
        return os.path.join(mask_dir, f"{layer['id']}_{pos:06d}.png")

    # ---- stage 3 + 4: refine and write ---------------------------------------
    def _refine_and_write(self, frames, positions, layers, mask_dir, refiner, device, out_dirs):
        erode = self.params.get("trimap_erode", 10)
        dilate = self.params.get("trimap_dilate", 10)
        edge = (self.params.get("threshold", 128), self.params.get("contrast", 100),
                self.params.get("shrink_grow", 0), self.params.get("feathering", 0))
        smooth = self.params.get("temporal_smoothing", False)
        bg = self.params.get("bg_color", "#6aff9b").lstrip("#")
        bg_bgr = tuple(int(bg[i:i + 2], 16) for i in (4, 2, 0))
        prev = None  # (raw combined alpha, gray) of the previous frame, for stabilisation

        for pos in positions:
            if self.is_cancelled:
                return
            frame = frames.read(pos)
            number = frames.numbers[pos]
            masks = [cv2.imread(self._mask_path(mask_dir, layer, pos), cv2.IMREAD_GRAYSCALE) for layer in layers]
            masks = [m if m is not None else np.zeros(frame.shape[:2], np.uint8) for m in masks]
            combined_mask = np.maximum.reduce(masks) if masks else np.zeros(frame.shape[:2], np.uint8)

            def refine(mask):
                return self.run_vitmatte(frame, mask, refiner["mematte"], refiner["onnx"], refiner["model"],
                                         refiner["processor"], refiner["ort"], erode, dilate, device)

            for layer, mask in zip(layers, masks):
                if len(layers) > 1:
                    layer_alpha = refine(mask)
                    self._write_layer(out_dirs["alpha"], layer, number, self._post_process_alpha(layer_alpha, *edge))
            raw = refine(combined_mask)
            if len(layers) == 1:
                self._write_layer(out_dirs["alpha"], layers[0], number, self._post_process_alpha(raw, *edge))

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            alpha = raw
            if smooth and prev is not None and prev[0].shape == raw.shape:
                alpha = self._stabilise(raw, prev[0], gray, prev[1])
            prev = (raw, gray)  # stabilise against the raw matte, not the already-smoothed one
            alpha = self._post_process_alpha(alpha, *edge)
            self._write_outputs(out_dirs, number, frame, alpha, bg_bgr)
            self.done += 1
            self.progress_update.emit(self.node_id, self.done, self.total_steps)

    def _refine_videomama(self, frames, positions, layers, mask_dir, refiner, out_dirs):
        """VideoMaMa in chunks read from disk (bounded memory), padded to 16:9 so nothing is squashed."""
        from PIL import Image

        pipeline = refiner["videomama"]
        edge = (self.params.get("threshold", 128), self.params.get("contrast", 100),
                self.params.get("shrink_grow", 0), self.params.get("feathering", 0))
        bg = self.params.get("bg_color", "#6aff9b").lstrip("#")
        bg_bgr = tuple(int(bg[i:i + 2], 16) for i in (4, 2, 0))
        targets = [None] + (list(layers) if len(layers) > 1 else [])  # None = combined matte

        for start in range(0, len(positions), VIDEOMAMA_CHUNK):
            if self.is_cancelled:
                return
            chunk = positions[start:start + VIDEOMAMA_CHUNK]
            rgb = [cv2.cvtColor(frames.read(p), cv2.COLOR_BGR2RGB) for p in chunk]
            h, w = rgb[0].shape[:2]
            target_w, target_h = VIDEOMAMA_SIZE
            pad_w = max(w, int(round(h * target_w / target_h)))
            pad_h = max(h, int(round(w * target_h / target_w)))

            def pad(img):
                return cv2.copyMakeBorder(img, 0, pad_h - h, 0, pad_w - w, cv2.BORDER_REPLICATE)

            cond = [Image.fromarray(pad(f)).resize(VIDEOMAMA_SIZE, Image.Resampling.BILINEAR) for f in rgb]
            for target in targets:
                layer_masks = []
                for p in chunk:
                    ms = [cv2.imread(self._mask_path(mask_dir, l, p), cv2.IMREAD_GRAYSCALE) for l in ([target] if target else layers)]
                    ms = [m for m in ms if m is not None]
                    layer_masks.append(np.maximum.reduce(ms) if ms else np.zeros((h, w), np.uint8))
                mask_pil = [Image.fromarray(pad(m), mode="L").resize(VIDEOMAMA_SIZE, Image.Resampling.BILINEAR) for m in layer_masks]
                out = pipeline.run(cond_frames=cond, mask_frames=mask_pil, seed=42, mask_cond_mode="vae")
                for p, frame_rgb, img in zip(chunk, rgb, out):
                    a = np.asarray(img.resize((pad_w, pad_h), Image.Resampling.BILINEAR).convert("L"), np.float32) / 255.0
                    a = self._post_process_alpha(a[:h, :w], *edge)
                    if target is None:
                        self._write_outputs(out_dirs, frames.numbers[p], cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR), a, bg_bgr)
                        if len(layers) == 1:
                            self._write_layer(out_dirs["alpha"], layers[0], frames.numbers[p], a)
                    else:
                        self._write_layer(out_dirs["alpha"], target, frames.numbers[p], a)
            self.done += len(chunk)
            self.progress_update.emit(self.node_id, self.done, self.total_steps)

    @staticmethod
    def _write_layer(alpha_dir, layer, number, alpha):
        folder = os.path.join(alpha_dir, layer.get("name", "Layer").replace(" ", "_"))
        os.makedirs(folder, exist_ok=True)
        _write_alpha16(os.path.join(folder, f"alpha_{number:06d}.png"), alpha)

    @staticmethod
    def _write_outputs(out_dirs, number, frame, alpha, bg_bgr):
        _write_alpha16(os.path.join(out_dirs["matte"], f"matte_{number:06d}.png"), alpha)
        a = alpha[..., None]
        comp = frame.astype(np.float32) * a + np.array(bg_bgr, np.float32) * (1.0 - a)
        cv2.imwrite(os.path.join(out_dirs["comp"], f"comp_{number:06d}.png"), np.clip(comp + 0.5, 0, 255).astype(np.uint8))

    # ---- entry point ---------------------------------------------------------
    def run_task(self):
        self.log_message.emit(self.node_id, "Initializing Super Matte Pipeline...")
        layers = [l for l in self.params.get("mask_layers", []) if l.get("enabled", True)]  # eye toggle
        if not layers:
            self.log_message.emit(self.node_id, "No visible mask layers. Nothing to render.")
            return
        if not any(_keyframes(l) for l in layers):
            raise Exception("No prompt points defined in any layer. Add points in the UI.")

        sam_version = self.params.get("sam_version", "SAM 1 (ViT-H)")
        refiner_mode = self.params.get("refiner_model", "ViTMatte")
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
        self.log_message.emit(self.node_id, f"Segmenter: {sam_version}. Refiner: {refiner_mode}.")

        out_dirs = {name: os.path.join(self.cache_dir, folder)
                    for name, folder in (("matte", "Matte"), ("comp", "Comp"), ("alpha", "alpha"))}
        mask_dir = os.path.join(self.cache_dir, "sam_masks")
        for folder in list(out_dirs.values()) + [mask_dir]:
            shutil.rmtree(folder, ignore_errors=True)  # never mix frames from an older render
            os.makedirs(folder)

        frames = _Frames(self.media_path, self.cache_dir, self.log_message)
        try:
            positions = list(self.positions(len(frames)))
            if not positions:
                raise Exception("The In/Out range is empty.")
            self.total_steps = len(positions) * 2
            self.done = 0

            from utvfx.bridge.ai_bridge_client import AIBridgeClient
            client = AIBridgeClient.get_instance()
            if "SAM 2" in sam_version:
                self._samurai_masks(frames, positions, layers, mask_dir, client, sam_version)
                self.done = len(positions)
            else:
                self._per_frame_masks(frames, positions, layers, mask_dir, client, sam_version)
            if self.is_cancelled:
                return

            self.log_message.emit(self.node_id, "Refining mattes...")
            refiner = self._load_refiner(refiner_mode, device)
            if refiner["videomama"] is not None:
                self._refine_videomama(frames, positions, layers, mask_dir, refiner, out_dirs)
            else:
                self._refine_and_write(frames, positions, layers, mask_dir, refiner, device, out_dirs)
        finally:
            frames.close()
        if not self.is_cancelled:
            first, last = frames.numbers[positions[0]], frames.numbers[positions[-1]]
            self.log_message.emit(self.node_id, f"Super Matte done: frames {first}-{last}, 16-bit mattes.")


def run_fast_preview(params, frame_idx, points, frame_path):
    """One SAM mask for the viewer while the user clicks."""
    from utvfx.bridge.ai_bridge_client import AIBridgeClient
    from utvfx.core.settings_manager import SettingsManager
    import uuid

    if not points:
        return None
    img = cv2.imread(frame_path)
    if img is None:
        return None
    h, w = img.shape[:2]
    pts, labels, boxes = _to_prompts(points, w, h)
    out_path = os.path.join(SettingsManager().get("temp_dir"), f"fast_preview_{uuid.uuid4().hex}.png")
    return AIBridgeClient.get_instance().query_mask(
        image_path=frame_path, points=pts, labels=labels, fill_color_hex="#f97316", out_mask_path=out_path,
        sam_version=params.get("sam_version", "SAM 1 (ViT-H)"), text_prompt=params.get("text_prompt", ""),
        boxes=boxes or None)

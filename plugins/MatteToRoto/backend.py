import os
import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

class MatteToRotoWorker(QThread):
    progress = Signal(int)
    log_message = Signal(str)
    error = Signal(str)
    finished_ok = Signal(str)

    def __init__(self, matte_dir, output_dir, params):
        super().__init__()
        self.matte_dir = matte_dir
        self.output_dir = output_dir
        self.params = params
        self.is_cancelled = False

    def run(self):
        try:
            self.log_message.emit("Starting Matte to Roto Vectorization...")
            files = sorted([f for f in os.listdir(self.matte_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.exr', '.dpx'))])
            
            if not files:
                self.error.emit("No valid matte frames found in upstream node.")
                return
                
            export_format = self.params.get("export_format", "Both (Nuke & SVG)")
            simplification = float(self.params.get("simplification", 2.0))
            smoothness = float(self.params.get("smoothness", 0.3))
            
            nuke_shapes = []
            svg_dir = os.path.join(self.output_dir, "svg_sequence")
            if "SVG" in export_format or "Both" in export_format:
                os.makedirs(svg_dir, exist_ok=True)
                
            for i, f in enumerate(files):
                if self.is_cancelled:
                    self.log_message.emit("Vectorization cancelled.")
                    return
                    
                filepath = os.path.join(self.matte_dir, f)
                img = cv2.imread(filepath, cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                    
                _, thresh = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
                contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                svg_paths = []
                frame_nuke_shapes = []
                
                for c_idx, contour in enumerate(contours):
                    if cv2.contourArea(contour) < 50:  # Ignore tiny noise
                        continue
                        
                    epsilon = simplification
                    approx = cv2.approxPolyDP(contour, epsilon, True)
                    
                    if len(approx) < 3:
                        continue
                        
                    points = [pt[0] for pt in approx]
                    n_pts = len(points)
                    
                    nuke_curve = []
                    svg_d = f"M {points[0][0]},{points[0][1]} "
                    
                    for p_idx in range(n_pts):
                        p_prev = points[(p_idx - 1) % n_pts]
                        p_curr = points[p_idx]
                        p_next = points[(p_idx + 1) % n_pts]
                        
                        # Tangent vector
                        tx = (p_next[0] - p_prev[0]) * smoothness * 0.5
                        ty = (p_next[1] - p_prev[1]) * smoothness * 0.5
                        
                        # Control points
                        lh_x, lh_y = p_curr[0] - tx, p_curr[1] - ty
                        rh_x, rh_y = p_curr[0] + tx, p_curr[1] + ty
                        
                        # Nuke format: {x y lh_x lh_y rh_x rh_y} (Nuke Y is inverted relative to OpenCV)
                        h = img.shape[0]
                        ny, nlh_y, nrh_y = h - p_curr[1], h - lh_y, h - rh_y
                        nuke_curve.append(f"      {{{p_curr[0]} {ny} {lh_x} {nlh_y} {rh_x} {nrh_y}}}")
                        
                        # SVG formatting
                        if p_idx > 0:
                            prev_p_prev = points[(p_idx - 2) % n_pts]
                            prev_curr = points[(p_idx - 1) % n_pts]
                            prev_next = p_curr
                            prev_tx = (prev_next[0] - prev_p_prev[0]) * smoothness * 0.5
                            prev_ty = (prev_next[1] - prev_p_prev[1]) * smoothness * 0.5
                            prev_rh_x = prev_curr[0] + prev_tx
                            prev_rh_y = prev_curr[1] + prev_ty
                            
                            svg_d += f"C {prev_rh_x},{prev_rh_y} {lh_x},{lh_y} {p_curr[0]},{p_curr[1]} "
                            
                    # Close SVG
                    prev_p_prev = points[-2]
                    prev_curr = points[-1]
                    prev_next = points[0]
                    prev_tx = (prev_next[0] - prev_p_prev[0]) * smoothness * 0.5
                    prev_ty = (prev_next[1] - prev_p_prev[1]) * smoothness * 0.5
                    prev_rh_x = prev_curr[0] + prev_tx
                    prev_rh_y = prev_curr[1] + prev_ty
                    
                    curr_lh_x = points[0][0] - (points[1][0] - points[-1][0]) * smoothness * 0.5
                    curr_lh_y = points[0][1] - (points[1][1] - points[-1][1]) * smoothness * 0.5
                    
                    svg_d += f"C {prev_rh_x},{prev_rh_y} {curr_lh_x},{curr_lh_y} {points[0][0]},{points[0][1]} Z"
                    svg_paths.append(svg_d)
                    
                    frame_nuke_shapes.append((c_idx, nuke_curve))
                
                if "SVG" in export_format or "Both" in export_format:
                    h, w = img.shape[:2]
                    svg_out = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">\n'
                    for sp in svg_paths:
                        svg_out += f'  <path d="{sp}" fill="white" stroke="none"/>\n'
                    svg_out += '</svg>'
                    with open(os.path.join(svg_dir, f"{os.path.splitext(f)[0]}.svg"), "w") as sf:
                        sf.write(svg_out)
                        
                if "Nuke" in export_format or "Both" in export_format:
                    nuke_shapes.append((f, frame_nuke_shapes))
                    
                pct = int((i + 1) / len(files) * 100)
                self.progress.emit(pct)
                
            if "Nuke" in export_format or "Both" in export_format:
                nk_path = os.path.join(self.output_dir, "roto_shapes.nk")
                with open(nk_path, "w") as nk:
                    nk.write("Roto {\n curves {\n  {\n   \"Roto_AI\" {\n")
                    for fname, shapes in nuke_shapes:
                        clean_fname = os.path.splitext(fname)[0].replace("-", "_").replace(".", "_")
                        for c_idx, curve_pts in shapes:
                            nk.write(f"    \"Bezier_{clean_fname}_{c_idx}\" {{\n     {{\n")
                            for pt in curve_pts:
                                nk.write(f"{pt}\n")
                            nk.write("     }\n    }\n")
                    nk.write("   }\n  }\n }\n}\n")
                    
            self.log_message.emit(f"Vectorization complete. Saved to {self.output_dir}")
            self.finished_ok.emit(self.output_dir)
            
        except Exception as e:
            self.error.emit(str(e))

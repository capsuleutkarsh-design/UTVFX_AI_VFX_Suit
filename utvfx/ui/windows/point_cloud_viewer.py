import os
import numpy as np
import pyqtgraph.opengl as gl
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

def q_to_rot_mat(qw, qx, qy, qz):
    """Convert quaternion to rotation matrix."""
    return np.array([
        [1 - 2*qy**2 - 2*qz**2, 2*qx*qy - 2*qz*qw, 2*qx*qz + 2*qy*qw],
        [2*qx*qy + 2*qz*qw, 1 - 2*qx**2 - 2*qz**2, 2*qy*qz - 2*qx*qw],
        [2*qx*qz - 2*qy*qw, 2*qy*qz + 2*qx*qw, 1 - 2*qx**2 - 2*qy**2]
    ])

class PointCloudViewerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.gl_widget = gl.GLViewWidget()
        self.gl_widget.setBackgroundColor((5, 5, 5, 255))
        
        # Add a grid
        self.grid = gl.GLGridItem()
        self.grid.setSize(20, 20, 1)
        self.grid.setSpacing(1, 1, 1)
        self.grid.setColor((100, 100, 100, 100))
        self.gl_widget.addItem(self.grid)
        
        self.layout.addWidget(self.gl_widget)
        
        self.scatter_item = None
        self.camera_items = []
        
        self.current_sparse_dir = None
        self.cameras = {} # frame_num -> (C, R)
        self.current_frame_num = 0

        # Shortcut for camera mode
        from PySide6.QtGui import QShortcut, QKeySequence
        self.shortcut_cam = QShortcut(QKeySequence(Qt.Key_0), self)
        self.shortcut_cam.setContext(Qt.ApplicationShortcut)
        self.shortcut_cam.activated.connect(self.snap_to_camera)

    def set_current_frame(self, frame_num):
        self.current_frame_num = frame_num

    def snap_to_camera(self):
        import math
        if self.current_frame_num in self.cameras:
            C, R = self.cameras[self.current_frame_num]
            
            # Map COLMAP to OpenGL pyqtgraph coords
            # COLMAP X -> X, COLMAP Y -> -Z, COLMAP Z -> Y
            mapped_C = np.array([C[0], C[2], -C[1]])
            
            # Forward vector in world (COLMAP cameras look +Z)
            forward_world = R[:, 2]
            mapped_forward = np.array([forward_world[0], forward_world[2], -forward_world[1]])
            
            distance = 10.0
            # Orbit center is what the camera looks at
            target_pos = mapped_C + mapped_forward * distance
            
            # Compute azimuth and elevation
            D = -mapped_forward
            # Clamp for asin
            dz = max(-1.0, min(1.0, D[2]))
            elev = math.degrees(math.asin(dz))
            azim = math.degrees(math.atan2(D[1], D[0]))
            
            self.gl_widget.setCameraPosition(
                pos=target_pos, 
                distance=distance, 
                elevation=elev, 
                azimuth=azim
            )

    def clear(self):
        if self.scatter_item:
            self.gl_widget.removeItem(self.scatter_item)
            self.scatter_item = None
            
        for item in self.camera_items:
            self.gl_widget.removeItem(item)
        self.camera_items.clear()
        
        self.current_sparse_dir = None

    def load_colmap_model(self, sparse_dir):
        if self.current_sparse_dir == sparse_dir:
            return # Already loaded
            
        self.clear()
        
        points_path = os.path.join(sparse_dir, "points3D.txt")
        images_path = os.path.join(sparse_dir, "images.txt")
        
        if not os.path.exists(points_path):
            return False
            
        # 1. Load Points
        pos = []
        color = []
        with open(points_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.strip().split()
                if len(parts) >= 7:
                    x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                    r, g, b = float(parts[4]), float(parts[5]), float(parts[6])
                    pos.append([x, y, z])
                    color.append([r/255.0, g/255.0, b/255.0, 1.0])
                    
        if pos:
            pos_np = np.array(pos, dtype=np.float32)
            color_np = np.array(color, dtype=np.float32)
            
            # Flip Y and Z axes to match OpenGL coordinate system
            # COLMAP is X right, Y down, Z forward
            # Pyqtgraph is X right, Y forward, Z up
            # Let's map COLMAP X -> X, COLMAP Y -> -Z, COLMAP Z -> Y
            mapped_pos = np.zeros_like(pos_np)
            mapped_pos[:, 0] = pos_np[:, 0]
            mapped_pos[:, 1] = pos_np[:, 2]
            mapped_pos[:, 2] = -pos_np[:, 1]
            
            self.scatter_item = gl.GLScatterPlotItem(pos=mapped_pos, color=color_np, size=3.0, pxMode=True)
            self.gl_widget.addItem(self.scatter_item)
            
            # Center view on point cloud
            center = np.mean(mapped_pos, axis=0)
            self.gl_widget.pan(center[0], center[1], center[2])
            
            # Estimate distance scale based on point cloud size
            dists = np.linalg.norm(mapped_pos - center, axis=1)
            scale = np.percentile(dists, 95) if len(dists) > 0 else 10.0
            self.gl_widget.setCameraPosition(distance=scale * 2.5)

        # 2. Load Cameras
        if os.path.exists(images_path):
            cam_positions = []
            with open(images_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                # Two lines per image
                for i in range(0, len(lines)):
                    line = lines[i].strip()
                    if line.startswith("#") or not line:
                        continue
                    # Check if it's the image header line
                    parts = line.split()
                    if len(parts) >= 10 and i % 2 == 0:
                        qw, qx, qy, qz = map(float, parts[1:5])
                        tx, ty, tz = map(float, parts[5:8])
                        
                        name = parts[9]
                        import re
                        m = re.match(r"^.*?(\d+)\.[^.]+$", name)
                        frame_num = int(m.group(1)) if m else i // 2 + 1
                        
                        R = q_to_rot_mat(qw, qx, qy, qz)
                        t = np.array([tx, ty, tz])
                        
                        # Camera center in world coords: C = -R^T * t
                        C = -np.dot(R.T, t)
                        cam_positions.append(C)
                        self.cameras[frame_num] = (C, R)
                        
                        # Draw camera frustum (pyramid)
                        # Local camera coordinates
                        s = scale * 0.05 # frustum size
                        pts_local = np.array([
                            [0, 0, 0],
                            [-s, -s, s*2],
                            [s, -s, s*2],
                            [s, s, s*2],
                            [-s, s, s*2]
                        ])
                        
                        # Transform to world coords
                        pts_world = np.dot(R.T, pts_local.T).T + C
                        
                        # Map to PyQtGraph coords
                        pts_mapped = np.zeros_like(pts_world)
                        pts_mapped[:, 0] = pts_world[:, 0]
                        pts_mapped[:, 1] = pts_world[:, 2]
                        pts_mapped[:, 2] = -pts_world[:, 1]
                        
                        # Line segments for the frustum
                        lines_idx = np.array([
                            [0, 1], [0, 2], [0, 3], [0, 4], # to corners
                            [1, 2], [2, 3], [3, 4], [4, 1]  # base
                        ])
                        
                        line_pts = pts_mapped[lines_idx]
                        line_pts = line_pts.reshape(-1, 3)
                        
                        cam_item = gl.GLLinePlotItem(pos=line_pts, color=(1.0, 0.5, 0.0, 1.0), width=1.5, mode='lines')
                        self.gl_widget.addItem(cam_item)
                        self.camera_items.append(cam_item)
                        
            # If camera path exists, draw a line connecting camera centers
            if len(cam_positions) > 1:
                cam_pos_np = np.array(cam_positions)
                cam_pos_mapped = np.zeros_like(cam_pos_np)
                cam_pos_mapped[:, 0] = cam_pos_np[:, 0]
                cam_pos_mapped[:, 1] = cam_pos_np[:, 2]
                cam_pos_mapped[:, 2] = -cam_pos_np[:, 1]
                
                path_item = gl.GLLinePlotItem(pos=cam_pos_mapped, color=(0.0, 0.8, 1.0, 1.0), width=2.0, mode='line_strip')
                self.gl_widget.addItem(path_item)
                self.camera_items.append(path_item)

        self.current_sparse_dir = sparse_dir
        return True

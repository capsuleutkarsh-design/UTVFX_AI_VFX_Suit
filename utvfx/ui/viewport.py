import os
import glob
import cv2
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy, QStackedWidget
)
from utvfx.ui.timeline import TimelineWidget
from utvfx.ui.windows.point_cloud_viewer import PointCloudViewerWidget
import time
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer, QMutex, QMutexLocker, QPointF, QRectF
from PySide6.QtGui import QColor, QPalette, QImage, QPixmap, QPainter, QPen, QBrush
from utvfx.playback.video_player import VideoPlayerThread
from utvfx.ui.canvas import InteractiveVideoCanvas
from utvfx.core.media_resolver import get_node_media_path


class Viewport(QWidget):
    interaction_requested = Signal(str, int, list) # node_id, frame_idx, points
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.player_thread = None
        self.current_node = None
        self.current_view_mode = "COMPOSITE"
        self.setup_ui()
        
    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.setStyleSheet("background-color: #0d0d0f;")
        
        # Add keyboard shortcuts for timeline scrubbing
        from PySide6.QtGui import QShortcut, QKeySequence
        from PySide6.QtCore import Qt
        
        self.shortcut_left = QShortcut(QKeySequence(Qt.Key_Left), self)
        self.shortcut_left.setContext(Qt.ApplicationShortcut)
        self.shortcut_left.activated.connect(self.step_backward)
        
        self.shortcut_right = QShortcut(QKeySequence(Qt.Key_Right), self)
        self.shortcut_right.setContext(Qt.ApplicationShortcut)
        self.shortcut_right.activated.connect(self.step_forward)
        
        self.shortcut_fit = QShortcut(QKeySequence(Qt.Key_F), self)
        self.shortcut_fit.setContext(Qt.ApplicationShortcut)
        # connect will be done below after self.img_display is initialized!
        
        self.shortcut_in = QShortcut(QKeySequence(Qt.Key_I), self)
        self.shortcut_in.setContext(Qt.ApplicationShortcut)
        self.shortcut_in.activated.connect(self.set_in_point)
        
        self.shortcut_out = QShortcut(QKeySequence(Qt.Key_O), self)
        self.shortcut_out.setContext(Qt.ApplicationShortcut)
        self.shortcut_out.activated.connect(self.set_out_point)
        
        # ——— Top Toolbar ———
        toolbar = QWidget()
        toolbar.setFixedHeight(48)
        toolbar.setStyleSheet("background-color: #121212; border-bottom: 1px solid #27272a;")
        t_layout = QHBoxLayout(toolbar)
        t_layout.setContentsMargins(20, 0, 20, 0)
        
        self.lbl_title = QLabel("🔴 Monitor A // NO MEDIA")
        self.lbl_title.setStyleSheet("font-family: 'Space Grotesk'; font-size: 13px; font-weight: bold; color: #fafafa; letter-spacing: 1px;")
        self.lbl_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        t_layout.addWidget(self.lbl_title, 1)
        
        self.frame_lbl = QLabel("F 1 / 1")
        self.frame_lbl.setFixedWidth(80)
        self.frame_lbl.setAlignment(Qt.AlignCenter)
        self.frame_lbl.setStyleSheet("font-family: 'JetBrains Mono'; font-size: 11px; color: #71717a; background-color: #1a1a1e; padding: 4px 8px; border-radius: 4px;")
        t_layout.addWidget(self.frame_lbl)
        
        # Stretch is now handled by lbl_title
        
        # View modes
        btn_layout = QHBoxLayout()
        modes = ["SRC", "MATTE", "COMP", "3D"]
        self.view_modes = {}
        for mode in modes:
            btn = QPushButton(mode)
            btn.setStyleSheet("""
                QPushButton {
                    background: #1a1b1e;
                    color: #9ca3af;
                    border: 1px solid #374151;
                    border-radius: 4px;
                    padding: 4px 10px;
                }
                QPushButton:hover {
                    background: #25262b;
                    color: white;
                }
            """)
            btn.clicked.connect(lambda checked=False, m=mode: self.set_view_mode(m))
            self.view_modes[mode] = btn
            btn_layout.addWidget(btn)
            
        # Wipe Tool Toggle
        btn_layout.addSpacing(10)
        self.btn_wipe = QPushButton("◩ Wipe")
        self.btn_wipe.setCheckable(True)
        self.btn_wipe.setStyleSheet("""
            QPushButton { background: #1a1b1e; color: #a1a1aa; border: 1px solid #27272a; border-radius: 4px; padding: 4px 10px; font-weight: bold; }
            QPushButton:hover { background: #27272a; color: white; }
            QPushButton:checked { background: #3b82f6; color: white; border: 1px solid #60a5fa; }
        """)
        self.btn_wipe.clicked.connect(self.toggle_wipe)
        btn_layout.addWidget(self.btn_wipe)
        btn_layout.addSpacing(10)
            
        clear_range_btn = QPushButton("CLR I/O")
        clear_range_btn.setStyleSheet("""
            QPushButton {
                background: #1a1b1e;
                color: #fca5a5;
                border: 1px solid #7f1d1d;
                border-radius: 4px;
                padding: 4px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #7f1d1d;
                color: white;
            }
        """)
        clear_range_btn.clicked.connect(self.clear_in_out)
        btn_layout.addWidget(clear_range_btn)
        
        # BG Modes
        btn_layout.addSpacing(20)
        bg_label = QLabel("BG:")
        bg_label.setStyleSheet("color: #71717a; font-size: 11px; font-weight: bold;")
        btn_layout.addWidget(bg_label)
        
        self.bg_btns = {}
        for bg in ["Black", "White", "Grid"]:
            b = QPushButton(bg)
            b.setStyleSheet("""
                QPushButton { background: #1a1b1e; color: #9ca3af; border: 1px solid #374151; border-radius: 4px; padding: 4px 8px; }
                QPushButton:hover { background: #25262b; color: white; }
            """)
            b.clicked.connect(lambda checked=False, mode=bg: self.set_bg_mode(mode))
            self.bg_btns[bg] = b
            btn_layout.addWidget(b)
            
        btn_layout.addStretch()
        
        self.lbl_zoom = QLabel("Zoom: 100%")
        self.lbl_zoom.setFixedWidth(80)
        self.lbl_zoom.setStyleSheet("color: #a1a1aa; font-family: 'Space Grotesk'; font-size: 11px; font-weight: bold;")
        btn_layout.addWidget(self.lbl_zoom)
        
        self.lbl_probe = QLabel("X: --  Y: --  |  R: -- G: -- B: --")
        self.lbl_probe.setFixedWidth(180)
        self.lbl_probe.setStyleSheet("color: #a1a1aa; font-family: 'JetBrains Mono'; font-size: 11px;")
        btn_layout.addWidget(self.lbl_probe)
        
        t_layout.addLayout(btn_layout)
            
        main_layout.addWidget(toolbar)
        
        # ——— Video Display Area ———
        display_area = QWidget()
        display_area.setStyleSheet("background-color: #050505;")
        d_layout = QVBoxLayout(display_area)
        d_layout.setContentsMargins(0, 0, 0, 0)
        
        self.stacked_display = QStackedWidget()
        
        self.img_display = InteractiveVideoCanvas("SELECT A NODE TO VIEW MEDIA")
        self.img_display.interaction_requested.connect(self._on_canvas_interaction)
        self.img_display.zoom_changed.connect(self._on_zoom_changed)
        self.img_display.pixel_probed.connect(self._on_pixel_probed)
        self.stacked_display.addWidget(self.img_display)
        
        self.point_cloud_viewer = PointCloudViewerWidget()
        self.stacked_display.addWidget(self.point_cloud_viewer)
        
        d_layout.addWidget(self.stacked_display)
        
        self.shortcut_fit.activated.connect(self.img_display.reset_zoom)
        
        main_layout.addWidget(display_area, 1) # stretch = 1
        
        # ——— Bottom Timeline ———
        timeline = QWidget()
        timeline.setFixedHeight(60)
        timeline.setStyleSheet("background-color: #121212; border-top: 1px solid #27272a;")
        t_layout = QHBoxLayout(timeline)
        t_layout.setContentsMargins(10, 0, 10, 0)
        
        # Playback Controls
        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(40, 40)
        self.btn_play.setStyleSheet("""
            QPushButton { 
                background-color: #f59e0b; 
                color: #000000; 
                border-radius: 20px; 
                border: 2px solid #e2e8f0; 
                font-weight: bold; 
                font-size: 18px; 
                padding-left: 3px; 
                padding-bottom: 2px;
            }
            QPushButton:hover { background-color: #fbbf24; }
        """)
        self.btn_play.clicked.connect(self.toggle_playback)
        t_layout.addWidget(self.btn_play)
        
        self.lbl_start = QLabel("1")
        self.lbl_start.setStyleSheet("color: #f59e0b; font-family: 'Space Grotesk'; font-size: 14px; padding: 0px 10px; font-weight: bold;")
        t_layout.addWidget(self.lbl_start)

        self.timeline = TimelineWidget()
        self.timeline.frame_seeked.connect(self.seek_frame)
        self.img_display.keyframes_changed.connect(self.timeline.set_keyframes)
        self.img_display.keyframes_changed.connect(self._sync_mask_keyframes)
        t_layout.addWidget(self.timeline, 1) # stretch = 1
        
        self.lbl_end = QLabel("1")
        self.lbl_end.setStyleSheet("color: #71717a; font-family: 'Space Grotesk'; font-size: 11px; padding: 0px 10px;")
        t_layout.addWidget(self.lbl_end)
        
        self.btn_loop = QPushButton("🔁")
        self.btn_loop.setFixedSize(30, 30)
        self.btn_loop.setStyleSheet("""
            QPushButton { 
                background-color: transparent; 
                color: #3b82f6; 
                font-size: 18px; 
                border: none; 
            } 
            QPushButton:hover { color: #60a5fa; }
        """)
        t_layout.addWidget(self.btn_loop)
        
        self.btn_clear_pts = QPushButton("Clear Frame Points")
        self.btn_clear_pts.setStyleSheet("""
            QPushButton { background-color: #1a1a1e; color: #a1a1aa; border: 1px solid #27272a; border-radius: 4px; padding: 4px 10px; font-size: 11px; }
            QPushButton:hover { background-color: #27272a; color: #fafafa; }
        """)
        self.btn_clear_pts.clicked.connect(self.img_display.clear_current_frame_points)
        self.btn_clear_pts.hide() # Hidden by default, shown when SAM3 node is selected
        t_layout.addWidget(self.btn_clear_pts)
        
        main_layout.addWidget(timeline)
        
        self.set_view_mode("COMP")

    def set_view_mode(self, mode):
        for m, btn in self.view_modes.items():
            if m == mode:
                btn.setStyleSheet("QPushButton { background: #2b5c3a; color: #a1fca9; border: 1px solid #4ade80; border-radius: 4px; padding: 4px 10px; font-weight: bold; }")
            else:
                btn.setStyleSheet("QPushButton { background: #1a1b1e; color: #9ca3af; border: 1px solid #374151; border-radius: 4px; padding: 4px 10px; }")

        self.current_view_mode = mode
        if self.current_node:
            # Check if we should switch to 3D Viewer
            if mode == "3D" and getattr(self.current_node, "plugin_type", "") == "sfm_tracker":
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                sparse_dir = os.path.join(project_root, "workspace", "cache", getattr(self.current_node, "node_id", ""), "sparse")
                if os.path.exists(os.path.join(sparse_dir, "0", "points3D.txt")):
                    self.stacked_display.setCurrentWidget(self.point_cloud_viewer)
                    self.point_cloud_viewer.load_colmap_model(sparse_dir)
                    if self.player_thread:
                        self.player_thread.stop()
                        self.player_thread = None
                    return
            
            # Otherwise, use 2D Viewer
            self.stacked_display.setCurrentWidget(self.img_display)
            media_path = get_node_media_path(self.current_node, view_mode=mode)
            if media_path and os.path.exists(media_path):
                was_paused = True
                curr_frame = 0
                if self.player_thread:
                    was_paused = self.player_thread.is_paused
                    curr_frame = self.player_thread.current_frame
                    self.player_thread.stop()
                    self.player_thread = None
                
                self.img_display.clear()
                self.img_display.setText("LOADING...")
                self.player_thread = VideoPlayerThread(media_path)
                self.player_thread.view_mode = mode
                
                # Maintain true timeline length from source
                true_path = get_node_media_path(self.current_node, view_mode="SOURCE BGR")
                if true_path and true_path != media_path:
                    temp_p = VideoPlayerThread(true_path)
                    self.player_thread.total_frames = max(self.player_thread.total_frames, temp_p.total_frames)
                    self.player_thread.start_frame_offset = getattr(temp_p, 'start_frame_offset', 1)
                    
                self.player_thread.current_frame = curr_frame
                self.player_thread.is_paused = was_paused
                self.player_thread.frame_ready.connect(self.update_frame)
                self.player_thread.start()
                if was_paused:
                    self.seek_frame(curr_frame)



    def _sync_mask_keyframes(self, kfs=None):
        pass # UI updates handled elsewhere

    def _on_canvas_interaction(self, frame_idx, points):
        if self.current_node:
            self.interaction_requested.emit(self.current_node.node_id, frame_idx, points)

    def _on_zoom_changed(self):
        if hasattr(self.img_display, 'last_raw_image') and self.img_display.last_raw_image:
            cur_frame = self.player_thread.current_frame if self.player_thread else 0
            tot_frames = self.player_thread.total_frames if self.player_thread else 1
            self.update_frame(self.img_display.last_raw_image, cur_frame, tot_frames)
            
    @Slot(str, str, int, QImage)
    def receive_interactive_mask(self, node_id, layer_id, frame_idx, qimage):
        if self.current_node and self.current_node.node_id == node_id:
            self.img_display.set_mask_overlay(layer_id, frame_idx, qimage)

    @Slot(str, int, float)
    def handle_media_loaded(self, path, total_frames, fps):
        self.img_display.clear()
        self.img_display.setText("LOADING...")
        self.player_thread = VideoPlayerThread(path)
        self.player_thread.frame_ready.connect(self.update_frame)
        self.player_thread.start()
        self.timeline.set_frames(0, total_frames, getattr(self.player_thread, 'start_frame_offset', 1))

    def connect_to_node(self, node):
        """Connect viewport to a media provider node"""
        if node and "mask_keyframes" in getattr(node, "params", {}):
            legacy = node.params.pop("mask_keyframes")
            migrated = {int(k): v for k, v in legacy.items()}
            new_layer = {
                "id": "layer_legacy", 
                "name": "Migrated Mask", 
                "color": "#ff0000", 
                "visible": True, 
                "locked": False, 
                "keyframes": migrated
            }
            node.params["mask_layers"] = [new_layer]
            node.params["active_layer_id"] = "layer_legacy"

        # Save the current mask keyframes and overlays to the node before switching
        if self.current_node and self.img_display.is_interactive:
            if not hasattr(self.current_node, "params"):
                self.current_node.params = {}
            self.current_node._mask_overlays_cache = self.img_display.mask_overlays.copy()
        # Get the new media path before stopping the existing player
        media_path = get_node_media_path(node, view_mode=self.current_view_mode)

        # If it's the same node and the same media path, don't interrupt playback
        if getattr(self, "current_node", None) == node and self.player_thread and self.player_thread.media_path == media_path:
            # We still need to sync keyframes to the UI since they might have changed
            if self.img_display.is_interactive and hasattr(node, "params"):
                self.img_display.mask_layers = node.params.get("mask_layers", [])
                self.img_display.active_layer_id = node.params.get("active_layer_id", None)
            
            active_layer = next((l for l in self.img_display.mask_layers if l["id"] == self.img_display.active_layer_id), None)
            kfs = list(active_layer["keyframes"].keys()) if active_layer and "keyframes" in active_layer else []
            self.img_display.keyframes_changed.emit(kfs)
            return

        self.current_node = node
        
        # Stop existing player
        if self.player_thread:
            self.last_media_path = self.player_thread.media_path
            self.last_current_frame = self.player_thread.current_frame
            self.last_is_paused = self.player_thread.is_paused
            self.player_thread.stop()
            self.player_thread = None
        if not node:
            self.lbl_title.setText("🔴 Monitor A // NO NODE SELECTED")
            self.btn_clear_pts.hide()
            self.img_display.enable_interaction(False)
            self.img_display.clear()
            self.img_display.setText("SELECT A NODE TO VIEW MEDIA")
            self.frame_lbl.setText("F 1 / 1")
            self.lbl_start.setText("1")
            self.lbl_end.setText("1")
            self.timeline.set_frames(0, 1)
            self.timeline.set_keyframes([])
            return
            
        self.lbl_title.setText(f"🔴 Monitor A // {node.name}")
        self.img_display.enable_interaction(node.plugin_type in ["sam3_rotoscope", "matte_anyone", "super_matte"])
        
        # Restore the mask keyframes from the new node
        if self.img_display.is_interactive and hasattr(node, "params"):
            self.img_display.mask_layers = node.params.get("mask_layers", [])
            self.img_display.active_layer_id = node.params.get("active_layer_id", None)
        else:
            self.img_display.mask_layers = []
            self.img_display.active_layer_id = None
            
        self.img_display.mask_overlays.clear()
        if hasattr(node, "_mask_overlays_cache"):
            self.img_display.mask_overlays = node._mask_overlays_cache.copy()
            
        self.img_display.current_mask_overlay = self.img_display.mask_overlays.get((self.img_display.active_layer_id, self.img_display.current_frame), None)
        
        active_layer = next((l for l in self.img_display.mask_layers if l["id"] == self.img_display.active_layer_id), None)
        kfs = list(active_layer["keyframes"].keys()) if active_layer and "keyframes" in active_layer else []
        self.img_display.keyframes_changed.emit(kfs)
        
        # Load Camera Tracking Points
        self.img_display.tracking_points.clear()
        self.img_display.show_tracking = False
        if node.plugin_type == "sfm_tracker":
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            sparse_dir = os.path.join(project_root, "cache", getattr(node, "node_id", ""), "sparse", "0")
            images_txt = os.path.join(sparse_dir, "images.txt")
            if os.path.exists(images_txt):
                self.img_display.show_tracking = True
                try:
                    with open(images_txt, "r") as f:
                        lines = f.readlines()
                        for i in range(0, len(lines), 2):
                            if lines[i].startswith("#") or not lines[i].strip():
                                continue
                            parts = lines[i].strip().split()
                            if len(parts) >= 10:
                                name = parts[9]
                                import re
                                m = re.match(r"^.*?(\d+)\.[^.]+$", name)
                                if m:
                                    frame_num = int(m.group(1))
                                    # COLMAP sequence start varies, we map by finding offset
                                    # We will just parse the 2nd line
                                    pts_line = lines[i+1].strip().split()
                                    pts = []
                                    for p_idx in range(0, len(pts_line), 3):
                                        x = float(pts_line[p_idx])
                                        y = float(pts_line[p_idx+1])
                                        has_3d = int(pts_line[p_idx+2]) != -1
                                        if has_3d: # We probably only want to draw matched points
                                            pts.append((x, y, True))
                                    # We don't know the frame_offset yet. We'll store by frame_num for now.
                                    self.img_display.tracking_points[frame_num] = pts
                except Exception as e:
                    print(f"Failed to read tracking points: {e}")
                    
        if node.plugin_type in ["sam3_rotoscope", "matte_anyone", "super_matte"]:
            self.btn_clear_pts.show()
        else:
            self.btn_clear_pts.hide()
            
        media_path = get_node_media_path(node, view_mode=self.current_view_mode)

        if media_path and os.path.exists(media_path):
            self.img_display.clear()
            self.img_display.setText("LOADING...")
            self.player_thread = VideoPlayerThread(media_path)
            self.player_thread.view_mode = self.current_view_mode
            
            # Maintain true timeline length from source
            true_path = get_node_media_path(node, view_mode="SOURCE BGR")
            if true_path and true_path != media_path:
                temp_p = VideoPlayerThread(true_path)
                self.player_thread.total_frames = max(self.player_thread.total_frames, temp_p.total_frames)
                self.player_thread.start_frame_offset = getattr(temp_p, 'start_frame_offset', 1)
            
            # ALWAYS restore frame to keep playhead consistent across nodes
            self.player_thread.current_frame = getattr(self, "last_current_frame", 0)
            self.player_thread.is_paused = getattr(self, "last_is_paused", True)
            
            # Re-map tracking points from frame_num (absolute) to frame_idx (relative)
            if self.img_display.show_tracking and getattr(self.player_thread, 'start_frame_offset', None):
                offset = self.player_thread.start_frame_offset
                mapped_points = {}
                for absolute_frame, pts in self.img_display.tracking_points.items():
                    relative_idx = absolute_frame - offset
                    if relative_idx >= 0:
                        mapped_points[relative_idx] = pts
                self.img_display.tracking_points = mapped_points
            
            self.player_thread.frame_ready.connect(self.update_frame)
            self.player_thread.start()
            
            self.timeline.set_media_path(media_path, self.player_thread.is_sequence)
        else:
            self.img_display.clear()
            self.img_display.setText("NO MEDIA OR CACHE GENERATED")
            self.frame_lbl.setText("F 1 / 1")
            self.lbl_start.setText("1")
            self.lbl_end.setText("1")
            self.timeline.set_frames(0, 1)

    @Slot(QImage, int, int)
    def update_frame(self, image, current_frame, total_frames):
        # Store the current unscaled QImage so we can redraw on zoom
        self.img_display.last_raw_image = image
        
        # Clear the loading text now that we have a frame
        if self.img_display.text():
            self.img_display.setText("")
            
        if self.img_display.wipe_enabled:
            # Sync fetch B frame
            b_img = self._fetch_source_frame_sync(current_frame)
            self.img_display.last_b_image = b_img
            
        start_offset = getattr(self.player_thread, 'start_frame_offset', 1)
        display_frame = current_frame + start_offset
        end_display = start_offset + total_frames - 1 if total_frames > 0 else start_offset
            
        self.img_display.set_current_frame(current_frame)
        self.point_cloud_viewer.set_current_frame(display_frame)
        self.frame_lbl.setText(f"F {display_frame} / {end_display}")
        
        self.lbl_start.setText(str(display_frame))
        self.lbl_end.setText(str(end_display))
        
        # Block signals to prevent seek loop
        self.timeline.blockSignals(True)
        self.timeline.set_frames(current_frame, total_frames, start_offset)
        self.timeline.blockSignals(False)

    def toggle_playback(self):
        if self.player_thread:
            if self.player_thread.is_paused:
                self.player_thread.is_paused = False
                self.btn_play.setText("⏸")
            else:
                self.player_thread.is_paused = True
                self.btn_play.setText("▶")

    def seek_frame(self, position):
        if self.player_thread:
            was_playing = not self.player_thread.is_paused
            self.player_thread.is_paused = True # pause during seek
            self.player_thread.seek(position)
            if was_playing:
                self.player_thread.is_paused = False

    def step_backward(self):
        if self.player_thread and self.player_thread.total_frames > 0:
            new_frame = max(0, self.player_thread.current_frame - 1)
            self.seek_frame(new_frame)
            
    def step_forward(self):
        if self.player_thread:
            self.seek_frame(min(self.player_thread.current_frame + 1, self.player_thread.total_frames - 1))

    def set_in_point(self):
        if self.player_thread:
            self.timeline.set_in_frame(self.player_thread.current_frame)
            self.player_thread.in_frame = self.player_thread.current_frame
            
    def set_out_point(self):
        if self.player_thread:
            self.timeline.set_out_frame(self.player_thread.current_frame)
            self.player_thread.out_frame = self.player_thread.current_frame

    def clear_in_out(self):
        if self.player_thread:
            self.timeline.set_in_frame(None)
            self.timeline.set_out_frame(None)
            self.player_thread.in_frame = None
            self.player_thread.out_frame = None

    def toggle_wipe(self, checked):
        self.img_display.wipe_enabled = checked
        if checked and self.player_thread:
            self.img_display.last_b_image = self._fetch_source_frame_sync(self.player_thread.current_frame)
        self.img_display.update()

    def _fetch_source_frame_sync(self, frame_idx):
        if not self.current_node: return None
        true_path = get_node_media_path(self.current_node, view_mode="SOURCE BGR")
        if not true_path: return None
        
        # Super quick read using OpenCV for the preview B frame
        try:
            if os.path.isdir(true_path):
                files = sorted([f for f in os.listdir(true_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.exr', '.dpx', '.hdr'))])
                if 0 <= frame_idx < len(files):
                    frame = cv2.imread(os.path.join(true_path, files[frame_idx]))
                    if frame is not None:
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        h, w, c = frame.shape
                        return QImage(frame.data, w, h, w * c, QImage.Format_RGB888).copy()
            else:
                cap = cv2.VideoCapture(true_path)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                cap.release()
                if ret:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, c = frame.shape
                    return QImage(frame.data, w, h, w * c, QImage.Format_RGB888).copy()
        except Exception:
            pass
        return None

    def _on_zoom_changed(self):
        z = int(self.img_display.zoom_factor * 100)
        self.lbl_zoom.setText(f"Zoom: {z}%")
        
    def _on_pixel_probed(self, px, py, r, g, b):
        self.lbl_probe.setText(f"X: {px:<4} Y: {py:<4} | R: {r:<3} G: {g:<3} B: {b:<3}")

    def set_bg_mode(self, mode):
        for m, btn in self.bg_btns.items():
            if m == mode:
                btn.setStyleSheet("QPushButton { background: #3f3f46; color: white; border: 1px solid #71717a; border-radius: 4px; padding: 4px 8px; font-weight: bold; }")
            else:
                btn.setStyleSheet("QPushButton { background: #1a1b1e; color: #9ca3af; border: 1px solid #374151; border-radius: 4px; padding: 4px 8px; }")
        
        if mode == "Grid":
            self.img_display.bg_mode = "checkerboard"
        elif mode == "White":
            self.img_display.bg_mode = "white"
        else:
            self.img_display.bg_mode = "black"
            
        self.img_display.update()

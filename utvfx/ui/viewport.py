import os
import glob
import cv2
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy, QStackedWidget,
    QToolButton, QButtonGroup, QComboBox, QLineEdit, QApplication
)
from utvfx.ui import theme, icons
from utvfx.ui.timeline import TimelineWidget
from utvfx.ui.windows.point_cloud_viewer import PointCloudViewerWidget
import time
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer, QMutex, QMutexLocker, QPointF, QRectF
from PySide6.QtGui import QColor, QPalette, QImage, QPixmap, QPainter, QPen, QBrush, QIntValidator
from utvfx.playback.video_player import VideoPlayerThread, FrameReaderThread, probe_media
from utvfx.ui.canvas import InteractiveVideoCanvas
from utvfx.core.media_resolver import get_node_media_path


class _ElidedLabel(QLabel):
    """A label that elides its text instead of clipping it when space is short."""

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        painter.setFont(self.font())
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.width())
        painter.drawText(self.rect(), int(self.alignment()), text)
        painter.end()


class _FrameBox(QLineEdit):
    """The transport's current frame: shows the plate frame number; type one and press Enter to jump."""
    frame_entered = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        theme.set_role(self, "mono")
        self.setValidator(QIntValidator(-999999, 9999999, self))
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setFixedWidth(64)
        self.setToolTip("Current frame. Type a frame number and press Enter to jump there.")
        self._shown = "1"
        self.returnPressed.connect(self._enter)

    def show_frame(self, number):
        self._shown = str(number)
        if not self.hasFocus():
            self.setText(self._shown)

    def _enter(self):
        text = self.text().strip()
        self.clearFocus()
        if text.lstrip("-").isdigit():
            self.frame_entered.emit(int(text))
        self.setText(self._shown)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.setText(self._shown)
            self.clearFocus()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        QTimer.singleShot(0, self.selectAll)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.setText(self._shown)


class Viewport(QWidget):
    interaction_requested = Signal(str, int, list) # node_id, frame_idx, points

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player_thread = None
        self.current_node = None
        self.current_view_mode = "COMPOSITE"
        self._hooked_undo_stack = None
        self._b_reader = None  # reads the wipe's B frame off the UI thread
        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

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

        # ——— Viewer toolbar ———
        toolbar = QWidget()
        toolbar.setObjectName("Toolbar")
        toolbar.setFixedHeight(30)
        t_layout = QHBoxLayout(toolbar)
        t_layout.setContentsMargins(8, 0, 8, 0)
        t_layout.setSpacing(2)

        # View modes: a segmented group of checkable buttons. The keys are the
        # view-mode ids the media resolver and player expect; only labels changed.
        self.view_modes = {}
        self.view_mode_group = QButtonGroup(self)
        self.view_mode_group.setExclusive(True)
        for mode, label in (("SRC", "Source"), ("MATTE", "Matte"), ("COMP", "Comp"), ("3D", "3D")):
            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            btn.setToolTip(f"View {label.lower()}" if mode != "3D" else "View the 3D point cloud")
            theme.set_role(btn, "flat")
            btn.clicked.connect(lambda checked=False, m=mode: self.set_view_mode(m))
            self.view_mode_group.addButton(btn)
            self.view_modes[mode] = btn
            t_layout.addWidget(btn)

        t_layout.addSpacing(6)
        t_layout.addWidget(self._separator())
        t_layout.addSpacing(6)

        # Wipe toggle
        self.btn_wipe = QToolButton()
        self.btn_wipe.setText("Wipe")
        self.btn_wipe.setIcon(icons.icon("wipe"))
        self.btn_wipe.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_wipe.setCheckable(True)
        self.btn_wipe.setToolTip("Compare with the source plate")
        theme.set_role(self.btn_wipe, "flat")
        self.btn_wipe.clicked.connect(self.toggle_wipe)
        t_layout.addWidget(self.btn_wipe)

        t_layout.addSpacing(6)
        t_layout.addWidget(self._separator())
        t_layout.addSpacing(8)

        # Background behind the image
        t_layout.addWidget(theme.set_role(QLabel("Background"), "dim"))
        t_layout.addSpacing(4)
        self.bg_btns = {}
        self.bg_combo = QComboBox()
        self.bg_combo.addItems(["Black", "White", "Grid"])
        self.bg_combo.setToolTip("Background shown behind transparent pixels")
        self.bg_combo.currentTextChanged.connect(self.set_bg_mode)
        t_layout.addWidget(self.bg_combo)

        # Node name, elided when the viewer is narrow
        t_layout.addSpacing(12)
        self.lbl_title = theme.set_role(_ElidedLabel("No node selected"), "faint")
        self.lbl_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_title.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        t_layout.addWidget(self.lbl_title, 1)
        t_layout.addSpacing(12)

        # Readouts, right aligned
        self.lbl_zoom = theme.set_role(QLabel("100%"), "mono")
        self.lbl_zoom.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_zoom.setMinimumWidth(40)
        self.lbl_zoom.setToolTip("Zoom (F to fit)")
        t_layout.addWidget(self.lbl_zoom)
        t_layout.addSpacing(12)

        self.lbl_probe = theme.set_role(QLabel(self._probe_text()), "mono")
        self.lbl_probe.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_probe.setToolTip("Pixel under the cursor")
        self.lbl_probe.setMinimumWidth(
            self.lbl_probe.fontMetrics().horizontalAdvance("x 9999 y 9999  r 10.000 g 10.000 b 10.000") + 4)
        t_layout.addWidget(self.lbl_probe)

        main_layout.addWidget(toolbar)

        # ——— Video display area ———
        display_area = QWidget()
        d_layout = QVBoxLayout(display_area)
        d_layout.setContentsMargins(0, 0, 0, 0)

        self.stacked_display = QStackedWidget()

        self.img_display = InteractiveVideoCanvas("No media")
        self.img_display.interaction_requested.connect(self._on_canvas_interaction)
        self.img_display.zoom_changed.connect(self._on_zoom_changed)
        self.img_display.pixel_probed.connect(self._on_pixel_probed)
        self.stacked_display.addWidget(self.img_display)

        self.point_cloud_viewer = PointCloudViewerWidget()
        self.stacked_display.addWidget(self.point_cloud_viewer)

        d_layout.addWidget(self.stacked_display)

        self.shortcut_fit.activated.connect(self.img_display.reset_zoom)

        main_layout.addWidget(display_area, 1) # stretch = 1

        # ——— Transport and timeline ———
        timeline = QWidget()
        timeline.setObjectName("Toolbar")
        timeline.setFixedHeight(34)
        t_layout = QHBoxLayout(timeline)
        t_layout.setContentsMargins(6, 0, 8, 0)
        t_layout.setSpacing(2)

        def transport_button(icon_name, tip, slot=None):
            btn = QToolButton()
            btn.setIcon(icons.icon(icon_name))
            btn.setIconSize(icons.ICON_SIZE)
            btn.setToolTip(tip)
            theme.set_role(btn, "icon")
            if slot:
                btn.clicked.connect(slot)
            t_layout.addWidget(btn)
            return btn

        self.btn_step_back = transport_button("step-back", "Previous frame (Left)", self.step_backward)
        self.btn_play = transport_button("play", "Play / pause", self.toggle_playback)
        self.btn_step_forward = transport_button("step-forward", "Next frame (Right)", self.step_forward)
        self.btn_loop = transport_button("loop", "Loop playback between the in and out points")
        self.btn_loop.setCheckable(True)
        self.btn_loop.setChecked(True)
        self.btn_loop.toggled.connect(self._on_loop_toggled)

        t_layout.addSpacing(8)

        # Current frame: type a plate frame number to jump there
        self.frame_box = _FrameBox()
        self.frame_box.show_frame(1)
        self.frame_box.frame_entered.connect(self.go_to_frame_number)
        self.lbl_start = self.frame_box  # older name
        t_layout.addWidget(self.frame_box)
        t_layout.addSpacing(8)

        self.timeline = TimelineWidget()
        self.timeline.frame_seeked.connect(self.seek_frame)
        self.img_display.keyframes_changed.connect(self.timeline.set_keyframes)
        t_layout.addWidget(self.timeline, 1) # stretch = 1
        t_layout.addSpacing(8)

        # Last frame
        self.lbl_end = theme.set_role(QLabel("1"), "mono")
        self.lbl_end.setMinimumWidth(36)
        self.lbl_end.setToolTip("Last frame")
        t_layout.addWidget(self.lbl_end)
        t_layout.addSpacing(4)

        clear_range_btn = QToolButton()
        clear_range_btn.setText("Clear in/out")
        clear_range_btn.setToolTip("Clear the in and out points (set them with I and O)")
        theme.set_role(clear_range_btn, "flat")
        clear_range_btn.clicked.connect(self.clear_in_out)
        t_layout.addWidget(clear_range_btn)

        # Kept for callers that read it; the transport shows the same numbers.
        self.frame_lbl = theme.set_role(QLabel("1 / 1", self), "mono")
        self.frame_lbl.hide()

        self.btn_clear_pts = QToolButton()
        self.btn_clear_pts.setText("Clear points")
        self.btn_clear_pts.setIcon(icons.icon("clear"))
        self.btn_clear_pts.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_clear_pts.setToolTip("Clear the points on this frame")
        theme.set_role(self.btn_clear_pts, "flat")
        self.btn_clear_pts.clicked.connect(self.img_display.clear_current_frame_points)
        self.btn_clear_pts.hide() # Hidden by default, shown when SAM3 node is selected
        t_layout.addSpacing(6)
        t_layout.addWidget(self.btn_clear_pts)

        main_layout.addWidget(timeline)

        self.set_view_mode("COMP")

    def _load_track_points(self, node):
        """2D positions of the solved points per plate frame, as fractions of the frame (0-1)."""
        import json
        from utvfx.core.media_resolver import get_node_cache
        sparse_dir = os.path.join(get_node_cache(node), "sparse")
        images_txt = os.path.join(sparse_dir, "0", "images.txt")
        try:
            with open(os.path.join(sparse_dir, "solve.json"), encoding="utf-8") as f:
                solve = json.load(f)
            with open(images_txt, "r", encoding="utf-8") as f:
                lines = [l for l in f.read().splitlines() if not l.startswith("#")]
        except (OSError, ValueError):
            return
        w, h = float(solve["image_width"]), float(solve["image_height"])
        for header, observations in zip(lines[0::2], lines[1::2]):
            parts = header.split()
            if len(parts) < 10 or parts[9] not in solve["frames"]:
                continue
            values = observations.split()
            pts = [(float(values[k]) / w, float(values[k + 1]) / h, True)
                   for k in range(0, len(values) - 2, 3) if values[k + 2] != "-1"]
            self.img_display.tracking_points[solve["frames"][parts[9]]] = pts
        self.img_display.show_tracking = bool(self.img_display.tracking_points)

    def set_view_mode(self, mode):
        for m, btn in self.view_modes.items():
            btn.setChecked(m == mode)

        self.current_view_mode = mode
        if self.current_node:
            # Check if we should switch to 3D Viewer
            if mode == "3D" and getattr(self.current_node, "plugin_type", "") == "sfm_tracker":
                from utvfx.core.media_resolver import get_node_cache
                sparse_dir = os.path.join(get_node_cache(self.current_node), "sparse", "0")
                if os.path.exists(os.path.join(sparse_dir, "points3D.txt")):
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
                self.img_display.setText("Loading…")
                self.player_thread = self._new_player(media_path, mode)

                self.player_thread.current_frame = curr_frame
                self.player_thread.is_paused = was_paused
                self.player_thread.start()
                if was_paused:
                    self.seek_frame(curr_frame)



    def _on_canvas_interaction(self, frame_idx, points):
        if self.current_node:
            self.interaction_requested.emit(self.current_node.node_id, frame_idx, points)


    @Slot(str, str, int, QImage)
    def receive_interactive_mask(self, node_id, layer_id, frame_idx, qimage):
        if self.current_node and self.current_node.node_id == node_id:
            self.img_display.set_mask_overlay(layer_id, frame_idx, qimage)

    @Slot(str, int, float)
    def handle_media_loaded(self, path, total_frames, fps):
        """Show media that is not attached to a node (also used by the tests)."""
        self.img_display.clear()
        self.img_display.setText("Loading…")
        self.player_thread = self._new_player(path, self.current_view_mode, keep_length=False)
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
                "enabled": True,
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
        media_path = get_node_media_path(node, view_mode=self.current_view_mode) if node else None

        # If it's the same node and the same media path, don't interrupt playback
        if getattr(self, "current_node", None) == node and self.player_thread and self.player_thread.media_path == media_path:
            # We still need to sync keyframes to the UI since they might have changed
            self._hook_undo_stack()
            if self.img_display.is_interactive and hasattr(node, "params"):
                self.img_display.sync_layers(node.params.get("mask_layers", []), node.params.get("active_layer_id", None))
            else:
                self.img_display.keyframes_changed.emit([])
            return

        self.current_node = node
        self.img_display.node = node
        self._hook_undo_stack()

        # Stop existing player
        if self.player_thread:
            self.last_media_path = self.player_thread.media_path
            self.last_current_frame = self.player_thread.current_frame
            self.last_is_paused = self.player_thread.is_paused
            self.player_thread.stop()
            self.player_thread = None
        if not node:
            self.lbl_title.setText("No node selected")
            self.btn_clear_pts.hide()
            self.img_display.enable_interaction(False)
            self.img_display.clear()
            self.img_display.setText("No media")
            self.frame_lbl.setText("1 / 1")
            self.frame_box.show_frame(1)
            self.lbl_end.setText("1")
            self.timeline.set_frames(0, 1)
            self.timeline.set_keyframes([])
            return

        self.lbl_title.setText(node.name)
        self.img_display.enable_interaction(node.plugin_type == "super_matte")

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
            self._load_track_points(node)

        if node.plugin_type == "super_matte":
            self.btn_clear_pts.show()
        else:
            self.btn_clear_pts.hide()

        media_path = get_node_media_path(node, view_mode=self.current_view_mode)

        if media_path and os.path.exists(media_path):
            self.img_display.clear()
            self.img_display.setText("Loading…")
            self.player_thread = self._new_player(media_path, self.current_view_mode)

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

            self.player_thread.start()

            self.timeline.set_media_path(media_path, self.player_thread.is_sequence)
        else:
            self.img_display.clear()
            self.img_display.setText("Nothing rendered yet")
            self.frame_lbl.setText("1 / 1")
            self.frame_box.show_frame(1)
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
            self._request_b_frame(current_frame)

        start_offset = getattr(self.player_thread, 'start_frame_offset', 1)
        display_frame = current_frame + start_offset
        end_display = start_offset + total_frames - 1 if total_frames > 0 else start_offset

        self.img_display.set_current_frame(current_frame)
        self.point_cloud_viewer.set_current_frame(display_frame)
        self.frame_lbl.setText(f"{display_frame} / {end_display}")

        self.frame_box.show_frame(display_frame)
        self.lbl_end.setText(str(end_display))

        # Block signals to prevent seek loop
        self.timeline.blockSignals(True)
        self.timeline.set_frames(current_frame, total_frames, start_offset)
        self.timeline.blockSignals(False)

    def toggle_playback(self):
        if self.player_thread:
            if self.player_thread.is_paused:
                player = self.player_thread
                if not player.loop:
                    # Stopped at the out point: play the range again from the in point
                    start, end = player._bounds()
                    if player.current_frame >= end:
                        self.seek_frame(start)
                player.is_paused = False
                self.btn_play.setIcon(icons.icon("pause"))
            else:
                self.player_thread.is_paused = True
                self.btn_play.setIcon(icons.icon("play"))

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
        if not checked:
            self.img_display.last_b_image = None
        elif self.player_thread:
            self._request_b_frame(self.player_thread.current_frame)
        self.img_display.update()

    # ---- helpers ------------------------------------------------------------------
    def _new_player(self, media_path, view_mode, keep_length=True):
        """A paused player for `media_path`, wired to the viewer and the transport."""
        player = VideoPlayerThread(media_path)
        player.view_mode = view_mode
        player.loop = self.btn_loop.isChecked()
        if keep_length and self.current_node is not None:
            # The timeline keeps the source plate's length (a render may be shorter)
            true_path = get_node_media_path(self.current_node, view_mode="SOURCE BGR")
            if true_path and true_path != media_path and os.path.exists(true_path):
                total, offset = probe_media(true_path)
                player.total_frames = max(player.total_frames, total)
                player.start_frame_offset = offset
        player.frame_ready.connect(self.update_frame)
        player.playback_finished.connect(self._on_playback_finished)
        return player

    def _on_loop_toggled(self, checked):
        if self.player_thread:
            self.player_thread.loop = checked
        self.btn_loop.setToolTip(
            "Loop playback between the in and out points" if checked else "Stop playback at the out point")

    def _on_playback_finished(self):
        self.btn_play.setIcon(icons.icon("play"))

    def go_to_frame_number(self, number):
        """Jump to a plate frame number (e.g. 1025), as typed in the frame box."""
        if not self.player_thread:
            return
        offset = getattr(self.player_thread, "start_frame_offset", 1)
        index = self.timeline.index_for_frame_number(number, offset, self.player_thread.total_frames)
        self.seek_frame(index)

    def _request_b_frame(self, frame_idx):
        """Ask for the wipe's B side (the source plate) without blocking the UI."""
        if not self.current_node:
            return
        true_path = get_node_media_path(self.current_node, view_mode="SOURCE BGR")
        if not true_path or not os.path.exists(true_path):
            return
        if self._b_reader is None:
            self._b_reader = FrameReaderThread(self)
            self._b_reader.frame_ready.connect(self._on_b_frame)
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._b_reader.stop)
        self._b_reader.request(true_path, frame_idx, "SRC")

    def _on_b_frame(self, path, frame_idx, image):
        if not self.img_display.wipe_enabled:
            return
        self.img_display.last_b_image = image
        self.img_display.update()

    def _hook_undo_stack(self):
        """Follow the window's undo stack so undo/redo of click points and layers shows here."""
        stack = getattr(self.window(), "undo_stack", None)
        if stack is None or stack is self._hooked_undo_stack:
            return
        if self._hooked_undo_stack is not None:
            try:
                self._hooked_undo_stack.indexChanged.disconnect(self._on_undo_index_changed)
            except (RuntimeError, TypeError):
                pass
        stack.indexChanged.connect(self._on_undo_index_changed)
        self._hooked_undo_stack = stack

    def _on_undo_index_changed(self, _index=None):
        node = self.current_node
        if node is None or not self.img_display.is_interactive:
            return
        try:
            if node.scene() is None:
                return  # node removed (undo of an add)
        except RuntimeError:
            return
        params = getattr(node, "params", {})
        self.img_display.sync_layers(params.get("mask_layers", []), params.get("active_layer_id"))

    def _on_zoom_changed(self):
        z = int(self.img_display.zoom_factor * 100)
        self.lbl_zoom.setText(f"{z}%")

    @staticmethod
    def _probe_text(px="-", py="-", r="-", g="-", b="-"):
        return f"x {px:>4} y {py:>4}  r {r:>3} g {g:>3} b {b:>3}"

    def _separator(self):
        line = QFrame()
        line.setFixedSize(1, 16)
        line.setAutoFillBackground(True)
        palette = line.palette()
        palette.setColor(QPalette.ColorRole.Window, theme.qcolor(theme.BORDER_SOFT))
        line.setPalette(palette)
        return line

    def _linear_source(self):
        """Scene-linear pixels (ACEScg) of the frame on screen, if it is a float image."""
        player = self.player_thread
        if player is None or not getattr(player, "is_sequence", False) or not player.sequence_files:
            return None
        index = min(max(int(getattr(player, "current_frame", 0)), 0), len(player.sequence_files) - 1)
        path = player.sequence_files[index]
        if not path.lower().endswith((".exr", ".hdr")):
            return None
        cached = getattr(self, "_probe_cache", None)
        if cached is None or cached[0] != path:
            from utvfx.core import colour
            try:
                self._probe_cache = (path, colour.read_linear(path))
            except (IOError, RuntimeError):
                self._probe_cache = (path, None)
        return self._probe_cache[1]

    def _on_pixel_probed(self, px, py, r, g, b):
        # For float plates show the real scene-linear values (highlights above 1.0 included),
        # not the 8-bit display pixels.
        linear = self._linear_source()
        if linear is not None and 0 <= py < linear.shape[0] and 0 <= px < linear.shape[1]:
            fr, fg, fb = (float(v) for v in linear[py, px, :3])
            self.lbl_probe.setText(f"x {px:>4} y {py:>4}  r {fr:6.3f} g {fg:6.3f} b {fb:6.3f}")
            self.lbl_probe.setToolTip("Scene-linear ACEScg values of the pixel under the cursor")
            return
        self.lbl_probe.setToolTip("Display values (0-255) of the pixel under the cursor")
        self.lbl_probe.setText(self._probe_text(px, py, r, g, b))

    def set_bg_mode(self, mode):
        if self.bg_combo.currentText() != mode:
            self.bg_combo.setCurrentText(mode)

        if mode == "Grid":
            self.img_display.bg_mode = "checkerboard"
        elif mode == "White":
            self.img_display.bg_mode = "white"
        else:
            self.img_display.bg_mode = "black"

        self.img_display.update()

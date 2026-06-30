from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QSlider, QGraphicsView, QGraphicsScene,
    QGroupBox, QFormLayout, QLineEdit, QComboBox, QMessageBox,
    QProgressBar, QFrame, QSizePolicy
)
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import Qt
import os
import cv2
import numpy as np
from .backend import InferenceWorker


class MatAnyoneUI(QWidget):
    # Design accent color for MatAnyone2
    ACCENT = "#0EA5E9"
    ACCENT_HOVER = "#0284C7"

    def __init__(self):
        super().__init__()

        self.video_path = None
        self.video_cap = None
        self.total_frames = 0
        self.current_frame = 0
        self.mask_dict = {}  # frame_idx -> numpy mask
        self.worker = None

        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(12)

        # ─── LEFT SIDEBAR ────────────────────────────────────
        sidebar = QWidget()
        sidebar.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(8)
        sidebar_layout.setAlignment(Qt.AlignTop)

        # Load Video
        self.btn_load_video = QPushButton("📂  Load Video")
        self.btn_load_video.setCursor(Qt.PointingHandCursor)
        self.btn_load_video.setMinimumHeight(50)
        self.btn_load_video.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.ACCENT};
                color: #000000;
                font-weight: bold;
                font-size: 12px;
                border: none;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {self.ACCENT_HOVER};
            }}
        """)
        sidebar_layout.addWidget(self.btn_load_video)

        # Load Mask
        self.btn_load_mask = QPushButton("🖌️  Load Mask")
        self.btn_load_mask.setCursor(Qt.PointingHandCursor)
        self.btn_load_mask.setMinimumHeight(38)
        sidebar_layout.addWidget(self.btn_load_mask)

        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("background-color: #27272A; max-height: 1px;")
        sidebar_layout.addWidget(sep1)

        # Output Path
        out_label = QLabel("OUTPUT PATH")
        out_label.setStyleSheet("font-size: 9px; letter-spacing: 2px; color: #71717A; font-weight: bold;")
        sidebar_layout.addWidget(out_label)

        self.btn_output_path = QPushButton("💾  Set Output")
        self.btn_output_path.setCursor(Qt.PointingHandCursor)
        sidebar_layout.addWidget(self.btn_output_path)

        self.lbl_output_path = QLabel("./results")
        self.lbl_output_path.setStyleSheet("color: #52525B; font-size: 10px; font-family: 'Consolas', monospace;")
        self.lbl_output_path.setWordWrap(True)
        sidebar_layout.addWidget(self.lbl_output_path)

        sidebar_layout.addStretch()

        # Sidebar info
        info_label = QLabel("Select a video and provide\na segmentation mask for\nframe 0 to begin matting.")
        info_label.setStyleSheet("color: #3F3F46; font-size: 10px; line-height: 1.4;")
        info_label.setWordWrap(True)
        sidebar_layout.addWidget(info_label)

        main_layout.addWidget(sidebar)

        # ─── RIGHT CONTENT ───────────────────────────────────
        content = QVBoxLayout()
        content.setSpacing(10)

        # Viewer area with tabs simulated by buttons
        viewer_header = QHBoxLayout()
        self.btn_view_fg = QPushButton("Foreground")
        self.btn_view_fg.setCheckable(True)
        self.btn_view_fg.setChecked(True)
        self.btn_view_alpha = QPushButton("Alpha")
        self.btn_view_alpha.setCheckable(True)

        for btn in [self.btn_view_fg, self.btn_view_alpha]:
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: #71717A;
                    border: none;
                    font-size: 10px;
                    font-weight: bold;
                    letter-spacing: 2px;
                    padding: 0 12px;
                    border-radius: 4px;
                }}
                QPushButton:hover {{
                    color: #A1A1AA;
                }}
                QPushButton:checked {{
                    background-color: #1E1E22;
                    color: #FFFFFF;
                    border: 1px solid #27272A;
                }}
            """)

        viewer_header.addWidget(self.btn_view_fg)
        viewer_header.addWidget(self.btn_view_alpha)
        viewer_header.addStretch()

        # Frame counter
        self.lbl_frame_info = QLabel("F 0 / 0")
        self.lbl_frame_info.setStyleSheet(f"""
            font-size: 9px;
            font-weight: bold;
            letter-spacing: 2px;
            color: {self.ACCENT};
            background-color: #050505;
            border: 1px solid #27272A;
            border-radius: 4px;
            padding: 4px 10px;
            font-family: 'Consolas', monospace;
        """)
        viewer_header.addWidget(self.lbl_frame_info)

        content.addLayout(viewer_header)

        # Graphics views (stacked)
        self.scene_foreground = QGraphicsScene()
        self.view_foreground = QGraphicsView(self.scene_foreground)
        self.view_foreground.setMinimumSize(640, 360)
        self.view_foreground.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.scene_alpha = QGraphicsScene()
        self.view_alpha = QGraphicsView(self.scene_alpha)
        self.view_alpha.setMinimumSize(640, 360)
        self.view_alpha.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view_alpha.hide()

        content.addWidget(self.view_foreground, stretch=3)
        content.addWidget(self.view_alpha, stretch=3)

        # Scrubber
        scrubber_layout = QHBoxLayout()
        scrubber_layout.setSpacing(10)
        self.scrubber = QSlider(Qt.Horizontal)
        self.scrubber.setMinimum(0)
        self.scrubber.setMaximum(0)
        self.scrubber.setEnabled(False)
        self.scrubber.setStyleSheet(f"""
            QSlider::sub-page:horizontal {{
                background: {self.ACCENT};
            }}
        """)
        self.lbl_frame_counter = QLabel("0 / 0")
        self.lbl_frame_counter.setStyleSheet("color: #71717A; font-size: 11px; font-family: 'Consolas', monospace; min-width: 60px;")

        scrubber_layout.addWidget(self.scrubber)
        scrubber_layout.addWidget(self.lbl_frame_counter)
        content.addLayout(scrubber_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar::chunk {{
                background-color: {self.ACCENT};
            }}
        """)
        content.addWidget(self.progress_bar)

        # ─── Controls Group ──────────────────────────────────
        controls_group = QGroupBox("Matting Controls")
        controls_group.setStyleSheet(f"""
            QGroupBox {{
                border-color: {self.ACCENT}40;
            }}
            QGroupBox::title {{
                color: {self.ACCENT};
            }}
        """)
        controls_layout = QHBoxLayout(controls_group)
        controls_layout.setSpacing(16)

        # Form section
        form_layout = QFormLayout()
        form_layout.setSpacing(8)

        lbl_frame = QLabel("START FRAME")
        lbl_frame.setStyleSheet("font-size: 9px; letter-spacing: 2px; color: #71717A; font-weight: bold;")
        self.inp_exact_frame = QLineEdit("0")
        self.inp_exact_frame.setMaximumWidth(70)

        lbl_model = QLabel("MODEL")
        lbl_model.setStyleSheet("font-size: 9px; letter-spacing: 2px; color: #71717A; font-weight: bold;")
        self.combo_model = QComboBox()
        self.combo_model.addItems(["MatAnyone 2 (matanyone2.pth)", "MatAnyone 1 (matanyone.pth)"])

        form_layout.addRow(lbl_frame, self.inp_exact_frame)
        form_layout.addRow(lbl_model, self.combo_model)

        # Action buttons
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(8)

        self.btn_clear_cache = QPushButton("🗑️  Empty Cache")
        self.btn_clear_cache.setCursor(Qt.PointingHandCursor)
        actions_layout.addWidget(self.btn_clear_cache)

        self.btn_execute = QPushButton("🚀  Run Matting Engine")
        self.btn_execute.setCursor(Qt.PointingHandCursor)
        self.btn_execute.setMinimumHeight(38)
        self.btn_execute.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.ACCENT};
                color: #000000;
                font-weight: bold;
                font-size: 12px;
                border: none;
                border-radius: 6px;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{
                background-color: {self.ACCENT_HOVER};
            }}
            QPushButton:disabled {{
                background-color: #3F3F46;
                color: #71717A;
            }}
        """)
        actions_layout.addWidget(self.btn_execute)

        controls_layout.addLayout(form_layout)
        controls_layout.addStretch()
        controls_layout.addLayout(actions_layout)

        content.addWidget(controls_group, stretch=0)

        main_layout.addLayout(content, stretch=4)

        # ─── Connections ─────────────────────────────────────
        self.btn_load_video.clicked.connect(self.load_video)
        self.btn_load_mask.clicked.connect(self.load_mask)
        self.btn_output_path.clicked.connect(self.select_output)
        self.scrubber.valueChanged.connect(self.on_scrub)
        self.btn_execute.clicked.connect(self.run_engine)
        self.btn_clear_cache.clicked.connect(self.clear_cache)
        self.btn_view_fg.clicked.connect(lambda: self.switch_view("fg"))
        self.btn_view_alpha.clicked.connect(lambda: self.switch_view("alpha"))

    def switch_view(self, mode):
        if mode == "fg":
            self.view_foreground.show()
            self.view_alpha.hide()
            self.btn_view_fg.setChecked(True)
            self.btn_view_alpha.setChecked(False)
        else:
            self.view_foreground.hide()
            self.view_alpha.show()
            self.btn_view_fg.setChecked(False)
            self.btn_view_alpha.setChecked(True)

    def select_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d:
            self.lbl_output_path.setText(d)

    def load_video(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Video", "", "Video Files (*.mp4 *.avi *.mov)")
        if file_name:
            self.video_path = file_name
            self.video_cap = cv2.VideoCapture(self.video_path)
            self.total_frames = int(self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.scrubber.setMaximum(max(0, self.total_frames - 1))
            self.scrubber.setEnabled(True)
            self.scrubber.setValue(0)
            self.on_scrub(0)
            print(f"Video loaded: {file_name}")

    def on_scrub(self, frame_idx):
        self.current_frame = frame_idx
        self.lbl_frame_counter.setText(f"{frame_idx} / {max(0, self.total_frames - 1)}")
        self.lbl_frame_info.setText(f"F {frame_idx} / {self.total_frames}")
        self.inp_exact_frame.setText(str(frame_idx))

        if self.video_cap:
            self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = self.video_cap.read()
            if ret:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                self.show_image(frame_rgb, self.scene_foreground)

    def load_mask(self):
        if self.current_frame is None or self.video_path is None:
            return
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Mask", "", "Images (*.png *.jpg)")
        if file_name:
            mask = cv2.imread(file_name, cv2.IMREAD_GRAYSCALE)
            if mask is not None:
                self.mask_dict[self.current_frame] = mask
                QMessageBox.information(self, "Mask Loaded", f"Mask loaded for frame {self.current_frame}!")

    def show_image(self, rgb_np, scene):
        h, w, c = rgb_np.shape
        bytes_per_line = c * w
        qimg = QImage(rgb_np.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)
        scene.clear()
        scene.addPixmap(pixmap)

    def show_alpha(self, alpha_np):
        h, w = alpha_np.shape
        bytes_per_line = w
        qimg = QImage(alpha_np.data, w, h, bytes_per_line, QImage.Format_Grayscale8)
        pixmap = QPixmap.fromImage(qimg)
        self.scene_alpha.clear()
        self.scene_alpha.addPixmap(pixmap)

    def run_engine(self):
        if not self.video_path:
            QMessageBox.warning(self, "Error", "Load video first!")
            return

        if 0 not in self.mask_dict:
            QMessageBox.warning(self, "Error", "You must load a mask for frame 0!")
            return

        out_path = self.lbl_output_path.text()
        if out_path == "./results":
            out_path = os.path.join(os.path.dirname(self.video_path), "results")
            self.lbl_output_path.setText(out_path)

        model_name = "matanyone2.pth" if "2" in self.combo_model.currentText() else "matanyone.pth"

        self.btn_execute.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.worker = InferenceWorker(self.video_path, self.mask_dict, out_path, {"model_selection": model_name})
        self.worker.progress_update.connect(self.on_progress)
        self.worker.frame_ready.connect(self.on_frame_ready)
        self.worker.finished_processing.connect(self.on_finished)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.start()

    def on_progress(self, curr, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(curr)

    def on_frame_ready(self, fgr_np, alpha_np, frame_idx):
        self.show_image(fgr_np, self.scene_foreground)
        self.show_alpha(alpha_np)
        self.scrubber.blockSignals(True)
        self.scrubber.setValue(frame_idx)
        self.lbl_frame_counter.setText(f"{frame_idx} / {max(0, self.total_frames - 1)}")
        self.lbl_frame_info.setText(f"F {frame_idx} / {self.total_frames}")
        self.scrubber.blockSignals(False)

    def on_finished(self):
        self.btn_execute.setEnabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.information(self, "Done", "Matting completed!")

    def on_error(self, err):
        self.btn_execute.setEnabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "Error", str(err))

    def clear_cache(self):
        self.mask_dict.clear()
        QMessageBox.information(self, "Cache Cleared", "Mask cache emptied.")


def get_ui():
    return MatAnyoneUI()

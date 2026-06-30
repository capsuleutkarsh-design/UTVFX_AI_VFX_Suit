from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QComboBox, QSlider, QGroupBox, QFormLayout,
    QProgressBar, QFrame, QTextEdit, QCheckBox, QSpinBox
)
from PySide6.QtCore import Qt
import os
from .backend import CorridorKeyWorker

class PluginUI(QWidget):
    # Design accent color for CorridorKey
    ACCENT = "#10B981"
    ACCENT_HOVER = "#059669"

    def __init__(self, parent=None):
        super().__init__(parent)

        self.video_path = None
        self.mask_path = None
        self.output_dir = os.path.join(os.getcwd(), "cache", "corridorkey_out")
        self.worker = None

        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(12)

        # ─── LEFT SIDEBAR ────────────────────────────────────
        sidebar = QWidget()
        sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(8)
        sidebar_layout.setAlignment(Qt.AlignTop)

        # Inputs
        self.btn_load_video = QPushButton("📂  Load Source Video")
        self.btn_load_video.setCursor(Qt.PointingHandCursor)
        self.btn_load_video.setMinimumHeight(45)
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
        self.btn_load_video.clicked.connect(self.load_video)
        sidebar_layout.addWidget(self.btn_load_video)

        self.btn_load_mask = QPushButton("🖌️  Load Mask (Optional)")
        self.btn_load_mask.setCursor(Qt.PointingHandCursor)
        self.btn_load_mask.setMinimumHeight(38)
        self.btn_load_mask.clicked.connect(self.load_mask)
        sidebar_layout.addWidget(self.btn_load_mask)

        # Labels
        self.lbl_video = QLabel("No video selected")
        self.lbl_video.setStyleSheet("color: #71717A; font-size: 10px;")
        self.lbl_video.setWordWrap(True)
        sidebar_layout.addWidget(self.lbl_video)

        self.lbl_mask = QLabel("Auto-Matte will be used")
        self.lbl_mask.setStyleSheet("color: #71717A; font-size: 10px;")
        self.lbl_mask.setWordWrap(True)
        sidebar_layout.addWidget(self.lbl_mask)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #27272A; max-height: 1px; margin: 10px 0;")
        sidebar_layout.addWidget(sep)

        # Output Path
        out_label = QLabel("OUTPUT CACHE")
        out_label.setStyleSheet("font-size: 9px; letter-spacing: 2px; color: #71717A; font-weight: bold;")
        sidebar_layout.addWidget(out_label)

        self.btn_output_path = QPushButton("💾  Set Output Dir")
        self.btn_output_path.setCursor(Qt.PointingHandCursor)
        self.btn_output_path.clicked.connect(self.set_output_dir)
        sidebar_layout.addWidget(self.btn_output_path)

        self.lbl_output_path = QLabel(self.output_dir)
        self.lbl_output_path.setStyleSheet("color: #52525B; font-size: 10px; font-family: 'Consolas', monospace;")
        self.lbl_output_path.setWordWrap(True)
        sidebar_layout.addWidget(self.lbl_output_path)

        sidebar_layout.addStretch()

        info_label = QLabel("Note: If no mask is provided, BiRefNet will automatically generate an alpha matte.")
        info_label.setStyleSheet("color: #3F3F46; font-size: 10px; line-height: 1.4;")
        info_label.setWordWrap(True)
        sidebar_layout.addWidget(info_label)

        main_layout.addWidget(sidebar)

        # ─── RIGHT CONTENT (Settings & Execution) ─────────────
        content = QVBoxLayout()
        content.setSpacing(12)

        # Settings Group
        settings_group = QGroupBox("Keying Settings")
        settings_group.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {self.ACCENT}40; border-radius: 6px; margin-top: 10px; }}
            QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; padding: 0 5px; color: {self.ACCENT}; }}
        """)
        form_layout = QFormLayout(settings_group)
        form_layout.setContentsMargins(15, 20, 15, 15)
        form_layout.setSpacing(10)

        # Screen Color
        self.combo_color = QComboBox()
        self.combo_color.addItems(["auto", "green", "blue"])
        form_layout.addRow("Screen Color:", self.combo_color)

        # Despill
        self.slider_despill = QSlider(Qt.Horizontal)
        self.slider_despill.setRange(0, 100)
        self.slider_despill.setValue(50)
        form_layout.addRow("Despill Strength:", self.slider_despill)

        # Despeckle
        self.chk_despeckle = QCheckBox("Enable Auto-Despeckle")
        self.chk_despeckle.setChecked(True)
        form_layout.addRow("", self.chk_despeckle)

        # Despeckle Size
        self.spin_despeckle = QSpinBox()
        self.spin_despeckle.setRange(0, 5000)
        self.spin_despeckle.setValue(400)
        form_layout.addRow("Despeckle Size:", self.spin_despeckle)

        # Refiner Scale
        self.spin_refiner = QSpinBox()
        self.spin_refiner.setRange(0, 500)
        self.spin_refiner.setValue(100)
        form_layout.addRow("Refiner Scale (%):", self.spin_refiner)

        content.addWidget(settings_group)

        # Console
        console_group = QGroupBox("Execution Log")
        console_layout = QVBoxLayout(console_group)
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(150)
        console_layout.addWidget(self.console)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{ border: 1px solid #3F3F46; border-radius: 4px; text-align: center; color: white; }}
            QProgressBar::chunk {{ background-color: {self.ACCENT}; width: 10px; }}
        """)
        console_layout.addWidget(self.progress_bar)
        content.addWidget(console_group)

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.btn_run = QPushButton("🚀 Run Keying Pipeline")
        self.btn_run.setMinimumHeight(45)
        self.btn_run.setStyleSheet(f"""
            QPushButton {{ background-color: {self.ACCENT}; color: #000; font-weight: bold; border-radius: 6px; }}
            QPushButton:hover {{ background-color: {self.ACCENT_HOVER}; }}
            QPushButton:disabled {{ background-color: #1e3a8a; color: #93c5fd; }}
        """)
        self.btn_run.clicked.connect(self.run_engine)
        btn_layout.addWidget(self.btn_run)

        self.btn_cancel = QPushButton("🛑 Cancel")
        self.btn_cancel.setMinimumHeight(45)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setStyleSheet("""
            QPushButton {{ background-color: #ef4444; color: white; font-weight: bold; border-radius: 6px; }}
            QPushButton:hover {{ background-color: #dc2626; }}
            QPushButton:disabled {{ background-color: #7f1d1d; color: #fca5a5; }}
        """)
        self.btn_cancel.clicked.connect(self.cancel_engine)
        btn_layout.addWidget(self.btn_cancel)

        content.addLayout(btn_layout)
        main_layout.addLayout(content)

    def load_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Source Video", "", "Videos (*.mp4 *.mov *.avi *.mkv);;Images (*.png *.jpg *.exr)")
        if path:
            self.video_path = path
            self.lbl_video.setText(os.path.basename(path))

    def load_mask(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Mask Video", "", "Videos (*.mp4 *.mov *.avi *.mkv);;Images (*.png *.jpg *.exr)")
        if path:
            self.mask_path = path
            self.lbl_mask.setText(os.path.basename(path))

    def set_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_dir = dir_path
            self.lbl_output_path.setText(dir_path)

    def log_message(self, msg):
        self.console.append(msg)

    def run_engine(self):
        if not self.video_path or not os.path.exists(self.video_path):
            self.log_message("ERROR: Please load a source video first.")
            return

        self.btn_run.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        params = {
            "screen_color": self.combo_color.currentText(),
            "despill_strength": self.slider_despill.value() / 100.0,
            "auto_despeckle": self.chk_despeckle.isChecked(),
            "despeckle_size": self.spin_despeckle.value(),
            "refiner_scale": self.spin_refiner.value() / 100.0,
        }

        self.worker = CorridorKeyWorker(self.video_path, self.mask_path, self.output_dir, params)
        self.worker.progress_update.connect(self.on_progress)
        self.worker.log_message.connect(self.log_message)
        self.worker.finished_processing.connect(self.on_finished)
        self.worker.error_occurred.connect(self.on_error)
        
        self.console.clear()
        self.log_message("Starting CorridorKey...")
        self.worker.start()

    def cancel_engine(self):
        if hasattr(self, 'worker') and self.worker:
            self.worker.cancel()
            self.btn_cancel.setEnabled(False)
            self.log_message("Cancellation requested...")

    def on_progress(self, current, total):
        if total > 0:
            pct = int((current / total) * 100)
            self.progress_bar.setValue(pct)
            self.progress_bar.setFormat(f"{pct}% ({current}/{total})")

    def on_finished(self):
        self.log_message("Process Complete!")
        self.btn_run.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress_bar.setValue(100)

    def on_error(self, err):
        self.log_message(f"ERROR: {err}")
        self.btn_run.setEnabled(True)
        self.btn_cancel.setEnabled(False)

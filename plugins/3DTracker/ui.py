import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QComboBox, QTextEdit, QGroupBox, QLineEdit, QFrame
)
from PySide6.QtCore import Qt, Signal, Slot
from .backend import TrackerBackend


class PluginUI(QWidget):
    # Design accent color for 3DTracker
    ACCENT = "#EAB308"
    ACCENT_HOVER = "#CA8A04"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.backend = TrackerBackend()
        self.setup_ui()
        self.setup_connections()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)

        # â”€â”€â”€ Config Section â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        config_group = QGroupBox("3D Tracking Configuration")
        config_group.setStyleSheet(f"""
            QGroupBox {{
                border-color: {self.ACCENT}40;
            }}
            QGroupBox::title {{
                color: {self.ACCENT};
            }}
        """)
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(10)

        # Input Directory
        input_label = QLabel("INPUT IMAGES DIRECTORY")
        input_label.setStyleSheet("font-size: 9px; letter-spacing: 2px; color: #71717A; font-weight: bold;")
        config_layout.addWidget(input_label)

        h_in = QHBoxLayout()
        h_in.setSpacing(8)
        self.input_btn = QPushButton("📂  Browse")
        self.input_btn.setFixedWidth(110)
        self.input_btn.setCursor(Qt.PointingHandCursor)
        self.input_lbl = QLineEdit()
        self.input_lbl.setReadOnly(True)
        self.input_lbl.setPlaceholderText("No directory selected...")
        h_in.addWidget(self.input_btn)
        h_in.addWidget(self.input_lbl)
        config_layout.addLayout(h_in)

        # Output Directory
        output_label = QLabel("OUTPUT DIRECTORY")
        output_label.setStyleSheet("font-size: 9px; letter-spacing: 2px; color: #71717A; font-weight: bold;")
        config_layout.addWidget(output_label)

        h_out = QHBoxLayout()
        h_out.setSpacing(8)
        self.output_btn = QPushButton("💾  Browse")
        self.output_btn.setFixedWidth(110)
        self.output_btn.setCursor(Qt.PointingHandCursor)
        self.output_lbl = QLineEdit()
        self.output_lbl.setReadOnly(True)
        self.output_lbl.setPlaceholderText("No directory selected...")
        h_out.addWidget(self.output_btn)
        h_out.addWidget(self.output_lbl)
        config_layout.addLayout(h_out)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #27272A; max-height: 1px;")
        config_layout.addWidget(sep)

        # Engine Selection
        engine_label = QLabel("RECONSTRUCTION ENGINE")
        engine_label.setStyleSheet("font-size: 9px; letter-spacing: 2px; color: #71717A; font-weight: bold;")
        config_layout.addWidget(engine_label)

        h_engine = QHBoxLayout()
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(["Colmap (Sparse + Dense)", "Glomap (Sparse)"])
        h_engine.addWidget(self.engine_combo)
        h_engine.addStretch()
        config_layout.addLayout(h_engine)

        # Action Buttons
        btn_layout = QHBoxLayout()
        
        # Run Button
        self.run_btn = QPushButton("⚡  Execute 3D Reconstruction")
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setMinimumHeight(42)
        self.run_btn.setStyleSheet(f"""
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
        btn_layout.addWidget(self.run_btn)

        # Cancel Button
        self.cancel_btn = QPushButton("🛑  Cancel")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setMinimumHeight(42)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #7F1D1D;
                color: #FECACA;
                font-weight: bold;
                font-size: 12px;
                border: none;
                border-radius: 6px;
                letter-spacing: 1px;
            }
            QPushButton:hover {
                background-color: #991B1B;
            }
            QPushButton:disabled {
                background-color: #3F3F46;
                color: #71717A;
            }
        """)
        btn_layout.addWidget(self.cancel_btn)
        config_layout.addLayout(btn_layout)

        main_layout.addWidget(config_group)

        # â”€â”€â”€ Console Output â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        console_group = QGroupBox("Processing Output")
        console_group.setStyleSheet(f"""
            QGroupBox {{
                border-color: {self.ACCENT}40;
            }}
            QGroupBox::title {{
                color: {self.ACCENT};
            }}
        """)
        console_layout = QVBoxLayout(console_group)
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setMinimumHeight(200)
        self.console_output.setPlaceholderText(">> CLI logs will stream here...")
        console_layout.addWidget(self.console_output)

        main_layout.addWidget(console_group)

    def setup_connections(self):
        self.input_btn.clicked.connect(self.select_input)
        self.output_btn.clicked.connect(self.select_output)
        self.run_btn.clicked.connect(self.start_tracking)
        self.cancel_btn.clicked.connect(self.cancel_tracking)

        self.backend.log_output.connect(self.append_log)
        self.backend.finished.connect(self.on_finished)

    def select_input(self):
        d = QFileDialog.getExistingDirectory(self, "Select Input Directory")
        if d:
            self.input_lbl.setText(d)

    def select_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d:
            self.output_lbl.setText(d)

    def start_tracking(self):
        in_dir = self.input_lbl.text()
        out_dir = self.output_lbl.text()
        if not in_dir or not out_dir:
            self.append_log("ERROR: Please select input and output directories.")
            return

        engine = "colmap" if "Colmap" in self.engine_combo.currentText() else "glomap"

        self.run_btn.setEnabled(False)
        self.console_output.clear()
        self.append_log(f"Starting {engine.upper()} processing...")
        self.backend.start_process(in_dir, out_dir, engine)

    def cancel_tracking(self):
        self.append_log("Cancelling reconstruction...")
        self.cancel_btn.setEnabled(False)
        self.backend.cancel_process()

    @Slot(str)
    def append_log(self, text):
        self.console_output.append(text)

    @Slot(bool)
    def on_finished(self, success):
        self.run_btn.setEnabled(True)
        if success:
            self.append_log("\n--- PROCESSING COMPLETED SUCCESSFULLY ---")
        else:
            self.append_log("\n--- PROCESSING FAILED ---")


import os
import sys
import requests
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QProgressBar, QScrollArea, QWidget, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal

try:
    from huggingface_hub import snapshot_download
except ImportError:
    snapshot_download = None

# Define the base directory of the software
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODELS = [
    {
        "name": "BiRefNet (General)",
        "type": "huggingface",
        "repo_id": "ZhengPeng7/BiRefNet",
        "path": os.path.join(BASE_DIR, "plugins", "CorridorKey", "System", "BiRefNetModule", "checkpoints", "BiRefNet"),
        "check_file": "model.safetensors"
    },
    {
        "name": "BiRefNet (Matting)",
        "type": "huggingface",
        "repo_id": "ZhengPeng7/BiRefNet-matting",
        "path": os.path.join(BASE_DIR, "plugins", "CorridorKey", "System", "BiRefNetModule", "checkpoints", "BiRefNet-matting"),
        "check_file": "model.safetensors"
    },
    {
        "name": "BiRefNet (Portrait)",
        "type": "huggingface",
        "repo_id": "ZhengPeng7/BiRefNet-portrait",
        "path": os.path.join(BASE_DIR, "plugins", "CorridorKey", "System", "BiRefNetModule", "checkpoints", "BiRefNet-portrait"),
        "check_file": "model.safetensors"
    },
    {
        "name": "MatAnyone 2",
        "type": "url",
        "url": "https://github.com/pq-yang/MatAnyone2/releases/download/v1.0.0/matanyone2.pth",
        "path": os.path.join(BASE_DIR, "plugins", "MatAnyone2", "pretrained_models"),
        "check_file": "matanyone2.pth"
    },
    {
        "name": "Segment Anything (SAM)",
        "type": "url",
        "url": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth",
        "path": os.path.join(BASE_DIR, "plugins", "MatAnyone2", "pretrained_models"),
        "check_file": "sam_vit_h_4b8939.pth"
    },
    {
        "name": "Depth Anything V2 (Large)",
        "type": "url",
        "url": "https://huggingface.co/depth-anything/Depth-Anything-V2-Large/resolve/main/depth_anything_v2_vitl.pth",
        "path": os.path.join(BASE_DIR, "plugins", "Depth-Anything-V2", "checkpoints"),
        "check_file": "depth_anything_v2_vitl.pth"
    }
]

class DownloadWorker(QThread):
    progress = Signal(int, int) # downloaded, total
    status = Signal(str)
    finished_all = Signal()
    error = Signal(str)

    def __init__(self, models_to_download):
        super().__init__()
        self.models_to_download = models_to_download
        self.is_cancelled = False

    def run(self):
        for model in self.models_to_download:
            if self.is_cancelled:
                break
                
            self.status.emit(f"Downloading {model['name']}...")
            try:
                if model["type"] == "huggingface":
                    if snapshot_download is None:
                        raise ImportError("huggingface_hub is not installed.")
                    os.makedirs(model["path"], exist_ok=True)
                    # For huggingface, we can't easily track progress with our custom UI bar without monkeypatching.
                    # We'll just show an indeterminate progress bar.
                    self.progress.emit(0, 0) 
                    snapshot_download(
                        repo_id=model["repo_id"],
                        local_dir=model["path"]
                    )
                    self.progress.emit(100, 100)
                    
                elif model["type"] == "url":
                    self.download_file_from_url(model["url"], model["path"], model["check_file"])
                    
            except Exception as e:
                self.error.emit(f"Error downloading {model['name']}: {str(e)}")
                continue

        if not self.is_cancelled:
            self.status.emit("All downloads completed!")
        self.finished_all.emit()

    def download_file_from_url(self, url, save_dir, filename):
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, filename)
        
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(save_path, 'wb') as file:
            for data in response.iter_content(chunk_size=8192):
                if self.is_cancelled:
                    break
                size = file.write(data)
                downloaded += size
                self.progress.emit(downloaded, total_size)

    def cancel(self):
        self.is_cancelled = True


class ModelDownloaderDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Model Downloader")
        self.setMinimumSize(600, 450)
        self.setStyleSheet("""
            QDialog {
                background-color: #18181b;
                color: #fafafa;
                font-family: 'Inter', sans-serif;
            }
            QLabel {
                color: #fafafa;
                font-size: 13px;
            }
            QProgressBar {
                border: 1px solid #3f3f46;
                border-radius: 4px;
                background-color: #27272a;
                text-align: center;
                color: white;
                height: 18px;
            }
            QProgressBar::chunk {
                background-color: #3b82f6; /* Blue progress */
                border-radius: 3px;
            }
            QPushButton {
                background-color: #27272a;
                color: #fafafa;
                border: 1px solid #3f3f46;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3f3f46;
            }
            QPushButton:disabled {
                background-color: #1f1f22;
                color: #71717a;
                border-color: #27272a;
            }
            QPushButton#primary {
                background-color: #3b82f6;
                border: None;
            }
            QPushButton#primary:hover {
                background-color: #2563eb;
            }
            QScrollArea {
                border: 1px solid #27272a;
                background-color: #0f0f11;
                border-radius: 6px;
            }
            QFrame#model_item {
                background-color: #18181b;
                border-bottom: 1px solid #27272a;
                padding: 8px;
            }
        """)

        self.worker = None
        self.models_to_download = []
        self.setup_ui()
        self.check_models()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title = QLabel("AI Model Requirements")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        
        self.summary_label = QLabel("Checking models...")
        self.summary_label.setStyleSheet("color: #a1a1aa;")
        layout.addWidget(self.summary_label)

        # Scroll area for models
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setSpacing(0)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(self.scroll_content)
        layout.addWidget(scroll)

        # Progress Area
        self.progress_container = QWidget()
        prog_layout = QVBoxLayout(self.progress_container)
        prog_layout.setContentsMargins(0,0,0,0)
        
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        prog_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        prog_layout.addWidget(self.progress_bar)
        
        layout.addWidget(self.progress_container)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close_dialog)
        btn_layout.addWidget(self.btn_close)
        
        self.btn_download = QPushButton("Download Missing Models")
        self.btn_download.setObjectName("primary")
        self.btn_download.clicked.connect(self.start_download)
        self.btn_download.setEnabled(False)
        btn_layout.addWidget(self.btn_download)
        
        layout.addLayout(btn_layout)

    def check_models(self):
        # Clear existing items
        for i in reversed(range(self.scroll_layout.count())): 
            w = self.scroll_layout.itemAt(i).widget()
            if w:
                w.setParent(None)

        self.models_to_download = []
        installed_count = 0

        for model in MODELS:
            expected_file = os.path.join(model["path"], model["check_file"])
            is_installed = os.path.exists(expected_file)
            
            if is_installed:
                installed_count += 1
            else:
                self.models_to_download.append(model)
                
            item_widget = QFrame()
            item_widget.setObjectName("model_item")
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(10, 10, 10, 10)
            
            name_lbl = QLabel(model["name"])
            name_lbl.setStyleSheet("font-weight: 500;")
            
            status_lbl = QLabel("✅ Installed" if is_installed else "❌ Missing")
            status_lbl.setStyleSheet("color: #10b981; font-weight: bold;" if is_installed else "color: #ef4444; font-weight: bold;")
            
            item_layout.addWidget(name_lbl)
            item_layout.addStretch()
            item_layout.addWidget(status_lbl)
            
            self.scroll_layout.addWidget(item_widget)

        total = len(MODELS)
        if installed_count == total:
            self.summary_label.setText(f"All {total} models are correctly installed!")
            self.btn_download.hide()
        else:
            self.summary_label.setText(f"{total - installed_count} model(s) are missing and need to be downloaded.")
            self.btn_download.setEnabled(True)

    def start_download(self):
        if not self.models_to_download:
            return

        self.btn_download.setEnabled(False)
        self.btn_close.setText("Cancel")
        self.progress_bar.show()
        
        self.worker = DownloadWorker(self.models_to_download)
        self.worker.progress.connect(self.update_progress)
        self.worker.status.connect(self.update_status)
        self.worker.error.connect(self.on_error)
        self.worker.finished_all.connect(self.on_finished)
        self.worker.start()

    def update_progress(self, downloaded, total):
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(downloaded)
        else:
            self.progress_bar.setMaximum(0) # Indeterminate mode for HF
            self.progress_bar.setValue(0)

    def update_status(self, text):
        self.status_label.setText(text)

    def on_error(self, err_text):
        self.status_label.setText(f"Error: {err_text}")
        self.status_label.setStyleSheet("color: #ef4444; font-size: 12px;")

    def on_finished(self):
        self.btn_close.setText("Close")
        self.btn_download.hide()
        self.progress_bar.hide()
        self.status_label.setStyleSheet("color: #10b981; font-size: 12px; font-weight: bold;")
        self.check_models() # Refresh list

    def close_dialog(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
        self.accept()

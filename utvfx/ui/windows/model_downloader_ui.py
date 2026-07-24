import os
import sys
import zipfile
import requests
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QProgressBar, QScrollArea, QWidget, QFrame, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal

try:
    from huggingface_hub import snapshot_download
except ImportError:
    snapshot_download = None

from utvfx.core.settings_manager import SettingsManager

try:
    from first_setup import MODELS as SETUP_MODELS
except ImportError:
    SETUP_MODELS = []

# Resolve paths using SettingsManager
_sm = SettingsManager()
MODELS_DIR = _sm.models_dir
BASE_DIR = os.path.dirname(MODELS_DIR)

MODELS = []
for sm in SETUP_MODELS:
    if sm.get("type") == "hf_repo":
        MODELS.append({
            "name": sm["name"],
            "type": "huggingface",
            "repo_id": sm["repo_id"],
            "path": os.path.join(BASE_DIR, sm.get("local_dir", "")),
            "check_file": "config.json"
        })
    elif sm.get("type") == "file":
        MODELS.append({
            "name": sm["name"],
            "type": "url",
            "url": sm["url"],
            "path": os.path.dirname(os.path.join(BASE_DIR, sm["path"])),
            "check_file": os.path.basename(sm["path"])
        })

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


class ExtractWorker(QThread):
    progress = Signal(int, int) # extracted, total
    status = Signal(str)
    finished_all = Signal()
    error = Signal(str)

    def __init__(self, zip_path, extract_dir):
        super().__init__()
        self.zip_path = zip_path
        self.extract_dir = extract_dir
        self.is_cancelled = False

    def run(self):
        self.status.emit("Extracting models (this may take a while)...")
        try:
            with zipfile.ZipFile(self.zip_path, 'r') as zip_ref:
                members = zip_ref.infolist()
                total_files = len(members)
                
                for i, member in enumerate(members):
                    if self.is_cancelled:
                        break
                        
                    # Fix paths for users who zipped the contents of the models directory directly
                    if not (member.filename.startswith("models/") or member.filename.startswith("plugins/")):
                        member.filename = "models/" + member.filename
                            
                    zip_ref.extract(member, self.extract_dir)
                    self.progress.emit(i + 1, total_files)
                    
            if not self.is_cancelled:
                self.status.emit("Extraction completed successfully!")
        except Exception as e:
            self.error.emit(f"Extraction failed: {str(e)}")
            
        self.finished_all.emit()

    def cancel(self):
        self.is_cancelled = True


class ModelDownloaderDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Offline/Online Model Setup")
        self.setMinimumSize(700, 500)
        self.setStyleSheet("""
            QDialog { background-color: #18181b; color: #fafafa; font-family: 'Inter', sans-serif; }
            QLabel { color: #fafafa; font-size: 13px; }
            QProgressBar { border: 1px solid #3f3f46; border-radius: 4px; background-color: #27272a; text-align: center; color: white; height: 18px; }
            QProgressBar::chunk { background-color: #3b82f6; border-radius: 3px; }
            QPushButton { background-color: #27272a; color: #fafafa; border: 1px solid #3f3f46; padding: 8px 16px; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background-color: #3f3f46; }
            QPushButton:disabled { background-color: #1f1f22; color: #71717a; border-color: #27272a; }
            QPushButton#primary { background-color: #3b82f6; border: None; }
            QPushButton#primary:hover { background-color: #2563eb; }
            QPushButton#secondary { background-color: #10b981; border: None; }
            QPushButton#secondary:hover { background-color: #059669; }
            QScrollArea { border: 1px solid #27272a; background-color: #0f0f11; border-radius: 6px; }
            QFrame#model_item { background-color: #18181b; border-bottom: 1px solid #27272a; padding: 8px; }
        """)

        self.worker = None
        self.models_to_download = []
        self.setup_ui()
        self.check_models()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("AI Models Setup")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        
        self.summary_label = QLabel("Checking models...")
        self.summary_label.setStyleSheet("color: #a1a1aa;")
        layout.addWidget(self.summary_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setSpacing(0)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.scroll_content)
        layout.addWidget(scroll)

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

        btn_layout = QHBoxLayout()
        
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close_dialog)
        btn_layout.addWidget(self.btn_close)
        
        btn_layout.addStretch()
        
        self.btn_download = QPushButton("Download from Internet")
        self.btn_download.setObjectName("primary")
        self.btn_download.clicked.connect(self.start_download)
        self.btn_download.setEnabled(False)
        btn_layout.addWidget(self.btn_download)

        self.btn_extract = QPushButton("Install from Offline ZIP...")
        self.btn_extract.setObjectName("secondary")
        self.btn_extract.clicked.connect(self.start_extraction)
        self.btn_extract.setEnabled(False)
        btn_layout.addWidget(self.btn_extract)
        
        layout.addLayout(btn_layout)

    def check_models(self):
        for i in reversed(range(self.scroll_layout.count())): 
            item = self.scroll_layout.itemAt(i)
            if item:
                w = item.widget()
                if w: w.setParent(None)

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
            self.summary_label.setText(f"All {total} models are correctly installed at {MODELS_DIR}!")
            self.btn_download.hide()
            self.btn_extract.hide()
        else:
            self.summary_label.setText(f"{total - installed_count} model(s) are missing. Select a method to install them.")
            self.btn_download.setEnabled(True)
            self.btn_extract.setEnabled(True)

    def start_download(self):
        if not self.models_to_download:
            return
        
        reply = QMessageBox.question(self, "Download Models", "This requires an active internet connection and may download several gigabytes. Continue?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No:
            return

        self.btn_download.setEnabled(False)
        self.btn_extract.setEnabled(False)
        self.btn_close.setText("Cancel")
        self.progress_bar.show()
        
        self.worker = DownloadWorker(self.models_to_download)
        self.worker.progress.connect(self.update_progress)
        self.worker.status.connect(self.update_status)
        self.worker.error.connect(self.on_error)
        self.worker.finished_all.connect(self.on_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def start_extraction(self):
        zip_path, _ = QFileDialog.getOpenFileName(self, "Select Models ZIP", "", "ZIP Files (*.zip)")
        if not zip_path:
            return

        self.btn_download.setEnabled(False)
        self.btn_extract.setEnabled(False)
        self.btn_close.setText("Cancel")
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        
        extract_target = BASE_DIR
        
        self.worker = ExtractWorker(zip_path, extract_target)
        self.worker.progress.connect(self.update_progress)
        self.worker.status.connect(self.update_status)
        self.worker.error.connect(self.on_error)
        self.worker.finished_all.connect(self.on_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def update_progress(self, current, total):
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
        else:
            self.progress_bar.setMaximum(0) # Indeterminate
            self.progress_bar.setValue(0)

    def update_status(self, text):
        self.status_label.setText(text)

    def on_error(self, err_text):
        self.status_label.setText(f"Error: {err_text}")
        self.status_label.setStyleSheet("color: #ef4444; font-size: 12px;")

    def on_finished(self):
        self.btn_close.setText("Close")
        self.progress_bar.hide()
        self.status_label.setStyleSheet("color: #10b981; font-size: 12px; font-weight: bold;")
        self.check_models()

    def close_dialog(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
        self.accept()

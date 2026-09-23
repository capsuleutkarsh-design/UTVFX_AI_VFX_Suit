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
from PySide6.QtGui import QColor, QPalette

try:
    from huggingface_hub import snapshot_download
except ImportError:
    snapshot_download = None

from utvfx.core.settings_manager import SettingsManager
from utvfx.ui import icons, theme

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
            self.status.emit("All downloads completed.")
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
                self.status.emit("Extraction completed.")
        except Exception as e:
            self.error.emit(f"Extraction failed: {str(e)}")
            
        self.finished_all.emit()

    def cancel(self):
        self.is_cancelled = True


class ModelDownloaderDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI models")
        self.setMinimumSize(640, 460)

        self.worker = None
        self.models_to_download = []
        self._had_error = False
        self.setup_ui()
        self.check_models()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACING)
        layout.setContentsMargins(14, 12, 14, 12)

        title = theme.set_role(QLabel("AI models"), "title")
        layout.addWidget(title)

        self.summary_label = theme.set_role(QLabel("Checking models..."), "dim")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("PanelBody")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setSpacing(0)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.scroll_content)
        layout.addWidget(scroll, 1)

        self.progress_container = QWidget()
        prog_layout = QVBoxLayout(self.progress_container)
        prog_layout.setContentsMargins(0, 0, 0, 0)
        prog_layout.setSpacing(4)

        self.status_label = theme.set_role(QLabel(""), "dim")
        self.status_label.setWordWrap(True)
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

        self.btn_extract = QPushButton("Install from offline ZIP...")
        self.btn_extract.setIcon(icons.icon("open"))
        self.btn_extract.clicked.connect(self.start_extraction)
        self.btn_extract.setEnabled(False)
        btn_layout.addWidget(self.btn_extract)

        self.btn_download = QPushButton("Download from internet")
        self.btn_download.setIcon(icons.icon("output", theme.TEXT_ON_ACCENT))
        theme.set_role(self.btn_download, "primary")
        self.btn_download.clicked.connect(self.start_download)
        self.btn_download.setEnabled(False)
        btn_layout.addWidget(self.btn_download)

        layout.addLayout(btn_layout)

    @staticmethod
    def _separator():
        line = QFrame()
        line.setFixedHeight(1)
        line.setAutoFillBackground(True)
        palette = line.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(theme.BORDER))
        line.setPalette(palette)
        return line

    def check_models(self):
        for i in reversed(range(self.scroll_layout.count())):
            item = self.scroll_layout.itemAt(i)
            if item:
                w = item.widget()
                if w: w.setParent(None)

        self.models_to_download = []
        installed_count = 0
        for index, model in enumerate(MODELS):
            expected_file = os.path.join(model["path"], model["check_file"])
            is_installed = os.path.exists(expected_file)

            if is_installed:
                installed_count += 1
            else:
                self.models_to_download.append(model)

            if index:
                self.scroll_layout.addWidget(self._separator())

            item_widget = QFrame()
            item_widget.setObjectName("model_item")
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(10, 6, 10, 6)
            item_layout.setSpacing(theme.SPACING)

            name_lbl = QLabel(model["name"])

            status_icon = QLabel()
            status_icon.setPixmap(icons.pixmap(
                "check" if is_installed else "clear", 14,
                theme.SUCCESS if is_installed else theme.ERROR))
            status_lbl = theme.set_role(QLabel("Installed" if is_installed else "Missing"),
                                        "ok" if is_installed else "error")

            item_layout.addWidget(name_lbl)
            item_layout.addStretch()
            item_layout.addWidget(status_icon)
            item_layout.addWidget(status_lbl)
            self.scroll_layout.addWidget(item_widget)

        total = len(MODELS)
        if installed_count == total:
            self.summary_label.setText(f"All {total} models are installed in {MODELS_DIR}.")
            self.btn_download.hide()
            self.btn_extract.hide()
        else:
            self.summary_label.setText(
                f"{total - installed_count} of {total} models are missing. "
                "Download them, or install them from an offline ZIP.")
            self.btn_download.setEnabled(True)
            self.btn_extract.setEnabled(True)

    def start_download(self):
        if not self.models_to_download:
            return

        reply = QMessageBox.question(self, "Download models", "This needs an internet connection and may download several gigabytes. Continue?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No:
            return

        self._had_error = False
        theme.set_role(self.status_label, "dim")
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
        zip_path, _ = QFileDialog.getOpenFileName(self, "Select models ZIP", "", "ZIP files (*.zip)")
        if not zip_path:
            return

        self._had_error = False
        theme.set_role(self.status_label, "dim")
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
        self._had_error = True
        self.status_label.setText(f"Error: {err_text}")
        theme.set_role(self.status_label, "error")

    def on_finished(self):
        self.btn_close.setText("Close")
        self.progress_bar.hide()
        if not self._had_error:
            theme.set_role(self.status_label, "ok")
        self.check_models()

    def close_dialog(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
        self.accept()

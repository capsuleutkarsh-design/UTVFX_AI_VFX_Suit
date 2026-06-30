import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, 
    QFileDialog, QMessageBox, QFrame, QGroupBox
)
from PySide6.QtCore import Qt
from core_ui.settings_manager import SettingsManager

class SettingsDialog(QDialog):
    def __init__(self, parent=None, download_callback=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Settings")
        self.setMinimumWidth(500)
        self.download_callback = download_callback
        
        self.setStyleSheet("""
            QDialog {
                background-color: #121212;
            }
            QLabel {
                color: #e5e5e5;
                font-family: 'Inter';
            }
            QLineEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #3f3f46;
                padding: 6px;
                border-radius: 4px;
            }
            QPushButton {
                background-color: #27272a;
                color: #ffffff;
                border: 1px solid #3f3f46;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3f3f46;
            }
            QGroupBox {
                color: #f59e0b;
                border: 1px solid #3f3f46;
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
            }
        """)

        self.settings_manager = SettingsManager()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # Paths Group
        path_group = QGroupBox("Directory Settings")
        path_layout = QVBoxLayout(path_group)
        
        # Output Directory
        out_layout = QHBoxLayout()
        out_layout.addWidget(QLabel("Default Output Folder:"))
        self.out_edit = QLineEdit(self.settings_manager.get("output_dir", ""))
        self.out_edit.setReadOnly(True)
        out_layout.addWidget(self.out_edit)
        btn_out_browse = QPushButton("Browse")
        btn_out_browse.clicked.connect(lambda: self.browse_folder(self.out_edit, "output_dir"))
        out_layout.addWidget(btn_out_browse)
        path_layout.addLayout(out_layout)
        
        # Cache Directory
        cache_layout = QHBoxLayout()
        cache_layout.addWidget(QLabel("Temp / Cache Folder:"))
        self.cache_edit = QLineEdit(self.settings_manager.get("cache_dir", ""))
        self.cache_edit.setReadOnly(True)
        cache_layout.addWidget(self.cache_edit)
        btn_cache_browse = QPushButton("Browse")
        btn_cache_browse.clicked.connect(lambda: self.browse_folder(self.cache_edit, "cache_dir"))
        cache_layout.addWidget(btn_cache_browse)
        path_layout.addLayout(cache_layout)
        
        layout.addWidget(path_group)
        
        # Maintenance Group
        maint_group = QGroupBox("Maintenance & Tools")
        maint_layout = QVBoxLayout(maint_group)
        
        btn_clear_cache = QPushButton("🗑️ Clear Cache (Delete all junk files)")
        btn_clear_cache.setStyleSheet("""
            QPushButton {
                background-color: #7f1d1d;
                color: white;
                border: 1px solid #991b1b;
            }
            QPushButton:hover {
                background-color: #991b1b;
            }
        """)
        btn_clear_cache.clicked.connect(self.clear_cache)
        maint_layout.addWidget(btn_clear_cache)
        
        btn_download = QPushButton("⬇️ Download AI Models")
        btn_download.setStyleSheet("""
            QPushButton {
                background-color: #1e3a8a;
                color: white;
                border: 1px solid #1e40af;
            }
            QPushButton:hover {
                background-color: #1e40af;
            }
        """)
        btn_download.clicked.connect(self.on_download_models)
        maint_layout.addWidget(btn_download)
        
        layout.addWidget(maint_group)

        # Bottom Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)
        
        layout.addLayout(btn_layout)

    def browse_folder(self, line_edit, setting_key):
        folder = QFileDialog.getExistingDirectory(self, "Select Directory", line_edit.text())
        if folder:
            line_edit.setText(folder)
            self.settings_manager.set(setting_key, folder)

    def clear_cache(self):
        reply = QMessageBox.question(
            self, 'Clear Cache',
            "Are you sure you want to delete all temporary cache files? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            success = self.settings_manager.clear_cache()
            if success:
                QMessageBox.information(self, "Success", "Cache cleared successfully.")
            else:
                QMessageBox.warning(self, "Error", "Failed to clear some cache files. They might be in use.")

    def on_download_models(self):
        if self.download_callback:
            self.download_callback()

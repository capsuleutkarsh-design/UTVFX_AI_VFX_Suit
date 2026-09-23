import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt
from utvfx.core.settings_manager import SettingsManager
from utvfx.ui import icons, theme


class SettingsDialog(QDialog):
    def __init__(self, parent=None, download_callback=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        self.download_callback = download_callback

        self.settings_manager = SettingsManager()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(theme.SPACING)

        # Folders
        layout.addWidget(theme.set_role(QLabel("Folders"), "section"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACING)
        grid.setVerticalSpacing(theme.SPACING)
        grid.setColumnStretch(1, 1)

        self.out_edit = QLineEdit(self.settings_manager.get("output_dir", ""))
        self.out_edit.setReadOnly(True)
        btn_out_browse = QPushButton("Browse...")
        btn_out_browse.setIcon(icons.icon("folder"))
        btn_out_browse.clicked.connect(lambda: self.browse_folder(self.out_edit, "output_dir"))
        self._add_row(grid, 0, "Default output", self.out_edit, btn_out_browse)

        self.cache_edit = QLineEdit(self.settings_manager.get("cache_dir", ""))
        self.cache_edit.setReadOnly(True)
        btn_cache_browse = QPushButton("Browse...")
        btn_cache_browse.setIcon(icons.icon("folder"))
        btn_cache_browse.clicked.connect(lambda: self.browse_folder(self.cache_edit, "cache_dir"))
        self._add_row(grid, 1, "Temp and cache", self.cache_edit, btn_cache_browse)

        layout.addLayout(grid)
        layout.addSpacing(8)

        # Maintenance
        layout.addWidget(theme.set_role(QLabel("Maintenance"), "section"))

        maint_grid = QGridLayout()
        maint_grid.setHorizontalSpacing(theme.SPACING)
        maint_grid.setVerticalSpacing(theme.SPACING)
        maint_grid.setColumnStretch(1, 1)

        btn_clear_cache = QPushButton("Clear cache")
        btn_clear_cache.setIcon(icons.icon("trash"))
        theme.set_role(btn_clear_cache, "danger")
        btn_clear_cache.clicked.connect(self.clear_cache)
        self._add_row(maint_grid, 0, "Delete all temporary files", None, btn_clear_cache)

        btn_download = QPushButton("AI models...")
        btn_download.setIcon(icons.icon("output"))
        btn_download.clicked.connect(self.on_download_models)
        self._add_row(maint_grid, 1, "Check, download or install models", None, btn_download)

        layout.addLayout(maint_grid)
        layout.addStretch()
        layout.addSpacing(8)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_close = QPushButton("Close")
        theme.set_role(btn_close, "primary")
        btn_close.setDefault(True)
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

    @staticmethod
    def _add_row(grid, row, label_text, field, button):
        label = theme.set_role(QLabel(label_text), "dim")
        if field is None:
            grid.addWidget(label, row, 0, 1, 2)
        else:
            label.setMinimumWidth(110)
            grid.addWidget(label, row, 0)
            grid.addWidget(field, row, 1)
        grid.addWidget(button, row, 2)

    def browse_folder(self, line_edit, setting_key):
        folder = QFileDialog.getExistingDirectory(self, "Select folder", line_edit.text())
        if folder:
            line_edit.setText(folder)
            self.settings_manager.set(setting_key, folder)

    def clear_cache(self):
        reply = QMessageBox.question(
            self, "Clear cache",
            "Delete all temporary cache files? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            success = self.settings_manager.clear_cache()
            if success:
                QMessageBox.information(self, "Clear cache", "Cache cleared.")
            else:
                QMessageBox.warning(self, "Clear cache", "Some cache files could not be deleted. They might be in use.")

    def on_download_models(self):
        if self.download_callback:
            self.download_callback()

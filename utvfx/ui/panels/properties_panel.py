from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QLineEdit,
    QCheckBox, QComboBox, QScrollArea, QPushButton, QTextEdit,
    QTabWidget, QRadioButton, QColorDialog, QFileDialog, QFrame, QProgressBar, QInputDialog, QMessageBox, QSizePolicy
)
from utvfx.ui import icons, theme
from utvfx.ui.panels.param_widgets import build_param_widget, sentence_case
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont, QColor
import os
import json
from utvfx.core.data_model import NODES_REGISTRY

class PropertiesPanel(QWidget):
    execute_node_requested = Signal(str)
    cancel_execution_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_node = None
        self.node_def = None
        self.console_widget = None
        self.node_logs = {} # node_id -> list of log messages
        self.node_progress = {} # node_id -> int
        
        self.setup_ui()

        
    def setup_ui(self):
        self.setObjectName("Panel")
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header: category colour chip + node name
        header = QWidget()
        header.setObjectName("PanelHeader")
        header.setFixedHeight(30)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(10, 0, 10, 0)
        h_layout.setSpacing(theme.SPACING)

        self.category_chip = QFrame()
        self.category_chip.setFixedSize(10, 10)
        self.category_chip.hide()
        h_layout.addWidget(self.category_chip)

        self.lbl_title = QLabel("No node selected")
        theme.set_role(self.lbl_title, "dim")
        self.lbl_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        h_layout.addWidget(self.lbl_title, 1)

        # Stretch handled by lbl_title
        main_layout.addWidget(header)

        from PySide6.QtWidgets import QSplitter
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)

        # Scroll Area for properties (Top Half)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.content_widget = QWidget()
        self.content_widget.setObjectName("PanelBody")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 8, 10, 10)
        self.content_layout.setSpacing(2)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll.setWidget(self.content_widget)
        self.splitter.addWidget(self.scroll)

        # Console Area (Bottom Half)
        self.console_container = QWidget()
        self.console_container.setObjectName("PanelBody")
        c_layout = QVBoxLayout(self.console_container)
        c_layout.setContentsMargins(10, 6, 10, 10)
        c_layout.setSpacing(4)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        c_layout.addWidget(self.progress_bar)

        # Mini console header
        console_header = QHBoxLayout()
        console_header.setContentsMargins(0, 0, 0, 0)

        lbl_console = theme.set_role(QLabel("Console"), "section")
        console_header.addWidget(lbl_console)

        console_header.addStretch()

        btn_copy = QPushButton("Copy logs")
        btn_copy.setIcon(icons.icon("copy"))
        theme.set_role(btn_copy, "flat")
        btn_copy.clicked.connect(self._copy_logs)
        console_header.addWidget(btn_copy)
        c_layout.addLayout(console_header)

        self.console_widget = QTextEdit()
        self.console_widget.setReadOnly(True)
        theme.set_role(self.console_widget, "console")
        self.console_widget.setFont(theme.mono_font())
        self.console_widget.setPlaceholderText("Node logs appear here while it runs.")
        c_layout.addWidget(self.console_widget)

        self.splitter.addWidget(self.console_container)
        self.splitter.setSizes([600, 200]) # 3:1 ratio

        main_layout.addWidget(self.splitter)

    def _clear_layout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                self._clear_layout(child.layout())

    @Slot()
    def refresh_ui(self):
        if getattr(self, "current_node", None):
            current_tab = 0
            if getattr(self, "tabs", None) is not None:
                current_tab = self.tabs.currentIndex()
                
            self.set_node(self.current_node)
            
            if getattr(self, "tabs", None) is not None and current_tab < self.tabs.count():
                self.tabs.setCurrentIndex(current_tab)


    def _set_title(self, text, role, chip_colour=None):
        self.lbl_title.setText(text)
        theme.set_role(self.lbl_title, role)
        if chip_colour:
            self.category_chip.setStyleSheet(
                f"background: {chip_colour}; border: 1px solid {theme.BORDER}; border-radius: 2px;")
            self.category_chip.show()
        else:
            self.category_chip.hide()

    def set_node(self, node_item):
        self.current_node = node_item

        # Clear existing
        self._clear_layout(self.content_layout)

        if not node_item:
            self._set_title("No node selected", "dim")
            return

        self.node_def = NODES_REGISTRY.get(node_item.plugin_type)
        if not self.node_def:
            self._set_title("Unknown node", "error")
            return

        color = self.node_def.get("color", theme.ACCENT)
        self._set_title(self.node_def['name'], "title", theme.node_colour(node_item.plugin_type))
        self.lbl_title.setToolTip(self.node_def.get("category", ""))

        # Build parameters
        params = self.node_def.get("parameters", [])
        if not params:
            lbl = theme.set_role(QLabel("No parameters."), "faint")
            self.content_layout.addWidget(lbl)
            self._build_execution_section(color)
            return

        has_tabs = any("tab" in p for p in params)
        if has_tabs:
            self.tabs = QTabWidget()
            self.tabs.setUsesScrollButtons(False)
            self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
            self.tabs.tabBar().setExpanding(False)
            # Layout only: slightly tighter tabs so a five-tab node still fits
            # the panel's 420 px minimum width (long names elide; tooltips hold
            # the full name).
            self.tabs.tabBar().setStyleSheet("QTabBar::tab { padding: 5px 8px; }")
            tab_dict = {}
            for param in params:
                t_name = param.get("tab", "General")
                if t_name not in tab_dict: tab_dict[t_name] = []
                tab_dict[t_name].append(param)

            for t_name, t_params in tab_dict.items():
                w = QWidget()
                l = QVBoxLayout(w)
                l.setContentsMargins(0, 8, 0, 4)
                l.setSpacing(2)
                l.setAlignment(Qt.AlignmentFlag.AlignTop)
                for p in t_params:
                    l.addWidget(self._build_param_widget(p, color))
                l.addStretch(1)
                index = self.tabs.addTab(w, sentence_case(t_name).replace("&", "&&"))
                self.tabs.setTabToolTip(index, t_name)

            self.content_layout.addWidget(self.tabs)
        else:
            self.tabs = None
            for param in params:
                group = self._build_param_widget(param, color)
                self.content_layout.addWidget(group)

        # Add execution section if applicable
        self._build_execution_section(color)

        # Force a layout recalculation to prevent the panel from clipping its contents
        self.content_widget.adjustSize()
        self.content_layout.update()

    def _build_param_widget(self, param, color):
        return build_param_widget(self, param, color)

    def _build_execution_section(self, color):
        self.content_layout.addSpacing(12)

        # Execute buttons
        exec_layout = QHBoxLayout()
        exec_layout.setContentsMargins(0, 0, 0, 0)
        exec_layout.setSpacing(theme.SPACING)

        self.btn_run = QPushButton("Execute")
        self.btn_run.setIcon(icons.icon("play", theme.TEXT_ON_ACCENT))
        self.btn_run.setToolTip(f"Execute {self.node_def['name']}")
        self.btn_run.setMinimumHeight(28)
        theme.set_role(self.btn_run, "primary")
        self.btn_run.clicked.connect(self._on_execute_clicked)
        exec_layout.addWidget(self.btn_run, 1)

        self.btn_cancel = QPushButton("Stop")
        self.btn_cancel.setIcon(icons.icon("stop"))
        self.btn_cancel.setMinimumHeight(28)
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        exec_layout.addWidget(self.btn_cancel)

        self.content_layout.addLayout(exec_layout)

        # Restore logs and progress if any exist for this node
        self.console_widget.clear()
        if self.current_node:
            logs = self.node_logs.get(self.current_node.node_id, [])
            for msg in logs:
                self.console_widget.append(msg)

            if self.current_node.node_id in self.node_progress:
                self.progress_bar.setValue(self.node_progress[self.current_node.node_id])
                self.progress_bar.show()
            else:
                self.progress_bar.setValue(0)
                self.progress_bar.hide()

    def _on_execute_clicked(self):
        if self.current_node:
            self.node_logs[self.current_node.node_id] = [] # Clear logs on new execution
            self.node_progress[self.current_node.node_id] = 0 # Clear progress
            if hasattr(self, 'console_widget') and self.console_widget:
                self.console_widget.clear()
            if hasattr(self, 'progress_bar') and self.progress_bar:
                self.progress_bar.setValue(0)
                self.progress_bar.show()
            self.execute_node_requested.emit(self.current_node.node_id)
            
    def _on_cancel_clicked(self):
        if self.current_node:
            self.cancel_execution_requested.emit(self.current_node.node_id)
            
    @Slot(str, str)
    def append_console_log(self, node_id, message):
        if node_id not in self.node_logs:
            self.node_logs[node_id] = []
        self.node_logs[node_id].append(message)
        
        if self.current_node and self.current_node.node_id == node_id:
            if hasattr(self, 'console_widget') and self.console_widget:
                self.console_widget.append(message)
                
    @Slot(str, int)
    def update_progress(self, node_id, percentage):
        self.node_progress[node_id] = percentage
        if self.current_node and self.current_node.node_id == node_id:
            if hasattr(self, 'progress_bar') and self.progress_bar:
                self.progress_bar.show()
                self.progress_bar.setValue(percentage)

    def _copy_logs(self):
        if self.console_widget:
            from PySide6.QtGui import QGuiApplication
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(self.console_widget.toPlainText())


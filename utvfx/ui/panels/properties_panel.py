from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QLineEdit,
    QCheckBox, QComboBox, QScrollArea, QPushButton, QTextEdit,
    QTabWidget, QRadioButton, QColorDialog, QFileDialog, QFrame, QProgressBar, QInputDialog, QMessageBox, QSizePolicy
)
from utvfx.ui.panels.param_widgets import build_param_widget
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
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Header
        header = QWidget()
        header.setFixedHeight(50)
        header.setStyleSheet("background-color: #121212; border-bottom: 1px solid #27272a;")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(10, 0, 10, 0)
        
        self.lbl_title = QLabel("NO NODE SELECTED")
        self.lbl_title.setStyleSheet("font-family: 'Space Grotesk'; font-size: 13px; font-weight: bold; color: #71717a; letter-spacing: 2px;")
        self.lbl_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        h_layout.addWidget(self.lbl_title, 1)
        
        # Stretch handled by lbl_title
        main_layout.addWidget(header)
        
        from PySide6.QtWidgets import QSplitter
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Scroll Area for properties (Top Half)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background-color: #0a0a0a; }")
        
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background-color: #0a0a0a;")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(12, 12, 12, 12)
        self.content_layout.setSpacing(4)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.scroll.setWidget(self.content_widget)
        self.splitter.addWidget(self.scroll)
        
        # Console Area (Bottom Half)
        self.console_container = QWidget()
        self.console_container.setStyleSheet("background-color: #0a0a0a;")
        c_layout = QVBoxLayout(self.console_container)
        c_layout.setContentsMargins(12, 0, 12, 12)
        c_layout.setSpacing(8)
        
        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #27272a;
                border-radius: 4px;
                background-color: #09090b;
                text-align: center;
                color: #fafafa;
                font-family: 'Inter';
                font-size: 10px;
                font-weight: bold;
                height: 16px;
                margin-top: 8px;
            }
            QProgressBar::chunk {
                background-color: #f59e0b; /* default color, updated per node */
                border-radius: 3px;
            }
        """)
        self.progress_bar.hide()
        c_layout.addWidget(self.progress_bar)
        
        # Mini console header
        console_header = QHBoxLayout()
        console_header.setContentsMargins(0, 0, 0, 0)
        
        lbl_console = QLabel("NODE CONSOLE")
        lbl_console.setStyleSheet("font-family: 'Inter'; font-size: 10px; font-weight: bold; color: #a1a1aa; letter-spacing: 1px;")
        console_header.addWidget(lbl_console)
        
        console_header.addStretch()
        
        btn_copy = QPushButton("Copy Logs")
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #3b82f6;
                font-family: 'Inter';
                font-size: 10px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover { color: #60a5fa; }
        """)
        btn_copy.clicked.connect(self._copy_logs)
        console_header.addWidget(btn_copy)
        c_layout.addLayout(console_header)
        
        self.console_widget = QTextEdit()
        self.console_widget.setReadOnly(True)
        self.console_widget.setStyleSheet("""
            QTextEdit {
                background-color: #09090b;
                color: #e4e4e7;
                font-family: 'JetBrains Mono';
                font-size: 11px;
                border: 1px solid #1f1f22;
                border-radius: 6px;
                padding: 12px;
            }
        """)
        self.console_widget.setPlaceholderText(">> Node logs will stream here during execution...")
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


    def set_node(self, node_item):
        self.current_node = node_item
        
        # Clear existing
        self._clear_layout(self.content_layout)
                
        if not node_item:
            self.lbl_title.setText("NO NODE SELECTED")
            self.lbl_title.setStyleSheet("font-family: 'Space Grotesk'; font-size: 13px; font-weight: bold; color: #71717a; letter-spacing: 2px;")
            return
            
        self.node_def = NODES_REGISTRY.get(node_item.plugin_type)
        if not self.node_def:
            self.lbl_title.setText("UNKNOWN NODE")
            return
        
        color = self.node_def.get("color", "#f59e0b")
        self.lbl_title.setText(self.node_def['name'].upper())
        self.lbl_title.setStyleSheet(f"font-family: 'Space Grotesk'; font-size: 12px; font-weight: bold; color: {color}; letter-spacing: 1px;")
        
        # Build parameters
        params = self.node_def.get("parameters", [])
        if not params:
            lbl = QLabel("No configurable parameters.")
            lbl.setStyleSheet("color: #71717a; font-style: italic;")
            self.content_layout.addWidget(lbl)
            self._build_execution_section(color)
            return
            
        has_tabs = any("tab" in p for p in params)
        if has_tabs:
            self.tabs = QTabWidget()
            self.tabs.setStyleSheet("""
                QTabWidget::pane { border: none; top: 0px; }
                QTabBar::tab { background-color: transparent; color: #a1a1aa; border: none; border-bottom: 2px solid transparent; padding: 8px 16px; font-family: 'Inter'; font-weight: bold; font-size: 12px; margin-right: 4px; }
                QTabBar::tab:selected { color: #fafafa; border-bottom: 2px solid """ + color + """; }
                QTabBar::tab:hover:!selected { color: #e4e4e7; border-bottom: 2px solid #3f3f46; }
            """)
            tab_dict = {}
            for param in params:
                t_name = param.get("tab", "General")
                if t_name not in tab_dict: tab_dict[t_name] = []
                tab_dict[t_name].append(param)
                
            for t_name, t_params in tab_dict.items():
                w = QWidget()
                w.setStyleSheet("background: transparent;")
                l = QVBoxLayout(w)
                l.setContentsMargins(0,16,0,16)
                l.setSpacing(12)
                l.setAlignment(Qt.AlignmentFlag.AlignTop)
                for p in t_params:
                    l.addWidget(self._build_param_widget(p, color))
                self.tabs.addTab(w, t_name)
                
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
        self.content_layout.addSpacing(16)
        
        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("background-color: #27272a; border: none; max-height: 1px;")
        self.content_layout.addWidget(div)
        
        self.content_layout.addSpacing(16)
        
        # Execute buttons
        exec_layout = QHBoxLayout()
        exec_layout.setContentsMargins(0, 0, 0, 0)
        
        self.btn_run = QPushButton(f"Execute {self.node_def['name']}")
        self.btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: #000000;
                font-family: 'Inter';
                font-weight: 800;
                font-size: 13px;
                letter-spacing: 0.5px;
                border: none;
                border-radius: 6px;
                padding: 14px;
            }}
            QPushButton:hover {{
                background-color: {color}dd;
            }}
            QPushButton:pressed {{
                background-color: {color}bb;
            }}
        """)
        self.btn_run.clicked.connect(self._on_execute_clicked)
        exec_layout.addWidget(self.btn_run)
        
        self.btn_cancel = QPushButton("Stop")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #3f3f46;
                color: #fafafa;
                font-family: 'Inter';
                font-weight: bold;
                font-size: 12px;
                border: none;
                border-radius: 6px;
                padding: 12px;
            }
            QPushButton:hover {
                background-color: #52525b;
            }
        """)
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        exec_layout.addWidget(self.btn_cancel)
        
        self.content_layout.addLayout(exec_layout)
        
        # Update Progress Bar Color
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid #27272a;
                border-radius: 4px;
                background-color: #09090b;
                text-align: center;
                color: #fafafa;
                font-family: 'Inter';
                font-size: 10px;
                font-weight: bold;
                height: 16px;
                margin-top: 8px;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 3px;
            }}
        """)
        
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


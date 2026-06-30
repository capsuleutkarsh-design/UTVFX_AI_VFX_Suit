from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QLineEdit,
    QCheckBox, QComboBox, QScrollArea, QPushButton, QTextEdit,
    QTabWidget, QRadioButton, QColorDialog, QFileDialog, QFrame, QProgressBar, QInputDialog, QMessageBox
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont, QColor
import os
import json
from .data_model import NODES_REGISTRY

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
        h_layout.setContentsMargins(20, 0, 20, 0)
        
        self.lbl_title = QLabel("NO NODE SELECTED")
        self.lbl_title.setStyleSheet("font-family: 'Space Grotesk'; font-size: 13px; font-weight: bold; color: #71717a; letter-spacing: 2px;")
        h_layout.addWidget(self.lbl_title)
        
        h_layout.addStretch()
        
        self.cb_presets = QComboBox()
        self.cb_presets.setStyleSheet("""
            QComboBox { background-color: #1a1a1e; color: #fafafa; border: 1px solid #27272a; border-radius: 4px; padding: 4px 8px; font-size: 11px; }
            QComboBox::drop-down { border: none; }
        """)
        self.cb_presets.setMinimumWidth(120)
        self.cb_presets.hide()
        h_layout.addWidget(self.cb_presets)
        
        self.btn_load_preset = QPushButton("Load")
        self.btn_load_preset.setStyleSheet("""
            QPushButton { background-color: #1a1a1e; color: #a1a1aa; border: 1px solid #27272a; border-radius: 4px; padding: 4px 10px; font-size: 11px; font-weight: bold; }
            QPushButton:hover { background-color: #27272a; color: white; }
        """)
        self.btn_load_preset.clicked.connect(self.load_preset)
        self.btn_load_preset.hide()
        h_layout.addWidget(self.btn_load_preset)
        
        self.btn_save_preset = QPushButton("Save")
        self.btn_save_preset.setStyleSheet("""
            QPushButton { background-color: #1a1a1e; color: #a1a1aa; border: 1px solid #27272a; border-radius: 4px; padding: 4px 10px; font-size: 11px; font-weight: bold; }
            QPushButton:hover { background-color: #27272a; color: white; }
        """)
        self.btn_save_preset.clicked.connect(self.save_preset)
        self.btn_save_preset.hide()
        h_layout.addWidget(self.btn_save_preset)
        
        main_layout.addWidget(header)
        
        from PySide6.QtWidgets import QSplitter
        self.splitter = QSplitter(Qt.Vertical)
        
        # Scroll Area for properties (Top Half)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background-color: #0a0a0a; }")
        
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background-color: #0a0a0a;")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(24, 24, 24, 24)
        self.content_layout.setSpacing(12)
        self.content_layout.setAlignment(Qt.AlignTop)
        
        self.scroll.setWidget(self.content_widget)
        self.splitter.addWidget(self.scroll)
        
        # Console Area (Bottom Half)
        self.console_container = QWidget()
        self.console_container.setStyleSheet("background-color: #0a0a0a;")
        c_layout = QVBoxLayout(self.console_container)
        c_layout.setContentsMargins(24, 0, 24, 24)
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
        btn_copy.setCursor(Qt.PointingHandCursor)
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
                color: #22c55e;
                font-family: 'JetBrains Mono';
                font-size: 11px;
                border: 1px solid #27272a;
                border-radius: 6px;
                padding: 8px;
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
        if self.current_node:
            self.set_node(self.current_node)

    def _refresh_presets_list(self):
        if not self.current_node: return
        self.cb_presets.clear()
        
        plugin_type = self.current_node.plugin_type
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        presets_dir = os.path.join(project_root, "presets", plugin_type)
        
        if os.path.exists(presets_dir):
            for f in os.listdir(presets_dir):
                if f.endswith(".json"):
                    self.cb_presets.addItem(f.replace(".json", ""))

    def save_preset(self):
        if not self.current_node: return
        
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset Name:")
        if ok and name:
            plugin_type = self.current_node.plugin_type
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            presets_dir = os.path.join(project_root, "presets", plugin_type)
            os.makedirs(presets_dir, exist_ok=True)
            
            filepath = os.path.join(presets_dir, f"{name}.json")
            with open(filepath, 'w') as f:
                json.dump(self.current_node.params, f, indent=4)
                
            self._refresh_presets_list()
            idx = self.cb_presets.findText(name)
            if idx >= 0:
                self.cb_presets.setCurrentIndex(idx)

    def load_preset(self):
        if not self.current_node: return
        
        name = self.cb_presets.currentText()
        if not name: return
        
        plugin_type = self.current_node.plugin_type
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        filepath = os.path.join(project_root, "presets", plugin_type, f"{name}.json")
        
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    preset_params = json.load(f)
                
                # Update current node params
                self.current_node.params.update(preset_params)
                
                # Rebuild UI
                self.set_node(self.current_node)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load preset: {e}")

    def set_node(self, node_item):
        self.current_node = node_item
        
        # Clear existing
        self._clear_layout(self.content_layout)
                
        if not node_item:
            self.lbl_title.setText("NO NODE SELECTED")
            self.lbl_title.setStyleSheet("font-family: 'Space Grotesk'; font-size: 13px; font-weight: bold; color: #71717a; letter-spacing: 2px;")
            self.btn_save_preset.hide()
            self.btn_load_preset.hide()
            self.cb_presets.hide()
            return
            
        self.node_def = NODES_REGISTRY.get(node_item.plugin_type)
        if not self.node_def:
            self.lbl_title.setText("UNKNOWN NODE")
            return
        
        self.btn_save_preset.show()
        self.btn_load_preset.show()
        self.cb_presets.show()
        self._refresh_presets_list()
            
        color = self.node_def.get("color", "#f59e0b")
        self.lbl_title.setText(f"PARAMS // {self.node_def['name'].upper()}")
        self.lbl_title.setStyleSheet(f"font-family: 'Space Grotesk'; font-size: 13px; font-weight: bold; color: {color}; letter-spacing: 2px;")
        
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
            tabs = QTabWidget()
            tabs.setStyleSheet("""
                QTabWidget::pane { border: 1px solid #27272a; border-radius: 4px; top: -1px; }
                QTabBar::tab { background-color: #121212; color: #a1a1aa; border: 1px solid #27272a; padding: 8px 16px; font-family: 'Inter'; font-weight: bold; font-size: 11px; }
                QTabBar::tab:selected { background-color: #18181b; color: #fafafa; border-bottom: 2px solid """ + color + """; }
            """)
            tab_dict = {}
            for param in params:
                t_name = param.get("tab", "General")
                if t_name not in tab_dict: tab_dict[t_name] = []
                tab_dict[t_name].append(param)
                
            for t_name, t_params in tab_dict.items():
                w = QWidget()
                l = QVBoxLayout(w)
                l.setContentsMargins(16,16,16,16)
                l.setSpacing(20)
                l.setAlignment(Qt.AlignTop)
                for p in t_params:
                    l.addWidget(self._build_param_widget(p, color))
                tabs.addTab(w, t_name)
                
            self.content_layout.addWidget(tabs)
        else:
            for param in params:
                group = self._build_param_widget(param, color)
                self.content_layout.addWidget(group)
            
        # Add execution section if applicable
        self._build_execution_section(color)
            
    def _build_param_widget(self, param, color):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Label
        lbl = QLabel(param["name"].upper())
        lbl.setStyleSheet("font-family: 'Inter'; font-size: 10px; font-weight: bold; color: #a1a1aa; letter-spacing: 1px;")
        layout.addWidget(lbl)
        
        ptype = param["type"]
        pid = param["id"]
        
        # Get value from node params, fallback to default
        if not hasattr(self.current_node, "params"):
            self.current_node.params = {}
            
        val = self.current_node.params.get(pid, param["value"])
        
        if ptype == "slider":
            h_layout = QHBoxLayout()
            h_layout.setContentsMargins(0,0,0,0)
            
            slider = QSlider(Qt.Horizontal)
            is_float = isinstance(param["step"], float)
            mult = 100 if is_float else 1
            
            slider.setRange(int(param["min"] * mult), int(param["max"] * mult))
            slider.setValue(int(val * mult))
            slider.setStyleSheet(f"QSlider::sub-page:horizontal {{ background: {color}; }}")
            
            val_lbl = QLabel(str(val))
            val_lbl.setStyleSheet(f"color: {color}; font-family: 'JetBrains Mono'; font-weight: bold; font-size: 12px; min-width: 50px;")
            val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            
            def on_change(v, l=val_lbl, m=mult, p=pid):
                actual_v = v / m
                l.setText(f"{actual_v:.2f}" if m == 100 else str(int(actual_v)))
                self.current_node.params[p] = actual_v
                
            def on_press(p=pid):
                slider.old_val = self.current_node.params.get(p, param["value"])
                
            def on_release(m=mult, p=pid):
                actual_v = slider.value() / m
                if hasattr(slider, 'old_val') and slider.old_val != actual_v:
                    scene = self.current_node.scene()
                    if scene and scene.undo_stack:
                        from core_ui.commands import ChangeParamCommand
                        cmd = ChangeParamCommand(self.current_node, p, slider.old_val, actual_v)
                        scene.undo_stack.push(cmd)
                
            slider.valueChanged.connect(on_change)
            slider.sliderPressed.connect(on_press)
            slider.sliderReleased.connect(on_release)
            
            h_layout.addWidget(slider)
            h_layout.addWidget(val_lbl)
            layout.addLayout(h_layout)
            
        elif ptype == "text" or ptype == "file":
            line = QLineEdit(str(val))
            line.setStyleSheet(f"background-color: #18181b; border: 1px solid #27272a; border-radius: 6px; padding: 10px; color: #fafafa; font-size: 12px;")
            
            def text_changed(t, p=pid):
                old_val = self.current_node.params.get(p, param["value"])
                scene = self.current_node.scene()
                if scene and scene.undo_stack:
                    from core_ui.commands import ChangeParamCommand
                    cmd = ChangeParamCommand(self.current_node, p, old_val, t)
                    scene.undo_stack.push(cmd)
                else:
                    self.current_node.params[p] = t
                    
            line.editingFinished.connect(lambda: text_changed(line.text()))
            
            if ptype == "file":
                line.setPlaceholderText("Select file path...")
                h = QHBoxLayout()
                btn = QPushButton("📂")
                btn.setFixedSize(36, 36)
                btn.setStyleSheet("background-color: #18181b; border: 1px solid #27272a; border-radius: 6px;")
                
                # We need QFileDialog here but to avoid cluttering we just let the Media Panel load logic override it.
                # If they click the folder icon here, let's open a dialog too.
                from PySide6.QtWidgets import QFileDialog
                def open_file(*args, l=line, p=pid):
                    path, _ = QFileDialog.getOpenFileName(self, "Select File")
                    if path:
                        l.setText(path)
                        text_changed(path, p)
                        
                btn.clicked.connect(open_file)
                
                h.addWidget(line)
                h.addWidget(btn)
                layout.addLayout(h)
            else:
                layout.addWidget(line)
                
        elif ptype == "select":
            combo = QComboBox()
            combo.addItems(param["options"])
            combo.setCurrentText(str(val))
            combo.setStyleSheet(f"background-color: #18181b; border: 1px solid #27272a; border-radius: 6px; padding: 8px; color: #fafafa; font-size: 12px;")
            
            def combo_changed(t, p=pid):
                old_val = self.current_node.params.get(p, param["value"])
                scene = self.current_node.scene()
                if scene and scene.undo_stack:
                    from core_ui.commands import ChangeParamCommand
                    cmd = ChangeParamCommand(self.current_node, p, old_val, t)
                    scene.undo_stack.push(cmd)
                else:
                    self.current_node.params[p] = t
                    
            combo.currentTextChanged.connect(combo_changed)
            layout.addWidget(combo)
            
        elif ptype == "checkbox":
            chk = QCheckBox("Enabled")
            chk.setChecked(bool(val))
            chk.setStyleSheet(f"""
                QCheckBox {{ color: {color}; font-weight: bold; font-size: 12px; }}
                QCheckBox::indicator {{ width: 14px; height: 14px; background: #27272a; border: 1px solid #52525b; border-radius: 3px; }}
                QCheckBox::indicator:hover {{ border: 1px solid {color}; }}
                QCheckBox::indicator:checked {{ background: {color}; border: 1px solid {color}; }}
            """)
            
            def checkbox_changed(checked, p=pid):
                old_val = self.current_node.params.get(p, param["value"])
                scene = self.current_node.scene()
                if scene and scene.undo_stack:
                    from core_ui.commands import ChangeParamCommand
                    cmd = ChangeParamCommand(self.current_node, p, old_val, checked)
                    scene.undo_stack.push(cmd)
                else:
                    self.current_node.params[p] = checked
                    
            chk.toggled.connect(checkbox_changed)
            layout.addWidget(chk)
            
        elif ptype == "radio":
            h = QHBoxLayout()
            h.setContentsMargins(0,0,0,0)
            from PySide6.QtWidgets import QRadioButton
            for opt in param["options"]:
                rb = QRadioButton(opt)
                rb.setStyleSheet(f"QRadioButton {{ color: #fafafa; font-size: 12px; }} QRadioButton::indicator:checked {{ background-color: {color}; border: 2px solid {color}; }}")
                if str(val) == opt:
                    rb.setChecked(True)
                    
                def radio_changed(checked, o=opt, p=pid):
                    if checked:
                        old_val = self.current_node.params.get(p, param["value"])
                        scene = self.current_node.scene()
                        if scene and scene.undo_stack:
                            from core_ui.commands import ChangeParamCommand
                            cmd = ChangeParamCommand(self.current_node, p, old_val, o)
                            scene.undo_stack.push(cmd)
                        else:
                            self.current_node.params[p] = o
                            
                rb.toggled.connect(radio_changed)
                h.addWidget(rb)
            layout.addLayout(h)
            
        elif ptype == "color":
            from PySide6.QtWidgets import QColorDialog
            btn = QPushButton()
            btn.setFixedSize(60, 24)
            btn.setStyleSheet(f"background-color: {val}; border: 1px solid #27272a; border-radius: 4px;")
            
            def choose_color(b=btn, p=pid, init_color=val):
                c = QColorDialog.getColor(QColor(self.current_node.params.get(p, init_color)), self, "Select Color")
                if c.isValid():
                    h_color = c.name()
                    b.setStyleSheet(f"background-color: {h_color}; border: 1px solid #27272a; border-radius: 4px;")
                    
                    old_val = self.current_node.params.get(p, param["value"])
                    scene = self.current_node.scene()
                    if scene and scene.undo_stack:
                        from core_ui.commands import ChangeParamCommand
                        cmd = ChangeParamCommand(self.current_node, p, old_val, h_color)
                        scene.undo_stack.push(cmd)
                    else:
                        self.current_node.params[p] = h_color
                    
            btn.clicked.connect(choose_color)
            layout.addWidget(btn)
            
        return container

    def _build_execution_section(self, color):
        self.content_layout.addSpacing(16)
        
        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("background-color: #27272a; border: none; max-height: 1px;")
        self.content_layout.addWidget(div)
        
        self.content_layout.addSpacing(16)
        
        # Execute buttons
        exec_layout = QHBoxLayout()
        exec_layout.setContentsMargins(0, 0, 0, 0)
        
        self.btn_run = QPushButton(f"Execute {self.node_def['name']}")
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: #000000;
                font-family: 'Inter';
                font-weight: bold;
                font-size: 12px;
                border: none;
                border-radius: 6px;
                padding: 12px;
            }}
            QPushButton:hover {{
                background-color: {color}dd;
            }}
        """)
        self.btn_run.clicked.connect(self._on_execute_clicked)
        exec_layout.addWidget(self.btn_run)
        
        self.btn_cancel = QPushButton("Stop")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
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


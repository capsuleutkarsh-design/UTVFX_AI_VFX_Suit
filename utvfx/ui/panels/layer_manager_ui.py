import uuid
import random
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QListWidgetItem, QInputDialog, QMessageBox, QDialog, QComboBox, QLabel
from PySide6.QtCore import Qt

class LayerManagerWidget(QWidget):
    def __init__(self, node, pid, color, parent=None):
        super().__init__(parent)
        self.node = node
        self.pid = pid
        self.color = color
        
        # Ensure mask_layers exists
        if pid not in node.params or not isinstance(node.params[pid], list):
            node.params[pid] = [{"id": "layer_0", "name": "Object 1", "color": "#ef4444", "keyframes": {}}]
        
        if "active_layer_id" not in node.params:
            if node.params[pid]:
                node.params["active_layer_id"] = node.params[pid][0]["id"]
            else:
                node.params["active_layer_id"] = None
                
        if "tool_mode" not in node.params:
            node.params["tool_mode"] = "Point"
                
        self.setup_ui()
        self.refresh_list()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Tool Mode Row
        tool_layout = QHBoxLayout()
        tool_lbl = QLabel("Tool:")
        tool_lbl.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        self.tool_combo = QComboBox()
        self.tool_combo.addItems(["Point", "Box"])
        self.tool_combo.setStyleSheet("""
            QComboBox { background-color: #27272a; color: white; border-radius: 4px; padding: 2px 6px; font-size: 11px; }
            QComboBox::drop-down { border: none; }
        """)
        self.tool_combo.setCurrentText(self.node.params.get("tool_mode", "Point"))
        self.tool_combo.currentTextChanged.connect(self.on_tool_mode_changed)
        tool_layout.addWidget(tool_lbl)
        tool_layout.addWidget(self.tool_combo)
        tool_layout.addStretch()
        layout.addLayout(tool_layout)
        
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: #18181b;
                border: 1px solid #27272a;
                border-radius: 6px;
                color: #fafafa;
                font-family: 'Inter';
                font-size: 12px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 6px;
                border-bottom: 1px solid #27272a;
            }}
            QListWidget::item:selected {{
                background-color: {self.color}40;
                border-left: 3px solid {self.color};
            }}
        """)
        self.list_widget.itemSelectionChanged.connect(self.on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        layout.addWidget(self.list_widget)
        
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("+ Add Layer")
        self.btn_add.setStyleSheet("""
            QPushButton { background-color: #27272a; color: white; border-radius: 4px; padding: 4px; font-size: 11px; }
            QPushButton:hover { background-color: #3f3f46; }
        """)
        self.btn_add.clicked.connect(self.add_layer)
        
        self.btn_remove = QPushButton("- Remove")
        self.btn_remove.setStyleSheet("""
            QPushButton { background-color: #7f1d1d; color: white; border-radius: 4px; padding: 4px; font-size: 11px; }
            QPushButton:hover { background-color: #991b1b; }
        """)
        self.btn_remove.clicked.connect(self.remove_layer)
        
        self.btn_auto_scan = QPushButton("Auto-Scan (SAM 3)")
        self.btn_auto_scan.setStyleSheet("""
            QPushButton { background-color: #0ea5e9; color: white; border-radius: 4px; padding: 4px; font-size: 11px; font-weight: bold; }
            QPushButton:hover { background-color: #0284c7; }
        """)
        self.btn_auto_scan.clicked.connect(self.auto_scan_objects)
        
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_remove)
        layout.addLayout(btn_layout)
        
        btn_layout2 = QHBoxLayout()
        btn_layout2.addWidget(self.btn_auto_scan)
        layout.addLayout(btn_layout2)
        
    def on_tool_mode_changed(self, text):
        self.node.params["tool_mode"] = text
        
    def auto_scan_objects(self):
        # Implementation to call backend to auto-scan objects
        from utvfx.bridge.ai_bridge_client import AIBridgeClient
        import cv2
        scene = self.node.scene()
        if not scene: return
        view = scene.views()[0]
        timeline = view.window().timeline if hasattr(view, "window") and view.window() else None
        if not timeline: return
        
        frame_idx = timeline.current_frame
        media_path = self.node.inputs.get("Video Plate")
        if not media_path:
            QMessageBox.warning(self, "Warning", "Please connect a Video Plate first.")
            return
            
        import os
        import glob
        if os.path.isdir(media_path):
            exts = ("*.png", "*.jpg", "*.jpeg", "*.exr", "*.dpx", "*.tif", "*.tiff", "*.hdr")
            files = []
            for ext in exts: files.extend(glob.glob(os.path.join(media_path, ext)))
            if not files: files = [os.path.join(media_path, f) for f in os.listdir(media_path) if os.path.isfile(os.path.join(media_path, f))]
            files.sort()
            if frame_idx >= len(files): frame_idx = len(files) - 1
            f_path = files[frame_idx]
        else:
            f_path = media_path
            
        QMessageBox.information(self, "Auto-Scan", "Scanning image for top objects... (this may take a few seconds)")
        
        client = AIBridgeClient.get_instance()
        objects = client.auto_scan(f_path)
        if not objects:
            QMessageBox.warning(self, "Scan Failed", "No objects detected or model failed.")
            return
            
        # Create a layer for each object
        colors = ["#ef4444", "#10b981", "#3b82f6", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4"]
        layers = []
        for i, (nx, ny, score) in enumerate(objects):
            layer_id = f"layer_{uuid.uuid4().hex[:8]}"
            c = colors[i % len(colors)]
            name = f"Auto Object {i+1} ({(score*100):.1f}%)"
            
            # Create a keyframe at the current frame with the object's center point
            keyframes = {str(frame_idx): [[nx, ny, 1]]}
            layers.append({"id": layer_id, "name": name, "color": c, "keyframes": keyframes, "enabled": True})
            
        self.node.params[self.pid] = layers
        self.node.params["active_layer_id"] = layers[0]["id"]
        self.refresh_list()
        self.on_selection_changed()
        QMessageBox.information(self, "Success", f"Created {len(layers)} object layers!")
        
    def refresh_list(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        layers = self.node.params[self.pid]
        active_id = self.node.params.get("active_layer_id")
        
        for layer in layers:
            item = QListWidgetItem(f" {layer['name']}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            is_enabled = layer.get("enabled", True)
            item.setCheckState(Qt.Checked if is_enabled else Qt.Unchecked)
            
            item.setData(Qt.UserRole, layer["id"])
            self.list_widget.addItem(item)
            if layer["id"] == active_id:
                item.setSelected(True)
        self.list_widget.blockSignals(False)
        
    def on_item_changed(self, item):
        layer_id = item.data(Qt.UserRole)
        layers = self.node.params[self.pid]
        layer = next((l for l in layers if l["id"] == layer_id), None)
        if layer:
            layer["enabled"] = (item.checkState() == Qt.Checked)
            
    def on_selection_changed(self):
        selected = self.list_widget.selectedItems()
        if selected:
            self.node.params["active_layer_id"] = selected[0].data(Qt.UserRole)
            # Force the viewport to refresh its display for the new active layer
            scene = self.node.scene()
            if scene and hasattr(scene.views()[0], "window"):
                main_window = scene.views()[0].window()
                if main_window and hasattr(main_window, "viewport"):
                    main_window.viewport.connect_to_node(self.node)
            
    def on_item_double_clicked(self, item):
        layer_id = item.data(Qt.UserRole)
        layers = self.node.params[self.pid]
        layer = next((l for l in layers if l["id"] == layer_id), None)
        if layer:
            name, ok = self._get_text_dialog("Rename Layer", "Enter new name:", layer["name"])
            if ok and name:
                layer["name"] = name
                self.refresh_list()
                
    def add_layer(self):
        layer_id = f"layer_{uuid.uuid4().hex[:8]}"
        name, ok = self._get_text_dialog("New Layer", "Enter layer name:", "New Object")
        if ok and name:
            colors = ["#ef4444", "#10b981", "#3b82f6", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4"]
            c = random.choice(colors)
            self.node.params[self.pid].append({"id": layer_id, "name": name, "color": c, "keyframes": {}})
            self.node.params["active_layer_id"] = layer_id
            self.refresh_list()
            self.on_selection_changed()
            
    def remove_layer(self):
        layers = self.node.params[self.pid]
        if len(layers) <= 1:
            QMessageBox.warning(self, "Warning", "Cannot remove the last layer.")
            return
            
        selected = self.list_widget.selectedItems()
        if selected:
            layer_id = selected[0].data(Qt.UserRole)
            self.node.params[self.pid] = [l for l in layers if l["id"] != layer_id]
            self.node.params["active_layer_id"] = self.node.params[self.pid][-1]["id"]
            self.refresh_list()
            self.on_selection_changed()

    def _get_text_dialog(self, title, label, text):
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setTextValue(text)
        dialog.setStyleSheet("""
            QInputDialog { background-color: #121212; }
            QLabel { color: #fafafa; font-family: 'Inter'; }
            QLineEdit { background-color: #1a1a1e; color: #fafafa; border: 1px solid #374151; border-radius: 4px; padding: 4px; }
            QPushButton { background-color: #27272a; color: #fafafa; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 12px; }
            QPushButton:hover { background-color: #3f3f46; }
        """)
        if dialog.exec() == QDialog.Accepted:
            return dialog.textValue(), True
        return "", False

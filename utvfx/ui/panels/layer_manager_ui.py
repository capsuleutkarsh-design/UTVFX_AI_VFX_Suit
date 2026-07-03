import uuid
import random
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QListWidgetItem, QInputDialog, QMessageBox, QDialog
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
                
        self.setup_ui()
        self.refresh_list()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
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
        
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_remove)
        layout.addLayout(btn_layout)
        
    def refresh_list(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        layers = self.node.params[self.pid]
        active_id = self.node.params.get("active_layer_id")
        
        for layer in layers:
            item = QListWidgetItem(f"● {layer['name']}")
            item.setData(Qt.UserRole, layer["id"])
            self.list_widget.addItem(item)
            if layer["id"] == active_id:
                item.setSelected(True)
        self.list_widget.blockSignals(False)
        
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

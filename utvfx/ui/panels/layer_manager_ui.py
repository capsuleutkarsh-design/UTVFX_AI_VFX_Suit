import uuid
import random
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QListWidgetItem, QInputDialog, QMessageBox, QDialog, QComboBox, QLabel, QFrame
from PySide6.QtCore import Qt, QSize, Slot, QThread, Signal

from utvfx.ui import icons, theme


def _swatch_style(colour):
    return f"background: {colour}; border: 1px solid {theme.BORDER}; border-radius: 2px;"

class ScanWorker(QThread):
    finished = Signal(object, int)
    def __init__(self, client, f_path, frame_idx, text_prompt="", sam_version=""):
        super().__init__()
        self.client = client
        self.f_path = f_path
        self.frame_idx = frame_idx
        self.text_prompt = text_prompt
        self.sam_version = sam_version
    def run(self):
        res = self.client.auto_scan(self.f_path, self.text_prompt, self.sam_version)
        self.finished.emit(res, self.frame_idx)

class LayerItemWidget(QWidget):
    def __init__(self, layer_id, name, color_hex, is_enabled, parent_manager):
        super().__init__()
        self.layer_id = layer_id
        self.parent_manager = parent_manager
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 6, 0)
        layout.setSpacing(theme.SPACING)

        self.btn_vis = QPushButton()
        self.btn_vis.setIcon(icons.icon("eye" if is_enabled else "eye-off", theme.TEXT_DIM))
        self.btn_vis.setToolTip("Show or hide this layer")
        theme.set_role(self.btn_vis, "flat")
        # Layout only: a compact square button inside the list row.
        self.btn_vis.setStyleSheet("padding: 2px;")
        self.btn_vis.setFixedSize(22, 22)
        self.btn_vis.clicked.connect(self.toggle_vis)
        layout.addWidget(self.btn_vis)

        self.swatch = QFrame()
        self.swatch.setFixedSize(10, 10)
        self.swatch.setStyleSheet(_swatch_style(color_hex))
        self.swatch.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.swatch)

        self.lbl_name = QLabel(name)
        self.lbl_name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.lbl_name)

        layout.addStretch()
        
    def toggle_vis(self):
        layers = self.parent_manager.node.params[self.parent_manager.pid]
        layer = next((l for l in layers if l["id"] == self.layer_id), None)
        if layer:
            new_state = not layer.get("enabled", True)
            layer["enabled"] = new_state
            self.btn_vis.setIcon(icons.icon("eye" if new_state else "eye-off", theme.TEXT_DIM))
            scene = self.parent_manager.node.scene()
            if scene and hasattr(scene.views()[0], "window"):
                main_window = scene.views()[0].window()
                if main_window and hasattr(main_window, "viewport"):
                    main_window.viewport.connect_to_node(self.parent_manager.node)

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
        layout.setSpacing(theme.SPACING)

        # Tool Mode Row
        tool_layout = QHBoxLayout()
        tool_layout.setSpacing(theme.SPACING)
        tool_lbl = theme.set_role(QLabel("Tool"), "dim")
        self.tool_combo = QComboBox()
        self.tool_combo.addItems(["Point", "Box"])
        self.tool_combo.setItemIcon(0, icons.icon("points"))
        self.tool_combo.setItemIcon(1, icons.icon("box"))
        self.tool_combo.setCurrentText(self.node.params.get("tool_mode", "Point"))
        self.tool_combo.currentTextChanged.connect(self.on_tool_mode_changed)
        tool_layout.addWidget(tool_lbl)
        tool_layout.addWidget(self.tool_combo)
        tool_layout.addStretch()
        layout.addLayout(tool_layout)

        self.list_widget = QListWidget()
        self.list_widget.setToolTip("Double-click a layer to rename it")
        self.list_widget.itemSelectionChanged.connect(self.on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.list_widget.setMinimumHeight(88)
        self.list_widget.setMaximumHeight(180)
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(theme.SPACING)
        self.btn_add = QPushButton("Add layer")
        self.btn_add.setIcon(icons.icon("plus"))
        self.btn_add.clicked.connect(self.add_layer)

        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setIcon(icons.icon("trash"))
        theme.set_role(self.btn_remove, "danger")
        self.btn_remove.clicked.connect(self.remove_layer)

        self.btn_auto_scan = QPushButton("Auto-scan")
        self.btn_auto_scan.setIcon(icons.icon("scan"))
        self.btn_auto_scan.setToolTip("Find objects in the current frame and make a layer for each. May take a few minutes.")
        self.btn_auto_scan.clicked.connect(self.auto_scan_objects)

        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_remove)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_auto_scan)
        layout.addLayout(btn_layout)

    def on_tool_mode_changed(self, text):
        self.node.params["tool_mode"] = text
        
    def auto_scan_objects(self):
        # Implementation to call backend to auto-scan objects
        from utvfx.bridge.ai_bridge_client import AIBridgeClient
        import cv2
        scene = self.node.scene()
        if not scene: return
        view = scene.views()[0]
        main_window = view.window() if hasattr(view, "window") else None
        viewport = getattr(main_window, "viewport", None) if main_window else None
        timeline = getattr(viewport, "timeline", None) if viewport else None
        if not timeline: return
        
        frame_idx = timeline._current_frame
        from utvfx.core.media_resolver import get_node_media_path
        media_path = get_node_media_path(self.node) if viewport else None
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
            if viewport and hasattr(viewport.img_display, "last_raw_image") and viewport.img_display.last_raw_image:
                import tempfile
                f_path = os.path.join(tempfile.gettempdir(), f"utvfx_autoscan_{frame_idx}.jpg")
                viewport.img_display.last_raw_image.save(f_path)
            else:
                f_path = media_path

        # Show status in the window's status bar instead of a blocking dialog
        if main_window and hasattr(main_window, "statusBar"):
            main_window.statusBar().showMessage("Auto-scan: looking for objects in the frame…", 10000)
        
        client = AIBridgeClient.get_instance()
        self.btn_auto_scan.setEnabled(False)
        self.btn_auto_scan.setText("Scanning…")
        
        text_prompt = self.node.params.get("text_prompt", "")
        sam_version = self.node.params.get("sam_version")
        if not sam_version:
            sam_version = "SAM 3 (ViT-B)"
        self.scan_thread = ScanWorker(client, f_path, frame_idx, text_prompt, sam_version)
        self.scan_thread.finished.connect(self.on_scan_finished)
        self.scan_thread.finished.connect(self.scan_thread.deleteLater)
        # Keep a strong reference on the persistent node object so the thread 
        # doesn't get destroyed if the user clicks away and this widget dies.
        self.node._active_scan_thread = self.scan_thread
        self.scan_thread.setParent(None)
        self.scan_thread.start()
        
    @Slot(object, int)
    def on_scan_finished(self, objects, frame_idx):
        self.btn_auto_scan.setEnabled(True)
        self.btn_auto_scan.setText("Auto-scan")
        
        if not objects:
            QMessageBox.warning(self, "Scan failed", "No objects were found, or the model failed.")
            return
            
        import uuid
        # Create a layer for each object
        colors = ["#ef4444", "#10b981", "#3b82f6", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4"]
        layers = self.node.params.get(self.pid, [])
        new_layers_count = 0
        for i, obj_data in enumerate(objects):
            if len(obj_data) >= 4:
                nx, ny, score, box = obj_data[0], obj_data[1], obj_data[2], obj_data[3]
            else:
                nx, ny, score = obj_data[0], obj_data[1], obj_data[2]
                box = None
                
            layer_id = f"layer_{uuid.uuid4().hex[:8]}"
            c = colors[i % len(colors)]
            name = f"Auto Object {len(layers)+1} ({(score*100):.1f}%)"
            
            sam_version = self.node.params.get("sam_version", "")
            is_sam3 = "SAM 3" in sam_version
            
            kf_data = []
            if box and is_sam3:
                kf_data.append([box[0], box[1], box[2], box[3], "box"])
            else:
                kf_data.append([nx, ny, 1])
                if box:
                    kf_data.append([box[0], box[1], box[2], box[3], "box"])
                
            keyframes = {frame_idx: kf_data}
            layers.append({"id": layer_id, "name": name, "color": c, "keyframes": keyframes, "enabled": True})
            new_layers_count += 1
            
        self.node.params[self.pid] = layers
        if new_layers_count > 0:
            self.node.params["active_layer_id"] = layers[-new_layers_count]["id"]
        self.refresh_list()
        self.on_selection_changed()
        QMessageBox.information(self, "Auto-scan", f"Created {new_layers_count} object layers.")
        
    def refresh_list(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        layers = self.node.params[self.pid]
        active_id = self.node.params.get("active_layer_id")
        
        for layer in layers:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, layer["id"])
            item.setSizeHint(QSize(0, 28))
            self.list_widget.addItem(item)
            
            is_enabled = layer.get("enabled", True)
            widget = LayerItemWidget(layer["id"], layer["name"], layer["color"], is_enabled, self)
            widget.setParent(self.list_widget)
            self.list_widget.setItemWidget(item, widget)
            
            if layer["id"] == active_id:
                item.setSelected(True)
        self.list_widget.blockSignals(False)
        self.update_list_style()
        
    def update_list_style(self):
        """Selection colours come from the global theme; each row carries its
        layer colour in its swatch. Kept so existing callers still work."""
        return

    def on_selection_changed(self):
        selected = self.list_widget.selectedItems()
        if selected:
            self.node.params["active_layer_id"] = selected[0].data(Qt.ItemDataRole.UserRole)
            self.update_list_style()
            # Force the viewport to refresh its display for the new active layer
            scene = self.node.scene()
            if scene and hasattr(scene.views()[0], "window"):
                main_window = scene.views()[0].window()
                if main_window and hasattr(main_window, "viewport"):
                    main_window.viewport.connect_to_node(self.node)
            
    def on_item_double_clicked(self, item):
        layer_id = item.data(Qt.ItemDataRole.UserRole)
        layers = self.node.params[self.pid]
        layer = next((l for l in layers if l["id"] == layer_id), None)
        if layer:
            name, ok = self._get_text_dialog("Rename layer", "Name:", layer["name"])
            if ok and name:
                layer["name"] = name
                self.refresh_list()
                
    def add_layer(self):
        layer_id = f"layer_{uuid.uuid4().hex[:8]}"
        name, ok = self._get_text_dialog("New layer", "Name:", "New object")
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
            layer_id = selected[0].data(Qt.ItemDataRole.UserRole)
            self.node.params[self.pid] = [l for l in layers if l["id"] != layer_id]
            self.node.params["active_layer_id"] = self.node.params[self.pid][-1]["id"]
            self.refresh_list()
            self.on_selection_changed()

    def _get_text_dialog(self, title, label, text):
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setTextValue(text)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.textValue(), True
        return "", False

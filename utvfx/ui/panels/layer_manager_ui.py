"""The SuperMatte layer list: one layer per object, each with its own click points.

Every change here (add, remove, rename, show/hide, tool, auto-scan) is one undo
step: the whole "mask_layers" list is swapped through a ChangeParamCommand with
deep copies (see utvfx.ui.param_undo). A hidden layer has layer["enabled"] = False.
"""
import random
import uuid

from PySide6.QtCore import QSize, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from utvfx.ui import icons, theme
from utvfx.ui.param_undo import layers_of, push_layers, push_param
from utvfx.ui.swatch import Swatch

LAYER_COLOURS = ["#ef4444", "#10b981", "#3b82f6", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4"]


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
        self.btn_vis.setToolTip("Show or hide this layer")
        theme.set_role(self.btn_vis, "icon")
        self.btn_vis.setFixedSize(22, 22)
        self.btn_vis.clicked.connect(self.toggle_vis)
        layout.addWidget(self.btn_vis)

        self.swatch = Swatch(color_hex, 10)
        layout.addWidget(self.swatch)

        self.lbl_name = QLabel(name)
        self.lbl_name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.lbl_name)

        layout.addStretch()
        self.set_enabled_state(is_enabled)

    def set_enabled_state(self, is_enabled):
        self.btn_vis.setIcon(icons.icon("eye" if is_enabled else "eye-off", theme.TEXT_DIM))
        theme.set_role(self.lbl_name, "" if is_enabled else "faint")

    def update_from(self, layer):
        self.lbl_name.setText(layer.get("name", ""))
        self.swatch.setColour(layer.get("color", "#ffffff"))
        self.set_enabled_state(layer.get("enabled", True))

    def toggle_vis(self):
        self.parent_manager.toggle_layer_enabled(self.layer_id)


class LayerManagerWidget(QWidget):
    def __init__(self, node, pid, color, parent=None):
        super().__init__(parent)
        self.node = node
        self.pid = pid
        self.color = color
        self._row_ids = []

        # A new node starts with one layer, so the first click has somewhere to go
        # (set up, not a user edit, so not undoable)
        if not isinstance(node.params.get(pid), list) or not node.params[pid]:
            node.params[pid] = [{"id": "layer_0", "name": "Object 1", "color": LAYER_COLOURS[0],
                                 "keyframes": {}, "enabled": True}]

        if node.params.get("active_layer_id") not in [l["id"] for l in node.params[pid]]:
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
        self.btn_add.clicked.connect(lambda: self.add_layer())

        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setIcon(icons.icon("trash"))
        theme.set_role(self.btn_remove, "danger")
        self.btn_remove.clicked.connect(lambda: self.remove_layer())

        self.btn_auto_scan = QPushButton("Auto-scan")
        self.btn_auto_scan.setIcon(icons.icon("scan"))
        self.btn_auto_scan.setToolTip("Find objects in the current frame and make a layer for each. May take a few minutes.")
        self.btn_auto_scan.clicked.connect(self.auto_scan_objects)

        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_remove)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_auto_scan)
        layout.addLayout(btn_layout)

    # ---- helpers ------------------------------------------------------------------
    def _layers(self):
        return self.node.params.get(self.pid) or []

    def _main_window(self):
        scene = self.node.scene() if hasattr(self.node, "scene") else None
        views = scene.views() if scene is not None else []
        return views[0].window() if views else None

    def _show_in_viewer(self):
        """Show this node's layers in the viewer (switches the viewer to this node)."""
        main_window = self._main_window()
        if main_window is not None and hasattr(main_window, "viewport"):
            main_window.viewport.connect_to_node(self.node)

    def _commit(self, new_layers, description, active_layer_id=None):
        if push_layers(self.node, new_layers, description, self.pid, active_layer_id):
            self.sync()
            self._show_in_viewer()

    # ---- edits (all undoable) -----------------------------------------------------
    def on_tool_mode_changed(self, text):
        push_param(self.node, "tool_mode", self.node.params.get("tool_mode", "Point"), text, "Change tool")

    def toggle_layer_enabled(self, layer_id):
        layers = layers_of(self.node, self.pid)
        layer = next((l for l in layers if l["id"] == layer_id), None)
        if layer is None:
            return
        layer["enabled"] = not layer.get("enabled", True)
        self._commit(layers, "Show layer" if layer["enabled"] else "Hide layer")

    def on_item_double_clicked(self, item):
        layer_id = item.data(Qt.ItemDataRole.UserRole)
        layers = layers_of(self.node, self.pid)
        layer = next((l for l in layers if l["id"] == layer_id), None)
        if layer:
            name, ok = self._get_text_dialog("Rename layer", "Name:", layer["name"])
            if ok and name and name != layer["name"]:
                layer["name"] = name
                self._commit(layers, "Rename layer")

    def add_layer(self, name=None):
        if not name:
            name, ok = self._get_text_dialog("New layer", "Name:", "New object")
            if not (ok and name):
                return
        layer_id = f"layer_{uuid.uuid4().hex[:8]}"
        layers = layers_of(self.node, self.pid)
        layers.append({"id": layer_id, "name": name, "color": random.choice(LAYER_COLOURS),
                       "keyframes": {}, "enabled": True})
        self._commit(layers, "Add layer", active_layer_id=layer_id)
        return layer_id

    def remove_layer(self, layer_id=None):
        layers = layers_of(self.node, self.pid)
        if len(layers) <= 1:
            QMessageBox.warning(self, "Warning", "Cannot remove the last layer.")
            return
        if layer_id is None:
            selected = self.list_widget.selectedItems()
            if not selected:
                return
            layer_id = selected[0].data(Qt.ItemDataRole.UserRole)
        remaining = [l for l in layers if l["id"] != layer_id]
        if len(remaining) == len(layers):
            return
        self._commit(remaining, "Remove layer", active_layer_id=remaining[-1]["id"])

    def auto_scan_objects(self):
        # Implementation to call backend to auto-scan objects
        from utvfx.bridge.ai_bridge_client import AIBridgeClient
        main_window = self._main_window()
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

        layers = layers_of(self.node, self.pid)
        is_sam3 = "SAM 3" in self.node.params.get("sam_version", "")
        new_ids = []
        for i, obj_data in enumerate(objects):
            if len(obj_data) >= 4:
                nx, ny, score, box = obj_data[0], obj_data[1], obj_data[2], obj_data[3]
            else:
                nx, ny, score = obj_data[0], obj_data[1], obj_data[2]
                box = None

            kf_data = []
            if box and is_sam3:
                kf_data.append([box[0], box[1], box[2], box[3], "box"])
            else:
                kf_data.append([nx, ny, 1])
                if box:
                    kf_data.append([box[0], box[1], box[2], box[3], "box"])

            layer_id = f"layer_{uuid.uuid4().hex[:8]}"
            layers.append({
                "id": layer_id,
                "name": f"Auto object {len(layers) + 1} ({score * 100:.1f}%)",
                "color": LAYER_COLOURS[i % len(LAYER_COLOURS)],
                "keyframes": {frame_idx: kf_data},
                "enabled": True,
            })
            new_ids.append(layer_id)

        if new_ids:
            self._commit(layers, "Auto-scan layers", active_layer_id=new_ids[0])
        QMessageBox.information(self, "Auto-scan", f"Created {len(new_ids)} object layers.")

    # ---- view -----------------------------------------------------------------------
    def sync(self):
        """Show the node's current layers (after an edit, undo or redo)."""
        self.tool_combo.blockSignals(True)
        self.tool_combo.setCurrentText(self.node.params.get("tool_mode", "Point"))
        self.tool_combo.blockSignals(False)
        layers = self._layers()
        if [l["id"] for l in layers] != self._row_ids:
            self.refresh_list()
            return
        # Same layers: update rows in place (a row may be running the click that got us here)
        active_id = self.node.params.get("active_layer_id")
        self.list_widget.blockSignals(True)
        for row, layer in enumerate(layers):
            item = self.list_widget.item(row)
            widget = self.list_widget.itemWidget(item)
            if widget is not None:
                widget.update_from(layer)
            item.setSelected(layer["id"] == active_id)
        self.list_widget.blockSignals(False)

    def refresh_list(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        layers = self._layers()
        active_id = self.node.params.get("active_layer_id")
        self._row_ids = [l["id"] for l in layers]

        for layer in layers:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, layer["id"])
            item.setSizeHint(QSize(0, 28))
            self.list_widget.addItem(item)

            is_enabled = layer.get("enabled", True)
            widget = LayerItemWidget(layer["id"], layer.get("name", ""), layer.get("color", "#ffffff"), is_enabled, self)
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
        # The active layer is where new clicks go: a view choice, not an undoable edit.
        selected = self.list_widget.selectedItems()
        if selected:
            self.node.params["active_layer_id"] = selected[0].data(Qt.ItemDataRole.UserRole)
            self.update_list_style()
            self._show_in_viewer()

    def _get_text_dialog(self, title, label, text):
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setTextValue(text)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.textValue(), True
        return "", False

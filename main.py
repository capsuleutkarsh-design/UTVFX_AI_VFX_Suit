import sys
import os

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import json

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QFrame, QLabel, QPushButton, QMessageBox, QFileDialog, QSplashScreen
)
from PySide6.QtCore import Qt, QSize, Slot, QTimer
from PySide6.QtGui import QIcon, QFontDatabase, QColor, QShortcut, QKeySequence, QPixmap

# Add current dir to path to allow absolute imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utvfx.ui.panels.media_panel import MediaPanel
from utvfx.ui.viewport import Viewport
from utvfx.ui.node_graph import NodeScene, NodeView
from utvfx.ui.panels.properties_panel import PropertiesPanel
from utvfx.core.data_model import NODES_REGISTRY
from utvfx.core.execution_engine import ExecutionEngine
from utvfx.ui.windows.render_queue import RenderQueueDialog
from utvfx.core.commands import create_undo_stack
from utvfx.ui.windows.model_downloader_ui import ModelDownloaderDialog
from utvfx.core.settings_manager import SettingsManager

class VFXCoreWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Main Setup
        self.setWindowTitle("UTVFX AI & VFX TOOL // v1.2")
        self.setMinimumSize(800, 600)
        self.resize(1280, 800)
        # Apply the icon
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "app_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        from utvfx.ui.styles import MAIN_WINDOW_STYLE
        
        # Load custom fonts if needed (assuming system fonts for now)
        self.setStyleSheet(MAIN_WINDOW_STYLE)
        
        # Undo/Redo Setup
        self.undo_stack = create_undo_stack(self)
        
        self.setup_ui()
        self.execution_engine = ExecutionEngine(self.node_scene)
        
        self.node_scene.undo_stack = self.undo_stack
        
        # Shortcuts
        self.shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.shortcut_undo.activated.connect(self.undo_stack.undo)
        
        self.shortcut_redo = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        self.shortcut_redo.activated.connect(self.undo_stack.redo)
        
        self.render_queue = RenderQueueDialog(self, self)
        
        self.setup_connections()
        
        # Validate that heavy AI model weights exist after UI is visible
        from PySide6.QtCore import QTimer
        QTimer.singleShot(500, self.check_models)
        
        # The graph will start empty. Users can add nodes via the Media Panel.

    def check_models(self):
        try:
            from first_setup import MODELS
            missing = []
            for item in MODELS:
                if item["type"] == "file":
                    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), item["path"])
                    if not os.path.exists(path):
                        missing.append(item["name"])
                elif item["type"] == "zip_extract":
                    target_path = item.get("final_name", item.get("path", ""))
                    if target_path.endswith(".exe"):
                        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), target_path)
                        if not os.path.exists(path):
                            missing.append(item["name"])
                    else:
                        plugin_parts = os.path.normpath(target_path).split(os.sep)
                        plugin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), *plugin_parts[:2])
                        found = False
                        if os.path.exists(plugin_dir):
                            for root, _, files in os.walk(plugin_dir):
                                if os.path.basename(target_path) in files:
                                    found = True
                                    break
                        if not found:
                            missing.append(item["name"])
                elif item["type"] == "hf_repo":
                    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), item["local_dir"])
                    if not os.path.exists(path):
                        missing.append(item["name"])
                        
            if missing:
                QMessageBox.warning(self, "Missing AI Models", 
                    f"The following required AI models/binaries are missing:\n\n{chr(10).join(missing)}\n\nPlease run 'python first_setup.py' or open Settings to download them to avoid crashes.")
        except Exception as e:
            print(f"Failed to validate models on startup: {e}")

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # ─── Global Top Nav ───
        nav = QWidget()
        nav.setFixedHeight(56)
        nav.setStyleSheet("background-color: #0d0d0f; border-bottom: 1px solid #27272a;")
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(10, 5, 10, 5)
        
        from utvfx.ui.styles import BTN_DEFAULT, BTN_DARK, BTN_PRIMARY, BTN_WARNING, get_label_style
        
        self.logo = QLabel("VFX.CORE — untitled.utvfx")
        self.logo.setStyleSheet("font-family: 'Space Grotesk'; font-size: 16px; font-weight: bold; color: #fafafa; letter-spacing: 2px;")
        nav_layout.addWidget(self.logo)
        
        nav_layout.addStretch()
        
        # Undo/Redo Buttons
        self.btn_undo = QPushButton("↩️ Undo")
        self.btn_undo.setStyleSheet(BTN_DEFAULT)
        self.btn_undo.clicked.connect(self.undo_stack.undo)
        nav_layout.addWidget(self.btn_undo)
        
        self.btn_redo = QPushButton("↪️ Redo")
        self.btn_redo.setStyleSheet(BTN_DEFAULT)
        self.btn_redo.clicked.connect(self.undo_stack.redo)
        nav_layout.addWidget(self.btn_redo)
        
        nav_layout.addSpacing(10)
        
        self.btn_save = QPushButton("💾 Save")
        self.btn_save.setStyleSheet(BTN_DARK)
        self.btn_save.clicked.connect(self.save_project)
        nav_layout.addWidget(self.btn_save)
        
        self.btn_load = QPushButton("📂 Load")
        self.btn_load.setStyleSheet(BTN_DARK)
        self.btn_load.clicked.connect(self.load_project)
        nav_layout.addWidget(self.btn_load)
        
        self.btn_settings = QPushButton("⚙️ Settings")
        self.btn_settings.setStyleSheet(BTN_PRIMARY)
        self.btn_settings.clicked.connect(self.open_settings)
        nav_layout.addWidget(self.btn_settings)
        
        self.btn_help = QPushButton("ℹ️ Help")
        self.btn_help.setStyleSheet(BTN_DEFAULT)
        self.btn_help.clicked.connect(self.open_help)
        nav_layout.addWidget(self.btn_help)
        
        self.btn_queue = QPushButton("▶ Render")
        self.btn_queue.setStyleSheet(BTN_WARNING)
        nav_layout.addWidget(self.btn_queue)
        
        main_layout.addWidget(nav)
        
        # ─── Main Splitter Layout ───
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        
        # 1. Left Dock
        self.media_panel = MediaPanel()
        self.media_panel.setMinimumWidth(200)
        self.media_panel.setMaximumWidth(350)
        self.main_splitter.addWidget(self.media_panel)
        
        # 2. Center Splitter
        self.center_splitter = QSplitter(Qt.Vertical)
        self.center_splitter.setChildrenCollapsible(False)
        
        self.viewport = Viewport()
        self.viewport.setMinimumHeight(200)
        self.center_splitter.addWidget(self.viewport)
        
        # Graph wrapper
        graph_container = QWidget()
        g_layout = QVBoxLayout(graph_container)
        g_layout.setContentsMargins(0,0,0,0)
        g_layout.setSpacing(0)
        
        # Graph Toolbar
        g_toolbar = QWidget()
        g_toolbar.setFixedHeight(40)
        g_toolbar.setStyleSheet("background-color: #121212; border-bottom: 1px solid #27272a; border-top: 1px solid #27272a;")
        gt_layout = QHBoxLayout(g_toolbar)
        gt_layout.setContentsMargins(20,0,20,0)
        
        lbl_graph = QLabel("⚙ PIPELINE FLOW GRAPH")
        lbl_graph.setStyleSheet("font-family: 'Space Grotesk'; font-size: 11px; font-weight: bold; color: #f59e0b; letter-spacing: 1px;")
        gt_layout.addWidget(lbl_graph)
        gt_layout.addStretch()
        
        btn_reset_layout = QPushButton("↺ RESET LAYOUT")
        btn_reset_layout.setStyleSheet("background-color: transparent; color: #f59e0b; border: 1px solid #f59e0b; border-radius: 4px; padding: 4px 12px; font-size: 10px; font-weight: bold;")
        btn_reset_layout.clicked.connect(self.reset_layout)
        gt_layout.addWidget(btn_reset_layout)
        
        g_layout.addWidget(g_toolbar)
        
        # Node Scene & View
        self.node_scene = NodeScene()
        self.node_view = NodeView(self.node_scene)
        g_layout.addWidget(self.node_view)
        
        self.center_splitter.addWidget(graph_container)
        self.main_splitter.addWidget(self.center_splitter)
        
        # 3. Right Dock
        self.properties_panel = PropertiesPanel()
        self.properties_panel.setMinimumWidth(420)
        self.properties_panel.setMaximumWidth(700)
        self.main_splitter.addWidget(self.properties_panel)
        
        # Set Splitter Sizes (approx: 250px, 1fr, 420px)
        self.main_splitter.setSizes([250, 600, 420])
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.center_splitter.setSizes([400, 400])
        
        main_layout.addWidget(self.main_splitter)

        # ─── Status Footer ───
        footer = QWidget()
        footer.setFixedHeight(32)
        footer.setStyleSheet("background-color: #050505; border-top: 1px solid #27272a;")
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(20,0,20,0)
        
        lbl_sys = QLabel("● SYSTEM ACTIVE")
        lbl_sys.setStyleSheet("font-family: 'JetBrains Mono'; font-size: 10px; color: #10b981; font-weight: bold;")
        f_layout.addWidget(lbl_sys)
        
        f_layout.addStretch()
        
        lbl_copyright = QLabel("© 2026 Utkarsh Tripathi / CapsuleUtkarsh Design. All Rights Reserved.")
        lbl_copyright.setStyleSheet("font-family: 'JetBrains Mono'; font-size: 10px; color: #52525b;")
        f_layout.addWidget(lbl_copyright)
        
        f_layout.addStretch()
        
        self.lbl_stats = QLabel("project / alpha_seq_012   |   engine / PySide6 (Qt6)")
        self.lbl_stats.setStyleSheet("font-family: 'JetBrains Mono'; font-size: 10px; color: #71717a;")
        f_layout.addWidget(self.lbl_stats)
        
        main_layout.addWidget(footer)
        
        # Setup system stats timer
        from PySide6.QtCore import QTimer
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.update_system_stats)
        self.stats_timer.start(1000)

    def update_system_stats(self):
        try:
            import psutil
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            
            # Use torch for VRAM if available
            gpu_str = ""
            try:
                import torch
                if torch.cuda.is_available():
                    gpu_util = torch.cuda.utilization()
                    vram_mb = torch.cuda.memory_allocated() / 1024 / 1024
                    gpu_str = f" | GPU: {gpu_util}% | VRAM: {vram_mb:.0f} MB"
            except ImportError:
                pass
            
            self.lbl_stats.setText(f"CPU: {cpu}% | RAM: {mem}%{gpu_str} | engine / PySide6 (Qt6)")
        except ImportError:
            self.lbl_stats.setText("project / alpha_seq_012   |   engine / PySide6 (Qt6) [psutil missing]")

    def setup_connections(self):
        self.media_panel.add_node_requested.connect(self.spawn_node)
        self.node_scene.signals.nodeSelected.connect(self.properties_panel.set_node)
        self.node_scene.signals.nodeSelected.connect(self.viewport.connect_to_node)
        self.node_scene.signals.viewerHotkey.connect(self._on_viewer_hotkey)
        self.properties_panel.execute_node_requested.connect(self._on_execute_node_requested)
        self.properties_panel.cancel_execution_requested.connect(self.execution_engine.cancel_execution)
        self.execution_engine.log_message.connect(self.properties_panel.append_console_log)
        self.execution_engine.node_execution_started.connect(self._on_node_execution_started)
        self.execution_engine.node_execution_progress.connect(self.properties_panel.update_progress)
        self.execution_engine.node_execution_progress.connect(self._on_node_execution_progress)
        self.execution_engine.node_execution_finished.connect(self._on_node_execution_finished)
        
        self.undo_stack.indexChanged.connect(self.properties_panel.refresh_ui)
        self.node_scene.signals.queueNodeRequested.connect(self.render_queue.add_node)
        self.node_scene.signals.fileDropped.connect(self._on_file_dropped)
        self.btn_queue.clicked.connect(self.render_queue.show)
        
        # Interactive Live Preview Routing
        self.viewport.interaction_requested.connect(self.execution_engine.handle_interaction)
        self.execution_engine.interactive_mask_ready.connect(self.viewport.receive_interactive_mask)

    @Slot(object, int)
    def _on_viewer_hotkey(self, node, key_num):
        # In a multi-input viewer, we'd map key_num to a specific input.
        # For now, any number 1-9 just connects the node to the main viewport.
        self.viewport.connect_to_node(node)

    def open_settings(self):
        from utvfx.ui.windows.settings_ui import SettingsDialog
        dialog = SettingsDialog(self, download_callback=self.open_model_downloader)
        dialog.exec()
        
    def open_help(self):
        from utvfx.ui.windows.help_dialog import HelpDialog
        dialog = HelpDialog(self)
        dialog.exec()

    def _on_execute_node_requested(self, node_id):
        node = None
        for n in self.node_scene.nodes:
            if n.node_id == node_id:
                node = n
                break
        if node:
            if hasattr(self.viewport.timeline, "_in_frame") and self.viewport.timeline._in_frame is not None:
                node.params["start_frame"] = self.viewport.timeline._in_frame + 1
            if hasattr(self.viewport.timeline, "_out_frame") and self.viewport.timeline._out_frame is not None:
                node.params["end_frame"] = self.viewport.timeline._out_frame + 1
            self.properties_panel.refresh_ui()
        self.execution_engine.execute_node(node_id)
        
    def _on_node_execution_started(self, node_id):
        for n in self.node_scene.nodes:
            if n.node_id == node_id:
                if hasattr(n, 'set_execution_state'):
                    n.set_execution_state(True, 0)
                break
                
    def _on_node_execution_progress(self, node_id, percentage):
        for n in self.node_scene.nodes:
            if n.node_id == node_id:
                if hasattr(n, 'set_execution_state'):
                    n.set_execution_state(True, percentage)
                break
                
    def _on_node_execution_finished(self, node_id):
        for n in self.node_scene.nodes:
            if n.node_id == node_id:
                if hasattr(n, 'set_execution_state'):
                    n.set_execution_state(False, 0)
                break
        
    def _on_file_dropped(self, file_path, pos):
        params = {"plate_file": file_path}
        # Call spawn_node directly, mapping the position to where it was dropped
        self.spawn_node("media_plate", params=params, override_pos=(pos["x"], pos["y"]))

    def spawn_node(self, plugin_type, params=None, override_pos=None):
        if params is None:
            params = {}
            
        p_def = NODES_REGISTRY.get(plugin_type)
        if not p_def:
            return
            
        if plugin_type == "media_plate" and "plate_file" in params:
            sm = SettingsManager()
            if sm.current_project_name == "Untitled":
                import re
                file_path = params["plate_file"]
                basename = os.path.basename(file_path)
                name, ext = os.path.splitext(basename)
                shot_name = name
                
                if ext.lower() in [".exr", ".png", ".jpg", ".jpeg", ".tiff", ".dpx"]:
                    clean_name = re.sub(r'[\._-]?\d+$', '', name)
                    if clean_name:
                        shot_name = clean_name
                    else:
                        folder_name = os.path.basename(os.path.dirname(file_path))
                        if folder_name and folder_name.lower() not in ["", "render", "renders", "output", "outputs", "frames", "images", "img"]:
                            shot_name = folder_name
                            
                sm.set_project_name(shot_name)
                self.logo.setText(f"VFX.CORE — {shot_name}.utvfx")
            
        # Populate default parameters from registry
        default_params = {}
        for p in p_def.get("parameters", []):
            default_params[p["id"]] = p["value"]
        # Merge with any passed parameters (e.g. plate_file)
        default_params.update(params)
            
        if override_pos is not None:
            pos = override_pos
        else:
            # Spawn at center of view
            center = self.node_view.mapToScene(self.node_view.viewport().rect().center())
            
            # Offset to prevent perfect overlap
            offset = len(self.node_scene.nodes) * 20
            pos = center.x() + offset, center.y() + offset
        
        node_data = {
            "name": p_def["name"],
            "plugin_type": plugin_type,
            "color": p_def.get("color", "#f59e0b"),
            "x": pos[0],
            "y": pos[1],
            "params": default_params
        }
        
        if self.undo_stack:
            from utvfx.core.commands import AddNodeCommand
            cmd = AddNodeCommand(self.node_scene, node_data)
            self.undo_stack.push(cmd)
        else:
            # Fallback if no undo stack
            node = self.node_scene.add_node(
                name=p_def["name"],
                plugin_type=plugin_type,
                inputs=p_def.get("inputs", []),
                outputs=p_def.get("outputs", []),
                color=p_def.get("color", "#f59e0b"),
                pos=pos
            )
            node.params = default_params
        

        
    def reset_layout(self):
        if self.node_scene.views():
            view = self.node_scene.views()[0]
            view.resetTransform()
            view.centerOn(0, 0)
            
    def closeEvent(self, event):
        print("Shutting down... cleaning up workers and subprocesses.", flush=True)
        
        if hasattr(self, 'viewport') and hasattr(self.viewport, 'player_thread'):
            if self.viewport.player_thread:
                try:
                    self.viewport.player_thread.stop()
                except Exception:
                    pass
        
        if hasattr(self, 'execution_engine'):
            for node_id, worker in self.execution_engine.active_workers.items():
                if hasattr(worker, 'cancel'): 
                    worker.cancel()
                elif hasattr(worker, 'is_cancelled'): 
                    worker.is_cancelled = True
                
                if hasattr(worker, 'wait'): 
                    worker.wait(1000)
                if hasattr(worker, 'terminate'): 
                    worker.terminate()
                
        # Shut down AI Bridge if running
        try:
            from utvfx.bridge.ai_bridge_client import AIBridgeClient
            bridge = AIBridgeClient._instance
            if bridge: bridge.shutdown()
        except Exception:
            pass
                    
        import threading
        for thread in threading.enumerate():
            if thread is not threading.main_thread() and hasattr(thread, 'stop'):
                try:
                    thread.stop()
                except Exception:
                    pass
                
        # Clean up temporary interactive files
        try:
            import glob
            temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace", "temp")
            for f in glob.glob(os.path.join(temp_dir, "utvfx_*")):
                try:
                    os.remove(f)
                except Exception:
                    pass
        except Exception:
            pass
                    
        event.accept()

    def save_project(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Project", "", "UTVFX Project (*.utvfx *.json)")
        if file_path:
            try:
                data = self.node_scene.to_dict()
                with open(file_path, "w") as f:
                    json.dump(data, f, indent=4)
                
                filename = os.path.basename(file_path)
                project_name = os.path.splitext(filename)[0]
                SettingsManager().set_project_name(project_name)
                self.logo.setText(f"VFX.CORE — {filename}")
                
                QMessageBox.information(self, "Saved", f"Project saved to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save project:\n{e}")

    def load_project(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Project", "", "UTVFX Project (*.utvfx *.json)")
        if file_path:
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)
                self.undo_stack.clear()
                self.node_scene.from_dict(data)
                
                filename = os.path.basename(file_path)
                project_name = os.path.splitext(filename)[0]
                SettingsManager().set_project_name(project_name)
                self.logo.setText(f"VFX.CORE — {filename}")
                
                QMessageBox.information(self, "Loaded", f"Project loaded successfully from {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load project:\n{e}")

    def open_model_downloader(self):
        dialog = ModelDownloaderDialog(self)
        dialog.exec()

if __name__ == "__main__":
    from utvfx.core.logger import setup_global_logger
    setup_global_logger()
    app = QApplication(sys.argv)
    app.setStyleSheet("* { outline: none; }")
    
    # --- SPLASH SCREEN ---
    splash_image_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "assets", "wizard_large.bmp")
    if os.path.exists(splash_image_path):
        splash_pixmap = QPixmap(splash_image_path)
        splash = QSplashScreen(splash_pixmap, Qt.WindowStaysOnTopHint)
        splash.show()
        splash.showMessage("Initializing Core VFX Engine...", Qt.AlignBottom | Qt.AlignCenter, Qt.white)
        app.processEvents()
    else:
        splash = None

    if splash:
        splash.showMessage("Loading UI Components...", Qt.AlignBottom | Qt.AlignCenter, Qt.white)
        app.processEvents()

    # Optional: Load font families if they exist locally
    # QFontDatabase.addApplicationFont("fonts/Inter-Regular.ttf")
    # QFontDatabase.addApplicationFont("fonts/SpaceGrotesk-Bold.ttf")
    
    window = VFXCoreWindow()
    window.showMaximized()
    
    if splash:
        splash.finish(window)
        
    sys.exit(app.exec())

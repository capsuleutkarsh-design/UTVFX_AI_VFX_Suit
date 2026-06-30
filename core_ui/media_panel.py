from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QFrame, QFileDialog
)
from PySide6.QtCore import Qt, Signal
from .data_model import NODES_REGISTRY

class NodeButton(QFrame):
    clicked = Signal()
    def __init__(self, name, color, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            QFrame {
                background-color: #121212;
                border: 1px solid #27272a;
                border-radius: 8px;
            }
            QFrame:hover {
                border-color: #52525b;
                background-color: #18181b;
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {color}; font-size: 14px; border: none; background: transparent;")
        dot.setAttribute(Qt.WA_TransparentForMouseEvents)
        
        lbl = QLabel(name)
        lbl.setStyleSheet("font-family: 'Inter'; font-weight: bold; font-size: 11px; color: #fafafa; border: none; background: transparent;")
        lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        
        plus = QLabel("+")
        plus.setStyleSheet("color: #71717a; font-weight: bold; font-size: 14px; border: none; background: transparent;")
        plus.setAttribute(Qt.WA_TransparentForMouseEvents)
        
        layout.addWidget(dot)
        layout.addWidget(lbl)
        layout.addStretch()
        layout.addWidget(plus)
        
    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

class MediaPanel(QWidget):
    # Emits the plugin_type when a user wants to add a node
    add_node_requested = Signal(str, dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        
    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Scroll Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: #0d0d0f; }")
        
        content = QWidget()
        content.setStyleSheet("background-color: #0d0d0f;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 24, 20, 24)
        layout.setSpacing(24)
        layout.setAlignment(Qt.AlignTop)
        
        # ─── Media Footage Section ───
        media_lbl = QLabel("🎥  MEDIA FOOTAGE //")
        media_lbl.setStyleSheet("font-family: 'Space Grotesk'; font-size: 10px; font-weight: bold; color: #a1a1aa; letter-spacing: 2px;")
        layout.addWidget(media_lbl)
        
        # Load Media Button
        btn_load = QPushButton("📁 Load Media...")
        btn_load.setCursor(Qt.PointingHandCursor)
        btn_load.setStyleSheet("""
            QPushButton {
                background-color: #1e1e24;
                border: 1px dashed #52525b;
                border-radius: 8px;
                padding: 16px;
                color: #e4e4e7;
                font-weight: bold;
                font-family: 'Inter';
            }
            QPushButton:hover {
                background-color: #27272a;
                border-color: #a1a1aa;
            }
        """)
        btn_load.clicked.connect(self._on_load_media)
        layout.addWidget(btn_load)
        
        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("background-color: #27272a; max-height: 1px;")
        layout.addWidget(div)
        
        # ─── Pipeline Operators Section ───
        ops_lbl = QLabel("⚡  PIPELINE OPERATORS //")
        ops_lbl.setStyleSheet("font-family: 'Space Grotesk'; font-size: 10px; font-weight: bold; color: #a1a1aa; letter-spacing: 2px;")
        layout.addWidget(ops_lbl)
        
        # Group nodes by category
        categories = {}
        for p_type, p_def in NODES_REGISTRY.items():
            if p_type == "media_plate":
                continue
            cat = p_def.get("category", "📦 Other")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append((p_type, p_def))
            
        for cat, nodes in categories.items():
            # Category Header
            cat_btn = QPushButton(f"{cat}")
            cat_btn.setCursor(Qt.PointingHandCursor)
            cat_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #d4d4d8;
                    font-weight: bold;
                    font-size: 12px;
                    text-align: left;
                    padding: 8px 4px;
                    border: none;
                    border-bottom: 1px solid #27272a;
                }
                QPushButton:hover {
                    color: #fafafa;
                }
            """)
            layout.addWidget(cat_btn)
            
            # Container for nodes
            nodes_container = QWidget()
            nodes_layout = QVBoxLayout(nodes_container)
            nodes_layout.setContentsMargins(8, 8, 0, 16)
            nodes_layout.setSpacing(8)
            
            for p_type, p_def in nodes:
                btn = NodeButton(p_def["name"], p_def["color"])
                btn.clicked.connect(lambda pt=p_type: self.add_node_requested.emit(pt, {}))
                nodes_layout.addWidget(btn)
                
            layout.addWidget(nodes_container)
            
            # Simple toggle logic
            def toggle_visibility(c=nodes_container):
                c.setVisible(not c.isVisible())
                
            cat_btn.clicked.connect(toggle_visibility)
            
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    def _on_load_media(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Media File", "", "Video/Image Files (*.mp4 *.mov *.png *.jpg *.exr)")
        if file_path:
            self.add_node_requested.emit("media_plate", {"plate_file": file_path})

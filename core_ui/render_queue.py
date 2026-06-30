from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, 
                               QListWidget, QPushButton, QLabel, QListWidgetItem)
from PySide6.QtCore import Qt, Slot

class RenderQueueDialog(QDialog):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setWindowTitle("Render Queue")
        self.resize(400, 300)
        self.setStyleSheet("""
            QDialog { background-color: #0d0d0f; color: #fafafa; }
            QLabel { color: #a1a1aa; font-family: 'Inter'; }
        """)
        
        self.queue_items = [] # list of node_ids
        self.is_rendering = False
        self.setup_ui()
        
        self.main_window.execution_engine.node_execution_finished.connect(self.on_node_finished)
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        lbl = QLabel("RENDER QUEUE")
        lbl.setStyleSheet("font-family: 'Space Grotesk'; font-size: 13px; font-weight: bold; color: #71717a; letter-spacing: 2px;")
        layout.addWidget(lbl)
        
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget { background-color: #1a1a1e; border: 1px solid #27272a; border-radius: 4px; outline: none; }
            QListWidget::item { padding: 8px; border-bottom: 1px solid #27272a; }
            QListWidget::item:selected { background-color: #2563eb; }
        """)
        layout.addWidget(self.list_widget)
        
        btn_layout = QHBoxLayout()
        
        self.btn_clear = QPushButton("Clear Queue")
        self.btn_clear.clicked.connect(self.clear_queue)
        self.btn_clear.setStyleSheet("""
            QPushButton { background-color: #1a1a1e; color: #a1a1aa; border: 1px solid #27272a; border-radius: 4px; padding: 8px; font-weight: bold; }
            QPushButton:hover { background-color: #27272a; color: white; }
        """)
        btn_layout.addWidget(self.btn_clear)
        
        self.btn_start = QPushButton("Start Render")
        self.btn_start.clicked.connect(self.start_queue)
        self.btn_start.setStyleSheet("""
            QPushButton { background-color: #3b82f6; color: white; border: none; border-radius: 4px; padding: 8px; font-weight: bold; }
            QPushButton:hover { background-color: #2563eb; }
            QPushButton:disabled { background-color: #1e3a8a; color: #93c5fd; }
        """)
        btn_layout.addWidget(self.btn_start)
        
        layout.addLayout(btn_layout)
        
    def add_node(self, node):
        if node.node_id not in self.queue_items:
            self.queue_items.append(node.node_id)
            item = QListWidgetItem(f"⏵ {node.name}  ({node.plugin_type})")
            item.setData(Qt.UserRole, node.node_id)
            self.list_widget.addItem(item)
            if not self.isVisible():
                self.show()
                self.raise_()
            
    def clear_queue(self):
        if self.is_rendering:
            return
        self.list_widget.clear()
        self.queue_items.clear()
        
    def start_queue(self):
        if self.is_rendering or not self.queue_items:
            return
            
        self.is_rendering = True
        self.btn_start.setText("Rendering...")
        self.btn_start.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.process_next()
        
    def process_next(self):
        if not self.queue_items:
            self.is_rendering = False
            self.btn_start.setText("Start Render")
            self.btn_start.setEnabled(True)
            self.btn_clear.setEnabled(True)
            return
            
        next_node_id = self.queue_items[0]
        if self.list_widget.count() > 0:
            self.list_widget.item(0).setBackground(Qt.darkBlue)
        self.main_window.execution_engine.execute_node(next_node_id)
        
    @Slot(str)
    def on_node_finished(self, node_id):
        if not self.is_rendering:
            return
            
        if self.queue_items and self.queue_items[0] == node_id:
            self.queue_items.pop(0)
            if self.list_widget.count() > 0:
                self.list_widget.takeItem(0)
            self.process_next()

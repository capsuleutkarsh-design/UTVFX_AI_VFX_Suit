from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                               QListWidget, QPushButton, QLabel, QListWidgetItem)
from PySide6.QtCore import Qt, Slot

from utvfx.ui import icons, theme


class RenderQueueDialog(QDialog):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setWindowTitle("Render queue")
        self.resize(420, 300)

        self.queue_items = [] # list of node_ids
        self.is_rendering = False
        self.setup_ui()

        self.main_window.execution_engine.node_execution_finished.connect(self.on_node_finished)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(theme.SPACING)

        header = QHBoxLayout()
        header.addWidget(theme.set_role(QLabel("Queued nodes"), "section"))
        header.addStretch()
        self.count_label = theme.set_role(QLabel("Empty"), "faint")
        header.addWidget(self.count_label)
        layout.addLayout(header)

        self.list_widget = QListWidget()
        self.list_widget.setIconSize(icons.ICON_SIZE)
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()

        self.btn_clear = QPushButton("Clear queue")
        self.btn_clear.setIcon(icons.icon("clear"))
        self.btn_clear.clicked.connect(self.clear_queue)
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addStretch()

        self.btn_start = QPushButton("Start render")
        self.btn_start.setIcon(icons.icon("render", theme.TEXT_ON_ACCENT))
        theme.set_role(self.btn_start, "primary")
        self.btn_start.clicked.connect(self.start_queue)
        btn_layout.addWidget(self.btn_start)

        layout.addLayout(btn_layout)

    def _update_count(self):
        n = len(self.queue_items)
        self.count_label.setText("Empty" if n == 0 else f"{n} node{'s' if n != 1 else ''}")

    def add_node(self, node):
        if node.node_id not in self.queue_items:
            self.queue_items.append(node.node_id)
            item = QListWidgetItem(icons.category_icon(node.plugin_type), f"{node.name}  ({node.plugin_type})")
            item.setData(Qt.UserRole, node.node_id)
            self.list_widget.addItem(item)
            self._update_count()
            if not self.isVisible():
                self.show()
                self.raise_()

    def clear_queue(self):
        if self.is_rendering:
            return
        self.list_widget.clear()
        self.queue_items.clear()
        self._update_count()

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
            self.btn_start.setText("Start render")
            self.btn_start.setEnabled(True)
            self.btn_clear.setEnabled(True)
            self._update_count()
            return

        next_node_id = self.queue_items[0]
        if self.list_widget.count() > 0:
            self.list_widget.item(0).setBackground(theme.qcolor(theme.ACCENT_MUTED))
        self.main_window.execution_engine.execute_node(next_node_id)

    @Slot(str)
    def on_node_finished(self, node_id):
        if not self.is_rendering:
            return

        if self.queue_items and self.queue_items[0] == node_id:
            self.queue_items.pop(0)
            if self.list_widget.count() > 0:
                self.list_widget.takeItem(0)
            self._update_count()
            self.process_next()

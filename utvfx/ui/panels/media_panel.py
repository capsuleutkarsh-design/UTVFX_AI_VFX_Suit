from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QFileDialog,
    QTreeWidget, QTreeWidgetItem
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont

from utvfx.core.data_model import NODES_REGISTRY
from utvfx.ui import icons, theme

# Item data role that holds a node row's plugin_type (category rows hold None).
PLUGIN_TYPE_ROLE = Qt.ItemDataRole.UserRole


class NodeButton(QFrame):
    """A single clickable node row. Kept for code that builds its own node lists;
    the media panel itself lists nodes in a tree."""
    clicked = Signal()

    def __init__(self, name, color, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(theme.SPACING)

        lbl = QLabel(name)
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(lbl)
        layout.addStretch()

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
        self.setObjectName("Panel")
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setObjectName("PanelHeader")
        header.setFixedHeight(30)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(10, 0, 10, 0)
        h_layout.addWidget(theme.set_role(QLabel("Media"), "section"))
        h_layout.addStretch()
        main_layout.addWidget(header)

        body = QWidget()
        body.setObjectName("PanelBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(theme.SPACING, theme.SPACING, theme.SPACING, theme.SPACING)
        layout.setSpacing(theme.SPACING)

        # Load media
        btn_load = QPushButton("Load media…")
        btn_load.setIcon(icons.icon("open"))
        btn_load.setToolTip("Add a Media Plate node from a video or image file")
        btn_load.clicked.connect(self._on_load_media)
        layout.addWidget(btn_load)

        layout.addWidget(theme.set_role(QLabel("Nodes"), "section"))

        # Node list: categories as section rows, nodes as flat rows (click to add)
        self.node_tree = QTreeWidget()
        self.node_tree.setHeaderHidden(True)
        self.node_tree.setRootIsDecorated(False)
        self.node_tree.setIndentation(14)
        self.node_tree.setIconSize(icons.ICON_SIZE)
        self.node_tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.node_tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.node_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.node_tree.setMouseTracking(True)
        self.node_tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.node_tree, 1)

        main_layout.addWidget(body, 1)
        self._populate_nodes()

    def _populate_nodes(self):
        # Group nodes by category
        categories = {}
        for p_type, p_def in NODES_REGISTRY.items():
            if p_type == "media_plate":
                continue
            cat = p_def.get("category", "Other")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append((p_type, p_def))

        header_font = theme.ui_font(weight=QFont.Weight.DemiBold)
        dim = QBrush(QColor(theme.TEXT_DIM))

        for cat, nodes in categories.items():
            cat_item = QTreeWidgetItem([cat])
            cat_item.setData(0, PLUGIN_TYPE_ROLE, None)
            cat_item.setIcon(0, icons.category_icon(nodes[0][0]))
            cat_item.setFont(0, header_font)
            cat_item.setForeground(0, dim)
            cat_item.setToolTip(0, "Click to show or hide")
            self.node_tree.addTopLevelItem(cat_item)

            for p_type, p_def in nodes:
                node_item = QTreeWidgetItem([p_def["name"]])
                node_item.setData(0, PLUGIN_TYPE_ROLE, p_type)
                node_item.setToolTip(0, f"Add {p_def['name']}")
                cat_item.addChild(node_item)

            cat_item.setExpanded(True)

    def _on_item_clicked(self, item, column=0):
        p_type = item.data(0, PLUGIN_TYPE_ROLE)
        if p_type:
            self.add_node_requested.emit(p_type, {})
        else:
            # Simple toggle logic
            item.setExpanded(not item.isExpanded())

    def _on_load_media(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select media file", "", "Video/Image Files (*.mp4 *.mov *.png *.jpg *.exr)")
        if file_path:
            self.add_node_requested.emit("media_plate", {"plate_file": file_path})

import re

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QLineEdit,
    QCheckBox, QComboBox, QPushButton, QRadioButton, QFileDialog, QColorDialog,
    QGroupBox, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from utvfx.ui import icons, theme

# Width of the label column, so every parameter row lines up.
LABEL_WIDTH = 140

# Words that stay capitalised when a label is put in sentence case.
_PROPER_NOUNS = {"Nuke", "Blender"}


def sentence_case(text):
    """'SAM Model Version' -> 'SAM model version'. Acronyms and mixed-case words
    (SAM, ViTMatte, GroundingDINO, I/O) are left alone."""
    first = [True]

    def visit(match):
        word = match.group(0)
        if first[0]:
            first[0] = False
            return word
        # Only plain Capitalised words are lowered; ALLCAPS and camelCase stay.
        if re.fullmatch(r"[A-Z][a-z]+", word) and word not in _PROPER_NOUNS:
            return word.lower()
        return word

    return re.sub(r"[A-Za-z]+", visit, text)


def _swatch_style(colour):
    return (
        f"QPushButton {{ background: {colour}; border: 1px solid {theme.BORDER_SOFT};"
        f" border-radius: 2px; padding: 0; }}"
        f"QPushButton:hover {{ border-color: {theme.TEXT_DIM}; }}"
    )


def build_param_widget(panel, param, color):
    ptype = param["type"]
    pid = param["id"]

    is_complex = ptype in ["layer_manager", "roto_layers"]
    label_text = sentence_case(param["name"])
    tooltip = param.get("tooltip", "")

    if is_complex:
        container = QGroupBox(label_text)
        container.setObjectName("CardWidget")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(theme.SPACING)
    else:
        container = QWidget()
        container.setObjectName("CardWidget")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        lbl = theme.set_role(QLabel(label_text), "dim")
        lbl.setFixedWidth(LABEL_WIDTH)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if tooltip:
            lbl.setToolTip(tooltip)
        layout.addWidget(lbl)

    # Get value from node params, fallback to default
    if not hasattr(panel.current_node, "params"):
        panel.current_node.params = {}
        
    val = panel.current_node.params.get(pid, param["value"])
    
    if ptype == "slider":
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(0,0,0,0)
        
        slider = QSlider(Qt.Orientation.Horizontal)
        step_val = param.get("step", param.get("value", 1))
        is_float = isinstance(step_val, float)
        mult = 100 if is_float else 1
        
        slider.setRange(int(param["min"] * mult), int(param["max"] * mult))
        slider.setValue(int(val * mult))
        if tooltip:
            slider.setToolTip(tooltip)

        val_lbl = theme.set_role(QLabel(f"{val:.2f}" if mult == 100 else str(val)), "mono")
        val_lbl.setMinimumWidth(44)
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        def on_change(v, l=val_lbl, m=mult, p=pid):
            actual_v = v / m
            l.setText(f"{actual_v:.2f}" if m == 100 else str(int(actual_v)))
            panel.current_node.params[p] = actual_v
            
        def on_press(p=pid):
            slider.old_val = panel.current_node.params.get(p, param["value"])
            
        def on_release(m=mult, p=pid):
            actual_v = slider.value() / m
            if hasattr(slider, 'old_val') and slider.old_val != actual_v:
                scene = panel.current_node.scene()
                if scene and scene.undo_stack:
                    from utvfx.core.commands import ChangeParamCommand
                    cmd = ChangeParamCommand(panel.current_node, p, slider.old_val, actual_v)
                    scene.undo_stack.push(cmd)
            
        slider.valueChanged.connect(on_change)
        slider.sliderPressed.connect(on_press)
        slider.sliderReleased.connect(on_release)
        
        h_layout.addWidget(slider)
        h_layout.addWidget(val_lbl)
        layout.addLayout(h_layout)
        
    elif ptype == "text" or ptype == "file" or ptype == "folder":
        line = QLineEdit(str(val))
        if tooltip:
            line.setToolTip(tooltip)

        def text_changed(t, p=pid):
            old_val = panel.current_node.params.get(p, param["value"])
            
            if panel.current_node.plugin_type == "media_plate" and p == "plate_file":
                from utvfx.core.settings_manager import SettingsManager
                sm = SettingsManager()
                if sm.current_project_name == "Untitled":
                    import os, re
                    basename = os.path.basename(t)
                    name, ext = os.path.splitext(basename)
                    shot_name = name
                    if ext.lower() in [".exr", ".png", ".jpg", ".jpeg", ".tiff", ".dpx"]:
                        clean_name = re.sub(r'[\._-]?\d+$', '', name)
                        if clean_name:
                            shot_name = clean_name
                        else:
                            folder_name = os.path.basename(os.path.dirname(t))
                            if folder_name and folder_name.lower() not in ["", "render", "renders", "output", "outputs", "frames", "images", "img"]:
                                shot_name = folder_name
                    sm.set_project_name(shot_name)
                    window = panel.window()
                    if hasattr(window, "set_project_title"):
                        window.set_project_title(shot_name)

            scene = panel.current_node.scene()
            if scene and scene.undo_stack:
                from utvfx.core.commands import ChangeParamCommand
                cmd = ChangeParamCommand(panel.current_node, p, old_val, t)
                scene.undo_stack.push(cmd)
            else:
                panel.current_node.params[p] = t
                
        line.editingFinished.connect(lambda: text_changed(line.text()))
        
        if ptype == "file" or ptype == "folder":
            line.setPlaceholderText("Select " + ("file" if ptype == "file" else "folder") + " path…")
            h = QHBoxLayout()
            h.setSpacing(4)
            btn = QPushButton()
            btn.setIcon(icons.icon("folder" if ptype == "folder" else "open"))
            btn.setToolTip("Browse")

            def open_file(*args, l=line, p=pid, is_folder=(ptype=="folder")):
                if is_folder:
                    path = QFileDialog.getExistingDirectory(panel, "Select folder")
                else:
                    path, _ = QFileDialog.getOpenFileName(panel, "Select file")
                    
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
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if tooltip:
            combo.setToolTip(tooltip)

        def combo_changed(t, p=pid):
            old_val = panel.current_node.params.get(p, param["value"])
            scene = panel.current_node.scene()
            if scene and scene.undo_stack:
                from utvfx.core.commands import ChangeParamCommand
                cmd = ChangeParamCommand(panel.current_node, p, old_val, t)
                scene.undo_stack.push(cmd)
            else:
                panel.current_node.params[p] = t
                
        combo.currentTextChanged.connect(combo_changed)
        layout.addWidget(combo)
        
    elif ptype == "checkbox":
        chk = QCheckBox()
        chk.setChecked(bool(val))
        if tooltip:
            chk.setToolTip(tooltip)

        def checkbox_changed(checked, p=pid):
            old_val = panel.current_node.params.get(p, param["value"])
            scene = panel.current_node.scene()
            if scene and scene.undo_stack:
                from utvfx.core.commands import ChangeParamCommand
                cmd = ChangeParamCommand(panel.current_node, p, old_val, checked)
                scene.undo_stack.push(cmd)
            else:
                panel.current_node.params[p] = checked
                
        chk.toggled.connect(checkbox_changed)
        layout.addWidget(chk)
        layout.addStretch()
        
    elif ptype == "radio":
        h = QHBoxLayout()
        h.setContentsMargins(0,0,0,0)
        h.setSpacing(12)
        for opt in param["options"]:
            rb = QRadioButton(opt)
            if str(val) == opt:
                rb.setChecked(True)
                
            def radio_changed(checked, o=opt, p=pid):
                if checked:
                    old_val = panel.current_node.params.get(p, param["value"])
                    scene = panel.current_node.scene()
                    if scene and scene.undo_stack:
                        from utvfx.core.commands import ChangeParamCommand
                        cmd = ChangeParamCommand(panel.current_node, p, old_val, o)
                        scene.undo_stack.push(cmd)
                    else:
                        panel.current_node.params[p] = o
                        
            rb.toggled.connect(radio_changed)
            h.addWidget(rb)
        h.addStretch()
        layout.addLayout(h)
        
    elif ptype == "layer_manager":
        from utvfx.ui.panels.layer_manager_ui import LayerManagerWidget
        layer_mgr = LayerManagerWidget(panel.current_node, pid, color)
        layer_mgr.setMinimumHeight(120)
        layout.addWidget(layer_mgr)
        
    elif ptype == "color":
        btn = QPushButton()
        btn.setFixedSize(28, 20)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(str(val))
        btn.setStyleSheet(_swatch_style(val))
        
        def choose_color(checked=False, b=btn, p=pid, init_color=val):
            c = QColorDialog.getColor(QColor(panel.current_node.params.get(p, init_color)), panel, "Select colour")
            if c.isValid():
                h_color = c.name()
                b.setStyleSheet(_swatch_style(h_color))
                b.setToolTip(h_color)
                
                old_val = panel.current_node.params.get(p, param["value"])
                scene = panel.current_node.scene()
                if scene and scene.undo_stack:
                    from utvfx.core.commands import ChangeParamCommand
                    cmd = ChangeParamCommand(panel.current_node, p, old_val, h_color)
                    scene.undo_stack.push(cmd)
                else:
                    panel.current_node.params[p] = h_color
                
        btn.clicked.connect(choose_color)
        layout.addWidget(btn)
        layout.addStretch()
        
    return container

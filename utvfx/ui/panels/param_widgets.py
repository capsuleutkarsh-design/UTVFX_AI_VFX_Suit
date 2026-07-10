from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QLineEdit,
    QCheckBox, QComboBox, QPushButton, QRadioButton, QFileDialog, QColorDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

def build_param_widget(panel, param, color):
    ptype = param["type"]
    pid = param["id"]
    
    is_complex = ptype in ["layer_manager", "roto_layers"]

    container = QWidget()
    container.setObjectName("CardWidget")
    
    if is_complex:
        container.setStyleSheet("""
            #CardWidget {
                background-color: #121212;
                border: 1px solid #1f1f22;
                border-radius: 8px;
            }
        """)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
    else:
        container.setStyleSheet("""
            #CardWidget {
                background-color: transparent;
            }
        """)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(12)
    
    # Label
    lbl = QLabel(param["name"].upper())
    lbl.setStyleSheet("font-family: 'Inter'; font-size: 10px; font-weight: 800; color: #a1a1aa; letter-spacing: 1px; background: transparent; border: none;")
    
    if not is_complex:
        lbl.setFixedWidth(140)
        
    layout.addWidget(lbl)
    
    # Get value from node params, fallback to default
    if not hasattr(panel.current_node, "params"):
        panel.current_node.params = {}
        
    val = panel.current_node.params.get(pid, param["value"])
    
    if ptype == "slider":
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(0,0,0,0)
        
        slider = QSlider(Qt.Horizontal)
        is_float = isinstance(param["step"], float)
        mult = 100 if is_float else 1
        
        slider.setRange(int(param["min"] * mult), int(param["max"] * mult))
        slider.setValue(int(val * mult))
        slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{ height: 6px; background: #27272a; border-radius: 3px; }}
            QSlider::sub-page:horizontal {{ background: {color}; border-radius: 3px; }}
            QSlider::handle:horizontal {{ background: #fafafa; border: 2px solid {color}; width: 14px; margin: -5px 0; border-radius: 7px; }}
            QSlider::handle:horizontal:hover {{ background: {color}; }}
        """)
        
        val_lbl = QLabel(str(val))
        val_lbl.setStyleSheet(f"color: {color}; font-family: 'JetBrains Mono'; font-weight: bold; font-size: 12px; min-width: 50px; background: transparent; border: none;")
        val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
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
        line.setStyleSheet(f"""
            QLineEdit {{
                background-color: #09090b; 
                border: 1px solid #27272a; 
                border-radius: 6px; 
                padding: 8px 12px; 
                color: #fafafa; 
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {color};
                background-color: #09090b;
            }}
        """)
        
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
                    if hasattr(window, "logo"):
                        window.logo.setText(f"VFX.CORE — {shot_name}.utvfx")

            scene = panel.current_node.scene()
            if scene and scene.undo_stack:
                from utvfx.core.commands import ChangeParamCommand
                cmd = ChangeParamCommand(panel.current_node, p, old_val, t)
                scene.undo_stack.push(cmd)
            else:
                panel.current_node.params[p] = t
                
        line.editingFinished.connect(lambda: text_changed(line.text()))
        
        if ptype == "file" or ptype == "folder":
            line.setPlaceholderText("Select " + ("file" if ptype == "file" else "folder") + " path...")
            h = QHBoxLayout()
            btn = QPushButton("📂")
            btn.setFixedSize(36, 36)
            btn.setStyleSheet("background-color: #18181b; border: 1px solid #27272a; border-radius: 6px;")
            
            def open_file(*args, l=line, p=pid, is_folder=(ptype=="folder")):
                if is_folder:
                    path = QFileDialog.getExistingDirectory(panel, "Select Folder")
                else:
                    path, _ = QFileDialog.getOpenFileName(panel, "Select File")
                    
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
        combo.setStyleSheet(f"""
            QComboBox {{
                background-color: #09090b; 
                border: 1px solid #27272a; 
                border-radius: 6px; 
                padding: 8px 12px; 
                color: #fafafa; 
                font-size: 12px;
            }}
            QComboBox:hover, QComboBox:focus {{
                border: 1px solid {color};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #18181b;
                color: #fafafa;
                selection-background-color: {color};
                selection-color: #000000;
                border: 1px solid #27272a;
                outline: none;
            }}
        """)
        
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
        chk = QCheckBox("Enabled")
        chk.setChecked(bool(val))
        chk.setStyleSheet(f"""
            QCheckBox {{ color: #fafafa; font-size: 12px; }}
            QCheckBox::indicator {{ width: 16px; height: 16px; background: #09090b; border: 1px solid #27272a; border-radius: 4px; }}
            QCheckBox::indicator:hover {{ border: 1px solid {color}; }}
            QCheckBox::indicator:checked {{ background: {color}; border: 1px solid {color}; }}
        """)
        
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
        
    elif ptype == "radio":
        h = QHBoxLayout()
        h.setContentsMargins(0,0,0,0)
        for opt in param["options"]:
            rb = QRadioButton(opt)
            rb.setStyleSheet(f"QRadioButton {{ color: #fafafa; font-size: 12px; }} QRadioButton::indicator:checked {{ background-color: {color}; border: 2px solid {color}; }}")
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
        layout.addLayout(h)
        
    elif ptype == "layer_manager":
        from utvfx.ui.panels.layer_manager_ui import LayerManagerWidget
        layer_mgr = LayerManagerWidget(panel.current_node, pid, color)
        layer_mgr.setMinimumHeight(120)
        layout.addWidget(layer_mgr)
        
    elif ptype == "color":
        btn = QPushButton()
        btn.setFixedSize(60, 24)
        btn.setStyleSheet(f"background-color: {val}; border: 1px solid #27272a; border-radius: 4px;")
        
        def choose_color(checked=False, b=btn, p=pid, init_color=val):
            c = QColorDialog.getColor(QColor(panel.current_node.params.get(p, init_color)), panel, "Select Color")
            if c.isValid():
                h_color = c.name()
                b.setStyleSheet(f"background-color: {h_color}; border: 1px solid #27272a; border-radius: 4px;")
                
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
        
    return container

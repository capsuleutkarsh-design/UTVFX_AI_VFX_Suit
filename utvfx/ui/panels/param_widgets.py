import re

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QLineEdit,
    QCheckBox, QComboBox, QPushButton, QRadioButton, QFileDialog, QColorDialog,
    QGroupBox, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor

from utvfx.ui import icons, theme
from utvfx.ui.number_field import NumberField
from utvfx.ui.param_undo import push_param, push_params
from utvfx.ui.swatch import SwatchButton

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


def push_with_presets(panel, node, param, old, new_val, description):
    """Push one edit, keeping shot presets honest.

    A select parameter with "presets" ({option: {param id: value}}) sets every value its
    choice lists, as one undo step. Changing by hand a value the current preset set turns
    that preset to its non-preset option ("Custom"), so the panel never claims a preset
    that is not what will run.
    """
    pid = param["id"]
    params_def = (getattr(panel, "node_def", None) or {}).get("parameters", [])
    defaults = {p["id"]: p["value"] for p in params_def}

    def value_of(p):
        return node.params.get(p, defaults.get(p))

    presets = param.get("presets")
    if presets and new_val in presets:
        changes = [(pid, old, new_val, False)] + [(k, value_of(k), v, False) for k, v in presets[new_val].items()]
        return push_params(node, changes, f"Preset: {new_val}")
    for other in params_def:
        table = other.get("presets")
        chosen = table.get(value_of(other["id"]), {}) if table else {}
        if pid in chosen and chosen[pid] != new_val:
            custom = next((o for o in other.get("options", []) if o not in table), None)
            if custom:
                return push_params(node, [(pid, old, new_val, False),
                                          (other["id"], value_of(other["id"]), custom, False)], description)
    return push_param(node, pid, old, new_val, description)


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

    node = panel.current_node
    val = node.params.get(pid, param["value"])

    def current(p=pid):
        return node.params.get(p, param["value"])

    def push(new_val, description=None, old_val=None):
        """One undoable edit of this parameter (skipped when nothing changed)."""
        old = current() if old_val is None else old_val
        return push_with_presets(panel, node, param, old, new_val, description or f"Change {label_text.lower()}")

    # Every row can be re-synced from the node (after undo/redo) without a rebuild.
    container.param_id = pid
    container.sync = lambda value: None
    container.flush = lambda: None

    if ptype == "slider":
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(6)

        step_val = param.get("step", param.get("value", 1))
        is_float = isinstance(step_val, float) or isinstance(param.get("value"), float)
        mult = 100 if is_float else 1
        step = param.get("step") or (0.01 if is_float else 1)

        def to_value(slider_pos):
            return slider_pos / mult if is_float else int(slider_pos)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(int(round(param["min"] * mult)), int(round(param["max"] * mult)))
        slider.setSingleStep(max(1, int(round(step * mult))))
        slider.setPageStep(max(1, int(round(step * mult)) * 10))
        slider.setValue(int(round(val * mult)))
        if tooltip:
            slider.setToolTip(tooltip)

        field = NumberField(val, param["min"], param["max"], step, 2 if is_float else 0)

        # One undo command per gesture: a handle drag, a number-field drag or entry,
        # or a burst of wheel / arrow-key / groove-click steps (debounced).
        gesture = {"old": None}
        settle = QTimer(slider)
        settle.setSingleShot(True)
        settle.setInterval(400)

        def begin():
            if gesture["old"] is None:
                gesture["old"] = current()

        def finish():
            settle.stop()
            old, gesture["old"] = gesture["old"], None
            if old is not None:
                push(current(), old_val=old)

        def set_live(value):
            node.params[pid] = value

        def on_slider_value(pos):
            value = to_value(pos)
            if not slider.isSliderDown():
                begin()          # wheel, keys or a groove click
                settle.start()
            set_live(value)
            field.setValue(value)

        def on_field_value(value):
            value = value if is_float else int(value)
            begin()
            set_live(value)
            slider.blockSignals(True)
            slider.setValue(int(round(value * mult)))
            slider.blockSignals(False)

        def on_field_committed(_old, _new):
            finish()

        slider.sliderPressed.connect(begin)
        slider.sliderReleased.connect(finish)
        slider.valueChanged.connect(on_slider_value)
        settle.timeout.connect(finish)
        field.valueChanged.connect(on_field_value)
        field.committed.connect(on_field_committed)

        def sync(value):
            if gesture["old"] is not None:
                return  # mid-gesture: the widget is the source of truth
            slider.blockSignals(True)
            slider.setValue(int(round(value * mult)))
            slider.blockSignals(False)
            field.setValue(value)

        container.sync = sync
        container.flush = finish
        container.slider = slider
        container.field = field

        h_layout.addWidget(slider, 1)
        h_layout.addWidget(field)
        layout.addLayout(h_layout, 1)

    elif ptype == "text" or ptype == "file" or ptype == "folder":
        line = QLineEdit(str(val))
        if tooltip:
            line.setToolTip(tooltip)

        def text_changed(t, p=pid):
            if str(current()) == t:
                return  # focus left an unchanged field

            if node.plugin_type == "media_plate" and p == "plate_file":
                _name_untitled_project(panel, t)

            push(t)

        line.editingFinished.connect(lambda: text_changed(line.text()))

        def sync(value, l=line):
            if not l.hasFocus() and l.text() != str(value):
                l.setText(str(value))

        container.sync = sync
        container.line = line

        if ptype == "file" or ptype == "folder":
            line.setPlaceholderText("Select " + ("file" if ptype == "file" else "folder") + " path…")
            h = QHBoxLayout()
            h.setSpacing(4)
            btn = QPushButton()
            btn.setIcon(icons.icon("folder" if ptype == "folder" else "open"))
            btn.setToolTip("Browse")

            def open_file(*args, l=line, p=pid, is_folder=(ptype == "folder")):
                if is_folder:
                    path = QFileDialog.getExistingDirectory(panel, "Select folder")
                else:
                    from utvfx.core.plate import MEDIA_FILTER
                    file_filter = MEDIA_FILTER if p == "plate_file" else "All files (*)"
                    path, _ = QFileDialog.getOpenFileName(panel, "Select file", "", file_filter)

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

        combo.currentTextChanged.connect(lambda t: push(t))

        def sync(value, c=combo):
            c.blockSignals(True)
            c.setCurrentText(str(value))
            c.blockSignals(False)

        container.sync = sync
        container.combo = combo
        layout.addWidget(combo)

    elif ptype == "checkbox":
        chk = QCheckBox()
        chk.setChecked(bool(val))
        if tooltip:
            chk.setToolTip(tooltip)

        chk.toggled.connect(lambda checked: push(checked))

        def sync(value, c=chk):
            c.blockSignals(True)
            c.setChecked(bool(value))
            c.blockSignals(False)

        container.sync = sync
        container.checkbox = chk
        layout.addWidget(chk)
        layout.addStretch()

    elif ptype == "radio":
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        buttons = []
        for opt in param["options"]:
            rb = QRadioButton(opt)
            if str(val) == opt:
                rb.setChecked(True)

            def radio_changed(checked, o=opt):
                if checked:
                    push(o)

            rb.toggled.connect(radio_changed)
            buttons.append(rb)
            h.addWidget(rb)
        h.addStretch()
        layout.addLayout(h)

        def sync(value, bs=buttons):
            for b in bs:
                b.blockSignals(True)
                b.setChecked(b.text() == str(value))
                b.blockSignals(False)

        container.sync = sync

    elif ptype == "layer_manager":
        from utvfx.ui.panels.layer_manager_ui import LayerManagerWidget
        layer_mgr = LayerManagerWidget(node, pid, color)
        layer_mgr.setMinimumHeight(120)
        layout.addWidget(layer_mgr)
        container.sync = lambda value: layer_mgr.sync()
        container.layer_manager = layer_mgr

    elif ptype == "color":
        btn = SwatchButton(val)
        btn.setFixedSize(28, 20)

        def choose_color(checked=False, b=btn):
            c = QColorDialog.getColor(QColor(current()), panel, "Select colour")
            if c.isValid():
                b.setColour(c.name())
                push(c.name())

        btn.clicked.connect(choose_color)
        container.sync = lambda value, b=btn: b.setColour(value)
        layout.addWidget(btn)
        layout.addStretch()

    return container


def _name_untitled_project(panel, plate_path):
    """Name an untitled project after the plate the user just picked."""
    import os
    from utvfx.core.settings_manager import SettingsManager
    sm = SettingsManager()
    if sm.current_project_name != "Untitled":
        return
    from utvfx.core.project import shot_name_from_path
    shot_name = shot_name_from_path(plate_path)
    sm.set_project_name(shot_name)
    window = panel.window()
    if hasattr(window, "set_project_title"):
        window.set_project_title(shot_name)

"""Every edit made in the properties panel and the viewer is one undo step."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest


@pytest.fixture
def window(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    # Never block a headless run on a dialog (e.g. the autosave recovery offer)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    from main import VFXCoreWindow
    win = VFXCoreWindow()
    win.check_models = lambda: None
    win.show()
    qapp.processEvents()
    yield win
    win.undo_stack.clear()
    win.hide()
    win.deleteLater()
    qapp.processEvents()


@pytest.fixture
def matte(window, qapp):
    window.spawn_node("super_matte")
    node = window.node_scene.nodes[-1]
    window.node_scene.signals.nodeSelected.emit(node)
    qapp.processEvents()
    return node


def _row(window, pid):
    return window.properties_panel._param_rows[pid]


def test_text_field_undo_round_trip(window, matte, qapp):
    row = _row(window, "text_prompt")
    line = row.line
    start = window.undo_stack.index()

    line.setText("person")
    line.editingFinished.emit()
    assert matte.params["text_prompt"] == "person"
    assert window.undo_stack.index() == start + 1
    assert _row(window, "text_prompt") is row  # the panel was not rebuilt

    line.editingFinished.emit()  # focus left again without a change
    assert window.undo_stack.index() == start + 1

    window.undo_stack.undo()
    assert matte.params.get("text_prompt", "") == ""
    assert line.text() == ""
    window.undo_stack.redo()
    assert matte.params["text_prompt"] == "person" and line.text() == "person"


def test_slider_keyboard_gesture_is_one_command(window, matte, qtbot):
    row = _row(window, "threshold")
    slider = row.slider
    start = window.undo_stack.index()
    original = matte.params.get("threshold", 128)

    for _ in range(4):
        QTest.keyClick(slider, Qt.Key_Up)  # Left/Right step the timeline
    assert matte.params["threshold"] == original + 4
    assert row.field.value() == original + 4
    qtbot.waitUntil(lambda: window.undo_stack.index() == start + 1, timeout=2000)
    qtbot.wait(500)
    assert window.undo_stack.index() == start + 1  # four steps, one command

    window.undo_stack.undo()
    assert matte.params["threshold"] == original
    assert slider.value() == original and row.field.value() == original


def test_number_field_typed_value_is_one_command(window, matte, qapp):
    row = _row(window, "threshold")
    field = row.field
    start = window.undo_stack.index()
    original = matte.params.get("threshold", 128)

    field.setFocus()
    qapp.processEvents()
    field.selectAll()
    QTest.keyClicks(field, "200")
    QTest.keyClick(field, Qt.Key_Return)
    assert matte.params["threshold"] == 200
    assert row.slider.value() == 200
    assert window.undo_stack.index() == start + 1

    window.undo_stack.undo()
    assert matte.params["threshold"] == original


def test_number_field_drag_is_one_command(window, matte, qapp):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    row = _row(window, "threshold")
    field = row.field
    start = window.undo_stack.index()
    original = matte.params.get("threshold", 128)

    def send(kind, x, buttons):
        pos = QPointF(x, field.height() / 2)
        event = QMouseEvent(kind, pos, field.mapToGlobal(pos), Qt.LeftButton, buttons, Qt.NoModifier)
        QApplication = type(qapp)
        QApplication.sendEvent(field, event)

    send(QEvent.MouseButtonPress, 10, Qt.LeftButton)
    for x in range(12, 60, 4):
        send(QEvent.MouseMove, x, Qt.LeftButton)
    send(QEvent.MouseButtonRelease, 60, Qt.NoButton)

    assert matte.params["threshold"] > original
    assert window.undo_stack.index() == start + 1
    window.undo_stack.undo()
    assert matte.params["threshold"] == original


def test_combo_and_checkbox_do_not_rebuild_the_panel(window, matte, qapp):
    params = window.properties_panel._param_rows
    combos = [r for r in params.values() if hasattr(r, "combo")]
    assert combos
    row = combos[0]
    options = [row.combo.itemText(i) for i in range(row.combo.count())]
    before = row.combo.currentText()
    row.combo.setCurrentText(next(o for o in options if o != before))
    assert window.properties_panel._param_rows[row.param_id] is row
    window.undo_stack.undo()
    assert row.combo.currentText() == before


def _layer_manager(window):
    return _row(window, "mask_layers").layer_manager


def test_add_and_remove_layer_undo(window, matte):
    mgr = _layer_manager(window)
    first = [l["id"] for l in matte.params["mask_layers"]]

    new_id = mgr.add_layer("Hair")
    assert [l["id"] for l in matte.params["mask_layers"]] == first + [new_id]
    assert matte.params["mask_layers"][-1]["enabled"] is True
    assert matte.params["active_layer_id"] == new_id
    assert mgr.list_widget.count() == len(first) + 1

    window.undo_stack.undo()
    assert [l["id"] for l in matte.params["mask_layers"]] == first
    assert matte.params["active_layer_id"] == first[0]
    assert mgr.list_widget.count() == len(first)

    window.undo_stack.redo()
    mgr.remove_layer(new_id)
    assert new_id not in [l["id"] for l in matte.params["mask_layers"]]
    window.undo_stack.undo()
    assert new_id in [l["id"] for l in matte.params["mask_layers"]]


def test_hide_layer_undo(window, matte):
    mgr = _layer_manager(window)
    layer_id = matte.params["mask_layers"][0]["id"]

    mgr.toggle_layer_enabled(layer_id)
    assert matte.params["mask_layers"][0]["enabled"] is False
    window.undo_stack.undo()
    assert matte.params["mask_layers"][0].get("enabled", True) is True


def test_undo_restores_a_copy_not_a_live_list(window, matte):
    mgr = _layer_manager(window)
    new_id = mgr.add_layer("Hair")
    # Something edits the live list in place after the command was pushed
    matte.params["mask_layers"][-1]["name"] = "Changed behind undo's back"
    window.undo_stack.undo()
    window.undo_stack.redo()
    assert matte.params["mask_layers"][-1]["name"] == "Hair"
    assert matte.params["mask_layers"][-1]["id"] == new_id


def test_click_point_undo(window, matte, qapp):
    viewport = window.viewport
    viewport.connect_to_node(matte)
    canvas = viewport.img_display
    assert canvas.is_interactive
    canvas.resize(320, 240)
    img = QImage(64, 48, QImage.Format.Format_RGB888)
    img.fill(0)
    canvas.last_raw_image = img

    requests = []
    canvas.interaction_requested.connect(lambda f, pts: requests.append(list(pts)))
    start = window.undo_stack.index()
    QTest.mouseClick(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(160, 120))

    layer = matte.params["mask_layers"][0]
    assert len(layer["keyframes"][canvas.current_frame]) == 1
    assert window.undo_stack.index() == start + 1
    assert requests and len(requests[-1]) == 1  # live preview asked for

    window.undo_stack.undo()
    layer = matte.params["mask_layers"][0]
    assert canvas.current_frame not in layer.get("keyframes", {})
    assert canvas.mask_layers is matte.params["mask_layers"]  # viewer shows the undone state

    window.undo_stack.redo()
    assert len(matte.params["mask_layers"][0]["keyframes"][canvas.current_frame]) == 1

    canvas.clear_current_frame_points()
    assert canvas.current_frame not in matte.params["mask_layers"][0]["keyframes"]
    window.undo_stack.undo()
    assert len(matte.params["mask_layers"][0]["keyframes"][canvas.current_frame]) == 1

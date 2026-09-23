"""A compact number field, as in Nuke: drag sideways to scrub, click to type.

    field = NumberField(minimum=0, maximum=1, step=0.01, decimals=2)
    field.valueChanged.connect(apply_live)          # every step of a drag, and typed values
    field.committed.connect(lambda old, new: ...)   # once per drag or typed entry

Drag: about 300 px covers the whole range (at least one step per pixel).
Ctrl slows the drag down ten times, Shift speeds it up ten times.
Click without dragging to type a value; Enter commits, Escape cancels.
"""
from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QLineEdit

from utvfx.ui import theme

_DRAG_THRESHOLD = 3     # px before a press becomes a drag
_FULL_RANGE_PX = 300.0  # drag distance that covers the whole range


class NumberField(QLineEdit):
    valueChanged = Signal(float)
    committed = Signal(float, float)  # old value, new value

    def __init__(self, value=0.0, minimum=0.0, maximum=1.0, step=0.01, decimals=2, parent=None):
        super().__init__(parent)
        self._min = float(minimum)
        self._max = float(maximum)
        self._step = float(step) if step else (1.0 if decimals == 0 else 0.01)
        self._decimals = int(decimals)
        self._value = self._clamp(value)
        self._press_pos = None
        self._drag_start_value = None
        self._dragging = False
        self._typing_start = None

        theme.set_role(self, "number")
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        validator = QDoubleValidator(self._min, self._max, max(self._decimals, 0), self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        validator.setLocale(QLocale.c())
        self.setValidator(validator)
        self.setToolTip("Drag to change (Ctrl: fine, Shift: coarse). Click to type a value.")
        self.setFixedWidth(self._width_for_range())
        self._show()

    # ---- value ------------------------------------------------------------------
    def value(self):
        return self._value

    def setValue(self, value):
        """Set the value without emitting anything (for syncing from the model)."""
        self._value = self._clamp(value)
        if not self.hasFocus():
            self._show()

    def _clamp(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = self._min
        value = min(max(value, self._min), self._max)
        return round(value) if self._decimals == 0 else round(value, self._decimals)

    def _format(self, value):
        return str(int(value)) if self._decimals == 0 else f"{value:.{self._decimals}f}"

    def _show(self):
        self.setText(self._format(self._value))
        self.setCursorPosition(0)

    def _width_for_range(self):
        metrics = self.fontMetrics()
        longest = max(len(self._format(self._min)), len(self._format(self._max)))
        return max(48, metrics.horizontalAdvance("0" * longest) + 20)

    def _set_live(self, value):
        value = self._clamp(value)
        if value != self._value:
            self._value = value
            self._show()
            self.valueChanged.emit(value)

    # ---- dragging ---------------------------------------------------------------
    def mousePressEvent(self, event):
        if self.hasFocus() or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._press_pos = event.position().toPoint()
        self._drag_start_value = self._value
        self._dragging = False
        event.accept()

    def mouseMoveEvent(self, event):
        if self._press_pos is None:
            super().mouseMoveEvent(event)
            return
        dx = event.position().toPoint().x() - self._press_pos.x()
        if not self._dragging and abs(dx) < _DRAG_THRESHOLD:
            return
        self._dragging = True
        steps_in_range = max(1.0, (self._max - self._min) / self._step)
        px_per_step = max(1.0, _FULL_RANGE_PX / steps_in_range)
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            px_per_step *= 10.0
        elif mods & Qt.KeyboardModifier.ShiftModifier:
            px_per_step /= 10.0
        steps = int(dx / px_per_step)
        self._set_live(self._drag_start_value + steps * self._step)
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._press_pos is None:
            super().mouseReleaseEvent(event)
            return
        was_dragging = self._dragging
        start = self._drag_start_value
        self._press_pos = None
        self._dragging = False
        self._drag_start_value = None
        event.accept()
        if was_dragging:
            # Always close the gesture, even if the drag came back to where it began.
            self.committed.emit(start, self._value)
        else:
            # A click: start typing.
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.selectAll()

    # ---- typing -----------------------------------------------------------------
    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._typing_start = self._value
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.selectAll()

    def focusOutEvent(self, event):
        self._commit_typed()
        super().focusOutEvent(event)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self._show()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._commit_typed()
            self.clearFocus()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._typing_start = None
            self._show()
            self.clearFocus()
            return
        super().keyPressEvent(event)

    def _commit_typed(self):
        start = self._typing_start
        self._typing_start = None
        if start is None:
            return
        text = self.text().strip().replace(",", ".")
        try:
            typed = float(text)
        except ValueError:
            self._show()
            return
        self._set_live(typed)
        self._show()
        if self._value != start:
            self.committed.emit(start, self._value)

    def wheelEvent(self, event):
        event.ignore()  # let the panel scroll; the slider takes the wheel

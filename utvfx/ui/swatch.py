"""Colour swatches drawn from the theme, so data colours never need an inline stylesheet."""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from utvfx.ui import theme


def _paint_swatch(widget, colour, hovered=False):
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(widget.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
    painter.setBrush(QColor(colour))
    painter.setPen(QPen(theme.qcolor(theme.TEXT_DIM if hovered else theme.BORDER_SOFT), 1))
    painter.drawRoundedRect(rect, 2, 2)
    painter.end()


class Swatch(QWidget):
    """A small filled square showing a colour (a layer's colour, a node category)."""

    def __init__(self, colour="#808080", size=10, parent=None):
        super().__init__(parent)
        self._colour = colour
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def colour(self):
        return self._colour

    def setColour(self, colour):
        self._colour = colour
        self.update()

    def paintEvent(self, event):
        _paint_swatch(self, self._colour)


class SwatchButton(QAbstractButton):
    """A clickable colour swatch (opens a colour picker in the caller)."""

    def __init__(self, colour="#808080", parent=None):
        super().__init__(parent)
        self._colour = colour
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(str(colour))

    def colour(self):
        return self._colour

    def setColour(self, colour):
        self._colour = colour
        self.setToolTip(str(colour))
        self.update()

    def sizeHint(self):
        return QSize(28, 20)

    def paintEvent(self, event):
        _paint_swatch(self, self._colour, self.underMouse())

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

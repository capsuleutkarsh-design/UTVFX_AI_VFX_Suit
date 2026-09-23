"""Contour VFX logo, app icon and splash screen, rendered from branding/*.svg."""
import os

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QSplashScreen

from utvfx.ui import theme
from utvfx.version import VERSION

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRANDING = os.path.join(ROOT, "branding")


def _render(svg_name, height, scale=2.0):
    renderer = QSvgRenderer(os.path.join(BRANDING, svg_name))
    size = renderer.defaultSize()
    width = size.width() * height / size.height()
    image = QPixmap(QSize(int(width * scale), int(height * scale)))
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, image.width(), image.height()))
    painter.end()
    image.setDevicePixelRatio(scale)
    return image


def logo_pixmap(height=22):
    return _render("logo.svg", height)


def mark_pixmap(size=20):
    return _render("mark.svg", size)


def app_icon():
    path = os.path.join(BRANDING, "app_icon.ico")
    return QIcon(path) if os.path.exists(path) else QIcon()


class Splash(QSplashScreen):
    """Start-up banner; status messages sit under the tagline, the version bottom right."""

    def __init__(self):
        super().__init__(_render("splash.svg", 405), Qt.WindowType.WindowStaysOnTopHint)
        self._message = ""

    def set_status(self, text):
        self._message = text
        self.repaint()

    def drawContents(self, painter):
        painter.setFont(theme.ui_font(9))
        painter.setPen(QColor(theme.TEXT_FAINT))
        painter.drawText(QRectF(181, 360, 400, 20), Qt.AlignmentFlag.AlignLeft, self._message)
        painter.drawText(QRectF(520, 360, 180, 20), Qt.AlignmentFlag.AlignRight, f"Version {VERSION}")

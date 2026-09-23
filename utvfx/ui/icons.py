"""Line icons for Contour VFX, drawn on a 24 px grid with a 1.6 px stroke.

    from utvfx.ui import icons
    button.setIcon(icons.icon("save"))

Icons are coloured at render time, so they follow the theme and never depend on
the fonts or emoji installed on the machine.
"""
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from utvfx.ui import theme

# Path data only; the <svg> wrapper and stroke style are added in _svg().
_PATHS = {
    # files and project
    "save": '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4"/><rect x="8" y="13" width="8" height="5"/>',
    "open": '<path d="M3 7V5h6l2 2h9v3"/><path d="M3 7v12h15l3-9H6l-3 9"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-4"/>',
    "redo": '<path d="m15 14 5-5-5-5"/><path d="M20 9H9a5 5 0 0 0 0 10h4"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14"/><path d="M12 17.2v.1"/>',
    "render": '<path d="M7 4.5v15l12-7.5z"/>',
    "queue": '<path d="M4 6h11M4 12h11M4 18h7"/><path d="m16 15 4 3-4 3z"/>',
    # playback and viewer
    "play": '<path d="M8 5v14l11-7z"/>',
    "pause": '<path d="M8 5v14M16 5v14"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1"/>',
    "step-back": '<path d="M6 5v14"/><path d="M18 5 9 12l9 7z"/>',
    "step-forward": '<path d="M18 5v14"/><path d="m6 5 9 7-9 7z"/>',
    "loop": '<path d="M17 3l3 3-3 3"/><path d="M4 12V9a3 3 0 0 1 3-3h13"/><path d="m7 21-3-3 3-3"/><path d="M20 12v3a3 3 0 0 1-3 3H4"/>',
    "wipe": '<rect x="3" y="5" width="18" height="14" rx="1"/><path d="M12 3v18"/>',
    "grid": '<rect x="4" y="4" width="16" height="16"/><path d="M4 12h16M12 4v16"/>',
    "fit": '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    "eye-off": '<path d="M3 3l18 18"/><path d="M10.6 5.6A9.5 9.5 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a16 16 0 0 1-2.8 3.6M6.5 6.9C4 8.6 2.5 12 2.5 12S6 18.5 12 18.5c1.8 0 3.3-.5 4.6-1.3"/>',
    "points": '<circle cx="7" cy="8" r="2"/><circle cx="16" cy="6" r="2"/><circle cx="13" cy="17" r="2"/>',
    "box": '<rect x="4" y="6" width="16" height="12" stroke-dasharray="3 2"/>',
    "text": '<path d="M5 6V4h14v2M12 4v16M9 20h6"/>',
    # editing
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="1"/><path d="M16 8V4H4v12h4"/>',
    "clear": '<path d="M6 6l12 12M18 6 6 18"/>',
    "check": '<path d="m5 12 5 5 9-10"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.5-4.5"/>',
    "reset": '<path d="M4 4v5h5"/><path d="M5 13a7 7 0 1 0 2-6.1L4 9"/>',
    "scan": '<path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4"/><path d="M4 12h16"/>',
    "freeze": '<path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9"/><path d="M9.5 4.5 12 7l2.5-2.5M9.5 19.5 12 17l2.5 2.5"/>',
    "bypass": '<path d="M12 3v8"/><path d="M6.3 6.8a8 8 0 1 0 11.4 0"/>',
    "folder": '<path d="M3 6h6l2 2h10v11H3z"/>',
    "warning": '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17v.1"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.1"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v6H4V6h6"/>',
    "chevron-left": '<path d="m15 5-7 7 7 7"/>',
    "chevron-right": '<path d="m9 5 7 7-7 7"/>',
    "chevron-down": '<path d="m5 9 7 7 7-7"/>',
    # node categories
    "media": '<rect x="3" y="5" width="18" height="14" rx="1"/><path d="M7 5v14M17 5v14M3 9h4M3 15h4M17 9h4M17 15h4"/>',
    "matte": '<rect x="4" y="4" width="16" height="16" rx="1"/><path d="M12 7c3 0 5 2.2 5 5s-2 5-5 5"/><path d="M12 7v10"/>',
    "tracking": '<path d="M12 3v4M12 17v4M3 12h4M17 12h4"/><circle cx="12" cy="12" r="5"/><path d="M12 11.9v.2"/>',
    "keying": '<path d="m14 4 6 6-2.5 2.5-6-6z"/><path d="m13 8-8 8v3h3l8-8"/>',
    "depth": '<path d="M3 19 9 9l4 6 3-4 5 8z"/>',
    "colour": '<circle cx="9" cy="10" r="5"/><circle cx="15" cy="10" r="5"/><circle cx="12" cy="15" r="5"/>',
    "output": '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M4 17v3h16v-3"/>',
    "utility": '<circle cx="12" cy="12" r="3"/>',
    "shapes": '<path d="M5 17c0-6 4-11 9-11 3 0 5 2 5 5 0 5-6 8-11 8"/><circle cx="5" cy="17" r="1.6"/><circle cx="19" cy="11" r="1.6"/>',
}


def _svg(name, colour):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{colour}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
        f"{_PATHS[name]}</svg>"
    )


def names():
    return sorted(_PATHS)


@lru_cache(maxsize=None)
def pixmap(name, size=16, colour=theme.TEXT, scale=2.0):
    """Render icon `name` at `size` logical px (drawn at `scale` for HiDPI)."""
    px = int(round(size * scale))
    image = QPixmap(px, px)
    image.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(_svg(name, colour).encode("utf-8")))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    image.setDevicePixelRatio(scale)
    return image


@lru_cache(maxsize=None)
def icon(name, colour=theme.TEXT, size=16):
    """A QIcon with normal, disabled and active (accent) states."""
    result = QIcon()
    result.addPixmap(pixmap(name, size, colour), QIcon.Mode.Normal)
    result.addPixmap(pixmap(name, size, theme.TEXT_FAINT), QIcon.Mode.Disabled)
    result.addPixmap(pixmap(name, size, theme.ACCENT), QIcon.Mode.Active, QIcon.State.On)
    return result


def category_icon(plugin_type, size=16):
    category = theme.NODE_CATEGORY.get(plugin_type, "utility")
    return icon(category, theme.NODE_CATEGORY_COLOURS[category], size)


ICON_SIZE = QSize(16, 16)

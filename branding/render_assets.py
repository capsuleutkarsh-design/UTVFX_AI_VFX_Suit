"""Render the SVG brand sources into the PNG and ICO files the app and installer use.

    python_base\\python.exe branding\\make_splash.py
    python_base\\python.exe branding\\render_assets.py

Outputs:
    branding/png/mark_<size>.png     16 ... 1024
    branding/png/logo.png, logo@2x.png
    branding/png/splash.png, splash@2x.png
    branding/app_icon.ico            multi-size Windows icon
"""
import sys
from pathlib import Path

# Use the normal Windows platform: "offscreen" has no font database, so the
# wordmark would render as boxes. No window is shown.
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

HERE = Path(__file__).resolve().parent
PNG = HERE / "png"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render(svg, w, h, out):
    renderer = QSvgRenderer(str(svg))
    if not renderer.isValid():
        sys.exit(f"bad svg: {svg}")
    img = QImage(QSize(w, h), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()
    img.save(str(out))
    return out


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841 (fonts need it)
    PNG.mkdir(exist_ok=True)

    for size in (16, 24, 32, 48, 64, 128, 256, 512, 1024):
        render(HERE / "mark.svg", size, size, PNG / f"mark_{size}.png")
    w = int(QSvgRenderer(str(HERE / "logo.svg")).defaultSize().width())
    render(HERE / "logo.svg", w, 64, PNG / "logo.png")
    render(HERE / "logo.svg", w * 2, 128, PNG / "logo@2x.png")
    render(HERE / "splash.svg", 720, 405, PNG / "splash.png")
    render(HERE / "splash.svg", 1440, 810, PNG / "splash@2x.png")

    icon_pngs = [render(HERE / "app_icon.svg", s, s, PNG / f"icon_{s}.png") for s in ICON_SIZES]

    from PIL import Image
    images = [Image.open(p) for p in icon_pngs]
    images[-1].save(HERE / "app_icon.ico", format="ICO", sizes=[(s, s) for s in ICON_SIZES],
                    append_images=images[:-1])
    for p in icon_pngs:
        p.unlink()

    # Inno Setup wizard images: 24-bit BMP, no alpha.
    for svg, size, name in (("wizard_large.svg", (164, 314), "wizard_large.bmp"),
                            ("app_icon.svg", (55, 55), "wizard_small.bmp")):
        tmp = render(HERE / svg, *size, PNG / "_wizard.png")
        flat = Image.new("RGB", size, (0x1B, 0x1B, 0x1B))
        img = Image.open(tmp).convert("RGBA")
        flat.paste(img, mask=img.split()[3])
        flat.save(HERE / name)
        tmp.unlink()
    print("rendered:", ", ".join(sorted(p.name for p in PNG.iterdir())), "+ app_icon.ico")


if __name__ == "__main__":
    main()

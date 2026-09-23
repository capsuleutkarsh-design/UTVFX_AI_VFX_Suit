"""Write the SVG brand sources: mark.svg, logo.svg and splash.svg.

    python_base\\python.exe branding\\make_brand.py
    python_base\\python.exe branding\\render_assets.py

The splash lines are iso-lines of a smooth height field, traced with OpenCV, so
they read as a real contour map. The seed is fixed, so the output only changes
when this file does. Word spacing is measured with Qt's font metrics.
"""
from pathlib import Path

import cv2
import numpy as np

W, H = 720, 405
BG = "#1B1B1B"
LINE = "#2C2C2C"
ACCENT = "#E8833A"
TEXT = "#E6E6E6"
DIM = "#8C8C8C"

HERE = Path(__file__).resolve().parent


def text_width(text, size, family):
    """Advance width measured by Qt, the same engine that renders the SVGs."""
    from PySide6.QtGui import QFont, QFontMetricsF, QGuiApplication
    QGuiApplication.instance() or QGuiApplication([])
    font = QFont(family)
    font.setPixelSize(size)
    return QFontMetricsF(font).horizontalAdvance(text)


def mark(transform=""):
    """U viewfinder bracket, tracker ring behind, T crosshair on top."""
    attr = f' transform="{transform}"' if transform else ""
    return (
        f"<g{attr}>\n"
        f'    <circle cx="32" cy="21" r="7.5" fill="none" stroke="{TEXT}" stroke-width="1.5"/>\n'
        f'    <path d="M13 10 V38 A14 14 0 0 0 27 52 H37 A14 14 0 0 0 51 38 V10" fill="none" '
        f'stroke="{TEXT}" stroke-width="6" stroke-linecap="round"/>\n'
        f'    <path d="M22 21 H42 M32 21 V41" fill="none" stroke="{ACCENT}" stroke-width="5" '
        f'stroke-linecap="round"/>\n'
        f"  </g>"
    )


def wordmark(x, baseline, size):
    """'Contour' semibold then 'VFX' light. Returns (svg, right edge)."""
    vfx_x = x + text_width("Contour", size, "Segoe UI Semibold") + size * 0.24
    right = vfx_x + text_width("VFX", size, "Segoe UI Light")
    svg = (
        f'<text x="{x}" y="{baseline}" font-family="Segoe UI Semibold" font-size="{size}" '
        f'fill="{TEXT}">Contour</text>\n'
        f'  <text x="{vfx_x:.1f}" y="{baseline}" font-family="Segoe UI Light" font-size="{size}" '
        f'fill="{DIM}">VFX</text>'
    )
    return svg, right


def height_field(w=W, h=H, seed=7, x_range=(0.45, 1.1)):
    rng = np.random.default_rng(seed)
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    field = np.zeros((h, w), np.float32)
    # A few broad hills, weighted to the right so the text side stays calm.
    for _ in range(7):
        cx, cy = rng.uniform(*x_range) * w, rng.uniform(-0.1, 1.1) * h
        sx, sy = rng.uniform(0.12, 0.3) * max(w, h), rng.uniform(0.17, 0.45) * min(w, h)
        field += rng.uniform(0.6, 1.2) * np.exp(-(((xs - cx) / sx) ** 2 + ((ys - cy) / sy) ** 2))
    return field


def contour_paths(field, levels):
    paths = []
    for level in levels:
        mask = (field > level).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        for c in contours:
            if len(c) < 40:
                continue
            pts = cv2.approxPolyDP(c, 1.2, True)[:, 0, :]
            paths.append((level, "M" + " L".join(f"{x},{y}" for x, y in pts) + " Z"))
    return paths


def main():
    levels = np.linspace(0.12, 1.6, 16)
    paths = contour_paths(height_field(), levels)
    accent_level = levels[9]
    lines = []
    for level, d in paths:
        if level == accent_level:
            lines.append(f'  <path d="{d}" fill="none" stroke="{ACCENT}" stroke-opacity="0.55" stroke-width="1.4"/>')
        else:
            lines.append(f'  <path d="{d}" fill="none" stroke="{LINE}" stroke-width="1"/>')

    words, _ = wordmark(178, 188, 58)
    splash = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">\n'
        f'  <rect width="{W}" height="{H}" fill="{BG}"/>\n'
        + "\n".join(lines) + "\n"
        f'  {mark("translate(56 118) scale(1.6)")}\n'
        f"  {words}\n"
        f'  <text x="181" y="222" font-family="Segoe UI" font-size="16" fill="{DIM}">'
        f"AI roto, mattes and camera tracking for compositors</text>\n"
        f'  <rect x="0" y="{H - 3}" width="{W}" height="3" fill="{ACCENT}"/>\n'
        f"</svg>\n"
    )
    (HERE / "splash.svg").write_text(splash, encoding="utf-8")

    (HERE / "mark.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">\n  {mark()}\n</svg>\n', encoding="utf-8")

    words, right = wordmark(70, 42, 31)
    logo_w = int(right) + 8
    (HERE / "logo.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {logo_w} 64" width="{logo_w}" height="64">\n'
        f"  {mark()}\n  {words}\n</svg>\n", encoding="utf-8")
    # Installer side panel (Inno Setup: 164x314) and corner image (55x55).
    ww, wh = 164, 314
    wpaths = contour_paths(height_field(ww, wh, seed=11, x_range=(-0.1, 1.1)), np.linspace(0.12, 1.6, 12))
    wlines = "\n".join(f'  <path d="{d}" fill="none" stroke="{LINE}" stroke-width="1"/>' for _, d in wpaths)
    (HERE / "wizard_large.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ww} {wh}" width="{ww}" height="{wh}">\n'
        f'  <rect width="{ww}" height="{wh}" fill="{BG}"/>\n{wlines}\n'
        f'  {mark("translate(42 96) scale(1.25)")}\n'
        f'  <rect x="0" y="{wh - 3}" width="{ww}" height="3" fill="{ACCENT}"/>\n</svg>\n', encoding="utf-8")
    print(f"wrote splash.svg ({len(paths)} contour lines), mark.svg, logo.svg ({logo_w}x64), wizard_large.svg")


if __name__ == "__main__":
    main()

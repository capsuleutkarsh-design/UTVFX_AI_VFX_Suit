# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the Contour VFX desktop app (build\build_installer.bat).
#
# How the frozen app finds things at run time (one-folder build, dist\ContourVFX\):
#   - Code: utvfx/ and plugins/ are bundled as data under _internal\ (sys._MEIPASS).
#     plugin_manager.py resolves plugins\ relative to its own file, so that is
#     _internal\plugins; ai_bridge_client.py falls back to _internal\plugins\SuperMatte.
#   - Models: settings_manager.py (frozen branch) uses <folder of ContourVFX.exe>\models,
#     next to the exe, never inside _internal. They are not bundled: the installer's
#     models ZIP or the in-app downloader puts them there.
#   - AI Python: the AI bridge and the model workers run in a separate CPython with torch.
#     ai_bridge_client.py looks for <exe folder>\python_base\python.exe (after the old
#     _internal\python_base location). python_base is 11 GB and is a second interpreter,
#     so it is NOT bundled here; the installer must provide it next to the exe (for
#     example by running first_setup.py, which builds it from requirements-lock.txt).
#     Note: nodes whose workers import torch in the UI process (CorridorKey, Depth, ...)
#     also need torch importable by the frozen interpreter; that is not solved by this spec.
#   - UPX is off: it breaks CUDA/Qt DLLs and triggers antivirus warnings.
#   - GPL-only Qt add-ons (Charts, DataVisualization, Graphs, Quick3D, NetworkAuth) are
#     excluded so the build stays within PySide6's LGPL modules.

GPL_QT_MODULES = [
    'PySide6.QtCharts',
    'PySide6.QtDataVisualization',
    'PySide6.QtGraphs',
    'PySide6.QtGraphsWidgets',
    'PySide6.QtQuick3D',
    'PySide6.QtNetworkAuth',
]
# File-name prefixes of the matching Qt DLLs and QML plugins (checked case-insensitively).
GPL_QT_FILES = (
    'qt6charts', 'qt6datavisualization', 'qt6graphs', 'qt6quick3d', 'qt6networkauth',
    'qtcharts', 'qtdatavisualization', 'qtgraphs', 'qtquick3d', 'qtnetworkauth',
)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('plugins', 'plugins/'),
        ('branding', 'branding/'),
        ('first_setup.py', '.'),
        ('requirements-lock.txt', '.'),
        ('assets', 'assets/'),
        ('utvfx', 'utvfx/'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=GPL_QT_MODULES,
    noarchive=False,
    optimize=0,
)


def exclude_models(datas):
    filtered = []
    # Model weights never go into the bundle.
    bad_ext = ('.pth', '.pt', '.safetensors', '.onnx', '.bin', '.ckpt', '.h5', '.part')
    # Nor environments, caches or debug symbols.
    bad_folders = ('uv_cache', '.venv', 'venv', 'python_base', '.git', '__pycache__', '.cache')

    for item in datas:
        # item is a tuple (dest_name, source_path, typecode); test the relative dest_name
        # so folders above the checkout never match.
        src = item[0].lower()

        if src.endswith(bad_ext) or src.endswith('.pdb'):
            continue

        path_parts = src.replace('\\', '/').split('/')
        if any(bad_folder in path_parts for bad_folder in bad_folders):
            continue

        filtered.append(item)
    return filtered


def exclude_gpl_qt(entries):
    kept = []
    for item in entries:
        name = item[0].replace('\\', '/').lower()
        parts = name.split('/')
        if any(p.startswith(GPL_QT_FILES) for p in parts):
            continue
        kept.append(item)
    return kept


a.datas = exclude_gpl_qt(exclude_models(a.datas))
a.binaries = exclude_gpl_qt(a.binaries)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ContourVFX',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['branding\\app_icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ContourVFX',
)

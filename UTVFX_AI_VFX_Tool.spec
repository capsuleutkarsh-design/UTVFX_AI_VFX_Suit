# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('core_ui', 'core_ui/'), ('plugins', 'plugins/'), ('CorridorKeyModule', 'CorridorKeyModule/')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
def exclude_models(datas):
    filtered = []
    # extensions to exclude
    bad_ext = ('.pth', '.pt', '.safetensors', '.onnx', '.bin')
    for item in datas:
        # item is a tuple: (source_path, dest_dir)
        src = item[0].lower()
        if not src.endswith(bad_ext):
            filtered.append(item)
    return filtered

a.datas = exclude_models(a.datas)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='UTVFX_AI_VFX_Tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['build\\app_icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='UTVFX_AI_VFX_Tool',
)

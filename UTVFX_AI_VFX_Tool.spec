# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('plugins', 'plugins/'), 
        ('CorridorKeyModule', 'CorridorKeyModule/'),
        ('build/assets/app_icon.ico', 'build/'),
        ('first_setup.py', '.'),
        ('python_base', 'python_base/'),
        ('tools', 'tools/'),
        ('assets', 'assets/'),
        ('utvfx', 'utvfx/')
    ],
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
    # folders to exclude
    bad_folders = ('uv_cache', '.venv', '.git', '__pycache__')
    
    for item in datas:
        # item is a tuple: (source_path, dest_dir)
        src = item[0].lower()
        
        # Check if the source path ends with a bad extension
        if src.endswith(bad_ext):
            continue
            
        # Check if any part of the path matches a bad folder
        path_parts = src.replace('\\', '/').split('/')
        if any(bad_folder in path_parts for bad_folder in bad_folders):
            continue
            
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
    icon=['build\\assets\\app_icon.ico'],
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

# -*- mode: python ; coding: utf-8 -*-
import os

HERE = os.path.dirname(os.path.abspath(__file__))

a = Analysis(
    [os.path.join(HERE, 'app.py')],
    pathex=[],
    binaries=[],
    datas=[
        (os.path.join(HERE, 'index.html'), '.'),
        (os.path.join(HERE, 'icon.ico'), '.'),
    ],
    hiddenimports=['pystray._win32', 'pystray._util', 'PIL', 'six'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='FocusDeck',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(HERE, 'icon.ico')],
)

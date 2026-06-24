# -*- mode: python ; coding: utf-8 -*-
# MediaServerManager.spec
#
# PyInstaller onedir build — output lands in dist\main\
# which matches AllClearServerServices_Setup.iss expectations.
#
# Build:
#   pyinstaller MediaServerManager.spec
#
# Then compile the installer:
#   "C:\Program Files (x86)\Inno Setup 6\iscc.exe" AllClearServerServices_Setup.iss

import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# ── Hidden imports ────────────────────────────────────────────────────────────
# paramiko pulls in cryptography internals that PyInstaller misses
hidden = (
    collect_submodules("paramiko") +
    collect_submodules("cryptography") +
    collect_submodules("PIL") +
    [
        "cryptography.hazmat.primitives.asymmetric.rsa",
        "cryptography.hazmat.primitives.asymmetric.ec",
        "cryptography.hazmat.primitives.asymmetric.ed25519",
        "cryptography.hazmat.bindings._rust",
        "cryptography.hazmat.bindings._rust.openssl",
        "bcrypt",
        "nacl",
        "nacl.bindings",
        "PIL._tkinter_finder",
        "PIL.Image",
        "PIL.ImageTk",
        "cffi",
        "_cffi_backend",
    ]
)

# Collect PIL/Pillow binary hooks (handles platform DLLs)
from PyInstaller.utils.hooks import collect_data_files as _cdf
pil_datas = _cdf("PIL")

# ── Data files bundled alongside the exe ─────────────────────────────────────
datas = [
    # App config and assets — kept at root of install dir
    ("assets/config.json", "assets"),
    ("splash.png",         "."),
] + pil_datas

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude large scientific libs that sneak in via cryptography
        "matplotlib", "numpy", "pandas", "scipy",
        "PIL", "cv2", "sklearn",
        "IPython", "notebook", "jupyter",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],                         # binaries/datas go into COLLECT, not here
    exclude_binaries=True,      # onedir mode
    name="main",                # → dist\main\main.exe  (matches .iss)
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=["vcruntime140.dll", "python3*.dll"],
    console=False,              # no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                  # add path to a .ico file here if you have one
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=["vcruntime140.dll", "python3*.dll"],
    name="main",                # → dist\main\  folder
)

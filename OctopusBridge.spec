# -*- mode: python ; coding: utf-8 -*-
# Сгенерировано build_app.py — не редактируйте вручную.
from PyInstaller.utils.hooks import collect_all, collect_data_files
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable,
    VarFileInfo, VarStruct, VSVersionInfo)

datas = collect_data_files('app') + [('ico.ico', '.')]
binaries, hiddenimports = [], []
# honyaku — встроенный модуль app/translators/honyaku: PyInstaller
# подхватит его из импортов app. Внешние пакеты — с бинарями и данными:
for _pkg in ("ctranslate2", "huggingface_hub"):
    try:
        _d, _b, _h = collect_all(_pkg)
    except Exception:
        _d, _b, _h = [], [], []
    datas += _d
    binaries += _b
    hiddenimports += _h

version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(0, 5, 0, 0),
        prodvers=(0, 5, 0, 0),
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo([
            StringTable('040904B0', [
                StringStruct('CompanyName', 'OctopusBridge'),
                StringStruct('FileDescription', 'OctopusBridge - game translation & modding tool'),
                StringStruct('FileVersion', '0.5.0'),
                StringStruct('InternalName', 'OctopusBridge'),
                StringStruct('OriginalFilename', 'OctopusBridge_v0.5.0.exe'),
                StringStruct('ProductName', 'OctopusBridge'),
                StringStruct('ProductVersion', '0.5.0'),
            ]),
        ]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])]),
    ],
)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision', 'torchaudio', 'torch_directml', 'transformers', 'tokenizers', 'safetensors', 'accelerate', 'datasets', 'peft', 'einops', 'triton', 'sympy', 'networkx', 'sklearn', 'scipy', 'pandas', 'matplotlib', 'PIL', 'IPython', 'jupyter_client', 'stanza'],
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
    name='OctopusBridge_v0.5.0.exe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['ico.ico'],
    version=version_info,
)

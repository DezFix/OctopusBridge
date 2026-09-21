# -*- mode: python ; coding: utf-8 -*-
# Сгенерировано build_app.py — не редактируйте вручную.
from PyInstaller.utils.hooks import collect_all, collect_data_files
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable,
    VarFileInfo, VarStruct, VSVersionInfo)

datas = collect_data_files('app') + collect_data_files('UnityPy') + [('assets/ico.ico', 'assets'), ('CHANGELOG.md', '.')]
# collect_data_files('UnityPy'): забирает UnityPy/resources/lzma.tpk (база
# typetree через importlib.resources). Без неё parse_as_dict падает на
# КАЖДОМ объекте с ModuleNotFoundError: UnityPy.resources — в exe было
# 26/26 файлов, 13988 текстовых объектов и 0 записей.
binaries, hiddenimports = [], ["UnityPy", "UnityPy.resources",
                               "TypeTreeGeneratorAPI"]

version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(7, 16, 0, 0),
        prodvers=(7, 16, 0, 0),
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
                StringStruct('FileVersion', '7.16'),
                StringStruct('InternalName', 'OctopusBridge'),
                StringStruct('OriginalFilename', 'OctopusBridge_v7.16.exe'),
                StringStruct('ProductName', 'OctopusBridge'),
                StringStruct('ProductVersion', '7.16'),
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
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'torch', 'torchvision', 'torchaudio', 'torch_directml', 'transformers', 'tokenizers', 'safetensors', 'accelerate', 'datasets', 'peft', 'einops', 'triton', 'sympy', 'networkx', 'sklearn', 'scipy', 'pandas', 'matplotlib', 'IPython', 'jupyter_client', 'stanza'],
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
    name='OctopusBridge_v7.16.exe',
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
    icon=['assets/ico.ico'],
    version=version_info,
)

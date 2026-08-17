# -*- coding: utf-8 -*-
"""Сборка OctopusBridge в приложение (.exe) через PyInstaller.

Использование:
    python build_app.py                # сборка
    python build_app.py --tests        # прогнать тесты перед сборкой
    python build_app.py --installer    # после сборки сделать установщик Inno Setup
    python build_app.py --version 1.2.0  # версия для setup.iss

После сборки exe лежит в dist\\OctopusBridge_v<версия>.exe
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
SPEC_PATH = os.path.join(ROOT, "OctopusBridge.spec")
ISS_PATH = os.path.join(ROOT, "setup.iss")
ICON = "assets/ico.ico"
APP_NAME = "OctopusBridge"
DIST_DIR = os.path.join(ROOT, "dist")
BUILD_DIR = os.path.join(ROOT, "build")

# Обязательные пакеты (module -> имя пакета для pip).
REQUIRED_MIN = {
    "PySide6": "PySide6", "requests": "requests", "websockets": "websockets",
    "psutil": "psutil", "frida": "frida",
}

# Исключаем неиспользуемые тяжёлые пакеты, чтобы exe оставался лёгким.
EXCLUDES_MIN = [
    "torch", "torchvision", "torchaudio", "torch_directml",
    "transformers", "tokenizers", "safetensors",
    "accelerate", "datasets", "peft", "einops", "triton", "sympy",
    "networkx", "sklearn", "scipy", "pandas", "matplotlib", "PIL",
    "IPython", "jupyter_client", "stanza",
]

SPEC_TEMPLATE = r'''# -*- mode: python ; coding: utf-8 -*-
# Сгенерировано build_app.py — не редактируйте вручную.
from PyInstaller.utils.hooks import collect_all, collect_data_files
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable,
    VarFileInfo, VarStruct, VSVersionInfo)

datas = collect_data_files('app') + [('assets/ico.ico', 'assets'), ('CHANGELOG.md', '.')]
binaries, hiddenimports = [], []

version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=__FILEVERS__,
        prodvers=__FILEVERS__,
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
                StringStruct('FileVersion', '__VERSION__'),
                StringStruct('InternalName', 'OctopusBridge'),
                StringStruct('OriginalFilename', '__EXE_NAME__'),
                StringStruct('ProductName', 'OctopusBridge'),
                StringStruct('ProductVersion', '__VERSION__'),
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
    excludes=__EXCLUDES__,
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
    name='__EXE_NAME__',
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
    icon=['__ICON__'],
    version=version_info,
)
'''


def log(msg: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass
    print(f"[build] {msg}", flush=True)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    log("> " + " ".join(cmd))
    return subprocess.run(cmd, **kw)


def pick_python() -> str:
    """Возвращает путь к интерпретатору (предпочитаем .venv)."""
    if os.path.isfile(VENV_PY):
        return VENV_PY
    return sys.executable


def ensure_deps(python: str) -> None:
    """Проверяет наличие обязательных пакетов, доустанавливает недостающие."""
    missing = []
    for module, pkg in REQUIRED_MIN.items():
        r = run([python, "-c", f"import {module}"], capture_output=True)
        if r.returncode != 0:
            missing.append(pkg)
    if not missing:
        log("Все зависимости на месте")
        return
    log(f"Отсутствуют пакеты: {', '.join(missing)}, устанавливаю...")
    r = run([python, "-m", "pip", "install", *missing])
    if r.returncode != 0:
        sys.exit("ОШИБКА: не удалось установить зависимости")


def ensure_pyinstaller(python: str) -> None:
    try:
        r = run([python, "-m", "PyInstaller", "--version"],
                capture_output=True, text=True)
        if r.returncode == 0:
            log(f"PyInstaller найден: {r.stdout.strip()}")
            return
    except OSError:
        pass
    log("PyInstaller не установлен, устанавливаю...")
    r = run([python, "-m", "pip", "install", "pyinstaller"])
    if r.returncode != 0:
        sys.exit("ОШИБКА: не удалось установить PyInstaller")
    log("PyInstaller установлен")


def _version_tuple(version: str) -> tuple:
    """'0.2.0' -> (0, 2, 0, 0) — PyInstaller хочет 4 компонента."""
    parts = [int(p) for p in version.split(".")]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def exe_name(version: str) -> str:
    """'0.3.4' -> 'OctopusBridge_v0.3.4.exe'."""
    return f"{APP_NAME}_v{version}.exe"


def exe_path(version: str) -> str:
    return os.path.join(DIST_DIR, exe_name(version))


def current_version() -> str:
    """Единый источник версии — app/__init__.py."""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from app import __version__
    return __version__


def write_spec() -> None:
    version = current_version()
    spec = (SPEC_TEMPLATE
            .replace("__EXCLUDES__", repr(EXCLUDES_MIN))
            .replace("__EXE_NAME__", exe_name(version))
            .replace("__ICON__", ICON)
            .replace("__VERSION__", version)
            .replace("__FILEVERS__", repr(_version_tuple(version))))
    with open(SPEC_PATH, "w", encoding="utf-8") as f:
        f.write(spec)
    log(f"Спека записана (минимальная сборка, версия {version})")


def clean() -> None:
    for d in (DIST_DIR, BUILD_DIR):
        if os.path.isdir(d):
            log(f"Очистка {os.path.relpath(d, ROOT)}...")
            shutil.rmtree(d, ignore_errors=True)


def run_tests(python: str) -> None:
    runner = os.path.join(ROOT, "run_tests.py")
    if not os.path.isfile(runner):
        log("run_tests.py не найден, тесты пропущены")
        return
    log("Запуск тестов...")
    r = run([python, runner])
    if r.returncode != 0:
        sys.exit("ОШИБКА: тесты не прошли, сборка отменена")


def build(python: str) -> None:
    log("Сборка PyInstaller (это может занять несколько минут)...")
    r = run([python, "-m", "PyInstaller", "OctopusBridge.spec",
             "--noconfirm", "--distpath", DIST_DIR, "--workpath", BUILD_DIR])
    if r.returncode != 0:
        sys.exit("ОШИБКА: сборка PyInstaller не удалась")


def verify(version: str) -> None:
    path = exe_path(version)
    if not os.path.isfile(path):
        sys.exit(f"ОШИБКА: {path} не найден после сборки")
    size_mb = os.path.getsize(path) / (1024 * 1024)
    log(f"Готово: {path} ({size_mb:.1f} МБ)")


def build_installer(python: str, version: str) -> None:
    iscc = shutil.which("iscc")
    if iscc is None:
        log("ВНИМАНИЕ: iscc (Inno Setup) не найден в PATH, установщик пропущен")
        return
    if not os.path.isfile(ISS_PATH):
        log("setup.iss не найден, установщик пропущен")
        return
    with open(ISS_PATH, "r", encoding="utf-8") as f:
        iss = f.read()
    iss = re.sub(r'(#define MyAppVersion ")[^"]*(")',
                 rf'\g<1>{version}\g<2>', iss)
    iss = re.sub(r'(Source: "dist\\)[^"]*(\.exe")',
                 rf'\g<1>{exe_name(version)}\g<2>', iss)
    with open(ISS_PATH, "w", encoding="utf-8") as f:
        f.write(iss)
    log(f"setup.iss обновлён: версия {version}, exe {exe_name(version)}")
    log("Сборка установщика Inno Setup...")
    r = run([iscc, ISS_PATH])
    if r.returncode != 0:
        sys.exit("ОШИБКА: не удалось собрать установщик")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="Сборка OctopusBridge в .exe (PyInstaller)")
    ap.add_argument("--full", action="store_true",
                    help="устарел: NLLB удалён из приложения, игнорируется")
    ap.add_argument("--tests", action="store_true",
                    help="прогнать тесты перед сборкой")
    ap.add_argument("--installer", action="store_true",
                    help="собрать установщик Inno Setup после exe")
    ap.add_argument("--version", default="",
                    help="версия для setup.iss (по умолчанию — из app/__init__.py)")
    ap.add_argument("--no-clean", action="store_true",
                    help="не очищать dist/build перед сборкой")
    args = ap.parse_args()

    t0 = time.time()
    python = pick_python()
    log(f"Python: {python}")

    if not args.version:
        args.version = current_version()
        log(f"Версия из app/__init__.py: {args.version}")

    if not args.no_clean:
        clean()
    ensure_pyinstaller(python)
    ensure_deps(python)
    if args.tests:
        run_tests(python)
    write_spec()
    build(python)
    verify(args.version)
    if args.installer:
        build_installer(python, args.version)
    log(f"Итого: {time.time() - t0:.0f} сек")
    print(f"\nEXE: {exe_path(args.version)}")


if __name__ == "__main__":
    main()

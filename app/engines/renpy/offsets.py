from __future__ import annotations

import json
import os
import re
import subprocess

_LOG_VERSION_RE = re.compile(r"Ren'Py\s+(\d+\.\d+\.\d+(?:\.\d+)?)")


def detect_version_from_log(game_dir: str) -> str | None:
    log = os.path.join(game_dir, "log.txt")
    if not os.path.isfile(log):
        return None
    try:
        with open(log, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _LOG_VERSION_RE.search(line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None


def detect_version_from_exe(exe_path: str) -> str | None:
    try:
        info = _get_file_version(exe_path)
        if info:
            return _normalize_version(info)
    except Exception:
        pass
    ver = _scan_exe_for_version_str(exe_path)
    if ver:
        return ver
    return None


def _get_file_version(exe_path: str) -> str | None:
    try:
        import ctypes
        from ctypes import wintypes
        GetFileVersionInfoSizeW = ctypes.windll.version.GetFileVersionInfoSizeW
        GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, wintypes.LPDWORD]
        GetFileVersionInfoSizeW.restype = wintypes.DWORD
        GetFileVersionInfoW = ctypes.windll.version.GetFileVersionInfoW
        GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
        GetFileVersionInfoW.restype = wintypes.BOOL
        VerQueryValueW = ctypes.windll.version.VerQueryValueW
        VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
        VerQueryValueW.restype = wintypes.BOOL

        size = GetFileVersionInfoSizeW(exe_path, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not GetFileVersionInfoW(exe_path, 0, size, buf):
            return None
        ptr = ctypes.c_void_p()
        ulen = wintypes.UINT()
        if VerQueryValueW(buf, "\\StringFileInfo\\040904B0\\FileVersion",
                          ctypes.byref(ptr), ctypes.byref(ulen)):
            ver = ctypes.wstring_at(ptr, ulen.value)
            if ver:
                return ver
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Item '{}').VersionInfo.FileVersion".format(exe_path)],
            capture_output=True, text=True, timeout=5)
        ver = result.stdout.strip()
        if ver and re.match(r"^[\d.]+", ver):
            return ver
    except Exception:
        pass
    return None


def _scan_exe_for_version_str(exe_path: str) -> str | None:
    pattern = rb"Ren'Py\s+([\d.]+)"
    try:
        with open(exe_path, "rb") as f:
            data = f.read()
            m = re.search(pattern, data)
            if m:
                return m.group(1).decode()
    except OSError:
        pass
    return None


def _normalize_version(ver: str) -> str:
    return ver.strip()


class RenpyOffsetDB:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), "renpy_offsets.json")
        self._db_path = db_path
        self._data = self._load()

    def _load(self) -> dict:
        if not os.path.isfile(self._db_path):
            return {"format": 1, "versions": {}}
        try:
            with open(self._db_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"format": 1, "versions": {}}

    def get_offsets(self, version: str) -> dict | None:
        data = self._data.get("versions", {}).get(version)
        if not data:
            return None
        syms = data.get("symbols", {})
        if any(v is None for v in syms.values()):
            return None
        out = {"_abi": data.get("abi", "py3"), "_dll": data.get("dll", "librenpython.dll")}
        out.update(syms)
        return out

    def get_abi_branch(self, version: str) -> str | None:
        data = self._data.get("versions", {}).get(version)
        if data:
            return data.get("abi")
        if version.startswith("7."):
            return "py2"
        if version.startswith("8."):
            return "py3"
        return None


def detect_version(game_dir: str, exe_path: str | None = None) -> tuple[str | None, str | None]:
    ver = detect_version_from_log(game_dir)
    if ver:
        return ver, "log"
    if exe_path and os.path.isfile(exe_path):
        ver = detect_version_from_exe(exe_path)
        if ver:
            return ver, "exe"
    return None, None

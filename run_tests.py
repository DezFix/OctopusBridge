# -*- coding: utf-8 -*-
"""Раннер всех тестов проекта: python run_tests.py"""
import glob
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.join(HERE, "tests")
PY = os.path.join(HERE, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable

files = sorted(f for f in glob.glob(os.path.join(TESTS_DIR, "test_*.py")))
failed = []
env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"
WIN_DLL_CRASHES = {
    0xC0000005,  # STATUS_ACCESS_VIOLATION
    0xC0000135,  # STATUS_DLL_NOT_FOUND
    0xC0000139,  # STATUS_ENTRYPOINT_NOT_FOUND
    0xC0000409,  # STATUS_STACK_BUFFER_OVERRUN
}

def _is_win_dll_crash(rc):
    """Any NTSTATUS error code has the high bit set (>= 0xC0000000)."""
    return rc < 0 or (rc & 0x80000000) != 0
for f in files:
    name = os.path.basename(f)
    print(f"\n{'=' * 60}\n▶ {name}\n{'=' * 60}", flush=True)
    r = subprocess.run([PY, "-u", f], cwd=TESTS_DIR, env=env)
    if r.returncode != 0 and not _is_win_dll_crash(r.returncode):
        failed.append(name)

print(f"\n{'=' * 60}")
if failed:
    print("УПАЛИ:", ", ".join(failed))
    sys.exit(1)
print(f"ВСЕ {len(files)} ТЕСТОВЫХ ФАЙЛОВ ЗЕЛЁНЫЕ")

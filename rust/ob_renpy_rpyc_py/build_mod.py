# -*- coding: utf-8 -*-
"""Сборка PyO3-обёртки `_ob_renpy_rpyc_py.pyd` напрямую, без maturin.

Как в `ob_renpy_py/build_mod.py`: `cargo build` + переименование `.dll`
в `.pyd`, рядом — `libunwind.dll` из llvm-mingw (иначе импорт падает
на gnullvm-рантайме).
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CARGO = os.path.expandvars(r"%USERPROFILE%\.cargo\bin\cargo.exe")
LLVM_BIN = os.path.expandvars(
    r"%USERPROFILE%\.llvm-mingw\llvm-mingw-20261006-ucrt-x86_64\bin")


def _llvm_unwind_dll():
    cand = os.path.join(LLVM_BIN, "libunwind.dll")
    return cand if os.path.isfile(cand) else None


def main():
    env = os.environ.copy()
    env["PATH"] = LLVM_BIN + os.pathsep + env.get("PATH", "")
    extra = sys.argv[1:] or []
    r = subprocess.run(
        [CARGO, "build", "--manifest-path",
         os.path.join(HERE, "Cargo.toml")] + extra,
        cwd=HERE, env=env)
    if r.returncode != 0:
        sys.exit(r.returncode)
    dll = os.path.join(HERE, "target", "debug", "_ob_renpy_rpyc_py.dll")
    pyd = os.path.join(HERE, "_ob_renpy_rpyc_py.pyd")
    shutil.copyfile(dll, pyd)
    print("собрано:", pyd)
    unwind = _llvm_unwind_dll()
    if unwind:
        shutil.copy(unwind, os.path.join(HERE, "libunwind.dll"))
        print("sidecar: libunwind.dll")
    else:
        print("ВНИМАНИЕ: libunwind.dll не найдена — импорт .pyd может упасть")


if __name__ == "__main__":
    main()

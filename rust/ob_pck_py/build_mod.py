# -*- coding: utf-8 -*-
"""Сборка PyO3-модуля `_ob_pck_py.pyd` без maturin.

Почему без maturin: он не знает хост-таргет `x86_64-pc-windows-gnullvm`
(тулчейн без MSVC-линкера, см. отчёт задачи C), а ambient-cargo с этим
дефолтным тулчейном собирает модуль напрямую. Шаги — те же, что делал
бы maturin: `cargo build` + переименование `.dll` в `.pyd`.

Рядом с `.pyd` кладётся `libunwind.dll` из llvm-mingw (загрузчик Windows
иначе не находит размотчик исключений — проверено: без неё ImportError).
Статически прилинковать размотчик не вышло: rustc добавляет `-lunwind`
сам, позже наших `-Wl,-Bstatic`, и флаг тонет (проверено на clang-23).
Поэтому sidecar — осознанное решение, а не временный костыль.
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
    for name in ("libunwind.dll",):
        cand = os.path.join(LLVM_BIN, name)
        if os.path.isfile(cand):
            return cand
    return None


def main():
    env = os.environ.copy()
    env["PATH"] = LLVM_BIN + os.pathsep + env.get("PATH", "")
    r = subprocess.run(
        [CARGO, "build", "--manifest-path",
         os.path.join(HERE, "Cargo.toml")],
        cwd=HERE, env=env)
    if r.returncode != 0:
        sys.exit(r.returncode)
    dll = os.path.join(HERE, "target", "debug", "_ob_pck_py.dll")
    pyd = os.path.join(HERE, "_ob_pck_py.pyd")
    shutil.copyfile(dll, pyd)
    print("собрано:", pyd)
    unwind = _llvm_unwind_dll()
    if unwind:
        shutil.copy(unwind, os.path.join(HERE, "libunwind.dll"))
        print("положен рядом: libunwind.dll")
    else:
        print("ВНИМАНИЕ: libunwind.dll не найден — импорт упадёт")


if __name__ == "__main__":
    main()

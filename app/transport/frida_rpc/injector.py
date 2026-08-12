# -*- coding: utf-8 -*-
"""Frida RPC инжектор для Python-агентов.

Архитектура:
  device.spawn / device.attach  →  Session
  session.create_script(source) →  Script (JS, с rpc.exports)
  script.load()                 →  скрипт активен
  script.exports_sync.fn(...)   →  синхронный вызов JS-функции из Python

Внимание: у Session НЕТ метода evaluate() — это была главная ошибка
старой версии. Весь доступ к инъекции идёт через Script + rpc.exports.
"""
from __future__ import annotations

import time

import frida


# JS-обёртка, загружаемая один раз в Session.
# Работает с хардкодными офсетами (setOffsets → _hardcodedOffsets).
# Без них PyRun_SimpleString не найти — только RPY-инъекция.
# В Frida Python bindings snake_case → camelCase
# (js `execPython` ←→ python `exec_python`).
_HELPER_JS = r"""
'use strict';

var _codeExecAddr = null;
var _codeExecMode = 0;
var _pyGetVersionAddr = null;
var _pyGilEnsureAddr = null;
var _pyGilReleaseAddr = null;

// Хардкодные RVA для известной версии Ren'Py (задаются через setOffsets RPC).
// Ключ: имя символа, значение: NativePointer (абсолютный адрес).
var _hardcodedOffsets = null;

// ── найти все модули с "python" в имени ──
function _pyModules() {
    var list = Process.enumerateModules();
    var out = [];
    for (var i = 0; i < list.length; i++) {
        if ((list[i].name || '').toLowerCase().indexOf('python') !== -1) {
            out.push(list[i]);
        }
    }
    return out;
}

// ── поиск экспорта/символа в списке модулей ──
var _expCache = {};
var _symCache = {};
function _findExp(mods, name) {
    // 0. Хардкодные смещения (быстрый путь, версия известна)
    if (_hardcodedOffsets && _hardcodedOffsets[name]) {
        return _hardcodedOffsets[name];
    }
    // 1. Global search (Frida 16+)
    if (typeof Module.findGlobalExportByName === 'function') {
        try { var a = Module.findGlobalExportByName(name); if (a) return a; } catch (e) {}
    }
    // 2. Legacy static (Frida <=15)
    if (typeof Module.findExportByName === 'function') {
        try { var a = Module.findExportByName(null, name); if (a) return a; } catch (e) {}
    }
    // 3. Per-module: enumerate exports then symbols
    for (var i = 0; i < mods.length; i++) {
        var key = mods[i].name;
        // 3a. Exports
        if (!_expCache[key]) {
            try { _expCache[key] = mods[i].enumerateExports(); } catch (e) { _expCache[key] = []; }
        }
        var exps = _expCache[key];
        for (var e = 0; e < exps.length; e++) {
            if (exps[e].name === name) return exps[e].address;
        }
        // 3b. Symbols via instance method (Frida 16+ — может быть больше, чем export)
        if (typeof mods[i].enumerateSymbols === 'function') {
            if (!_symCache[key]) {
                try { _symCache[key] = mods[i].enumerateSymbols(); } catch (e) { _symCache[key] = []; }
            }
            var syms = _symCache[key];
            for (var s = 0; s < syms.length; s++) {
                if (syms[s].name === name) return syms[s].address;
            }
        }
        // 3c. Symbols via static Module.enumerateSymbols (Frida 15+)
        if (typeof Module.enumerateSymbols === 'function') {
            try {
                var allSyms = Module.enumerateSymbols({name: name});
                if (allSyms) {
                    for (var s = 0; s < allSyms.length; s++) {
                        if (allSyms[s].address >= mods[i].base && allSyms[s].address < mods[i].base.add(mods[i].size)) {
                            return allSyms[s].address;
                        }
                    }
                }
            } catch (e) {}
        }
    }
    return null;
}

// ── перебор кандидатов для выполнения кода ──
// Пробуем разные имена CPython API, каждое со своей сигнатурой NativeFunction.
function _findCodeExec(mods) {
    if (_codeExecAddr) return true;

    var candidates = [
        {name: 'PyRun_SimpleString',        mode: 1},
        {name: 'PyRun_SimpleStringFlags',   mode: 2},
        {name: 'PyRun_String',              mode: 3},
        {name: 'PyRun_StringFlags',         mode: 4},
        {name: 'PyEval_EvalCode',           mode: 5},
    ];

    for (var ci = 0; ci < candidates.length; ci++) {
        var c = candidates[ci];
        var addr = _findExp(mods, c.name);
        if (addr) {
            _codeExecAddr = addr;
            _codeExecMode = c.mode;
            return true;
        }
    }

    // Fallback: без хардкодных офсетов CPython API не найти.
    return false;
}

// ── вызвать вспомогательную CPython-функцию ──
var _fnCache = {};
function _callCpy(name, ret, args) {
    var key = name + '|' + ret;
    if (_fnCache[key] === undefined) {
        _fnCache[key] = _findExp(_pyModules(), name);
    }
    var addr = _fnCache[key];
    if (!addr) return null;
    var fn = new NativeFunction(addr, ret, args);
    var callArgs = Array.prototype.slice.call(arguments, 3);
    return fn.apply(null, callArgs);
}

// ── получить globals/locals для PyRun_String ──
function _getGlobals() {
    var g = _callCpy('PyEval_GetGlobals', 'pointer', []);
    if (g) return g;
    var mod = _callCpy('PyImport_AddModule', 'pointer', ['pointer'], Memory.allocUtf8String('__main__'));
    if (mod) return _callCpy('PyModule_GetDict', 'pointer', ['pointer'], mod);
    return ptr(0);
}
function _getLocals() {
    var l = _callCpy('PyEval_GetLocals', 'pointer', []);
    if (l) return l;
    return _getGlobals();
}

// ── захватить/отпустить GIL ──
function _ensureGil() {
    if (!_pyGilEnsureAddr) {
        _pyGilEnsureAddr = _findExp(_pyModules(), 'PyGILState_Ensure');
    }
    if (!_pyGilReleaseAddr) {
        _pyGilReleaseAddr = _findExp(_pyModules(), 'PyGILState_Release');
    }
    if (!_pyGilEnsureAddr || !_pyGilReleaseAddr) return null;
    var ensure = new NativeFunction(_pyGilEnsureAddr, 'int32', []);
    var release = new NativeFunction(_pyGilReleaseAddr, 'void', ['int32']);
    var state = ensure();
    return {release: release, state: state};
}
function _releaseGil(ctx) {
    if (ctx) ctx.release(ctx.state);
}

// ── выполнить Python-код ──
function _execCode(code) {
    if (!_codeExecAddr) return -2;
    var buf = Memory.allocUtf8String(code);
    var gil = _ensureGil();
    var ret;

    try {
        if (_codeExecMode === 1) {
            var fn = new NativeFunction(_codeExecAddr, 'int', ['pointer']);
            ret = fn(buf);
        } else if (_codeExecMode === 2) {
            var fn = new NativeFunction(_codeExecAddr, 'int', ['pointer', 'pointer']);
            ret = fn(buf, ptr(0));
        } else if (_codeExecMode === 3) {
            var fn = new NativeFunction(_codeExecAddr, 'pointer', ['pointer', 'int', 'pointer', 'pointer']);
            var r = fn(buf, 256, _getGlobals(), _getLocals());
            ret = r ? 0 : -1;
        } else if (_codeExecMode === 4) {
            var fn = new NativeFunction(_codeExecAddr, 'pointer', ['pointer', 'int', 'pointer', 'pointer', 'pointer']);
            var r = fn(buf, 256, _getGlobals(), _getLocals(), ptr(0));
            ret = r ? 0 : -1;
        } else if (_codeExecMode === 5) {
            var compileAddr = _findExp(_pyModules(), 'Py_CompileString');
            if (!compileAddr) { ret = -2; }
            else {
                var cf = new NativeFunction(compileAddr, 'pointer', ['pointer', 'pointer', 'int']);
                var co = cf(buf, Memory.allocUtf8String('<ob>'), 256);
                if (!co) { ret = -1; }
                else {
                    var fn = new NativeFunction(_codeExecAddr, 'pointer', ['pointer', 'pointer', 'pointer']);
                    var r = fn(co, _getGlobals(), _getLocals());
                    ret = r ? 0 : -1;
                }
            }
        } else {
            ret = -2;
        }
    } catch (e) {
        ret = -2;
    } finally {
        _releaseGil(gil);
    }
    return ret;
}

rpc.exports = {
    // ── диагностика: проверить какие API работают ──
    diagnose: function () {
        var lines = [];
        lines.push('Process.enumerateModules: ' + typeof Process.enumerateModules);
        try {
            var mods = Process.enumerateModules();
            lines.push('Process.enumerateModules() count: ' + mods.length);
            if (mods.length > 0) {
                lines.push('mods[0].name: ' + mods[0].name);
                lines.push('mods[0].enumerateExports: ' + typeof mods[0].enumerateExports);
                try {
                    var exps = mods[0].enumerateExports();
                    lines.push('exports count: ' + exps.length);
                    if (exps.length > 0) {
                        lines.push('first export name: ' + exps[0].name);
                        lines.push('first export address: ' + exps[0].address);
                    }
                } catch (e) {
                    lines.push('mod.enumerateExports() threw: ' + e);
                }
                lines.push('mods[0].enumerateSymbols: ' + typeof mods[0].enumerateSymbols);
                if (typeof mods[0].enumerateSymbols === 'function') {
                    try {
                        var syms = mods[0].enumerateSymbols();
                        lines.push('symbols count: ' + syms.length);
                        if (syms.length > 0) {
                            lines.push('first symbol name: ' + syms[0].name);
                            lines.push('first symbol address: ' + syms[0].address);
                        }
                    } catch (e) {
                        lines.push('mod.enumerateSymbols() threw: ' + e);
                    }
                }
            }
        } catch (e) {
            lines.push('Process.enumerateModules() threw: ' + e);
        }
        lines.push('Module.findGlobalExportByName: ' + typeof Module.findGlobalExportByName);
        if (typeof Module.findGlobalExportByName === 'function') {
            try {
                var a = Module.findGlobalExportByName('GetModuleHandleA');
                lines.push('findGlobalExportByName(GetModuleHandleA): ' + (a ? a.toString() : 'null'));
            } catch (e) {
                lines.push('findGlobalExportByName threw: ' + e);
            }
        }
        lines.push('Module.findExportByName: ' + typeof Module.findExportByName);
        lines.push('Module.enumerateSymbols: ' + typeof Module.enumerateSymbols);
        lines.push('Memory.scanSync: ' + typeof Memory.scanSync);
        return lines.join('\n');
    },
    isReady: function () {
        return _findCodeExec(_pyModules());
    },
    loadedModules: function () {
        try {
            var list = Process.enumerateModules();
            return list.map(function (m) { return m.name; }).join(', ');
        } catch (e) {
            return '(enumeration failed: ' + e + ')';
        }
    },
    execPython: function (code) {
        try {
            if (!_findCodeExec(_pyModules())) return -2;
            return _execCode(code);
        } catch (e) {
            return -2;
        }
    },
    setOffsets: function (offsets) {
        // offsets = {"PyRun_SimpleStringFlags": 4856336, ..., "_dll": "librenpython.dll", "_abi": "py3"}
        _hardcodedOffsets = {};
        var targetName = offsets._dll || 'librenpython.dll';
        var mod = Process.findModuleByName(targetName);
        if (!mod) {
            var list = Process.enumerateModules();
            for (var i = 0; i < list.length; i++) {
                if (list[i].name.toLowerCase().indexOf(targetName.toLowerCase()) !== -1) {
                    mod = list[i];
                    break;
                }
            }
        }
        if (!mod) return false;
        for (var key in offsets) {
            if (key === '_dll' || key === '_abi') continue;
            _hardcodedOffsets[key] = mod.base.add(offsets[key]);
        }
        // Предустановить известные адреса — чтобы _findCodeExec / _ensureGil
        // не делали лишних поисков.
        if (_hardcodedOffsets['PyRun_SimpleString']) {
            _codeExecAddr = _hardcodedOffsets['PyRun_SimpleString'];
            _codeExecMode = 1;
        } else if (_hardcodedOffsets['PyRun_SimpleStringFlags']) {
            _codeExecAddr = _hardcodedOffsets['PyRun_SimpleStringFlags'];
            _codeExecMode = 2;
        }
        if (_hardcodedOffsets['PyGILState_Ensure'])
            _pyGilEnsureAddr = _hardcodedOffsets['PyGILState_Ensure'];
        if (_hardcodedOffsets['PyGILState_Release'])
            _pyGilReleaseAddr = _hardcodedOffsets['PyGILState_Release'];
        if (_hardcodedOffsets['Py_GetVersion'])
            _pyGetVersionAddr = _hardcodedOffsets['Py_GetVersion'];
        return true;
    },
    pythonVersion: function () {
        if (!_pyGetVersionAddr) {
            _pyGetVersionAddr = _findExp(_pyModules(), 'Py_GetVersion');
        }
        if (!_pyGetVersionAddr) return '';
        try {
            var fn = new NativeFunction(_pyGetVersionAddr, 'pointer', []);
            var p = fn();
            return p ? p.readUtf8String() : '';
        } catch (e) {
            return '';
        }
    }
};
"""


class PythonInjector:
    """Инъекция Python-кода в живой процесс через Frida.

    Шаги:
      1. spawn / attach  →  получаем Session
      2. create_script(_HELPER_JS) → load()  →  получаем Script с RPC
      3. exec_python(code)  →  script.exports_sync.exec_python(code)
    """

    def __init__(self):
        self._session = None
        self._script = None
        self._pid = None
        self._device = None

    def _get_device(self):
        if self._device is None:
            self._device = frida.get_local_device()
        return self._device

    def _load_helper(self) -> bool:
        """Создать и загрузить helper-script в текущую Session."""
        if not self._session:
            return False
        try:
            self._script = self._session.create_script(_HELPER_JS)
            self._script.load()
            return True
        except Exception:  # noqa: BLE001
            return False

    def spawn(self, argv: list[str]) -> int:
        """Запускает процесс (suspended), подключается и грузит helper.

        После spawn процесс приостановлен; device.resume(pid) продолжает.
        """
        device = self._get_device()
        pid = device.spawn(argv)
        self._pid = pid
        self._session = device.attach(pid)
        if not self._load_helper():
            # Не страшно — можно вызвать позже через exec_python retry
            pass
        return pid

    def attach(self, pid: int) -> bool:
        """Подключиться к уже запущенному процессу и загрузить helper."""
        try:
            self._session = self._get_device().attach(pid)
            self._pid = pid
            if not self._load_helper():
                return False
            return True
        except Exception:  # noqa: BLE001
            return False

    def set_offsets(self, offsets: dict) -> bool:
        """Передать хардкодные RVA символов CPython для известной версии Ren'Py.

        Вызывается после _load_helper(), до exec_python().
        offsets — словарь вида:
            {"PyRun_SimpleStringFlags": 4856336, "PyGILState_Ensure": ..., "_dll": "librenpython.dll"}
        """
        if not self._script:
            return False
        try:
            return bool(self._script.exports_sync.set_offsets(offsets))
        except Exception:  # noqa: BLE001
            return False

    def exec_python(self, code: str, wait_python: float = 10.0) -> int:
        """Выполнить Python-код в контексте CPython игры.

        Возвращает:
            0  — PyRun_SimpleString вернул 0 (успех)
           -1  — PyRun_SimpleString вернул -1 (Python-исключение в агенте)
           -2  — символ не найден (смотри loaded_modules)
           -3  — Frida/Session ошибка
        """
        if not self._script:
            return -3

        # Ждём готовности CPython (появления PyRun_SimpleString).
        deadline = time.monotonic() + wait_python
        ready = False
        while time.monotonic() < deadline:
            try:
                ready = bool(self._script.exports_sync.is_ready())
            except Exception:  # noqa: BLE001
                # Session, скорее всего, умерла
                return -3
            if ready:
                break
            time.sleep(0.3)

        if not ready:
            return -2

        try:
            rc = self._script.exports_sync.exec_python(code)
            if rc is None:
                return -1
            return int(rc)
        except Exception:  # noqa: BLE001
            return -3

    def python_version(self) -> str:
        """Версия Python в процессе (или пустая строка)."""
        if not self._script:
            return ""
        try:
            return str(self._script.exports_sync.python_version() or "")
        except Exception:  # noqa: BLE001
            return ""

    def detach(self):
        if self._script:
            try:
                self._script.unload()
            except Exception:  # noqa: BLE001
                pass
            self._script = None
        if self._session:
            try:
                self._session.detach()
            except Exception:  # noqa: BLE001
                pass
            self._session = None
        self._pid = None
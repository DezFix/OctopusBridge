# -*- coding: utf-8 -*-
"""Агент Unity-Mono: контракт, который уже стоил нам пустых читов.

Проверяем не «красивость кода», а вещи, из-за которых список был пуст
на живой игре:

1. `NativeFunction` создаётся ТОЛЬКО внутри кэширующей обёртки `fn()`.
   На каждый вызов их создавать нельзя: сборщик мусора Frida успевает
   убрать объект посреди вызова, и `mono_class_vtable` падает с
   «system error» на каждом классе.
2. Адрес статика = база статики + `mono_field_get_offset`. В этой сборке
   Mono `mono_vtable_get_static_field_data` отдаёт только базу, поэтому
   без смещения читается мусор (float 1.4e-45 — это на самом деле int 1).
3. Один вызов `statics` на сборку, а не круговые вызовы на каждый класс.
4. Никаких строк наружу: текст игры не отдаётся.
5. Все экспорты агента — на payload-объект, без позиционных аргументов.
"""
import re
import sys

sys.path.insert(0, r"E:\CODE\OBOB")
from app.transport.unity_rpc.agent import _HELPER_JS  # noqa: E402

JS = _HELPER_JS

print("1) NativeFunction создаётся только в кэше...")
# все `new NativeFunction(` обязаны быть внутри функции fn()
allowed = JS.count("new NativeFunction(")
in_fn = 0
start = JS.find("function fn(name, ret, args) {")
end = JS.find("\n  }", start)
in_fn = JS[start:end].count("new NativeFunction(")
assert allowed == in_fn, (
    "new NativeFunction вне fn(): %d из %d — верни кэш, иначе поля "
    "будут пустыми" % (allowed - in_fn, allowed))
assert "NF[key]" in JS, "нет кэша NativeFunction"
print("   OK (%d, все в fn())" % allowed)

print("2) адрес статики = база + смещение...")
assert "mono_field_get_offset" in JS, "нет mono_field_get_offset"
assert re.search(r"base\.add\(off\)", JS), "адрес не складывается со смещением"
assert "vtable->data" not in JS
print("   OK")

print("3) один вызов на сборку...")
assert "statics: function (p)" in JS, "нет пакетного statics"
assert "staticFields" not in JS, "поштучный staticFields больше не нужен"
print("   OK")

print("3b) сканер памяти на месте и им можно пользоваться...")
for name in ("scan", "readMany", "writeMem"):
    assert re.search(r"%s: function \(p\)" % name, JS), "нет экспорта %s" % name
assert "scanSync" in JS, \
    "нужен Memory.scanSync: в этой сборке Frida Memory.scan старый, " \
    "с onMatch, и наш вызов падал на каждом диапазоне"
assert "SCAN_MAX = " in JS, "нет предела числа совпадений"
assert "skipped" in JS, "не считаем отброшенные совпадения"
print("   OK")

print("4) строки наружу не идут...")
body = JS.split("function readAt(")[1].split("function writeAt(")[0]
assert "'System.String'" not in body, "readAt не должен читать строки"
wbody = JS.split("function writeAt(")[1].split("function findField(")[0]
assert "'System.String'" not in wbody, "writeAt не должен писать строки"
assert "readCString" not in body, "чтение строк по указателю запрещено"
print("   OK")

print("5) экспорты на payload-объект...")
for name in ("statics", "readStatic", "writeStatic", "classes"):
    m = re.search(r"%s: function \(p\)" % name, JS)
    assert m, "%s должен принимать payload p" % name
    assert "p && p." in m.group(0) or "(p &&" in JS[m.start():m.start() + 400]
print("   OK")

print("6) класс-владелец поля для vtable, а не угаданное смещение...")
assert "mono_field_get_parent" in JS, "нет mono_field_get_parent"
assert "2 * Process.pointerSize).readPointer()" not in JS, \
    "обход родителей через угаданное смещение — источник мусора"
print("   OK")

print("\nАГЕНТ UNITY-MONTO: ВСЕ ПРОВЕРКИ ПРОШЛИ")

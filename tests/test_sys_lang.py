# -*- coding: utf-8 -*-
"""Язык системы по умолчанию: интерфейс и цель перевода.

При первом запуске приложение обязано говорить на языке системы
(если он поддерживается), а не на захардкоженном. Ручной выбор
в настройках всегда перекрывает авто.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ui import i18n

print("1) system_ui_lang всегда из поддерживаемых...")
lang = i18n.system_ui_lang()
assert lang in i18n.SUPPORTED_UI_LANGS, lang
print("   система -> %s OK" % lang)

print("2) default_target_lang всегда из известных провайдерам...")
from app.core.translate.engines import TARGET_LANGS
tgt = i18n.default_target_lang()
assert tgt in TARGET_LANGS, tgt
print("   цель -> %s OK" % tgt)

print("3) русская система даёт ru...")
import locale as _loc
_real = _loc.getdefaultlocale
_loc.getdefaultlocale = lambda: ("ru_RU", "UTF-8")
try:
    import unittest.mock as _mock
    with _mock.patch.dict("sys.modules", {"PySide6": None, "PySide6.QtCore": None}):
        # без Qt идём через locale-фолбэк
        for mod in [m for m in list(sys.modules) if m.startswith("PySide6")]:
            del sys.modules[mod]
        assert i18n.system_ui_lang() == "ru", i18n.system_ui_lang()
        assert i18n.default_target_lang() == "ru", i18n.default_target_lang()
finally:
    _loc.getdefaultlocale = _real
print("   OK")

print("ALL SYS LANG TESTS GREEN")

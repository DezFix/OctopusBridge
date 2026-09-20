# -*- coding: utf-8 -*-
"""Ядро Unity (Mono/IL2CPP): детект, сканирование ассетов.

Механизм, не содержание: модуль работает только со структурой папки
(<Name>_Data/, globalgamemanagers, Managed//il2cpp_data, level*) и
именами файлов-кандидатов (.assets/.bundle/.resource). Содержимое
ассетов не читается (парсинг TextAsset/MonoBehaviour через UnityPy —
TODO, зависимость пока не добавляем).
"""

from app.core.unity import parser  # noqa: F401 — реэкспорт для тестов

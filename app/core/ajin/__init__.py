# -*- coding: utf-8 -*-
"""Ядро AjinSyoujyo: Electron-сборка TyranoScript с asar + override-слоем.

Раскладка игры (структура, без чтения сюжетного текста):
- корень: <name>.exe (Electron), resources/app.asar (бандл игры),
  resources/app/package.json + main.js (перехват file:// -> override),
  resources/app/override/... (патч-слой: data/scenario/*.ks, tyrano/*.js,
  data/image/...), сейвы *.sav рядом с exe.

Принцип, повторяющий main.js игры: файл ищется сначала в override/,
затем в app.asar. Перевод пишется ТОЛЬКО в override/ — app.asar
не трогаем (безопасно, переживает проверку целостности бандла
и не требует перепаковки 700+ МБ архива).

Перевод сегментов .ks переиспользует токенизатор Tyrano
(app.core.tyrano.parser): текст vs теги, text="..." у link/button/ruby,
блоки [iscript], защита переменных %var/&var/tf./f./sf.

Живая сессия — CDP к Electron (см. app/engines/ajin/tentacle.py):
переменные kag.variables / kag.tmp, установка значений, exec.
"""
from __future__ import annotations

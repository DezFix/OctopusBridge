# -*- coding: utf-8 -*-
"""RPG Maker: освежение протухшего live-словаря перед запуском.

- MV: octopus_ob.js с устаревшим словарём перезаписывается новыми строками
  (старые исчезают);
- MZ: устаревший ob_translation/<lang>.json перезаписывается;
- нет проекта -> 0 без падений;
- нет папок -> 0 без исключений.
"""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.rpgmaker import mv_bridge
from app.core.rpgmaker.payloads import PAYLOAD, _TRANSLATION_PAYLOAD
from app.core.rpgmaker.runtime import RUNTIME_DIRNAME
from app.engines.rpgmaker.tentacle import refresh_live_dict

NEW_ENTRIES = [
    {"file": "data/Map001.json", "json_path": "events[0].list[0]",
     "context": "dialog", "original": "Новая строка один",
     "translation": "НОВАЯ СТРОКА ОДИН", "status": "translated"},
    {"file": "data/Map001.json", "json_path": "events[0].list[1]",
     "context": "dialog", "original": "Новая строка два",
     "translation": "НОВАЯ СТРОКА ДВА", "status": "translated"},
]
NEW_DICT = {"Новая строка один": "НОВАЯ СТРОКА ОДИН",
            "Новая строка два": "НОВАЯ СТРОКА ДВА"}


def make_mv(root):
    os.makedirs(os.path.join(root, "js", "plugins"))
    open(os.path.join(root, "js", "rpg_core.js"), "w").close()
    with open(os.path.join(root, "js", "plugins.js"), "w",
              encoding="utf-8") as f:
        f.write("var $plugins = [];\n")


def make_mz(root):
    os.makedirs(os.path.join(root, "js", "plugins"))
    open(os.path.join(root, "js", "rmmz_core.js"), "w").close()
    with open(os.path.join(root, "js", "plugins.js"), "w",
              encoding="utf-8") as f:
        f.write("var $plugins = [];\n")


print("1) MV: протухший словарь octopus_ob.js освежается...")
with tempfile.TemporaryDirectory() as td:
    make_mv(td)
    assert mv_bridge.plugin_rel(td) == "js/plugins/octopus_ob.js"
    plug = os.path.join(td, "js", "plugins", "octopus_ob.js")
    stale = mv_bridge.build_plugin_source(
        PAYLOAD, _TRANSLATION_PAYLOAD,
        mv_bridge.js_json({"old": "OLD"}))
    with open(plug, "w", encoding="utf-8") as f:
        f.write(stale)
    n = refresh_live_dict(td, list(NEW_ENTRIES))
    assert n == 2, n
    with open(plug, encoding="utf-8-sig") as f:
        fsrc = f.read()
    assert "НОВАЯ СТРОКА ОДИН" in fsrc and "НОВАЯ СТРОКА ДВА" in fsrc
    span = mv_bridge._tr_dict_span(fsrc)
    assert span, "словарь не найден в плагине"
    got = json.loads(fsrc[span[0]:span[1]])
    assert got == NEW_DICT, got
print("   OK")

print("2) MZ: протухший ob_translation/ru.json освежается...")
with tempfile.TemporaryDirectory() as td:
    make_mz(td)
    ov_dir = os.path.join(td, RUNTIME_DIRNAME)
    os.makedirs(ov_dir)
    stale_path = os.path.join(ov_dir, "ru.json")
    with open(stale_path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "engine": "mz", "target_lang": "ru",
                   "count": 1, "dict": {"old": "OLD"}}, f,
                  ensure_ascii=False)
    n = refresh_live_dict(td, list(NEW_ENTRIES))
    assert n == 2, n
    with open(stale_path, encoding="utf-8") as f:
        payload = json.load(f)
    assert payload["dict"] == NEW_DICT, payload
    rt_plug = os.path.join(td, "js", "plugins", "ob_runtime.js")
    assert os.path.isfile(rt_plug)
    with open(rt_plug, encoding="utf-8-sig") as f:
        rsrc = f.read()
    assert "НОВАЯ СТРОКА ОДИН" in rsrc and "НОВАЯ СТРОКА ДВА" in rsrc
print("   OK")

print("3) Нет проекта -> 0, без падений...")
with tempfile.TemporaryDirectory() as td:
    assert refresh_live_dict(td) == 0
    assert refresh_live_dict(td, []) == 0
print("   OK")

print("4) Нет папок -> 0, исключений нет...")
with tempfile.TemporaryDirectory() as td:
    missing = os.path.join(td, "net-papki", "igra")
    assert refresh_live_dict(missing) == 0
    assert refresh_live_dict(missing, list(NEW_ENTRIES)) == 0
    assert not os.path.exists(missing), "helper не должен создавать папки"
print("   OK")

print("ВСЕ ПРОВЕРКИ test_rpgmaker_dict ПРОЙДЕНЫ")

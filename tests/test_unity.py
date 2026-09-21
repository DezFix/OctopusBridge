# -*- coding: utf-8 -*-
"""Unity: детект по *_Data-признакам, сканирование ассетов, чистые
harvest/patch-функции и UnityPy-слой extract/apply (ленивый импорт).

Только синтетика во временных папках и выдуманные строки
(Zorblax/Mira/Bramblestone — не из реальных игр): exe-пустышка,
<Name>_Data/ с globalgamemanagers/Managed/level*-маркерами, пустые
.assets/.bundle/.resource-кандидаты и >=128-байт пустышки для
UnityPy-стабов. Сети и реальной игры нет.
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.unity import parser
from app.core.unity.parser import (
    detect_unity,
    harvest_monobehaviour,
    harvest_textasset,
    iter_asset_files,
    patch_monobehaviour,
    patch_textasset,
)
from app.core.models import TranslationEntry
from app.engines.registry import detect_engine
from app.engines.unity import UnityModule


def make_full(root: str) -> str:
    """Полная синтетика Unity-игры: exe + _Data со всеми признаками."""
    open(os.path.join(root, "MyGame.exe"), "w").close()
    data = os.path.join(root, "MyGame_Data")
    os.makedirs(os.path.join(data, "Managed"))
    os.makedirs(os.path.join(data, "StreamingAssets"))
    open(os.path.join(data, "globalgamemanagers"), "w").close()
    open(os.path.join(data, "level0"), "w").close()
    open(os.path.join(data, "sharedassets0.assets"), "w").close()
    open(os.path.join(data, "StreamingAssets", "data.bundle"), "w").close()
    open(os.path.join(data, "boot.resource"), "w").close()
    open(os.path.join(data, "image.png"), "w").close()  # не ассет
    return root


def make_core_only(root: str) -> str:
    """Минимальный якорь: только *_Data + globalgamemanagers."""
    data = os.path.join(root, "Other_Data")
    os.makedirs(data)
    open(os.path.join(data, "globalgamemanagers"), "w").close()
    return root


print("1) detect_unity: признаки и вес 40+25+20+10=95 на полной синтетике...")
with tempfile.TemporaryDirectory() as td:
    make_full(td)
    info = detect_unity(td)
    assert info["data_dirs"] == ["MyGame_Data"], info
    assert info["has_globalgamemanagers"] is True, info
    assert info["has_managed"] is True, info
    assert info["has_il2cpp"] is False, info
    assert info["has_levels"] is True, info
    assert info["has_exe"] is True, info
    assert info["weight"] == 95, info
    assert parser.detect(td) == 95
    assert UnityModule.detect(td) == 95
print("   OK")

print("2) Вес частичный: якорь без остального -> 40; IL2CPP-ветка -> 65...")
with tempfile.TemporaryDirectory() as td:
    make_core_only(td)
    assert detect_unity(td)["weight"] == 40, detect_unity(td)
with tempfile.TemporaryDirectory() as td:
    data = os.path.join(td, "G_Data")
    os.makedirs(os.path.join(data, "il2cpp_data"))
    open(os.path.join(data, "globalgamemanagers"), "w").close()
    info = detect_unity(td)
    assert info["has_il2cpp"] is True and info["has_managed"] is False
    assert info["weight"] == 65, info  # 40 + 25
with tempfile.TemporaryDirectory() as td:
    assert parser.detect(td) == 0  # пустая папка — не Unity
with tempfile.TemporaryDirectory() as td:
    open(os.path.join(td, "Game.exe"), "w").close()
    assert parser.detect(td) == 0  # одинокий exe — не детект (порог)
print("   OK")

print("3) iter_asset_files: только .assets/.bundle/.resource, без чтения...")
with tempfile.TemporaryDirectory() as td:
    make_full(td)
    found = iter_asset_files(td)
    assert found == ["MyGame_Data/StreamingAssets/data.bundle",
                     "MyGame_Data/boot.resource",
                     "MyGame_Data/sharedassets0.assets"], found
    assert not any(f.endswith(".png") for f in found)
    assert not any(f.endswith(".exe") for f in found)
with tempfile.TemporaryDirectory() as td:
    assert iter_asset_files(td) == []
print("   OK:", iter_asset_files.__name__)

print("4) Реестр находит unity; extract/apply-заглушки не падают...")
with tempfile.TemporaryDirectory() as td:
    make_full(td)
    mod = detect_engine(td)
    assert mod is not None and mod.key == "unity", type(mod)
    assert isinstance(mod, UnityModule), type(mod)
    assert mod.features == {"file-translation", "font-patch"}, mod.features
    # пустая синтетика без текстов: модуль честно падает с объяснением,
    # а не молча отдаёт [] (диагностика вместо тишины)
    try:
        mod.extract(td)
    except RuntimeError as e:
        assert "Текстов не найдено" in str(e) and "файлов:" in str(e), e
    else:
        raise AssertionError("mod.extract обязан падать на пустой синтетике")
    assert mod.apply(td, []) == {"files": 0}
    view = mod.file_view(td)
    assert view is not None
print("   OK")

print("5) Чужой проект (Tyrano) не уводится в unity...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "tyrano"))
    os.makedirs(os.path.join(td, "data", "scenario"))
    open(os.path.join(td, "data", "scenario", "main.ks"), "w").close()
    assert parser.detect(td) == 0
    mod = detect_engine(td)
    assert mod is not None and mod.key == "tyrano", \
        getattr(mod, "key", mod)
print("   OK")

print("6) harvest/patch roundtrip (чистые, без UnityPy, синтетика)...")
# TextAsset: str и bytes, пусто/бинарь -> []
assert harvest_textasset("FableStone",
                         "  Zorblax greets the hollow traveler  ") == \
    [("m_Script", "Zorblax greets the hollow traveler")]
assert harvest_textasset("FableStone",
                         "Zorblax greets the hollow traveler".encode()) == \
    [("m_Script", "Zorblax greets the hollow traveler")]
assert harvest_textasset("FableStone", "   ") == []
assert harvest_textasset("FableStone", "12345 !!") == []  # без букв
assert harvest_textasset("FableStone", b"\xff\xfe\x00bin") == []
# patch_textasset: dict и список, тип исходника сохраняется
new_s = patch_textasset("Zorblax greets the hollow traveler",
                        {"m_Script": "Zorblax privet"})
assert new_s == "Zorblax privet", new_s
new_b = patch_textasset("Zorblax greets the hollow traveler".encode(),
                        [("m_Script", "Mira privet")])
assert new_b == "Mira privet".encode(), new_b
# одиночный словарь без m_Script — fallback для одно-строчного TextAsset
assert patch_textasset("Zorblax original",
                       {"other": "Mira privet"}) == "Mira privet"
# несколько ключей без m_Script — без совпадения, исходник цел
assert patch_textasset("Zorblax original",
                       {"other": "Mira privet",
                        "another": "Quen privet"}) == "Zorblax original"
# MonoBehaviour roundtrip: harvest -> patch -> проверка значения
tree = {"m_text": "Mira lights the lantern",
        "Choices": [{"text": "Follow the moths"}],
        "m_Name": "Zorblax"}
pairs = harvest_monobehaviour(tree)
assert ("m_text", "Mira lights the lantern") in pairs, pairs
assert any(p[0] == "Choices[0].text" and p[1] == "Follow the moths"
           for p in pairs), pairs
patched = patch_monobehaviour(tree, [("m_text", "Mira zazhigayet"),
                                     ("Choices[0].text", "Sleduy")])
assert patched["m_text"] == "Mira zazhigayet", patched
assert patched["Choices"][0]["text"] == "Sleduy", patched
assert tree["m_text"] == "Mira lights the lantern"  # исходник не мутирует
# несуществующий путь молча пропускается
patched2 = patch_monobehaviour(tree, {"Nope.missing": "X"})
assert patched2 == tree and patched2 is not tree
print("   OK")

print("7) allow/deny полей MonoBehaviour (подстрока-хинт, SKIP, PPtr)...")
allow_tree = {
    "m_text": "Zorblax hums softly",
    "dialogLine": "Quen asks about the tide",
    "custom_title": "Bramblestone chronicle",
    "Options": ["First moth call", "Second moth call"],
}
got = dict(harvest_monobehaviour(allow_tree))
assert got.get("m_text") == "Zorblax hums softly", got
assert got.get("dialogLine") == "Quen asks about the tide", got
assert got.get("custom_title") == "Bramblestone chronicle", got
assert got.get("Options[0]") == "First moth call", got
assert got.get("Options[1]") == "Second moth call", got
deny_tree = {
    "m_Name": "Zorblax",  # служебное
    "m_Script": "Zorblax script ref",  # служебное
    "m_GameObject": {"m_FileID": 1},
    "plainField": "Zorblax visible but no hint",  # нет хинта в имени
    "m_text": "12345",  # без букв
    "dialog": "x",  # короче 2 символов
    "message": b"\xff\xfe",  # не-utf8
    "choice": {"m_FileID": 0, "m_PathID": 33},  # PPtr-ссылка
    "RawData": ["Zorblax hidden list"],  # база списка без хинта
}
assert harvest_monobehaviour(deny_tree) == [], \
    harvest_monobehaviour(deny_tree)
# глубина >3 не сканируется
deep = {"l1": {"l2": {"l3": {"l4": {"m_text": "Zorblax deep echo"}}}}}
assert harvest_monobehaviour(deep) == [], harvest_monobehaviour(deep)
# глубина ровно 3 — ещё видно
ok3 = {"l1": {"l2": {"m_text": "Zorblax near echo"}}}
assert harvest_monobehaviour(ok3) == [("l1.l2.m_text", "Zorblax near echo")]
print("   OK")


class _FakeType:
    def __init__(self, name: str):
        self.name = name


class _FakeObj:
    def __init__(self, pid: int, tname: str, tree: dict):
        self.path_id = pid
        self.type = _FakeType(tname)
        self._tree = dict(tree)
        self.patched = None

    def parse_as_dict(self, check_read: bool = True):
        return dict(self._tree)

    def patch(self, new_tree: dict):
        self.patched = dict(new_tree)
        self._tree = dict(new_tree)


class _FakeAsset:
    def __init__(self, objs: list):
        self.objects = {i: o for i, o in enumerate(objs)}
        self.saved: bytes | None = None

    def save(self) -> bytes:
        self.saved = b"FAKE-UNITY:" + repr(
            sorted((o.path_id, o._tree) for o in self.objects.values())
        ).encode("utf-8", "ignore")
        return self.saved


class _FakeEnv:
    def __init__(self, asset: _FakeAsset):
        self.files = {"main": asset}
        self.asset = asset


def _install_fake_unitypy(env: _FakeEnv):
    """Подмена UnityPy.load + _setup_typetree; возвращает restore()."""
    orig_load_holder: dict = {}
    orig_setup = parser._setup_typetree
    orig_import = parser._try_import_unitypy

    class _FakeUnityPy:
        @staticmethod
        def load(_path: str):
            return env

    def _fake_import():
        return _FakeUnityPy

    parser._try_import_unitypy = _fake_import  # type: ignore[method-assign]
    parser._setup_typetree = lambda _e, _g: False  # type: ignore[method-assign]

    def _restore():
        parser._try_import_unitypy = orig_import  # type: ignore[method-assign]
        parser._setup_typetree = orig_setup  # type: ignore[method-assign]

    orig_load_holder["restore"] = _restore
    return _restore


def _write_big_asset(td: str, rel: str) -> str:
    """Пустышка >=128 байт, чтобы extract/apply не скипали как синтетику."""
    abs_p = os.path.join(td, *rel.split("/"))
    os.makedirs(os.path.dirname(abs_p), exist_ok=True)
    with open(abs_p, "wb") as f:
        f.write(b"FAKE" * 64)  # 256 байт
    return abs_p


print("8) extract: дедуп по (file, json_path), формат asset://...")
with tempfile.TemporaryDirectory() as td:
    rel = "MyGame_Data/sharedassets9.assets"
    _write_big_asset(td, rel)
    dup_tree = {"m_Script": "Zorblax dedup probe chant",
                "m_Name": "FableStone"}
    asset = _FakeAsset([_FakeObj(777, "TextAsset", dup_tree),
                        _FakeObj(777, "TextAsset", dup_tree)])
    restore = _install_fake_unitypy(_FakeEnv(asset))
    try:
        entries = parser.extract(td)
    finally:
        restore()
    assert len(entries) == 1, [ (e.file, e.json_path, e.original)
                                for e in entries]
    e = entries[0]
    assert e.file == rel, e.file
    assert e.json_path == "asset://sharedassets9.assets/777/m_Script", \
        e.json_path
    assert e.original == "Zorblax dedup probe chant", e.original
    assert e.context == "TextAsset:FableStone", e.context
    # два разных pid — два разных json_path, дедупа нет
with tempfile.TemporaryDirectory() as td:
    rel = "MyGame_Data/sharedassets9.assets"
    _write_big_asset(td, rel)
    asset = _FakeAsset([_FakeObj(101, "TextAsset",
                                 {"m_Script": "Zorblax first chant",
                                  "m_Name": "FableStone"}),
                        _FakeObj(102, "TextAsset",
                                 {"m_Script": "Mira second chant",
                                  "m_Name": "FableStone"})])
    restore = _install_fake_unitypy(_FakeEnv(asset))
    try:
        entries = parser.extract(td)
    finally:
        restore()
    assert len(entries) == 2, [(e.json_path, e.original) for e in entries]
    assert entries[0].json_path.endswith("/101/m_Script")
    assert entries[1].json_path.endswith("/102/m_Script")
print("   OK")

print("9) apply: пропуск skip/пустых, запись валидной (UnityPy-стаб)...")
with tempfile.TemporaryDirectory() as td:
    rel = "MyGame_Data/sharedassets9.assets"
    _write_big_asset(td, rel)
    base = "sharedassets9.assets"
    asset = _FakeAsset([_FakeObj(101, "TextAsset",
                                 {"m_Script": "Zorblax greets traveler",
                                  "m_Name": "FableStone"})])
    restore = _install_fake_unitypy(_FakeEnv(asset))
    try:
        valid = TranslationEntry(
            id=1, file=rel, json_path=f"asset://{base}/101/m_Script",
            context="TextAsset:FableStone",
            original="Zorblax greets traveler",
            translation="Zorblax privetstvuet", status="new")
        skipped_entry = TranslationEntry(
            id=2, file=rel, json_path=f"asset://{base}/101/m_Script",
            context="TextAsset:FableStone",
            original="Zorblax greets traveler",
            translation="Ne nado", status="skip")
        empty_entry = TranslationEntry(
            id=3, file=rel, json_path=f"asset://{base}/101/m_Script",
            context="TextAsset:FableStone",
            original="Zorblax greets traveler",
            translation="   ", status="new")
        stats = parser.apply(td, [valid, skipped_entry, empty_entry],
                             target_lang="ru")
    finally:
        restore()
    assert stats.get("files") == 1, stats
    assert stats.get("strings") == 1, stats
    # объект реально пропатчен валидным переводом
    assert asset.objects[0]._tree.get("m_Script") == \
        "Zorblax privetstvuet", asset.objects[0]._tree
    assert asset.saved is not None  # save() вызван, verify прошёл
    assert stats.get("verified") == 1, stats
print("   OK")

print("10) no-unitypy ветка; wiring модуля (target_lang, font_patch)...")
with tempfile.TemporaryDirectory() as td:
    orig = parser._try_import_unitypy
    parser._try_import_unitypy = lambda: None  # type: ignore[method-assign]
    try:
        assert parser.extract(td) == []
        noup = parser.apply(td, [TranslationEntry(
            id=1, file="MyGame_Data/sharedassets9.assets",
            json_path="asset://sharedassets9.assets/101/m_Script",
            context="TextAsset:FableStone", original="Zorblax probe",
            translation="Zorblax perevod", status="new")])
        assert noup == {"files": 0, "strings": 0, "skipped": "no-unitypy"}, \
            noup
        # пустой вход без UnityPy — та же честная ветка
        assert parser.apply(td, []) == \
            {"files": 0, "strings": 0, "skipped": "no-unitypy"}
    finally:
        parser._try_import_unitypy = orig  # type: ignore[method-assign]
# wiring UnityModule -> parser (target_lang из проекта)
with tempfile.TemporaryDirectory() as td:
    mod = UnityModule(td)
    assert mod.features == {"file-translation", "font-patch"}
    assert mod.font_patch(td) == {"patched": False, "reason": "todo"}
    captured: dict = {}
    orig_apply = parser.apply
    try:
        def _spy(game_dir: str, entries: list, **kw):
            captured.update(kw)
            return {"files": 0, "spy": True}
        parser.apply = _spy  # type: ignore[method-assign]
        mod.apply(td, [], target_lang="uk")
        assert captured.get("target_lang") == "uk", captured
        mod.apply(td, [])
        assert captured.get("target_lang") == "ru", captured
        orig_extract = parser.extract
        try:
            parser.extract = lambda _g, stats=None: ["SENTINEL"]  # type: ignore[method-assign]
            assert mod.extract(td) == ["SENTINEL"]
        finally:
            parser.extract = orig_extract  # type: ignore[method-assign]
    finally:
        parser.apply = orig_apply  # type: ignore[method-assign]
print("   OK")

print("11) extract(stats): диагностика причин нуля...")
with tempfile.TemporaryDirectory() as td:
    make_full(td)
    stats: dict = {}
    entries = parser.extract(td, stats)
    assert isinstance(entries, list)
    for key in ("candidates", "checked", "loaded", "load_failed",
                "objects", "text_objects", "parse_fail", "parse_err",
                "entries"):
        assert key in stats, stats
    assert stats["entries"] == len(entries), stats
    assert stats["candidates"] >= 0 and stats["loaded"] >= 0
print("   OK")

print("12) JSON-конфиги режем, диалоги в JSON и текст — нет...")
assert parser._is_json_config('{"TestSuite":"","Date":0}') is True
assert parser._is_json_config('{"clothType":1,"sourceRenderers":[]}') is True
assert parser._is_json_config('{"MeasurementCount":-1}') is True
assert parser._is_json_config('["a","b",1]') is True
assert parser._is_json_config(
    '{"text": "Zorblax the brave wandered into Bramblestone"}') is False
assert parser._is_json_config("Zorblax the brave wandered on") is False
assert parser._is_json_config("{broken") is False
assert harvest_textasset("t", '{"TestSuite":"","Date":0}') == []
assert harvest_textasset(
    "d", '{"k": "Zorblax the brave wandered into Bramblestone"}') != []
assert harvest_textasset("p", "Zorblax the brave wandered on") != []
print("   OK")

print()
print("ВСЕ ТЕСТЫ UNITY ПРОШЛИ")

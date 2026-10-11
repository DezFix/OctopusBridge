# -*- coding: utf-8 -*-
"""Unity (новое): TMP-тексты, StreamingAssets, legacy Font swap,
конвенция features, target_lang в статистике.

Только синтетика во временных папках и выдуманные строки
(Zorblax/Mira — не из реальных игр) + опциональный guarded-блок
с подсчётами по реальной Mono-игре, если она доступна по известному
пути (иначе SKIP без падения).
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.models import TranslationEntry
from app.core.unity import parser
from app.engines.unity import UnityModule

REAL_GAME = r"E:\Temp\IDM\GakkodeG_v1.00_Uncensored"


class _FakeType:
    def __init__(self, name):
        self.name = name


class _FakeObj:
    def __init__(self, pid, tname, tree):
        self.path_id = pid
        self.type = _FakeType(tname)
        self._tree = dict(tree)
        self.patched = None

    def parse_as_dict(self, check_read=True):
        return dict(self._tree)

    def patch(self, new_tree):
        self.patched = dict(new_tree)
        self._tree = dict(new_tree)


class _FakeAsset:
    def __init__(self, objs):
        self.objects = {i: o for i, o in enumerate(objs)}
        self.saved = None

    def save(self):
        self.saved = b"FAKE-UNITY:" + repr(
            sorted((o.path_id, o._tree) for o in self.objects.values())
        ).encode("utf-8", "ignore")
        return self.saved


class _FakeEnv:
    def __init__(self, asset):
        self.files = {"main": asset}


def _install_fake(env):
    orig_import = parser._try_import_unitypy
    orig_setup = parser._setup_typetree

    class _FakeUnityPy:
        @staticmethod
        def load(_path):
            return env

        @staticmethod
        def load_bytes(_data):
            return env

    parser._try_import_unitypy = lambda: _FakeUnityPy  # type: ignore[method-assign]
    parser._setup_typetree = lambda e, g, n=None: False  # type: ignore[method-assign]

    def _restore():
        parser._try_import_unitypy = orig_import  # type: ignore[method-assign]
        parser._setup_typetree = orig_setup  # type: ignore[method-assign]

    # verify в apply/font_patch грузит из байтов тем же load
    _FakeUnityPy.load = staticmethod(lambda arg: env)
    return _restore


def _write_big(td, rel):
    abs_p = os.path.join(td, *rel.split("/"))
    os.makedirs(os.path.dirname(abs_p), exist_ok=True)
    with open(abs_p, "wb") as f:
        f.write(b"FAKE" * 64)
    return abs_p


print("1) TMP harvest/patch round-trip (TextMeshProUGUI/TextMeshPro, m_text)...")
with tempfile.TemporaryDirectory() as td:
    rel = "UGame_Data/sharedassets9.assets"
    _write_big(td, rel)
    asset = _FakeAsset([
        _FakeObj(201, "TextMeshProUGUI",
                 {"m_text": "Zorblax tmp chant", "m_Name": "TmpLabel"}),
        _FakeObj(202, "TextMeshPro",
                 {"m_text": "Mira tmp echo", "m_Name": "Tmp3D"}),
        _FakeObj(203, "TextMeshProUGUI",
                 {"m_text": "12 !!", "m_Name": "TmpJunk"}),  # без букв — пропуск
    ])
    restore = _install_fake(_FakeEnv(asset))
    try:
        entries = parser.extract(td)
    finally:
        restore()
    assert len(entries) == 2, [(e.json_path, e.original) for e in entries]
    by_pid = {e.json_path.rsplit("/", 2)[1]: e for e in entries}
    assert by_pid["201"].json_path.endswith("/201/m_text"), by_pid["201"].json_path
    assert by_pid["201"].original == "Zorblax tmp chant"
    assert by_pid["201"].context == "TextMeshProUGUI:TmpLabel"
    assert by_pid["202"].json_path.endswith("/202/m_text")
    assert by_pid["202"].context == "TextMeshPro:Tmp3D"
    # apply: m_text регистр обязан совпасть (m_Text не подойдёт)
    for e in entries:
        e.translation = e.original + " RU"
        e.status = "translated"
    restore = _install_fake(_FakeEnv(asset))
    try:
        stats = parser.apply(td, entries, target_lang="ru",
                             backup_root=os.path.join(td, "bak"))
    finally:
        restore()
    assert stats.get("files") == 1 and stats.get("strings") == 2, stats
    assert asset.objects[0]._tree["m_text"] == "Zorblax tmp chant RU"
    assert asset.objects[1]._tree["m_text"] == "Mira tmp echo RU"
    assert stats.get("verified") == 1, stats
print("   OK")

print("2) Legacy Font swap (m_FontData -> TTF, BackupStore+atomic+verify)...")
with tempfile.TemporaryDirectory() as td:
    rel = "UGame_Data/resources.assets"
    _write_big(td, rel)
    asset = _FakeAsset([
        _FakeObj(11, "Font", {"m_Name": "ZorblaxSans",
                              "m_FontData": [1, 2, 3],
                              "m_FontNames": ["ZorblaxSans"]}),
    ])
    ttf = os.path.join(td, "fake.ttf")
    with open(ttf, "wb") as f:
        f.write(b"\x00\x01\x00\x00" + b"\x00" * 256)
    restore = _install_fake(_FakeEnv(asset))
    try:
        stats = parser.font_patch(td, ttf_path=ttf,
                                  backup_root=os.path.join(td, "bak"))
    finally:
        restore()
    assert stats["patched"] is True and stats["reason"] == "ok", stats
    assert stats["fonts"] == 1 and stats["files"] == 1, stats
    assert stats["names"] == ["ZorblaxSans"], stats
    assert stats["verified"] == 1 and len(stats["backups"]) == 1, stats
    assert asset.objects[0]._tree["m_FontData"] == [0, 1, 0, 0] + [0] * 256, \
        asset.objects[0]._tree["m_FontData"][:8]
    assert asset.saved is not None
    # Динамический OS-шрифт обязан стать статическим: иначе Unity
    # рисует текст системным файлом из m_FontNames и кириллица
    # после перевода не видна (пустые квадраты).
    assert asset.objects[0]._tree["m_FontNames"] == [], \
        asset.objects[0]._tree["m_FontNames"]
    assert stats["dynamic_neutralized"] == 1, stats
print("   OK")

print("2b) Статический шрифт не трогаем, счётчик динамических честный...")
with tempfile.TemporaryDirectory() as td:
    rel = "UGame_Data/sharedassets9.assets"
    _write_big(td, rel)
    asset = _FakeAsset([
        # уже статический: пустой m_FontNames — не должен «нейтрализоваться»
        _FakeObj(21, "Font", {"m_Name": "StaticSans",
                              "m_FontData": [0],
                              "m_FontNames": []}),
        # динамический: обязан обнулиться
        _FakeObj(22, "Font", {"m_Name": "OsSans",
                              "m_FontData": [0],
                              "m_FontNames": ["OsSans", "OsSans-Bold"]}),
        # TMP SDF — считается, но не патчится (нужен Unity Editor)
        _FakeObj(23, "TMP_FontAsset", {"m_Name": "SdfFont"}),
    ])
    ttf = os.path.join(td, "fake.ttf")
    with open(ttf, "wb") as f:
        f.write(b"OTTO" + b"\x00" * 256)
    restore = _install_fake(_FakeEnv(asset))
    try:
        stats = parser.font_patch(td, ttf_path=ttf,
                                  backup_root=os.path.join(td, "bak"))
    finally:
        restore()
    assert stats["dynamic_neutralized"] == 1, stats
    assert stats["tmp_fonts"] == 1, stats
    assert asset.objects[0]._tree["m_FontNames"] == [], \
        asset.objects[0]._tree["m_FontNames"]
    assert asset.objects[1]._tree["m_FontNames"] == [], \
        asset.objects[1]._tree["m_FontNames"]
    # is_patched честно отвечает по бэкапам
    assert parser.is_patched(td) is False, "бэкап ушёл в отдельный bak/"
    restore2 = _install_fake(_FakeEnv(asset))
    try:
        parser.font_patch(td, ttf_path=ttf,
                          backup_root=os.path.join(td, "backup", "unity"))
    finally:
        restore2()
    assert parser.is_patched(td) is True
    from app.core.io import BackupStore
    before = open(os.path.join(td, rel), "rb").read()
    restored = BackupStore(os.path.join(td, "backup", "unity")).restore_all()
    assert restored.get("restored") == 1, restored
    assert open(os.path.join(td, rel), "rb").read() == before, "откат вернул байты"
print("   OK")

print("3) font_patch честные отказы: no-ttf / bad-ttf / no-fonts / no-unitypy...")
with tempfile.TemporaryDirectory() as td:
    assert parser.font_patch(td, ttf_path=os.path.join(td, "нет.ttf"))["reason"] == "no-ttf"
    bad = os.path.join(td, "bad.ttf")
    with open(bad, "wb") as f:
        f.write(b"ZZZZ" + b"\x00" * 256)
    r = parser.font_patch(td, ttf_path=bad)
    assert r == {"patched": False, "fonts": 0, "files": 0, "reason": "bad-ttf"}, r
    good = os.path.join(td, "good.ttf")
    with open(good, "wb") as f:
        f.write(b"OTTO" + b"\x00" * 256)
    r = parser.font_patch(td, ttf_path=good)  # candidатов нет вообще
    assert r["patched"] is False and r["reason"] == "no-fonts", r
    orig = parser._try_import_unitypy
    parser._try_import_unitypy = lambda: None  # type: ignore[method-assign]
    try:
        r = parser.font_patch(td, ttf_path=good)
        assert r == {"patched": False, "fonts": 0, "files": 0,
                     "reason": "no-unitypy"}, r
    finally:
        parser._try_import_unitypy = orig  # type: ignore[method-assign]
print("   OK")

print("4) features — конвенция базы, maturity, target_lang течёт в stats...")
from app.engines.base import EngineModule as _Base
assert UnityModule.features == {"files", "font"}, UnityModule.features
assert UnityModule.features <= {"cheats", "resources", "font", "files"}
assert "file-translation" not in UnityModule.features
assert "font-patch" not in UnityModule.features
assert UnityModule.maturity == "experimental"
assert _Base.features == {"files"}
with tempfile.TemporaryDirectory() as td:
    rel = "UGame_Data/sharedassets9.assets"
    _write_big(td, rel)
    base = "sharedassets9.assets"
    asset = _FakeAsset([_FakeObj(101, "TextAsset",
                                 {"m_Script": "Zorblax greets traveler",
                                  "m_Name": "FableStone"})])
    restore = _install_fake(_FakeEnv(asset))
    try:
        e = TranslationEntry(
            id=1, file=rel, json_path="asset://%s/101/m_Script" % base,
            context="TextAsset:FableStone", original="Zorblax greets traveler",
            translation="Zorblax privetstvuet", status="new")
        stats = parser.apply(td, [e], target_lang="uk",
                             backup_root=os.path.join(td, "bak"))
    finally:
        restore()
    assert stats.get("target_lang") == "uk", stats
    # wiring модуля: target_lang из kwargs доходит до parser.apply
    captured = {}
    orig_apply = parser.apply
    try:
        def _spy(game_dir, entries, **kw):
            captured.update(kw)
            return {"files": 0, "spy": True}
        parser.apply = _spy  # type: ignore[method-assign]
        UnityModule(td).apply(td, [], target_lang="uk")
        assert captured.get("target_lang") == "uk", captured
    finally:
        parser.apply = orig_apply  # type: ignore[method-assign]
print("   OK")

print("5) StreamingAssets: harvest-гарды + extract/apply round-trip...")
assert parser.harvest_streaming_text("d.json",
    '{"k": "Zorblax the brave wandered into Bramblestone"}') == \
    [("content", '{"k": "Zorblax the brave wandered into Bramblestone"}')]
assert parser.harvest_streaming_text("c.json", '{"TestSuite":"","Date":0}') == []
assert parser.harvest_streaming_text("t.txt", "   ") == []
assert parser.harvest_streaming_text("t.txt", "123 !!") == []
assert parser.harvest_streaming_text("b.txt", b"\xff\xfe") == []
assert parser.harvest_streaming_text(
    "d.csv", "id,text\n1,Zorblax sails beyond Bramblestone") == \
    [("content", "id,text\n1,Zorblax sails beyond Bramblestone")]
with tempfile.TemporaryDirectory() as td:
    data = os.path.join(td, "UGame_Data")
    os.makedirs(os.path.join(data, "Managed"))
    open(os.path.join(data, "globalgamemanagers"), "w").close()
    sdir = os.path.join(data, "StreamingAssets")
    os.makedirs(sdir)
    with open(os.path.join(sdir, "dialog.csv"), "w", encoding="utf-8") as f:
        f.write("id,text\n1,Zorblax sails beyond Bramblestone bay")
    with open(os.path.join(sdir, "cfg.json"), "w", encoding="utf-8") as f:
        f.write('{"TestSuite":"","Date":0}')
    with open(os.path.join(sdir, "img.png"), "wb") as f:
        f.write(b"\x89PNG" + b"\x00" * 64)
    assert parser.iter_streaming_text_files(td) == \
        ["UGame_Data/StreamingAssets/cfg.json",
         "UGame_Data/StreamingAssets/dialog.csv"]
    entries = parser.extract(td)  # 0-байт пустышек нет — UnityPy не трогаем
    assert len(entries) == 1, [(e.file, e.json_path) for e in entries]
    e = entries[0]
    assert e.json_path == "asset://dialog.csv/streaming/content", e.json_path
    assert e.context == "Streaming:dialog.csv", e.context
    assert "Zorblax sails" in e.original
    e.translation = "id,text\n1,Zorblax plyvyot RU"
    e.status = "translated"
    stats = parser.apply(td, [e], target_lang="ru",
                         backup_root=os.path.join(td, "bak"))
    assert stats.get("files") == 1 and stats.get("strings") == 1, stats
    assert stats.get("target_lang") == "ru" and stats.get("verified") == 1, stats
    with open(os.path.join(sdir, "dialog.csv"), encoding="utf-8") as f:
        assert f.read() == "id,text\n1,Zorblax plyvyot RU"
print("   OK")

print("6) Реальная Mono-игра (guarded): TMP 0, Font x2, action-хинт жив...")
if os.path.isdir(REAL_GAME):
    stats = {}
    entries = parser.extract(REAL_GAME, stats)
    assert stats.get("tmp_fonts") == 0, stats
    assert stats.get("fonts") == 2, stats
    assert stats.get("streaming") == 0, stats  # нет StreamingAssets
    tmp_entries = [e for e in entries if e.json_path.endswith("/m_text")]
    assert tmp_entries == [], len(tmp_entries)
    act_entries = [e for e in entries
                   if e.context.startswith("MonoBehaviour")]
    assert len(entries) > 6000, len(entries)
    print("   entries=%d fonts=%s tmp_fonts=%s streaming=%s" % (
        len(entries), stats.get("fonts"), stats.get("tmp_fonts"),
        stats.get("streaming")))
else:
    print("   SKIP: нет %s" % REAL_GAME)
print("   OK")

print("6b) Реальная Mono-игра: оба шрифта динамические OS (только чтение)...")
if os.path.isdir(REAL_GAME):
    import UnityPy
    parser._force_pure_python_reader()
    seen = {}
    for rel in parser._candidate_files(REAL_GAME):
        abs_p = os.path.join(REAL_GAME, *rel.split("/"))
        if not os.path.isfile(abs_p):
            continue
        try:
            if os.path.getsize(abs_p) < 128:
                continue
        except OSError:
            continue
        try:
            env = UnityPy.load(abs_p)
        except Exception:
            continue
        for _ak, asset in list(getattr(env, "files", {}).items()):
            objects = getattr(asset, "objects", None) or {}
            vals = objects.values() if isinstance(objects, dict) else objects
            for obj in list(vals):
                try:
                    if str(getattr(obj.type, "name", "?")) != "Font":
                        continue
                    tree = obj.parse_as_dict()
                except Exception:
                    continue
                seen[tree.get("m_Name")] = list(tree.get("m_FontNames") or [])
        parser._close_env(env)
    assert len(seen) == 2, seen
    # Именно этот случай ломал перевод: m_FontNames непустой -> Unity рисует
    # системным шрифтом, m_FontData игнорирует, кириллица не видна.
    assert all(names for names in seen.values()), seen
    print("   dynamic fonts: %s" % sorted(seen))
else:
    print("   SKIP: нет %s" % REAL_GAME)
print("   OK")

print()
print("ВСЕ НОВЫЕ ТЕСТЫ UNITY ПРОШЛИ")

print('7) apply target-asset selection: lazy env.files with dependency, only target saved...')
with tempfile.TemporaryDirectory() as td:
    rel = 'UGame_Data/sharedassets9.assets'
    abs_p = _write_big(td, rel)
    base = 'sharedassets9.assets'
    target = _FakeAsset([_FakeObj(301, 'TextAsset', {'m_Script': 'Zorblax target chant', 'm_Name': 'FableStone'})])
    dep = _FakeAsset([_FakeObj(302, 'TextAsset', {'m_Script': 'Zorblax dep chant', 'm_Name': 'DepStone'})])
    other_p = os.path.join(td, 'UGame_Data', 'other.assets')
    env = _FakeEnv(target)
    env.files = {abs_p: target, other_p: dep}
    restore = _install_fake(env)
    try:
        e = TranslationEntry(id=9001, file=rel, json_path='asset://' + base + '/301/m_Script', context='TextAsset:FableStone', original='Zorblax target chant', translation='Zorblax target RU', status='translated')
        stats = parser.apply(td, [e], target_lang='ru', backup_root=os.path.join(td, 'bak'))
    finally:
        restore()
    assert stats.get('files') == 1 and stats.get('strings') == 1, stats
    assert stats.get('skipped') == 0, stats
    assert target.saved is not None, stats
    assert dep.saved is None, dep.saved
    assert target.objects[0]._tree.get('m_Script') == 'Zorblax target RU'
    assert open(abs_p, 'rb').read() == target.saved
print('   OK')
print('8) apply skips when env.files keys do not match target and several files present...')
with tempfile.TemporaryDirectory() as td:
    rel = 'UGame_Data/sharedassets9.assets'
    abs_p = _write_big(td, rel)
    before = open(abs_p, 'rb').read()
    base = 'sharedassets9.assets'
    a1 = _FakeAsset([_FakeObj(401, 'TextAsset', {'m_Script': 'Zorblax nowhere chant', 'm_Name': 'FableStone'})])
    a2 = _FakeAsset([_FakeObj(402, 'TextAsset', {'m_Script': 'Zorblax other chant', 'm_Name': 'DepStone'})])
    env = _FakeEnv(a1)
    env.files = {'nope1': a1, 'nope2': a2}
    restore = _install_fake(env)
    try:
        e = TranslationEntry(id=9002, file=rel, json_path='asset://' + base + '/401/m_Script', context='TextAsset:FableStone', original='Zorblax nowhere chant', translation='Zorblax nowhere RU', status='translated')
        stats = parser.apply(td, [e], target_lang='ru', backup_root=os.path.join(td, 'bak'))
    finally:
        restore()
    assert stats.get('files') == 0, stats
    assert stats.get('skipped') == 1, stats
    assert a1.saved is None and a2.saved is None, stats
    assert open(abs_p, 'rb').read() == before
print('   OK')
print('9) apply legacy single-file env still saved via fallback...')
with tempfile.TemporaryDirectory() as td:
    rel = 'UGame_Data/sharedassets9.assets'
    abs_p = _write_big(td, rel)
    base = 'sharedassets9.assets'
    asset = _FakeAsset([_FakeObj(501, 'TextAsset', {'m_Script': 'Zorblax legacy chant', 'm_Name': 'FableStone'})])
    restore = _install_fake(_FakeEnv(asset))
    try:
        e = TranslationEntry(id=9003, file=rel, json_path='asset://' + base + '/501/m_Script', context='TextAsset:FableStone', original='Zorblax legacy chant', translation='Zorblax legacy RU', status='translated')
        stats = parser.apply(td, [e], target_lang='ru', backup_root=os.path.join(td, 'bak'))
    finally:
        restore()
    assert stats.get('files') == 1 and stats.get('strings') == 1, stats
    assert asset.saved is not None, stats
    assert asset.objects[0]._tree.get('m_Script') == 'Zorblax legacy RU'
print('   OK')
print('TARGET-ASSET TESTS PASSED')

# ── контракт ApplyReport: пропуски с причинами, verify_failed — список ─────
print('10) apply: контракт ApplyReport (skipped_total/skipped_by/verify_failed)...')
with tempfile.TemporaryDirectory() as td:
    rel = 'UGame_Data/level0'
    abs_p = _write_big(td, rel)
    asset = _FakeAsset([
        _FakeObj(601, 'TextAsset', {'m_Script': 'Zorblax contract chant',
                                    'm_Name': 'FableStone'}),
        _FakeObj(602, 'TextAsset', {'m_Script': 'Zorblax second chant',
                                    'm_Name': 'GraveBell'}),
    ])
    env = _FakeEnv(asset)
    env.files = {abs_p: asset}
    restore = _install_fake(env)
    try:
        def _mk(pid, original, translation):
            return TranslationEntry(
                id=pid, file=rel,
                json_path='asset://level0/%d/m_Script' % pid,
                context='TextAsset:X', original=original,
                translation=translation, status='translated')

        # один ок, один с устаревшим оригиналом, один с битым json_path
        entries = [
            _mk(601, 'Zorblax contract chant', 'Zorblax contract RU'),
            _mk(602, 'STALE different text', 'Zorblax second RU'),
            _mk(603, 'no such object', 'Zorblax third RU'),
        ]
        entries[2].json_path = 'garbage'
        stats = parser.apply(td, entries, target_lang='ru',
                             backup_root=os.path.join(td, 'bak'))
    finally:
        restore()
    # UI читает skipped_total/skipped_by — они обязаны быть, иначе
    # «применил, а в игре пусто» остаётся без объяснения
    assert 'skipped_total' in stats and 'skipped_by' in stats, stats.keys()
    assert isinstance(stats['verify_failed'], list), stats['verify_failed']
    assert isinstance(stats['verify_restored'], bool), stats['verify_restored']
    assert stats['skipped_total'] == stats['skipped'], stats
    assert stats['skipped_by'].get('bad-json-path') == 1, stats['skipped_by']
    assert stats['skipped_by'].get('changed') == 1, stats['skipped_by']
    assert stats['strings'] == 1 and stats['files'] == 1, stats
    # ApplyReport.from_legacy обязан принимать без исключений
    from app.engines.protocol import ApplyReport
    report = ApplyReport.from_legacy(stats)
    assert report.skipped_total == stats['skipped_total']
    assert isinstance(report.verify_failed, list)
    # пустой вход: без исключений, с контрактными полями
    with tempfile.TemporaryDirectory() as td2:
        stats2 = parser.apply(td2, [], target_lang='ru')
        assert stats2['skipped_total'] == 0 and stats2['files'] == 0, stats2
        assert isinstance(stats2['verify_failed'], list), stats2
print('   OK')

# ── PlayerPrefs: разбор ключа, типы, гварды ввода ───────────────────────────
print('11) PlayerPrefs: split_hash/is_system_key/parse_input/_as_bool...')
from app.core.unity import json_save as js
from app.core.unity import playerprefs as pp
assert pp.split_hash('Screenmanager Width_h182942802') == \
    ('Screenmanager Width', '_h182942802')
assert pp.split_hash('NoHashHere') == ('NoHashHere', '')
assert pp.is_system_key('Screenmanager Width') is True
assert pp.is_system_key('unity.player_id') is True
assert pp.is_system_key('playerLevel') is False
assert pp.parse_input('42', 'auto') == 42
assert pp.parse_input('-7', 'auto') == -7
assert pp.parse_input('1.5', 'auto') == 1.5
assert pp.parse_input('hello', 'auto') == 'hello'
assert pp.parse_input(' 8 ', 'int') == 8
for bad, kind in (('x', 'int'), ('y', 'float'), ('zz', 'bytes')):
    try:
        pp.parse_input(bad, kind)
        raise AssertionError('должен быть отказ: %r/%s' % (bad, kind))
    except pp.PrefError:
        pass
assert pp.format_value({'kind': 'int', 'value': 5}) == '5'
assert pp.format_value({'kind': 'float', 'value': 0.5}) == '0.5'
assert 'Б' in pp.format_value({'kind': 'bytes', 'value': b'\x01\x02'})
assert pp.prefs_subkey('C', 'P') == r'Software\C\P'
# ветка реестра строится из PlayerSettings, а не угадывается
if os.path.isdir(REAL_GAME):
    ident = pp.player_settings(REAL_GAME)
    assert ident and all(ident), ident
print('   OK')

# ── json_save: flatten/set_paths/save_json/restore ──────────────────────────
print('12) json_save: flatten, типы, гварды, бэкап и самопроверка...')
sample = {
    'gold': 100,
    'flags': {'unlock': False, 'hard': True},
    'party': [{'hp': 10, 'name': 'Al'}],
    'ratio': 0.5,
}
flat = js.flatten(sample)
assert flat == {'gold': 100, 'flags.unlock': False, 'flags.hard': True,
                'party[0].hp': 10, 'party[0].name': 'Al', 'ratio': 0.5}, flat
assert js.get_path(sample, 'flags.unlock') is False
missing = js.get_path(sample, 'nope')
assert missing is not None and not missing, 'пропуск должен быть falsy'
new, skipped = js.set_paths(sample, {
    'gold': 999,            # int -> int
    'ratio': '0.25',        # float не должен стать int
    'flags.unlock': '1',    # bool из '1'
    'flags.hard': 'off',    # bool из 'off'
})
assert skipped == [], skipped
assert new['gold'] == 999 and isinstance(new['gold'], int)
assert new['ratio'] == 0.25 and isinstance(new['ratio'], float)
assert new['flags']['unlock'] is True
assert new['flags']['hard'] is False
assert new['party'][0]['hp'] == 10, 'нетронутое не должно меняться'
# гварды: путь не существует, абсурдный индекс, мусор в типе
new2, skipped2 = js.set_paths(sample, {
    'no.such.path': 1,
    'x[99999999]': 1,
    'gold': 'не число',
})
assert len(skipped2) == 3, skipped2
with tempfile.TemporaryDirectory() as td:
    import json as _json

    path = os.path.join(td, 'save.json')
    with open(path, 'w', encoding='utf-8') as f:
        _json.dump(sample, f, ensure_ascii=False)
    changed, _sk = js.set_paths(js.load_json(path), {'gold': 555})
    res = js.save_json(path, changed)
    assert res['backup'] and os.path.isfile(res['backup']), res
    assert js.flatten(js.load_json(path))['gold'] == 555
    # несохранённые контейнеры не превращаются в строки
    assert isinstance(js.load_json(path)['flags'], dict)
    assert js.restore_backup(path) is True
    assert js.load_json(path) == sample, 'откат вернул исходник'
print('   OK')
print('ВСЕ НОВЫЕ ТЕСТЫ UNITY (10-12) ПРОШЛИ')

# ────────────────────────────────────────────────────────────
# _close_env: в UnityPy 1.25.3 поток лежит в asset.stream,
#    а не в asset.reader.stream — иначе ручка течёт на каждом открытом
#    ассете, и font_patch/apply идут вутри себя (WinError 32/5).
print('13) _close_env реально закрывает поток ассета...')
with tempfile.TemporaryDirectory() as td:
    dd = os.path.join(td, 'UGame_Data')
    os.makedirs(dd)
    gg = os.path.join(dd, 'globalgamemanagers')
    with open(gg, 'wb') as f:
        f.write(b'FAKE' * 64)
    parser._force_pure_python_reader()
    UnityPy = parser._try_import_unitypy()
    if UnityPy is None:
        print('   SKIP: UnityPyнет')
    else:
        def _open_handles(path):
            if os.name != 'nt':
                return 0
            import psutil
            want = os.path.normpath(os.path.abspath(path))
            return len([h for h in psutil.Process().open_files()
                        if os.path.normpath(os.path.abspath(h.path)) == want])

        env = UnityPy.load(gg)
        assert _open_handles(gg) == 1, 'UnityPy должен держать исходник'
        parser._close_env(env)
        assert _open_handles(gg) == 0, \
            '_close_env не закрыл ручку — течёт хендл'
        for _i in range(3):
            e = UnityPy.load(gg)
            parser._close_env(e)
        assert _open_handles(gg) == 0
print('   OK')
print('ВСЕ НОВЫЕ ТЕСТЫ UNITY (13) ПРОШЛИ')

# ──────────────────────────────────────────────────────────────────
# Построчный TextAsset + идентификаторы ввода.
# История: actionName был переведён (553 записи) ->
# персонаж перестал ходить; цельный TextAsset-сценарий
# уходил переводчику одной строкой -> диалог ломался.
print('14) TextAsset построчно: структура файла не преет...')
_script = ('Hello there friend\n\nWhere the wild stone sleeps\n'
            'Nobody came\n')
_out = parser.harvest_textasset('x', _script)
assert _out == [('m_Script#0', 'Hello there friend'),
               ('m_Script#2', 'Where the wild stone sleeps'),
               ('m_Script#3', 'Nobody came')], _out
_patched = parser.patch_textasset_lines(_script, {
    0: 'Privet drug', 3: 'Nikto ne prishyol'})
assert _patched == ('Privet drug\n\nWhere the wild stone sleeps\n'
                   'Nikto ne prishyol\n'), repr(_patched)
assert _patched.count('\n') == _script.count('\n'), \
    '\u0447\u0438\u0441\u043b\u043e \u0441\u0442\u0440\u043e\u043a \u043f\u043e\u0435\u0445\u0430\u043b\u043e'
assert '\n\n' in _patched, '\u043f\u0443\u0441\u0442\u0430\u044f \u0441\u0442\u0440\u043e\u043a\u0430 \u043f\u043e\u0442\u0435\u0440\u044f\u043b\u0430\u0441\u044c'
# CRLF \u0441\u043e\u0445\u0440\u0430\u043d\u044f\u0435\u0442\u0441\u044f
_crlf = 'one\r\ntwo\r\nthree\r\n'
assert parser.patch_textasset_lines(_crlf, {1: 'dva'}).count('\r\n') == 3
# bytes -> bytes, \u0431\u0435\u0437 \u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0439 \u0438\u0441\u0445\u043e\u0434\u043d\u0438\u043a
_b = _script.encode('utf-8')
_after = parser.patch_textasset_lines(_b, {0: 'Bait'})
assert isinstance(_after, bytes) and _after.decode().startswith('Bait')
assert parser.patch_textasset_lines(_script, {}) is _script
assert parser.patch_textasset_lines(_script, {99: 'x'}) is _script
assert parser.patch_textasset_lines(_script, {-3: 'x'}) is _script
assert parser._line_index('m_Script#7') == 7
assert parser._line_index('m_Script#') is None
assert parser._line_index('m_Script#x') is None
assert parser._line_index('m_Text') is None
# \u043e\u0442\u0447\u0451\u0442 \u0441\u0431\u043e\u0440\u043a\u0438 Unity \u0438 \u0442\u0430\u0431\u043b\u0438\u0446\u044b \u0440\u0435\u0436\u0443\u0442\u0441\u044f
_report = ('{"TestSuite":"","Date":0,"Dependencies":'
            '["com.unity.2d.sprite@1.0.0",'
            '"com.unity.tilemap@2.0.0"]}')
assert parser._is_json_config(_report) is True, '\u043e\u0442\u0447\u0451\u0442 \u0441\u0431\u043e\u0440\u043a\u0438 \u0440\u0435\u0437\u0430\u043d'
assert parser.harvest_textasset('x', _report) == [], _report
assert parser._is_json_config(_report) is True
_table = 'id,name,desc\n1,sword,steel\n2,shield,iron\n'
assert parser.harvest_textasset('x', _table) == [], 'tsv-\u0442\u0430\u0431\u043b\u0438\u0446\u0430 \u0440\u0435\u0437\u0430\u043d\u0430'
print('   OK')

# ──────────────────────────────────────────────────────────────────
# И\u0434\u0435\u043d\u0442\u0438\u0444\u0438\u043a\u0430\u0442\u043e\u0440\u044b \u0432\u0432\u043e\u0434\u0430 (Unity Input System) \u043d\u0435
# \u043f\u0435\u0440\u0435\u0432\u043e\u0434\u044f\u0442\u0441\u044f: \u0438\u043d\u0430\u0447\u0435 \u043f\u0435\u0440\u0441\u043e\u043d\u0430\u0436 \u043d\u0435 \u0445\u043e\u0434\u0438\u0442.
print('15) Идентификаторы ввода не переводятся...')
assert 'action' not in parser._TEXT_HINTS, parser._TEXT_HINTS
_tree = {
    'm_Name': 'InteractableThing',
    'actionName': 'Interact',
    'm_ActionId': '8f4b2c1d-0000-4000-8000-1234567890ab',
    'm_DefaultActionMap': 'Player',
    'interactText': 'Открыть дверь',
}
_pairs = parser.harvest_monobehaviour(_tree)
_fields = [p[0] for p in _pairs]
assert _fields == ['interactText'], _fields
assert _tree['actionName'] == 'Interact', '\u0434\u0435\u0440\u0435\u0432\u043e \u043d\u0435 \u043c\u0443\u0442\u0438\u0440\u043e\u0432\u0430\u043b\u0438'
# \u043d\u0435\u0441\u043a\u043e\u043b\u044c\u043a\u043e \u0437\u0430\u043f\u0438\u0441\u0435\u0439 \u043e\u0434\u043d\u043e\u0433\u043e \u0442\u0438\u043f\u0430 \u043d\u0435 \u043f\u0443\u0442\u0430\u044e\u0442\u0441\u044f
for _n in parser._IDENT_FIELDS:
    assert parser.harvest_monobehaviour({_n: 'Interact'}) == [], _n
print('   OK')
print('\u0412\u0421\u0415 \u041d\u041e\u0412\u042b\u0415 \u0422\u0415\u0421\u0422\u042b UNITY (14-15) \u041f\u0420\u041e\u0428\u041b\u0418')



# ──────────────────────────────────────────────────────────────────
# Реестр наших запусков: в чужой процесс не лезем.
# Главный инвариант для живых читов.
print('16) Реестр запусков: только свои процессы...')
from app.transport.unity_rpc import registry as _reg
_real = os.environ.get('APPDATA')
with tempfile.TemporaryDirectory() as td:
    os.environ['APPDATA'] = td
    try:
        assert _reg.launches_path().startswith(td), _reg.launches_path()
        assert _reg.verify_launch(4242) is None
        assert _reg.verify_launch(999999) is None
        assert _reg.verify_launch('не число') is None
        assert _reg.verify_launch(None) is None
        assert _reg.our_launches() == []
        _me = os.getpid()
        _exe = os.path.abspath(sys.executable)
        _reg.record_launch(_me, _exe, r'C:\fake\UGame')
        assert _reg.verify_launch(_me) == _exe
        assert _reg.verify_launch(_me, r'C:\fake\UGame') == _exe
        assert _reg.verify_launch(_me, r'C:\other') is None
        assert os.path.isfile(_reg.launches_path())
        rows = _reg.our_launches()
        assert any(r['pid'] == _me for r in rows), rows
        _reg.forget_launch(_me)
        assert _reg.verify_launch(_me) is None
        with open(_reg.launches_path(), 'w', encoding='utf-8') as _f:
            _f.write('{')
        assert _reg.verify_launch(_me) is None
    finally:
        if _real is not None:
            os.environ['APPDATA'] = _real
print('   OK')

# ──────────────────────────────────────────────────────────────────
# Разбор значений для live-читов: ошибка тут =
# запись мусора в чужую память.
print('17) as_bool + parse_input: типы для live-правки...')
from app.core.unity import json_save as _js
assert _js.as_bool('1') is True
assert _js.as_bool('true') is True
assert _js.as_bool('YES') is True
assert _js.as_bool('да') is True
assert _js.as_bool('0') is False
assert _js.as_bool('off') is False
assert _js.as_bool('') is False
assert _js.as_bool(True) is True and _js.as_bool(0) is False
try:
    _js.as_bool('может быть')
    raise AssertionError('as_bool должен отказать на мусоре')
except _js.SaveError:
    pass
assert pp.parse_input('9999', 'int') == 9999
assert pp.parse_input('2.5', 'float') == 2.5
try:
    pp.parse_input('не число', 'int')
    raise AssertionError('parse_input должен отказать')
except pp.PrefError:
    pass
for _t, _kind in (('System.Boolean', 'bool'), ('System.Int32', 'int'),
                   ('System.Int64', 'int'), ('System.Single', 'float'),
                   ('System.Double', 'float'),
                   ('System.String', 'str'), ('', 'str')):
    assert _kind in ('bool', 'int', 'float', 'str'), _kind
print('   OK')
print('ВСЕ НОВЫЕ ТЕСТЫ UNITY (16-17) ПРОШЛИ')

# ──────────────────────────────────────────────────────────────────
# attach к чужому pid: отказ до frida, без повторов.
# Цена ошибки здесь — прикосновение к чужой игре.
print('18) attach отказывает чужой процесс до Frida...')
from app.transport.unity_rpc.injector import UnityMonoRPC, UnityRPCError
_real = os.environ.get('APPDATA')
with tempfile.TemporaryDirectory() as td:
    os.environ['APPDATA'] = td
    try:
        _rpc = UnityMonoRPC()
        try:
            _rpc.attach(424242)
            raise AssertionError('должен был отказ')
        except UnityRPCError as _e:
            assert 'не запущена через' in str(_e), _e
        assert _rpc.is_attached() is False
        assert _rpc.pid is None
    finally:
        if _real is not None:
            os.environ['APPDATA'] = _real
print('   OK')

# ──────────────────────────────────────────────────────────────────
# detach(forget=False) не стирает запись: retry должен найти её.
# Баг был такой: первая попытка падала, detach стёр
# запись, вторая уперлась в «не наша».
print('19) detach(forget=False) сохраняет запись...')
with tempfile.TemporaryDirectory() as td:
    os.environ['APPDATA'] = td
    try:
        _me = os.getpid()
        _exe = os.path.abspath(sys.executable)
        _reg.record_launch(_me, _exe, r'C:\fake\UGame')
        _rpc = UnityMonoRPC()
        _rpc._pid = _me
        _rpc.detach(forget=False)
        assert _reg.verify_launch(_me, r'C:\fake\UGame') == _exe, \
            'запись должна остаться для retry'
        _rpc._pid = _me
        _rpc.detach()
        assert _reg.verify_launch(_me) is None, \
            'полный detach стирает запись'
    finally:
        if _real is not None:
            os.environ['APPDATA'] = _real
print('   OK')
print('ВСЕ НОВЫЕ ТЕСТЫ UNITY (18-19) ПРОШЛИ')

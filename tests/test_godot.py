# -*- coding: utf-8 -*-
"""Godot 4: формат .pck (сверен с file_access_pack.cpp 4.2), извлечение
csv/tscn/tres/gd, безопасная пересборка пакета, защита от ломки игры.

Только синтетика: .pck собирается прямо здесь, реальной Godot-игры у нас
нет. Строки — выдуманные ASCII-маркеры вида T1/T2, не текст игр.
"""
import hashlib
import io
import os
import struct
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.godot import pck, parser
from app.core.models import TranslationEntry

Q = '"'

CSV_SRC = (
    "keys,en\n"
    "T1,T2 alpha bravo\n"
    "T2,T2 charlie delta\n"
    "T3,T3 echo %s foxtrot\n"
    "T4,\n"
)

TSCN_SRC = (
    "[gd_scene format=3]\n"
    "\n"
    "[ext_resource type=\"Script\" path=\"res://code/main.gd\" id=\"1_abc\"]\n"
    "\n"
    "[node name=\"Main\" type=\"Node\"]\n"
    "script = ExtResource(\"1_abc\")\n"
    "\n"
    "[node name=\"Btn\" type=\"Button\"]\n"
    "text = \"T5 golf hotel\"\n"
    "placeholder_text = \"T6 india juliet\"\n"
    "icon = ExtResource(\"2_icon\")\n"
    "item_text = PackedStringArray(\"T7 kilo lima\", \"T8 mike november\")\n"
    "; комментарий со строкой \"T9 oscar papa\"\n"
)

GD_SRC = (
    "extends Node\n"
    "\n"
    "var title = \"TA papa quebec\"\n"
    "# player's save # T_second\n"
    "var path = load(\"res://data/x.bin\")\n"
    "var key = \"Button_2\"\n"
    "var greeting = 'TB romeo sierra'\n"
)


def _pack(root: str, **kw) -> str:
    """Синтетический .pck в папке игры."""
    path = os.path.join(root, "game.pck")
    pck.pack_files(path, {
        "res://locale/translation.csv": CSV_SRC.encode("utf-8"),
        "res://scenes/main.tscn": TSCN_SRC.encode("utf-8"),
        "res://code/main.gd": GD_SRC.encode("utf-8"),
        "res://data/x.bin": bytes(range(256)),
        "res://data/level.scn": b"RSCC" + bytes(30),
        "res://code/compiled.gdc": b"GDSC\x00" + bytes(20),
    }, **kw)
    return path


def _raw_header(raw: bytes) -> dict:
    """Разбор заголовка .pck СТРОГО ПО fap.cpp:199-217.

    Смещения взяты из самого исходника движка, а не из ``pck.py``,
    поэтому одинаковая ошибка в обоих местах не сойдётся за «успех»:
    round-trip через собственный ``pack_files`` доказывает лишь
    согласованность двух авторов одной модели.

        fap.cpp:199-202  version, ver_major, ver_minor, patch
        fap.cpp:207-208  pack_flags, file_base
        fap.cpp:212-215  16 зарезервированных uint32 (пропускаем)
        fap.cpp:217      file_count
    """
    assert raw[:4] == b"GDPC", "fap.cpp:140-141 magic"
    return {
        "version": struct.unpack_from("<I", raw, 4)[0],
        "ver_major": struct.unpack_from("<I", raw, 8)[0],
        "ver_minor": struct.unpack_from("<I", raw, 12)[0],
        "ver_patch": struct.unpack_from("<I", raw, 16)[0],
        "pack_flags": struct.unpack_from("<I", raw, 20)[0],
        "file_base": struct.unpack_from("<Q", raw, 24)[0],
        "reserved": list(struct.unpack_from("<16I", raw, 32)),
        "file_count": struct.unpack_from("<I", raw, 96)[0],
    }


def _raw_entries(raw: bytes, file_count: int, file_base: int = 0) -> list[dict]:
    """Каталог .pck СТРОГО ПО fap.cpp:235-251.

    fap.cpp:217 — каталог идёт сразу за file_count, поля ``dir_offset``
    в 4.2 нет. fap.cpp:245 — ``ofs = file_base + прочитанное``.
    """
    pos = 100
    out = []
    for i in range(file_count):
        path_len = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        path = raw[pos:pos + path_len].decode("utf-8")
        pos += path_len
        rel_ofs = struct.unpack_from("<Q", raw, pos)[0]
        size = struct.unpack_from("<Q", raw, pos + 8)[0]
        md5 = raw[pos + 16:pos + 32]
        flags = struct.unpack_from("<I", raw, pos + 32)[0]
        pos += 36
        out.append({"path": path, "ofs": file_base + rel_ofs, "size": size,
                    "md5": md5, "flags": flags})
    return out


def _raw_header_v3(raw: bytes) -> dict:
    """Разбор заголовка v3 СТРОГО ПО fap.cpp (Godot 4.6), :289-319.

    Отличие от :func:`_raw_header` — не в байтах, а в ПОРЯДКЕ: полем
    ``dir_offset`` вместо ``reserved[16]``, а ``file_count`` читается уже
    ПОСЛЕ ``seek(dir_offset + pck_start_pos)`` (fap.cpp:307-319), а не по
    текущей позиции. Читать его «там, где остановились» — ровно та ошибка,
    из-за которой v2-разбор v3 берёт в file_count мусор.

        fap.cpp:227    magic
        fap.cpp:289-292 version, ver_major, ver_minor, ver_patch
        fap.cpp:297    pack_flags
        fap.cpp:302    file_base
        fap.cpp:309-310 dir_offset, затем seek(dir_offset + pck_start_pos)
        fap.cpp:319    file_count
    """
    assert raw[:4] == b"GDPC", "fap.cpp:228 magic"
    head = {
        "version": struct.unpack_from("<I", raw, 4)[0],
        "ver_major": struct.unpack_from("<I", raw, 8)[0],
        "ver_minor": struct.unpack_from("<I", raw, 12)[0],
        "ver_patch": struct.unpack_from("<I", raw, 16)[0],
        "pack_flags": struct.unpack_from("<I", raw, 20)[0],
        "file_base": struct.unpack_from("<Q", raw, 24)[0],
        "dir_offset": struct.unpack_from("<Q", raw, 32)[0],
    }
    pos = head["dir_offset"]        # fap.cpp:310: seek(dir_offset + start)
    head["file_count"] = struct.unpack_from("<I", raw, pos)[0]
    return head


def _raw_entries_v3(raw: bytes, file_count: int, dir_offset: int,
                    file_base: int, pck_start: int = 0) -> list[dict]:
    """Каталог v3 СТРОГО ПО fap.cpp:307-353.

    ``pck_start_pos`` складывается и в ``dir_offset`` (fap.cpp:309), и в
    ``file_base`` (fap.cpp:303-305, для v3 безусловно) — поэтому при
    пакете по смещению подставлять надо в оба места.
    """
    pos = dir_offset + pck_start + 4        # +4 = uint32 file_count
    out = []
    for _i in range(file_count):
        path_len = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        path = raw[pos:pos + path_len].decode("utf-8")
        pos += path_len
        rel_ofs = struct.unpack_from("<Q", raw, pos)[0]
        size = struct.unpack_from("<Q", raw, pos + 8)[0]
        md5 = raw[pos + 16:pos + 32]
        flags = struct.unpack_from("<I", raw, pos + 32)[0]
        pos += 36
        out.append({"path": path, "ofs": file_base + pck_start + rel_ofs,
                    "size": size, "md5": md5, "flags": flags})
    return out


def _v3_dir_to_end(path: str) -> int:
    """Переложить каталог v3 в КОНЕЦ пакета. Вернуть новый dir_offset.

    Так выглядит настоящая сборка Godot 4.6: блобы идут подряд, а каталог
    лежит после них, и ``dir_offset`` указывает на него. Синтетика с
    каталогом сразу за заголовком этот случай не проверяет — именно на
    нём ошибаются при пересборке.
    """
    header = pck.read_header(path)
    entries = pck.read_entries(path, header)
    raw = open(path, "rb").read()
    dir_size = sum(pck.ENTRY_OVERHEAD + len(e.path.encode("utf-8"))
                   for e in entries)
    # вырезаем ВМЕСТЕ с file_count: он лежит по dir_offset (fap.cpp:319)
    cat_start = header.dir_offset
    cat_end = cat_start + 4 + dir_size
    catalog = raw[cat_start:cat_end]
    # место каталога заменяем ПРОБЕЛАМИ, а не вырезаем: блобы обязаны
    # остаться на тех же абсолютных смещениях, что записаны в записях
    body = raw[:cat_start] + b"\x00" * (cat_end - cat_start) + raw[cat_end:]
    out = body + catalog                       # и кладём каталог в хвост
    new_dir = len(body)
    blob = bytearray(out[:pck.HEADER_SIZE_V3])
    struct.pack_into("<Q", blob, 32, new_dir)
    out = bytes(blob) + out[pck.HEADER_SIZE_V3:]
    with open(path, "wb") as f:
        f.write(out)
    # смещения записей при этом НЕ меняются: блобы остались на своих местах
    assert pck.read_entries(path, pck.read_header(path))[0].ofs == \
        entries[0].ofs
    assert new_dir > header.dir_offset + 4 + dir_size
    return new_dir


print("1) Формат .pck: независимый разбор по fap.cpp + наш парсер...")
with tempfile.TemporaryDirectory() as td:
    path = _pack(td, version=2, ver_major=4, ver_minor=2, ver_patch=1,
                 file_base=4096, reserved=[7] * 16)
    raw = open(path, "rb").read()
    assert raw[:4] == b"GDPC"
    # fap.cpp:199-217 — version..pack_flags, file_base, reserved[16], file_count
    assert struct.unpack_from("<I", raw, 0)[0] == pck.MAGIC_U32
    assert struct.unpack_from("<I", raw, 96)[0] == 6, "file_count на 96"
    # и сразу на 100 идёт path_len первой записи: dir_offset в 4.2 НЕТ.
    # Если бы поле было, path_len лежал бы на 108 и подпись выше рассыпалась бы.
    first_len = struct.unpack_from("<I", raw, 100)[0]
    assert first_len == len("res://locale/translation.csv")
    assert raw[104:104 + first_len] == b"res://locale/translation.csv"
    assert pck.HEADER_SIZE == 100

    # независимое чтение обязано совпасть с pck.read_header/read_entries
    rh = _raw_header(raw)
    header = pck.read_header(path)
    entries = pck.read_entries(path, header)
    raw_entries = _raw_entries(raw, rh["file_count"], rh["file_base"])
    for field in ("version", "ver_major", "ver_minor", "ver_patch",
                  "pack_flags", "file_base", "file_count"):
        assert getattr(header, field) == rh[field], field
    assert header.reserved == rh["reserved"] == [7] * 16
    assert len(entries) == len(raw_entries) == 6
    for got, want in zip(entries, raw_entries):
        assert got.path == want["path"], (got.path, want["path"])
        assert got.ofs == want["ofs"], (got.ofs, want["ofs"])
        assert got.size == want["size"]
        assert got.md5 == want["md5"]
        assert got.flags == want["flags"]
    # и блоб по НЕЗАВИСИМО вычисленному смещению — те же байты
    blob = raw[raw_entries[3]["ofs"]:raw_entries[3]["ofs"]
               + raw_entries[3]["size"]]
    assert blob == bytes(range(256))
    assert hashlib.md5(blob).digest() == raw_entries[3]["md5"]
print("   OK")

print("2) Round-trip: записали -> прочитали -> пути/size/md5 совпали...")
with tempfile.TemporaryDirectory() as td:
    path = _pack(td, version=2, ver_major=4, ver_minor=2, ver_patch=1,
                 file_base=4096, reserved=[7] * 16)
    header = pck.read_header(path)
    entries = pck.read_entries(path, header)
    assert header.version == 2 and header.ver_major == 4
    assert header.ver_minor == 2 and header.ver_patch == 1
    assert header.file_base == 4096 and header.reserved == [7] * 16
    assert header.file_count == 6 and len(header.reserved) == 16
    assert pck.locate(path) == (0, False)
    assert [e.path for e in entries] == [
        "res://locale/translation.csv", "res://scenes/main.tscn",
        "res://code/main.gd", "res://data/x.bin", "res://data/level.scn",
        "res://code/compiled.gdc"]
    assert all(len(e.md5) == 16 for e in entries)
    # ofs абсолютный: file_base уже сложен (fap.cpp:245)
    assert entries[0].ofs >= header.file_base + pck.HEADER_SIZE
    assert pck.read_blob(path, entries[3]) == bytes(range(256))
    assert pck.read_blob(path, entries[0]) == CSV_SRC.encode("utf-8")
    assert pck.verify(path, [e.path for e in entries], {}) == []
print("   OK")

print("3) Детект: пусто / .pck / project.godot / .godot / self-contained...")
with tempfile.TemporaryDirectory() as td:
    assert parser.detect(td) == 0
with tempfile.TemporaryDirectory() as td:
    _pack(td)
    assert parser.detect(td) == 100
with tempfile.TemporaryDirectory() as td:
    open(os.path.join(td, "project.godot"), "w").close()
    assert parser.detect(td) == 95
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, ".godot"))
    assert parser.detect(td) == 85
with tempfile.TemporaryDirectory() as td:
    with tempfile.TemporaryDirectory() as stage:
        tmp = os.path.join(stage, "_base.pck")
        pck.pack_files(tmp, {"res://a.tscn": b"[gd_scene]\n"})
        pck.embedded_pck(os.path.join(td, "Game.exe"),
                         open(tmp, "rb").read())
    assert parser.detect(td) == 70, "self-contained exe виден, но не наш"
with tempfile.TemporaryDirectory() as td:
    open(os.path.join(td, "readme.txt"), "w").write("hi")
    assert parser.detect(td) == 0
print("   OK")

print("4) Извлечение: csv/tscn/gd найдены, служебное — нет...")
with tempfile.TemporaryDirectory() as td:
    _pack(td)
    entries = parser.extract(td)
    texts = [e.original for e in entries]
    paths = {(e.file, e.json_path) for e in entries}
    assert ("res://locale/translation.csv", "line[2].col[1]") in paths
    assert ("res://locale/translation.csv", "line[3].col[1]") in paths
    assert "T5 golf hotel" in texts and "T6 india juliet" in texts
    assert "T7 kilo lima" in texts and "T8 mike november" in texts
    assert "TA papa quebec" in texts and "TB romeo sierra" in texts
    # служебное в перевод не попало НИКОГДА
    assert not any("res://" in t for t in texts), texts
    assert "1_abc" not in texts and "2_icon" not in texts
    assert "Main" not in texts and "Btn" not in texts
    assert "Button_2" not in texts and "Button" not in texts
    assert "T9 oscar papa" not in texts          # из комментария ; в .tscn
    assert "T_second" not in texts               # из комментария # в .gd
    assert "T1" not in texts and "T2" not in texts   # колонка ключей
    assert "T4" not in texts                     # пустое значение
    counts = parser.scan(td)
    assert counts["candidates"] == len(entries) == 9, counts
    assert counts["unsupported:binary"] == 1     # .scn
    assert counts["unsupported:gdc"] == 1        # .gdc
    assert counts["skipped:path"] == 1             # load("res://...")
    assert counts["skipped:identifier"] == 1      # "Button_2"
print("   OK")

print("5) Внедрение: перевод записан, оригинал в бэкапе, повтор идемпотентен...")
with tempfile.TemporaryDirectory() as td:
    path = _pack(td)
    before = open(path, "rb").read()
    entries = parser.extract(td)
    for i, e in enumerate(entries):
        e.translation = "RU%02d %s" % (i, e.original)
        e.status = "translated"
    skipped = []
    stats = parser.apply(td, entries, on_skip=lambda e, r: skipped.append(r))
    assert stats["files"] == 3 and stats["strings"] == len(entries), stats
    assert not stats["verify_failed"], stats["verify_failed"]
    assert stats["skipped_total"] == 0 and stats["skipped_by"] == {}
    assert len(stats["backups"]) == 1, stats["backups"]
    # бэкап — побайтовая копия ДО изменений
    assert open(stats["backups"][0], "rb").read() == before
    # пакет жив: те же файлы/порядок, изменённый md5 пересчитан
    header = pck.read_header(path)
    catalog = pck.read_entries(path, header)
    assert [e.path for e in catalog] == [
        "res://locale/translation.csv", "res://scenes/main.tscn",
        "res://code/main.gd", "res://data/x.bin", "res://data/level.scn",
        "res://code/compiled.gdc"]
    assert pck.read_blob(path, catalog[3]) == bytes(range(256)), "нетронутый"
    assert parser.verify(td) == []
    # перевод реально в файлах
    csv_out = pck.read_blob(path, catalog[0]).decode("utf-8")
    assert "RU00 T2 alpha bravo" in csv_out and csv_out.startswith("keys,en")
    tscn_out = pck.read_blob(path, catalog[1]).decode("utf-8")
    assert "ExtResource(\"1_abc\")" in tscn_out
    assert 'path=' + Q + "res://code/main.gd" + Q in tscn_out
    # повторный apply ничего не ломает и не считается ошибкой
    stats2 = parser.apply(td, entries)
    assert stats2["strings"] == 0 and stats2["files"] == 0, stats2
    assert stats2["skipped_total"] == 0, stats2
    # откат возвращает оригинальный байт в байт
    assert parser.restore_original(td)["restored"] >= 1
    assert open(path, "rb").read() == before
print("   OK")

print("6) Защита: placeholder и строка-путь дают пропуск С ПРИЧИНОЙ...")
assert parser.reject_reason("res://icon.png") == "path"
assert parser.reject_reason("icon.png") == "path"
assert parser.reject_reason("scenes/main.tscn") == "path"
assert parser.reject_reason("Button_2") == "identifier"
assert parser.reject_reason("id_12345") == "identifier"
assert parser.reject_reason("42") == "no letters"
assert parser.reject_reason("A") == "too short"
assert parser.reject_reason("T1 alpha bravo") is None
assert parser.translation_reason("T1 %s alpha", "T2 bravo") == "placeholder"
assert parser.translation_reason("T1 alpha", "T2 {0} bravo") == "placeholder"
assert parser.translation_reason("T1 alpha", "T2 bravo") is None
with tempfile.TemporaryDirectory() as td:
    _pack(td)
    entries = parser.extract(td)
    # 1) перевод ломает плейсхолдер
    ph = next(e for e in entries if "%s" in e.original)
    ph.translation = "RU без плейсхолдера"
    ph.status = "translated"
    # 2) в перевод всунули путь ресурса (испорченный .ob.json / ручная правка)
    fake = TranslationEntry(id=9999, file="res://locale/translation.csv",
                            json_path="line[4].col[1]", context="x",
                            original="T4", translation="res://icon.png",
                            status="translated")
    # 3) оригинал не совпал (файл правили руками)
    stale = TranslationEntry(id=9998, file="res://locale/translation.csv",
                             json_path="line[3].col[1]", context="x",
                             original="T999 другой текст",
                             translation="RU что-то", status="translated")
    # 4) в записи originaл — путь ресурса (испорченный .ob.json)
    res_path = TranslationEntry(id=9997, file="res://scenes/main.tscn",
                                json_path="line[1].str[1]", context="x",
                                original="res://icon.png",
                                translation="RU картинка", status="translated")
    others = [e for e in entries if e is not ph]
    for i, e in enumerate(others):
        e.translation = "RU%02d %s" % (i, e.original)
        e.status = "translated"
    reasons = []
    stats = parser.apply(td, [ph, fake, stale, res_path] + others,
                         on_skip=lambda e, r: reasons.append(r))
    assert stats["skipped_by"] == {"original not found": 1, "identifier": 1,
                                   "path": 1, "placeholder": 1}, stats
    assert stats["skipped_total"] == 4, stats
    assert set(reasons) == {"placeholder", "original not found",
                            "identifier", "path"}, reasons
    assert stats["strings"] == len(entries) - 1, stats
    assert not stats["verify_failed"]
    # в файл путь не попал
    pack_path = os.path.join(td, "game.pck")
    header = pck.read_header(pack_path)
    csv_out = pck.read_blob(pack_path, pck.read_entries(
        pack_path, header)[0]).decode("utf-8")
    tscn_out = pck.read_blob(pack_path, pck.read_entries(
        pack_path, header)[1]).decode("utf-8")
    assert "res://icon.png" not in csv_out and "res://icon.png" not in tscn_out
    assert "RU картинка" not in tscn_out
    assert "RU без плейсхолдера" not in csv_out
print("   OK")

print("7) Экранирование: кавычки в переводе не ломают .tscn/.gd...")
assert parser.escape('он сказал "да"') == 'он сказал \\"да\\"'
assert parser.unescape(parser.escape('он сказал "да"')) == 'он сказал "да"'
assert parser.unescape("a\\nb") == "a\nb"
assert parser.escape("a\nb") == "a\\nb"
with tempfile.TemporaryDirectory() as td:
    _pack(td)
    entries = parser.extract(td)
    entry = next(e for e in entries if e.original == "T5 golf hotel")
    entry.translation = 'RU "кавычки" и \\ слеш'
    entry.status = "translated"
    stats = parser.apply(td, [entry])
    assert stats["strings"] == 1, stats
    path = os.path.join(td, "game.pck")
    catalog = pck.read_entries(path, pck.read_header(path))
    tscn_out = pck.read_blob(path, catalog[1]).decode("utf-8")
    assert 'text = "RU \\"кавычки\\" и \\\\ слеш"' in tscn_out, tscn_out
    assert parser.verify(td) == []
print("   OK")

print("8) CSV: запятая и кавычка в переводе -> корректное поле...")
with tempfile.TemporaryDirectory() as td:
    _pack(td)
    entries = parser.extract(td)
    entry = next(e for e in entries if e.original == "T2 alpha bravo")
    entry.translation = 'RU "да, точно", вторая'
    entry.status = "translated"
    assert parser.apply(td, [entry])["strings"] == 1
    path = os.path.join(td, "game.pck")
    catalog = pck.read_entries(path, pck.read_header(path))
    csv_out = pck.read_blob(path, catalog[0]).decode("utf-8")
    assert '"RU ""да, точно"", вторая"' in csv_out, csv_out
    assert parser.csv_value(parser.csv_quote(entry.translation)) == \
        entry.translation
    # перевод с переводом строк в CSV не пишем
    entry2 = next(e for e in parser.extract(td)
                  if e.original == "T2 charlie delta")
    entry2.translation = "RU две\nстроки"
    entry2.status = "translated"
    assert parser.apply(td, [entry2])["skipped_by"].get("control chars") == 1
print("   OK")

print("9) Зашифрованные пакеты: честный отказ, без попыток вскрыть...")
with tempfile.TemporaryDirectory() as td:
    _pack(td, pack_flags=pck.PACK_DIR_ENCRYPTED)
    try:
        pck.read_header(os.path.join(td, "game.pck"))
        raise AssertionError("ожидался PckEncrypted")
    except pck.PckEncrypted:
        pass
    assert parser.extract(td) == []
    assert parser.scan(td)["unsupported:encrypted"] == 1
    entries = [TranslationEntry(1, "res://locale/translation.csv",
                                "line[2].col[1]", "x", "T1 alpha bravo",
                                "RU перевод", "translated")]
    reasons = []
    stats = parser.apply(td, entries, on_skip=lambda e, r: reasons.append(r))
    assert stats["strings"] == 0 and stats["files"] == 0
    assert reasons == ["encrypted pack"], reasons
    assert not os.path.exists(os.path.join(td, "backup")), "бэкап не нужен"
with tempfile.TemporaryDirectory() as td:
    # зашифрован ОТДЕЛЬНЫЙ файл внутри каталога
    path = os.path.join(td, "game.pck")
    pck.pack_files(path, {
        "res://a.csv": b"keys,en\nT1,T2 alpha bravo\n",
        "res://b.csv": b"keys,en\nT2,T2 charlie delta\n",
    })
    header = pck.read_header(path)
    entries = pck.read_entries(path, header)
    patched = pck.PckEntry(path=entries[1].path, ofs=entries[1].ofs,
                           size=entries[1].size, md5=entries[1].md5,
                           flags=pck.PACK_FILE_ENCRYPTED)
    assert patched.encrypted and not entries[0].encrypted
    # ставим флаг ровно во второй записи каталога
    off = header.dir_start + pck.ENTRY_OVERHEAD + len(
        entries[0].path.encode("utf-8"))
    off += 4 + len(entries[1].path.encode("utf-8")) + 32
    with open(path, "r+b") as f:
        f.seek(off)
        f.write(struct.pack("<I", pck.PACK_FILE_ENCRYPTED))
    assert parser.scan(td)["unsupported:encrypted"] == 1
    assert [e.original for e in parser.extract(td)] == ["T2 alpha bravo"]
print("   OK")

print("10) Self-contained exe: видим, но НЕ трогаем...")
with tempfile.TemporaryDirectory() as td:
    with tempfile.TemporaryDirectory() as stage:
        tmp = os.path.join(stage, "_base.pck")
        pck.pack_files(tmp, {
            "res://locale/translation.csv": CSV_SRC.encode("utf-8"),
        })
        exe = pck.embedded_pck(os.path.join(td, "Game.exe"),
                               open(tmp, "rb").read())
    before = open(exe, "rb").read()
    counts = parser.scan(td)
    assert counts["unsupported:embedded"] == 1, counts
    assert parser.extract(td) == []
    entries = [TranslationEntry(1, "res://locale/translation.csv",
                                "line[2].col[1]", "x", "T2 alpha bravo",
                                "RU перевод", "translated")]
    reasons = []
    stats = parser.apply(td, entries, on_skip=lambda e, r: reasons.append(r))
    assert stats["strings"] == 0 and stats["files"] == 0
    assert reasons == ["unsupported:embedded"], reasons
    assert open(exe, "rb").read() == before, "exe обязан остаться целым"
print("   OK")

print("11) Битый/чужой .pck и битые смещения -> отказ, а не догадки...")
with tempfile.TemporaryDirectory() as td:
    open(os.path.join(td, "game.pck"), "wb").write(b"NOTAPCK" + bytes(500))
    assert pck.locate(os.path.join(td, "game.pck")) is None
    assert parser.extract(td) == []
    assert parser.scan(td)["unsupported:format"] == 1
with tempfile.TemporaryDirectory() as td:
    path = _pack(td)
    raw = bytearray(open(path, "rb").read())
    # сдвигаем ofs первой записи за пределы файла
    struct.pack_into("<Q", raw, 100 + 4 + 28, len(raw) + 1000)
    open(path, "wb").write(bytes(raw))
    try:
        pck.read_entries(path, pck.read_header(path))
        raise AssertionError("ожидался PckError на битом смещении")
    except pck.PckError:
        pass
print("   OK")

print("12) Несколько .pck: цель одна, остальные посчитаны...")
with tempfile.TemporaryDirectory() as td:
    pck.pack_files(os.path.join(td, "a.pck"),
                   {"res://locale/translation.csv": CSV_SRC.encode()})
    pck.pack_files(os.path.join(td, "b.pck"),
                   {"res://extra.csv": b"keys,en\nT9,T9 oscar papa\n"})
    assert parser.scan(td)["unsupported:multi-pack"] == 1
    assert {e.file for e in parser.extract(td)} == {
        "res://locale/translation.csv"}, "берём первый .pck"
    assert len(parser.extract(td)) == 3
print("   OK")

print("13) Распакованный проект (project.godot) — тот же extract/apply...")
with tempfile.TemporaryDirectory() as td:
    open(os.path.join(td, "project.godot"), "w").close()
    os.makedirs(os.path.join(td, "locale"))
    os.makedirs(os.path.join(td, ".godot"))
    csv_path = os.path.join(td, "locale", "translation.csv")
    with open(csv_path, "wb") as f:
        f.write(CSV_SRC.encode("utf-8"))
    with open(os.path.join(td, "main.gd"), "wb") as f:
        f.write(GD_SRC.encode("utf-8"))
    assert parser.detect(td) == 95
    entries = parser.extract(td)
    texts = [e.original for e in entries]
    assert "T2 alpha bravo" in texts and "TA papa quebec" in texts
    assert entries[0].file in ("locale/translation.csv", "main.gd")
    for i, e in enumerate(entries):
        e.translation = "RU%02d %s" % (i, e.original)
        e.status = "translated"
    before = open(csv_path, "rb").read()
    stats = parser.apply(td, entries)
    assert stats["strings"] == len(entries) and stats["files"] == 2, stats
    assert not stats["verify_failed"]
    assert "RU" in open(csv_path, encoding="utf-8").read()
    assert "RU" in open(os.path.join(td, "main.gd"), encoding="utf-8").read()
    # бэкап оригинала на месте и используется повторно
    bak = stats["backups"][0]
    assert open(bak, "rb").read() == before
    stats2 = parser.apply(td, entries)
    assert stats2["strings"] == 0, stats2
    assert parser.restore_original(td)["restored"] == 2
    assert open(csv_path, "rb").read() == before
print("   OK")

print("14) Границы слоёв: в core нет Qt, движок не зарегистрирован...")
here = os.path.dirname(os.path.abspath(__file__))
core = os.path.join(os.path.dirname(here), "app", "core", "godot")
for fn in sorted(os.listdir(core)):
    if not fn.endswith(".py"):
        continue
    body = open(os.path.join(core, fn), encoding="utf-8").read()
    assert "QtCore" not in body and "PySide6" not in body, fn
    assert "import requests" not in body and "frida" not in body, fn
from app.engines.registry import MODULES
assert not any(c.key == "godot" for c in MODULES), "регистрация — отдельная задача"
print("   OK")

print("15) verify читает БЛОБЫ: битый байт и сдвиг смещения ловятся...")
with tempfile.TemporaryDirectory() as td:
    path = _pack(td)
    header = pck.read_header(path)
    entries = pck.read_entries(path, header)
    want_blob = b"keys,en\nT1,RU alpha bravo\n"
    pck.write_pck(path, path, header, entries,
                  {"res://locale/translation.csv": want_blob})
    want_md5 = hashlib.md5(want_blob).digest()
    assert pck.verify(path, [e.path for e in entries],
                      {"res://locale/translation.csv": want_md5}) == []
    # КАТАЛОГ при этом самосогласован (md5 в нём правильный) — портим
    # ОДИН байт блоба: это ровно то, что делает ошибка арифметики
    # смещений, уехавшая на байт. Старый verify молчал бы.
    target = pck.read_entries(path, pck.read_header(path))[0]
    with open(path, "r+b") as f:
        f.seek(target.ofs)
        cur = f.read(1)
        f.seek(target.ofs)
        f.write(bytes([cur[0] ^ 0xFF]))
    problems = pck.verify(path, [e.path for e in entries],
                          {"res://locale/translation.csv": want_md5})
    assert problems, "битый блоб обязан быть замечен"
    # и сдвиг самого смещения: каталог едет, блоб остаётся на месте
    raw = bytearray(open(path, "rb").read())
    struct.pack_into("<Q", raw, 100 + 4 + 28, len(raw) + 1000)
    open(path, "wb").write(bytes(raw))
    assert pck.verify(path, [e.path for e in entries],
                      {"res://locale/translation.csv": want_md5})
print("   OK")

print("16) Неизвестная версия .pck — честный отказ с ЧИСЛОМ...")
for version, vmaj in ((1, 3), (4, 5), (99, 4)):
    with tempfile.TemporaryDirectory() as td:
        path = _pack(td, version=version, ver_major=vmaj)
        before = open(path, "rb").read()
        counts = parser.scan(td)
        assert counts.get("unsupported:version:%d" % version) == 1, counts
        assert parser.extract(td) == []
        entries = [TranslationEntry(1, "res://locale/translation.csv",
                                    "line[2].col[1]", "x", "T2 alpha bravo",
                                    "RU перевод", "translated")]
        reasons = []
        stats = parser.apply(td, entries,
                             on_skip=lambda e, r: reasons.append(r))
        assert stats["strings"] == 0 and stats["files"] == 0, stats
        assert reasons == ["unsupported:version %d" % version], reasons
        assert open(path, "rb").read() == before, "пакет не тронут"
# константы движка: 3.5 -> PACK_FORMAT_VERSION 1, 4.0-4.3 -> 2, master -> 4
assert pck.FORMAT_VERSION_3X == 1 and pck.FORMAT_VERSION_4X == 2
pck.check_version(2, 4, 0)   # раскладка, которую мы умеем
for bad in ((1, 3, 5), (2, 3, 5), (4, 5, 0)):
    try:
        pck.check_version(*bad)
        raise AssertionError("ожидался PckVersion для %r" % (bad,))
    except pck.PckVersion as exc:
        assert exc.version == bad[0], bad
print("   OK")

print("17) Откат: неуспешный verify возвращает .pк к оригиналу...")
_real_verify = parser.pck.verify
with tempfile.TemporaryDirectory() as td:
    path = _pack(td)
    before = open(path, "rb").read()
    entries = parser.extract(td)
    for i, e in enumerate(entries):
        e.translation = "RU%02d %s" % (i, e.original)
        e.status = "translated"
    parser.pck.verify = lambda *a, **kw: ["verify: подделка"]
    try:
        stats = parser.apply(td, entries)
    finally:
        parser.pck.verify = _real_verify
    assert stats["verify_failed"], "молчать о провале нельзя"
    assert stats["strings"] == 0 and stats["files"] == 0, stats
    assert stats["verify_restored"] is True, stats
    assert open(path, "rb").read() == before, "игра обязана быть целой"
    assert parser.verify(td) == []
print("   OK")

print("18) apply, упавший с OSError ПОСЛЕ записи: откат и stats, не traceback...")
with tempfile.TemporaryDirectory() as td:
    path = _pack(td)
    before = open(path, "rb").read()
    entries = parser.extract(td)
    for i, e in enumerate(entries):
        e.translation = "RU%02d %s" % (i, e.original)
        e.status = "translated"

    def _boom(*a, **kw):
        raise OSError("диск отвалился")

    parser.pck.verify = _boom
    try:
        stats = parser.apply(td, entries)     # НЕ имеет права бросить
    finally:
        parser.pck.verify = _real_verify
    assert stats["verify_failed"], stats
    assert stats["strings"] == 0 and stats["files"] == 0, stats
    assert stats["verify_restored"] is True, stats
    assert open(path, "rb").read() == before, "откат обязателен"
print("   OK")

print("19) Битый/усечённый бэкап НЕ используется как годный...")
# 19a. оборванная потоковая запись не оставляет куска под настоящим именем
with tempfile.TemporaryDirectory() as td:
    dest = os.path.join(td, "out.bin")
    with open(dest, "wb") as f:
        f.write(b"ORIGINAL")

    def _half(fh):
        fh.write(b"\x00" * 5)
        raise OSError("нет места на диске")

    try:
        pck._atomic_stream(dest, _half)
        raise AssertionError("ожидался OSError")
    except OSError:
        pass
    assert open(dest, "rb").read() == b"ORIGINAL", "файл не тронут"
    assert not [n for n in os.listdir(td) if n.startswith(".tmp-")]
# 19b. обрезок на месте + манифеста нет -> apply пересоздаёт бэкап целиком
with tempfile.TemporaryDirectory() as td:
    path = _pack(td)
    before = open(path, "rb").read()
    bak_dir = os.path.join(td, "backup")
    os.makedirs(bak_dir)
    bak = os.path.join(bak_dir, "game.pck.ob_bak")
    with open(bak, "wb") as f:
        f.write(b"\x00" * 10)          # ровно тот обрезок, что убивал игру
    entries = parser.extract(td)
    for i, e in enumerate(entries):
        e.translation = "RU%02d %s" % (i, e.original)
        e.status = "translated"
    stats = parser.apply(td, entries)
    assert stats["strings"] == len(entries), stats
    assert not stats["verify_failed"], stats
    assert os.path.getsize(bak) == len(before), "обрезок пересоздан"
    assert open(bak, "rb").read() == before
    assert parser.restore_original(td)["restored"] >= 1
    assert open(path, "rb").read() == before
# 19c. restore_original отказывается откатываться из обрезка
with tempfile.TemporaryDirectory() as td:
    path = _pack(td)
    before = open(path, "rb").read()
    bak_dir = os.path.join(td, "backup")
    os.makedirs(bak_dir)
    bak = os.path.join(bak_dir, "game.pck.ob_bak")
    with open(bak, "wb") as f:
        f.write(b"\x00" * 10)
    parser._save_pck_manifest(td, {
        "pck": os.path.abspath(path), "backup": os.path.abspath(bak),
        "backup_size": len(before)})
    with open(path, "r+b") as f:      # пакет «переведён», оригинала нет
        f.seek(200)
        f.write(b"RU")
    dirty = open(path, "rb").read()
    out = parser.restore_original(td)
    assert out["restored"] == 0, out
    assert out["failed"], out
    assert open(path, "rb").read() == dirty, "откат из обрезка не делаем"
# 19d. годный бэкап повторный apply НЕ перетирает
with tempfile.TemporaryDirectory() as td:
    path = _pack(td)
    before = open(path, "rb").read()
    entries = parser.extract(td)
    for i, e in enumerate(entries):
        e.translation = "RU%02d %s" % (i, e.original)
        e.status = "translated"
    stats = parser.apply(td, entries)
    bak = stats["backups"][0]
    assert open(bak, "rb").read() == before
    # второй apply меняет .pck (размер/байты другие), но не оригинал
    again = parser.extract(td)
    for i, e in enumerate(again):
        e.translation = "FR%02d %s" % (i, e.original)
        e.status = "translated"
    stats2 = parser.apply(td, again)
    assert stats2["files"] == 3, stats2
    assert not stats2["verify_failed"], stats2
    assert os.path.getsize(path) != len(before), "пакет не изменился?"
    assert open(bak, "rb").read() == before, "оригинал затёрт!"
    assert parser.restore_original(td)["restored"] >= 1
    assert open(path, "rb").read() == before
print("   OK")

print("20) verify() не обещает того, чего не проверял...")
with tempfile.TemporaryDirectory() as td:
    _pack(td)
    path = os.path.join(td, "game.pck")
    raw = open(path, "rb").read()
    with open(path, "wb") as f:
        f.write(raw[:110])          # каталог обрезан — пакет не читается
    problems = parser.verify(td)
    assert problems and "не читается" in problems[0], problems
with tempfile.TemporaryDirectory() as td:
    _pack(td, version=99, ver_major=4)   # раскладка, которую мы не умеем
    problems = parser.verify(td)
    assert problems and "version" in problems[0], problems
with tempfile.TemporaryDirectory() as td:
    _pack(td)                       # .pck есть, но его не трогали
    problems = parser.verify(td)
    assert problems and "внедрялся" in problems[0], problems
with tempfile.TemporaryDirectory() as td:
    problems = parser.verify(td)
    assert problems, "пустая папка: проверять нечего"
with tempfile.TemporaryDirectory() as td:
    open(os.path.join(td, "project.godot"), "w").close()
    problems = parser.verify(td)
    assert problems and "внедрялся" in problems[0], problems
    csv_path = os.path.join(td, "locale")
    os.makedirs(csv_path)
    with open(os.path.join(csv_path, "translation.csv"), "wb") as f:
        f.write(CSV_SRC.encode("utf-8"))
    entries = parser.extract(td)
    for i, e in enumerate(entries):
        e.translation = "RU%02d %s" % (i, e.original)
        e.status = "translated"
    assert parser.apply(td, entries)["files"] == 1
    assert parser.verify(td) == [], parser.verify(td)
    os.remove(os.path.join(csv_path, "translation.csv"))
    problems = parser.verify(td)
    assert problems and "отсутствует" in problems[0], problems
with tempfile.TemporaryDirectory() as td:
    with tempfile.TemporaryDirectory() as stage:
        tmp = os.path.join(stage, "_base.pck")
        pck.pack_files(tmp, {"res://locale/translation.csv": CSV_SRC.encode()})
        pck.embedded_pck(os.path.join(td, "Game.exe"), open(tmp, "rb").read())
    problems = parser.verify(td)
    assert problems and "embedded" in problems[0], problems
print("   OK")

print("21) Мелкие контракты: CSV, дубли позиций, полный список причин...")
assert parser.csv_balanced("T1,T2 alpha bravo") is True
assert parser.csv_balanced('"T1",T2 alpha bravo') is True
# второе поле не закрыто — раньше проверялось только первое
assert parser.csv_balanced('T1,"T2 alpha') is False
assert parser.csv_balanced('"T1,T2 alpha') is False
assert parser.csv_balanced("") is True
assert parser.csv_balanced("T1,") is True
# две записи на одну позицию = одно место в файле
with tempfile.TemporaryDirectory() as td:
    _pack(td)
    items = [TranslationEntry(1, "res://locale/translation.csv",
                              "line[2].col[1]", "x", "T2 alpha bravo",
                              "RU раз", "translated"),
             TranslationEntry(2, "res://locale/translation.csv",
                              "line[2].col[1]", "x", "T2 alpha bravo",
                              "RU два", "translated")]
    text, count, skipped = parser.splice_text(CSV_SRC, items)
    assert count == 1, (count, text)
    assert text.count("RU раз") == 1 and text.count("RU два") == 0, text
    assert skipped and skipped[0][1] == "duplicate position", skipped
# никакого молчаливого обрезания списка причин
with tempfile.TemporaryDirectory() as td:
    _pack(td)
    e = TranslationEntry
    items = [
        e(1, "res://locale/translation.csv", "line[2].col[1]", "x",
          "T2 alpha bravo", "", "translated"),          # empty translation
        e(2, "res://locale/translation.csv", "мусор", "x",
          "T2 alpha bravo", "RU a", "translated"),      # bad position
        e(3, "res://locale/translation.csv", "line[999].col[1]", "x",
          "T2 alpha bravo", "RU b", "translated"),      # position not found
        e(4, "res://locale/translation.csv", "line[3].col[1]", "x",
          "T9 совсем другое", "RU c", "translated"),     # original not found
        e(5, "res://locale/translation.csv", "line[4].col[1]", "x",
          "T3 echo %s foxtrot", "RU без плейсхолдера", "translated"),
        e(6, "res://locale/translation.csv", "line[2].col[1]", "x",
          "Button_2", "RU d", "translated"),             # identifier
        e(7, "res://locale/translation.csv", "line[2].col[1]", "x",
          "res://icon.png", "RU e", "translated"),       # path
    ]
    stats = parser.apply(td, items)
    got = set(stats["skipped_by"])
    want = {"empty translation", "bad position", "position not found",
            "original not found", "placeholder", "identifier", "path"}
    assert want <= got, (want - got, stats["skipped_by"])
    assert len(got) > 5, "список причин режется молча"
    assert stats["skipped_total"] == len(items), stats
    assert stats["files"] == 0 and stats["strings"] == 0, stats
# поле CSV, «висящее» на следующей строке, — тоже с причиной
with tempfile.TemporaryDirectory() as td:
    pck.pack_files(os.path.join(td, "m.pck"),
                   {"res://locale/t.csv": b'keys,en\nT1,"T2 alpha\nT2,ok val\n'})
    assert parser.scan(td)["skipped:csv:multiline"] == 1
    bad = TranslationEntry(1, "res://locale/t.csv", "line[2].col[1]", "x",
                           "T2 alpha", "RU перевод", "translated")
    stats = parser.apply(td, [bad])
    assert stats["skipped_by"] == {"csv multiline": 1}, stats
    assert stats["files"] == 0, stats
print("   OK")

print("22) Формат v3 (Godot 4.6): dir_offset + file_count ПОСЛЕ seek...")
V3_KW = dict(version=pck.FORMAT_VERSION_46, ver_major=4, ver_minor=6,
             ver_patch=2, pack_flags=pck.PACK_REL_FILEBASE)
with tempfile.TemporaryDirectory() as td:
    path = _pack(td, **V3_KW)
    raw = open(path, "rb").read()
    rh = _raw_header_v3(raw)
    assert (rh["version"], rh["ver_major"], rh["ver_minor"], rh["ver_patch"]) \
        == (3, 4, 6, 2), rh
    assert rh["dir_offset"] == pck.HEADER_SIZE_V3 == 40, rh
    assert rh["file_count"] == 6, rh
    assert pck.header_size(2) == 100 and pck.header_size(3) == 40
    # ГЛАВНОЕ: file_count лежит ПО dir_offset, а не там, где остановился бы
    # v2-разбор. На 96 байте у v3 — хвост записи каталога, НЕ число файлов.
    assert struct.unpack_from("<I", raw, 96)[0] != 6, \
        "каталог v3 не должен читаться на месте file_count из v2"
    header = pck.read_header(path)
    assert header.version == 3 and header.file_count == 6
    assert header.dir_offset == rh["dir_offset"]
    assert header.reserved == [], "у v3 полей reserved[16] НЕТ вообще"
    assert header.file_base == rh["file_base"] and not header.embedded
    entries = pck.read_entries(path, header)
    raw_entries = _raw_entries_v3(raw, rh["file_count"], rh["dir_offset"],
                                  rh["file_base"])
    assert len(entries) == len(raw_entries) == 6
    for got, want in zip(entries, raw_entries):
        assert (got.path, got.ofs, got.size, got.md5, got.flags) == \
            (want["path"], want["ofs"], want["size"], want["md5"],
             want["flags"]), (got, want)
    # и блоб по НЕЗАВИСИМО вычисленному смещению — те же байты
    assert pck.read_blob(path, entries[3]) == bytes(range(256))
    assert pck.verify(path, [e.path for e in entries], {}) == []
print("   OK")

print("23) Round-trip v3: extract/apply, версия формата НЕ меняется...")
with tempfile.TemporaryDirectory() as td:
    path = _pack(td, **V3_KW)
    before = open(path, "rb").read()
    entries = parser.extract(td)
    assert parser.scan(td)["candidates"] == len(entries) == 9
    for i, e in enumerate(entries):
        e.translation = "RU%02d %s" % (i, e.original)
        e.status = "translated"
    stats = parser.apply(td, entries)
    assert stats["files"] == 3 and stats["strings"] == len(entries), stats
    assert not stats["verify_failed"], stats["verify_failed"]
    assert stats["skipped_total"] == 0, stats
    header = pck.read_header(path)
    assert header.version == 3, "версию формата молча улучшать нельзя"
    catalog = pck.read_entries(path, header)
    assert [e.path for e in catalog] == [
        "res://locale/translation.csv", "res://scenes/main.tscn",
        "res://code/main.gd", "res://data/x.bin", "res://data/level.scn",
        "res://code/compiled.gdc"]
    assert pck.read_blob(path, catalog[3]) == bytes(range(256)), "нетронутый"
    csv_out = pck.read_blob(path, catalog[0]).decode("utf-8")
    assert csv_out.startswith("keys,en") and "RU00 T2 alpha bravo" in csv_out
    assert parser.verify(td) == []
    assert parser.restore_original(td)["restored"] >= 1
    assert open(path, "rb").read() == before, "откат обязан вернуть оригинал"
print("   OK")

print("24) Пересборка v3 не ломает dir_offset (в т.ч. каталог в хвосте)...")
with tempfile.TemporaryDirectory() as td:
    path = _pack(td, **V3_KW)
    want_blob = b"keys,en\nT1,RU alpha bravo\n"
    # сперва обычный v3: каталог сразу за заголовком
    header = pck.read_header(path)
    entries = pck.read_entries(path, header)
    pck.write_pck(path, path, header, entries,
                  {"res://locale/translation.csv": want_blob})
    raw = open(path, "rb").read()
    rh = _raw_header_v3(raw)
    assert rh["dir_offset"] == pck.HEADER_SIZE_V3, rh
    assert rh["file_count"] == 6, rh
    want_md5 = hashlib.md5(want_blob).digest()
    assert pck.verify(path, [e.path for e in entries],
                      {"res://locale/translation.csv": want_md5}) == []
    # теперь НАСТОЯЩЕЕ расположение: каталог после всех блобов
    new_dir = _v3_dir_to_end(path)
    header = pck.read_header(path)
    entries = pck.read_entries(path, header)
    assert header.dir_offset == new_dir and len(entries) == 6
    raw = open(path, "rb").read()
    rh = _raw_header_v3(raw)
    assert rh["dir_offset"] == new_dir, rh
    assert [e["path"] for e in _raw_entries_v3(raw, rh["file_count"],
                                               rh["dir_offset"],
                                               rh["file_base"])] == \
        [e.path for e in entries]
    blob2 = "keys,en\nT1,RU второй alpha bravo\n".encode("utf-8")
    pck.write_pck(path, path, header, entries,
                  {"res://locale/translation.csv": blob2})
    raw = open(path, "rb").read()
    rh = _raw_header_v3(raw)
    # после пересборки каталог возвращается сразу за заголовок, и движок
    # после seek(dir_offset + pck_start_pos) попадает именно на него
    assert rh["dir_offset"] == pck.HEADER_SIZE_V3, rh
    assert rh["file_count"] == 6, rh
    assert rh["version"] == 3 and rh["pack_flags"] == pck.PACK_REL_FILEBASE
    rebuilt = pck.read_entries(path, pck.read_header(path))
    assert [e.path for e in rebuilt] == [e.path for e in entries]
    assert pck.read_blob(path, rebuilt[0]) == blob2
    assert pck.verify(path, [e.path for e in entries],
                      {"res://locale/translation.csv":
                       hashlib.md5(blob2).digest()}) == []
print("   OK")

print("25) v3 по смещению (base != 0): file_base складывается с pck_start...")
with tempfile.TemporaryDirectory() as td:
    with tempfile.TemporaryDirectory() as stage:
        tmp = os.path.join(stage, "_base.pck")
        pck.pack_files(tmp, {
            "res://locale/translation.csv": CSV_SRC.encode("utf-8"),
            "res://data/x.bin": bytes(range(256)),
        }, version=pck.FORMAT_VERSION_46, ver_major=4, ver_minor=6)
        exe = pck.embedded_pck(os.path.join(td, "Game.exe"),
                               open(tmp, "rb").read())
    before = open(exe, "rb").read()
    header = pck.read_header(exe)
    assert header.base != 0 and header.embedded, "нужен пакет НЕ с нуля"
    # fap.cpp:303-305 — при v3 pck_start_pos складывается БЕЗУСЛОВНО
    assert header.file_base_abs == header.file_base + header.base
    entries = pck.read_entries(exe, header)
    raw = open(exe, "rb").read()
    rh = _raw_header_v3(raw[header.base:])
    assert rh["dir_offset"] == pck.HEADER_SIZE_V3
    raw_entries = _raw_entries_v3(raw, rh["file_count"], rh["dir_offset"],
                                  rh["file_base"], pck_start=header.base)
    assert len(entries) == len(raw_entries) == 2
    for got, want in zip(entries, raw_entries):
        assert (got.path, got.ofs, got.size, got.md5) == \
            (want["path"], want["ofs"], want["size"], want["md5"])
    # и блобы читаются по абсолютным смещениям — а не по относительным
    assert pck.read_blob(exe, entries[1]) == bytes(range(256))
    assert pck.read_blob(exe, entries[0]) == CSV_SRC.encode("utf-8")
    # пакет по смещению мы переписывать не берёмся
    try:
        pck.write_pck(exe, exe, header, entries,
                      {"res://locale/translation.csv": b"x"})
        raise AssertionError("ожидался отказ на embedded-pck")
    except pck.PckUnsupported:
        pass
    assert open(exe, "rb").read() == before, "exe обязан остаться целым"
print("   OK")

print("26) Флаги v3: REMOVAL/DELTA не переводятся, SPARSE — честный отказ...")
with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, "game.pck")
    pck.pack_files(path, {
        "res://locale/translation.csv": CSV_SRC.encode("utf-8"),
        "res://data/x.bin": bytes(range(256)),
        "res://gone.tscn": None,                       # удалён: блоба нет
        "res://patch.gdc": b"GDSC\x01" + bytes(12),   # дельта-патч
    }, version=pck.FORMAT_VERSION_46, ver_major=4, ver_minor=6,
        entry_flags={"res://patch.gdc": pck.PACK_FILE_DELTA})
    counts = parser.scan(td)
    assert counts.get("unsupported:removal") == 1, counts
    assert counts.get("unsupported:delta") == 1, counts
    # 3 строки из CSV_SRC; удалённый .tscn и дельта-.gdc НЕ в счёт
    assert counts["candidates"] == 3, counts
    entries = parser.extract(td)
    assert {e.file for e in entries} == {"res://locale/translation.csv"}, \
        "удалённый и дельта-файл переводить нельзя"
    header = pck.read_header(path)
    catalog = pck.read_entries(path, header)
    assert any(e.removal and e.size == 0 for e in catalog)
    assert any(e.delta and e.has_blob for e in catalog)
    for e in catalog:
        if e.removal:
            try:
                pck.read_blob(path, e)
                raise AssertionError("ожидался отказ на удалённом файле")
            except pck.PckUnsupported as exc:
                assert exc.reason == "unsupported:removal"
        if e.delta:
            try:
                pck.read_blob(path, e)
                raise AssertionError("ожидался отказ на дельта-файле")
            except pck.PckUnsupported as exc:
                assert exc.reason == "unsupported:delta"
    # переписать содержимое таких записей мы не берёмся — с причиной
    for rel, reason in (("res://gone.tscn", "unsupported:removal"),
                        ("res://patch.gdc", "unsupported:delta")):
        try:
            pck.write_pck(path, path, header, catalog, {rel: b"RU"})
            raise AssertionError("ожидался отказ для " + rel)
        except pck.PckUnsupported as exc:
            assert exc.reason == reason, (rel, exc.reason)
    # apply: обе записи получают пропуск с причиной, обычный csv — перевод
    items = list(entries)
    for i, e in enumerate(items):
        e.translation = "RU%02d %s" % (i, e.original)
        e.status = "translated"
    for i, rel in enumerate(("res://gone.tscn", "res://patch.gdc")):
        items.append(TranslationEntry(
            9000 + i, rel, "line[1].str[1]", "x", "T1 alpha bravo",
            "RU перевод", "translated"))
    stats = parser.apply(td, items)
    assert stats.get("skipped_by") == {"unsupported:removal": 1,
                                       "unsupported:delta": 1}, stats
    assert stats["files"] == 1, stats
    assert not stats["verify_failed"], stats["verify_failed"]
    # флаги пережили пересборку
    rebuilt = pck.read_entries(path, pck.read_header(path))
    assert [e.path for e in rebuilt] == [e.path for e in catalog]
    assert [e.flags for e in rebuilt] == [e.flags for e in catalog]
    assert any(e.removal for e in rebuilt) and any(e.delta for e in rebuilt)
    assert pck.verify(path, [e.path for e in catalog], {}) == []
# PACK_SPARSE_BUNDLE — блобы вне пакета, отказ целиком
with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, "game.pck")
    pck.pack_files(path, {"res://locale/translation.csv": CSV_SRC.encode()},
                   version=pck.FORMAT_VERSION_46, ver_major=4, ver_minor=6,
                   pack_flags=pck.PACK_SPARSE_BUNDLE)
    before = open(path, "rb").read()
    try:
        pck.read_header(path)
        raise AssertionError("ожидался отказ на sparse")
    except pck.PckUnsupported as exc:
        assert exc.reason == "unsupported:sparse", exc.reason
    assert parser.scan(td)["unsupported:sparse"] == 1
    assert parser.extract(td) == []
    reasons = []
    stats = parser.apply(
        td, [TranslationEntry(1, "res://locale/translation.csv",
                              "line[2].col[1]", "x", "T2 alpha bravo",
                              "RU перевод", "translated")],
        on_skip=lambda e, r: reasons.append(r))
    assert stats["strings"] == 0 and stats["files"] == 0, stats
    assert reasons == ["unsupported:sparse"], reasons
    assert not os.path.exists(os.path.join(td, "backup")), "бэкап не нужен"
    assert open(path, "rb").read() == before, "пакет не тронут"
print("   OK")

print("27) Регрессия v2: версия 2 остаётся 2; check_version(3) принимается...")
assert pck.FORMAT_VERSION_3X == 1 and pck.FORMAT_VERSION_4X == 2
assert pck.FORMAT_VERSION_46 == 3
assert pck.SUPPORTED_VERSIONS == (2, 3)
assert pck.HEADER_SIZE == 100 and pck.HEADER_SIZE_V3 == 40
pck.check_version(2, 4, 0)
pck.check_version(2, 4, 6)
pck.check_version(3, 4, 0)
pck.check_version(3, 4, 6)
for bad in ((1, 3, 5), (2, 3, 5), (2, 5, 0), (3, 5, 0), (3, 4, 7), (4, 5, 0),
(99, 4, 0)):
    try:
        pck.check_version(*bad)
        raise AssertionError("ожидался PckVersion для %r" % (bad,))
    except pck.PckVersion as exc:
        assert exc.version == bad[0], bad
with tempfile.TemporaryDirectory() as td:
    path = _pack(td, version=2, ver_major=4, ver_minor=2, pack_flags=0)
    header = pck.read_header(path)
    entries = pck.read_entries(path, header)
    assert header.version == 2 and header.dir_offset == 0
    assert header.reserved == [0] * 16
    want = b"keys,en\nT1,RU v2 alpha bravo\n"
    pck.write_pck(path, path, header, entries,
                  {"res://locale/translation.csv": want})
    header2 = pck.read_header(path)
    assert header2.version == 2, "v2 обязан остаться v2"
    assert header2.dir_offset == 0 and header2.reserved == [0] * 16
    rebuilt = pck.read_entries(path, header2)
    assert [e.path for e in rebuilt] == [e.path for e in entries]
    assert pck.read_blob(path, rebuilt[0]) == want
    assert pck.verify(path, [e.path for e in entries],
                      {"res://locale/translation.csv":
                       hashlib.md5(want).digest()}) == []
print("   OK")

print("28) Пути с NUL-выравниванием: обрезаем, как это делает движок...")
with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, "game.pck")
    pck.pack_files(path, {
        "res://locale/translation.csv": CSV_SRC.encode("utf-8"),
        "res://data/padded.tscn\x00\x00\x00": TSCN_SRC.encode("utf-8"),
    }, **V3_KW)
    header = pck.read_header(path)
    entries = pck.read_entries(path, header)
    paths = [e.path for e in entries]
    assert paths == ["res://locale/translation.csv", "res://data/padded.tscn"], \
        paths
    assert "\x00" not in paths[1]
    assert not any(chr(0) in p for p in paths)
    assert pck.read_blob(path, entries[1]) == TSCN_SRC.encode("utf-8")
    # пересборка обязана записать путь БЕЗ нулей — иначе движок найдёт
    # другой ресурс, чем мы перевели
    pck.write_pck(path, path, header, entries,
                  {"res://locale/translation.csv":
                   "keys,en\nT1,RU padded\n".encode("utf-8")})
    raw = open(path, "rb").read()
    rh = _raw_header_v3(raw)
    rebuilt = pck.read_entries(path, pck.read_header(path))
    assert [e.path for e in rebuilt] == paths, [e.path for e in rebuilt]
    assert rh["file_count"] == 2 and rh["dir_offset"] == pck.HEADER_SIZE_V3
    # ни одного NUL в записанных путях
    with open(path, "rb") as f:
        f.seek(rh["dir_offset"] + 4)
        for _e in rebuilt:
            sl = struct.unpack("<I", f.read(4))[0]
            raw_path = f.read(sl)
            f.read(pck.ENTRY_FIXED)      # ofs/size/md5/flags — не путь
            assert b"\x00" not in raw_path, "NUL попал в записанный путь"
            assert len(raw_path) == sl
    assert pck.verify(path, paths, {}) == []
print("   OK")

print()
print("ВСЕ ТЕСТЫ GODOT ПРОШЛИ")

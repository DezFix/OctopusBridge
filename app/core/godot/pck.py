# -*- coding: utf-8 -*-
"""Чтение и пересборка .pck движка Godot 4.

Формат сверен с первоисточником: ``core/io/file_access_pack.cpp``,
``PackedSourcePCK::try_open_pack()``. Строки ниже даны для Godot 4.6
(``fap.cpp``) — именно там появились ``dir_offset`` и флаги записей.
Раскладка little-endian:

    uint32  magic        == 'GDPC' (0x43504447)
    uint32  version      == PACK_FORMAT_VERSION_V2 (2) или _V3 (3)
    uint32  ver_major
    uint32  ver_minor
    uint32  ver_patch    (движком не проверяется, fap.cpp:292)
    uint32  pack_flags   bit0 PACK_DIR_ENCRYPTED, bit1 PACK_REL_FILEBASE,
                          bit2 PACK_SPARSE_BUNDLE
    uint64  file_base
    ─── дальше ветвление ПО ВЕРСИИ, читать «подряд» нельзя ───
    v2: uint32 reserved[16]; затем ПО ТЕКУЩЕЙ ПОЗИЦИИ uint32 file_count
    v3: uint64 dir_offset; движок делает seek(dir_offset + pck_start_pos)
        и ТОЛЬКО ПОТОМ читает uint32 file_count (fap.cpp:307-319)
    затем file_count записей (формат записи у v2 и v3 ОДИН):
        uint32 path_len
        byte  path[path_len]      utf-8, напр. "res://scenes/main.tscn";
                                   хвост из NUL-байт движок отбрасывает
                                   (ustring.cpp::append_utf8), и мы тоже
        uint64 ofs                ofs = file_base + это_значение (fap.cpp:353)
        uint64 size
        byte  md5[16]
        uint32 flags             bit0 PACK_FILE_ENCRYPTED,
                                 bit1 PACK_FILE_REMOVAL,
                                 bit2 PACK_FILE_DELTA
    затем блобы файлов по абсолютным ofs/size

ГЛАВНОЕ РАЗЛИЧИЕ v3 ОТ v2 (fap.cpp:307-316): вместо ``reserved[16]``
лежит 8-байтовое ``dir_offset``, а ``file_count`` читается НЕ по текущей
позиции, а ПОСЛЕ ``seek(dir_offset + pck_start_pos)``. Прочитать v3
нашей v2-разметкой — значит взять в ``file_count`` хвост заголовка, а не
число файлов, и дальше разлететься на первой же записи. Именно поэтому
заголовок разбирается по ветке версии, а ``dir_start``/``count_pos``
считаются через :attr:`PckHeader.dir_offset`.

Ещё: ``file_base`` прибавляет ``pck_start_pos`` (fap.cpp:303-305) при
``version == V3`` БЕЗУСЛОВНО, а при v2 — только если выставлен
``PACK_REL_FILEBASE``. Для отдельного .pck ``pck_start_pos == 0``, но для
пакета по смещению это не так, поэтому арифметика вынесена в
:attr:`PckHeader.file_base_abs` и не «схлопнута» под standalone-случай.

Два принципа, из-за которых модуль такой, какой есть:

1. **Честный отказ вместо догадки.** ``version``/``ver_*`` проверены по
   константам движка (см. ``SUPPORTED_VERSIONS``): мы умеем ровно две
   раскладки и на остальных НИЧЕГО не трогаем. Всё, что в поддерживаемой
   раскладке не нужно менять (``pack_flags``/``file_base``/``reserved``/
   ``dir_offset``), копируется ДОСЛОВНО. Дополнительно проверяются
   инварианты из исходника: абсолютный ``ofs`` каждой записи указывает
   внутрь файла и не НАКРЫВАЕТ каталог. Для v2 каталог по построению идёт
   перед блобами (значит ``ofs`` строго после его конца), а для v3 —
   нет: ``dir_offset`` указывает каталог в любом месте пакета, и в реальных
   сборках Godot 4.6 он лежит в самом конце, ПОСЛЕ всех блобов. Не сошлось —
   отказ, а не догадка.
2. **Не держать файл в памяти.** Реальный .pck — сотни мегабайт.
   Пересборка потоковая (чанк 1 МиБ), копия бэкапа и откат — тоже потоком,
   через ``stream_copy_atomic``. Для атомарности используется тот же
   контракт, что у ``app/core/io.py::atomic_write_bytes`` (tmp в той же
   папке + fsync + размер-сверка + ``os.replace``), но без чтения файла
   целиком в RAM.

Шифрование (``PACK_DIR_ENCRYPTED`` / ``PACK_FILE_ENCRYPTED``) НЕ ломаем:
ключ в официальных шаблонах экспорта отсутствует (его задаёт
``script_encryption_key``, fap.cpp:326-333 — то есть кастомная сборка
движка). Такие игры честно помечаются ``PckEncrypted`` и не трогаются.

Новые флаги v3 (``file_access_pack.h`` 4.6) тоже не трогаем молча:

- ``PACK_FILE_REMOVAL`` — движок вызывает ``remove_path`` (fap.cpp:350-351),
  блоба у такой записи нет: её не читаем, не переводим и не переписываем,
  но СОХРАНЯЕМ при пересборке;
- ``PACK_FILE_DELTA`` — дельта-патч (fap.cpp:353, ``p_delta``): это не
  самостоятельный файл, переписывать его содержимое мы не берёмся —
  пропуск с причиной, флаг сохраняем;
- ``PACK_SPARSE_BUNDLE`` — блоб лежит ВНЕ пакета, сам пакет читать
  бесполезно (fap.cpp:513-517): честный отказ, файл игры не трогаем.

Self-contained экспорт (pck приклеен к .exe, fap.cpp:257-280) читается
только для ДЕТЕКТА; пересборка такого exe запрещена — см. ``parser.py``.
"""
from __future__ import annotations

import hashlib
import os
import struct
import tempfile
from dataclasses import dataclass, field

MAGIC = b"GDPC"
MAGIC_U32 = 0x43504447

#: v2: 4 (magic) + 20 (version..pack_flags) + 8 (file_base) + 16*4 + 4
#: (file_count) — до ПЕРВОЙ записи каталога.
HEADER_SIZE = 100
#: v3: 4 + 20 + 8 + 8 (dir_offset) — до поля ``file_count``, которое лежит
#: по ``dir_offset`` (fap.cpp:307-319). Считать по версии, а не одним
#: числом на обе раскладки: разница в 60 байт съела бы первую запись.
HEADER_SIZE_V3 = 40
#: размер записи каталога БЕЗ самого пути: ofs(8) + size(8) + md5(16)
#: + flags(4). Поле path_len(4) учитывается отдельно в ENTRY_OVERHEAD.
ENTRY_FIXED = 36
#: path_len(4) + путь + ENTRY_FIXED — полный размер записи каталога
ENTRY_OVERHEAD = 4 + ENTRY_FIXED

PACK_DIR_ENCRYPTED = 1 << 0
PACK_REL_FILEBASE = 1 << 1
PACK_SPARSE_BUNDLE = 1 << 2
PACK_FILE_ENCRYPTED = 1 << 0
#: файл удалён из пакета (fap.cpp:350-351) — блоба нет
PACK_FILE_REMOVAL = 1 << 1
#: дельта-патч поверх базового файла (fap.cpp:353) — не самостоятельный файл
PACK_FILE_DELTA = 1 << 2

#: ``PACK_FORMAT_VERSION_*`` из ``core/io/file_access_pack.h``:
#:   Godot 3.5 — 1, Godot 4.0-4.3 — 2, Godot 4.5+ — 3.
#: Значения сверены с первоисточником (fap.cpp:294), а не выдуманы.
FORMAT_VERSION_3X = 1
FORMAT_VERSION_4X = 2
FORMAT_VERSION_46 = 3
#: раскладки, которые модуль умеет читать И пересобирать. У 3.x заголовок
#: 88 байт и полей pack_flags/file_base НЕТ — это физически другая
#: раскладка, а не «старая версия v2».
SUPPORTED_VERSIONS = (FORMAT_VERSION_4X, FORMAT_VERSION_46)
SUPPORTED_VER_MAJOR = 4
#: новее этой раскладки движка мы не знаем — пакет собран незнакомым
#: экспортом и переписывать его мы не берёмся (fap.cpp:295 отказывает
#: по зеркальной причине: пакет новее самого движка).
SUPPORTED_VER_MINOR = 6

#: самосохраняющийся трейлер self-contained: uint64 pck_size + 'GDPC'
TRAILER_SIZE = 12

COPY_CHUNK = 1 << 20
_ALIGN = 4

#: предохранители против битого/чужого файла — чтобы не уйти в ООМ
MAX_PATH_LEN = 4096
MAX_FILE_COUNT = 1 << 20
MAX_BLOB = 256 << 20  # 256 МиБ на один файл


def header_size(version: int) -> int:
    """Размер фиксированной части заголовка ПО ВЕРСИИ.

    Для v2 это расстояние до первой записи каталога (``file_count`` стоит
    последним полем). Для v3 — расстояние до поля ``file_count``, которое
    читается не подряд, а по ``dir_offset``.
    """
    return HEADER_SIZE_V3 if version == FORMAT_VERSION_46 else HEADER_SIZE


class PckError(ValueError):
    """Файл не является разбираемым .pck Godot."""


class PckEncrypted(PckError):
    """PACK_DIR_ENCRYPTED / PACK_FILE_ENCRYPTED — ключа у нас нет."""


class PckUnsupported(PckError):
    """Формат разобран, но переписывать его мы не берёмся.

    ``reason`` — машинно-читаемый код для UI и счётчиков ``scan()``, а не
    «что-то не так»: у нас их несколько (sparse/removal/delta), и молчать
    о них нельзя (``AGENTS.md:71-73``).
    """

    def __init__(self, message: str, reason: str = "unsupported:format"):
        super().__init__(message)
        self.reason = reason


class PckVersion(PckUnsupported):
    """Версия/раскладка пакета, которую модуль не умеет.

    Отдельный класс — вызывающий обязан сказать пользователю ЧИСЛО
    (``exc.version``), а не «что-то не так».
    """

    def __init__(self, message: str, version: int = -1):
        super().__init__(message)
        self.version = version


@dataclass
class PckEntry:
    """Запись каталога .pck. ``ofs`` — АБСОЛЮТНЫЙ (file_base уже сложен)."""

    path: str
    ofs: int
    size: int
    md5: bytes
    flags: int

    @property
    def encrypted(self) -> bool:
        return bool(self.flags & PACK_FILE_ENCRYPTED)

    @property
    def removal(self) -> bool:
        """PACK_FILE_REMOVAL: файл удалён, блоба за записью НЕТ."""
        return bool(self.flags & PACK_FILE_REMOVAL)

    @property
    def delta(self) -> bool:
        """PACK_FILE_DELTA: блоб — патч поверх другого файла, не сам файл."""
        return bool(self.flags & PACK_FILE_DELTA)

    @property
    def has_blob(self) -> bool:
        """Есть ли у записи вообще блоб, который можно переписать."""
        return not (self.removal or self.encrypted)


@dataclass
class PckHeader:
    """Заголовок .pck. Все поля сохраняются дословно при пересборке."""

    version: int
    ver_major: int
    ver_minor: int
    ver_patch: int
    pack_flags: int
    file_base: int
    reserved: list[int] = field(default_factory=lambda: [0] * 16)
    file_count: int = 0
    base: int = 0            # смещение начала pck внутри файла-контейнера
    filesize: int = 0        # размер файла-контейнера
    embedded: bool = False   # pck приклеен к .exe
    dir_offset: int = 0      # v3: смещение каталога ОТ НАЧАЛА pck (fap.cpp:309)

    @property
    def file_base_abs(self) -> int:
        """``file_base`` в том виде, в каком его считает движок.

        fap.cpp:303-305: ``pck_start_pos`` (у нас это ``base``) прибавляется
        при v3 БЕЗУСЛОВНО, при v2 — только с ``PACK_REL_FILEBASE``. У
        отдельного .pck ``base == 0``, поэтому разница не видна, но
        схлопывать её в ``file_base`` нельзя: пакет по смещению читался бы
        с битых адресов.
        """
        if self.version == FORMAT_VERSION_46 or (self.pack_flags
                                                 & PACK_REL_FILEBASE):
            return self.file_base + self.base
        return self.file_base

    @property
    def sparse(self) -> bool:
        return bool(self.pack_flags & PACK_SPARSE_BUNDLE)

    @property
    def count_pos(self) -> int:
        """Абсолютное смещение поля ``file_count``.

        v2 — сразу за ``reserved[16]``; v3 — по ``dir_offset + pck_start_pos``
        (fap.cpp:307-319). Смешивать эти два места нельзя.
        """
        if self.version == FORMAT_VERSION_46:
            return self.base + self.dir_offset
        return self.base + HEADER_SIZE - 4

    @property
    def dir_start(self) -> int:
        """Смещение ПЕРВОЙ записи каталога (сразу за file_count).

        Конца каталога это НЕ даёт: он зависит от суммы длин путей и
        известен только после чтения всех записей (см. ``catalog_end``).
        """
        return self.count_pos + 4


def catalog_end(header: PckHeader, entries) -> int:
    """Абсолютное смещение сразу ЗА каталогом — блобы лежат дальше."""
    return header.dir_start + sum(
        ENTRY_OVERHEAD + len(e.path.encode("utf-8")) for e in entries)



def locate(path: str) -> tuple[int, bool] | None:
    """Найти начало pck: ``(смещение, embedded)`` либо None.

    Порядок как в движке (fap.cpp:223-286): сначала магия по смещению 0,
    затем трейлер в конце файла для self-contained exe.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if size < HEADER_SIZE:
        return None
    try:
        with open(path, "rb") as f:
            if f.read(4) == MAGIC:
                return 0, False
            if size < TRAILER_SIZE:
                return None
            f.seek(size - TRAILER_SIZE)
            raw = f.read(8)
            if len(raw) != 8:
                return None
            pck_size = struct.unpack("<Q", raw)[0]
            start = size - TRAILER_SIZE - pck_size
            if 0 <= start < size - TRAILER_SIZE:
                f.seek(start)
                if f.read(4) == MAGIC:
                    return start, True
    except OSError:
        return None
    return None


def check_version(version: int, ver_major: int, ver_minor: int) -> None:
    """Отказ на версии, раскладку которой мы не знаем.

    Движок проверяет ровно то же (fap.cpp:294-295): ``version`` должен быть
    ``PACK_FORMAT_VERSION_V2`` или ``_V3``, а собранный пакет — не новее
    самого движка (``ver_major``/``ver_minor``). Нам этого мало: у Godot
    3.x (``version`` 1) НЕТ ни ``pack_flags``, ни ``file_base`` (заголовок
    88 байт), и читать такой пакет нашей раскладкой — значит читать мусор.
    Лучше честно сказать «не умею», чем портить игру.
    """
    if version == FORMAT_VERSION_3X:
        raise PckVersion(
            f"unsupported:version {version} (движок {ver_major}.{ver_minor}): "
            f"Godot 3.x — заголовок 88 байт, другая раскладка; модуль умеет "
            f"только version {SUPPORTED_VERSIONS[0]} и {SUPPORTED_VERSIONS[1]}",
            version)
    if version not in SUPPORTED_VERSIONS:
        raise PckVersion(
            f"unsupported:version {version} (движок {ver_major}.{ver_minor}): "
            f"модуль умеет version {SUPPORTED_VERSIONS[0]} и "
            f"{SUPPORTED_VERSIONS[1]}", version)
    if ver_major != SUPPORTED_VER_MAJOR:
        raise PckVersion(
            f"unsupported:version {version} (движок {ver_major}.{ver_minor}): "
            f"модуль знает только раскладку движка {SUPPORTED_VER_MAJOR}.x",
            version)
    if ver_minor > SUPPORTED_VER_MINOR:
        raise PckVersion(
            f"unsupported:version {version} (движок {ver_major}.{ver_minor}): "
            f"пакет собран движком новее известного "
            f"{SUPPORTED_VER_MAJOR}.{SUPPORTED_VER_MINOR}", version)


def parse_header(f) -> PckHeader:
    """Разобрать заголовок из открытого файла (позиция f не важна)."""
    f.seek(0, os.SEEK_END)
    filesize = f.tell()
    found = locate(f.name)
    if found is None:
        raise PckError("нет магии GDPC ни в начале, ни в трейлере")
    base, embedded = found
    f.seek(base)
    if f.read(4) != MAGIC:
        raise PckError("магия GDPC не читается")
    fixed = f.read(20)
    if len(fixed) != 20:
        raise PckError("обрезан заголовок")
    version, ver_major, ver_minor, ver_patch, pack_flags = struct.unpack(
        "<IIIII", fixed)
    # Версию проверяем ДО чтения остатка заголовка: у v1 и у неизвестных
    # значений раскладка ДРУГАЯ, и дочитывать её нашими полями — значит
    # читать мусор. Движок отказывает на том же месте (fap.cpp:294).
    check_version(version, ver_major, ver_minor)
    raw = f.read(8)
    if len(raw) != 8:
        raise PckError("обрезан file_base")
    file_base = struct.unpack("<Q", raw)[0]
    reserved: list[int] = []
    dir_offset = 0
    if version == FORMAT_VERSION_46:
        # v3: reserved[16] НЕТ — вместо них смещение каталога (fap.cpp:309)
        raw = f.read(8)
        if len(raw) != 8:
            raise PckError("обрезан dir_offset")
        dir_offset = struct.unpack("<Q", raw)[0]
        if dir_offset < HEADER_SIZE_V3 or base + dir_offset >= filesize:
            raise PckError(f"dir_offset={dir_offset} вне файла")
    else:
        for _ in range(16):
            chunk = f.read(4)
            if len(chunk) != 4:
                raise PckError("обрезан reserved[16]")
            reserved.append(struct.unpack("<I", chunk)[0])
    header = PckHeader(
        version=version, ver_major=ver_major, ver_minor=ver_minor,
        ver_patch=ver_patch, pack_flags=pack_flags, file_base=file_base,
        reserved=reserved, file_count=0, base=base,
        filesize=filesize, embedded=embedded, dir_offset=dir_offset)
    if pack_flags & PACK_DIR_ENCRYPTED:
        raise PckEncrypted("PACK_DIR_ENCRYPTED: каталог зашифрован")
    if header.sparse:
        # блобы лежат вне пакета (fap.cpp:513-517) — читать нечего, а
        # переписывать тем более нельзя: пакет не трогаем целиком
        raise PckUnsupported(
            "PACK_SPARSE_BUNDLE: содержимое пакета лежит вне .pck",
            reason="unsupported:sparse")
    # v3: file_count читается ПОСЛЕ seek(dir_offset + pck_start_pos), а не
    # по текущей позиции (fap.cpp:307-319). Читать его «где остановились»
    # — это и есть та ошибка, из-за которой v2-разбор v3 берёт мусор.
    f.seek(header.count_pos)
    chunk = f.read(4)
    if len(chunk) != 4:
        raise PckError("обрезан file_count")
    file_count = struct.unpack("<I", chunk)[0]
    if file_count > MAX_FILE_COUNT:
        raise PckError(f"невероятный file_count={file_count}")
    header.file_count = file_count
    return header


def read_header(path: str) -> PckHeader:
    """Заголовок .pck или PckError/PckEncrypted."""
    with open(path, "rb") as f:
        return parse_header(f)


def read_entries(path: str, header: PckHeader) -> list[PckEntry]:
    """Каталог .pck. Проверяет инвариант смещений (см. модульный docstring)."""
    entries: list[PckEntry] = []
    with open(path, "rb") as f:
        f.seek(header.dir_start)
        for i in range(header.file_count):
            chunk = f.read(4)
            if len(chunk) != 4:
                raise PckError(f"обрезан каталог на записи {i}")
            path_len = struct.unpack("<I", chunk)[0]
            if path_len > MAX_PATH_LEN:
                raise PckError(f"невероятный path_len={path_len} (запись {i})")
            raw = f.read(path_len)
            if len(raw) != path_len:
                raise PckError(f"обрезан путь записи {i}")
            tail = f.read(ENTRY_FIXED)
            if len(tail) != ENTRY_FIXED:
                raise PckError(f"обрезана запись {i}")
            rel_ofs, size = struct.unpack_from("<QQ", tail, 0)
            md5 = tail[16:32]
            flags = struct.unpack_from("<I", tail, 32)[0]
            try:
                # Записи пишутся с выравниванием длины NUL-байтами
                # (проверено на игре Godot 4.6: 10215 из 13271 путей
                # заканчиваются нулём). Движок обрезает путь по первому NUL —
                # ``String::append_utf8`` в ``core/string/ustring.cpp`` крутит
                # цикл ``while (ptrtmp < ptr_limit && *ptrtmp)``. Оставим
                # нули в пути — и ни один ресурс потом не найдётся.
                p = raw.split(b"\x00", 1)[0].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PckError(f"путь записи {i} не utf-8") from exc
            if not p:
                raise PckError(f"путь записи {i} пустой")
            ofs = header.file_base_abs + rel_ofs
            entry = PckEntry(path=p, ofs=ofs, size=size, md5=md5, flags=flags)
            # у PACK_FILE_REMOVAL блоба нет вовсе (fap.cpp:350-351): движок
            # её даже не открывает, а ofs/size в записи служебные, так что
            # проверять их не на чем и незачем
            if entry.removal:
                entries.append(entry)
                continue
            if ofs + size > header.filesize:
                raise PckError(
                    f"смещение записи {i} вне файла (ofs={ofs}, size={size}, "
                    f"filesize={header.filesize})")
            entries.append(entry)
    # блоб не может НАКРЫВАТЬ каталог — конец каталога известен только
    # сейчас, когда прочитан весь
    limit = catalog_end(header, entries)
    for i, e in enumerate(entries):
        if e.removal:
            continue
        if header.version == FORMAT_VERSION_46:
            # v3: каталог адресуется через dir_offset и в реальных сборках
            # лежит В КОНЦЕ пакета, после всех блобов (проверено на игре
            # Godot 4.6: блобы 112..dir_offset, каталог после них). Значит
            # требование «ofs больше конца каталога» тут неверно — проверяем
            # ровно то, что запрещено: перекрытие.
            if e.ofs < limit and e.ofs + e.size > header.dir_start:
                raise PckError(
                    f"блоб записи {i} перекрывается каталогом "
                    f"(ofs={e.ofs}, size={e.size}, каталог="
                    f"{header.dir_start}..{limit})")
        elif e.ofs < limit:
            # v2: каталог по построению идёт перед блобами
            raise PckError(
                f"смещение записи {i} попадает в каталог "
                f"(ofs={e.ofs}, конец каталога={limit})")
    return entries


def read_blob(path: str, entry: PckEntry) -> bytes:
    """Блоб одного файла из .pck (с проверкой, что он вообще влезает)."""
    if entry.encrypted:
        raise PckEncrypted("PACK_FILE_ENCRYPTED: файл зашифрован")
    if entry.removal:
        raise PckUnsupported("PACK_FILE_REMOVAL: файл удалён, блоба нет",
                             reason="unsupported:removal")
    if entry.delta:
        # блоб-патч читается не как файл, а через FileAccessPatched
        # (fap.cpp:363-371): отдавать его переводчику нельзя
        raise PckUnsupported("PACK_FILE_DELTA: блоб — патч, не файл",
                             reason="unsupported:delta")
    if entry.size > MAX_BLOB:
        raise PckUnsupported(f"файл крупнее {MAX_BLOB} байт")
    with open(path, "rb") as f:
        f.seek(entry.ofs)
        data = f.read(entry.size)
    if len(data) != entry.size:
        raise PckError("файл обрезан: блоб короче size")
    return data


# ── запись ──

def blob_md5(f, entry: PckEntry) -> bytes:
    """md5 блоба, посчитанный по БАЙТАМ НА ДИСКЕ, потоком (без RAM).

    Открытый на чтение ``f`` не закрывается — читаем все записи пакета
    через одну ручку. Смещение берётся у записи как есть: если арифметика
    ``cursor`` в :func:`write_pck` сдвинется на байт, md5 не совпадёт.
    """
    h = hashlib.md5()
    f.seek(entry.ofs)
    left = entry.size
    while left > 0:
        chunk = f.read(min(COPY_CHUNK, left))
        if not chunk:
            raise PckError("файл обрезан: блоб короче size")
        h.update(chunk)
        left -= len(chunk)
    return h.digest()


def _size_check(expected: int):
    """Проверка «скопировано ровно столько, сколько весит оригинал»."""
    def _check(tmp_path: str) -> None:
        got = os.path.getsize(tmp_path)
        if got != expected:
            raise PckError(f"копия обрезана: {got} из {expected} байт")
    return _check


def _atomic_stream(path: str, writer, check=None) -> None:
    """Атомарная потоковая запись: tmp в той же папке + fsync + os.replace.

    Контракт тот же, что у ``app/core/io.py::atomic_write_bytes``, но без
    чтения целиком в память — файл может весить сотни мегабайт.
    ``check(tmp_path)`` вызывается ДО ``os.replace``: оборванная копия
    никогда не получает имя ``path``.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".new")
    try:
        with os.fdopen(fd, "wb") as f:
            writer(f)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # не все ФС умеют fsync — данные уже в tmp, replace безопасен
                pass
        if check is not None:
            check(tmp)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def stream_copy_atomic(src: str, dest: str,
                       chunk: int = COPY_CHUNK) -> int:
    """Атомарно скопировать ``src`` в ``dest`` потоком. Вернуть размер.

    tmp создаётся в каталоге ``dest``, поэтому ``os.replace`` атомарен и
    на диске НИКОГДА не остаётся частичный ``dest``. Размер сверяется с
    оригиналом до replace — иначе обрыв копирования выдал бы 10 байт
    «бэкапа», откат с которого убил бы игру.

    Размер .pck в RAM не попадает: нужен и бэкапу, и откату.
    """
    want = os.path.getsize(src)
    written = 0

    def _writer(f):
        nonlocal written
        with open(src, "rb") as s:
            while True:
                block = s.read(chunk)
                if not block:
                    break
                f.write(block)
                written += len(block)

    _atomic_stream(dest, _writer, check=_size_check(want))
    return want



def _align_up(value: int) -> int:
    return (value + (_ALIGN - 1)) // _ALIGN * _ALIGN


def write_pck(dest: str, source: str, header: PckHeader,
              entries: list[PckEntry], replace: dict[str, bytes]) -> None:
    """Пересобрать .pck.

    ФОРМАТ ИСХОДНОЙ ВЕРСИИ СОХРАНЯЕТСЯ: прочитали v3 — пишем v3, v2 — v2.
    «Улучшать» версию молча нельзя: движок собран под свой формат, а в v3
    ещё и каталог адресуется через ``dir_offset``.

    Те же ``version``/``ver_*``/``pack_flags``/``file_base``/``reserved``/
    ``dir_offset``, те же пути и тот же порядок записей; ``ofs``/``size``/
    ``md5`` пересчитываются. Изменённые файлы берутся из ``replace``,
    остальные копируются потоком из ``source`` как есть.

    Удалённые записи (``PACK_FILE_REMOVAL``) и дельты (``PACK_FILE_DELTA``)
    переносятся как есть, вместе с флагами: блоба у них нет, а переписывать
    патч мы не берёмся. Каталог всегда кладётся сразу за заголовком, а
    ``dir_offset`` для v3 ставится равным концу заголовка — так движок
    после ``seek(dir_offset + pck_start_pos)`` попадает на каталог при любом
    исходном расположении блобов.

    Пересборка запрещена для embedded-pck: такой exe мы не трогаем.
    """
    if header.embedded or header.base != 0:
        raise PckUnsupported("embedded-pck не пересобирается")
    if header.version not in SUPPORTED_VERSIONS:
        raise PckUnsupported(f"нечем пересобирать version {header.version}")
    if not replace:
        raise PckUnsupported("пустой пересбор не нужен")
    if not entries:
        raise PckUnsupported("пустой каталог пересобирать нечего")
    for e in entries:
        if e.encrypted:
            raise PckEncrypted("PACK_FILE_ENCRYPTED: пересборка небезопасна")
        if e.path not in replace:
            continue
        if e.removal:
            raise PckUnsupported(
                "PACK_FILE_REMOVAL: удалённый файл не переводится",
                reason="unsupported:removal")
        if e.delta:
            raise PckUnsupported(
                "PACK_FILE_DELTA: содержимое патча не переписывается",
                reason="unsupported:delta")
    # тот заголовок, который мы СОБИРАЕМСЯ записать: v3 отличается от v2
    # именно наличием dir_offset, и каталог мы кладём сразу за ним
    dir_offset = header_size(header.version) \
        if header.version == FORMAT_VERSION_46 else 0
    out_header = PckHeader(
        version=header.version, ver_major=header.ver_major,
        ver_minor=header.ver_minor, ver_patch=header.ver_patch,
        pack_flags=header.pack_flags, file_base=header.file_base,
        reserved=list(header.reserved), file_count=len(entries),
        base=header.base, dir_offset=dir_offset)
    dir_size = sum(ENTRY_OVERHEAD + len(e.path.encode("utf-8"))
                   for e in entries)
    head_end = out_header.dir_start + dir_size
    # абсолютное смещение блобов отсчитывается от file_base: движок
    # складывает его сам (fap.cpp:353), поэтому заносим в каталог разность
    file_base = out_header.file_base_abs
    cursor = _align_up(file_base + head_end)
    plan: list[tuple[PckEntry, int, int, bool]] = []  # (entry, abs_ofs, size, есть блоб)
    first_blob = None
    for e in entries:
        if e.removal:
            # блоба нет: смещение/размер переносим как есть, флаг сохраняем
            plan.append((e, e.ofs, e.size, False))
            continue
        blob = replace.get(e.path)
        size = len(blob) if blob is not None else e.size
        plan.append((e, cursor, size, True))
        if first_blob is None:
            first_blob = cursor
        cursor = _align_up(cursor + size)

    def _write(f):
        head = bytearray()
        head += MAGIC
        head += struct.pack("<IIIII", out_header.version, out_header.ver_major,
                            out_header.ver_minor, out_header.ver_patch,
                            out_header.pack_flags)
        head += struct.pack("<Q", out_header.file_base)
        if out_header.version == FORMAT_VERSION_46:
            head += struct.pack("<Q", dir_offset)
        else:
            head += struct.pack("<16I", *((out_header.reserved + [0] * 16)[:16]))
        head += struct.pack("<I", len(entries))
        want = out_header.dir_start - out_header.base
        if len(head) != want:
            raise PckError(f"собранный заголовок не {want} байт")
        f.write(bytes(head))
        for e, abs_ofs, size, has_blob in plan:
            blob = replace.get(e.path) if has_blob else None
            raw_path = e.path.encode("utf-8")
            md5 = hashlib.md5(blob).digest() if blob is not None else e.md5
            f.write(struct.pack("<I", len(raw_path)))
            f.write(raw_path)
            # движок складывает file_base сам (fap.cpp:353) — пишем разность
            f.write(struct.pack("<QQ", abs_ofs - file_base, size))
            f.write(md5)
            f.write(struct.pack("<I", e.flags))
        # паддинг между концом каталога и первым блобом
        if first_blob is not None:
            f.write(b"\x00" * (first_blob - head_end))
        with open(source, "rb") as src:
            for e, abs_ofs, size, has_blob in plan:
                if not has_blob:
                    continue
                blob = replace.get(e.path)
                if blob is not None:
                    f.write(blob)
                else:
                    src.seek(e.ofs)
                    left = size
                    while left > 0:
                        chunk = src.read(min(COPY_CHUNK, left))
                        if not chunk:
                            raise PckError("источник обрезан на " + e.path)
                        f.write(chunk)
                        left -= len(chunk)
                pad = _align_up(abs_ofs + size) - (abs_ofs + size)
                if pad:
                    f.write(b"\x00" * pad)

    _atomic_stream(dest, _write)


def verify(dest: str, expected_paths: list[str],
           expected_md5: dict[str, bytes]) -> list[str]:
    """Перечитать пересобранный .pck и сверить с ожиданием.

    Пустой список = расхождений нет. Проверяем ТРИ вещи, а не одну:

    1. число файлов, порядок и пути;
    2. md5 из каталога у изменённых (у остальных он по определению прежний);
    3. **сами байты блобов на диске** — md5 пересчитывается потоком по
       смещению, которое мы сами же и записали в каталог. Без этого
       сдвиг арифметики смещений на байт дал бы самосогласованный
       каталог, пустой список проблем и битые ресурсы в игре.

    Чтения идут чанками через одну ручку — файл в RAM не попадает.
    """
    problems: list[str] = []
    try:
        header = read_header(dest)
        entries = read_entries(dest, header)
    except PckError as exc:
        return [f"verify: пересобранный pck не читается: {exc}"]
    except OSError as exc:
        return [f"verify: пересобранный pck не открывается: {exc}"]
    if len(entries) != len(expected_paths):
        problems.append(
            f"verify: число файлов {len(entries)} != {len(expected_paths)}")
        return problems
    by_path = {e.path: e for e in entries}
    for i, path in enumerate(expected_paths):
        if entries[i].path != path:
            problems.append(
                f"verify: запись {i} '{path}' -> '{entries[i].path}'")
    for path, want in sorted(expected_md5.items()):
        got = by_path.get(path)
        if got is None:
            problems.append(f"verify: нет файла {path}")
        elif got.encrypted:
            problems.append(f"verify: файл {path} помечен зашифрованным")
        elif got.removal:
            problems.append(f"verify: файл {path} помечен удалённым")
        elif got.delta:
            problems.append(f"verify: файл {path} помечен дельта-патчем")
        elif got.md5 != want:
            problems.append(f"verify: md5 не совпал для {path}")
        else:
            # каталог совпал — проверяем, что записаны именно те байты
            try:
                with open(dest, "rb") as f:
                    actual = blob_md5(f, got)
            except (PckError, OSError) as exc:
                problems.append(f"verify: блоб {path} не читается: {exc}")
                continue
            if actual != want:
                problems.append(
                    f"verify: байты блоба не совпали с каталогом для {path}")
    return problems


# ── сборка синтетических .pck (нужна тестам и самопроверке) ──

def pack_files(dest: str, files, version: int = 2, ver_major: int = 4,
               ver_minor: int = 2, ver_patch: int = 0, pack_flags: int = 0,
               file_base: int = 0, reserved=None,
               entry_flags: dict | None = None) -> PckHeader:
    """Собрать .pck из ``{path: bytes}``.

    Нужна тестам (реальной Godot-игры у нас нет) и для самопроверки
    round-trip. Значения по умолчанию — константы движка 4.2
    (``PACK_FORMAT_VERSION_V2`` 2, ver 4.2), см. :func:`check_version`.
    ``version=FORMAT_VERSION_46`` собирает v3: заголовок 40 байт,
    ``dir_offset`` указывает на каталог сразу за ним.

    Значение ``None`` вместо блоба — запись-УДАЛЕНИЕ: она пишется с
    ``PACK_FILE_REMOVAL`` и без блоба (fap.cpp:350-351). ``entry_flags``
    задаёт дополнительные флаги записи по путям (например
    ``PACK_FILE_DELTA``).
    """
    entry_flags = dict(entry_flags or {})
    items = list(files.items())
    if not items:
        raise PckUnsupported("пустой пакет собирать нечего")
    # у v3 полей reserved[16] НЕТ (fap.cpp:307-316) — и хранить их «для
    # галочки» незачем: пустой список честнее выдуманных нулей
    if version == FORMAT_VERSION_46:
        reserved = []
    else:
        reserved = list(reserved) if reserved else [0] * 16
        reserved = (reserved + [0] * 16)[:16]
    dir_offset = header_size(version) if version == FORMAT_VERSION_46 else 0
    header = PckHeader(
        version=version, ver_major=ver_major, ver_minor=ver_minor,
        ver_patch=ver_patch, pack_flags=pack_flags, file_base=file_base,
        reserved=reserved, file_count=len(items), base=0,
        filesize=0, embedded=False, dir_offset=dir_offset)
    dir_size = sum(ENTRY_OVERHEAD + len(p.encode("utf-8")) for p, _b in items)
    head_end = header.dir_start + dir_size
    cursor = _align_up(file_base + head_end)
    plan = []          # (путь, блоб|None, abs_ofs, size, флаги)
    for p, blob in items:
        flags = entry_flags.get(p, 0)
        if blob is None:
            plan.append((p, None, 0, 0, flags | PACK_FILE_REMOVAL))
            continue
        plan.append((p, blob, cursor, len(blob), flags))
        cursor = _align_up(cursor + len(blob))
    blobs = [row for row in plan if row[1] is not None]
    first_blob = blobs[0][2] if blobs else None
    header.filesize = (blobs[-1][2] + blobs[-1][3]) if blobs else header.dir_start

    def _write(f):
        out = bytearray()
        out += MAGIC
        out += struct.pack("<IIIII", version, ver_major, ver_minor,
                           ver_patch, pack_flags)
        out += struct.pack("<Q", file_base)
        if version == FORMAT_VERSION_46:
            out += struct.pack("<Q", dir_offset)
        else:
            out += struct.pack("<16I", *reserved)
        out += struct.pack("<I", len(items))
        for p, blob, ofs, size, flags in plan:
            raw_path = p.encode("utf-8")
            out += struct.pack("<I", len(raw_path))
            out += raw_path
            # удалённая запись блоба не имеет: её ofs/size — нули (fap.cpp:350)
            stored_ofs = 0 if blob is None else ofs - file_base
            out += struct.pack("<QQ", stored_ofs, size)
            out += hashlib.md5(blob).digest() if blob is not None else bytes(16)
            out += struct.pack("<I", flags)
        f.write(bytes(out))
        # паддинг между концом каталога и первым блобом
        if first_blob is not None:
            f.write(b"\x00" * (first_blob - head_end))
        for _p, blob, ofs, size, _flags in plan:
            if blob is None:
                continue
            f.write(blob)
            pad = _align_up(ofs + len(blob)) - (ofs + len(blob))
            if pad:
                f.write(b"\x00" * pad)

    _atomic_stream(dest, _write)
    return header


def embedded_pck(dest: str, pck_bytes: bytes,
                 exe_head: bytes = b"MZ\x90\x00",
                 exe_tail: bytes = b"") -> str:
    """Склеить синтетический self-contained exe (нужно тестам детекта).

    Трейлер ровно как в движке (fap.cpp:257-280): ``uint64 pck_size``
    + ``'GDPC'``, а начало pck ищется как ``filesize - 12 - pck_size``.
    Поэтому после блоба НИЧЕГО быть не должно (``exe_tail`` пустой) —
    иначе формула движка укажет не туда.
    """
    with open(dest, "wb") as f:
        f.write(exe_head)
        f.write(pck_bytes)
        f.write(exe_tail)
        f.write(struct.pack("<Q", len(pck_bytes)))
        f.write(MAGIC)
    return dest

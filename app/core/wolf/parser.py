# -*- coding: utf-8 -*-
"""Wolf RPG Editor: детект, извлечение и внедрение текста.

Механизм (структура, не содержание):
- Data/*.wolf — DXA-v8 архивы (см. dxa.py); переводятся только
  текстовые внутренности (.dat/.mps), картинки/аудио не трогаем;
- строки — len-prefixed t_str (u4 длина с null-терминатором);
  кодировка по version_header: v2 (0x00) — cp932, v3 (0x55) — utf-8;
- контейнеры: Game.dat (только заголовок), *Database.dat (таблицы),
  CommonEvent.dat + .mps (команды событий, strings[] + route[]).

Безопасность:
- контрольные коды (\\n, \\c[n], \\v[]...) в переводе проверяются
  (порядок и наличие как в оригинале), иначе запись пропускается;
- имена файлов, ключи шифрования, шрифты, сериалы не извлекаются;
- apply идёт в loose-файлы Data/<Папка>/<inner> (движок читает
  распакованную Data/), оригинальные .wolf — в .wolf.ob_backup;
- повторный apply перепарсивает текущие файлы и сверяется
  с оригиналом (сдвиги длин не ломают позиции).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct

from app.core.models import TranslationEntry
from app.core.wolf import dxa

# ── константы формата ──

_V2 = 0x00
_V3 = 0x55

_DAT_MAGIC = b"\x00W\x00\x00OL"       # .dat (6 байт)
_MPS_MAGIC = bytes([0] * 10) + b"WOLFM\x00"  # .mps (16 байт)

_MANIFEST = ".ob_wolf_manifest.json"
_WOLF_BACKUP_SUFFIX = ".wolf.ob_backup"

# внутрь .wolf за переводом идём только за этими суффиксами
_TEXT_INNERS = (".dat", ".mps")
_SKIP_INNERS = (".project", ".xxxxx", ".png", ".jpg", ".jpeg", ".ogg",
                ".mp3", ".wav", ".mid", ".midi", ".mp4", ".avi", ".wmv")

# Game.dat v2: индексы строк record_string_settings_v2
# (title, serial, key, font_base, sub1..3, hero_graphic, unknown)
_GAME_V2_TITLE = 0
# Game.dat v3: (title, serial, key, font_base, sub1..3, hero_graphic,
# subtitle, loadingpic, gauge, title_loading, title_gameplay)
_GAME_V3_TITLE = 0
_GAME_V3_SUBTITLE = 8

# коды управления Wolf (должны сохраняться в переводе дословно)
_CODE_RE = re.compile(r"\\[A-Za-z]+\[[^\]]*\]|\\[A-Za-z]")

# похоже на имя файла/путь — не текст
_RES_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".ogg", ".mp3",
             ".wav", ".mid", ".midi", ".m4a", ".mp4", ".avi", ".wmv",
             ".dat", ".mps", ".project", ".ttf", ".otf", ".txt", ".ini")
_RES_RE = re.compile(r"^[A-Za-z0-9_\-./\\]+\.[A-Za-z0-9]{2,5}$")


def _has_letters(s: str) -> bool:
    return any(ch.isalpha() for ch in s)


def _looks_like_filename(s: str) -> bool:
    t = s.strip()
    if not t or len(t) > 128:
        return False
    low = t.lower()
    if low.endswith(_RES_EXTS) and _RES_RE.match(t):
        return True
    if (("\\" in t or "/" in t) and "." in t and " " not in t
            and len(t) < 64):
        return True
    return False


def _looks_like_code(s: str) -> bool:
    """Похоже на скрипт-код, а не на текст (круглые скобки + точка
    с запятой, фигурные блоки) — перевод сломал бы логику."""
    t = s.strip()
    if len(t) < 8:
        return False
    if "(" in t and ")" in t and ";" in t:
        return True
    if t.startswith(("{", "}", "function ", "var ", "if(", "if ")):
        return True
    return False


def _is_var_safe(original: str, translation: str) -> bool:
    """Контрольные коды оригинала — в переводе дословно и по порядку."""
    codes = _CODE_RE.findall(original)
    if not codes:
        return True
    pos = 0
    for code in codes:
        idx = translation.find(code, pos)
        if idx == -1:
            return False
        pos = idx + len(code)
    return True


def _enc_for_version(ver_hdr: int) -> str:
    return "utf-8" if ver_hdr == _V3 else "cp932"


# ── курсор по байтам ──

class _Cur:
    __slots__ = ("buf", "pos", "enc")

    def __init__(self, buf: bytes, enc: str):
        self.buf = buf
        self.pos = 0
        self.enc = enc

    def left(self) -> int:
        return len(self.buf) - self.pos

    def u1(self) -> int:
        v = self.buf[self.pos]
        self.pos += 1
        return v

    def u4(self) -> int:
        v = struct.unpack("<I", self.buf[self.pos:self.pos + 4])[0]
        self.pos += 4
        return v

    def s4(self) -> int:
        v = struct.unpack("<i", self.buf[self.pos:self.pos + 4])[0]
        self.pos += 4
        return v

    def raw(self, n: int) -> bytes:
        v = self.buf[self.pos:self.pos + n]
        if len(v) != n:
            raise ValueError("truncated")
        self.pos += n
        return v

    def t_str(self) -> tuple[str, int, int]:
        """Читает t_str. Возвращает (текст, смещение поля длины, полная длина)."""
        if self.left() < 4:
            raise ValueError("truncated t_str len")
        off = self.pos
        ln = self.u4()
        if ln == 0 or ln > 1_000_000 or ln > self.left():
            raise ValueError(f"bad t_str len {ln}")
        payload = self.raw(ln)
        if not payload.endswith(b"\x00"):
            raise ValueError("t_str not null-terminated")
        try:
            text = payload[:-1].decode(self.enc)
        except (UnicodeDecodeError, ValueError):
            # v2-файлы иногда содержат UTF-8 строки — пробуем второй шанс
            alt = "utf-8" if self.enc != "utf-8" else "cp932"
            text = payload[:-1].decode(alt)
        return text, off, 4 + ln


def _t_str_at(buf: bytes, off: int, enc: str) -> tuple[str, int]:
    """Текст и полная длина t_str по смещению (для apply)."""
    c = _Cur(buf, enc)
    c.pos = off
    text, _o, total = c.t_str()
    return text, total


def _encode_t_str(text: str, enc: str) -> bytes:
    raw = text.encode(enc) + b"\x00"
    return struct.pack("<I", len(raw)) + raw


# ── route_info (пропуск, размеры по типам) ──

# route_data type -> фиксированный размер ИЛИ None (читать general)
_ROUTE_FIXED: dict[int, int] = {}
for _t in (0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09,
            0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11, 0x12, 0x13,
            0x14, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x20, 0x21, 0x22,
            0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x29, 0x30, 0x31, 0x32,
            0x33, 0x34, 0x38, 0x39):
    _ROUTE_FIXED[_t] = -1  # general_no_param: 3 байта [0,1,0]
for _t in (0x15, 0x1C, 0x37, 0x36):
    _ROUTE_FIXED[_t] = -2  # 11 байт: 1+4+4+1+1
for _t in (0x1D, 0x1E, 0x1F, 0x2C, 0x2D, 0x2E, 0x2F, 0x35, 0x3A):
    _ROUTE_FIXED[_t] = -3  # 7 байт: 1+4+1+1


def _skip_route(c: _Cur) -> None:
    """Пропускает route_info (10 байт заголовка + route_data[])."""
    c.raw(4)  # animation/move/move_frequency/mode
    c.raw(1)  # behavior_options
    c.raw(1)  # route_options
    n = c.u4()
    if n > 10000:
        raise ValueError(f"bad route_length {n}")
    for _ in range(n):
        t = c.u1()
        kind = _ROUTE_FIXED.get(t)
        if kind == -1:
            raw = c.raw(3)
            if raw != bytes([0, 1, 0]):
                raise ValueError("bad no_param route")
        elif kind == -2:
            c.raw(11)
        elif kind == -3:
            c.raw(7)
        else:
            # general (и неизвестные типы): счётчики длин
            na = c.u1()
            if na > 64:
                raise ValueError("bad route u4 count")
            c.raw(4 * na)
            nb = c.u1()
            if nb > 64:
                raise ValueError("bad route u1 count")
            c.raw(nb)


# ── event_command (общее для .mps и CommonEvent.dat) ──

class _CmdStr:
    __slots__ = ("cmd_index", "str_index", "off", "text")

    def __init__(self, cmd_index: int, str_index: int, off: int, text: str):
        self.cmd_index = cmd_index
        self.str_index = str_index
        self.off = off
        self.text = text


def _parse_commands(c: _Cur, count: int) -> list[_CmdStr]:
    """Парсит count event_command, возвращает позиции строк.

    Формат: param_count u1; если >0: command_type u4,
    param[param_count*4-4], branch_depth u1, string_count u1,
    strings[string_count] t_str, have_route u1, [route_info].
    """
    out: list[_CmdStr] = []
    for ci in range(count):
        if c.left() < 1:
            raise ValueError("truncated cmd")
        pc = c.u1()
        if pc == 0:
            continue
        if c.left() < 4 + 1 + 1 + 1:
            raise ValueError("truncated cmd head")
        _ctype = c.u4()
        c.raw(pc * 4 - 4)
        c.u1()  # branch_depth
        sc = c.u1()
        if sc > 64:
            raise ValueError(f"bad string_count {sc}")
        for si in range(sc):
            text, off, _total = c.t_str()
            out.append(_CmdStr(ci, si, off, text))
        if c.left() < 1:
            raise ValueError("truncated have_route")
        hr = c.u1()
        if hr:
            _skip_route(c)
    return out


# ── Game.dat ──

def _parse_game(buf: bytes) -> tuple[str, list[tuple[int, str, str]]]:
    """Возвращает (enc, [(ключ, текст, путь)]) для Game.dat."""
    if buf[:6] != b"\x00W\x00\x00OL" or buf[6:9] != b"\x00FM":
        raise ValueError("bad Game.dat magic")
    # порядок: magic 9 байт (00 57 00 00 4f 4c 00 46 4d),
    # version_header u1, u8_settings_len u4, ...
    vh = buf[9]
    enc = _enc_for_version(vh)
    c = _Cur(buf, enc)
    c.pos = 10
    u8len = c.u4()
    c.raw(u8len)
    nstr = c.u4()
    if nstr > 64:
        raise ValueError(f"bad Game.dat string count {nstr}")
    out: list[tuple[int, str, str]] = []
    for i in range(nstr):
        text, off, _t = c.t_str()
        out.append((off, text, f"game:s{i}"))
    return enc, out


def _game_translatable(vh: int, idx: int) -> bool:
    if vh == _V3:
        return idx in (_GAME_V3_TITLE, _GAME_V3_SUBTITLE)
    return idx == _GAME_V2_TITLE


# ── database_dat (*Database.dat) ──

def _parse_database(buf: bytes) -> tuple[str, int, list[tuple[int, str, str]]]:
    """(enc, version_header, [(off, text, путь)]) для *Database.dat."""
    if buf[:6] != _DAT_MAGIC or buf[7:10] != b"FM\x00":
        raise ValueError("bad database magic")
    vh = buf[6]
    enc = _enc_for_version(vh)
    c = _Cur(buf, enc)
    c.pos = 10
    _ver = c.u1()
    ntypes = c.u4()
    if ntypes > 10000:
        raise ValueError(f"bad type count {ntypes}")
    out: list[tuple[int, str, str]] = []
    for ti in range(ntypes):
        if c.raw(4) != bytes([0xFE, 0xFF, 0xFF, 0xFF]):
            raise ValueError("bad type sub_header")
        c.raw(4)  # data_id_method
        pcount = c.u4()
        if pcount > 10000:
            raise ValueError("bad property count")
        # property_position: raw u4 × pcount (блок/поз не нужны — строки
        # идут подряд блоками: сначала все number, потом все string)
        ppos = [c.u4() for _ in range(pcount)]
        n_num = sum(1 for v in ppos if v // 1000 == 1)
        n_str = pcount - n_num
        size2 = c.u4()
        if size2 > 1000000:
            raise ValueError("bad row count")
        for ri in range(size2):
            c.raw(4 * n_num)
            for si in range(n_str):
                text, off, _t = c.t_str()
                out.append((off, text, f"db:t{ti}:r{ri}:s{si}"))
    return enc, vh, out


# ── CommonEvent.dat ──

def _parse_commonevent(buf: bytes) -> tuple[str, list[tuple[int, str, str]]]:
    if buf[:6] != _DAT_MAGIC or buf[7:10] != b"FC\x00":
        raise ValueError("bad commonevent magic")
    vh = buf[6]
    enc = _enc_for_version(vh)
    c = _Cur(buf, enc)
    c.pos = 10
    _ver = c.u1()
    count = c.u4()
    if count > 100000:
        raise ValueError(f"bad common count {count}")
    out: list[tuple[int, str, str]] = []
    for ei in range(count):
        if c.u1() != 0x8E:
            raise ValueError("bad common header")
        c.raw(4)  # id
        c.raw(1)  # condition_operator+run_condition
        c.raw(4)  # condition_variable (magic_number: u4? см. kaitai)
        c.raw(4)  # condition_value
        argc_n = c.u1()
        argc_s = c.u1()
        if argc_n > 64 or argc_s > 64:
            raise ValueError("bad arg counts")
        t, off, _x = c.t_str()
        out.append((off, t, f"ce:{ei}:title"))
        nlines = c.u4()
        if nlines > 1000000:
            raise ValueError("bad lines count")
        for cs in _parse_commands(c, nlines):
            out.append((cs.off, cs.text, f"ce:{ei}:c{cs.cmd_index}:s{cs.str_index}"))
        if c.raw(5) != bytes([1, 0, 0, 0, 0]):
            raise ValueError("bad common unknown4")
        t, off, _x = c.t_str()
        out.append((off, t, f"ce:{ei}:memo"))
        if c.u1() != 0x8F:
            raise ValueError("bad common sep1")
        # argument_names: t_str_array (len + t_str[len])
        na = c.u4()
        if na > 10000:
            raise ValueError("bad arg names")
        for ai in range(na):
            t, off, _x = c.t_str()
            out.append((off, t, f"ce:{ei}:arg{ai}"))
        # дальше — таблицы спец. аргументов (числа) и尾部: читаем по спекам
        nmode = c.u4()
        if nmode > 10000:
            raise ValueError("bad spec mode pages")
        c.raw(nmode)  # argument_special_specification (u1 каждый)
        nstr_pages = c.u4()
        if nstr_pages > 10000:
            raise ValueError("bad str pages")
        for _p in range(nstr_pages):
            nl = c.u4()
            if nl > 10000:
                raise ValueError("bad str page len")
            for si in range(nl):
                t, off, _x = c.t_str()
                out.append((off, t, f"ce:{ei}:opt{_p}:{si}"))
        nnum_pages = c.u4()
        if nnum_pages > 10000:
            raise ValueError("bad num pages")
        for _p in range(nnum_pages):
            nl = c.u4()
            if nl > 10000:
                raise ValueError("bad num page len")
            c.raw(4 * nl)
        # argument_number_default_value: t_s4_array
        nl = c.u4()
        if nl > 10000:
            raise ValueError("bad defvals")
        c.raw(4 * nl)
        if c.u1() != 0x90:
            raise ValueError("bad common sep2")
        c.raw(4)  # color
        for vi in range(100):
            t, off, _x = c.t_str()
            # self-переменные: имена по умолчанию пустые — пустые пропускаем
            # при извлечении, но позицию фиксируем тем же путём
            out.append((off, t, f"ce:{ei}:self{vi}"))
        if c.u1() != 0x91:
            raise ValueError("bad common sep3")
        if c.raw(5) != bytes([1, 0, 0, 0, 0]):
            raise ValueError("bad common unknown5")
        if c.u1() != 0x92:
            raise ValueError("bad common sep4")
        t, off, _x = c.t_str()
        out.append((off, t, f"ce:{ei}:retname"))
        c.raw(4)  # return_value_id
        if c.u1() != 0x92:
            raise ValueError("bad common sep5")
    return enc, out


# ── .mps (MapData) ──

def _parse_mps(buf: bytes) -> tuple[str, list[tuple[int, str, str]]]:
    if buf[:16] != _MPS_MAGIC:
        raise ValueError("bad mps magic")
    vh = buf[16]
    enc = _enc_for_version(vh)
    c = _Cur(buf, enc)
    c.pos = 17
    c.raw(3)  # magic2
    if c.u4() != 0x64:
        raise ValueError("bad mps unknown1")
    c.u1()  # version 0x65/0x66
    t, off, _x = c.t_str()
    out = [(off, t, "mps:title")]
    _tileset = c.u4()
    width = c.u4()
    height = c.u4()
    if width > 1000 or height > 1000 or width == 0 or height == 0:
        raise ValueError(f"bad map size {width}x{height}")
    ev_count = c.u4()
    if ev_count > 100000:
        raise ValueError("bad event count")
    # mapdata_block: first_pixel u4; если != FFFFFFFF — пропуск
    # width*height*12-4 байт (3 слоя пикселей)
    first = c.u4()
    if first != 0xFFFFFFFF:
        c.raw(width * height * 12 - 4)
    for ei in range(ev_count):
        if c.u1() != 0x6F:
            raise ValueError("bad event header")
        if c.u4() != 0x3039:
            raise ValueError("bad event header2")
        c.raw(4)  # event_id
        t, off, _x = c.t_str()
        out.append((off, t, f"mps:e{ei}:title"))
        c.raw(4)  # map_x
        c.raw(4)  # map_y
        npages = c.u4()
        if npages > 1000:
            raise ValueError("bad page count")
        if c.u4() != 0:
            raise ValueError("bad event separator")
        for pi in range(npages):
            if c.u1() != 0x79:
                raise ValueError("bad page header")
            c.raw(4)  # chipid
            # имя графического чипа — ссылка на ресурс (tileset/char),
            # никогда не текст: пропускаем целиком, не извлекая
            _t, _o, _x = c.t_str()
            c.raw(1 + 1 + 1 + 1)  # row/col/opacity/display
            c.raw(1)  # trigger_condition
            c.raw(4)  # trigger_switch ×4 (b4+b4 → 1 байт каждый)
            c.raw(16)  # trigger_variable ×4 (magic_number u4)
            c.raw(16)  # trigger_value s4 ×4
            _skip_route(c)  # route_info страницы
            ncmd = c.u4()
            if ncmd > 1000000:
                raise ValueError("bad cmd count")
            for cs in _parse_commands(c, ncmd):
                out.append((cs.off, cs.text,
                            f"mps:e{ei}:p{pi}:c{cs.cmd_index}:s{cs.str_index}"))
            if c.u4() != 3:
                raise ValueError("bad page unknown3")
            c.raw(1 + 1 + 1)  # shadow/range_x/range_y
            if c.u1() != 0x7A:
                raise ValueError("bad page footer")
        if c.u1() != 0x70:
            raise ValueError("bad event footer")
    return enc, out


# ── выбор парсера по имени ──

def _parse_inner(name: str, buf: bytes):
    low = name.lower()
    if low == "game.dat":
        enc, items = _parse_game(buf)
        return enc, 0, [i for i in items
                        if _game_translatable(_vh_of(buf), int(i[2].split(":s")[1]))]
    if low == "commonevent.dat":
        enc, items = _parse_commonevent(buf)
        return enc, 0, items
    if low.endswith(".mps"):
        enc, items = _parse_mps(buf)
        return enc, 0, items
    if low.endswith(".dat"):
        enc, vh, items = _parse_database(buf)
        return enc, vh, items
    raise ValueError("not a text inner")


def _vh_of(buf: bytes) -> int:
    try:
        if buf[:16] == _MPS_MAGIC:
            return buf[16]
        if buf[:6] == _DAT_MAGIC:
            return buf[6]
    except IndexError:
        pass
    return _V2


# ── workspace / детект ──

def _data_dir(game_dir: str) -> str:
    d = os.path.join(game_dir, "Data")
    return d if os.path.isdir(d) else game_dir


def _wolf_files(game_dir: str) -> list[str]:
    d = _data_dir(game_dir)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    out = [os.path.join(d, n) for n in names if n.lower().endswith(".wolf")]
    return sorted(out)


def _is_dx_wolf(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(4)
        return len(head) == 4 and head[:2] == b"DX" and head[2] in (5, 6, 8)
    except OSError:
        return False


def detect(game_dir: str) -> int:
    """Вес уверенности: 0 — не Wolf RPG Editor."""
    wolves = _wolf_files(game_dir)
    dx = [w for w in wolves if _is_dx_wolf(w)]
    has_exe = os.path.isfile(os.path.join(game_dir, "Game.exe"))
    has_ini = os.path.isfile(os.path.join(game_dir, "Game.ini"))
    has_data = os.path.isdir(os.path.join(game_dir, "Data"))
    if dx and has_exe and (has_ini or has_data):
        return 105
    if dx:
        return 85
    if has_exe and has_ini and has_data:
        # возможный распакованный проект Woditor (без .wolf)
        try:
            ini = open(os.path.join(game_dir, "Game.ini"),
                       encoding="utf-8", errors="replace").read(512)
        except OSError:
            ini = ""
        if "Start=" in ini and ("WindowModeFlag" in ini or "SoftModeFlag" in ini):
            return 55
        return 0
    return 0


def _workspace(game_dir: str) -> str:
    from app import projects_dir
    h = hashlib.md5(os.path.abspath(game_dir).encode()).hexdigest()[:12]
    base = os.path.basename(os.path.normpath(game_dir)) or "game"
    safe = "".join(ch if ch.isalnum() else "_" for ch in base)[:24]
    ws = os.path.join(projects_dir(), "wolf-workspace", f"{safe}_{h}")
    os.makedirs(ws, exist_ok=True)
    return ws


# ── извлечение ──

class _Collector:
    def __init__(self, stems: set[str] | None = None):
        self.entries: list[TranslationEntry] = []
        self._next = 1
        self.skipped = 0
        self._stems = stems or set()

    def add(self, rel: str, path: str, original: str):
        original = original.strip("\x00").strip()
        if not original or len(original) < 2:
            self.skipped += 1
            return
        if not _has_letters(original):
            self.skipped += 1
            return
        if _looks_like_filename(original):
            self.skipped += 1
            return
        if _looks_like_code(original):
            self.skipped += 1
            return
        # ссылка на ресурс без расширения (BGM/SE/графика голым именем):
        # однотокенные строки, совпавшие со стемами внутренностей —
        # перевод дал бы silencio/missing asset в игре
        if " " not in original.strip() and "\n" not in original:
            if original.strip().lower() in self._stems:
                self.skipped += 1
                return
        if len(original) > 4000:
            self.skipped += 1
            return
        self.entries.append(TranslationEntry(
            id=self._next, file=rel, json_path=path,
            context=path, original=original))
        self._next += 1


def _iter_text_wolves(game_dir: str):
    """(wolf_path, arc) для архивов с текстовыми внутренностями."""
    for wpath in _wolf_files(game_dir):
        if not _is_dx_wolf(wpath):
            continue
        try:
            arc = dxa.list_archive(wpath)
        except (ValueError, OSError):
            continue
        inners = [fi for fi in arc.files
                  if fi.name.lower().endswith(_TEXT_INNERS)
                  and not fi.name.lower().endswith(_SKIP_INNERS)]
        if inners:
            yield wpath, arc, inners


_STEMS_CACHE: dict[str, set[str]] = {}


def resource_stems(game_dir: str) -> set[str]:
    """Стемы имён ресурсов (аудио/картинки без расширений, lower).

    Архивы без текстовых внутренностей — заведомо ресурсы; их имена —
    индекс «не-текста» (зеркало resrefs RPG Maker): однотокенные строки,
    совпавшие со стемом, не извлекаются (иначе missing asset в игре).
    Кэш на процесс: шапки архивов читаются быстро, но один раз.
    """
    key = os.path.abspath(game_dir)
    hit = _STEMS_CACHE.get(key)
    if hit is not None:
        return hit
    stems: set[str] = set()
    for wpath in _wolf_files(game_dir):
        if not _is_dx_wolf(wpath):
            continue
        try:
            arc = dxa.list_archive(wpath)
        except (ValueError, OSError):
            continue
        has_text = any(fi.name.lower().endswith(_TEXT_INNERS)
                       and not fi.name.lower().endswith(_SKIP_INNERS)
                       for fi in arc.files)
        if has_text:
            continue
        for fi in arc.files:
            base = os.path.basename(fi.name)
            stem, _ext = os.path.splitext(base)
            stem = stem.strip().lower()
            if stem:
                stems.add(stem)
    _STEMS_CACHE[key] = stems
    return stems


def _loose_inners(game_dir: str):
    """Loose-файлы перевода (после прошлого apply): (wolf, inner, bytes).

    wolf восстанавливается из имени папки (Data/<stem>/ -> <stem>.wolf).
    Парсится только то, что понимает _parse_inner; остальное пропускается.
    """
    data = _data_dir(game_dir)
    try:
        stems = [d for d in os.listdir(data)
                 if os.path.isdir(os.path.join(data, d))
                 and not d.startswith(".") and d.lower() != "backup"]
    except OSError:
        return
    for stem in sorted(stems):
        sdir = os.path.join(data, stem)
        try:
            names = os.listdir(sdir)
        except OSError:
            continue
        for n in sorted(names):
            if not n.lower().endswith(_TEXT_INNERS):
                continue
            if n.lower().endswith(_SKIP_INNERS):
                continue
            p = os.path.join(sdir, n)
            try:
                with open(p, "rb") as f:
                    buf = f.read()
            except OSError:
                continue
            try:
                _parse_inner(n, buf)
            except (ValueError, IndexError, struct.error):
                continue
            yield f"{stem}.wolf", n, buf


def extract(game_dir: str) -> list[TranslationEntry]:
    """Извлекает строки из .wolf и loose-файлов перевода.

    Loose-файлы (Data/<Папка>/<inner> после apply) читаются в первую
    очередь: после внедрения .wolf убран в бэкап, и архивного источника
    больше нет. Дубли (и архив, и loose) — берётся loose.
    """
    try:
        stems = resource_stems(game_dir)
    except (ValueError, OSError, MemoryError):
        stems = set()
    col = _Collector(stems)
    seen: set[tuple[str, str]] = set()
    for wolf, inner, buf in _loose_inners(game_dir):
        rel = f"Data/{wolf}/{inner}".replace(os.sep, "/")
        seen.add((wolf, inner))
        try:
            _enc, _vh, items = _parse_inner(inner, buf)
        except (ValueError, IndexError, struct.error):
            col.skipped += 1
            continue
        for _off, text, path in items:
            col.add(rel, path, text)
    for wpath, arc, inners in _iter_text_wolves(game_dir):
        wolf = os.path.basename(wpath)
        for fi in inners:
            if (wolf, fi.name) in seen:
                continue
            rel = f"Data/{wolf}/{fi.name}".replace(os.sep, "/")
            try:
                buf = dxa.extract_file(arc, fi)
            except (ValueError, OSError, MemoryError):
                col.skipped += 1
                continue
            try:
                _enc, _vh, items = _parse_inner(fi.name, buf)
            except (ValueError, IndexError, struct.error):
                col.skipped += 1
                continue
            for _off, text, path in items:
                col.add(rel, path, text)
    return col.entries


# ── внедрение (loose-файлы + бэкап .wolf) ──

def _manifest_path(game_dir: str) -> str:
    return os.path.join(_data_dir(game_dir), _MANIFEST)


def _load_manifest(game_dir: str) -> dict:
    try:
        with open(_manifest_path(game_dir), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_manifest(game_dir: str, m: dict) -> None:
    try:
        from app.core.io import atomic_write_json
        atomic_write_json(_manifest_path(game_dir), m, indent=1)
    except (OSError, TypeError, ValueError):
        pass


def _loose_path(game_dir: str, wolf: str, inner: str) -> str:
    stem = os.path.splitext(os.path.basename(wolf))[0]
    return os.path.join(_data_dir(game_dir), stem, inner)


def _current_inner_bytes(game_dir: str, wolf: str, inner: str,
                         arc: dxa.WolfArchive,
                         fi: dxa.WolfFileInfo) -> bytes:
    """Актуальные байты внутренности: loose-файл (после прошлого apply)
    или свежая распаковка .wolf."""
    lp = _loose_path(game_dir, wolf, inner)
    if os.path.isfile(lp):
        with open(lp, "rb") as f:
            return f.read()
    return dxa.extract_file(arc, fi)


def apply(game_dir: str, entries: list, target_lang: str = "",
          on_skip=None, **kwargs) -> dict:
    """Внедряет переводы в loose-файлы. Возвращает статистику."""
    try:
        stems = resource_stems(game_dir)
    except (ValueError, OSError, MemoryError):
        stems = set()
    # группировка по (wolf, inner)
    by_file: dict[tuple[str, str], list] = {}
    res_skipped = 0
    for e in entries:
        tr = e.translation if not isinstance(e, dict) else e.get("translation", "")
        st = e.status if not isinstance(e, dict) else e.get("status", "")
        if not tr or not tr.strip() or st == "skip":
            continue
        orig = e.original if not isinstance(e, dict) else e.get("original", "")
        # ссылки на ресурсы из старых извлечений — не внедряем никогда
        # (перевод имени файла = missing asset в игре)
        if (orig and " " not in orig.strip() and "\n" not in orig
                and orig.strip().lower() in stems):
            res_skipped += 1
            continue
        rel = e.file if not isinstance(e, dict) else e.get("file", "")
        parts = (rel or "").split("/")
        if len(parts) < 3 or parts[0] != "Data":
            if on_skip:
                on_skip(e, "bad wolf path")
            continue
        by_file.setdefault((parts[1], "/".join(parts[2:])), []).append(e)

    stats: dict = {"files": 0, "strings": 0, "backups": [],
                   "skipped_total": 0, "skipped_by": {},
                   "res_skipped": res_skipped}
    skip_count: dict[str, int] = {}
    if res_skipped:
        skip_count["resources"] = res_skipped

    def _skip(e, reason: str):
        skip_count[reason] = skip_count.get(reason, 0) + 1
        if on_skip:
            try:
                on_skip(e, reason)
            except TypeError:
                pass

    if not by_file:
        return stats

    # индекс архивов (быстро: только шапки)
    arcs: dict[str, dxa.WolfArchive] = {}
    for wpath in _wolf_files(game_dir):
        try:
            arcs[os.path.basename(wpath)] = dxa.list_archive(wpath)
        except (ValueError, OSError):
            continue

    manifest = _load_manifest(game_dir)
    manifest.setdefault("loose", [])
    manifest.setdefault("wolf_backups", [])

    # ФАЗА 1 — чтение: все нужные внутренности ДО переименований .wolf.
    # (бэкап одного архива делает его недоступным для чтения остальных
    # внутренностей того же архива — читаем всё заранее.)
    loaded: dict[tuple[str, str], tuple[bytes, str, list] | None] = {}
    for (wolf, inner) in sorted(by_file):
        arc = arcs.get(wolf)
        if arc is None:
            continue
        fi = next((x for x in arc.files if x.name == inner), None)
        if fi is None:
            fi = next((x for x in arc.files
                       if x.name.lower() == inner.lower()), None)
        if fi is None:
            continue
        try:
            buf = _current_inner_bytes(game_dir, wolf, inner, arc, fi)
            enc, _vh, parsed = _parse_inner(fi.name, buf)
        except (ValueError, OSError, MemoryError, IndexError, struct.error):
            loaded[(wolf, inner)] = None
            continue
        loaded[(wolf, inner)] = (buf, enc, parsed)

    for (wolf, inner), items in sorted(by_file.items()):
        if (wolf, inner) not in loaded:
            for e in items:
                _skip(e, "archive not found")
            continue
        got = loaded[(wolf, inner)]
        if got is None:
            # различаем «нет внутренности» и «не прочиталась»
            arc = arcs.get(wolf)
            fi = next((x for x in (arc.files if arc else [])
                       if x.name == inner or x.name.lower() == inner.lower()),
                      None) if arc else None
            for e in items:
                _skip(e, "inner not found" if fi is None else "cannot read inner")
            continue
        buf, enc, parsed = got
        # позиция по структурному пути
        slots: dict[str, list[tuple[int, str]]] = {}
        for off, text, path in parsed:
            slots.setdefault(path, []).append((off, text))
        repl: list[tuple[int, int, bytes]] = []  # (off, old_total, new_blob)
        for e in items:
            path = e.json_path if not isinstance(e, dict) else e.get("json_path", "")
            orig = e.original if not isinstance(e, dict) else e.get("original", "")
            tr = e.translation if not isinstance(e, dict) else e.get("translation", "")
            cands = slots.get(path or "", [])
            hit = next((o for o, t in cands
                        if t.strip("\x00").strip() == (orig or "").strip()), None)
            if hit is None:
                # дубль-строка могла съехать: ищем по первому вхождению
                # того же оригинала в этом файле
                alt = next((o for o, t, _p in parsed
                            if t.strip("\x00").strip() == (orig or "").strip()
                            and not any(r[0] == o for r in repl)), None)
                if alt is None:
                    _skip(e, "original not found")
                    continue
                hit = alt
            try:
                _cur_text, total = _t_str_at(buf, hit, enc)
            except (ValueError, IndexError, struct.error):
                _skip(e, "offset desync")
                continue
            if not _is_var_safe(orig or "", tr or ""):
                _skip(e, "control codes")
                continue
            try:
                new_blob = _encode_t_str((tr or "").strip(), enc)
            except (UnicodeEncodeError, ValueError):
                _skip(e, "encoding")
                continue
            repl.append((hit, total, new_blob))
        if not repl:
            continue
        # splice от конца к началу (смещения не съезжают)
        out = bytearray(buf)
        for off, total, new_blob in sorted(repl, reverse=True):
            out[off:off + total] = new_blob
        # Game.dat: поле filesize = size-1
        if inner.lower() == "game.dat" and len(out) >= 4:
            try:
                _fix_game_filesize(out)
            except (ValueError, IndexError, struct.error):
                for e in items:
                    _skip(e, "filesize fix")
                continue
        # бэкап .wolf один раз + запись loose
        wpath = os.path.join(_data_dir(game_dir), wolf)
        bak = wpath + _WOLF_BACKUP_SUFFIX
        if os.path.isfile(wpath) and not os.path.isfile(bak):
            try:
                os.replace(wpath, bak)
                stats["backups"].append(bak)
                manifest["wolf_backups"].append(os.path.basename(bak))
            except OSError:
                for e in items:
                    _skip(e, "cannot backup wolf")
                continue
        lp = _loose_path(game_dir, wolf, inner)
        try:
            os.makedirs(os.path.dirname(lp), exist_ok=True)
            try:
                from app.core.io import atomic_write_bytes as _awb
            except ImportError:  # pragma: no cover
                _awb = None  # type: ignore
            if _awb is not None:
                _awb(lp, bytes(out))
            else:
                with open(lp, "wb") as f:
                    f.write(bytes(out))
        except OSError:
            for e in items:
                _skip(e, "cannot write loose")
            continue
        rel_loose = os.path.relpath(lp, game_dir).replace(os.sep, "/")
        if rel_loose not in manifest["loose"]:
            manifest["loose"].append(rel_loose)
        stats["files"] += 1
        stats["strings"] += len(repl)

    if skip_count:
        stats["skipped_total"] = sum(skip_count.values())
        stats["skipped_by"] = dict(sorted(skip_count.items(),
                                          key=lambda kv: -kv[1])[:5])
    _save_manifest(game_dir, manifest)
    return stats


def _fix_game_filesize(out: bytearray) -> None:
    """filesize (u4 перед u16-настройками) = len(out)-1."""
    # раскладка: magic9, vh1, u8len4, u8[u8len], nstr4, строки...,
    # filesize4, unknown3_4, u16_settings, randoms, footer1.
    # filesize ищем с конца: randoms+footer известны неточно, поэтому
    # ищем поле перебором: кандидат p, где u16_settings парсится, а
    # filesize == len-1. Упрощённо: filesize — первое u4 после строк,
    # равное СТАРОМУ len-1; заменяем на новый len-1.
    # Надёжный якорь: nstr и строки уже распарсены выше — filesize идёт
    # сразу после последней строки.
    vh = out[9]
    enc = _enc_for_version(vh)
    c = _Cur(bytes(out), enc)
    c.pos = 10
    u8len = c.u4()
    c.raw(u8len)
    nstr = c.u4()
    for _ in range(nstr):
        c.t_str()
    # c.pos теперь в начале filesize
    if c.left() < 4:
        raise ValueError("no filesize")
    struct.pack_into("<I", out, c.pos, len(out) - 1)


def restore_original(game_dir: str) -> dict:
    """Удаляет loose-файлы перевода и возвращает .wolf из бэкапов."""
    manifest = _load_manifest(game_dir)
    restored = 0
    for rel in manifest.get("loose", []):
        p = os.path.join(game_dir, *rel.split("/"))
        try:
            if os.path.isfile(p):
                os.remove(p)
                restored += 1
        except OSError:
            pass
        # чистим пустые каталоги вверх до Data/
        d = os.path.dirname(p)
        data = _data_dir(game_dir)
        while d.startswith(data) and d != data:
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)
    for bak in manifest.get("wolf_backups", []):
        src = os.path.join(_data_dir(game_dir), os.path.basename(bak))
        if src.endswith(_WOLF_BACKUP_SUFFIX) and os.path.isfile(src):
            dst = src[:-len(_WOLF_BACKUP_SUFFIX)]
            try:
                if os.path.isfile(dst):
                    os.remove(dst)
                os.replace(src, dst)
                restored += 1
            except OSError:
                pass
    try:
        os.remove(_manifest_path(game_dir))
    except OSError:
        pass
    return {"restored": restored}

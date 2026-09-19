# -*- coding: utf-8 -*-
"""DXLib-архивы (.wolf) Wolf RPG Editor — чтение (read-only).

Формат: DXA v5/v6/v8 (игры Woditor используют 6 и 8; данный модуль
реализует v8 — версию архивов исследуемой игры; v5/v6 детектятся
заголовком и честно отклоняются).

Источники алгоритма: DXLib (исходники архиватора, свободная
библиотека), Xentax Wiki «DX Archive», kaitai-спеки djytw/wolf-rpg-formats
(MIT). Код ниже — собственная реализация по этим спекам
(совместимость/интероп), без копирования чужих файлов.

Схема v8:
- заголовок 64 байта — открытый (magic 'DX', version, headSize,
  dataStart, таблицы имён/файлов/каталогов, codepage, flags, huffmanKB);
- таблицы в конце файла: XOR базовым ключом (7 байт из keyString через
  CRC32) -> Huffman-decode -> LZ-decode -> headBuffer;
- каждый файл: XOR персональным ключом (keyString + имя + родители)
  -> Huffman (опц.) -> LZ (опц.) -> сырые байты.

Только чтение: encode/compress не реализованы (для apply используется
стратегия loose-файлов — движок читает распакованные Data/<папка>/).
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

DX_MAGIC = 0x5844  # 'DX' LE
DX_VER_8 = 8
DX_VER_5 = 5
DX_VER_6 = 6

_HEAD_STRUCT = struct.Struct("<HHIQQQQIIB14sB")
_FILEHEAD_STRUCT = struct.Struct("<QQQQQQQQQ")
_DIR_STRUCT = struct.Struct("<QQQQ")
_NO_COMPRESS = 0xFFFFFFFFFFFFFFFF

FLAG_NO_KEY = 0x01
FLAG_NO_HEAD_PRESS = 0x02

# Известные keyString Wolf RPG Editor (ASCII). Порядок = от новых к старым:
# игры новее 2.55 (включая исследуемую) открываются 32-байтным ключом.
WOLF_KEYS: list[bytes] = [
    b"WLFRPrO!p(;s5((8P@((UFWlu$#5(=",  # 2.255–2.281 (32 байта)
    b"8P@(rO!p;s58",                    # 2.20–2.24 (12 байт)
    bytes([0x4C, 0xD9, 0x2A, 0xB7, 0x28, 0x9B,
           0xAC, 0x07, 0x3E, 0x77, 0xEC, 0x4C]),  # 2.10
    bytes([0x0F, 0x53, 0xE1, 0x3E, 0x04, 0x37,
           0x12, 0x17, 0x60, 0x0F, 0x53, 0xE1]),  # 1.01–2.02a
]

_DEFAULT_KEY_PAD = b"DXBDXARC\x00"


# ── CRC32 (IEEE) ──

_CRC_TABLE: list[int] | None = None


def _crc32(data: bytes) -> int:
    global _CRC_TABLE
    if _CRC_TABLE is None:
        tbl = []
        for i in range(256):
            c = i
            for _ in range(8):
                c = (c >> 1) ^ 0xEDB88320 if (c & 1) else (c >> 1)
            tbl.append(c & 0xFFFFFFFF)
        _CRC_TABLE = tbl
    crc = 0xFFFFFFFF
    for b in data:
        crc = _CRC_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF


def make_base_key(key_string: bytes) -> bytes:
    """7-байтный XOR-ключ из keyString (чётные/нечётные байты -> CRC32)."""
    src = bytes(key_string) if key_string else b""
    if len(src) < 4:
        src = src + _DEFAULT_KEY_PAD
    even = bytes(src[i] for i in range(0, len(src), 2))
    odd = bytes(src[i] for i in range(1, len(src), 2))
    c0 = _crc32(even)
    c1 = _crc32(odd)
    return bytes([(c0 >> 0) & 0xFF, (c0 >> 8) & 0xFF,
                  (c0 >> 16) & 0xFF, (c0 >> 24) & 0xFF,
                  (c1 >> 0) & 0xFF, (c1 >> 8) & 0xFF,
                  (c1 >> 16) & 0xFF])


def _xor(data: bytearray, key: bytes, pos: int) -> None:
    if not key:
        return
    k = len(key)
    j = pos % k
    for i in range(len(data)):
        data[i] ^= key[j]
        j += 1
        if j == k:
            j = 0


# ── LZ (DXA, LZSS-вариант) ──

def lz_decode(src: bytes) -> bytes:
    """Распаковка DXA-LZ блока. src включает 9-байтный заголовок."""
    if len(src) < 9:
        raise ValueError("lz block too small")
    dest_size = struct.unpack("<I", src[0:4])[0]
    src_size = struct.unpack("<I", src[4:8])[0] - 9
    keycode = src[8]
    sp = src[9:]
    if len(sp) < src_size:
        raise ValueError("lz truncated")
    out = bytearray(dest_size)
    tp = 0
    p = 0
    MIN_COMPRESS = 4
    while src_size > 0:
        b = sp[p]
        if b != keycode:
            out[tp] = b
            tp += 1
            p += 1
            src_size -= 1
            continue
        if sp[p + 1] == keycode:
            out[tp] = keycode
            tp += 1
            p += 2
            src_size -= 2
            continue
        code = sp[p + 1]
        if code > keycode:
            code -= 1
        p += 2
        src_size -= 2
        combo = code >> 3
        if code & (1 << 2):
            combo |= sp[p] << 5
            p += 1
            src_size -= 1
        combo += MIN_COMPRESS
        idx_size = code & 0x3
        if idx_size == 0:
            index = sp[p]
            p += 1
            src_size -= 1
        elif idx_size == 1:
            index = sp[p] | (sp[p + 1] << 8)
            p += 2
            src_size -= 2
        else:
            index = sp[p] | (sp[p + 1] << 8) | (sp[p + 2] << 16)
            p += 3
            src_size -= 3
        index += 1
        # копирование с перекрытием (memmove-семантика)
        if index < combo:
            # короткие дистанции — побайтно, чтобы перекрытие работало
            for _ in range(combo):
                out[tp] = out[tp - index]
                tp += 1
        else:
            for _ in range(combo):
                out[tp] = out[tp - index]
                tp += 1
    return bytes(out[:tp])


# ── Huffman (DXA) ──

class _BitReader:
    def __init__(self, buf: bytes):
        self._buf = buf
        self._byte = 0
        self._bit = 0

    def read(self, n: int) -> int:
        r = 0
        for i in range(n):
            b = self._buf[self._byte]
            r |= ((b >> (7 - self._bit)) & 1) << (n - 1 - i)
            self._bit += 1
            if self._bit == 8:
                self._byte += 1
                self._bit = 0
        return r

    def consumed(self) -> int:
        return self._byte + (1 if self._bit else 0)


def huffman_decode(press: bytes, dest_size_hint: int = 0) -> bytes:
    """Полная распаковка Huffman-блока DXA. Возвращает сырые байты.

    Семантика DXLib: дерево из таблицы весов, поиск по 9-битной таблице
    префиксов для основной части потока, побитный спуск для хвоста.
    Заголовок весов читается MSB-first, пейлоад — LSB-first.
    """
    br = _BitReader(press)
    orig_size = br.read(br.read(6) + 1)
    _press_size = br.read(br.read(6) + 1)
    weights: list[int] = [0] * 256
    bitn = (br.read(3) + 1) * 2
    br.read(1)  # знак weight[0]: читается, но не используется (как в DXLib)
    weights[0] = br.read(bitn)
    for i in range(1, 256):
        bitn = (br.read(3) + 1) * 2
        minus = br.read(1)
        save = br.read(bitn)
        weights[i] = (weights[i - 1] - save) & 0xFFFF if minus \
            else (weights[i - 1] + save) & 0xFFFF
    head_size = br.consumed()
    if orig_size == 0:
        return b""
    # дерево: 256 листьев + 255 внутренних (510 — корень)
    NN = 256 + 255
    weight = weights + [0] * 255
    parent = [-1] * NN
    child0 = [-1] * NN
    child1 = [-1] * NN
    node_num = 256
    remaining = 256
    while remaining > 1:
        m1 = m2 = -1
        for idx in range(node_num):
            if parent[idx] != -1:
                continue
            if m1 == -1 or weight[idx] < weight[m1]:
                m2 = m1
                m1 = idx
            elif m2 == -1 or weight[idx] < weight[m2]:
                m2 = idx
        parent[m1] = parent[m2] = node_num
        child0[node_num] = m1
        child1[node_num] = m2
        weight[node_num] = (weight[m1] + weight[m2]) & 0xFFFFFFFF
        node_num += 1
        remaining -= 1
    # коды узлов (LSB-first целые + длины) для таблицы префиксов
    code_len = [0] * NN
    code_val = [0] * NN
    for i in range(256 + 254):
        bits: list[int] = []
        n = i
        while parent[n] != -1:
            p = parent[n]
            bits.append(0 if child0[p] == n else 1)
            n = p
        bits.reverse()
        v = 0
        for k, b in enumerate(bits):
            v |= (b & 1) << k
        code_len[i] = len(bits)
        code_val[i] = v
    masks = [(1 << (i + 1)) - 1 for i in range(16)]
    table = [-1] * 512
    for i in range(512):
        for j in range(256 + 254):
            nb = code_len[j]
            if nb == 0 or nb > 9:
                continue
            if (i & masks[nb - 1]) == (code_val[j] & masks[nb - 1]):
                table[i] = j
                break
    data = press[head_size:]
    out = bytearray(orig_size)
    pos = 0          # индекс текущего байта в data
    bitpos = 0       # сколько бит уже съедено из data[pos] (0..7)
    cur = data[0] if data else 0
    for o in range(orig_size):
        if o >= orig_size - 17:
            node = 510
        else:
            if bitpos == 8:
                pos += 1
                cur = data[pos] if pos < len(data) else 0
                bitpos = 0
            nxt = data[pos + 1] if pos + 1 < len(data) else 0
            key9 = (cur | (nxt << (8 - bitpos))) & 0x1FF
            node = table[key9]
            if node < 0:
                node = 510
            else:
                bitpos += code_len[node]
                if bitpos >= 16:
                    pos += 2
                    bitpos -= 16
                    cur = data[pos] >> bitpos if pos < len(data) else 0
                elif bitpos >= 8:
                    pos += 1
                    bitpos -= 8
                    cur = data[pos] >> bitpos if pos < len(data) else 0
                else:
                    cur >>= code_len[node]
                if node < 256:
                    out[o] = node
                    continue
        while node > 255:
            if bitpos == 8:
                pos += 1
                cur = data[pos] if pos < len(data) else 0
                bitpos = 0
            bit = cur & 1
            cur >>= 1
            bitpos += 1
            node = child1[node] if bit else child0[node]
        out[o] = node
    return bytes(out)


# ── Структуры каталога ──

@dataclass
class WolfFileInfo:
    name: str                    # имя внутри архива (как хранится)
    data_address: int            # смещение от dataStart
    data_size: int               # распакованный размер
    press_size: int              # LZ-размер (NO_COMPRESS = без сжатия)
    huff_size: int               # Huffman-размер (NO_COMPRESS = без)
    key: bytes = b""             # персональный XOR-ключ (7 байт)
    is_dir: bool = False


@dataclass
class WolfArchive:
    path: str
    head_size: int = 0
    data_start: int = 0
    codepage: int = 932
    flags: int = 0
    huff_kb: int = 0
    files: list[WolfFileInfo] = field(default_factory=list)
    _key_string: bytes = b""

    @property
    def no_key(self) -> bool:
        return bool(self.flags & FLAG_NO_KEY)


def _decode_name(raw: bytes) -> str:
    for enc in ("utf-8", "cp932"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return raw.decode("cp932", errors="replace")


def _read_tables(arc_path: str, key_string: bytes) -> WolfArchive:
    """Читает и расшифровывает таблицы архива (без распаковки содержимого)."""
    with open(arc_path, "rb") as f:
        head_raw = f.read(_HEAD_STRUCT.size)
        if len(head_raw) < _HEAD_STRUCT.size:
            raise ValueError("too small for DXA8")
        (magic, ver, head_size, data_start, fname_start, ftable_start,
         dtable_start, codepage, flags, huff_kb, _res, _last) = \
            _HEAD_STRUCT.unpack(head_raw)
        if magic != DX_MAGIC:
            raise ValueError("not a DX archive")
        if ver != DX_VER_8:
            raise ValueError(f"unsupported DXA version {ver} (need v8)")
        arc = WolfArchive(path=arc_path, head_size=head_size,
                          data_start=data_start, codepage=codepage,
                          flags=flags, huff_kb=huff_kb,
                          _key_string=bytes(key_string))
        f.seek(0, os.SEEK_END)
        file_size = f.tell()
        f.seek(fname_start)
        huff_head_size = file_size - f.tell()
        if huff_head_size <= 0:
            raise ValueError("bad header addresses")
        blob = bytearray(f.read(huff_head_size))
        base_key = b"" if (flags & FLAG_NO_KEY) else make_base_key(key_string)
        if base_key:
            _xor(blob, base_key, 0)
        if flags & FLAG_NO_HEAD_PRESS:
            head_buf = bytes(blob[:head_size])
        else:
            lz_buf = huffman_decode(bytes(blob))
            head_buf = lz_decode(lz_buf)
        if len(head_buf) < head_size:
            raise ValueError("header decode short")
        name_table = head_buf[:ftable_start]
        file_table = head_buf[ftable_start:dtable_start]
        dir_table = head_buf[dtable_start:]
        # корневой каталог — первая DARC_DIRECTORY
        if len(dir_table) < _DIR_STRUCT.size:
            raise ValueError("dir table too small")
        (root_dir_addr, root_parent, root_num, root_head) = \
            _DIR_STRUCT.unpack(dir_table[:_DIR_STRUCT.size])
        # рекурсивный обход каталогов
        out: list[WolfFileInfo] = []

        def _name_at(addr: int) -> tuple[str, bytes]:
            # Запись имени: первый БАЙТ — число 4-байтных единиц до
            # настоящего имени (пропускаем верхнерегистровый ключ для
            # keyCreate + выравнивание), далее null-terminated строка.
            # Повторяет getOriginalFileName DXA: table[0]*4+4.
            # Для персонального ключа файла DXA берёт ПЕРВУЮ строку записи
            # (верхний регистр, смещение addr+4 до \x00) — возвращаем её
            # как key_raw отдельно от отображаемого имени.
            if addr + 1 > len(name_table):
                return "", b""
            skip = name_table[addr]
            start = addr + skip * 4 + 4
            if start > len(name_table):
                return "", b""
            end = name_table.find(b"\x00", start)
            if end < 0:
                end = len(name_table)
            raw = name_table[start:end]
            kend = name_table.find(b"\x00", addr + 4)
            if kend < 0:
                kend = len(name_table)
            key_raw = bytes(name_table[addr + 4:kend])
            return _decode_name(raw), key_raw

        def _walk(dir_off: int, _depth: int = 0):
            if _depth > 32:
                return
            (d_addr, d_parent, d_num, d_head) = _DIR_STRUCT.unpack(
                dir_table[dir_off:dir_off + _DIR_STRUCT.size])
            for i in range(d_num):
                fo = d_head + i * _FILEHEAD_STRUCT.size
                (nm_addr, attrs, _c, _a, _w, d_addr2, d_size,
                 p_size, h_size) = _FILEHEAD_STRUCT.unpack(
                    file_table[fo:fo + _FILEHEAD_STRUCT.size])
                if attrs & 0x10:  # FILE_ATTRIBUTE_DIRECTORY
                    _walk(d_addr2, _depth + 1)
                else:
                    nm, raw = _name_at(nm_addr)
                    out.append(WolfFileInfo(
                        name=nm, data_address=d_addr2, data_size=d_size,
                        press_size=p_size, huff_size=h_size))
                    # сохраняем raw для ключа
                    out[-1].key = raw  # временно: raw имени
        _walk(0)
        # персональные ключи файлов (нужны raw имён + родители; родители
        # для плоских архивов Woditor — корень, т.е. только имя)
        if not (flags & FLAG_NO_KEY):
            for fi in out:
                raw = fi.key if isinstance(fi.key, bytes) else b""
                buf = bytes(key_string) + raw
                fi.key = make_base_key(buf[:2048])
        else:
            for fi in out:
                fi.key = b""
        arc.files = out
        return arc


def list_archive(arc_path: str, key_string: bytes | None = None):
    """Список файлов архива (имена + размеры). Ключ — явный или автодетект."""
    keys = [key_string] if key_string else list(WOLF_KEYS)
    last_err: Exception | None = None
    for k in keys:
        try:
            arc = _read_tables(arc_path, bytes(k))
            if arc.files:
                return arc
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise ValueError(f"cannot open {os.path.basename(arc_path)}: {last_err}")


def detect_key(arc_path: str) -> bytes | None:
    """Автодетект keyString перебором известных ключей (быстро: только шапка)."""
    for k in WOLF_KEYS:
        try:
            arc = _read_tables(arc_path, k)
            if arc.files:
                return k
        except Exception:  # noqa: BLE001
            continue
    return None


def extract_file(arc: WolfArchive, info: WolfFileInfo) -> bytes:
    """Распаковка одного файла архива в память."""
    if info.data_size == 0:
        return b""
    with open(arc.path, "rb") as f:
        f.seek(arc.data_start + info.data_address)
        comp = info.press_size != _NO_COMPRESS
        huff = info.huff_size != _NO_COMPRESS
        key = info.key or b""
        if huff:
            want = info.press_size if comp else info.data_size
            total = info.huff_size + want
            # DXA8: хвост может читаться вторым проходом (huffmanKB);
            # упрощённо читаем весь нужный диапазон сразу — покрывает
            # файлы перевода (.dat/.mps, до десятков МБ).
            raw = bytearray(f.read(info.huff_size))
            if key and not arc.no_key:
                _xor(raw, key, info.data_size)
            plain_huff = huffman_decode(bytes(raw))
            # huffmanKB-перестановка середины (большие файлы)
            if (arc.huff_kb != 0xFF and want > arc.huff_kb * 1024 * 2):
                # середина зашифрована отдельно — дочитываем и ксорим
                mid_size = want - arc.huff_kb * 1024 * 2
                mid = bytearray(f.read(mid_size))
                if key and not arc.no_key:
                    _xor(mid, key,
                         info.data_size + info.huff_size)
                # вставляем середину между головой и хвостом huffman-потока
                head = arc.huff_kb * 1024
                plain = (plain_huff[:head] + bytes(mid)
                         + plain_huff[head:])
                plain_huff = plain[:want]
            if comp:
                return lz_decode(plain_huff)
            return plain_huff[:info.data_size]
        if comp:
            raw = bytearray(f.read(info.press_size))
            if key and not arc.no_key:
                _xor(raw, key, info.data_size)
            return lz_decode(bytes(raw))
        # без сжатия — потоковое чтение с XOR
        out = bytearray()
        left = info.data_size
        off = 0
        while left > 0:
            chunk = bytearray(f.read(min(1 << 20, left)))
            if not chunk:
                break
            if key and not arc.no_key:
                _xor(chunk, key, info.data_size + off)
            out += chunk
            off += len(chunk)
            left -= len(chunk)
        return bytes(out)

# -*- coding: utf-8 -*-
"""Сейвы SugarCube (.save): чтение и запись переменных.

Формат экспортированного .save: base64-строка LZ-String
(LZString.compressToBase64) над JSON-объектом:
    {"id": ..., "state": {"index": N, "history": [{"variables": {...}}]}}
Текущие переменные — в history[state.index - 1] (активный момент).

LZ-String портирован с референс-реализации (MIT, pieroxy/lz-string) —
самодостаточно, без внешних зависимостей.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import time
from datetime import datetime

_B64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="


# ---------- LZ-String (порт референса) ----------

def _decompress(length: int, reset_value: int, get_next_value) -> str | None:
    dictionary = list(range(3))
    enlarge_in = 4
    dict_size = 4
    num_bits = 3
    result: list[str] = []

    data_val = get_next_value(0)
    data_position = reset_value
    data_index = 1

    def read_bits(n: int) -> int:
        nonlocal data_val, data_position, data_index
        bits = 0
        power = 1
        maxpower = 1 << n
        while power != maxpower:
            resb = data_val & data_position
            data_position >>= 1
            if data_position == 0:
                data_position = reset_value
                if data_index >= length:
                    data_val = 0
                else:
                    data_val = get_next_value(data_index)
                data_index += 1
            bits |= (1 if resb > 0 else 0) * power
            power <<= 1
        return bits

    nxt = read_bits(2)
    if nxt == 0:
        c = chr(read_bits(8))
    elif nxt == 1:
        c = chr(read_bits(16))
    else:
        return ""
    dictionary.append(c)
    w = c
    result.append(c)

    while True:
        if data_index > length:
            return ""
        nxt = read_bits(num_bits)
        if nxt == 0:
            dictionary.append(chr(read_bits(8)))
            nxt = dict_size            # индекс только что добавленного
            dict_size += 1
            enlarge_in -= 1
        elif nxt == 1:
            dictionary.append(chr(read_bits(16)))
            nxt = dict_size            # индекс только что добавленного
            dict_size += 1
            enlarge_in -= 1
        elif nxt == 2:
            return "".join(result)
        # nxt >= 3 — индекс в словаре, проваливаемся ниже
        if enlarge_in == 0:
            enlarge_in = 1 << num_bits
            num_bits += 1
        if nxt < len(dictionary) and dictionary[nxt] is not None:
            entry = dictionary[nxt]
        elif nxt == dict_size:
            entry = w + w[0]
        else:
            return None
        result.append(entry)
        dictionary.append(w + entry[0])
        dict_size += 1
        enlarge_in -= 1
        w = entry
        if enlarge_in == 0:
            enlarge_in = 1 << num_bits
            num_bits += 1


def lz_decompress_base64(compressed: str) -> str | None:
    """LZString.decompressFromBase64."""
    compressed = compressed.strip()
    return _decompress(len(compressed), 32,
                       lambda i: _B64_ALPHABET.find(compressed[i]))


def _compress(uncompressed: str, bits_per_char: int, get_char_from_int) -> str:
    if uncompressed is None:
        return ""

    context_dictionary: dict = {}
    context_dictionary_to_create: dict = {}
    context_w = ""
    context_enlarge_in = 2.0
    context_dict_size = 3
    context_num_bits = 2
    context_data: list[str] = []
    context_data_val = 0
    context_data_position = 0

    def emit_bit(bit: int):
        nonlocal context_data_val, context_data_position
        context_data_val = (context_data_val << 1) | bit
        if context_data_position == bits_per_char - 1:
            context_data_position = 0
            context_data.append(get_char_from_int(context_data_val))
            context_data_val = 0
        else:
            context_data_position += 1

    def emit_value(value: int, num_bits: int):
        for i in range(num_bits):
            emit_bit(value & 1)
            value >>= 1

    for c in uncompressed:
        if c not in context_dictionary:
            context_dictionary[c] = context_dict_size
            context_dict_size += 1
            context_dictionary_to_create[c] = True
        wc = context_w + c
        if wc in context_dictionary:
            context_w = wc
        else:
            if context_w in context_dictionary_to_create:
                if ord(context_w[0]) < 256:
                    emit_value(0, context_num_bits)
                    emit_value(ord(context_w[0]), 8)
                else:
                    emit_value(1, context_num_bits)
                    emit_value(ord(context_w[0]), 16)
                context_enlarge_in -= 1
                if context_enlarge_in == 0:
                    context_enlarge_in = float(2 ** context_num_bits)
                    context_num_bits += 1
                del context_dictionary_to_create[context_w]
            else:
                emit_value(context_dictionary[context_w], context_num_bits)
            context_enlarge_in -= 1
            if context_enlarge_in == 0:
                context_enlarge_in = float(2 ** context_num_bits)
                context_num_bits += 1
            context_dictionary[wc] = context_dict_size
            context_dict_size += 1
            context_w = c

    if context_w:
        if context_w in context_dictionary_to_create:
            if ord(context_w[0]) < 256:
                emit_value(0, context_num_bits)
                emit_value(ord(context_w[0]), 8)
            else:
                emit_value(1, context_num_bits)
                emit_value(ord(context_w[0]), 16)
            context_enlarge_in -= 1
            if context_enlarge_in == 0:
                context_enlarge_in = float(2 ** context_num_bits)
                context_num_bits += 1
            del context_dictionary_to_create[context_w]
        else:
            emit_value(context_dictionary[context_w], context_num_bits)
        context_enlarge_in -= 1
        if context_enlarge_in == 0:
            context_enlarge_in = float(2 ** context_num_bits)
            context_num_bits += 1

    emit_value(2, context_num_bits)

    while True:
        context_data_val <<= 1
        if context_data_position == bits_per_char - 1:
            context_data.append(get_char_from_int(context_data_val))
            break
        context_data_position += 1

    return "".join(context_data)


def lz_compress_base64(text: str) -> str:
    """LZString.compressToBase64."""
    res = _compress(text, 6, lambda a: _B64_ALPHABET[a])
    mod = len(res) % 4
    return res + "=" * ((4 - mod) % 4) if mod else res


# ---------- сейв SugarCube ----------

def load_save(path: str) -> dict:
    """Читает .save -> разобранный словарь состояния."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    text = lz_decompress_base64(raw)
    if not text:
        raise ValueError("Не SugarCube-сейв (LZ-String не раскодировался)")
    data = json.loads(text)
    if not isinstance(data, dict) or "state" not in data:
        raise ValueError("Не SugarCube-сейв (нет state)")
    return data


def write_save(path: str, data: dict, backup: bool = True):
    """Записывает словарь состояния обратно в .save (с бэкапом)."""
    if backup and os.path.exists(path) \
            and not os.path.exists(path + ".ob_backup"):
        shutil.copy2(path, path + ".ob_backup")
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(lz_compress_base64(text))


def _deep_merge(base: dict, extra: dict) -> dict:
    """base + extra рекурсивно (как SugarCube State.deltaDecode)."""
    out = dict(base)
    for k, v in extra.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _moments(state: dict) -> list:
    return state.get("history") or state.get("delta") or []


def _current_moment(data: dict) -> dict | None:
    state = data.get("state") or {}
    moments = _moments(state)
    index = state.get("index", len(moments))
    if 1 <= index <= len(moments):
        return moments[index - 1]
    return moments[-1] if moments else None


def get_variables(data: dict) -> dict:
    """Текущие переменные игры: полный декод (history | delta)."""
    state = data.get("state") or {}
    moments = _moments(state)
    if not moments:
        return {}
    if state.get("delta"):
        # delta-формат: первый момент полный, дальше — диффы до активного
        index = state.get("index", len(moments))
        index = max(1, min(index, len(moments)))
        merged: dict = {}
        for moment in moments[:index]:
            variables = moment.get("variables")
            if isinstance(variables, dict):
                merged = _deep_merge(merged, variables)
        return merged
    moment = _current_moment(data) or {}
    variables = moment.get("variables")
    return variables if isinstance(variables, dict) else {}


_PATH_PART = re.compile(r"^([^\[\]]*)((?:\[\d+\])*)$")
_PATH_IDX = re.compile(r"\[(\d+)\]")


def _path_parts(dotted: str) -> list:
    """'a.b[0].c' → [('key','a'), ('key','b'), ('idx',0), ('key','c')]."""
    parts = []
    for seg in str(dotted).split("."):
        m = _PATH_PART.match(seg)
        if not m:
            continue
        if m.group(1):
            parts.append(("key", m.group(1)))
        for im in _PATH_IDX.finditer(m.group(2)):
            parts.append(("idx", int(im.group(1))))
    return parts


def _set_nested(target: dict, dotted: str, value):
    """Записывает значение по dot-path с поддержкой индексов списков
    ('flags[0]', 'inv[1].qty'). Следующий сегмент пути заранее известен —
    промежуточные контейнеры создаются сразу нужного типа."""
    parts = _path_parts(dotted)
    if not parts:
        return
    node: object = target
    for i, (kind, key) in enumerate(parts[:-1]):
        nxt = parts[i + 1][0]
        if kind == "key":
            child = node.get(key) if isinstance(node, dict) else None
            if not isinstance(child, (dict, list)):
                child = [] if nxt == "idx" else {}
                if isinstance(node, dict):
                    node[key] = child
            node = child
        else:
            if not isinstance(node, list):
                node = []
            while len(node) <= key:
                node.append([] if nxt == "idx" else {})
            node = node[key]
    last_kind, last_key = parts[-1]
    if last_kind == "key":
        if isinstance(node, dict):
            node[last_key] = value
    else:
        if not isinstance(node, list):
            node = []
        while len(node) <= last_key:
            node.append(None)
        node[last_key] = value


def set_variables(data: dict, updates: dict):
    """Обновляет переменные (dot-path) в активном моменте сейва.

    Для delta-формата правки вливаются в последний момент — при декоде
    они применятся поверх предыдущих состояний, т.е. текущее состояние
    игры изменится, а «отмотка» истории сохранит старые значения.
    """
    moment = _current_moment(data)
    if moment is None:
        raise ValueError("В сейве нет активного момента")
    variables = moment.setdefault("variables", {})
    for dotted, value in updates.items():
        _set_nested(variables, dotted, value)


def flatten_variables(variables: dict, max_depth: int = 50) -> dict:
    """ВСЕ значения дерева переменных → плоский dict, ничего не теряется.

    Словари — точками ('player.money'), списки/кортежи — индексами
    ('flags[0]'), прочие объекты — строкой, пустые контейнеры — '{}'/'[]'.
    """
    out: dict = {}

    def walk(node, path: str, depth: int):
        if depth > max_depth:
            return
        if isinstance(node, dict):
            if not node:
                out[path] = "{}"
                return
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else str(k), depth + 1)
        elif isinstance(node, (list, tuple)):
            if not node:
                out[path] = "[]"
                return
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]", depth + 1)
        elif isinstance(node, (int, float, str, bool)) or node is None:
            out[path] = node
        else:
            out[path] = str(node)

    if isinstance(variables, dict):
        walk(variables, "", 0)
    return out


def write_slots(game_dir: str, base_name: str, slots: list,
                fallback_ts: str | None = None) -> list[str]:
    """Слоты игры (id/date/data-LZ-b64) → .save файлы в папку игры.

    Имя файла: '<игра>-<дата слота>-slot<id>.save'. Повторный синк
    перезаписывает те же файлы — дубли не копятся. Возвращает пути
    записанных файлов.
    """
    safe = re.sub(r'[^\w .\-()]+', '_', base_name or 'game').strip() or 'game'
    safe = safe[:60]
    written = []
    for s in slots or []:
        data = s.get('data')
        if not isinstance(data, str) or not data:
            continue
        sid = str(s.get('id', 'x'))
        stamp = fallback_ts or time.strftime('%Y%m%d-%H%M%S')
        date = s.get('date')
        if date:
            try:
                stamp = datetime.fromtimestamp(
                    int(date) / 1000).strftime('%Y%m%d-%H%M%S')
            except (ValueError, OSError, OverflowError):
                pass
        path = os.path.join(game_dir, f'{safe}-{stamp}-slot{sid}.save')
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(data)
        except OSError:
            continue
        written.append(path)
    return written


def find_saves(game_dir: str) -> list[str]:
    """*.save рядом с игрой: в папке игры и на уровень выше."""
    found = []
    roots = [game_dir, os.path.dirname(os.path.normpath(game_dir))]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for f in sorted(os.listdir(root)):
            if f.lower().endswith(".save"):
                p = os.path.join(root, f)
                if p not in found:
                    found.append(p)
    return found

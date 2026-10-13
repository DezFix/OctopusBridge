# -*- coding: utf-8 -*-
"""Файловый перевод игр на движке Godot (4.x): детект, извлечение, внедрение.

Что переводим (по убыванию надёжности):

1. ``.csv`` — штатный механизм переводов Godot (``locale/translation.csv``,
   колонка 0 = ключи, остальные колонки = языки). Самый надёжный случай:
   перевод меняет только значение, ключи остаются как были.
2. ``.tscn`` / ``.tres`` — текстовый формат сцен и ресурсов. Берём ТОЛЬКО
   значения известных текстовых свойств (``text``, ``placeholder_text``,
   ``tooltip_text``, ``title``, ``dialog_text``, ...) из белого списка.
   Служебное (``path="res://..."``, ``ExtResource("1_abc")``,
   ``script = ExtResource(...)``) в белый список не входит.
3. ``.gd`` — исходники GDScript: все строковые литералы, прошедшие
   фильтры безопасности. Комментарии отбрасывает сканер, поэтому
   ``# player's save`` записью не станет.
4. ``.gdc`` (скомпилированный GDScript), бинарные ``.scn``/``.res``/
   ``.translation``, зашифрованные пакеты, self-contained exe и ``.zip``
   НЕ трогаем — считаем и показываем отдельными числами (см. ``scan``).

Фильтры безопасности («лучше пропустить строку, чем убить игру»,
``app/engines/protocol.py:96-97``): пути ресурсов, идентификаторы, строки
без букв, слишком короткие, плейсхолдеры формата. Каждый пропуск записи
обязан получить причину — она уходит в ``skipped_by`` и в ``on_skip``.

Позиция записи выводится из структуры заново: ``line[N].str[M]`` — M-я
(с единицы) кавычная строка в строке N файла-сцены/скрипта,
``line[N].col[C]`` — поле CSV с индексом C (с нуля, как их нумерует сам
парсер Godot) в строке N. Перед подстановкой текущее значение сверяется с
``original``; не сошлось — пропуск с причиной, а не порча игры.

Запись в ``.pck`` идёт через ``app/core/godot/pck.py``: полный бэкап до
изменений (атомарно, потоком, со сверкой размера), потоковая пересборка с
теми же путями и порядком записей, обязательная проверка перечитыванием
ВМЕСТЕ с чтением байтов блобов; расхождение — откат из бэкапа и причина в
``verify_failed``. Всё, что происходит после первой записи, под
``try/except``: ``apply`` не имеет права бросить исключение, когда файл
игры уже изменён, — UI обязан получить отчёт, а не traceback.

Версия пакета проверяется по константам движка: раскладку, которую модуль
не умеет (Godot 3.x — заголовок 88 байт, а это другая физическая
структура, не «старая v2»), мы не трогаем, а показываем числом
(``unsupported:version:N``). Читаются и пересобираются обе раскладки 4.x:
v2 (Godot 4.0-4.3) и v3 (4.5+/4.6), причём пересборка ВСЕГДА пишет
версию исходного пакета — «улучшать» её молча нельзя. Записи v3 с
флагами ``PACK_FILE_REMOVAL`` (файл удалён) и ``PACK_FILE_DELTA``
(патч) не переводятся, считаются отдельными числами и при пересборке
сохраняются как есть; ``PACK_SPARSE_BUNDLE`` — честный отказ.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil

from app.core.godot import pck
from app.core.io import BackupStore, atomic_write_bytes, atomic_write_json
from app.core.models import TranslationEntry

# ── что вообще смотрим ──

_TEXT_EXTS = (".csv", ".tscn", ".tres", ".gd")
#: бинарные форматы Godot того же смысла — считаем, но НЕ трогаем
_BINARY_EXTS = (".scn", ".res", ".translation")
_GDC_EXT = ".gdc"
_SCAN_EXTS = tuple(sorted(set(_TEXT_EXTS + _BINARY_EXTS + (_GDC_EXT,))))

_SKIP_DIRS = {"backup", "node_modules"}

#: Текстовые свойства сцены/ресурса. Список СПЕЦИАЛЬНЫЙ: любое незнакомое
#: свойство не переводится. Иначе `name="Button_2"`-подобные служебные
#: значения попадают в перевод, а игра перестаёт находить свой узел.
_SCENE_TEXT_KEYS = frozenset({
    "text", "placeholder_text", "tooltip_text", "title", "dialog_text",
    "description", "hint_text", "header", "label", "prompt", "message",
    "window_title", "confirm_text", "ok_text", "cancel_text", "item_text",
    "tab_title",
})
_ARRAY_WRAPPERS = ("PackedStringArray(", "PoolStringArray(")
_ASSIGN_RE = re.compile(r"^(\s*)([A-Za-z_][\w/]*)\s*=\s*(.*)$")

# ── фильтры безопасности ──

def _has_letters(text: str) -> bool:
    return any(ch.isalpha() for ch in text)


#: Button, id_12345, Button_2, Some.State — служебное, не текст
_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+(?:[.#][A-Za-z0-9_]+)*$")
#: "имя.расширение" — кандидат на ресурс
_FILE_PATH_RE = re.compile(r"^\S+\.([A-Za-z0-9]{1,6})$")
#: расширения, которые движок открывает сам (Godot + частые импорты).
#: По этому списку "icon.png" отсеивается как ресурс, а "Some.State"
#: остаётся идентификатором и отсеивается как идентификатор.
_GODOT_EXTS = frozenset({
    "csv", "tscn", "tres", "gd", "gdc", "scn", "res", "translation",
    "png", "jpg", "jpeg", "bmp", "svg", "webp", "ttf", "otf", "woff",
    "woff2", "ogg", "wav", "mp3", "obj", "glb", "gltf", "import", "cfg",
    "json", "txt", "xml", "html", "shader", "gdshader", "theme",
    "anim", "fnt", "material", "mat",
})
#: схемы Godot, которые движок открывает сам — их перевод ломает загрузку
_SCHEME_RE = re.compile(r"(res://|user://|uid://)")

#: printf / str.format / String.format плейсхолдеры
_PH_RE = re.compile(
    r"%(?:\([^)]*\))?[-+ #0]*[\d*]*(?:\.[\d*]+)?[A-Za-z%{]"
    r"|\{[^{}]*\}"
    r"|%\{[A-Za-z_]\w*\}"
)


def reject_reason(original: str) -> str | None:
    """Причина отказа от строки-кандидата или None (строка годится)."""
    s = original.strip()
    if len(s) < 2:
        return "too short"
    if not _has_letters(s):
        return "no letters"
    if _SCHEME_RE.search(s):
        return "path"
    if "\\" in s:
        return "path"
    m = _FILE_PATH_RE.match(s)
    if m and m.group(1).lower() in _GODOT_EXTS:
        return "path"
    # путь без пробелов (text/left). С пробелом — обычный текст ("OK/Cancel")
    if " " not in s and "/" in s:
        return "path"
    if _IDENT_RE.match(s):
        return "identifier"
    if len(s) > 4000:
        return "too long"
    return None


def _placeholders(text: str) -> tuple:
    return tuple(sorted(_PH_RE.findall(text)))


def translation_reason(original: str, translation: str,
                       multiline_ok: bool = True) -> str | None:
    """Можно ли класть перевод в строку вместо оригинала. None = можно."""
    if not translation or not translation.strip():
        return "empty translation"
    if "\x00" in translation:
        return "control chars"
    if not multiline_ok and ("\n" in translation or "\r" in translation):
        return "control chars"
    if _placeholders(original) != _placeholders(translation):
        # перевод потерял или надумал %s/{0} — движок покажет мусор
        return "placeholder"
    return None


# ── экранирование (одинаково для .tscn/.tres/.gd — C-подобные строки) ──

_UNESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b",
              "f": "\f", "v": "\v", '"': '"', "'": "'", "\\": "\\",
              "0": "\0", "/": "/"}
_HEX = "0123456789abcdefABCDEF"


def unescape(raw: str) -> str:
    """Сырое содержимое кавычного литерала -> текст для переводчика."""
    out: list[str] = []
    i, n = 0, len(raw)
    while i < n:
        ch = raw[i]
        if ch != "\\" or i + 1 >= n:
            out.append(ch)
            i += 1
            continue
        nxt = raw[i + 1]
        if nxt == "u" and i + 6 <= n:
            hexpart = raw[i + 2:i + 6]
            if len(hexpart) == 4 and all(c in _HEX for c in hexpart):
                out.append(chr(int(hexpart, 16)))
                i += 6
                continue
        if nxt in _UNESCAPES:
            out.append(_UNESCAPES[nxt])
            i += 2
            continue
        # неизвестный escape не трогаем: ломать игру ради косметики глупо
        out.append(ch)
        out.append(nxt)
        i += 2
    return "".join(out)


def escape(text: str) -> str:
    """Текст -> содержимое кавычного литерала .tscn/.tres/.gd."""
    out: list[str] = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\0":
            out.append("\\0")
        else:
            out.append(ch)
    return "".join(out)


def scan_literals(text: str, quotes: str = '"',
                  comments: str = "#;") -> list[tuple[int, int, str]]:
    """Кавычные литералы в КОДЕ строки: ``(start, end_after_quote, raw)``.

    Комментарии отбрасываются. Незакрытая кавычка (многострочный
    ``\"\"\"...\"\"\"`` в GDScript, битая строка) литералом не считается —
    мы скорее пропустим строку, чем разнесём файл.
    """
    out: list[tuple[int, int, str]] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in comments:
            break
        if ch in quotes:
            j = i + 1
            raw: list[str] = []
            closed = False
            while j < n:
                cur = text[j]
                if cur == "\\" and j + 1 < n:
                    raw.append(text[j:j + 2])
                    j += 2
                    continue
                if cur == ch:
                    closed = True
                    break
                raw.append(cur)
                j += 1
            if closed:
                out.append((i, j + 1, "".join(raw)))
                i = j + 1
                continue
            i = j
            continue
        i += 1
    return out


# ── CSV ──

def csv_split(line: str) -> list[tuple[int, int]]:
    """Спаны сырых полей CSV (раскрытие кавычек — отдельно)."""
    spans: list[tuple[int, int]] = []
    i, n = 0, len(line)
    while True:
        start = i
        if i < n and line[i] == '"':
            j = i + 1
            while j < n:
                if line[j] == '"':
                    if j + 1 < n and line[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            end = j + 1 if j < n else n
        else:
            end = line.find(",", i)
            if end == -1:
                end = n
        spans.append((start, end))
        if end >= n:
            break
        i = end + 1
    return spans


def csv_balanced(line: str) -> bool:
    """Ни одно поле строки не «висит» на следующей строке.

    Проверяем ВСЕ колонки, а не первую: ``"ключ",T2 alpha`` выглядит
    законченной строкой, пока не заметишь, что второе поле не закрыто.
    Для такой строки нужен другой разбор — значит, пропуск с причиной.
    """
    raw = line.rstrip("\r\n")
    for start, end in csv_split(raw):
        if raw[start:start + 1] != '"':
            continue
        if end - start < 2 or raw[end - 1:end] != '"':
            return False
    return True


def csv_value(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        return raw[1:-1].replace('""', '"')
    return raw


def csv_quote(text: str) -> str:
    if any(ch in text for ch in ',"\r\n'):
        return '"' + text.replace('"', '""') + '"'
    return text


# ── позиции записей ──

_PATH_RE = re.compile(r"^line\[(\d+)\]\.(str|col)\[(\d+)\]$")


def _entry_value(entry, key: str) -> str:
    if isinstance(entry, dict):
        return entry.get(key, "") or ""
    return getattr(entry, key, "") or ""


def _entry_translation(entry) -> str:
    return _entry_value(entry, "translation")


def _is_writable(entry) -> bool:
    tr = _entry_translation(entry)
    return bool(tr.strip()) and _entry_value(entry, "status") != "skip"


# ── сборщик ──

class _Collector:
    def __init__(self):
        self.entries: list[TranslationEntry] = []
        self.counts: dict[str, int] = {}
        self._next = 1

    def count(self, key: str, n: int = 1):
        if n:
            self.counts[key] = self.counts.get(key, 0) + n

    def add(self, file: str, json_path: str, context: str,
            original: str) -> bool:
        reason = reject_reason(original)
        if reason is not None:
            self.count(f"skipped:{reason}")
            return False
        self.entries.append(TranslationEntry(
            id=self._next, file=file, json_path=json_path,
            context=context, original=original.strip()))
        self._next += 1
        return True


# ── поиск цели ──

def _pck_paths(game_dir: str) -> list[str]:
    try:
        names = sorted(os.listdir(game_dir))
    except OSError:
        return []
    return [os.path.join(game_dir, n) for n in names
            if n.lower().endswith(".pck")
            and os.path.isfile(os.path.join(game_dir, n))]


def find_pck(game_dir: str) -> tuple[str | None, int]:
    """``(путь к .pck, сколько .pck проигнорировано)``.

    Цель одна: несколько .pck (база + DLC) по ``res://``-пути не различить,
    а ошибка в выборе пакета = запись перевода не туда. Остальные честно
    отмечаются счётчиком ``unsupported:multi-pack``.
    """
    found: str | None = None
    extra = 0
    for path in _pck_paths(game_dir):
        try:
            header = pck.read_header(path)
        except (pck.PckEncrypted, pck.PckVersion, pck.PckUnsupported):
            # увидим, но честно откажемся при разборе — с ЧИСЛОМ причины
            if found is None:
                found = path
            else:
                extra += 1
            continue
        except pck.PckError:
            continue
        if header.embedded:
            continue
        if found is None:
            found = path
        else:
            extra += 1
    return found, extra


def _pck_problem(game_dir: str) -> str | None:
    """Почему ни один .pck в папке не подошёл: 'encrypted' | 'version' | 'format'."""
    for path in _pck_paths(game_dir):
        try:
            pck.read_header(path)
        except pck.PckEncrypted:
            return "unsupported:encrypted"
        except pck.PckVersion as exc:
            return _version_reason(exc)
        except pck.PckUnsupported as exc:
            return exc.reason
        except pck.PckError:
            return "unsupported:format"
    return None


def _version_reason(exc: pck.PckVersion) -> str:
    """Причина отказа по версии — с ЧИСЛОМ, а не «что-то не так»."""
    return f"unsupported:version:{exc.version}"


def _iter_loose(game_dir: str):
    """Текстовые и «считаемые» файлы распакованного проекта."""
    for root, dirs, files in os.walk(game_dir):
        dirs[:] = sorted(d for d in dirs
                         if not d.startswith(".") and d not in _SKIP_DIRS)
        for fn in sorted(files):
            if os.path.splitext(fn)[1].lower() not in _SCAN_EXTS:
                continue
            abs_path = os.path.join(root, fn)
            rel = os.path.relpath(abs_path, game_dir).replace(os.sep, "/")
            yield abs_path, rel


# ── детект ──

def _exe_has_pck_trailer(path: str) -> bool:
    """Self-contained exe: в конце файла трейлер pck (fap.cpp:171-193)."""
    try:
        size = os.path.getsize(path)
        if size < pck.TRAILER_SIZE + pck.HEADER_SIZE:
            return False
        with open(path, "rb") as f:
            f.seek(size - pck.TRAILER_SIZE)
            raw = f.read(8)
            if len(raw) != 8:
                return False
            start = size - pck.TRAILER_SIZE - int.from_bytes(raw, "little")
            if start < 0:
                return False
            f.seek(start)
            return f.read(4) == pck.MAGIC
    except OSError:
        return False


def _embedded_exes(game_dir: str) -> list[str]:
    """exe с приклеенным pck (self-contained экспорт)."""
    try:
        names = sorted(os.listdir(game_dir))
    except OSError:
        return []
    return [os.path.join(game_dir, n) for n in names
            if n.lower().endswith(".exe")
            and os.path.isfile(os.path.join(game_dir, n))
            and _exe_has_pck_trailer(os.path.join(game_dir, n))]


def detect(game_dir: str) -> int:
    """Вес уверенности: 0 — не Godot.

    100 — обычный .pck с магией GDPC; 95 — распакованный проект
    (``project.godot``); 85 — папка импорта ``.godot/``; 70 —
    self-contained exe (движок виден, но переводить exe мы не берёмся).
    """
    try:
        names = sorted(os.listdir(game_dir))
    except OSError:
        return 0
    embedded = False
    for name in names:
        if not name.lower().endswith(".pck"):
            continue
        full = os.path.join(game_dir, name)
        if not os.path.isfile(full):
            continue
        loc = pck.locate(full)
        if loc is not None:
            if loc[1]:
                embedded = True
            else:
                return 100
    if os.path.isfile(os.path.join(game_dir, "project.godot")):
        return 95
    if os.path.isdir(os.path.join(game_dir, ".godot")):
        return 85
    if embedded or _embedded_exes(game_dir):
        return 70
    return 0


# ── извлечение ──

def _collect_csv(col: _Collector, name: str, text: str):
    for idx, line in enumerate(text.splitlines(), 1):
        if idx == 1:
            # заголовок Godot-CSV ("keys,<locale>") — не данные
            continue
        if not line.strip():
            continue
        if not csv_balanced(line):
            col.count("skipped:csv:multiline")
            continue
        for c, (s, e) in enumerate(csv_split(line)):
            if c == 0:
                continue  # колонка ключей — идентификаторы, не текст
            if col.add(name, f"line[{idx}].col[{c}]", f"{name}:{idx}",
                       csv_value(line[s:e])):
                col.count("csv")


def _collect_scene(col: _Collector, name: str, text: str):
    kind = "tscn" if name.lower().endswith(".tscn") else "tres"
    for idx, line in enumerate(text.splitlines(), 1):
        m = _ASSIGN_RE.match(line)
        if not m:
            continue
        key = m.group(2)
        if key not in _SCENE_TEXT_KEYS:
            continue
        value = m.group(3).strip()
        is_array = value.startswith(_ARRAY_WRAPPERS)
        if not (is_array or value.startswith('"')):
            continue
        value_start = m.start(3)
        picked = 0
        for k, (s, _e, raw) in enumerate(scan_literals(line), 1):
            if s < value_start:
                continue
            # без обёртки массива берём только ПЕРВЫЙ литерал значения:
            # всё остальное в .tscn — служебное (ExtResource, uid и т.п.)
            if not is_array and picked:
                break
            picked += 1
            if col.add(name, f"line[{idx}].str[{k}]",
                       f"{name}:{idx} {key}", unescape(raw)):
                col.count(kind)


def _collect_gd(col: _Collector, name: str, text: str):
    for idx, line in enumerate(text.splitlines(), 1):
        for k, (_s, _e, raw) in enumerate(
                scan_literals(line, quotes="\"'", comments="#"), 1):
            if col.add(name, f"line[{idx}].str[{k}]", f"{name}:{idx}",
                       unescape(raw)):
                col.count("gd")


def _scan_one(col: _Collector, name: str, loader):
    ext = os.path.splitext(name)[1].lower()
    if ext in _BINARY_EXTS:
        col.count("unsupported:binary")
        return
    if ext == _GDC_EXT:
        col.count("unsupported:gdc")
        return
    if ext not in _TEXT_EXTS:
        return
    col.count(f"files:{ext[1:]}")
    try:
        raw = loader()
    except (pck.PckError, OSError):
        col.count("unsupported:read")
        return
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        col.count("unsupported:encoding")
        return
    if ext == ".csv":
        _collect_csv(col, name, text)
    elif ext == ".gd":
        _collect_gd(col, name, text)
    else:
        _collect_scene(col, name, text)


def _collect(game_dir: str, want_entries: bool):
    """Общий обход: .pck либо распакованный проект. Возвращает (entries, counts)."""
    col = _Collector()
    pck_path, extra = find_pck(game_dir)

    def _out():
        return col.entries if want_entries else []

    if pck_path is None:
        for abs_path, rel in _iter_loose(game_dir):
            def _load(p=abs_path):
                with open(p, "rb") as f:
                    return f.read()
            _scan_one(col, rel, _load)
        # self-contained exe: движок найден, но exe мы не вскрываем
        col.count("unsupported:embedded", len(_embedded_exes(game_dir)))
        problem = _pck_problem(game_dir)
        if problem:
            col.count(problem)
        return _out(), col.counts

    if extra:
        col.count("unsupported:multi-pack", extra)
    try:
        header = pck.read_header(pck_path)
    except pck.PckEncrypted:
        col.count("unsupported:encrypted")
        return _out(), col.counts
    except pck.PckVersion as exc:
        col.count(_version_reason(exc))
        return _out(), col.counts
    except pck.PckUnsupported as exc:
        col.count(exc.reason)
        return _out(), col.counts
    except pck.PckError:
        col.count("unsupported:format")
        return _out(), col.counts
    if header.embedded:
        # exe с приклеенным pck не трогаем: риск сломать игру не окупается
        col.count("unsupported:embedded")
        return _out(), col.counts
    try:
        catalog = pck.read_entries(pck_path, header)
    except pck.PckError:
        col.count("unsupported:format")
        return _out(), col.counts
    for entry in catalog:
        if entry.encrypted:
            col.count("unsupported:encrypted")
            continue
        if entry.removal:
            col.count("unsupported:removal")
            continue
        if entry.delta:
            col.count("unsupported:delta")
            continue
        _scan_one(col, entry.path,
                  lambda e=entry: pck.read_blob(pck_path, e))
    return _out(), col.counts


def scan(game_dir: str) -> dict:
    """Числа для отчёта: сколько кандидатов по типам и почему отказались.

    Только счётчики, без текста игры (AGENTS.md:35-38).
    """
    _entries, counts = _collect(game_dir, False)
    counts = dict(counts)
    counts["candidates"] = sum(counts.get(k, 0)
                               for k in ("csv", "tscn", "tres", "gd"))
    return counts


def extract(game_dir: str) -> list[TranslationEntry]:
    """Извлекает переводимые строки из .pck или распакованного проекта."""
    entries, _counts = _collect(game_dir, True)
    return entries


# ── внедрение ──

def _line_starts(text: str) -> tuple[list[str], list[int]]:
    lines = text.splitlines(keepends=True)
    starts: list[int] = []
    pos = 0
    for ln in lines:
        starts.append(pos)
        pos += len(ln)
    return lines, starts


def splice_text(text: str, items: list, quotes: str = '"'):
    """Подставить переводы в текст одного файла.

    Возвращает ``(text, count, skipped)``, где ``skipped`` — список пар
    ``(запись, причина)``. Диск не трогается — вызывающий решает по
    ``count``. Всё вне подстановок остаётся байт в байт (переводы строк
    CRLF/LF и завершающий перевод строки не едут).
    """
    lines, starts = _line_starts(text)
    edits: list[tuple[int, int, str, object]] = []
    skipped: list = []

    def _fail(entry, reason: str):
        skipped.append((entry, reason))

    for e in items:
        m = _PATH_RE.match(_entry_value(e, "json_path"))
        if not m:
            _fail(e, "bad position")
            continue
        n, kind, idx = int(m.group(1)), m.group(2), int(m.group(3))
        if n < 1 or n > len(lines):
            _fail(e, "position not found")
            continue
        original = _entry_value(e, "original")
        translation = _entry_translation(e)
        # повторная проверка оригинала: запись могла прийти из старого
        # .ob.json или из ручной правки UI — служебное не пишем никогда
        guard = reject_reason(original)
        if guard is not None:
            _fail(e, guard)
            continue
        line = lines[n - 1]
        base = starts[n - 1]
        body = line.rstrip("\r\n")
        if kind == "col":
            if not csv_balanced(line):
                _fail(e, "csv multiline")
                continue
            spans = csv_split(body)
            # col[C] — индекс поля CSV с нуля (как его видит парсер Godot),
            # в отличие от str[M], где M — порядковый номер литерала с единицы
            if idx < 0 or idx >= len(spans):
                _fail(e, "position not found")
                continue
            s, end = spans[idx]
            cur = csv_value(body[s:end])
            if cur == translation:
                continue  # уже переведено — apply идемпотентен
            if cur != original:
                _fail(e, "original not found")
                continue
            reason = translation_reason(original, translation,
                                        multiline_ok=False)
            if reason:
                _fail(e, reason)
                continue
            edits.append((base + s, base + end, csv_quote(translation), e))
            continue
        lits = scan_literals(body, quotes=quotes)
        if idx < 1 or idx > len(lits):
            _fail(e, "position not found")
            continue
        s, end, raw = lits[idx - 1]
        cur = unescape(raw)
        if cur == translation:
            continue
        if cur != original:
            _fail(e, "original not found")
            continue
        reason = translation_reason(original, translation)
        if reason:
            _fail(e, reason)
            continue
        new_raw = escape(translation)
        if unescape(new_raw) != translation:
            # наш экранировщик не выразил этот перевод — лучше пропуск
            _fail(e, "escape")
            continue
        edits.append((base + s, base + end, '"' + new_raw + '"', e))

    if not edits:
        return text, 0, skipped
    # две записи на ОДНУ позицию — одно место в файле. Вторая правка
    # переписала бы первую, а count разошёлся бы с реальностью вдвое,
    # поэтому оставляем первую, второй говорим причину.
    unique: list[tuple[int, int, str, object]] = []
    taken: set[tuple[int, int]] = set()
    for e_s, e_end, new, entry in edits:
        if (e_s, e_end) in taken:
            _fail(entry, "duplicate position")
            continue
        taken.add((e_s, e_end))
        unique.append((e_s, e_end, new, entry))
    if not unique:
        return text, 0, skipped
    out = text
    for s, end, new, _entry in sorted(unique, key=lambda it: it[:2],
                                       reverse=True):
        out = out[:s] + new + out[end:]
    return out, len(unique), skipped


_PCK_MANIFEST = "godot_pck.json"


def _pck_manifest_path(game_dir: str) -> str:
    return os.path.join(game_dir, "backup", _PCK_MANIFEST)


def _load_pck_manifest(game_dir: str) -> dict:
    try:
        with open(_pck_manifest_path(game_dir), encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_pck_manifest(game_dir: str, data: dict):
    try:
        atomic_write_json(_pck_manifest_path(game_dir), data, indent=1)
    except (OSError, TypeError, ValueError):
        pass


def _backup_is_usable(bak: str, recorded, current: int) -> bool:
    """Годен ли лежащий на диске бэкап как ОРИГИНАЛ игры.

    Прерванная копия — обрезок в несколько байт. Откат из неё сокращает
    .pck и убивает игру, поэтому битый по размеру бэкап годным не считаем
    никогда. Если размер известен из манифеста — сверяемся с ним (это
    размер оригинала на момент бэкапа, и он не меняется от повторных
    apply); старый манифест без размера — сверяемся с текущим .pck.
    """
    if isinstance(recorded, bool) or not isinstance(recorded, int):
        recorded = None
    if not os.path.isfile(bak):
        return False
    try:
        size = os.path.getsize(bak)
    except OSError:
        return False
    want = current if recorded is None else recorded
    return size == want


def _backup_pck(pck_path: str, game_dir: str, backup_dir: str):
    """Полная побайтовая копия .pck ДО любых изменений (потоком).

    ``BackupStore`` тут не годится: он читает файл целиком в память, а
    .pck бывает сотни мегабайт. Копия идёт чанками во ВРЕМЕННЫЙ файл рядом
    и переезжает на место через ``os.replace`` только после сверки размера,
    поэтому на диске никогда не остаётся «половинчатый бэкап». Уже
    записанный годный бэкап не перезаписывается (как и в BackupStore) —
    иначе откат вернул бы не оригинал.
    """
    try:
        os.makedirs(backup_dir, exist_ok=True)
        bak = os.path.join(backup_dir,
                           os.path.basename(pck_path) + ".ob_bak")
        known = _load_pck_manifest(game_dir)
        try:
            current = os.path.getsize(pck_path)
        except OSError:
            return None
        recorded = known.get("backup_size")
        want = current if not isinstance(recorded, int) or \
            isinstance(recorded, bool) else recorded
        if not _backup_is_usable(bak, recorded, current):
            pck.stream_copy_atomic(pck_path, bak)
            try:
                shutil.copystat(pck_path, bak)
            except OSError:
                pass
            want = current
        try:
            size = os.path.getsize(bak)
        except OSError:
            return None
        if size != want:
            # годного бэкапа на диске нет — лучше не писать, чем откатываться
            # в мусор
            return None
        # манифест всегда по каноническому пути game_dir/backup/ — там его
        # ищет restore_original; размер оригинала запоминаем, чтобы повторный
        # apply не счёл годный бэкап обрезком и не перебил его
        known = dict(known)
        known.update({
            "pck": os.path.abspath(pck_path),
            "backup": os.path.abspath(bak),
            "backup_dir": os.path.abspath(backup_dir),
            "backup_size": size,
        })
        _save_pck_manifest(game_dir, known)
        return bak
    except (OSError, pck.PckError):
        return None


def _restore_stream(bak: str, dest: str, is_pck: bool = False) -> tuple[bool, str]:
    """Вернуть в ``dest`` копию ``bak`` ПОТОКОМ и проверить результат.

    ``(True, "")`` только если файл на месте и размер совпал с бэкапом.
    Для .pck дополнительно проверяется магия GDPC — откат, после которого
    файл не открывается движком, хуже, чем честный отказ.
    """
    try:
        want = pck.stream_copy_atomic(bak, dest)
        got = os.path.getsize(dest)
        if got != want:
            return False, f"размер после отката {got} != {want}"
    except (OSError, pck.PckError) as exc:
        return False, str(exc)
    if is_pck and pck.locate(dest) is None:
        return False, "после отката не читается магия GDPC"
    return True, ""


def apply(game_dir: str, entries: list, target_lang: str = "",
          on_skip=None, backup_root: str | None = None, **kwargs) -> dict:
    """Внедряет переводы в .pck или файлы распакованного проекта.

    Порядок записи обязателен (``AGENTS.md:214-216``): бэкап целиком ->
    атомарная запись -> проверка перечитыванием. Любое расхождение
    откатывает файл из бэкапа и попадает в ``verify_failed``.
    """
    backup_dir = backup_root or os.path.join(game_dir, "backup")
    stats: dict = {"files": 0, "strings": 0, "backups": [], "skipped_total": 0,
                   "skipped_by": {}, "verify_failed": [],
                   "verify_restored": True}
    skip_count: dict[str, int] = {}

    def _skip(entry, reason: str):
        skip_count[reason] = skip_count.get(reason, 0) + 1
        if on_skip:
            try:
                on_skip(entry, reason)
            except TypeError:
                pass

    def _finish() -> dict:
        stats["skipped_total"] = sum(skip_count.values())
        # никакого молчаливого обрезания: UI обязан видеть ВСЕ причины
        # (AGENTS.md:71-73), иначе шестая исчезает вместе с объяснением
        stats["skipped_by"] = dict(sorted(skip_count.items(),
                                          key=lambda kv: -kv[1]))
        return stats

    by_file: dict[str, list] = {}
    for e in entries:
        if _is_writable(e):
            by_file.setdefault(_entry_value(e, "file"), []).append(e)
            continue
        if _entry_value(e, "status") == "skip":
            continue  # пользователь сам снял строку — молчание тут правильное
        _skip(e, "empty translation")
    if not by_file:
        return _finish()

    pck_path, _extra = find_pck(game_dir)
    # self-contained: нет отдельного .pck, exe не вскрываем — честный отказ
    embedded_only = pck_path is None and bool(_embedded_exes(game_dir))
    header = None
    catalog: dict = {}
    if pck_path is not None:
        try:
            header = pck.read_header(pck_path)
        except pck.PckEncrypted:
            reason = "encrypted pack"
            for items in by_file.values():
                for e in items:
                    _skip(e, reason)
            return _finish()
        except pck.PckVersion as exc:
            reason = f"unsupported:version {exc.version}"
            for items in by_file.values():
                for e in items:
                    _skip(e, reason)
            return _finish()
        except pck.PckUnsupported as exc:
            for items in by_file.values():
                for e in items:
                    _skip(e, exc.reason)
            return _finish()
        except pck.PckError:
            reason = "unreadable pack"
            for items in by_file.values():
                for e in items:
                    _skip(e, reason)
            return _finish()
        if header.embedded:
            for items in by_file.values():
                for e in items:
                    _skip(e, "unsupported:embedded")
            return _finish()
        try:
            catalog = {e.path: e
                       for e in pck.read_entries(pck_path, header)}
        except pck.PckError:
            for items in by_file.values():
                for e in items:
                    _skip(e, "unreadable pack")
            return _finish()

    new_blobs: dict[str, bytes] = {}
    new_counts: dict[str, int] = {}
    touched_loose: dict[str, tuple] = {}

    for rel, items in sorted(by_file.items()):
        entry = None
        abs_path = None
        if embedded_only:
            for e in items:
                _skip(e, "unsupported:embedded")
            continue
        if pck_path is not None:
            entry = (catalog.get(rel)
                     or catalog.get(rel.replace("\\", "/"))
                     or catalog.get("res://" + rel.lstrip("/")))
            if entry is None:
                for e in items:
                    _skip(e, "file not found")
                continue
            if entry.encrypted:
                for e in items:
                    _skip(e, "encrypted pack")
                continue
            if entry.removal:
                for e in items:
                    _skip(e, "unsupported:removal")
                continue
            if entry.delta:
                for e in items:
                    _skip(e, "unsupported:delta")
                continue
            try:
                raw = pck.read_blob(pck_path, entry)
            except (pck.PckError, OSError):
                for e in items:
                    _skip(e, "unreadable pack")
                continue
        else:
            abs_path = os.path.join(game_dir, *rel.split("/"))
            try:
                with open(abs_path, "rb") as f:
                    raw = f.read()
            except OSError:
                for e in items:
                    _skip(e, "file not found")
                continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            for e in items:
                _skip(e, "encoding")
            continue
        quotes = "\"'" if rel.lower().endswith(".gd") else '"'
        new_text, count, skipped = splice_text(text, items, quotes=quotes)
        for bad, reason in skipped:
            _skip(bad, reason)
        if not count:
            continue
        blob = new_text.encode("utf-8")
        if entry is not None:
            new_blobs[entry.path] = blob
            # единицы считаем в записях, как и остальные skip_count
            new_counts[entry.path] = count
            stats["strings"] += count
        else:
            touched_loose[abs_path] = (blob, count)

    # ── .pck: одна пересборка на весь пакет ──
    if new_blobs and pck_path:
        bak = _backup_pck(pck_path, game_dir, backup_dir)
        if bak is None:
            for count in new_counts.values():
                skip_count["cannot backup pack"] = skip_count.get(
                    "cannot backup pack", 0) + count
            stats["strings"] = 0
        else:
            stats["backups"].append(bak)
            catalog_list = list(catalog.values())
            written = False
            problems: list[str] = []
            try:
                pck.write_pck(pck_path, pck_path, header, catalog_list,
                              new_blobs)
                written = True
                problems = pck.verify(
                    pck_path,
                    [e.path for e in catalog_list],
                    {path: hashlib.md5(blob).digest()
                     for path, blob in new_blobs.items()})
            except Exception as exc:  # noqa: BLE001
                # файл игры уже изменён — наружу исключение бросать нельзя:
                # UI обязан получить отчёт, а не traceback (протокол
                # apply -> ApplyReport). Откат делаем сами.
                problems.append(f"verify failed: {exc}")
            if not written:
                # write_pck атомарен: сорвался он ДО os.replace, .pck цел
                stats["strings"] = 0
                stats["verify_failed"].extend(problems)
            elif problems:
                stats["strings"] = 0
                stats["verify_failed"].extend(problems)
                ok, why = _restore_stream(bak, pck_path, is_pck=True)
                if not ok:
                    stats["verify_restored"] = False
                    stats["verify_failed"].append(f"restore failed: {why}")
            else:
                stats["files"] = len(new_blobs)

    # ── распакованный проект: файл за файлом ──
    if touched_loose:
        store = BackupStore(backup_dir)
        for abs_path, (blob, count) in sorted(touched_loose.items()):
            bak = store.backup(abs_path)
            if bak is None:
                skip_count["cannot backup file"] = skip_count.get(
                    "cannot backup file", 0) + 1
                continue
            if bak not in stats["backups"]:
                stats["backups"].append(bak)
            try:
                atomic_write_bytes(abs_path, blob)
            except OSError:
                skip_count["cannot write file"] = skip_count.get(
                    "cannot write file", 0) + 1
                continue
            written = None
            try:
                with open(abs_path, "rb") as f:
                    written = f.read()
            except OSError:
                written = None
            if written is None or written != blob:
                # файл мог быть перезаписан — откатываем и говорим честно
                stats["verify_failed"].append(
                    "verify: файл не совпал после записи: "
                    + os.path.basename(abs_path))
                ok, why = _restore_stream(bak, abs_path)
                if not ok:
                    stats["verify_restored"] = False
                    stats["verify_failed"].append(f"restore failed: {why}")
                continue
            stats["files"] += 1
            stats["strings"] += count

    return _finish()


def verify(game_dir: str) -> list[str]:
    """Проверка целостности после apply: пустой список = всё в порядке.

    Пустой список UI читает как «игра стартует» (``protocol.py:100-101``),
    поэтому вернуть его можно только когда это правда. Нет .pck — нет и
    права молчать: проверяем, что внедрение вообще было и что файлы на
    месте. Иначе «применил, а перевода нет» остаётся без объяснения
    (``AGENTS.md:71-73``).
    """
    pck_path, _extra = find_pck(game_dir)
    if pck_path is not None:
        try:
            header = pck.read_header(pck_path)
            pck.read_entries(pck_path, header)
        except pck.PckError as exc:
            return [f"pck не читается: {exc}"]
        known = _load_pck_manifest(game_dir).get("backup")
        if not (known and os.path.isfile(str(known))):
            return ["перевод не внедрялся: признака применения нет"]
        return []
    if _embedded_exes(game_dir):
        return ["unsupported:embedded: внедрение не выполнялось, exe не трогаем"]
    if not os.path.isfile(os.path.join(game_dir, "project.godot")):
        return ["pck не найден: проверять нечего"]
    files = BackupStore(os.path.join(game_dir, "backup")).manifest_files()
    if not files:
        return ["перевод не внедрялся: признака применения нет"]
    return [f"файл после внедрения отсутствует: {os.path.basename(abs_orig)}"
            for abs_orig in sorted(files) if not os.path.isfile(abs_orig)]


def restore_original(game_dir: str) -> dict:
    """Откат: .pck целиком из бэкапа + файлы проекта через BackupStore.

    Бэкап .pck проверяется по размеру: откат из обрезка сократил бы игру
    до десяти байт, а «отчёт об успешном откате» врал бы в лицо.
    """
    restored = 0
    problems: list[str] = []
    manifest = _load_pck_manifest(game_dir)
    src = manifest.get("backup")
    dst = manifest.get("pck")
    if src and dst and os.path.isfile(src):
        try:
            current = os.path.getsize(dst) if os.path.isfile(dst) else -1
        except OSError:
            current = -1
        if _backup_is_usable(str(src), manifest.get("backup_size"), current):
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                ok, why = _restore_stream(str(src), str(dst))
                if ok:
                    restored += 1
                else:
                    problems.append(f"{os.path.basename(str(dst))}: {why}")
            except OSError as exc:
                problems.append(f"{os.path.basename(str(dst))}: {exc}")
        else:
            problems.append(
                f"{os.path.basename(str(dst))}: бэкап неполон, отказ от отката")
    result = BackupStore(os.path.join(game_dir, "backup")).restore_all()
    out = {"restored": restored + int(result.get("restored", 0) or 0),
           "failed": problems + list(result.get("errors", []) or [])}
    return out

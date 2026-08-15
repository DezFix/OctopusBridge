# -*- coding: utf-8 -*-
"""Ren'Py support: detect, text extraction from .rpy/.rpyc, translation generation.

Extraction:
- .rpy source files: regex-based (dialogues, choices, _() markers, old blocks)
- .rpyc compiled files: RPC2 unpickling with mock AST, walker extracts
  dialogues (Say.who/what), menu choices (Menu.items), Character names (Define)

Generation: official Ren'Py mechanism — game/tl/<lang>/*.rpy with blocks:
    translate russian strings:
        old "original"
        new "translation"
"""
from __future__ import annotations

import ast
import hashlib
import io
import os
import pickle
import re
import struct
import zlib

from app.core.models import TranslationEntry

LANG_FOLDERS = {"ru": "russian", "en": "english", "ja": "japanese",
                "zh": "chinese"}


def _extract_interp_codes(text: str) -> list[str]:
    """Вырезает сбалансированные группы [...]/{...} (Ren'Py-интерполяция
    и теги). Учитывает вложенность (например `current_track['title']`
    внутри внешних [...])."""
    codes: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] in "[{":
            start = i
            depth = 1
            i += 1
            while i < n and depth > 0:
                if text[i] in "[{":
                    depth += 1
                elif text[i] in "]}":
                    depth -= 1
                i += 1
            codes.append(text[start:i])
        else:
            i += 1
    return codes


def _is_interp_safe(original: str, translation: str) -> bool:
    """True, если весь Python-код/теги внутри [...]/{...} оригинала
    присутствуют в переводе ДОСЛОВНО и в том же порядке.

    Нужно, чтобы MT/переводчик, получивший строку с интерполяцией
    (например "Играет [menu_music.truncate_text(current_track['title'])]"),
    не смог незаметно испортить код — известный случай: подчёркивания
    в идентификаторах превращались в пробелы, движок падал с
    SyntaxError прямо в игре. Если код не совпал — эту запись нельзя
    применять, используем оригинал.
    """
    orig_codes = _extract_interp_codes(original)
    if not orig_codes:
        return True
    pos = 0
    for code in orig_codes:
        idx = translation.find(code, pos)
        if idx == -1:
            return False
        pos = idx + len(code)
    return True

_STR = r'"((?:[^"\\]|\\.)*)"'
RE_CHOICE = re.compile(r'^\s*' + _STR + r'\s*:\s*$')
RE_TR_FN = re.compile(r'_\(\s*' + _STR + r'\s*\)')
RE_OLD = re.compile(r'^\s*old\s+' + _STR)
RE_COMMENT = re.compile(r'^\s*#')
# начало строки-диалога: необязательный говорящий + открывающая кавычка
RE_QUOTE_START = re.compile(r'^\s*(?:[a-zA-Z_][\w.]*\s+)?\"')

_DLG_SKIP_RE = re.compile(
    r'^(?:def|default|define|label|screen|transform|style|image|'
    r'scene|show|hide|play|stop|queue|jump|call|return|if|elif|'
    r'else|while|for|with|menu|init|translate|python|layer|pause|'
    r'voice|camera|animation|audio|movie|window|onlayer|group|'
    r'when|or|and|not|in|is|None|True|False|pass|as|at|zorder|'
    r'old|new)\b'
    r'(?:\s|$)')

RE_DIALOGUE = re.compile(
    r'^\s*(?:[a-zA-Z_][\w.]*\s+)?' + _STR + r'(?:\s|$)')

# ── Mock Ren'Py AST classes for .rpyc unpickling ─────────────────────

class _PyCode:
    def __setstate__(self, state):
        attrs = ["version", "source", "location", "mode", "py", "hashcode", "col_offset"]
        for i, a in enumerate(attrs):
            setattr(self, a, state[i] if len(state) > i else ("" if a == "source" else None))
        if not isinstance(self.source, str):
            self.source = getattr(self.source, "source", str(self.source))

class _PyExpr:
    def __init__(self, *args):
        self._args = args
        src = args[1] if len(args) > 1 else ""
        self.source = src if isinstance(src, str) else str(src)

class _MockPyExpr(str):
    """Mock для str-подклассов Ren'Py 7.4+/8.x: PyExpr и RawCode.

    Такие объекты pickle восстанавливает через __new__(cls, source) —
    простой класс упал бы с TypeError и обрушил бы unpickle всего .rpyc.
    Значение mock-объекта == сам python-исходник (например '"Играть"'),
    флаг _ob_py_expr помечает его как код, а не текст для перевода.
    """
    _ob_py_expr = True

    def __new__(cls, *args):
        return str.__new__(cls, args[0] if args else "")

class _RevertableDict(dict):
    pass

class _MockNode:
    pass

_RENPY_MOCKS: dict[tuple[str, str], type] = {
    ("renpy.ast", "PyCode"): _PyCode,
    ("renpy.ast", "PyExpr"): _MockPyExpr,
    ("renpy.astsupport", "PyExpr"): _PyExpr,
    ("renpy.python", "RawCode"): _MockPyExpr,
    ("renpy.revertable", "RevertableDict"): _RevertableDict,
    ("renpy.parameter", "ArgumentInfo"): _MockNode,
    ("renpy.sl2.slast", "SLScreen"): _MockNode,
}

for _name in [
    "Node", "Init", "Python", "Return", "Say", "Menu", "Label",
    "Jump", "Call", "If", "While", "Pass", "Show", "Scene",
    "Hide", "With", "Play", "Queue", "Pause",
    "Translate", "TranslateSay", "TranslateString", "TranslateBlock",
    "Define", "Default", "Screen",
]:
    _RENPY_MOCKS[("renpy.ast", _name)] = type(_name, (_MockNode,), {})

class _RenPyUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        key = (module, name)
        if key in _RENPY_MOCKS:
            return _RENPY_MOCKS[key]
        if module.startswith("renpy."):
            cls = type(f"_mock_{name}", (_MockNode,), {})
            _RENPY_MOCKS[key] = cls
            return cls
        return super().find_class(module, name)

# ── RPC2 unpickling ─────────────────────────────────────────────────

def _unpickle_rpyc(rpyc_data: bytes):
    """Unpickle .rpyc data, return (data_dict, stmts_list) or None."""
    if rpyc_data[:10] != b"RENPY RPC2":
        try:
            data = zlib.decompress(rpyc_data)
            u = _RenPyUnpickler(io.BytesIO(data))
            obj = u.load()
            if isinstance(obj, tuple) and len(obj) >= 2:
                return obj[0], obj[1]
        except Exception:
            pass
        return None

    pos = len(b"RENPY RPC2")
    while True:
        slot, start, length = struct.unpack("III", rpyc_data[pos:pos + 12])
        if slot == 0:
            break
        if slot == 1:
            compressed = rpyc_data[start:start + length]
            try:
                decompressed = zlib.decompress(compressed)
                u = _RenPyUnpickler(io.BytesIO(decompressed))
                obj = u.load()
                if isinstance(obj, tuple) and len(obj) >= 2:
                    return obj[0], obj[1]
            except Exception:
                pass
        pos += 12
    return None

def _string_parts(text) -> list[str]:
    """Строковые части what/who/пункта меню.

    Ren'Py хранит интерполированный текст списком — например
    Say(what=["Привет, ", <var>, "!"]) — это части реплики вокруг
    вставок переменных. Переводим строковые элементы по отдельности:
    рантайм-хук ob_dict подменяет каждый элемент списка своим переводом
    (см. _ACTIVATE_TEMPLATE, ветку isinstance(text, list)).

    Вставки переменных — объекты PyExpr/RawCode (в Ren'Py 7.4+/8.x это
    str-подклассы, mock-восстановленные как _MockPyExpr) — НЕ текст:
    их значение это python-код (имя переменной). Флаг _ob_py_expr
    отличает их от настоящих строковых частей реплики.
    """
    def _is_code(t) -> bool:
        return isinstance(t, str) and getattr(type(t), "_ob_py_expr", False)

    if isinstance(text, str):
        return [] if _is_code(text) else ([text] if text else [])
    if isinstance(text, bytes):
        # Ren'Py 7 (Python 2) может хранить строки как байты — декодируем
        return [text.decode("utf-8", "replace")] if text else []
    if isinstance(text, (list, tuple)):
        return [t if isinstance(t, str) and not _is_code(t)
                else t.decode("utf-8", "replace") if isinstance(t, bytes)
                else "" for t in text if isinstance(t, (str, bytes)) and t]
    return []


def _sl_text_value(part) -> str | None:
    """Строковый литерал из позиционного аргумента text/textbutton SL2.

    В .rpyc позиционные аргументы — PyExpr (str-подкласс, значение ==
    python-исходник, например '"Играть"'; у старых Ren'Py 7.0-7.3 —
    объект с атрибутом .source). Извлекаем строковую константу; если
    текст составной (text "a" + var) — берём первый строковый литерал
    (best effort, такие строки редки в экранах).
    """
    src = part if isinstance(part, str) else getattr(part, "source", "")
    if not src:
        return None
    src = src.strip()
    if not src:
        return None
    try:
        v = ast.literal_eval(src)
        if isinstance(v, str):
            return v
    except Exception:
        pass
    m = re.search(_STR, src)
    return m.group(1) if m else None


def _walk_ast(stmts) -> list[tuple[str, str]]:
    """Walk Ren'Py AST, extracting (kind, text) pairs."""
    result = []
    visited = set()

    def walk(nodes):
        if isinstance(nodes, (list, tuple)):
            for n in nodes:
                walk(n)
            return
        if id(nodes) in visited:
            return
        visited.add(id(nodes))
        nt = type(nodes).__name__
        # Ленивые mock-классы называются _mock_<Имя> (например
        # _mock_SLDisplayable) — нормализуем для ветвлений.
        base = nt.removeprefix("_mock_")

        if nt == "Say":
            what = getattr(nodes, "what", None)
            who = getattr(nodes, "who", None)
            for part in _string_parts(what):
                result.append(("dialogue", part))
            for part in _string_parts(who):
                result.append(("speaker", part))

        elif nt == "TranslateSay":
            what = getattr(nodes, "what", None)
            for part in _string_parts(what):
                result.append(("dialogue", part))
            who = getattr(nodes, "who", None)
            for part in _string_parts(who):
                result.append(("speaker", part))

        elif nt == "Menu":
            items = getattr(nodes, "items", [])
            for item in items:
                label = item[0] if isinstance(item, (list, tuple)) else None
                for part in _string_parts(label):
                    if len(part) >= 2:
                        result.append(("choice", part))
                if isinstance(item, (list, tuple)) and len(item) > 2:
                    walk(item[2])

        elif nt == "Label":
            walk(getattr(nodes, "block", []))

        elif nt == "Translate":
            walk(getattr(nodes, "block", []))

        elif nt == "TranslateString":
            old = getattr(nodes, "old", None)
            if old and isinstance(old, str):
                result.append(("translated_string", old))

        elif nt == "Define":
            code = getattr(nodes, "code", None)
            src = getattr(code, "source", "") if code else ""
            for m in re.finditer(r'(?:Character|create_character)\(\s*"([^"]+)"', src):
                result.append(("character", m.group(1)))

        elif nt == "Python":
            code = getattr(nodes, "code", None)
            src = getattr(code, "source", "") if code else ""
            for m in re.finditer(r'create_character\(\s*"([^"]+)"', src):
                result.append(("character", m.group(1)))

        elif nt == "Screen":
            # SL2 (Ren'Py 6.99+): Screen.screen → slast.SLScreen с
            # деревом SL-узлов; текст экранов — SLDisplayable text/
            # textbutton (см. ветку SLDisplayable ниже).
            walk(getattr(nodes, "screen", None))

        elif base == "SLDisplayable":
            # text "…" и textbutton "…": текст лежит в positional как
            # PyExpr (python-исходник строкового литерала). Остальные
            # дисплейаблы (image, add, bar…) в positional держат имена
            # файлов/переменные — их не переводим. displayable — сам
            # класс (mock _mock_Text / _mock__textbutton).
            _d = getattr(nodes, "displayable", None)
            disp_name = getattr(_d, "__name__", "") if _d is not None else ""
            if disp_name.removeprefix("_mock_") in ("Text", "_textbutton"):
                for pos in getattr(nodes, "positional", []):
                    v = _sl_text_value(pos)
                    if v:
                        result.append(("screen", v))

        elif base == "SLPython":
            code = getattr(nodes, "code", None)
            src = getattr(code, "source", "") if code else ""
            for m in re.finditer(r'create_character\(\s*"([^"]+)"', src):
                result.append(("character", m.group(1)))

        # SL2-деревья: дети блоков (SLBlock.children), ветки if/showif
        # (SLIf.entries — пары (условие, блок)), блоки use (SLUse.block).
        walk(getattr(nodes, "children", []))
        for _e in getattr(nodes, "entries", []):
            if isinstance(_e, (list, tuple)) and len(_e) > 1:
                walk(_e[1])
        walk(getattr(nodes, "block", []))
        walk(getattr(nodes, "body", []))

    walk(stmts)
    return result

# ── Main API ────────────────────────────────────────────────────────

def detect(game_dir: str) -> bool:
    """Is this a Ren'Py game? (has game/ with .rpy/.rpyc/.rpa or renpy/)"""
    game_sub = os.path.join(game_dir, "game")
    if os.path.isdir(game_sub):
        for _root, _dirs, files in os.walk(game_sub):
            if any(f.endswith(".rpy") for f in files):
                return True
            if any(f.endswith(".rpyc") for f in files):
                return True
            if any(f.lower().endswith(".rpa") for f in files):
                return True
    return os.path.isdir(os.path.join(game_dir, "renpy"))


def find_rpa_archives(game_dir: str) -> list[str]:
    """Find all .rpa archives in game/."""
    result = []
    game_sub = os.path.join(game_dir, "game")
    if not os.path.isdir(game_sub):
        return result
    for root, _dirs, files in os.walk(game_sub):
        for f in files:
            if f.lower().endswith(".rpa"):
                result.append(os.path.join(root, f))
    return result


def list_languages(game_dir: str) -> list[str]:
    """Языки официальных переводов игры: подпапки game/tl/* на диске
    и каталоги tl/<lang>/ внутри .rpa архивов."""
    langs: set[str] = set()
    tl_dir = os.path.join(game_dir, "game", "tl")
    if os.path.isdir(tl_dir):
        for name in os.listdir(tl_dir):
            if os.path.isdir(os.path.join(tl_dir, name)) \
                    and not name.startswith("."):
                langs.add(name)
    try:
        from app.core.renpy.rpa import RpaArchive, find_rpa_archives as _find_rpa
        for arc_path in _find_rpa(game_dir):
            try:
                arc = RpaArchive(arc_path)
            except Exception:
                continue
            for fname in arc.files:
                if fname.startswith("tl/") \
                        and (fname.endswith(".rpy") or fname.endswith(".rpyc")):
                    head = fname[len("tl/"):].split("/", 1)[0]
                    if head:
                        langs.add(head)
    except ImportError:
        pass
    return sorted(langs)


def _iter_rpy(game_dir: str, extract_lang: str | None = None):
    """Iterate .rpy and .rpyc files from game/ and .rpa archives.

    extract_lang: если задан — берём только tl/<язык>/ (на диске и в
    архивах), остальные языки пропускаем. None = весь текст игры,
    включая все официальные переводы tl/* (раньше tl/ на диске
    пропускалась целиком — «весь текст» не был всем текстом).

    Файлы OctopusBridge (ob_*.rpy, ob_dict.json — в game/ и tl/) НЕ
    извлекаются: иначе свои же артефакты попадают в выгрузку как
    текст игры и порождают дубликаты old-строк в tl/<lang>/, из-за
    которых Ren'Py падает («A translation ... already exists»).
    """
    game_sub = os.path.join(game_dir, "game")
    if os.path.isdir(game_sub):
        for root, dirs, files in os.walk(game_sub):
            def keep(d: str) -> bool:
                if d in ("renpy", "__pycache__", "ob_fonts",
                         "ob_fonts_orig"):
                    return False
                if extract_lang is not None and os.path.basename(root) == "tl":
                    return d == extract_lang
                return True
            dirs[:] = [d for d in dirs if keep(d)]
            for f in sorted(files):
                if f.endswith(".rpy") or f.endswith(".rpyc"):
                    if _is_ob_artifact(f):
                        continue
                    path = os.path.join(root, f)
                    rel = os.path.relpath(path, game_dir).replace(os.sep, "/")
                    yield path, rel

    try:
        from app.core.renpy.rpa import RpaArchive, find_rpa_archives as _find_rpa
        for arc_path in _find_rpa(game_dir):
            try:
                arc = RpaArchive(arc_path)
                arc_name = os.path.basename(arc_path)
            except Exception:
                continue
            for fname in arc.files:
                if not (fname.endswith(".rpy") or fname.endswith(".rpyc")):
                    continue
                if _is_ob_artifact(fname.rsplit("/", 1)[-1]):
                    continue
                if extract_lang and fname.startswith("tl/"):
                    head = fname[len("tl/"):].split("/", 1)[0]
                    if head != extract_lang:
                        continue
                yield f"rpa://{arc_name}/{fname}", fname
    except ImportError:
        pass


def extract(game_dir: str, extract_lang: str | None = None
            ) -> list[TranslationEntry]:
    """Extract all translatable strings from .rpy/.rpyc files.

    extract_lang: выбрать один язык из game/tl/ (см. list_languages),
    остальные языки не извлекаются (иначе текст дублируется по числу
    языков — 13k строк × 5 языков = 65k). None = весь текст, включая
    все официальные переводы tl/*.
    """
    entries: list[TranslationEntry] = []
    next_id = 1
    seen_originals: set[str] = set()

    def add(file: str, context: str, original: str):
        nonlocal next_id
        if not original or len(original.strip()) < 2:
            return
        # ВАЖНО: не strip() — игровая строка сохраняется дословно.
        # Строки с ведущими/хвостовыми пробелами (части интерполированных
        # реплик «Привет, »/« конец», диалоги с пробелом перед закрывающей
        # кавычкой) обязаны совпадать с текстом игры ПОСИМВОЛЬНО: рантайм-
        # хук Text.__init__ ищет точное вхождение в ob_dict.json, а
        # официальный механизм tl/* матчит old-блоки по точной строке.
        key = original
        if key in seen_originals:
            return
        seen_originals.add(key)
        entries.append(TranslationEntry(
            id=next_id, file=file, json_path=f"ctx:{context[:60]}",
            context=context, original=original))
        next_id += 1

    # .rpa-архивы открываем один раз — раньше каждый .rpyc из архива
    # заново сканировал game/ и перечитывал индекс (O(файлов × архивов)).
    from app.core.renpy.rpa import RpaArchive
    _archives: dict[str, RpaArchive | None] = {}
    for arc_path in find_rpa_archives(game_dir):
        try:
            _archives[os.path.basename(arc_path)] = RpaArchive(arc_path)
        except Exception:
            _archives[os.path.basename(arc_path)] = None

    for path, rel in _iter_rpy(game_dir, extract_lang):
        # ── .rpyc from RPA archive ──
        if path.startswith("rpa://"):
            parts = path[len("rpa://"):].split("/", 1)
            if len(parts) != 2:
                continue
            arc_name, fname = parts
            arc = _archives.get(arc_name)
            if arc is None:
                continue
            try:
                raw = arc.read(fname)
                if fname.endswith(".rpyc"):
                    parsed = _unpickle_rpyc(raw)
                    if parsed:
                        _, stmts = parsed
                        for kind, s in _walk_ast(stmts):
                            add(rel, f"{rel}:{kind}", s)
                else:
                    text = raw.decode("utf-8", errors="replace")
                    for n, line in enumerate(text.splitlines(), 1):
                        _extract_line(rel, n, line, add)
            except Exception:
                continue

        # ── .rpyc from disk ──
        elif path.endswith(".rpyc"):
            try:
                with open(path, "rb") as f:
                    raw = f.read()
                parsed = _unpickle_rpyc(raw)
                if parsed:
                    _, stmts = parsed
                    for kind, s in _walk_ast(stmts):
                        add(rel, f"{rel}:{kind}", s)
            except Exception:
                pass

        # ── .rpy from disk ──
        else:
            try:
                with open(path, encoding="utf-8") as f:
                    lines = f.readlines()
                i = 0
                n_lines = len(lines)
                while i < n_lines:
                    line = lines[i]
                    # Многострочная строка-диалог (кавычка не закрыта на
                    # строке): склеиваем физические строки в логическую,
                    # пока нечётное число неэкранированных кавычек не
                    # станет чётным. Только для строк, похожих на диалог/
                    # old-блок — код (python: и т.п.) не склеиваем.
                    if _unescaped_quotes(line) % 2 == 1 \
                            and (RE_QUOTE_START.match(line)
                                 or RE_OLD.match(line)):
                        start = i
                        buf = [line]
                        odd = True
                        guard = 0
                        while i + 1 < n_lines and odd and guard < 200:
                            i += 1
                            guard += 1
                            nxt = lines[i]
                            buf.append(nxt)
                            if _unescaped_quotes(nxt) % 2 == 1:
                                odd = False
                        _extract_line(rel, start + 1, "".join(buf), add)
                    else:
                        _extract_line(rel, i + 1, line, add)
                    i += 1
            except (OSError, UnicodeDecodeError):
                pass

    return entries


def _unescaped_quotes(line: str) -> int:
    """Число неэкранированных двойных кавычек в строке (чётность решает,
    закрыта ли строка-литерал на этой физической строке)."""
    count = 0
    i, n = 0, len(line)
    while i < n:
        if line[i] == "\\":
            i += 2
            continue
        if line[i] == '"':
            count += 1
        i += 1
    return count


def _extract_line(rel: str, n: int, line: str, add) -> None:
    """Extract strings from a single .rpy source line."""
    if len(line) > 4000 or RE_COMMENT.match(line):
        return
    try:
        found: list[tuple[str, str]] = []
        m = RE_OLD.match(line)
        if m:
            found.append((m.group(1), "translate-block"))
        else:
            m = RE_CHOICE.match(line)
            if m:
                found.append((m.group(1), "choice"))
            else:
                stripped = line.lstrip()
                if not _DLG_SKIP_RE.match(stripped):
                    dm = RE_DIALOGUE.match(line)
                    if dm:
                        found.append((dm.group(1), "dialogue"))
        for mm in RE_TR_FN.finditer(line):
            found.append((mm.group(1), "_()"))
    except Exception:
        return
    for text, kind in found:
        # текст из кавычек сохраняем дословно (см. add) — пробелы значимы
        if text:
            add(rel, f"{rel}:{n}:{kind}", text)


def _is_ob_artifact(fname: str) -> bool:
    """True для файлов, создаваемых OctopusBridge: ob_*.rpy/rpyc и
    ob_dict.json. Их нельзя извлекать как текст игры (см. _iter_rpy)."""
    base = fname.rsplit("/", 1)[-1].lower()
    return base.startswith("ob_") and (
        base.endswith(".rpy") or base.endswith(".rpyc")
        or base.endswith(".json"))


def _escape(text: str) -> str:
    """Экранирование для записи в .rpy внутри двойных кавычек.

    Ren'Py 8.2 не парсит строковые литералы с настоящими переносами строк —
    многострочные реплики игры (\\n внутри исходника) обязаны уходить в
    файл как escape-последовательность \\n, иначе Ren'Py падает с
    «Could not parse string». Порядок важен: сначала backslash и кавычки,
    затем переводы строк (они «рождают» новый backslash, который не должен
    экранироваться повторно).
    """
    return (text.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\r\n", "\\n").replace("\r", "\\n")
            .replace("\n", "\\n").replace("\t", "\\t"))


def _unescape_rpy_string(text: str) -> str:
    """Обратное преобразование к _escape(): \\n → перевод строки,
    \\t → таб, \\" → кавычка, \\\\ → один backslash.

    Порядок важен: обычный chained-replace сначала сворачивает \\\\ в \\,
    а затем ложно превращает литеральную последовательность \\n (backslash
    + n из текста игры, в файле \\\\n) в настоящий перевод строки.
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("\t")
            elif nxt == '"':
                out.append('"')
            elif nxt == "\\":
                out.append("\\")
            else:
                out.append(nxt)
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _read_existing_olds(out_path: str) -> set[str]:
    """Old-строки из ранее сгенерированного ob_*.rpy.

    Нужны, чтобы отличить НОВЫЕ записи (игра обновилась, текст сдвинулся)
    от уже применённых: новые блоки помечаются комментарием.
    """
    if not os.path.exists(out_path):
        return set()
    try:
        with open(out_path, encoding="utf-8") as f:
            multiline = re.compile(RE_OLD.pattern, re.MULTILINE)
            raw = multiline.findall(f.read())
        return {_unescape_rpy_string(r) for r in raw}
    except OSError:
        return set()


def apply(game_dir: str, entries: list[TranslationEntry],
          target_lang: str = "ru") -> dict:
    """Generate game/tl/<lang>/ob_*.rpy with old/new blocks.

    ВАЖНО: раньше здесь стоял фильтр `e.file.endswith(".rpy")`, из-за
    которого весь текст, извлечённый из .rpa/.rpyc (а это большинство
    реальных игр — они пакуют скомпилированные .rpyc в архив и не кладут
    рядом .rpy), молча выбрасывался и никогда не попадал в файл перевода.
    Убрано — старый/новый блок теперь пишется для ЛЮБОГО файла-источника.

    Безопасная запись: над каждым блоком пишется SHA1 оригинала
    (# ob-sha1 <hex>), новые строки помечаются # ob-new — по этим
    меткам видно, сдвинулся ли текст после обновления игры.
    """
    lang = LANG_FOLDERS.get(target_lang, target_lang)
    by_file: dict[str, list[TranslationEntry]] = {}
    unsafe_count = 0
    for e in entries:
        if e.translation.strip() and e.status != "skip":
            if not _is_interp_safe(e.original, e.translation):
                unsafe_count += 1
                continue
            by_file.setdefault(e.file, []).append(e)

    tl_dir = os.path.join(game_dir, "game", "tl", lang)
    stats = {"files": 0, "strings": 0, "new_strings": 0, "out_dir": "",
             "unsafe_skipped": unsafe_count, "removed_orphans": 0,
             "dup_skipped": 0}
    written_paths: set[str] = set()
    # Ren'Py запрещает дубликаты old-строк в одном языке (падение
    # «A translation ... already exists»), поэтому одна и та же реплика
    # из разных скриптов игры пишется ровно один раз — в первый файл.
    global_olds: set[str] = set()
    for rel, items in by_file.items():
        flat = rel.replace("/", "__")
        if flat.endswith(".rpy"):
            flat = flat[:-4]
        out_path = os.path.join(tl_dir, f"ob_{flat}.rpy")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        written_paths.add(out_path)
        existing_olds = _read_existing_olds(out_path)
        seen_old: set[str] = set()
        deduped: list[TranslationEntry] = []
        for e in items:
            if e.original in seen_old or e.original in global_olds:
                if e.original not in seen_old:
                    stats["dup_skipped"] += 1
                continue
            seen_old.add(e.original)
            global_olds.add(e.original)
            deduped.append(e)
        new_count = 0
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# OctopusBridge translation ({rel})\n"
                    f"translate {lang} strings:\n\n")
            for e in deduped:
                if e.original not in existing_olds:
                    new_count += 1
                digest = hashlib.sha1(
                    e.original.encode("utf-8")).hexdigest()[:12]
                f.write(f"    # ob-sha1 {digest}\n")
                f.write(f'    old "{_escape(e.original)}"\n')
                f.write(f'    new "{_escape(e.translation)}"\n\n')
        stats["files"] += 1
        stats["strings"] += len(deduped)
        stats["new_strings"] += new_count
        stats["out_dir"] = os.path.dirname(out_path)

    if stats["files"] > 0:
        # Осиротевшие ob_*.rpy: файлы, оставшиеся от старых билдов
        # (до 0.5.9, когда переносы строк не экранировались) или от
        # прежнего языка извлечения (tl/english, tl/french, ...).
        # Их записи больше не в by_file — файл не перезапишется, но
        # Ren'Py читает его при старте и падает с «Could not parse
        # string». Удаляем всё ob_*.rpy, не переписанное в этот прогон.
        try:
            for fname in os.listdir(tl_dir):
                if not (fname.startswith("ob_") and fname.endswith(".rpy")):
                    continue
                if fname == "ob_activate.rpy":
                    continue  # пересоздаётся ниже, не осиротевший
                path = os.path.join(tl_dir, fname)
                if path not in written_paths:
                    os.remove(path)
                    stats["removed_orphans"] += 1
        except OSError:
            pass

    if stats["files"] > 0:
        import json
        import shutil

        font_src = os.path.join(os.path.dirname(__file__), "..", "assets",
                                "fonts", "NotoSans-Regular.ttf")
        font_dst_dir = os.path.join(game_dir, "game", "ob_fonts")
        os.makedirs(font_dst_dir, exist_ok=True)
        font_dst = os.path.join(font_dst_dir, "NotoSans-Regular.ttf")
        if os.path.isfile(font_src) and not os.path.exists(font_dst):
            shutil.copy2(font_src, font_dst)

        # ── JSON-словарь original -> translation (для рантайм-хука) ──
        # Строится из ВСЕХ entries сразу, независимо от файла-источника,
        # это и есть словарь для универсального перехвата текста.
        full_dict: dict[str, str] = {}
        for e in entries:
            if e.translation.strip() and e.status != "skip" \
                    and _is_interp_safe(e.original, e.translation):
                full_dict[e.original] = e.translation
        dict_path = os.path.join(game_dir, "game", "tl", lang,
                                 "ob_dict.json")
        os.makedirs(os.path.dirname(dict_path), exist_ok=True)
        with open(dict_path, "w", encoding="utf-8") as f:
            json.dump(full_dict, f, ensure_ascii=False)

        activate_path = os.path.join(game_dir, "game", "tl", lang,
                                     "ob_activate.rpy")
        with open(activate_path, "w", encoding="utf-8") as f:
            f.write(_ACTIVATE_TEMPLATE.format(lang=lang))

    return stats


# Шаблон рантайм-активатора: подключает язык, грузит JSON-словарь и
# ставит ДВА независимых, дополняющих друг друга механизма перевода:
#
# 1) Хук на Text.__init__ — перехватывает АБСОЛЮТНО ЛЮБОЙ текст в момент
#    создания Text-displayable (диалог, реплика, пункт меню, кнопка
#    экрана, всплывающее уведомление — всё это в итоге создаёт Text).
#    Ищет точную строку в словаре и подменяет её ДО того, как Ren'Py
#    вообще начнёт что-либо парсить/лейаутить. Не зависит от того,
#    зарегистрировал ли официальный tl-механизм эту строку как
#    "переводимую" — если строка была в словаре, она будет заменена
#    в любом контексте. Именно так работают инструменты вроде MTool:
#    не встраивание перевода "по месту", а перехват на границе рендера.
#
# 2) FontGroup на каждый именованный стиль — вместо жёсткой замены шрифта
#    (что теряет иконки/спецсимволы оригинального шрифта и требует ручного
#    перечисления имён стилей) берём оригинальный шрифт стиля и НАШ шрифт
#    как fallback по диапазону кодовых точек: там, где в оригинальном
#    шрифте нет кириллицы — символ берётся из NotoSans, всё остальное
#    (латиница, иконки) остаётся как в оригинале. Проходим по ВСЕМ стилям
#    через dir(store.style), а не по жёсткому списку — так patch покрывает
#    и кастомные стили, которых разработчик игры мог насоздавать сколько
#    угодно под свои экраны.
_ACTIVATE_TEMPLATE = '''# OctopusBridge: activate {lang} translation + universal text/font hooks
init 1 python:
    config.language = "{lang}"

init -999 python:
    import json as _ob_json
    try:
        _ob_dict_path = renpy.loader.transfn("tl/{lang}/ob_dict.json")
        with open(_ob_dict_path, "r", encoding="utf-8") as _ob_f:
            _OB_DICT = _ob_json.load(_ob_f)
    except Exception:
        _OB_DICT = {{}}

    if not hasattr(renpy.text.text.Text, "_ob_patched"):
        _ob_orig_text_init = renpy.text.text.Text.__init__

        def _ob_text_init(self, text, *args, **kwargs):
            try:
                if isinstance(text, str):
                    text = _OB_DICT.get(text, text)
                elif isinstance(text, list):
                    text = [_OB_DICT.get(t, t) if isinstance(t, str) else t
                            for t in text]
            except Exception:
                pass
            return _ob_orig_text_init(self, text, *args, **kwargs)

        renpy.text.text.Text.__init__ = _ob_text_init
        renpy.text.text.Text._ob_patched = True

init 999 python:
    _ob_fallback_font = "ob_fonts/NotoSans-Regular.ttf"

    def _ob_patch_fonts():
        for _name in dir(store.style):
            if _name.startswith("_"):
                continue
            try:
                _s = getattr(store.style, _name)
                _orig = _s.font
            except Exception:
                continue
            if not hasattr(_s, "font"):
                continue
            try:
                _base = _orig if isinstance(_orig, str) else "DejaVuSans.ttf"
                _fg = renpy.text.font.FontGroup()
                _fg.add(_base, 0x0000, 0x00FF)
                _fg.add(_ob_fallback_font, 0x0100, 0x10FFFF)
                _s.font = _fg
            except Exception:
                pass

    _ob_patch_fonts()
    config.start_callbacks.append(_ob_patch_fonts)
    config.after_load_callbacks.append(_ob_patch_fonts)
'''
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

class _RevertableDict(dict):
    pass

class _MockNode:
    pass

_RENPY_MOCKS: dict[tuple[str, str], type] = {
    ("renpy.ast", "PyCode"): _PyCode,
    ("renpy.astsupport", "PyExpr"): _PyExpr,
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

        if nt == "Say":
            what = getattr(nodes, "what", None)
            who = getattr(nodes, "who", None)
            if what and isinstance(what, str):
                result.append(("dialogue", what))
            if who and isinstance(who, str):
                result.append(("speaker", who))

        elif nt == "TranslateSay":
            what = getattr(nodes, "what", None)
            if what and isinstance(what, str):
                result.append(("dialogue", what))
            who = getattr(nodes, "who", None)
            if who and isinstance(who, str):
                result.append(("speaker", who))

        elif nt == "Menu":
            items = getattr(nodes, "items", [])
            for item in items:
                label = item[0] if isinstance(item, (list, tuple)) else None
                if label and isinstance(label, str) and len(label) >= 2:
                    result.append(("choice", label))
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
            for m in re.finditer(r'"[^"]*"\s*,\s*"([^"]+)"', src):
                if src.strip().startswith("define"):
                    result.append(("character_name", m.group(1)))

        elif nt == "Python":
            code = getattr(nodes, "code", None)
            src = getattr(code, "source", "") if code else ""
            for m in re.finditer(r'create_character\(\s*"([^"]+)"\s*,\s*"([^"]+)"', src):
                result.append(("character", m.group(1)))
                result.append(("character_name", m.group(2)))

        elif nt == "Screen":
            screen = getattr(nodes, "screen", None)
            if screen:
                name = getattr(screen, "name", None)
                if name and isinstance(name, str):
                    result.append(("screen", name))

        walk(getattr(nodes, "block", []))
        walk(getattr(nodes, "body", []))

    walk(stmts)
    return result

# ── Main API ────────────────────────────────────────────────────────

def detect(game_dir: str) -> bool:
    """Is this a Ren'Py game? (has game/ with .rpy/.rpa or renpy/)"""
    game_sub = os.path.join(game_dir, "game")
    if os.path.isdir(game_sub):
        for _root, _dirs, files in os.walk(game_sub):
            if any(f.endswith(".rpy") for f in files):
                return True
            if any(f.endswith(".rpa") for f in files):
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


def _iter_rpy(game_dir: str):
    """Iterate .rpy and .rpyc files from game/ and .rpa archives."""
    game_sub = os.path.join(game_dir, "game")
    if os.path.isdir(game_sub):
        for root, dirs, files in os.walk(game_sub):
            dirs[:] = [d for d in dirs if d not in ("tl", "renpy", "__pycache__")]
            for f in sorted(files):
                if f.endswith(".rpy") or f.endswith(".rpyc"):
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
                if fname.endswith(".rpy") or fname.endswith(".rpyc"):
                    yield f"rpa://{arc_name}/{fname}", fname
    except ImportError:
        pass


def extract(game_dir: str) -> list[TranslationEntry]:
    """Extract all translatable strings from .rpy/.rpyc files."""
    entries: list[TranslationEntry] = []
    next_id = 1
    seen_originals: set[str] = set()

    def add(file: str, context: str, original: str):
        nonlocal next_id
        if not original or len(original.strip()) < 2:
            return
        key = original.strip()
        if key in seen_originals:
            return
        seen_originals.add(key)
        entries.append(TranslationEntry(
            id=next_id, file=file, json_path=f"ctx:{context[:60]}",
            context=context, original=key))
        next_id += 1

    for path, rel in _iter_rpy(game_dir):
        # ── .rpyc from RPA archive ──
        if path.startswith("rpa://"):
            try:
                from app.core.renpy.rpa import RpaArchive
                parts = path[len("rpa://"):].split("/", 1)
                arc_name, fname = parts
                for arc_path in find_rpa_archives(game_dir):
                    if os.path.basename(arc_path) == arc_name:
                        arc = RpaArchive(arc_path)
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
                        break
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
                for n, line in enumerate(lines, start=1):
                    _extract_line(rel, n, line, add)
            except (OSError, UnicodeDecodeError):
                pass

    return entries


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
        text = text.strip()
        if text:
            add(rel, f"{rel}:{n}:{kind}", text)


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
        # разэкранирование: old-строки пишутся через _escape()
        return {(r.replace("\\\\", "\\").replace('\\"', '"')
                 .replace("\\t", "\t").replace("\\n", "\n")) for r in raw}
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

    stats = {"files": 0, "strings": 0, "new_strings": 0, "out_dir": "",
             "unsafe_skipped": unsafe_count}
    for rel, items in by_file.items():
        flat = rel.replace("/", "__")
        if flat.endswith(".rpy"):
            flat = flat[:-4]
        out_path = os.path.join(game_dir, "game", "tl", lang,
                                f"ob_{flat}.rpy")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        existing_olds = _read_existing_olds(out_path)
        seen_old: set[str] = set()
        deduped: list[TranslationEntry] = []
        for e in items:
            if e.original not in seen_old:
                seen_old.add(e.original)
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
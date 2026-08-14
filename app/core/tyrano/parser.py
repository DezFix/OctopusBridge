# -*- coding: utf-8 -*-
"""Поддержка TyranoScript / TyranoBuilder (HTML5): детект, извлечение, внедрение.

Tyrano-игра — это HTML5-проект с папкой data/scenario/*.ks (KAG-подобные
сценарии) и движком в tyrano/. Приложение лежит в корне игры либо в
подпапке: www/ (MV-подобная сборка) или resources/app (Electron-сборка
TyranoBuilder) — корень ищется автоматически. Текст лежит построчно:
реплики — обычные строки, инлайн-теги ([l], [bg storage="..."], [link],
[ruby] и т.п.) обрамляют или несут текст.

Извлечение: строка разбивается на сегменты — текст и теги. В перевод
попадают ТОЛЬКО текстовые сегменты (теги остаются в файле нетронутыми,
переводчику они не показываются) и атрибуты text="..." тегов
link/button/ruby. Управляющие строки (;комментарии, *метки, блоки
[iscript]...[endscript], строки из одних тегов) пропускаются.

Внедрение: позиции записей выводятся из структуры строки заново
(json_path вида line[N].seg[M] / line[N].tag[K].text) и проверяются
по оригиналу — сдвиг файла не ломает перевод, чужие правки не
затираются. Дополнительно проверяется сохранность переменных Tyrano
(%var, &var, tf.x, f.x, sf.x) в переводе.
"""
from __future__ import annotations

import os
import re
import shutil

from app.core.models import TranslationEntry

# Теги, чей атрибут text="..." — видимый текст (переводим)
_TEXT_ATTR_TAGS = {"link", "button", "ruby"}

# Блочные теги JS-кода: содержимое между ними не переводится
_SCRIPT_BLOCK_OPEN = {"iscript", "script"}
_SCRIPT_BLOCK_CLOSE = {"endscript"}

# Строки с одним тегом (управление) — сами не переводятся, но внутри
# тега может быть text="..." — его извлекаем отдельно.
_RE_TAG = re.compile(r"\[/?([A-Za-z_][\w-]*)((?:[^\]]*))\]")
_RE_ATTR = re.compile(r'([A-Za-z_:][\w:.-]*)\s*=\s*("[^"]*"|\'[^\']*\')')

# Переменные Tyrano: %user, &system, tf./f./sf. флаги
_VAR_RE = re.compile(
    r"(%[A-Za-z_][\w]*|&[A-Za-z_][\w]*|\btf\.[A-Za-z_]\w*|"
    r"\bf\.[A-Za-z_]\w*|\bsf\.[A-Za-z_]\w*)")

_ENC_CACHE: dict[str, str] = {}  # abs path -> 'utf-8' | 'cp932'
_NL_CACHE: dict[str, str] = {}   # abs path -> '\n' | '\r\n' (перевод строк файла)
_TRAIL_CACHE: dict[str, bool] = {}  # abs path -> файл кончался переводом строки


def _read_lines(path: str) -> list[str]:
    """Читает .ks с автоопределением кодировки (UTF-8 или Shift-JIS).

    Запоминает кодировку, перевод строк (CRLF/LF) и наличие завершающего
    перевода строки — внедрение пишет файл в исходном виде.
    """
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
        _ENC_CACHE[path] = "utf-8" if enc != "cp932" else "cp932"
        _NL_CACHE[path] = "\r\n" if b"\r\n" in raw else "\n"
        _TRAIL_CACHE[path] = text.endswith(("\n", "\r"))
        return text.splitlines()
    # не разобрали — пропускаем файл (бинарный/битый)
    raise UnicodeDecodeError("tyrano", raw, 0, 1, "no suitable encoding")


def _write_text(path: str, text: str):
    enc = _ENC_CACHE.get(path, "utf-8")
    with open(path, "w", encoding=enc, newline="") as f:
        f.write(text)


# ── токенизация строки ──

def _split_tokens(line: str) -> list[tuple[str, str]]:
    """Разбивает строку на токены [(тип, текст)], тип: 'text' | 'tag'.

    Тег — всё, что начинается с '[' и заканчивается ']' ВНЕ кавычек
    атрибутов: [link text="a[b]" target="*x"] — один токен целиком,
    вложенная ']' внутри "..." тег не режет (текст атрибута извлекается
    и переводится как положено).
    """
    tokens: list[tuple[str, str]] = []
    buf: list[str] = []
    i, n = 0, len(line)
    while i < n:
        if line[i] == "[":
            # ищем закрывающую ']', игнорируя скобки внутри "..." / '...'
            quote = ""
            j = i + 1
            while j < n:
                c = line[j]
                if quote:
                    if c == quote:
                        quote = ""
                elif c in ('"', "'"):
                    quote = c
                elif c == "]":
                    break
                j += 1
            if j >= n:
                buf.append(line[i:])
                break
            if buf:
                tokens.append(("text", "".join(buf)))
                buf = []
            tokens.append(("tag", line[i:j + 1]))
            i = j + 1
        else:
            buf.append(line[i])
            i += 1
    if buf:
        tokens.append(("text", "".join(buf)))
    return tokens


def _tag_attrs(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for m in _RE_ATTR.finditer(tag):
        attrs[m.group(1)] = m.group(2)[1:-1]
    return attrs


def _tag_name(tag: str) -> str:
    m = _RE_TAG.match(tag)
    return m.group(1) if m else ""


def _has_letters(text: str) -> bool:
    return any(ch.isalpha() for ch in text)


# ── детект ──

# Tyrano-приложение может лежать в подпапке: стандартная сборка в корне,
# MV-подобная — в www/, Electron-сборка (TyranoBuilder) — в resources/app/
_APP_ROOT_CANDIDATES = ("", "www", os.path.join("resources", "app"))


def _app_root(game_dir: str) -> str | None:
    """Папка с приложением Tyrano (tyrano/ или data/scenario/) или None."""
    for sub in _APP_ROOT_CANDIDATES:
        cand = os.path.join(game_dir, sub) if sub else game_dir
        if os.path.isdir(os.path.join(cand, "tyrano")) or \
                os.path.isdir(os.path.join(cand, "data", "scenario")):
            return cand
    return None


def detect(game_dir: str) -> int:
    """Вес уверенности: 0 — не Tyrano."""
    root = _app_root(game_dir)
    if not root:
        return 0
    if os.path.isdir(os.path.join(root, "tyrano")):
        if os.path.isdir(os.path.join(root, "data", "scenario")):
            return 95
        return 70
    scenario = os.path.join(root, "data", "scenario")
    try:
        for f in os.listdir(scenario):
            if f.lower().endswith(".ks"):
                return 80
    except OSError:
        pass
    return 0


def _iter_ks(game_dir: str):
    """Все .ks файлы игры: (абс. путь, путь относительно папки игры)."""
    root = _app_root(game_dir) or game_dir
    for sub in (os.path.join("data", "scenario"),
                os.path.join("data", "system")):
        scan = os.path.join(root, sub)
        if not os.path.isdir(scan):
            continue
        for fname in sorted(os.listdir(scan)):
            if not fname.lower().endswith(".ks"):
                continue
            path = os.path.join(scan, fname)
            rel = os.path.relpath(path, game_dir).replace(os.sep, "/")
            yield path, rel


# ── извлечение ──

class _Extractor:
    def __init__(self):
        self.entries: list[TranslationEntry] = []
        self._next_id = 1

    def add(self, file: str, path: str, context: str, original: str):
        original = original.strip()
        if not original or not _has_letters(original):
            return
        self.entries.append(TranslationEntry(
            id=self._next_id, file=file, json_path=path,
            context=context, original=original))
        self._next_id += 1

    def line(self, file: str, rel: str, n: int, line: str):
        """Одна строка .ks: сегменты текста + text="..." тегов."""
        if len(line) > 4000:
            return
        tokens = _split_tokens(line)
        text_tokens = [t for t in tokens if t[0] == "text"]
        # строка из одних тегов — текста нет, но text="..." может быть
        if not text_tokens:
            self._tag_texts(file, rel, n,
                            [t for t in tokens if t[0] == "tag"])
            return
        seg_idx = 0
        for kind, value in tokens:
            if kind == "text":
                seg_idx += 1
                self.add(file, f"line[{n}].seg[{seg_idx}]",
                         f"{rel}:{n} text", value)
        self._tag_texts(file, rel, n,
                        [t for t in tokens if t[0] == "tag"])

    def _tag_texts(self, file: str, rel: str, n: int, tags: list):
        """text="..." у link/button/ruby (стиль [link text="..."])."""
        for k, (_kind, tag) in enumerate(tags):
            if _tag_name(tag) not in _TEXT_ATTR_TAGS:
                continue
            attrs = _tag_attrs(tag)
            text = attrs.get("text")
            if text:
                self.add(file, f"line[{n}].tag[{k}].text",
                         f"{rel}:{n} {_tag_name(tag)}", text)


def extract(game_dir: str) -> list[TranslationEntry]:
    """Извлекает все переводимые строки из data/scenario/*.ks."""
    ex = _Extractor()
    for path, rel in _iter_ks(game_dir):
        try:
            lines = _read_lines(path)
        except (OSError, UnicodeDecodeError):
            continue
        in_script = False
        for n, raw_line in enumerate(lines, 1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            # блок JS-кода
            if in_script:
                if stripped == "[endscript]" or _tag_name(stripped) == "endscript":
                    in_script = False
                continue
            tag = _tag_name(stripped)
            if tag in _SCRIPT_BLOCK_OPEN:
                in_script = True
                continue
            if stripped.startswith(";") or stripped.startswith("*"):
                continue
            ex.line(file=rel, rel=rel, n=n, line=raw_line)
    return ex.entries


# ── безопасность переменных ──

def _is_var_safe(original: str, translation: str) -> bool:
    """True, если все переменные Tyrano (%var, &var, tf.x, f.x, sf.x)
    оригинала присутствуют в переводе ДОСЛОВНО и в том же порядке.

    Машинный перевод может заменить %имя_переменной текстом — движок
    тогда выведет имя, а не значение. Такие записи не применяем.
    """
    codes = _VAR_RE.findall(original)
    if not codes:
        return True
    pos = 0
    for code in codes:
        idx = translation.find(code, pos)
        if idx == -1:
            return False
        pos = idx + len(code)
    return True


# ── внедрение ──

_PATH_RE = re.compile(r"line\[(\d+)\](?:\.seg\[(\d+)\]|\.tag\[(\d+)\]\.text)?")


def apply(game_dir: str, entries: list[TranslationEntry],
          backup_root: str | None = None, on_skip=None,
          target_lang: str = "", **kwargs) -> dict:
    """Внедряет переводы в .ks файлы (с бэкапом). Возвращает статистику.

    Для каждой записи позиция выводится из структуры строки заново
    (line[N].seg[M] / line[N].tag[K].text), текущий сегмент сверяется
    с оригиналом — расхождение (файл изменился) пропускает запись.
    target_lang принимается для единого контракта движков.
    """
    if backup_root is None:
        backup_root = os.path.join(game_dir, "backup")
    by_file: dict[str, list[TranslationEntry]] = {}
    for e in entries:
        if e.translation.strip() and e.status != "skip":
            by_file.setdefault(e.file, []).append(e)

    stats = {"files": 0, "strings": 0, "unsafe_skipped": 0, "backups": []}

    for rel, items in by_file.items():
        abs_path = os.path.join(game_dir, *rel.split("/"))
        if not os.path.exists(abs_path):
            continue
        try:
            lines = _read_lines(abs_path)
        except (OSError, UnicodeDecodeError):
            continue
        backup_path = os.path.join(backup_root, rel)
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        if not os.path.exists(backup_path):
            shutil.copy2(abs_path, backup_path)
            stats["backups"].append(backup_path)

        written = 0
        for e in items:
            m = _PATH_RE.match(e.json_path)
            if not m:
                continue
            n = int(m.group(1)) - 1
            if n < 0 or n >= len(lines):
                continue
            if not _is_var_safe(e.original, e.translation):
                stats["unsafe_skipped"] += 1
                continue
            line = lines[n]
            if m.group(2) is not None:
                new_line, ok = _replace_seg(line, int(m.group(2)),
                                            e.original, e.translation)
            elif m.group(3) is not None:
                new_line, ok = _replace_tag_attr(line, int(m.group(3)),
                                                 e.original, e.translation)
            else:
                ok = False
                if line.strip() == e.original:
                    lead = line[:len(line) - len(line.lstrip())]
                    new_line = lead + e.translation
                    ok = True
            if not ok:
                if on_skip:
                    on_skip(e, f"{rel}: строка {n + 1}: оригинал не найден")
                continue
            lines[n] = new_line
            written += 1
        if written:
            # пишем в исходной кодировке, переводе строк (CRLF/LF)
            # и с завершающим переводом строки, как было в файле
            nl = _NL_CACHE.get(abs_path, "\n")
            body = nl.join(lines)
            if _TRAIL_CACHE.get(abs_path, False) and not body.endswith(nl):
                body += nl
            _write_text(abs_path, body)
        stats["files"] += 1 if written else 0
        stats["strings"] += written
    return stats


# имя старых таймстамп-папок бэкапа: YYYYmmdd_HHMMSS
_TS_RE = re.compile(r"^\d{8}_\d{6}$")


def restore_original(game_dir: str) -> dict:
    """Восстанавливает оригинальные .ks из backup/ (одноразовый бэкап
    до первого перевода: backup/<rel> либо старые backup/<ts>/<rel>).
    Возвращает статистику."""
    root = os.path.join(game_dir, "backup")
    if not os.path.isdir(root):
        return {"restored": 0}
    restored = 0
    done: set[str] = set()
    # Плоский формат: backup/<rel> — приоритет (канонический оригинал)
    for _r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not _TS_RE.match(d)]
        for f in files:
            src = os.path.join(_r, f)
            rel = os.path.relpath(src, root).replace(os.sep, "/")
            if rel in done:
                continue
            dst = os.path.join(game_dir, *rel.split("/"))
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                done.add(rel)
                restored += 1
            except OSError:
                pass
    # Старые таймстамп-папки сортируются хронологически: первая
    # копия = оригинал до переводов.
    try:
        legacy = sorted(d for d in os.listdir(root)
                        if _TS_RE.match(d)
                        and os.path.isdir(os.path.join(root, d)))
    except OSError:
        legacy = []
    for d in legacy:
        base = os.path.join(root, d)
        for _r, _dirs, files in os.walk(base):
            for f in files:
                src = os.path.join(_r, f)
                rel = os.path.relpath(src, base).replace(os.sep, "/")
                if rel in done:
                    continue
                dst = os.path.join(game_dir, *rel.split("/"))
                try:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    done.add(rel)
                    restored += 1
                except OSError:
                    pass
    return {"restored": restored}


def _replace_seg(line: str, seg_idx: int, original: str,
                 translation: str) -> tuple[str, bool]:
    """Заменяет seg_idx-й текстовый сегмент строки (1-based)."""
    tokens = _split_tokens(line)
    text_count = 0
    changed = False
    for i, (kind, value) in enumerate(tokens):
        if kind != "text":
            continue
        text_count += 1
        if text_count == seg_idx:
            if value.strip() != original:
                return line, False
            # сохраняем отступы сегмента, как у twine-парсера
            lead = value[:len(value) - len(value.lstrip())]
            tokens[i] = ("text", lead + translation)
            changed = True
            break
    if not changed:
        return line, False
    return "".join(v for _k, v in tokens), True


def _replace_tag_attr(line: str, tag_idx: int, original: str,
                      translation: str) -> tuple[str, bool]:
    """Заменяет text="..." у tag_idx-го тега (0-based)."""
    tokens = _split_tokens(line)
    tag_count = 0
    for i, (kind, value) in enumerate(tokens):
        if kind != "tag":
            continue
        if tag_count != tag_idx:
            tag_count += 1
            continue
        if _tag_name(value) not in _TEXT_ATTR_TAGS:
            return line, False
        attrs = _tag_attrs(value)
        if attrs.get("text") != original:
            return line, False
        # точная замена внутри атрибута
        new_tag = _RE_ATTR.sub(
            lambda m: (f"{m.group(1)}={m.group(2)}"
                       if m.group(1) != "text"
                       else f'{m.group(1)}="{translation}"'),
            value)
        tokens[i] = ("tag", new_tag)
        return "".join(v for _k, v in tokens), True
    return line, False

# -*- coding: utf-8 -*-
"""Поддержка Twine (HTML5): детект, извлечение текста, внедрение перевода.

Twine-игра — это .html с элементом <tw-storydata>, внутри которого
пассажи <tw-passagedata pid="N" name="...">текст</tw-passagedata>.

Извлечение построчное: строки-макросы (<<...>> SugarCube, (...): Harlowe),
служебные строки и висячие [[ без закрытия пропускаются — переводятся
только строки с «живым» текстом. Подписи ссылок [[подпись|таргет]]
переводятся, а таргеты (имена пассажей) маскируются токенами и не
изменяются. HTML-сущности раскрываются при извлечении
и экранируются обратно при внедрении.

Защита кода игры (перевод НЕ ломает игру):
- Аргументы-КЛЮЧИ печатающих макросов (имена пассажей, $переменные,
  значения, CSS-селекторы) не извлекаются и не внедряются — перевод
  ключа убивает кнопку/ссылку/картинку (см. _PRINT_MACROS).
- Harlowe: (имя: …) и [подпись->таргет] маскируются целиком — картинки
  (image:), переходы (goto:) и условия не переводятся.
- Кавычка/|/-> в переведённой подписи не ломает макрос/ссылку:
  такие переводы отбрасываются при внедрении.
"""
from __future__ import annotations

import html as html_mod
import json
import os
import re
import shutil
from dataclasses import dataclass

from app.core.models import TranslationEntry

STORY_TAG = "<tw-storydata"
_MAX_HTML_SIZE = 64 * 1024 * 1024   # безопасный предел чтения

RE_PASSAGE = re.compile(
    r"<tw-passagedata\b([^>]*)>(.*?)</tw-passagedata>", re.DOTALL)
RE_ATTR = re.compile(r'(\w[\w-]*)="([^"]*)"')

# служебные строки (не переводим)
RE_MACRO_SUGARCUBE = re.compile(r"^\s*<<.*>>\s*$", re.DOTALL)
RE_MACRO_HARLOWE = re.compile(r"^\s*\(.*\)\s*$", re.DOTALL)
RE_COMMENT = re.compile(r"^\s*(/%%|%%/|<!--)")
RE_PURE_TAG = re.compile(r"^\s*<[^>]*>\s*$")

# коды внутри переводимой строки: SugarCube-макросы <<..>>, переменные
# $var и HTML-теги <..> — маскируются токенами <xN/>, чтобы переводчик
# (LLM/Honyaku) не изменил их и игра не упала («cannot find a closing
# tag for macro <<widget>>» и т.п.). Ссылки [[...]] обрабатываются
# отдельно (см. RE_LINK): подпись ссылки — текст для перевода, а таргет
# (имя пассажа) маскируется токеном.
# Лимиты щедрые: в игре встречаются длинные макросы
# (<<= either('…', '…', …)>> до 2 КБ) и длинные теги с путями к
# картинкам — если код не замаскировать, переводчик переведёт
# текст внутри (кавычки, >=, пути images/...) и сломает игру.
RE_TWINE_CODE = re.compile(
    r"<<[^>]{1,2000}>>"
    # naked-переменные по вики SugarCube: $var, $var.prop, $var[0],
    # $var["prop"], $var['prop'], $var[$idx] — иначе LLM переводит
    # «prop» внутри скобок/точек
    r"|\$[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*"
    r"|\[[^\]\n]{0,120}\]){0,4}"
    r"|</?[A-Za-z][^>]{0,2000}>")
# ссылка [[...]]: подпись|таргет, подпись->таргет, таргет<-подпись,
# таргет, с сеттерами [[подпись|таргет][$var to 1, ...]]
RE_LINK = re.compile(r"\[\[([^\]\n]{1,1000})\]\]")
# «код» внутри подписи ссылки (макросы, $var, теги, вложенные скобки) —
# такую подпись переводить нельзя, ссылка уходит в токен целиком
RE_LINK_CODE = re.compile(r"[<>$\[\]]|<<|>>")
_TOKEN_RE = re.compile(r"</?x(\d+)\s*/?>")
# любой макрос в строке (для детекта «выполняющего кода»)
RE_MACRO_ANY = re.compile(r"<<[^>]*>>")
# кириллица — признак того, что прошлый перевод залез внутрь макроса
RE_CYR = re.compile(r"[А-Яа-яЁё]")
# line continuation: '\' в начале/конце строки склеивает строки в
# SugarCube — перевод отдельной строки ломает структуру
_RE_LINE_CONT = re.compile(r"(^\\|\s*\\$)")
# служебные пассажи Twine: их содержимое — код (макросы, JS-массивы,
# стили), а не текст для игрока. Перевод строк внутри них ломает игру
# («bad evaluation», сломанные кавычки в коде и т.п.) — не извлекаем.
_SERVICE_NAMES = {
    "StoryInit", "StoryMenu", "StoryShare", "StoryInterface",
    "StoryStylesheet", "StoryJavaScript", "StoryCaption",
    "StoryDisplayTitle", "StorySettings", "PassageReady", "PassageDone",
}
# код-теги пассажей (вики SugarCube: init/script/stylesheet/widget)
_SERVICE_TAGS = {"widget", "init", "script", "stylesheet"}


def _is_service_passage(attrs: dict[str, str]) -> bool:
    tags = attrs.get("tags", "")
    name = html_mod.unescape(attrs.get("name", ""))
    return bool(_SERVICE_TAGS & set(tags.split())) or name in _SERVICE_NAMES


def _dangerous_macro(line: str) -> bool:
    """Есть ли в строке макрос, ВЫПОЛНЯЮЩИЙ код (set/run/if/вызов
    виджета и т.п.). Безопасны только печатающие: <<= expr>>,
    <<$var>> (старый синтаксис), <<print ...>>.

    Такие строки не переводим вообще: даже с маской токена
    переводчик может переставить макрос относительно текста
    или слить два макроса — логика игры сломается.
    """
    for m in RE_MACRO_ANY.finditer(line):
        body = m.group(0)[2:-2].lstrip()
        if (body.startswith("=") or body.startswith("$")
                or body.lower().startswith("print")):
            continue
        return True
    return False


# комментарий в коде (/* ... */) — не текст для игрока
RE_CODE_COMMENT = re.compile(r"/\*.*\*/", re.S)


def _is_code_comment(line: str) -> bool:
    return "/*" in line and "*/" in line


def _in_macro(line: str) -> bool:
    """Строка внутри/несбалансированного макроса (<</>> не сходятся).

    Многострочные макросы (<<set $x = {...}>> разбитый на строки) в
    Twine-экспорте выглядят как отдельные «текстовые» строки — по ним
    нельзя понять код; признак — незакрытый <<.
    """
    u = html_mod.unescape(line)
    return u.count("<<") != u.count(">>")


def _has_letters(text: str) -> bool:
    return any(ch.isalpha() for ch in text)


def _link_parts(inner: str) -> tuple[str, str, str]:
    """(подпись, разделитель, таргет) ссылки [[...]].

    Разделители по вики SugarCube/Harlowe: подпись->таргет,
    таргет<-подпись, подпись|таргет. Без разделителя подпись == таргет
    (переводить нельзя). Сеттеры [[подпись|таргет][$var to 1]] остаются
    в «таргете» — туда не смотрим.
    """
    for sep in ("->", "<-", "|"):
        i = inner.find(sep)
        if i >= 0:
            if sep == "<-":
                return inner[i + len(sep):].strip(), sep, inner[:i].strip()
            return inner[:i].strip(), sep, inner[i + len(sep):].strip()
    return inner.strip(), "", ""


def _mask_link(inner: str, codes: list[str]) -> str:
    """Маска одной ссылки: подпись остаётся текстом (если она статична
    и отличается от таргета), таргет уходит в токен <xN/>.

    Для обратного синтаксиса ([[таргет<-подпись]]) токен ставится ДО
    разделителя: замаскированную строку в apply разбирает тот же
    _link_parts, и подпись/таргет не путаются.
    """
    label, sep, target = _link_parts(inner)
    if not sep or RE_LINK_CODE.search(label):
        # без разделителя подпись == таргет: перевод имени пассажа
        # сломает переход. Подпись с кодом (макрос/$var/тег) тоже
        # не переводим — вся ссылка одним токеном.
        codes.append("[[%s]]" % inner)
        return f"<x{len(codes) - 1}/>"
    codes.append(target)
    if sep == "<-":
        return f"[[<x{len(codes) - 1}/>{sep}{label}]]"
    return f"[[{label}{sep}<x{len(codes) - 1}/>]]"


def _has_translatable_text(masked: str) -> bool:
    """Есть ли в замаскированной строке буквы вне токенов кодов."""
    return _has_letters(_TOKEN_RE.sub("", masked))


def find_story(game_dir: str) -> str | None:
    """Путь к .html с <tw-storydata> (сам файл, корень папки или
    1 уровень вглубь)."""
    candidates: list[str] = []
    if os.path.isfile(game_dir) \
            and game_dir.lower().endswith((".html", ".htm")):
        candidates.append(game_dir)
    for root, dirs, files in os.walk(game_dir):
        depth = os.path.relpath(root, game_dir).count(os.sep)
        if depth > 0:
            dirs[:] = []
        for f in sorted(files):
            if f.lower().endswith((".html", ".htm")):
                candidates.append(os.path.join(root, f))
    for path in candidates:
        try:
            if os.path.getsize(path) > _MAX_HTML_SIZE:
                continue
            with open(path, encoding="utf-8", errors="ignore") as f:
                head = f.read(2 * 1024 * 1024)
            if STORY_TAG in head:
                return path
        except OSError:
            continue
    return None


def _backup_dir(game_dir: str) -> str:
    """Каталог бэкапов рядом с игрой: если game_dir — сам .html-файл,
    бэкапы кладём рядом с ним, а не внутрь (внутрь файла нельзя)."""
    base = game_dir if os.path.isdir(game_dir) \
        else os.path.dirname(os.path.abspath(game_dir))
    return os.path.join(base, "backup")


def detect(game_dir: str) -> bool:
    return find_story(game_dir) is not None


def _attrs(attr_text: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in RE_ATTR.finditer(attr_text)}


def _story_format(text: str) -> str:
    """Формат истории из тега <tw-storydata>: 'SugarCube', 'Harlowe', ''."""
    m = re.search(r"<tw-storydata\b[^>]*>", text, re.DOTALL)
    if not m:
        return ""
    attrs = _attrs(m.group(0)[len("<tw-storydata"):-1])
    return attrs.get("format", "").strip()


# ── сегменты строки ──
# Каждая строка пассажа разбивается на сегменты: text (переводим),
# link [[...]] (переводим только подпись), macro <<...>> (не переводим,
# кроме строковых аргументов печатающих макросов — кнопок/ссылок),
# tag <...>, var $var, img [img[...]] (не переводим). Это позволяет
# брать текст из строк, где он перемешан с кодом (<<nobr>>Текст</div>),
# а не отбрасывать строку целиком.

_RE_VAR = re.compile(
    r"\$[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*"
    r"|\[[^\]\n]{0,120}\]){0,4}")

# печатающие макросы SugarCube 1/2: их строковые аргументы — видимый
# текст (кнопки, ссылки, выборы) и должны переводиться. НО не каждый
# строковый аргумент — текст: у части макросов есть аргументы-КЛЮЧИ —
# имена пассажей (переходы), $переменные (приёмники ввода), значения.
# Перевод ключа ломает игру («перевод убивает игры»): кнопка ведёт в
# несуществующий пассаж, сломанное имя переменной, битая картинка.
# Поэтому для каждого макроса заданы ПОЗИЦИИ аргументов:
#   text — строка для перевода (подпись кнопки/ссылки, промпт);
#   key  — идентификатор игры: не извлекаем и в apply не внедряем
#          (защита старых проектов, где ключи уже извлечены).
# Позиции — SugarCube 2 (доминирующий формат); позиции $переменных
# дополнительно защищены проверкой «аргумент начинается с $» в
# _extract_segment (перекрывает и SugarCube 1, где переменная первая:
# <<textbox "$var" "label">>).
# goto/display/include/widget/addclass — ВСЕ аргументы ключи (имена
# пассажей, CSS-селекторы) — их в списке нет, они не переводятся вовсе.
_PRINT_MACROS: dict[str, tuple[frozenset[int], frozenset[int]]] = {
    "button":      (frozenset({0}), frozenset({1})),   # SC1: [[...]]-ссылка
    "link":        (frozenset({0}), frozenset({1})),   # SC1: 2-й арг — пассаж
    "label":       (frozenset({0}), frozenset()),
    "click":       (frozenset({0}), frozenset({1})),
    "hover":       (frozenset({0}), frozenset({1})),
    "linkappend":  (frozenset({0}), frozenset({1})),   # «текст» «пассаж»
    "linkprepend": (frozenset({0}), frozenset({1})),
    "linkreplace": (frozenset({0}), frozenset({1})),
    "menu":        (frozenset({0}), frozenset()),
    "option":      (frozenset({0}), frozenset({1})),   # SC2: 2-й арг — пассаж
    "radio":       (frozenset({0}), frozenset({1, 2})),  # SC1: подписи — значения
    "checkbox":    (frozenset({0}), frozenset({1, 2})),
    "select":      (frozenset({0}), frozenset({1})),
    "textbox":     (frozenset({0}), frozenset({1, 2})),
    "textarea":    (frozenset({0}), frozenset({1, 2})),
    "input":       (frozenset({0}), frozenset({1, 2})),
    "prompt":      (frozenset({0}), frozenset({1, 2})),  # default — значение
}


def _macro_arg_positions(name: str
                         ) -> tuple[frozenset[int], frozenset[int]]:
    """(текстовые позиции, ключевые позиции) аргументов макроса."""
    return _PRINT_MACROS.get(name.lower(), (frozenset(), frozenset()))


# печатающие макросы, у которых ВСЕ строковые аргументы — видимый текст
# (ключей-имён пассажей у них нет): print печатает аргументы, dialog —
# заголовок и содержимое окна (модальное сообщение в игре). Перевод
# аргумента-ключа (имени пассажа/$переменной) ломает игру, поэтому
# только эти два — «всё текст».
_ALL_TEXT_MACROS = {"print", "dialog"}


def _macro_text_positions(name: str, macro_body: str,
                          n_args: int) -> frozenset[int]:
    """Позиции строковых аргументов макроса, которые переводятся.

    «=» (<<= expr>>) — печатающее выражение: строковые литералы — это
    текст для игрока, если выражение выбирает фразу (<<= either('…',
    '…')>> — случайный выбор реплики — частый паттерн в играх). Прочие
    <<= …>>-выражения (replace/split/match с литералами) не трогаем:
    их «аргументы» — код, перевод сломает логику.
    print/dialog — все строковые аргументы — видимый текст.
    """
    if name == "=":
        if "either(" in macro_body:
            return frozenset(range(n_args))
        return frozenset()
    if name.lower() in _ALL_TEXT_MACROS:
        return frozenset(range(n_args))
    return _macro_arg_positions(name)[0]


def _find_macro_end(line: str, start: int) -> int:
    """Индекс закрывающего >> макроса (вне строковых литералов "…" '…')."""
    i, n = start, len(line)
    quote: str | None = None
    while i < n:
        c = line[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif line.startswith(">>", i):
            return i
        i += 1
    return -1


# Harlowe: макрос — «(имя: …)» (имя всегда с двоеточием). Строка с
# (имя:) внутри — код игры: картинки (image:), переходы (goto:), условия
# (if:), присваивания (set:) и т.п. Перевод таких строк ломает игру
# («(изображение: …)» не макрос — картинка/ссылка умирает), поэтому они
# маскируются токенами как и SugarCube-код. Скобки в скобках (вложенные
# макросы (either: "a", (link: "b")) и кавычки )/«)» — экранируются.
_RE_HARLOWE_NAME = re.compile(r"\([A-Za-z][A-Za-z0-9-]*:")
# Harlowe-ссылки: [подпись->таргет], [таргет<-подпись] (одинарные скобки).
RE_HARLOWE_LINK = re.compile(
    r"\[([^\[\]\n]{1,1000}?(?:->|<-)[^\[\]\n]{1,1000})\]")


def _find_harlowe_end(line: str, start: int) -> int:
    """Индекс ) закрывающего Harlowe-макроса (вложенные скобки, кавычки)."""
    depth = 0
    i, n = start, len(line)
    quote: str | None = None
    while i < n:
        c = line[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _split_segments(line: str, harlowe: bool = False
                    ) -> list[tuple[str, str, int, int]]:
    """Разбивает строку пассажа на сегменты (тип, текст, start, end).

    Типы: text, link ([[...]]), img ([img[...]]), macro (<<...>>),
    tag (<...>), var ($var). Последний сегмент может быть обрезан
    (незакрытый макрос — продолжается на следующей строке).
    Для Harlowe (harlowe=True) к macro добавляются (имя: …) и
    [подпись->таргет] — это код игры (картинки, переходы, условия),
    перевод ломает игру, поэтому они не извлекаются вовсе.
    """
    segs: list[tuple[str, str, int, int]] = []
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c == "<" and line.startswith("<<", i):
            end = _find_macro_end(line, i + 2)
            if end < 0:
                segs.append(("macro", line[i:], i, n))
                break
            segs.append(("macro", line[i:end + 2], i, end + 2))
            i = end + 2
            continue
        if harlowe and c == "(" and i + 1 < n \
                and _RE_HARLOWE_NAME.match(line, i):
            end = _find_harlowe_end(line, i)
            if end < 0:
                segs.append(("macro", line[i:], i, n))
                break
            segs.append(("macro", line[i:end + 1], i, end + 1))
            i = end + 1
            continue
        if line.startswith("[img[", i):
            end = line.find("]]", i + 5)
            if end > 0:
                segs.append(("img", line[i:end + 2], i, end + 2))
                i = end + 2
                continue
        if c == "[" and line.startswith("[[", i):
            end = line.find("]]", i + 2)
            if end > 0:
                segs.append(("link", line[i:end + 2], i, end + 2))
                i = end + 2
                continue
            # незакрытая [[ (многострочная ссылка/сеттер) — код-структура
            segs.append(("macro", line[i:], i, n))
            break
        if harlowe and c == "[" and not line.startswith("[[", i):
            end = line.find("]", i + 1)
            if end > 0 and ("->" in line[i + 1:end]
                            or "<-" in line[i + 1:end]):
                segs.append(("macro", line[i:end + 1], i, end + 1))
                i = end + 1
                continue
        if c == "$" and i + 1 < n and _RE_VAR.match(line, i):
            m = _RE_VAR.match(line, i)
            segs.append(("var", m.group(0), i, m.end()))
            i = m.end()
            continue
        if c == "<" and not line.startswith("<<", i) \
                and i + 1 < n and re.match(r"[A-Za-z!/]", line[i + 1]):
            end = line.find(">", i + 1)
            if end > 0:
                segs.append(("tag", line[i:end + 1], i, end + 1))
                i = end + 1
                continue
        # текст: копим до следующего кода
        j = i + 1
        while j < n:
            nc = line[j]
            if (line.startswith("<<", j) or line.startswith("[[", j)
                    or line.startswith("[img[", j)
                    or (harlowe and line.startswith("(", j)
                        and j + 1 < n and _RE_HARLOWE_NAME.match(line, j))
                    or (harlowe and nc == "[" and not line.startswith("[[", j))
                    or (nc == "$" and j + 1 < n and _RE_VAR.match(line, j))
                    or (nc == "<" and not line.startswith("<<", j)
                        and j + 1 < n
                        and re.match(r"[A-Za-z!/]", line[j + 1]))):
                break
            j += 1
        segs.append(("text", line[i:j], i, j))
        i = j
    return segs


# строковые литералы внутри макроса: "…" / '…' (с экранированием)
_RE_STR_LIT = re.compile(r"(?P<q>['\"])(?P<v>(?:\\.|(?!(?P=q)).)*)(?P=q)",
                         re.S)


def _macro_args(macro: str) -> list[tuple[str, int, str]]:
    """Строковые литералы макроса <<name "arg1" "arg2">>: (текст, offset,
    кавычка)."""
    out: list[tuple[str, int, str]] = []
    for m in _RE_STR_LIT.finditer(macro):
        out.append((m.group("v"), m.start(), m.group("q")))
    return out


def _extract_segment(seg_type: str, seg_text: str,
                     codes: list[str], harlowe: bool = False
                     ) -> list[tuple[str, str, int]]:
    """Переводимые фрагменты сегмента: (текст, вид, индекс).

    Возвращает список (фрагмент, вид, idx):
    вид 'text' — текст сегмента (замаскированный, без отступов),
    idx = -1; вид 'link' — подпись ссылки, idx = -1; вид 'arg' —
    строка-аргумент печатающего макроса, idx — номер аргумента.
    Аргументы-КЛЮЧИ (имена пассажей, $переменные, значения) и
    аргументы, начинающиеся с $ (SugarCube 1: переменная первой),
    не извлекаются: перевод ключа ломает кнопку/ссылку/картинку.
    """
    out: list[tuple[str, str, int]] = []
    if seg_type == "text":
        stripped = seg_text.strip()
        if not stripped:
            return out
        # комментарий в коде (/* … */) — не текст для игрока
        if _is_code_comment(stripped):
            return out
        masked, _ = mask_codes(stripped, harlowe)
        if _has_translatable_text(masked):
            out.append((masked, "text", -1))
    elif seg_type == "link":
        inner = seg_text[2:-2]
        label, sep, target = _link_parts(inner)
        if sep and not RE_LINK_CODE.search(label) \
                and _has_letters(label):
            out.append((label, "link", -1))
    elif seg_type == "macro":
        name_m = re.match(r"<<\s*([A-Za-z_]+|\=)", seg_text)
        if name_m:
            args = _macro_args(seg_text)
            text_positions = _macro_text_positions(
                name_m.group(1), seg_text, len(args))
            if text_positions:
                for i, (arg, _off, _q) in enumerate(args):
                    # Ключ (имя пассажа/$var/значение) — не текст:
                    # перевод сломает переход, картинку или логику.
                    # Позиции $переменных в SugarCube 1 (переменная
                    # первой) ловятся проверкой на «$» в начале.
                    if i not in text_positions:
                        continue
                    # аргумент со вложенными макросами (например подпись
                    # кнопки с <<if>>-условием) — код: LLM переведёт условие
                    # и сломает логику; apply их всё равно не внедрит
                    if _has_letters(arg) \
                            and not RE_MACRO_ANY.search(arg) \
                            and not RE_LINK_CODE.search(arg):
                        out.append((arg, "arg", i))
    return out


def _mask_link_plain(inner: str) -> str:
    """Замаскированная ссылка для записи в строку: подпись — текст
    (в apply переведётся), таргет — токен."""
    label, sep, target = _link_parts(inner)
    codes: list[str] = []
    if not sep or RE_LINK_CODE.search(label):
        return "<x0/>"
    codes.append(target)
    if sep == "<-":
        return f"[[<x0/>{sep}{label}]]"
    return f"[[{label}{sep}<x0/>]]"


def is_translatable_line(line: str) -> bool:
    """Строка пассажа — «живой» текст, а не макрос/ссылка/тег."""
    s = line.strip()
    if not s:
        return False
    if RE_MACRO_SUGARCUBE.match(line) or RE_MACRO_HARLOWE.match(line):
        return False
    if RE_COMMENT.match(line):
        return False
    if RE_PURE_TAG.match(line):
        return False
    if re.search(r"<script\b|</script", line, re.I):
        return False
    if _dangerous_macro(line):
        return False
    # SugarCube-картинка [img[путь]] — кодовая конструкция: LLM
    # «переводит» пути внутри "..." и ломает изображения
    if "[img[" in line.lower():
        return False
    # висячая [[ без закрывающей ]] на строке — многострочная ссылка
    # ([[подпись|таргет][сеттер] разбитый на строки): переводить
    # нельзя, таргет не влезет в токен и переводчик испортит имя
    # пассажа. Полные ссылки [[...]] маскируются ниже (см. mask_codes).
    if "[[" in line and "[[" in RE_LINK.sub("", line):
        return False
    # line continuation '\' склеивает строки — перевод ломает структуру
    if _RE_LINE_CONT.search(line):
        return False
    # после маскирования кодов (макросы, $var, теги, ссылки) в строке
    # должны остаться буквы — иначе это чистый код, переводить нечего
    masked, _ = mask_codes(s)
    return _has_translatable_text(masked)


def mask_codes(text: str, harlowe: bool = False) -> tuple[str, list[str]]:
    """Заменяет Twine-коды (<<..>>, $var, HTML-теги, таргеты ссылок
    [[..]]; для Harlowe — (имя: …) и [подпись->таргет]) на <xN/>.

    Подпись ссылки [[подпись|таргет]] остаётся текстом — её переводит
    LLM, а таргет (имя пассажа) замаскирован. Ссылки без разделителя
    ([[таргет]]) и с кодом в подписи уходят в токен целиком.

    Harlowe-конструкции (картинки (image:), переходы (goto:), ссылки
    [a->b]) маскируются ЦЕЛИКОМ: их перевод ломает игру, а маскирование
    защищает и legacy-путь в apply (строки старых проектов без
    сегментов), где маска пересчитывается по текущему файлу.

    Возвращает (замаскированный текст, список кодов) — порядок
    и число кодов детерминированы: одинаковый вход → одинаковые
    токены, поэтому маску можно пересчитывать в apply.
    """
    codes: list[str] = []

    def repl(m: re.Match) -> str:
        codes.append(m.group(0))
        return f"<x{len(codes) - 1}/>"

    # Harlowe-макросы (name: …): сканер со скобками/кавычками, до общего
    # прохода — иначе $var внутри (set: $x to …) маскировался бы отдельно
    # и переводчик увидел бы код. Токены пишутся в codes сразу (первые).
    if harlowe:
        harlowe_map: list[tuple[str, str]] = []
        i = 0
        while i < len(text):
            m = _RE_HARLOWE_NAME.search(text, i)
            if not m:
                break
            end = _find_harlowe_end(text, m.start())
            if end < 0:
                break
            idx = len(codes)
            codes.append(text[m.start():end + 1])
            sentinel = f"\x00H{len(harlowe_map)}\x00"
            harlowe_map.append((sentinel, f"<x{idx}/>"))
            text = text[:m.start()] + sentinel + text[end + 1:]
            i = m.start() + len(sentinel)
        # Harlowe-ссылки [подпись->таргет] — код целиком.
        temp = RE_HARLOWE_LINK.sub(repl, text)
        for sentinel, tok in harlowe_map:
            temp = temp.replace(sentinel, tok)
        text = temp

    # ссылки заменяем sentinel'ами до общего прохода: токены <xN/> внутри
    # ссылок не должны быть повторно замаскированы как HTML-теги, а коды
    # в подписи/таргете ссылки не должны «утечь» в общий список.
    link_map: list[tuple[str, str]] = []

    def link_repl(m: re.Match) -> str:
        masked_link = _mask_link(m.group(1), codes)
        sentinel = f"\x00L{len(link_map)}\x00"
        link_map.append((sentinel, masked_link))
        return sentinel

    temp = RE_LINK.sub(link_repl, text)
    masked = RE_TWINE_CODE.sub(repl, temp)
    for sentinel, masked_link in link_map:
        masked = masked.replace(sentinel, masked_link)
    return masked, codes


def unmask_codes(text: str, codes: list[str]) -> str:
    """Восстанавливает коды на места токенов <xN/>."""
    def repl(m: re.Match) -> str:
        i = int(m.group(1))
        return codes[i] if i < len(codes) else m.group(0)

    return _TOKEN_RE.sub(repl, text)


def codes_intact(text: str, n: int) -> bool:
    """True, если в text все токены <x0/>..<x{n-1}/> на месте по порядку."""
    found = sorted(int(m.group(1)) for m in _TOKEN_RE.finditer(text))
    return found == list(range(n))


def extract(game_dir: str) -> list[TranslationEntry]:
    """Извлекает переводимые строки из пассажей истории."""
    story = find_story(game_dir)
    if not story:
        return []
    rel = os.path.basename(story)
    with open(story, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    # Harlowe: (имя: …) и [подпись->таргет] — код игры, в сегменты macro
    harlowe = _story_format(text).lower().startswith("harlowe")
    entries: list[TranslationEntry] = []
    next_id = 1
    for m in RE_PASSAGE.finditer(text):
        attrs = _attrs(m.group(1))
        pid = attrs.get("pid", "?")
        name = html_mod.unescape(attrs.get("name", ""))
        # Пассажи-виджеты и служебные пассажи (StoryInit и т.п.) — код:
        # JS-массивы, макросы, стили. Перевод их содержимого ломает игру
        # («Cannot read properties of undefined», «bad evaluation»).
        if _is_service_passage(attrs):
            continue
        # Состояние (незакрытый макрос / <script>) живёт внутри ОДНОГО
        # пассажа: в Twine-экспорте пассажи самодостаточны, строка
        # первого пассажа не может продолжать макрос второго.
        in_script = False
        mac_open = False
        link_open = False
        for n, line in enumerate(m.group(2).split("\n")):
            u = html_mod.unescape(line)
            low = u.lower()
            # JS-код внутри <script>...</script>: строки похожи на
            # текст, LLM их «переводит» и ломает логику игры
            if "<script" in low:
                in_script = "</script" not in low  # inline-блок — без флага
                continue
            if in_script:
                if "</script" in low:
                    in_script = False
                continue
            # многострочная ссылка/сеттер ([[…]…] разбитый на строки):
            # строки-«продолжения» (например 'to true] ]') — код-структура,
            # их перевод ломает ссылку. Скипаем до строки, закрывающей ]
            if link_open:
                link_open = not (u.rstrip().endswith("]")
                                 or u.rstrip().endswith("]]"))
                continue
            # многострочный макрос (<<set $x = { ... }>> разбитый на
            # строки): строки-«продолжения» — код, не текст. Пока
            # макрос открыт (mac_open) — каждая строка — код, пока
            # она не закроет макрос: у строк-продолжений счётчики
            # равны (0<< 0>>), закрывает макрос строка с лишними >>.
            if mac_open:
                mac_open = u.count("<<") >= u.count(">>")
                continue
            if u.count("<<") != u.count(">>"):
                mac_open = u.count("<<") > u.count(">>")
                continue
            # висячая [[ без закрывающей ]] на строке — многострочная
            # ссылка/сеттер (код-структура): не извлекаем саму строку
            # и включаем режим пропуска строк-продолжений
            if "[[" in u:
                rest = RE_LINK.sub("", u)
                rest = re.sub(r"\[\[[^\]\n]{0,1000}\]\[[^\]\n]{0,1000}\]\]",
                              "", rest)
                if "[[" in rest:
                    link_open = True
                    continue
            # line continuation '\' склеивает строки — перевод ломает
            # структуру: такие строки не извлекаем вовсе
            if _RE_LINE_CONT.search(u):
                continue
            # В Twine-экспорте макросы экранированы (&lt;&lt;if…&gt;&gt;) —
            # после unescape разбиваем строку на сегменты и берём
            # только текстовые (текст, подписи ссылок, аргументы
            # кнопок/ссылок); код-сегменты не извлекаем вовсе.
            for k, (stype, stext, _s0, _s1) in enumerate(
                    _split_segments(u, harlowe)):
                for frag, kind, arg_idx in _extract_segment(
                        stype, stext, None, harlowe):
                    path = f"passage[{pid}].line[{n}].seg[{k}]"
                    if kind == "arg":
                        path += f".arg[{arg_idx}]"
                    entries.append(TranslationEntry(
                        id=next_id, file=rel,
                        json_path=path,
                        context=f"{name} (pid {pid})",
                        original=frag))
                    next_id += 1
    return entries


def _load_backup_lines(game_dir: str, story_name: str
                       ) -> tuple[dict[tuple[str, int], str],
                                  dict[str, str]]:
    """Строки и служебные пассажи из существующих бэкапов (backup/*/).

    Нужны для ремонта: если прошлый перевод сломал макрос в строке
    (залез внутрь <<...>>) или повредил код служебного пассажа
    (переведённые строки массива в widget/StoryInit), восстанавливаем
    из оригинального файла до перевода.

    Возвращает (строки, пассажи): строки берём только из бэкапов,
    где макросы не содержат кириллицы (не переведённые); служебные
    пассажи — целиком, из бэкапа без кириллицы в содержимом.
    """
    root = _backup_dir(game_dir)
    lines_out: dict[tuple[str, int], str] = {}
    passages_out: dict[str, str] = {}
    if not os.path.isdir(root):
        return lines_out, passages_out
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return lines_out, passages_out
    # Приоритет: плоский backup/<story> — это оригинал до первого
    # перевода; таймстамп-папки backup/<ts>/<story> — старые итерации
    # (могут содержать переводы). Первый найденный бэкап побеждает
    # (first-wins), поэтому плоский обрабатываем раньше папок.
    def _scan(path: str) -> None:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            return
        for m in RE_PASSAGE.finditer(text):
            attrs = _attrs(m.group(1))
            pid = attrs.get("pid")
            if pid is None:
                continue
            body = m.group(2)
            if _is_service_passage(attrs):
                if pid not in passages_out \
                        and not RE_CYR.search(html_mod.unescape(body)):
                    passages_out[pid] = body
                continue
            for n, line in enumerate(body.split("\n")):
                key = (pid, n)
                if key in lines_out:
                    continue
                if any(RE_CYR.search(c) for c in
                       RE_MACRO_ANY.findall(html_mod.unescape(line))):
                    continue  # макросы переведены — не оригинал
                lines_out[key] = line
    flat = os.path.join(root, story_name)
    if os.path.isfile(flat):
        _scan(flat)
    for d in entries:
        path = os.path.join(root, d)
        if not os.path.isdir(path):
            continue
        _scan(os.path.join(path, story_name))
    return lines_out, passages_out


def _apply_seg(stype: str, stext: str, arg_idx: int,
               original: str, translation: str,
               harlowe: bool = False) -> str | None:
    """Перевод одного сегмента строки (или None — сегмент изменился /
    тип не тот / перевод опасен). Вид определяется по типу сегмента:
    text — текст, link — подпись ссылки, macro+arg_idx — аргумент
    печатающего макроса."""
    if RE_MACRO_ANY.search(translation):
        return None  # переводчик добавил макрос — не внедряем
    if stype == "text":
        stripped = stext.strip()
        if not stripped:
            return None
        masked, codes = mask_codes(stripped, harlowe)
        if masked != original:
            return None
        text = unmask_codes(translation, codes)
        if mask_codes(text, harlowe)[1] != codes:
            return None
        ls = len(stext) - len(stext.lstrip())
        rs = len(stext) - len(stext.rstrip())
        core = stext[ls:] if not rs else stext[ls:-rs]
        if core != stripped:
            return None
        return stext[:ls] + text + ("" if not rs else stext[-rs:])
    if stype == "link":
        inner = stext[2:-2]
        label, sep, target = _link_parts(inner)
        if not sep or RE_LINK_CODE.search(label) or label != original:
            return None
        # Кавычки/скобки/код в подписи — сломают синтаксис ссылки;
        # разделители | -> <- в переводе переставят подпись/таргет
        # ([[a->b|c]] разберётся как подпись a, таргет b|c) — не внедряем
        if RE_LINK_CODE.search(translation) \
                or "|" in translation or "->" in translation \
                or "<-" in translation:
            return None
        if sep == "<-":
            return f"[[{target}{sep}{translation}]]"
        return f"[[{translation}{sep}{target}]]"
    if stype == "macro":
        return _apply_macro_arg(stext, arg_idx, original, translation)
    return None


def _apply_macro_arg(stext: str, arg_idx: int, original: str,
                     translation: str) -> str | None:
    """Перевод одного строкового аргумента макроса; возвращает макрос
    целиком или None, если аргумент — ключ/код или перевод опасен."""
    name_m = re.match(r"<<\s*([A-Za-z_]+|\=)", stext)
    if arg_idx < 0 or not name_m:
        return None
    args = _macro_args(stext)
    text_positions = _macro_text_positions(
        name_m.group(1), stext, len(args))
    # Аргумент-КЛЮЧ (имя пассажа, $переменная, значение) — перевод
    # сломает игру. Запись может прийти из старого проекта, где
    # ключи ещё извлекались — не внедряем ни при каких условиях.
    if arg_idx not in text_positions:
        return None
    if arg_idx >= len(args):
        return None
    arg, off, q = args[arg_idx]
    if arg != original:
        return None
    # Кавычка в переводе закроет строковый литерал макроса раньше
    # времени (сломанный JS); $/<[/<< — переводчик изобрёл код.
    if q in translation or RE_LINK_CODE.search(translation):
        return None
    # off — позиция ОТКРЫВАЮЩЕЙ кавычки; закрывающая идёт сразу
    # после аргумента — её не трогаем, подставляем свою пару.
    return stext[:off] + q + translation + q \
        + stext[off + len(q) + len(arg) + len(q):]


def _apply_macro_args(stext: str,
                      ws: list[tuple[int, str, str]]) -> str | None:
    """Применяет переводы НЕСКОЛЬКИХ строковых аргументов одного макроса
    (например <<= either('…', '…', …)>>). Сплайс с конца, чтобы смещения
    остальных аргументов не сдвигались. None — ни один не применился."""
    repls: list[tuple[int, str, str, str]] = []
    for arg_idx, original, translation in ws:
        r = _apply_macro_arg(stext, arg_idx, original, translation)
        if r is None:
            continue
        arg, off, q = _macro_args(stext)[arg_idx]
        repls.append((off, q, arg, translation))
    if not repls:
        return None
    out = stext
    for off, q, arg, translation in sorted(repls, key=lambda x: x[0],
                                           reverse=True):
        out = out[:off] + q + translation + q \
            + out[off + len(q) + len(arg) + len(q):]
    return out


def apply(game_dir: str, entries: list[TranslationEntry],
          backup_root: str | None = None, on_skip=None,
          target_lang: str | None = None) -> dict:
    """Внедряет переводы построчно обратно в .html истории.

    По умолчанию — в сам файл (с бэкапом в backup/). Если задан
    target_lang — перевод пишется в НОВЫЙ файл «имя_<язык>.html»
    рядом с игрой: оригинал не трогается и остаётся бэкапом.
    """
    story = find_story(game_dir)
    if not story:
        return {"files": 0, "strings": 0, "backups": []}
    backup_lines, backup_passages = _load_backup_lines(
        game_dir, os.path.basename(story))
    by_pid: dict[str, dict[int, tuple[str, str]]] = {}
    seg_by_pid: dict[str, dict[int, list[tuple[int, int, str, str]]]] = {}
    _SEG_RE = re.compile(
        r"passage\[(\d+)\]\.line\[(\d+)\](?:\.seg\[(\d+)\](?:\.arg\[(\d+)\])?)?")
    for e in entries:
        if not e.translation.strip() or e.status == "skip":
            continue
        m = _SEG_RE.match(e.json_path)
        if not m:
            continue
        pid, ln = m.group(1), int(m.group(2))
        if m.group(3) is None:
            by_pid.setdefault(pid, {})[ln] = (e.original, e.translation)
        else:
            seg_by_pid.setdefault(pid, {}).setdefault(ln, []).append(
                (int(m.group(3)), int(m.group(4) or -1),
                 e.original, e.translation))

    with open(story, encoding="utf-8", errors="ignore") as f:
        text = f.read()

    # Harlowe: (имя: …) и [подпись->таргет] — код игры; маскирование и
    # ремонт работают по тому же правилу, что и в extract.
    harlowe = _story_format(text).lower().startswith("harlowe")

    if backup_root is None:
        backup_root = _backup_dir(game_dir)
    backup_path: str | None = None
    if not target_lang:
        # Одноразовый бэкап до первого перевода: нужен только при
        # правке самого файла. Для новой копии («имя_язык.html»)
        # оригинал и есть бэкап — ничего не копируем.
        os.makedirs(backup_root, exist_ok=True)
        backup_path = os.path.join(backup_root, os.path.basename(story))
        if not os.path.exists(backup_path):
            shutil.copy2(story, backup_path)

    written = 0

    def replace_passage(m: re.Match) -> str:
        nonlocal written
        attrs = _attrs(m.group(1))
        pid = attrs.get("pid")
        # Ремонт служебных пассажей (widget, StoryInit и т.п.): прошлый
        # перевод повредил код — переведённые строки массивов, кавычки-
        # «ёлочки» в JS и т.п. Весь пассаж возвращается из оригинала.
        if _is_service_passage(attrs):
            saved = backup_passages.get(pid)
            if saved is not None and saved != m.group(2):
                written += 1
                return f"<tw-passagedata{m.group(1)}>" + saved + \
                    "</tw-passagedata>"
            return m.group(0)
        lines = m.group(2).split("\n")
        # Строки внутри <script>...</script> — JS-код: даже если запись
        # из старого проекта на них ссылается, не трогаем (строки похожи
        # на текст, перевод ломает логику игры).
        script_flags: set[int] = set()
        in_script = False
        for n, line in enumerate(lines):
            low = line.lower()
            if "<script" in low:
                in_script = "</script" not in low
                script_flags.add(n)
            elif in_script:
                script_flags.add(n)
                if "</script" in low:
                    in_script = False
        # Глобальный ремонт: прошлый перевод залез внутрь макросов
        # (кириллица в строке-макросе — «bad evaluation», сломанные
        # кавычки). Строки-макросы целиком (<<if>>...<<else>>...<<</if>>)
        # восстанавливаются из оригинального backup/-файла — даже если
        # записи в проекте для них уже нет.
        for idx, line in enumerate(lines):
            u = html_mod.unescape(line)
            if RE_MACRO_SUGARCUBE.match(u) and RE_CYR.search(u):
                saved = backup_lines.get((pid, idx))
                if saved is not None:
                    lines[idx] = saved
                    written += 1
                continue
            # Harlowe: кириллица ВНУТРИ (имя: …) — прошлый перевод сломал
            # код (переведённый путь картинки, имя пассажа, условие) —
            # восстанавливаем строку из backup/. Кириллица вне макроса
            # (хук [Текст]) — легальный перевод, не трогаем.
            hl_damaged = False
            if harlowe:
                for hm in _RE_HARLOWE_NAME.finditer(u):
                    hend = _find_harlowe_end(u, hm.start())
                    if hend > hm.start() \
                            and RE_CYR.search(u[hm.start():hend + 1]):
                        hl_damaged = True
                        break
            if hl_damaged:
                saved = backup_lines.get((pid, idx))
                if saved is not None and saved != lines[idx]:
                    lines[idx] = saved
                    written += 1
                continue
            # Ремонт ссылок: прошлый перевод залез внутрь [[...]] —
            # переведены имена пассажей (|Start→«Начало») или сломана
            # структура (висячая [[, удалены цели |Interact) — такие
            # ссылки ведут в никуда. Восстанавливаем оригинал из
            # backup/, если он без кириллицы (не переведён).
            # Кириллица ТОЛЬКО в подписи ([[Открыть дверь->Door]]) —
            # легальный перевод, не трогаем.
            if "[[" in u and RE_CYR.search(u):
                repair = False
                if "[[" in RE_LINK.sub("", u):
                    repair = True  # висячая [[ — незакрытая/сломанная
                else:
                    for lm in RE_LINK.finditer(u):
                        _, sep, target = _link_parts(lm.group(1))
                        if not sep or RE_CYR.search(target):
                            repair = True
                            break
                if repair:
                    saved = backup_lines.get((pid, idx))
                    if saved is not None \
                            and not RE_CYR.search(html_mod.unescape(saved)):
                        lines[idx] = saved
                        written += 1
        lines_map = by_pid.get(pid)
        seg_map = seg_by_pid.get(pid)
        if not lines_map and not seg_map:
            return f"<tw-passagedata{m.group(1)}>" + "\n".join(lines) + \
                "</tw-passagedata>"
        if lines_map:
            for idx, (orig, translation) in lines_map.items():
                if 0 <= idx < len(lines):
                    lead = lines[idx][:len(lines[idx])
                                         - len(lines[idx].lstrip())]
                    cur = lines[idx]
                    cur_unesc = html_mod.unescape(cur)
                    # Ремонт из бэкапа: прошлый перевод залез внутрь
                    # макроса (кириллица в <<...>> — «bad evaluation»,
                    # сломанные кавычки). Восстанавливаем оригинальную
                    # строку из backup/, чтобы игра снова работала.
                    if any(RE_CYR.search(c) for c in
                           RE_MACRO_ANY.findall(cur_unesc)):
                        saved = backup_lines.get((pid, idx))
                        if saved is not None:
                            lines[idx] = saved
                            written += 1
                            continue
                    # Строки, содержащие выполняющий код (<<set>>,
                    # <<run>>, вызовы виджетов и т.п.), JS-код внутри
                    # <script>, комментарии кода (/* … */) или
                    # многострочные макросы, не трогаем ни при каких
                    # условиях — даже перевод из старого проекта не
                    # внедряем, чтобы не сломать игру. Ссылки [[...]] —
                    # НЕ в списке: подпись переводится, таргет
                    # замаскирован токеном (см. mask_codes).
                    if _dangerous_macro(cur_unesc) \
                            or re.search(r"<script\b|</script", cur_unesc,
                                         re.I) \
                            or _is_code_comment(cur_unesc) \
                            or _in_macro(cur_unesc) \
                            or "[img[" in cur_unesc.lower() \
                            or _RE_LINE_CONT.search(cur_unesc) \
                            or idx in script_flags:
                        continue
                    # Ремонт старых проектов: строка была извлечена с
                    # выполняющим кодом, а в файле код уже пропал — такой
                    # файл сломан прошлым переводом («Unexpected
                    # identifier», «cannot find a closing tag»).
                    # Возвращаем оригинал. Если строка цела — не трогаем.
                    if _dangerous_macro(orig) \
                            or re.search(r"<script\b|</script", orig, re.I) \
                            or _is_code_comment(orig) \
                            or _in_macro(orig) \
                            or "[img[" in orig.lower() \
                            or _RE_LINE_CONT.search(orig):
                        if RE_MACRO_ANY.search(cur_unesc) \
                                or not RE_MACRO_ANY.search(orig) \
                                or idx in script_flags:
                            continue
                        lines[idx] = lead + html_mod.escape(
                            orig, quote=False)
                        written += 1
                        continue
                    # Новые извлечения хранят оригинал с токенами <xN/>:
                    # пересчитываем маску по текущей строке и
                    # восстанавливаем коды в переводе. Если переводчик
                    # потерял токен — строку не трогаем, чтобы не
                    # сломать игру.
                    _, codes = mask_codes(cur_unesc, harlowe)
                    if codes and _TOKEN_RE.search(orig) \
                            and not codes_intact(translation, len(codes)):
                        continue
                    text = unmask_codes(translation, codes)
                    # Если переводчик изменил макрос/ссылку — перевёл
                    # текст внутри <<= either(...)>> и сломал кавычки
                    # либо добавил свой макрос — в переводе появится
                    # макрос, которого нет в исходной строке. Такой
                    # перевод не внедряем.
                    cur_macros = set(RE_MACRO_ANY.findall(cur_unesc))
                    tr_macros = set(RE_MACRO_ANY.findall(text))
                    if tr_macros - cur_macros:
                        continue
                    # Строгая проверка: после восстановления кодов из
                    # токенов список всех кодов (макросы, теги, $var,
                    # ссылки) должен в точности совпасть с кодами
                    # исходной строки — иначе переводчик что-то
                    # добавил/сломал (путь к картинке, тег, переменную)
                    # — не внедряем, игра останется рабочей.
                    if mask_codes(text, harlowe)[1] != codes:
                        continue
                    lines[idx] = lead + html_mod.escape(text, quote=False)
                    written += 1
        # Сегментные записи (новый формат извлечения): строка разбита
        # на сегменты, переводы вставляются в текстовые сегменты /
        # подписи ссылок / аргументы кнопок; код-сегменты не трогаем.
        if seg_map:
            for idx, segs in seg_map.items():
                if not (0 <= idx < len(lines)):
                    continue
                cur_unesc = html_mod.unescape(lines[idx])
                if re.search(r"<script\b|</script", cur_unesc, re.I) \
                        or _is_code_comment(cur_unesc) \
                        or _RE_LINE_CONT.search(cur_unesc) \
                        or idx in script_flags:
                    continue
                # Ремонт из бэкапа: прошлый перевод залез внутрь макроса
                # (кириллица в <<...>> — «bad evaluation») — возвращаем
                # оригинальную строку, чтобы игра снова работала.
                if any(RE_CYR.search(c) for c in
                       RE_MACRO_ANY.findall(cur_unesc)):
                    saved = backup_lines.get((pid, idx))
                    if saved is not None:
                        lines[idx] = saved
                        written += 1
                    continue
                seg_list = _split_segments(cur_unesc, harlowe)
                want: dict[int, list[tuple[int, str, str]]] = {}
                for k, arg_idx, orig, trans in segs:
                    want.setdefault(k, []).append((arg_idx, orig, trans))
                parts: list[str] = []
                any_changed = False
                for k, (stype, stext, s0, s1) in enumerate(seg_list):
                    ws = want.get(k)
                    if not ws:
                        parts.append(cur_unesc[s0:s1])
                        continue
                    if stype == "macro" and len(ws) > 1:
                        repl = _apply_macro_args(stext, ws)
                        if repl is None:
                            parts.append(cur_unesc[s0:s1])
                            continue
                        parts.append(repl)
                        any_changed = True
                        continue
                    arg_idx, orig, trans = ws[0]
                    repl = _apply_seg(stype, stext, arg_idx, orig, trans,
                                      harlowe)
                    if repl is None:
                        parts.append(cur_unesc[s0:s1])
                        continue
                    parts.append(repl)
                    any_changed = True
                if any_changed:
                    lines[idx] = html_mod.escape("".join(parts), quote=False)
                    written += 1
        return f"<tw-passagedata{m.group(1)}>" + "\n".join(lines) + \
            "</tw-passagedata>"

    new_text = RE_PASSAGE.sub(replace_passage, text)
    if target_lang:
        base = os.path.splitext(story)[0]
        out_path = f"{base}_{target_lang}.html"
        if not written:
            return {"files": 0, "strings": 0, "backups": [],
                    "out_file": out_path,
                    "out_dir": os.path.dirname(out_path)}
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(new_text)
        return {"files": 1, "strings": written, "backups": [],
                "out_file": out_path,
                "out_dir": os.path.dirname(out_path)}
    with open(story, "w", encoding="utf-8") as f:
        f.write(new_text)
    return {"files": 1 if written else 0, "strings": written,
            "backups": [backup_path] if backup_path else []}


def restore_original(game_dir: str) -> dict:
    """Восстанавливает оригинальный .html из backup/ (одноразовый бэкап
    до первого перевода). Возвращает статистику."""
    story = find_story(game_dir)
    if not story:
        return {"restored": 0}
    name = os.path.basename(story)
    candidates: list[str] = []
    root = _backup_dir(game_dir)
    if os.path.isdir(root):
        try:
            entries = sorted(os.listdir(root))
        except OSError:
            entries = []
        for d in entries:
            p = os.path.join(root, d)
            if os.path.isdir(p):
                p = os.path.join(p, name)  # старый формат backup/<ts>/
            elif d != name:
                continue
            if os.path.isfile(p):
                candidates.append(p)
    # Старые таймстамп-папки сортируются хронологически: первая
    # копия = оригинал до переводов.
    for src in candidates:
        try:
            shutil.copy2(src, story)
            return {"restored": 1}
        except OSError:
            continue
    return {"restored": 0}


# ── человекочитаемый текст игры (для просмотра в приложении) ──
# Пассажи по порядку, код игры свёрнут в маркеры ⟦…⟧: видно только то,
# что реально читает игрок. Нужно, чтобы посмотреть на текст игры
# «как он выглядит для человека» и настроить перевод до внедрения.
@dataclass
class Passage:
    pid: str
    name: str
    tags: str
    text: str          # человекочитаемый текст пассажа (код свёрнут)


_MACRO_NAME_RE = re.compile(r"<<\s*([A-Za-z_]+)")


def _collapse_line(line: str, harlowe: bool) -> str:
    """Сворачивает код одной строки в маркеры ⟦…⟧, оставляя читаемый текст."""
    u = html_mod.unescape(line)
    # Harlowe-макрос (имя: …) — код целиком (картинка/переход/условие)
    if harlowe:
        m = _RE_HARLOWE_NAME.search(u)
        if m:
            end = _find_harlowe_end(u, m.start())
            if end > m.start():
                name = m.group(0)[1:-1].split(":", 1)[0].strip()
                u = u[:m.start()] + f"⟦макрос: {name}⟧" + u[end + 1:]
    # SugarCube-макросы <<...>> (включая оставшиеся многострочные)
    def macro_repl(m: re.Match) -> str:
        nm = _MACRO_NAME_RE.match(m.group(0))
        return f"⟦макрос: {nm.group(1)}⟧" if nm else "⟦макрос⟧"
    u = re.sub(r"<<.*?>>", macro_repl, u, flags=re.S)
    # картинки [img[...]] — код (путь/селектор), не текст
    u = re.sub(r"\[img\[.*?\]\]", "⟦картинка⟧", u, flags=re.S)
    # ссылки с сеттером [[label|target][$var to ...]] — сеттер это код
    def setter_repl(m: re.Match) -> str:
        label, sep, _t = _link_parts(m.group(1))
        return f"⟦ссылка: {label.strip()}⟧" if sep else "⟦ссылка⟧"
    u = re.sub(r"\[\[([^\]\n]{1,1000})\]\[[^\]\n]*\]\]", setter_repl, u)
    # ссылки [[...]]: подпись видна, таргет/сеттер скрыты
    def link_repl(m: re.Match) -> str:
        label, sep, _t = _link_parts(m.group(1))
        if sep:
            return f"⟦ссылка: {label.strip()}⟧"
        return "⟦ссылка⟧"
    u = re.sub(r"\[\[([^\]\n]{1,1000})\]\]", link_repl, u)
    # переменные $var — имя видно (это то, что подставит игра)
    u = _RE_VAR.sub(lambda m: f"⟦{m.group(0)}⟧", u)
    # HTML-теги убираем — в игре их не видно
    u = re.sub(r"<[^>]+>", "", u)
    return u.strip()


def _clean_passage_body(body: str, harlowe: bool) -> str:
    """Человекочитаемый текст пассажа: скрипты и многострочные макросы
    сворачиваются в маркеры, остальной код — в ⟦…⟧; строки-код целиком
    пропускаются. Текст, который читает игрок, остаётся как есть."""
    out: list[str] = []
    in_script = False
    script_lines = 0
    macro_open = False
    link_open = False
    for line in body.split("\n"):
        low = line.lower()
        if "<script" in low:
            in_script = "</script" not in low
            continue
        if in_script:
            script_lines += 1
            if "</script" in low:
                in_script = False
            continue
        u = html_mod.unescape(line)
        if link_open:
            link_open = not (u.rstrip().endswith("]")
                             or u.rstrip().endswith("]]"))
            continue
        if u.count("<<") != u.count(">>"):
            was_open = macro_open
            macro_open = u.count("<<") > u.count(">>")
            if not was_open:
                out.append("⟦макрос⟧")
            continue
        if macro_open:
            continue
        if _RE_LINE_CONT.search(u):
            out.append("⟦продолжение строки⟧")
            continue
        # висячая [[ (многострочная ссылка/сеттер) — код-структура.
        # Однострочные ссылки [[...]] и [[...][...]] сначала убираются —
        # иначе они ошибочно считаются висячими.
        if "[[" in u:
            rest = RE_LINK.sub("", u)
            rest = re.sub(r"\[\[[^\]\n]{0,1000}\]\[[^\]\n]{0,1000}\]\]",
                          "", rest)
            if "[[" in rest:
                out.append("⟦ссылка⟧")
                link_open = True
                continue
        # строки-код целиком (макрос/тег/комментарий) — маркер
        if RE_MACRO_SUGARCUBE.match(u) or RE_MACRO_HARLOWE.match(u) \
                or RE_COMMENT.match(u) or RE_PURE_TAG.match(u) \
                or _is_code_comment(u):
            nm = _MACRO_NAME_RE.match(u)
            out.append(f"⟦макрос: {nm.group(1)}⟧" if nm else "⟦код⟧")
            continue
        cleaned = _collapse_line(line, harlowe)
        if cleaned:
            out.append(cleaned)
    text = "\n".join(out)
    if script_lines:
        text += f"\n⟦скрипт: {script_lines} строк кода пропущено⟧"
    return text


def read_passages(game_dir: str) -> list[Passage]:
    """Пассажи игры по порядку с человекочитаемым текстом (код свёрнут).
    Служебные пассажи (StoryInit, widget, script и т.п.) пропускаются."""
    story = find_story(game_dir)
    if not story:
        return []
    with open(story, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    harlowe = _story_format(text).lower().startswith("harlowe")
    passages: list[Passage] = []
    for m in RE_PASSAGE.finditer(text):
        attrs = _attrs(m.group(1))
        if _is_service_passage(attrs):
            continue
        passages.append(Passage(
            pid=attrs.get("pid", "?"),
            name=html_mod.unescape(attrs.get("name", "")),
            tags=attrs.get("tags", ""),
            text=_clean_passage_body(m.group(2), harlowe)))
    return passages


def format_passages(passages: list[Passage]) -> str:
    """Человекочитаемый вид текста игры: пассажи по порядку с заголовками,
    код свёрнут в маркеры ⟦…⟧ — видно, что именно читает игрок."""
    lines: list[str] = []
    for i, p in enumerate(passages):
        if i:
            lines.append("")
        head = f"ПАССАЖ «{p.name}» (pid {p.pid})"
        if p.tags:
            head += f"  [теги: {p.tags}]"
        lines.append(head)
        lines.append("─" * len(head))
        lines.append(p.text or "(нет текста)")
    return "\n".join(lines)


# ── JSON-промежуток ──
# Конвертация html игры в структурированный JSON: пассажи по порядку,
# каждый разбит на сегменты (text/link/macro/img/var/tag). У сегмента —
# raw (код игры как есть) и translatable — список фрагментов, которые
# реально видит игрок и которые можно переводить (текст, подписи
# ссылок, аргументы кнопок/ссылок). Ссылки, картинки, макросы,
# переменные и теги в translatable не попадают — перевод их ломает
# игру. JSON удобно читать/править/передавать переводчику отдельно,
# не трогая html.


def story_to_json(game_dir: str) -> dict:
    """Структурированная модель игры: метаданные + пассажи с сегментами.

    Служебные пассажи (StoryInit, widget, script и т.п.) пропускаются —
    их содержимое — код игры, а не текст для игрока.
    """
    story = find_story(game_dir)
    if not story:
        return {"game": "", "format": "", "name": "", "startnode": "",
                "passages": []}
    with open(story, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    harlowe = _story_format(text).lower().startswith("harlowe")
    m = re.search(r"<tw-storydata\b[^>]*>", text, re.DOTALL)
    attrs = _attrs(m.group(0)[len("<tw-storydata"):-1]) if m else {}
    doc: dict = {
        "game": os.path.basename(story),
        "format": attrs.get("format", ""),
        "name": html_mod.unescape(attrs.get("name", "")),
        "startnode": attrs.get("startnode", ""),
        "passages": [],
    }
    for pm in RE_PASSAGE.finditer(text):
        a = _attrs(pm.group(1))
        if _is_service_passage(a):
            continue
        segments: list[dict] = []
        for n, line in enumerate(pm.group(2).split("\n")):
            for k, (stype, stext, _s0, _s1) in enumerate(
                    _split_segments(line, harlowe)):
                frags = _extract_segment(stype, stext, None, harlowe)
                segments.append({
                    "line": n,
                    "seg": k,
                    "type": stype,
                    "raw": stext,
                    "translatable": [f[0] for f in frags],
                })
        doc["passages"].append({
            "pid": a.get("pid", "?"),
            "name": html_mod.unescape(a.get("name", "")),
            "tags": a.get("tags", ""),
            "segments": segments,
        })
    return doc


def write_story_json(game_dir: str, out_path: str | None = None) -> str:
    """Пишет JSON-модель игры рядом с ней: «игра.json». Возвращает путь.

    Файл — тот же структурированный документ, что строит story_to_json:
    его можно открыть и прочитать/отредактировать отдельно от html,
    а перевод применится к новой html-копии (см. apply target_lang=...).
    """
    doc = story_to_json(game_dir)
    if out_path is None:
        story = find_story(game_dir)
        if story:
            base = os.path.splitext(story)[0]
            out_path = base + ".json"
        else:
            out_path = os.path.join(game_dir, "story.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    return out_path

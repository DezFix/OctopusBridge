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
"""
from __future__ import annotations

import html as html_mod
import os
import re
import shutil

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
# текст (кнопки, ссылки, выборы) и должны переводиться
_PRINT_MACROS = {
    "button", "link", "label", "radio", "checkbox", "select", "option",
    "click", "hover", "menu", "prompt", "textbox", "textarea",
    "input", "linkappend", "linkprepend", "linkreplace", "goto", "addclass",
}


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


def _split_segments(line: str) -> list[tuple[str, str, int, int]]:
    """Разбивает строку пассажа на сегменты (тип, текст, start, end).

    Типы: text, link ([[...]]), img ([img[...]]), macro (<<...>>),
    tag (<...>), var ($var). Последний сегмент может быть обрезан
    (незакрытый макрос — продолжается на следующей строке).
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
                     codes: list[str]) -> list[tuple[str, str, int]]:
    """Переводимые фрагменты сегмента: (текст, вид, индекс).

    Возвращает список (фрагмент, вид, idx):
    вид 'text' — текст сегмента (замаскированный, без отступов),
    idx = -1; вид 'link' — подпись ссылки, idx = -1; вид 'arg' —
    строка-аргумент печатающего макроса, idx — номер аргумента.
    """
    out: list[tuple[str, str, int]] = []
    if seg_type == "text":
        stripped = seg_text.strip()
        if not stripped:
            return out
        # комментарий в коде (/* … */) — не текст для игрока
        if _is_code_comment(stripped):
            return out
        masked, _ = mask_codes(stripped)
        if _has_translatable_text(masked):
            out.append((masked, "text", -1))
    elif seg_type == "link":
        inner = seg_text[2:-2]
        label, sep, target = _link_parts(inner)
        if sep and not RE_LINK_CODE.search(label) \
                and _has_letters(label):
            out.append((label, "link", -1))
    elif seg_type == "macro":
        name_m = re.match(r"<<\s*([A-Za-z_]+)", seg_text)
        if name_m and name_m.group(1).lower() in _PRINT_MACROS:
            args = _macro_args(seg_text)
            for i, (arg, _off, _q) in enumerate(args):
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


def mask_codes(text: str) -> tuple[str, list[str]]:
    """Заменяет Twine-коды (<<..>>, $var, HTML-теги, таргеты ссылок
    [[..]]) на <xN/>.

    Подпись ссылки [[подпись|таргет]] остаётся текстом — её переводит
    LLM, а таргет (имя пассажа) замаскирован. Ссылки без разделителя
    ([[таргет]]) и с кодом в подписи уходят в токен целиком.

    Возвращает (замаскированный текст, список кодов) — порядок
    и число кодов детерминированы: одинаковый вход → одинаковые
    токены, поэтому маску можно пересчитывать в apply.
    """
    codes: list[str] = []

    def repl(m: re.Match) -> str:
        codes.append(m.group(0))
        return f"<x{len(codes) - 1}/>"

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
            # line continuation '\' склеивает строки — перевод ломает
            # структуру: такие строки не извлекаем вовсе
            if _RE_LINE_CONT.search(u):
                continue
            # В Twine-экспорте макросы экранированы (&lt;&lt;if…&gt;&gt;) —
            # после unescape разбиваем строку на сегменты и берём
            # только текстовые (текст, подписи ссылок, аргументы
            # кнопок/ссылок); код-сегменты не извлекаем вовсе.
            for k, (stype, stext, _s0, _s1) in enumerate(
                    _split_segments(u)):
                for frag, kind, arg_idx in _extract_segment(stype, stext,
                                                            None):
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
               original: str, translation: str) -> str | None:
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
        masked, codes = mask_codes(stripped)
        if masked != original:
            return None
        text = unmask_codes(translation, codes)
        if mask_codes(text)[1] != codes:
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
        if RE_LINK_CODE.search(translation):
            return None
        if sep == "<-":
            return f"[[{target}{sep}{translation}]]"
        return f"[[{translation}{sep}{target}]]"
    if stype == "macro":
        name_m = re.match(r"<<\s*([A-Za-z_]+)", stext)
        if arg_idx < 0 or not name_m \
                or name_m.group(1).lower() not in _PRINT_MACROS:
            return None
        args = _macro_args(stext)
        if arg_idx >= len(args):
            return None
        arg, off, q = args[arg_idx]
        if arg != original:
            return None
        return stext[:off] + q + translation + q + stext[off + len(q) + len(arg):]
    return None


def apply(game_dir: str, entries: list[TranslationEntry],
          backup_root: str | None = None, on_skip=None) -> dict:
    """Внедряет переводы построчно обратно в .html истории (с бэкапом)."""
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

    if backup_root is None:
        backup_root = _backup_dir(game_dir)
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
                    _, codes = mask_codes(cur_unesc)
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
                    if mask_codes(text)[1] != codes:
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
                seg_list = _split_segments(cur_unesc)
                want = {k: (arg_idx, orig, trans)
                        for k, arg_idx, orig, trans in segs}
                parts: list[str] = []
                any_changed = False
                for k, (stype, stext, s0, s1) in enumerate(seg_list):
                    w = want.get(k)
                    if w is None:
                        parts.append(cur_unesc[s0:s1])
                        continue
                    arg_idx, orig, trans = w
                    repl = _apply_seg(stype, stext, arg_idx, orig, trans)
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
    with open(story, "w", encoding="utf-8") as f:
        f.write(new_text)
    return {"files": 1 if written else 0, "strings": written,
            "backups": [backup_path]}


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

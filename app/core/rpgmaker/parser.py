# -*- coding: utf-8 -*-
"""Парсер RPG Maker MV/MZ: извлечение и внедрение текста в data/*.json.

Расширенное извлечение (v2):
- Все текстоносные поля БД (Actors, Items, Skills, States, ...)
- Команды событий: диалоги, комментарии, выбор, плагин-команды
- Имена карт, общих событий, групп врагов
- Системные строки (термины, сообщения, название игры)
- Поля message1..message4 в Skills/States
- Все плагин-команда (MZ: cmd 357/657, MV: cmd 356) с параметрами

Заметки (note) не извлекаются: это конфигурация плагинов (теги <...>),
перевод ломает их работу и выдаёт ошибки в игре.
"""
from __future__ import annotations

import json
import os
import re
import shutil

from app.core.models import TranslationEntry

# ── Коды команд событий ──
CMD_DIALOG = 401
CMD_SCROLL = 405
CMD_CHOICES = 102
CMD_CHOICE_BRANCH = 402
CMD_COMMENT = 108
CMD_COMMENT_CONT = 408
CMD_SHOW_TEXT_HDR = 101
CMD_CHANGE_NAME = 320
CMD_CHANGE_NICK = 324
CMD_PLUGIN = 357
CMD_PLUGIN_CONT = 657
CMD_PLUGIN_MV = 356
CMD_SCRIPT = 355
CMD_SCRIPT_CONT = 655

# ── Поля БД: файл -> список полей ──
DB_FIELDS = {
    "Actors.json": ["name", "nickname", "profile"],
    "Classes.json": ["name"],
    "Items.json": ["name", "description"],
    "Weapons.json": ["name", "description"],
    "Armors.json": ["name", "description"],
    "Enemies.json": ["name"],
    "Skills.json": ["name", "description", "message1", "message2"],
    "States.json": ["name", "message1", "message2", "message3", "message4"],
    "Animations.json": ["name"],
    "Tilesets.json": ["name"],
}

SYSTEM_LIST_FIELDS = [
    "skillTypes", "armorTypes", "weaponTypes", "elements", "equipTypes"
]
TERMS_LIST_FIELDS = ["basic", "commands", "params"]


def detect_engine(game_dir: str) -> str:
    """Определяет движок: 'mz' | 'mv' | 'unknown'."""
    from .variant import detect_variant
    return detect_variant(game_dir)


def find_data_dir(game_dir: str) -> str:
    """Где лежат данные: 'data' (MZ/MV) или 'www/data' (деплой MV)."""
    if os.path.isdir(os.path.join(game_dir, "data")):
        return "data"
    if os.path.isdir(os.path.join(game_dir, "www", "data")):
        return "www/data"
    return "data"


# ── Пути внутри JSON ──

_PATH_TOKEN = re.compile(r'([^\[\]]+)|\[(\d+)\]')


def parse_path(path: str) -> list:
    """'events[3].pages[0]' -> ['events', 3, 'pages', 0]"""
    out = []
    for m in _PATH_TOKEN.finditer(path):
        name, idx = m.group(1), m.group(2)
        if idx is not None:
            out.append(int(idx))
        elif name:
            for part in name.split('.'):
                if part:
                    out.append(part)
    return out


def get_by_path(obj, path: str):
    node = obj
    for key in parse_path(path):
        if isinstance(node, str):
            raise TypeError("path goes into a string")
        node = node[key]
    return node


# ── Тексты внутри JS (скрипт-команды 355/655) ──

_JS_STRING_RE = re.compile(r"""(["'])((?:\\.|(?!\1).)*)\1""", re.S)
_JS_CJK_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]")


def iter_js_strings(code: str) -> list[tuple[str, str, int, int]]:
    """(raw, quote, start, end) строковых литералов JS-кода.

    Комментарии и template-литералы игнорируются; end — позиция
    сразу после закрывающей кавычки.
    """
    out: list[tuple[str, str, int, int]] = []
    i, n = 0, len(code)
    while i < n:
        c = code[i]
        if c == "/" and i + 1 < n:
            nxt = code[i + 1]
            if nxt == "/":
                j = code.find("\n", i)
                i = n if j == -1 else j + 1
                continue
            if nxt == "*":
                j = code.find("*/", i + 2)
                i = n if j == -1 else j + 2
                continue
        if c in "\"'":
            start = i
            j = i + 1
            while j < n:
                ch = code[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == c:
                    break
                j += 1
            if j < n and code[j] == c:
                out.append((code[i + 1:j], c, start, j + 1))
                i = j + 1
                continue
        i += 1
    return out


def extract_js_strings(code: str) -> list[str]:
    """Строковые литералы из JS-кода (без комментариев, template-строк)."""
    return [raw for raw, _, _, _ in iter_js_strings(code)]


def js_text_candidate(s: str) -> bool:
    """Подходит ли литерал для перевода: текст, а не идентификатор/путь."""
    if not s or len(s) < 2 or len(s) > 400:
        return False
    if not re.search(r"[^\W\d_]", s):          # без букв
        return False
    if _JS_CJK_RE.search(s):
        return True                            # CJK — почти наверняка текст
    if not re.search(r"\s", s):                # латиница без пробела — ключ
        return False
    if re.search(r"[\\/]", s):                 # пути, коды
        return False
    if s.startswith(("http", "www.", "=", ":", "<")):
        return False
    return True


# ── Тексты в js-плагинах ──

_PLUGIN_MARK = "#plugin:"
_PLUGIN_SKIP_PREFIXES = ("rmmz_", "rpg_", "pixi", "lz-", "effekseer", "kry_")
_PLUGIN_SKIP_STARTS = (
    "var ", "const ", "let ", "function", "return ", "this.", "new ",
    "typeof", "instanceof", "delete ", "import ", "export ", "class ",
    "extends ", "if (", "else", "try ", "catch ", "throw ", "switch ",
    "case ", "while (", "for (", "do ", "break", "continue", "await ",
    "yield ", "=>", "http", "www.", "use strict",
)
_PLUGIN_SKIP_EXACT = ("null", "true", "false", "undefined", "NaN", "none",
                      "none yet", "empty")


def _plugin_text_candidate(s: str) -> bool:
    if not js_text_candidate(s):
        return False
    if s.strip().lower() in _PLUGIN_SKIP_EXACT:
        return False
    low = s.lstrip().lower()
    return not low.startswith(_PLUGIN_SKIP_STARTS)


def _read_plugins(path: str, variant: str = "") -> list | None:
    """plugins.js: MZ — JSON-массив '[...]' в data/, MV — JS-скрипт
    'var $plugins = [...];' в js/. Возвращает список или None.

    Основной парсер выбирается по варианту, при неудаче пробуем другой
    (страховка для нестандартных деплоев).
    """
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return None
    from .variant import is_mv
    order = ("js", "json") if is_mv(variant) else ("json", "js")
    for mode in order:
        if mode == "json":
            if not text.lstrip().startswith("["):
                continue
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
        else:
            if text.lstrip().startswith("["):
                continue
            try:
                start = text.index("[")
                end = text.rindex("]") + 1
                # MV-редактор пишет висячие запятые перед ']'/'}' (JS)
                return json.loads(re.sub(r",(\s*[\]}])", r"\1",
                                          text[start:end]))
            except (ValueError, json.JSONDecodeError):
                continue
    return None


def extract_plugins(game_dir: str, data_dir: str, on_skip=None,
                    variant: str | None = None) -> list:
    """Тексты из включённых js-плагинов (js/plugins/<name>.js).

    Список плагинов берём по варианту игры: MV — js/plugins.js
    (JS-скрипт), MZ — data/plugins.js (JSON-массив). Строковые
    литералы с фильтром на текст (не код/ключи/пути).
    Возвращает записи с json_path "#plugin:<n>" — внедрение идёт
    по содержимому литерала в тексте файла.
    """
    from .variant import detect_variant, plugins_list_rel
    if variant is None:
        variant = detect_variant(game_dir)
    js_dir = "www/js" if data_dir.startswith("www/") else "js"
    rel = plugins_list_rel(variant, game_dir, data_dir)
    if not rel:
        return []
    plugins = _read_plugins(
        os.path.join(game_dir, rel.replace("/", os.sep)), variant)
    if not plugins:
        return []
    ex = _Extractor()
    for pl in plugins:
        if not isinstance(pl, dict) or not pl.get("status"):
            continue
        name = pl.get("name", "")
        if not name or name.startswith(_PLUGIN_SKIP_PREFIXES):
            continue
        # имена параметров (из plugins.js) — это КЛЮЧИ, а не текст:
        # плагины читают их через Parameters['Default Rows']; перевод
        # ключа ломает плагин (YEP_MessageCore и др. зависают на
        # старте новой игры). Пропускаем точные совпадения.
        params = pl.get("parameters")
        param_keys = ({str(k) for k in params.keys()}
                      if isinstance(params, dict) else set())
        # plugins.js хранит имя с расширением ("MyPlugin.js") — не
        # приклеиваем ".js" повторно
        js_name = name[:-3] if name.lower().endswith(".js") else name
        code = None
        try:
            with open(os.path.join(game_dir, js_dir, "plugins",
                                   js_name + ".js"),
                      encoding="utf-8") as f:
                code = f.read()
        except (OSError, UnicodeDecodeError) as e:
            if on_skip:
                on_skip(name, e)
            continue
        rel = f"{js_dir}/plugins/{js_name}.js"
        n = 0
        for s in extract_js_strings(code):
            if s.strip() in param_keys:
                continue
            if _plugin_text_candidate(s):
                ex.add(rel, f"{_PLUGIN_MARK}{n}", f"plugin {name}", s)
                n += 1
    return ex.entries


def set_by_path(obj, path: str, value) -> None:
    keys = parse_path(path)
    node = obj
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value


# ── Извлечение ──

class _Extractor:
    def __init__(self):
        self.entries: list[TranslationEntry] = []
        self._next_id = 1
        self._seen: set[tuple[str, str]] = set()

    def add(self, file: str, path: str, context: str, text: str):
        if not isinstance(text, str) or not text.strip():
            return
        key = (file, path)
        if key in self._seen:
            return
        self._seen.add(key)
        self.entries.append(TranslationEntry(
            id=self._next_id, file=file, json_path=path,
            context=context, original=text,
        ))
        self._next_id += 1

    # ── команды событий ──
    def event_list(self, file: str, base: str, cmd_list: list, context: str):
        for i, cmd in enumerate(cmd_list):
            if not isinstance(cmd, dict):
                continue
            code = cmd.get("code")
            params = cmd.get("parameters") or []
            p = f"{base}[{i}].parameters"

            if code in (CMD_DIALOG, CMD_SCROLL, CMD_COMMENT, CMD_COMMENT_CONT):
                if params:
                    kind = ("comment" if code in (CMD_COMMENT, CMD_COMMENT_CONT)
                            else "dialog")
                    self.add(file, f"{p}[0]", f"{context} / {kind}", params[0])
            elif code == CMD_CHOICES and params and isinstance(params[0], list):
                for j, label in enumerate(params[0]):
                    self.add(file, f"{p}[0][{j}]",
                             f"{context} / choice", label)
            elif code == CMD_CHOICE_BRANCH and len(params) > 1:
                self.add(file, f"{p}[1]", f"{context} / branch", params[1])
            elif code == CMD_SHOW_TEXT_HDR and len(params) > 4:
                self.add(file, f"{p}[4]",
                         f"{context} / speaker name", params[4])
            elif code in (CMD_CHANGE_NAME, CMD_CHANGE_NICK) and len(params) > 1:
                self.add(file, f"{p}[1]", f"{context} / rename", params[1])
            elif code == CMD_PLUGIN and len(params) > 3:
                args = params[3]
                if isinstance(args, dict):
                    for k, v in args.items():
                        self.add(file, f"{p}[3].{k}",
                                 f"{context} / plugin", v)
                elif isinstance(args, list):
                    for j, v in enumerate(args):
                        self.add(file, f"{p}[3][{j}]",
                                 f"{context} / plugin", v)
            elif code == CMD_PLUGIN_CONT:
                for j, v in enumerate(params):
                    self.add(file, f"{p}[{j}]",
                             f"{context} / plugin", v)
            elif code == CMD_PLUGIN_MV and params:
                self.add(file, f"{p}[0]",
                         f"{context} / plugin (MV)", params[0])
            elif code in (CMD_SCRIPT, CMD_SCRIPT_CONT) and params:
                n = 0
                for s in extract_js_strings(params[0]):
                    if js_text_candidate(s):
                        self.add(file, f"{p}[0]{_SCRIPT_MARK}:{n}",
                                 f"{context} / script", s)
                        n += 1
            else:
                # generic fallback — неизвестные коды / кастомные плагины:
                # берём CJK-строки и осмысленный латинский текст на любой
                # глубине вложенности. Вариант-3 применяет перевод только
                # в памяти игры, поэтому ложные срабатывания безопасны.
                for j, v in enumerate(params):
                    self._generic_walk_value(
                        file, f"{p}[{j}]", f"{context} / param {code}", v)

    def db_file(self, file: str, data: list, fields: list[str]):
        for idx, obj in enumerate(data):
            if not isinstance(obj, dict):
                continue
            name = obj.get("name") or f"#{idx}"
            for field in fields:
                if field in obj:
                    self.add(file, f"[{idx}].{field}",
                             f"{file[:-5]} '{name}'", obj[field])

    def map_file(self, file: str, data: dict):
        if data.get("displayName"):
            self.add(file, "displayName", "map name", data["displayName"])
        for ei, ev in enumerate(data.get("events") or []):
            if not isinstance(ev, dict):
                continue
            if ev.get("name"):
                self.add(file, f"events[{ei}].name",
                         f"{file[:-5]} event name", ev["name"])
            for pi, page in enumerate(ev.get("pages") or []):
                if not isinstance(page, dict):
                    continue
                ctx = (f"{file[:-5]} event "
                       f"'{ev.get('name', ei)}' p.{pi + 1}")
                self.event_list(
                    file, f"events[{ei}].pages[{pi}].list",
                    page.get("list") or [], ctx)

    def common_events(self, file: str, data: list):
        for idx, ev in enumerate(data):
            if not isinstance(ev, dict):
                continue
            self.add(file, f"[{idx}].name",
                     f"common event #{idx}", ev.get("name", ""))
            self.event_list(
                file, f"[{idx}].list", ev.get("list") or [],
                f"common event '{ev.get('name', idx)}'")

    def troops(self, file: str, data: list):
        for idx, tr in enumerate(data):
            if not isinstance(tr, dict):
                continue
            self.add(file, f"[{idx}].name",
                     f"enemy group #{idx}", tr.get("name", ""))
            for pi, page in enumerate(tr.get("pages") or []):
                if not isinstance(page, dict):
                    continue
                self.event_list(
                    file, f"[{idx}].pages[{pi}].list",
                    page.get("list") or [],
                    f"battle '{tr.get('name', idx)}' p.{pi + 1}")

    def system(self, file: str, data: dict):
        self.add(file, "gameTitle", "game title",
                 data.get("gameTitle", ""))
        self.add(file, "currencyUnit", "currency",
                 data.get("currencyUnit", ""))
        for fld in SYSTEM_LIST_FIELDS:
            for j, v in enumerate(data.get(fld) or []):
                self.add(file, f"{fld}[{j}]", f"term {fld}", v)
        for j, v in enumerate(data.get("variables") or []):
            self.add(file, f"variables[{j}]", f"variable #{j}", v)
        for j, v in enumerate(data.get("switches") or []):
            self.add(file, f"switches[{j}]", f"switch #{j}", v)
        terms = data.get("terms") or {}
        if not isinstance(terms, dict):
            terms = {}
        for fld in TERMS_LIST_FIELDS:
            for j, v in enumerate(terms.get(fld) or []):
                self.add(file, f"terms.{fld}[{j}]",
                         f"term {fld}", v)
        for k, v in (terms.get("messages") or {}).items():
            self.add(file, f"terms.messages.{k}",
                     "system message", v)

    def map_infos(self, file: str, data: list):
        for idx, obj in enumerate(data):
            if isinstance(obj, dict) and obj.get("name"):
                self.add(file, f"[{idx}].name",
                         "map name (list)", obj["name"])

    # ── generic fallback — для кастомных плагинов/игр ──────────────
    _GENERIC_SKIP_KEYS = {"note", "meta", "traits", "effects", "damage"}

    def _generic_text(self, s) -> bool:
        """Кандидат из НЕИЗВЕСТНОЙ структуры: CJK-строка или осмысленный
        латинский текст (как js_text_candidate). Вариант-3 применяет
        перевод только в памяти игры, поэтому ложные срабатывания здесь
        безопаснее, чем при патче файлов; фильтруем лишь очевидный код
        (пути/URL/ключи без пробелов/одиночные символы)."""
        if not isinstance(s, str):
            return False
        s = s.strip()
        if not s or len(s) > 600:
            return False
        if _JS_CJK_RE.search(s):
            return True
        return js_text_candidate(s)

    # обратная совместимость: старое имя метода
    def _generic_cjk(self, s) -> bool:
        return self._generic_text(s)

    def _generic_walk_value(self, file: str, path: str, ctx: str,
                            v, depth: int = 0):
        """Рекурсивный обход значения произвольной глубины."""
        if depth > 4 or v is None:
            return
        if isinstance(v, str):
            if self._generic_text(v):
                self.add(file, path, ctx, v)
        elif isinstance(v, dict):
            for dk, dv in v.items():
                self._generic_walk_value(
                    file, f"{path}.{dk}", ctx, dv, depth + 1)
        elif isinstance(v, list):
            for j, item in enumerate(v):
                self._generic_walk_value(
                    file, f"{path}[{j}]", ctx, item, depth + 1)

    def generic_obj(self, file: str, obj: dict, base: str, ctx: str, depth: int = 0):
        """Рекурсивный обход неизвестной JSON-структуры.

        Берём CJK-строки и осмысленный латинский текст на любой
        глубине (до 6 уровней вложенности).
        """
        if depth > 6 or not isinstance(obj, dict):
            return
        for k, v in obj.items():
            if k in self._GENERIC_SKIP_KEYS:
                continue
            path = f"{base}.{k}" if base else k
            if isinstance(v, dict):
                self.generic_obj(file, v, path, ctx, depth + 1)
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    self._generic_walk_value(
                        file, f"{path}[{i}]", ctx, item, 1)
            else:
                self._generic_walk_value(file, path, ctx, v)

    def db_file_generic(self, file: str, data: list, known_fields: list[str]):
        """DB-файл + добираем кастомные текстовые поля вне known_fields."""
        # known — уже извлечены через db_file; теперь ищем кастомные
        for idx, obj in enumerate(data):
            if not isinstance(obj, dict):
                continue
            for k, v in obj.items():
                if k in known_fields or k in self._GENERIC_SKIP_KEYS:
                    continue
                self._generic_walk_value(
                    file, f"[{idx}].{k}",
                    f"{file[:-5]} '{obj.get('name') or idx}' / {k}", v)

def _read_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_rpgm_map(game_dir: str, path: str) -> dict | None:
    """Читает зашифрованную карту MV (.rpgmvm) как dict JSON."""
    try:
        with open(path, "rb") as f:
            body = f.read()
    except OSError:
        return None
    from app.core.rpgmaker import crypto
    key = crypto.get_key_mv(game_dir)
    if not key:
        return None
    try:
        plain = crypto.decrypt_bytes(body, key)
    except (ValueError, IndexError):
        return None
    try:
        return json.loads(plain.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None


def extract(game_dir: str, data_dir: str | None = None,
            variant: str | None = None,
            on_skip=None) -> list[TranslationEntry]:
    """Извлекает все переводимые строки из data/*.json игры.

    variant ('mz'/'mv') определяет, где искать список плагинов и как
    его парсить; при None — авто-детект. Поддерживает и зашифрованные
    карты MV (.rpgmvm).
    on_skip(filename, exception) вызывается, если файл не удалось прочитать.
    """
    if data_dir is None:
        data_dir = find_data_dir(game_dir)
    if variant is None:
        from .variant import detect_variant
        variant = detect_variant(game_dir)
    ex = _Extractor()
    root = os.path.join(game_dir, data_dir)
    for fname in sorted(os.listdir(root)):
        rel = f"{data_dir}/{fname}"
        if fname.endswith(".json"):
            try:
                data = _read_json(os.path.join(root, fname))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                if on_skip:
                    on_skip(fname, e)
                else:
                    print(f"[parser] skipped {fname}: {e}")
                continue
            if fname in DB_FIELDS:
                ex.db_file(rel, data, DB_FIELDS[fname])
                # кастомные поля от плагинов (YEP и т.п.) — добираем CJK
                ex.db_file_generic(rel, data, DB_FIELDS[fname])
            elif fname.startswith("Map") and fname != "MapInfos.json":
                ex.map_file(rel, data)
            elif fname == "CommonEvents.json":
                ex.common_events(rel, data)
            elif fname == "Troops.json":
                ex.troops(rel, data)
            elif fname == "System.json":
                ex.system(rel, data)
            elif fname == "MapInfos.json":
                ex.map_infos(rel, data)
            else:
                # неизвестный JSON (кастомные файлы плагинов):
                # только изолированные CJK-строки — текст, без кода
                if isinstance(data, dict):
                    ex.generic_obj(rel, data, "", f"file {fname}")
                elif isinstance(data, list):
                    for idx, item in enumerate(data):
                        if isinstance(item, dict):
                            ex.generic_obj(rel, item, f"[{idx}]",
                                           f"file {fname} #{idx}")
                        elif isinstance(item, str) and ex._generic_cjk(item):
                            ex.add(rel, f"[{idx}]", f"file {fname} #{idx}", item)
        elif fname.lower().endswith(".rpgmvm"):
            data = _read_rpgm_map(game_dir, os.path.join(root, fname))
            if data is None:
                if on_skip:
                    on_skip(fname, "cannot decrypt MV map")
                else:
                    print(f"[parser] skipped {fname}: cannot decrypt")
                continue
            ex.map_file(rel, data)
    entries = ex.entries
    entries += extract_plugins(game_dir, data_dir, on_skip, variant)
    return entries


# ── Внедрение ──

def _detect_indent(path: str) -> int | None:
    with open(path, encoding="utf-8") as f:
        head = f.read(64)
    return 2 if head.startswith("{\n") or head.startswith("[\n") else None


_SCRIPT_MARK = "#script"


def _replace_js_strings(code: str, original: str,
                        translation: str) -> str | None:
    """Заменяет литералы, равные original, на translation. None — если
    ни один литерал не совпал (строка уже изменена или её нет)."""
    matches = iter_js_strings(code)
    if not any(raw == original for raw, _, _, _ in matches):
        return None
    result = code
    for raw, q, start, end in reversed(matches):
        if raw == original:
            esc = (translation
                   .replace("\\", "\\\\").replace("\r", "\\r")
                   .replace("\n", "\\n").replace(q, "\\" + q))
            result = result[:start] + q + esc + q + result[end:]
    return result


def apply(game_dir: str, entries: list[TranslationEntry],
          backup_root: str | None = None, data_dir: str | None = None,
          target_lang: str = "ru",
          on_skip=None) -> dict:
    """Внедряет переводы обратно в файлы игры. Возвращает статистику.

    Гибридный режим: JSON-файлы + опциональная генерация JS-пейлоада
    для live-подмены.
    """
    if data_dir is None:
        data_dir = find_data_dir(game_dir)
    by_file: dict[str, list[TranslationEntry]] = {}
    for e in entries:
        if e.translation.strip() and e.status != "skip":
            by_file.setdefault(e.file, []).append(e)

    if backup_root is None:
        backup_root = os.path.join(game_dir, "backup")
    stats = {"files": 0, "strings": 0, "backups": []}

    for rel, items in by_file.items():
        abs_path = os.path.join(game_dir, *rel.split("/"))
        if not os.path.exists(abs_path):
            continue
        backup_path = os.path.join(backup_root, rel)
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        if not os.path.exists(backup_path):
            shutil.copy2(abs_path, backup_path)
            stats["backups"].append(backup_path)

        if rel.lower().endswith(".rpgmvm"):
            # зашифрованная карта MV: расшифровали при извлечении,
            # переводим JSON и записываем обратно зашифрованной
            from app.core.rpgmaker import crypto
            key = crypto.get_key_mv(game_dir)
            if not key:
                continue
            try:
                with open(abs_path, "rb") as f:
                    body = f.read()
                data = json.loads(
                    crypto.decrypt_bytes(body, key).decode("utf-8"))
            except (OSError, ValueError, IndexError,
                    json.JSONDecodeError, UnicodeDecodeError):
                continue
            written = 0
            for e in items:
                if _PLUGIN_MARK in e.json_path or _SCRIPT_MARK in e.json_path:
                    continue
                try:
                    current = get_by_path(data, e.json_path)
                except (KeyError, IndexError, TypeError) as exc:
                    if on_skip:
                        on_skip(e, f"path not found: {exc}")
                    continue
                if isinstance(current, str):
                    try:
                        set_by_path(data, e.json_path, e.translation)
                        written += 1
                    except (KeyError, IndexError, TypeError) as exc:
                        if on_skip:
                            on_skip(e, f"cannot write: {exc}")
            try:
                new_body = crypto.encrypt_bytes(
                    json.dumps(data, ensure_ascii=False).encode("utf-8"), key)
                with open(abs_path, "wb") as f:
                    f.write(new_body)
            except OSError:
                continue
            stats["files"] += 1
            stats["strings"] += written
            continue

        if not rel.endswith(".json"):
            # js-плагин: заменяем литералы по содержимому
            try:
                with open(abs_path, encoding="utf-8") as f:
                    code = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            new_code = code
            for e in items:
                if _PLUGIN_MARK not in e.json_path:
                    continue
                replaced = _replace_js_strings(
                    new_code, e.original, e.translation)
                if replaced is not None:
                    new_code = replaced
                    stats["strings"] += 1
            if new_code != code:
                with open(abs_path, "w", encoding="utf-8") as f:
                    f.write(new_code)
                stats["files"] += 1
            continue

        data = _read_json(abs_path)
        indent = _detect_indent(abs_path)
        written = 0
        for e in items:
            if _SCRIPT_MARK in e.json_path:
                # текст внутри скрипт-команды (355/655): заменяем
                # литералы по содержимому, не трогая остальной код
                path = e.json_path.split(_SCRIPT_MARK, 1)[0]
                try:
                    script = get_by_path(data, path)
                except (KeyError, IndexError, TypeError) as exc:
                    if on_skip:
                        on_skip(e, f"path not found: {exc}")
                    else:
                        print(f"[parser] {rel}: path {path} "
                              f"not found ({exc})")
                    continue
                if not isinstance(script, str):
                    continue
                new_script = _replace_js_strings(
                    script, e.original, e.translation)
                if new_script is not None:
                    set_by_path(data, path, new_script)
                    written += 1
                continue
            try:
                current = get_by_path(data, e.json_path)
            except (KeyError, IndexError, TypeError) as exc:
                if on_skip:
                    on_skip(e, f"path not found: {exc}")
                else:
                    print(f"[parser] {rel}: path {e.json_path} "
                          f"not found ({exc})")
                continue
            if isinstance(current, str):
                try:
                    set_by_path(data, e.json_path, e.translation)
                    written += 1
                except (KeyError, IndexError, TypeError) as exc:
                    if on_skip:
                        on_skip(e, f"cannot write: {exc}")
                    else:
                        print(f"[parser] {rel}: cannot write "
                              f"{e.json_path} ({exc})")
            elif on_skip:
                on_skip(e, "current value is not a string")
        with open(abs_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        stats["files"] += 1
        stats["strings"] += written
    return stats


# имя старых таймстамп-папок бэкапа: YYYYmmdd_HHMMSS
_TS_RE = re.compile(r"^\d{8}_\d{6}$")


def restore_original(game_dir: str) -> dict:
    """Восстанавливает оригинальные файлы из backup/ (одноразовый бэкап
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

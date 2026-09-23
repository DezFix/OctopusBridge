# -*- coding: utf-8 -*-
"""Unity (Mono/IL2CPP): детект, сканирование и перевод ассетов.

Структура папки (без чтения содержимого):
- detect_unity() — признаки + вес;
- detect() — вес для реестра движков;
- iter_asset_files() — кандидаты .assets/.bundle/.resource (os.walk
  по именам, байты файлов не открываются).

Перевод (ленивый UnityPy, без него — пустые заглушки):
- harvest_textasset() / harvest_monobehaviour() — чистые, без UnityPy;
- patch_textasset() / patch_monobehaviour() — чистые, без UnityPy;
- extract() — TextAsset/MonoBehaviour/TextMesh/GUIText
  -> list[TranslationEntry] (json_path='asset://<file>/<path_id>/<field>',
  context='<Type>:<name>' без текста, дедуп по (file, json_path));
- apply() — BackupStore + atomic_write_bytes + verify переоткрытием.

Разведка (структура, без значений):
- TextAsset ~103 в sharedassets2/3/4/5 + resources: все UTF-8 (ok=103,
  fail=0), длины <1k dominant, 1k-10k minority;
- MonoBehaviour ~13.9k суммарно (sharedassets1 3182 + level1-5 + др.):
  без TypeTreeGeneratorAPI typetree скриптовых полей недоступен
  (parse_as_dict(check_read=True) -> ValueError, с check_read=False —
  только база m_GameObject/m_Enabled/m_Script/m_Name);
- Font x2 (resources.assets, sharedassets0.assets).
"""
from __future__ import annotations

import copy
import json
import os
import re

# Веса детекта. Якорь (<Name>_Data + globalgamemanagers) обязателен:
# без него вес 0 — порог как у соседних ядер (слабые сигналы вроде
# одинокого .exe за детект не считаем, иначе любой exe-каталог стал
# бы «Unity»).
_W_DATA_GGM = 40
_W_MANAGED_IL2CPP = 25
_W_LEVELS = 20
_W_EXE = 10

# Кандидаты на ассеты Unity (только по суффиксу имени, без чтения).
_ASSET_SUFFIXES = (".assets", ".bundle", ".resource")


def _data_dirs(game_dir: str) -> list[str]:
    """Папки <Name>_Data в корне игры (абс. пути, отсортированы)."""
    try:
        names = os.listdir(game_dir)
    except OSError:
        return []
    out = []
    for name in sorted(names):
        if name.lower().endswith("_data"):
            path = os.path.join(game_dir, name)
            if os.path.isdir(path):
                out.append(path)
    return out


def detect_unity(game_dir: str) -> dict:
    """Признаки Unity-игры: флаги по структуре папки + суммарный вес.

    Вес: *_Data + globalgamemanagers = 40; Managed/ или il2cpp_data
    = 25; level*-файлы = 20; .exe рядом = 10 (максимум 95).
    """
    has_ggm = False
    has_managed = False
    has_il2cpp = False
    has_levels = False
    data = _data_dirs(game_dir)
    for ddir in data:
        try:
            entries = os.listdir(ddir)
        except OSError:
            continue
        for entry in entries:
            full = os.path.join(ddir, entry)
            low = entry.lower()
            if low == "globalgamemanagers" \
                    or low.startswith("globalgamemanagers."):
                has_ggm = True
            elif os.path.isdir(full):
                if low == "managed":
                    has_managed = True
                elif low == "il2cpp_data":
                    has_il2cpp = True
            elif low.startswith("level"):
                has_levels = True
    has_exe = False
    try:
        top = os.listdir(game_dir)
    except OSError:
        top = []
    for name in top:
        if name.lower().endswith(".exe") \
                and os.path.isfile(os.path.join(game_dir, name)):
            has_exe = True
            break
    if not data or not has_ggm:
        weight = 0
    else:
        weight = _W_DATA_GGM
        if has_managed or has_il2cpp:
            weight += _W_MANAGED_IL2CPP
        if has_levels:
            weight += _W_LEVELS
        if has_exe:
            weight += _W_EXE
    return {
        "data_dirs": [os.path.basename(d) for d in data],
        "has_globalgamemanagers": has_ggm,
        "has_managed": has_managed,
        "has_il2cpp": has_il2cpp,
        "has_levels": has_levels,
        "has_exe": has_exe,
        "weight": weight,
    }


def detect(game_dir: str) -> int:
    """Вес уверенности: 0 — не Unity (порог как у соседних ядер)."""
    try:
        return int(detect_unity(game_dir).get("weight", 0))
    except OSError:
        return 0


def iter_asset_files(game_dir: str) -> list[str]:
    """Кандидаты ассетов: отн. пути файлов .assets/.bundle/.resource.

    Только сканирование диска по именам (os.walk) — содержимое файлов
    не открывается и не парсится.
    """
    out: list[str] = []
    for root, _dirs, files in os.walk(game_dir):
        for name in files:
            if name.lower().endswith(_ASSET_SUFFIXES):
                full = os.path.join(root, name)
                out.append(os.path.relpath(full, game_dir)
                           .replace(os.sep, "/"))
    return sorted(out)


# ── чистые функции (без UnityPy) ───────────────────────────────────────────

# Подозрительные на текст поля MonoBehaviour-typetree (VN/Choice/TMP).
# Сравнение — case-insensitive подстрока в имени поля.
_TEXT_HINTS: tuple[str, ...] = (
    "m_text",
    "text",
    "content",
    "dialog",
    "message",
    "string",
    "choice",
    "option",
    "caption",
    "label",
    "title",
    "subtitle",
    "description",
)

# Служебные поля Unity — никогда не переводим.
_SKIP_FIELDS: frozenset[str] = frozenset({
    "m_Script",
    "m_GameObject",
    "m_Enabled",
    "m_Name",
    "m_PrefabInstance",
    "m_PrefabAsset",
    "m_EditorHideFlags",
    "m_EditorClassIdentifier",
    "m_Namespace",
    "m_ClassName",
    "m_AssemblyName",
    "m_FileID",
    "m_PathID",
    "guid",
})

_TOKEN_RE = re.compile(r"([^\.\[\]]+)|\[(\d+)\]")


def _has_letters(text: str) -> bool:
    """True, если в строке есть хоть одна буква (отсев цифр/пунктуации)."""
    return any(ch.isalpha() for ch in text)


def _is_pptr(value: object) -> bool:
    """True для PPtr-ссылок вида {'m_FileID':.., 'm_PathID':..}."""
    if not isinstance(value, dict):
        return False
    keys = set(value.keys())
    return bool(keys) and keys <= {"m_FileID", "m_PathID"}


def _decode_text(value: str | bytes) -> str | None:
    """str/bytes -> str (utf-8) или None (бинарные/не-utf8)."""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return None


def _tokenize_field_path(path: str) -> list[str | int]:
    """'Choices[0].text' -> ['Choices', 0, 'text']."""
    toks: list[str | int] = []
    for m in _TOKEN_RE.finditer(path):
        name, idx = m.group(1), m.group(2)
        if name is not None:
            toks.append(name)
        else:
            toks.append(int(idx))
    return toks


def _get_path_value(tree: dict, field_path: str) -> str | None:
    """Значение строкового поля по пути или None (нет/не строка)."""
    try:
        toks = _tokenize_field_path(field_path)
    except Exception:
        return None
    cur: object = tree
    for tok in toks:
        if isinstance(tok, str):
            if not isinstance(cur, dict) or tok not in cur:
                return None
            cur = cur[tok]
        else:
            if not isinstance(cur, (list, tuple)):
                return None
            if tok < 0 or tok >= len(cur):
                return None
            cur = cur[tok]
    if isinstance(cur, str):
        return cur
    if isinstance(cur, bytes):
        return _decode_text(cur)
    return None


def _set_path_value(tree: dict, field_path: str, new_text: str) -> bool:
    """Установить строковое поле по пути. True — установлено."""
    toks = _tokenize_field_path(field_path)
    if not toks:
        return False
    cur: object = tree
    for tok in toks[:-1]:
        if isinstance(tok, str):
            if not isinstance(cur, dict) or tok not in cur:
                return False
            cur = cur[tok]
        else:
            if not isinstance(cur, (list, tuple)):
                return False
            if tok < 0 or tok >= len(cur):
                return False
            cur = cur[tok]
    last = toks[-1]
    try:
        if isinstance(last, str):
            if not isinstance(cur, dict) or last not in cur:
                return False
            old = cur[last]
            if isinstance(old, bytes):
                cur[last] = new_text.encode("utf-8")
            elif isinstance(old, str):
                cur[last] = new_text
            else:
                return False
            return True
        else:
            if not isinstance(cur, list):
                return False
            if last < 0 or last >= len(cur):
                return False
            old = cur[last]
            if isinstance(old, bytes):
                cur[last] = new_text.encode("utf-8")
            elif isinstance(old, str):
                cur[last] = new_text
            else:
                return False
            return True
    except Exception:
        return False


def _has_sentence(value: object) -> bool:
    """Есть ли в JSON-дереве хоть одно «предложение» (текст для игрока)."""
    stack: list[object] = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            s = node.strip()
            if len(s) >= 10 and _has_letters(s):
                return True
        elif isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
    return False


def _is_json_config(text: str) -> bool:
    """True — TextAsset это JSON-конфиг движка, а не текст для перевода.

    Примеры: {"TestSuite":"","Date":0,...}, {"clothType":1,...},
    {"MeasurementCount":-1}. Диалоги в JSON ({"text": "длинная реплика"})
    содержат предложения — такие НЕ режем.
    """
    s = text.strip()
    if not s or s[0] not in "{[":
        return False
    try:
        obj = json.loads(s)
    except Exception:
        return False
    if not isinstance(obj, (dict, list)):
        return False
    return not _has_sentence(obj)


def harvest_textasset(name: str, script: str | bytes) -> list[tuple[str, str]]:
    """Текст TextAsset -> [('m_Script', text)] или [] (пусто/бинарь/конфиг).

    Чистая, без UnityPy. ``name`` — только для сигнатуры (в контекст
    его подставляет extract, здесь не используется).
    """
    _ = name
    text = _decode_text(script)
    if text is None:
        return []
    stripped = text.strip()
    if len(stripped) < 2 or not _has_letters(stripped):
        return []
    if _is_json_config(stripped):
        return []
    return [("m_Script", stripped)]


def harvest_monobehaviour(tree: dict) -> list[tuple[str, str]]:
    """Строки MonoBehaviour-typetree по allow-list, рекурсия глуб.3.

    Чистая, без UnityPy. Пропуск: m_Script и PPtr-ссылки, служебные
    поля Unity. Путь поля — 'Choices[0].text' / 'm_text'.
    """
    out: list[tuple[str, str]] = []
    if not isinstance(tree, dict):
        return out

    def _walk(node: object, path: str, depth: int) -> None:
        if depth > 3 or node is None:
            return
        if isinstance(node, dict):
            for key, val in node.items():
                if not isinstance(key, str):
                    continue
                if key in _SKIP_FIELDS:
                    continue
                if _is_pptr(val):
                    continue
                child = f"{path}.{key}" if path else key
                if isinstance(val, (str, bytes)):
                    low = key.lower()
                    if not any(h in low for h in _TEXT_HINTS):
                        continue
                    text = _decode_text(val)
                    if text is None:
                        continue
                    stripped = text.strip()
                    if len(stripped) >= 2 and _has_letters(stripped):
                        out.append((child, stripped))
                elif isinstance(val, (dict, list, tuple)):
                    _walk(val, child, depth + 1)
        elif isinstance(node, (list, tuple)):
            base = path.rsplit(".", 1)[-1].split("[")[0] if path else ""
            base_low = base.lower()
            for idx, item in enumerate(node):
                child = f"{path}[{idx}]"
                if isinstance(item, (str, bytes)):
                    if not any(h in base_low for h in _TEXT_HINTS):
                        continue
                    text = _decode_text(item)
                    if text is None:
                        continue
                    stripped = text.strip()
                    if len(stripped) >= 2 and _has_letters(stripped):
                        out.append((child, stripped))
                elif isinstance(item, (dict, list, tuple)):
                    _walk(item, child, depth + 1)

    _walk(tree, "", 0)
    return out


def patch_textasset(
    script: str | bytes,
    translations: dict[str, str] | list[tuple[str, str]],
) -> str | bytes:
    """Новый m_Script по translations. Чистая, без UnityPy.

    ``translations`` — dict {field: new} или [(field, new)] (ищется
    'm_Script'); без совпадения — исходник без изменений (тип сохранён).
    """
    new: str | None = None
    if isinstance(translations, dict):
        if "m_Script" in translations and isinstance(
            translations["m_Script"], str
        ):
            new = translations["m_Script"]
        elif len(translations) == 1:
            sole = next(iter(translations.values()))
            if isinstance(sole, str):
                new = sole
    elif isinstance(translations, (list, tuple)):
        for item in translations:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            field, text = item
            if field == "m_Script" or (
                isinstance(field, str) and field.endswith("m_Script")
            ):
                if isinstance(text, str):
                    new = text
                    break
        if new is None and len(translations) == 1:
            try:
                cand = translations[0][1]
            except Exception:
                cand = None
            if isinstance(cand, str):
                new = cand
    elif isinstance(translations, str):
        new = translations
    if new is None:
        return script
    if isinstance(script, bytes):
        try:
            return new.encode("utf-8")
        except Exception:
            return script
    return new


def patch_monobehaviour(
    tree: dict,
    pairs: dict[str, str] | list[tuple[str, str]],
) -> dict:
    """Копия typetree с подставленными строками. Чистая, без UnityPy.

    ``pairs`` — dict {field_path: new} или [(field_path, new)];
    несуществующие пути молча пропускаются, исходник не мутируется.
    """
    if not isinstance(tree, dict):
        return tree
    new_tree = copy.deepcopy(tree)
    items: list[tuple[str, str]] = []
    if isinstance(pairs, dict):
        items = [(k, v) for k, v in pairs.items()
                 if isinstance(k, str) and isinstance(v, str)]
    elif isinstance(pairs, (list, tuple)):
        for item in pairs:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                field, text = item
                if isinstance(field, str) and isinstance(text, str):
                    items.append((field, text))
    else:
        return new_tree
    for field, text in items:
        try:
            _set_path_value(new_tree, field, text)
        except Exception:
            continue
    return new_tree


# Кэш typetree-генераторов: {(game_dir, version): gen}. Загрузка Managed
# в холодную может занять десятки секунд — один раз на игру за сессию,
# дальше переиспользуем (иначе 58с на КАЖДЫЙ файл extract/apply).
_TTGEN_CACHE: dict[tuple[str, str], object] = {}


def _close_env(env) -> None:
    """Закрыть файловые ручки env (fsspec LocalFileOpener).

    UnityPy.load(path) держит исходник открытым; на Windows открытая
    ручка роняет os.replace с WinError 5. Закрываем детерминированно
    перед atomic_write_bytes (загрузка из байтов — НЕ вариант: через
    неё ломается разбор скриптовых полей MonoBehaviour).
    Без исключений.
    """
    try:
        files = getattr(env, "files", None) or {}
    except Exception:
        return
    try:
        items = list(files.values())
    except Exception:
        return
    for asset in items:
        try:
            reader = getattr(asset, "reader", None)
            stream = getattr(reader, "stream", None)
        except Exception:
            continue
        try:
            if stream is not None and not getattr(stream, "closed", True):
                stream.close()
        except Exception:
            pass

# ── UnityPy-слой (ленивый импорт) ──────────────────────────────────────────

# Диагностика последнего extract для UI (копия stat): диалог извлечения
# показывает typetree-статус, иначе молчаливый 101 вместо 6400.
LAST_STATS: dict = {}

_TEXT_TYPES = frozenset({"TextAsset", "MonoBehaviour", "TextMesh", "GUIText"})


def _try_import_unitypy():
    """UnityPy или None (без исключений — для заглушек extract/apply)."""
    try:
        import UnityPy  # type: ignore[import-not-found]

        return UnityPy
    except Exception:
        return None


def _force_pure_python_reader() -> None:
    """Отключить C-ридер typetree (read_typetree_boost).

    В замороженной сборке (PyInstaller) нативный хелпер падает на
    КАЖДОМ parse_as_dict — extract молча отдаёт 0 при живых объектах
    (файлов 26/26, текстовых объектов 13988, записей 0). Pure-python
    медленнее (~2.5x), но работает везде. Без исключений.
    """
    try:
        from UnityPy.helpers import TypeTreeHelper as _tth  # type: ignore
        _tth.read_typetree_boost = False
    except Exception:
        pass


def _candidate_files(game_dir: str) -> list[str]:
    """iter_asset_files() + level*-файлы из *_Data (отн. пути, sort)."""
    rels = set(iter_asset_files(game_dir))
    for ddir in _data_dirs(game_dir):
        try:
            entries = os.listdir(ddir)
        except OSError:
            continue
        for entry in entries:
            if entry.lower().startswith("level"):
                full = os.path.join(ddir, entry)
                try:
                    if os.path.isfile(full):
                        rels.add(os.path.relpath(full, game_dir)
                                .replace(os.sep, "/"))
                except OSError:
                    continue
    return sorted(rels)


def _setup_typetree(env, game_dir: str, note: dict | None = None) -> bool:
    """Typetree-генератор из Managed/*.dll (Mono). False — недоступен.

    Требует пакет TypeTreeGeneratorAPI (опциональный, в requirements);
    без него MonoBehaviour-скриптовые поля не парсятся — extract берёт
    только TextAsset/TextMesh/GUIText + базу MonoBehaviour (без текста).
    Генератор кэшируется на (game_dir, version): холодная загрузка
    Managed — десятки секунд один раз, дальше мгновенно.
    Причина отказа (ASCII) — в note['typetree'] для диагностики exe.
    """
    def _reason(text: str) -> bool:
        if note is not None:
            raw = text[:120]
            note["typetree"] = "".join(
                ch for ch in raw if ord(ch) < 128)
        return False

    try:
        from UnityPy.helpers.TypeTreeGenerator import (  # type: ignore
            TypeTreeGenerator,
        )
    except Exception as e:
        return _reason(f"no-pkg {type(e).__name__}")
    try:
        version: str | None = None
        for fobj in getattr(env, "files", {}).values():
            cand = getattr(fobj, "unity_version", None)
            if isinstance(cand, str) and cand:
                version = cand
                break
            header = getattr(fobj, "header", None)
            cand = getattr(header, "unity_version", None) if header else None
            if isinstance(cand, str) and cand:
                version = cand
                break
        if not version:
            return _reason("no-version")
        key = (os.path.abspath(game_dir), version)
        gen = _TTGEN_CACHE.get(key)
        if gen is None:
            try:
                gen = TypeTreeGenerator(version)
            except Exception as e:
                return _reason(f"no-gen {type(e).__name__}")
            loaded = False
            for ddir in _data_dirs(game_dir):
                managed = os.path.join(ddir, "Managed")
                if os.path.isdir(managed):
                    try:
                        gen.load_local_dll_folder(managed)
                        loaded = True
                    except Exception:
                        continue
            if not loaded:
                return _reason("no-dll")
            _TTGEN_CACHE[key] = gen
        env.typetree_generator = gen
        if note is not None:
            note["typetree"] = "ok"
        return True
    except Exception as e:
        return _reason(f"fail {type(e).__name__}")


def _parse_json_path(json_path: str) -> tuple[str, int, str] | None:
    """'asset://<file>/<path_id>/<field>' -> (file, pid, field)."""
    if not isinstance(json_path, str) or not json_path.startswith("asset://"):
        return None
    try:
        rest = json_path[len("asset://"):]
        file_part, pid_str, field = rest.rsplit("/", 2)
        return (file_part, int(pid_str), field)
    except Exception:
        return None


def _object_name(tree: dict, fallback: str = "") -> str:
    """m_Name из typetree (только имя, без текста) для context."""
    try:
        name = tree.get("m_Name", fallback)
    except Exception:
        return fallback
    return name if isinstance(name, str) else fallback


def extract(game_dir: str, stats: dict | None = None) -> list:
    """Строки TextAsset/MonoBehaviour/TextMesh/GUIText -> TranslationEntry.

    json_path='asset://<basename>/<path_id>/<field>',
    file=отн. путь ассета, context='<Type>:<name>' (имя без текста),
    дедуп по (file, json_path). Без UnityPy -> [].
    В stats (если dict передан) — диагностика: candidates/files_checked,
    loaded, load_failed, objects, text_objects, entries (почему 0).
    """
    UnityPy = _try_import_unitypy()
    if UnityPy is None:
        return []
    _force_pure_python_reader()
    try:
        from app.core.models import TranslationEntry
    except Exception:
        return []
    entries: list = []
    seen: set[tuple[str, str]] = set()
    next_id = 1
    stat = {"candidates": 0, "checked": 0, "loaded": 0, "load_failed": 0,
            "objects": 0, "text_objects": 0, "parse_fail": 0, "parse_err": "",
            "typetree": "off"}
    cands = _candidate_files(game_dir)
    stat["candidates"] = len(cands)
    for rel in cands:
        abs_path = os.path.join(game_dir, *rel.split("/"))
        if not os.path.isfile(abs_path):
            continue
        try:
            # синтетика тестов (0-байт пустышки) — не трогаем UnityPy,
            # иначе на Windows остаётся открытая ручка и rmtree падает
            if os.path.getsize(abs_path) < 128:
                continue
        except OSError:
            continue
        stat["checked"] += 1
        # Путь, НЕ байты: load(bytes) ломает разбор скриптовых полей
        # MonoBehaviour. Ручки закрываем _close_env перед следующей
        # итерацией (иначе WinError 5 на replace/удалении).
        try:
            env = UnityPy.load(abs_path)
        except Exception:
            stat["load_failed"] += 1
            continue
        stat["loaded"] += 1
        try:
            _setup_typetree(env, game_dir, stat)
        except Exception:
            pass
        basename = rel.rsplit("/", 1)[-1]
        try:
            files = getattr(env, "files", {})
        except Exception:
            continue
        for _asset_key, asset in list(files.items()):
            objects = getattr(asset, "objects", None)
            if not objects:
                continue
            items = objects.values() if isinstance(objects, dict) else objects
            for obj in list(items):
                try:
                    type_name = getattr(obj.type, "name", "?")
                except Exception:
                    continue
                stat["objects"] += 1
                if str(type_name) not in _TEXT_TYPES:
                    continue
                stat["text_objects"] += 1
                try:
                    path_id = int(getattr(obj, "path_id", -1))
                except Exception:
                    continue
                # typetree: сначала строгий, затем базовый (без скрипт-полей)
                tree: dict | None = None
                try:
                    cand = obj.parse_as_dict()
                    if isinstance(cand, dict):
                        tree = cand
                except Exception as e:
                    # Первая ошибка разбора — в диагностику (только ASCII
                    # из текста исключения: тип + начало сообщения, без
                    # байтов игрового контента).
                    if not stat["parse_err"]:
                        raw = f"{type(e).__name__}: {e}"[:160]
                        stat["parse_err"] = "".join(
                            ch for ch in raw if ord(ch) < 128)
                    stat["parse_fail"] += 1
                    try:
                        cand = obj.parse_as_dict(check_read=False)
                        if isinstance(cand, dict):
                            tree = cand
                    except Exception:
                        stat["parse_fail"] += 1
                        continue
                if tree is None:
                    continue
                obj_name = _object_name(tree)
                pairs: list[tuple[str, str]] = []
                try:
                    if type_name == "TextAsset":
                        pairs = harvest_textasset(
                            obj_name, tree.get("m_Script", ""))
                    elif type_name == "MonoBehaviour":
                        pairs = harvest_monobehaviour(tree)
                    else:  # TextMesh / GUIText: поле m_Text
                        raw = tree.get("m_Text", tree.get("m_text", None))
                        text = _decode_text(raw) if raw is not None else None
                        if text is not None:
                            stripped = text.strip()
                            if len(stripped) >= 2 \
                                    and _has_letters(stripped):
                                pairs = [("m_Text", stripped)]
                except Exception:
                    continue
                for field, original in pairs:
                    if not isinstance(original, str):
                        continue
                    if len(original.strip()) < 2:
                        continue
                    json_path = f"asset://{basename}/{path_id}/{field}"
                    key = (rel, json_path)
                    if key in seen:
                        continue
                    seen.add(key)
                    context = f"{type_name}:{obj_name}"
                    entries.append(TranslationEntry(
                        id=next_id, file=rel, json_path=json_path,
                        context=context, original=original))
                    next_id += 1
        _close_env(env)
    if stats is not None:
        stats.update(stat)
        stats["entries"] = len(entries)
    LAST_STATS.clear()
    LAST_STATS.update(stat)
    LAST_STATS["entries"] = len(entries)
    return entries


def apply(
    game_dir: str,
    entries: list,
    target_lang: str = "ru",
    backup: bool = True,
    backup_root: str | None = None,
    **kwargs,
) -> dict:
    """Перевод в ассеты: BackupStore + atomic_write_bytes + verify.

    Группировка по e.file, позиция — из json_path
    ('asset://<file>/<path_id>/<field>'), сверка с оригиналом,
    пропуск при расхождении. Без UnityPy ->
    {'files': 0, 'strings': 0, 'skipped': 'no-unitypy'}.
    Пустой вход (с UnityPy) -> {'files': 0} (совместимость заглушки).
    """
    _ = target_lang
    _ = kwargs
    UnityPy = _try_import_unitypy()
    if UnityPy is None:
        return {"files": 0, "strings": 0, "skipped": "no-unitypy"}
    _force_pure_python_reader()
    if not entries:
        return {"files": 0}
    # группировка по файлу (поддержка TranslationEntry и dict)
    by_file: dict[str, list] = {}
    for entry in entries:
        try:
            if isinstance(entry, dict):
                translation = str(entry.get("translation", ""))
                status = entry.get("status", "new")
                file = str(entry.get("file", ""))
            else:
                translation = str(getattr(entry, "translation", ""))
                status = getattr(entry, "status", "new")
                file = str(getattr(entry, "file", ""))
        except Exception:
            continue
        if not translation.strip() or status == "skip" or not file:
            continue
        by_file.setdefault(file, []).append(entry)
    if not by_file:
        return {"files": 0, "strings": 0, "skipped": 0}
    stats: dict = {"files": 0, "strings": 0, "skipped": 0,
                   "backups": [], "verified": 0, "verify_failed": 0}
    for rel, items in by_file.items():
        abs_path = os.path.join(game_dir, *rel.split("/"))
        if not os.path.isfile(abs_path):
            stats["skipped"] += len(items)
            continue
        try:
            if os.path.getsize(abs_path) < 128:
                stats["skipped"] += len(items)
                continue
        except OSError:
            stats["skipped"] += len(items)
            continue
        # Путь, НЕ байты: load(bytes) ломает разбор скриптовых полей
        # MonoBehaviour. Ручки закрываем _close_env перед записью.
        try:
            env = UnityPy.load(abs_path)
        except Exception:
            stats["skipped"] += len(items)
            continue
        try:
            _setup_typetree(env, game_dir)
        except Exception:
            pass
        # pid -> объект
        pid_to_obj: dict[int, object] = {}
        pid_to_type: dict[int, str] = {}
        try:
            files = getattr(env, "files", {})
        except Exception:
            stats["skipped"] += len(items)
            continue
        for _ak, asset in list(files.items()):
            objects = getattr(asset, "objects", None)
            if not objects:
                continue
            vals = objects.values() if isinstance(objects, dict) else objects
            for obj in list(vals):
                try:
                    pid = int(getattr(obj, "path_id", -1))
                    tname = str(getattr(obj.type, "name", "?"))
                except Exception:
                    continue
                if pid not in pid_to_obj:
                    pid_to_obj[pid] = obj
                    pid_to_type[pid] = tname
        # переводы по pid
        grouped: dict[int, list[tuple[str, str, object]]] = {}
        for entry in items:
            try:
                if isinstance(entry, dict):
                    jp = str(entry.get("json_path", ""))
                    trans = str(entry.get("translation", ""))
                    orig = entry.get("original", "")
                else:
                    jp = str(getattr(entry, "json_path", ""))
                    trans = str(getattr(entry, "translation", ""))
                    orig = getattr(entry, "original", "")
            except Exception:
                stats["skipped"] += 1
                continue
            parsed = _parse_json_path(jp)
            if parsed is None:
                stats["skipped"] += 1
                continue
            _fpart, pid, field = parsed
            if not trans.strip():
                stats["skipped"] += 1
                continue
            grouped.setdefault(pid, []).append((field, trans, orig))
        file_written = 0
        for pid, lst in grouped.items():
            obj = pid_to_obj.get(pid)
            tname = pid_to_type.get(pid, "?")
            if obj is None:
                stats["skipped"] += len(lst)
                continue
            # строгий typetree; fallback-база для MonoBehaviour —
            # маркер неполноты (patch такой базы уронил бы скрипт-данные)
            tree: dict | None = None
            strict_ok = True
            try:
                cand = obj.parse_as_dict()  # type: ignore[attr-defined]
                if isinstance(cand, dict):
                    tree = cand
            except Exception:
                strict_ok = False
                try:
                    cand = obj.parse_as_dict(check_read=False)  # type: ignore[attr-defined]
                    if isinstance(cand, dict):
                        tree = cand
                except Exception:
                    stats["skipped"] += len(lst)
                    continue
            if tree is None:
                stats["skipped"] += len(lst)
                continue
            if tname == "MonoBehaviour" and not strict_ok:
                # скриптовые поля без генератора недоступны — не портим
                stats["skipped"] += len(lst)
                continue
            # сверка оригиналов + отбор к применению
            to_apply: list[tuple[str, str]] = []
            for field, trans, orig in lst:
                cur = _get_path_value(tree, field)
                if cur is None:
                    # TextAsset m_Script может лежать как bytes/str —
                    # _get_path_value уже декодирует; None = нет поля
                    stats["skipped"] += 1
                    continue
                orig_s = orig if isinstance(orig, str) else ""
                if cur != orig_s and cur.strip() != orig_s.strip():
                    stats["skipped"] += 1
                    continue
                to_apply.append((field, trans))
            if not to_apply:
                continue
            try:
                if tname == "TextAsset":
                    mapping = dict(to_apply)
                    new_script = patch_textasset(
                        tree.get("m_Script", ""), mapping)
                    if new_script == tree.get("m_Script", ""):
                        continue
                    tree["m_Script"] = new_script
                    obj.patch(tree)  # type: ignore[attr-defined]
                    file_written += len(to_apply)
                elif tname in ("TextMesh", "GUIText"):
                    new_tree = patch_monobehaviour(tree, to_apply)
                    if new_tree == tree:
                        continue
                    obj.patch(new_tree)  # type: ignore[attr-defined]
                    file_written += len(to_apply)
                elif tname == "MonoBehaviour":
                    new_tree = patch_monobehaviour(tree, to_apply)
                    if new_tree == tree:
                        continue
                    obj.patch(new_tree)  # type: ignore[attr-defined]
                    file_written += len(to_apply)
                else:
                    stats["skipped"] += len(to_apply)
            except Exception:
                stats["skipped"] += len(to_apply)
                continue
        if file_written <= 0:
            continue
        # бэкап до записи
        if backup:
            try:
                from app.core.io import BackupStore

                bdir = backup_root or os.path.join(
                    game_dir, "backup", "unity")
                store = BackupStore(bdir)
                saved = store.backup(abs_path)
                if saved:
                    stats["backups"].append(saved)
            except Exception:
                pass
        # запись + verify переоткрытием.
        # Порядок строгий: save() ПЕРВЫМ (читает из потока!), затем
        # _close_env (открытый исходник роняет os.replace с WinError 5),
        # затем atomic_write_bytes.
        data: bytes | None = None
        try:
            from app.core.io import atomic_write_bytes

            for _ak, asset in list(
                    getattr(env, "files", {}).items()):
                save = getattr(asset, "save", None)
                if not callable(save):
                    continue
                # однозадачный случай: один файл на диске
                if len(getattr(env, "files", {})) != 1:
                    continue
                raw = save()
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                data = bytes(raw)
            if data is None:
                stats["skipped"] += file_written
                continue
            _close_env(env)
            atomic_write_bytes(abs_path, data)
            try:
                # verify из байтов, НЕ путём: path-загрузка держит ручку
                # (мешает следующим replace/удалению на Windows)
                check_env = UnityPy.load(bytes(data))
                _ = getattr(check_env, "files", {})
                stats["verified"] += 1
            except Exception:
                stats["verify_failed"] += 1
            stats["files"] += 1
            stats["strings"] += file_written
        except Exception:
            stats["skipped"] += file_written
            continue
    return stats

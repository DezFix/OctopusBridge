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
- extract() — TextAsset/MonoBehaviour/TextMesh/GUIText/TextMeshProUGUI/
  TextMeshPro + текстовые файлы StreamingAssets (*.json/*.csv/*.txt)
  -> list[TranslationEntry] (json_path='asset://<file>/<path_id>/<field>'
  для ассетов и 'asset://<file>/streaming/content' для StreamingAssets,
  context='<Type>:<name>' без текста, дедуп по (file, json_path));
- apply() — BackupStore + atomic_write_bytes + verify переоткрытием
  (StreamingAssets — прямой перезаписью файла тем же паттерном);
- font_patch() — замена m_FontData классических Font на TTF с кириллицей
  (TMP SDF-генерация вне скоупа: нужен Unity Editor; TMP_FontAsset
  только детектим и честно отчитываемся в stats).

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
# Naninovel/Fungus/Yarn/I2-полей в ней нет — их хинты не добавляем.
#
# "action" здесь НЕТ намеренно: в RealMono-игре поле actionName — это
# не подпись для игрока, а имя действия Unity Input System (и `m_ActionId`
# / `m_DefaultActionMap` рядом). Перевод таких строк ломает привязку
# ввода — персонаж перестаёт ходить. Идентификаторы перечислены явно в
# _IDENT_FIELDS, а подсказку "action" мы убрали, чтобы следующая игра
# с похожим полем не сломалась тем же образом.
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

# Идентификаторы и привязки ввода. Перевод строки здесь ломает механику,
# а не текст: Unity Input System ищет действие/карту по имени/GUID и молча
# перестаёт реагировать на управление. Имена берём и с префиксом, и без —
# в typetree встречаются оба варианта. Исторический случай: 553 записи
# actionName/m_ActionId/m_DefaultActionMap были переведены, персонаж
# перестал ходить.
_IDENT_FIELDS: frozenset[str] = frozenset({
    "actionName", "m_ActionName",
    "actionMap", "m_ActionMap",
    "m_DefaultActionMap",
    "m_ActionId", "actionId",
    "m_BindingId", "bindingId",
    "m_CompositeBindingId",
    "m_ControlScheme",
    "m_ControlPath", "m_Path",
    "m_AssetName", "assetName",
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
    """Есть ли в JSON-дереве хоть одно «предложение» (текст для игрока).

    «Предложение» = буквы, длина >= 10 и **пробел внутри**. Последнее
    условие добавлено не для красоты: без него за предложение сходили
    строки вида ``com.unity.2d.sprite@1.0.0`` из отчёта сборки Unity —
    JSON-конфиг перестал определяться и его переводили целым блобом.
    """
    stack: list[object] = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            s = node.strip()
            if len(s) >= 10 and _has_letters(s) and " " in s:
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


def _is_table(text: str) -> bool:
    """True — TextAsset это таблица (CSV/TSV), а не цельный текст.

    Почему это критично: ``patch_textasset`` подменяет содержимое
    TextAsset целиком. Для прозы это правильно, а для таблицы — нет:
    перевод одной ячейки затёрёт бы все остальные. В реальной Mono-игре
    100 из 101 TextAsset оказались CSV/TSV (реплики по строкам), и
    замена файла целиком ломала разметку — «текст чутька поломался».

    Признак таблицы: несколько строк, и на большинстве из них
    один и тот же разделитель (``,`` или ``\\t``) встречается одинаковое
    число раз. Считаем доминирующее число разделителей: если оно
    покрывает >= 60% строк и >= 1 — это таблица. Обычный текст с запятыми
    так не ловится (число запятых по строкам разное), а ``a,b\\nc,d`` и
    ``a,b,c\\nd,e,f`` — обе таблицы.
    """
    lines = [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    if len(lines) < 2:
        return False
    for delim in (",", "\t"):
        counts = [ln.count(delim) for ln in lines]
        best, hits = 0, 0
        for c in sorted(set(counts), reverse=True):
            n = counts.count(c)
            if n > hits:
                best, hits = c, n
        if best >= 1 and hits >= max(2, int(len(lines) * 0.6)):
            return True
    return False


#: маркер строки внутри TextAsset: 'm_Script#7' == 7-я строка файла
_TA_LINE = "m_Script#"


def harvest_textasset(name: str, script: str | bytes) -> list[tuple[str, str]]:
    """Текст TextAsset -> [('m_Script#N', строка_N)] — ПОСТРОЧНО.

    Чистая, без UnityPy. ``name`` — только для сигнатуры (в контекст
    его подставляет extract, здесь не используется).

    Почему построчно, а не одним куском: ``patch_textasset`` подменяет
    содержимое TextAsset целиком, и раньше весь файл уходил переводчику
    одной строкой. Переводчик имеет право склеить/потерять/переставить
    строки — и он это делал, из-за чего диалоги «чутька ломались».
    С построчной разбивкой каждый перевод встаёт ровно на своё место,
    а число строк в файле не меняется никогда.

    Пропускаем: пусто/без букв, JSON-конфиги движка, таблицы (CSV/TSV —
    им нужна посекционная правка по колонкам, формат у каждой игры свой).
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
    if _is_table(stripped):
        return []
    out: list[tuple[str, str]] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for idx, line in enumerate(lines):
        s = line.strip()
        if len(s) < 2 or not _has_letters(s):
            continue
        out.append((f"{_TA_LINE}{idx}", s))
    return out


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
                if key in _SKIP_FIELDS or key in _IDENT_FIELDS:
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


def _line_index(field: str) -> int | None:
    """'m_Script#7' -> 7. Не тот формат или мусор -> None."""
    if not isinstance(field, str) or not field.startswith(_TA_LINE):
        return None
    tail = field[len(_TA_LINE):]
    if not tail.isdigit():
        return None
    return int(tail)


def _split_lines(raw: str | bytes) -> list[str]:
    """Строки TextAsset. Перевод строки сохраняет исходный вариант."""
    text = _decode_text(raw) if isinstance(raw, bytes) else raw
    if not isinstance(text, str):
        return []
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def patch_textasset_lines(
    script: str | bytes,
    by_index: dict[int, str],
) -> str | bytes:
    """Новый m_Script с заменёнными строками по индексам. Чистая.

    Меняются ТОЛЬКО перечисленные номера строк; остальные остаются
    байт в байт, включая пустые строки и отступы. Число строк не меняется
    никогда — разбивка на строки это главное, что держит диалог живым
    после перевода. Без совпадений — исходник без изменений.
    """
    if not by_index:
        return script
    text = _decode_text(script)
    if text is None:
        return script
    newline = "\r\n" if "\r\n" in text else ("\r" if "\r" in text else "\n")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    changed = False
    for idx, new_text in by_index.items():
        if isinstance(new_text, str) and 0 <= idx < len(lines):
            if lines[idx] != new_text:
                lines[idx] = new_text
                changed = True
    if not changed:
        return script
    out = newline.join(lines)
    if isinstance(script, bytes):
        try:
            return out.encode("utf-8")
        except Exception:
            return script
    return out


def patch_textasset(
    script: str | bytes,
    translations: dict[str, str] | list[tuple[str, str]],
) -> str | bytes:
    """Совместимость: старая точка входа (цельная подмена m_Script).

    ``translations`` — dict {field: new} или [(field, new)] (ищется
    'm_Script'); без совпадения — исходник без изменений (тип сохранён).
    Новая разметка ('m_Script#N') сюда не попадает — её обрабатывает
    patch_textasset_lines: построчно, иначе диалог ломается.
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


# ── StreamingAssets (текстовые файлы, без UnityPy) ──────────────────────────

# Текстовые суффиксы StreamingAssets (только по имени, без чтения).
_STREAMING_SUFFIXES = (".json", ".csv", ".txt")

# Шрифт из комплекта репозитория (Noto Sans заведомо с кириллицей;
# проверить cmap нечем — fontTools в окружении нет, честная оговорка).
_BUNDLED_FONT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "fonts", "NotoSans-Regular.ttf")

# Сигнатуры TTF/OTF: шрифт обязан начинаться с одной из них.
_TTF_MAGICS = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1")


def iter_streaming_text_files(game_dir: str) -> list[str]:
    """Отн. пути текстовых файлов из *_Data/StreamingAssets (sort)."""
    out: list[str] = []
    for ddir in _data_dirs(game_dir):
        sdir = os.path.join(ddir, "StreamingAssets")
        for root, _dirs, files in os.walk(sdir):
            for name in files:
                if name.lower().endswith(_STREAMING_SUFFIXES):
                    full = os.path.join(root, name)
                    try:
                        if os.path.isfile(full):
                            out.append(os.path.relpath(full, game_dir)
                                       .replace(os.sep, "/"))
                    except OSError:
                        continue
    return sorted(out)


def harvest_streaming_text(
    name: str, text: str | bytes,
) -> list[tuple[str, str]]:
    """Весь текстовый файл -> [('content', text)] или [].

    Те же гарды, что у TextAsset: пусто/без букв/JSON-конфиг — пропуск.
    ``name`` — только для сигнатуры (в контекст его подставляет extract).
    """
    _ = name
    decoded = _decode_text(text)
    if decoded is None:
        return []
    stripped = decoded.strip()
    if len(stripped) < 2 or not _has_letters(stripped):
        return []
    if _is_json_config(stripped):
        return []
    return [("content", stripped)]


# Кэш typetree-генераторов: {(game_dir, version): gen}. Загрузка Managed
# в холодную может занять десятки секунд — один раз на игру за сессию,
# дальше переиспользуем (иначе 58с на КАЖДЫЙ файл extract/apply).
_TTGEN_CACHE: dict[tuple[str, str], object] = {}


def _close_env(env) -> None:
    """Закрыть файловые ручки env (поток исходного ассета).

    UnityPy.load(path) держит исходник открытым; на Windows открытая
    ручка роняет os.replace с WinError 5. Закрываем детерминированно
    перед atomic_write_bytes (загрузка из байтов — НЕ вариант: через
    неё ломается разбор скриптовых полей MonoBehaviour).

    Важно: в UnityPy 1.25.3 у ассета нет ``reader.stream`` — поток лежит
    сразу в ``asset.stream`` (fsspec LocalFileOpener). Поэтому перебираем
    все разумные места, иначе _close_env молча ничего не делает и ручка
    течёт на каждой открытой ассете (14+ на проекте).
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
        # поток может быть в самом ассете, в его ``reader`` или вложенно
        holders = [asset, getattr(asset, "reader", None)]
        for holder in holders:
            if holder is None:
                continue
            for attr in ("stream", "f", "file", "_file", "closable"):
                stream = getattr(holder, attr, None)
                closer = getattr(stream, "close", None)
                if not callable(closer):
                    continue
                try:
                    if not getattr(stream, "closed", False):
                        closer()
                except Exception:
                    pass

# ── UnityPy-слой (ленивый импорт) ──────────────────────────────────────────

# Диагностика последнего extract для UI (копия stat): диалог извлечения
# показывает typetree-статус, иначе молчаливый 101 вместо 6400.
LAST_STATS: dict = {}

# TextMeshProUGUI/TextMeshPro — скриптовые компоненты (в части сборок
# приходят отдельными типами, не MonoBehaviour): поле m_text (строчное).
_TMP_TYPES = frozenset({"TextMeshProUGUI", "TextMeshPro"})

_TEXT_TYPES = frozenset(
    {"TextAsset", "MonoBehaviour", "TextMesh", "GUIText"}) | _TMP_TYPES


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
    """Строки TextAsset/MonoBehaviour/TextMesh/GUIText/TMP + StreamingAssets -> TranslationEntry.

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
            "typetree": "off", "fonts": 0, "tmp_fonts": 0, "streaming": 0}
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
                if str(type_name) == "Font":
                    stat["fonts"] += 1
                elif str(type_name) == "TMP_FontAsset":
                    # SDF-шрифты TextMeshPro генерируются только в Unity
                    # Editor — детектим и честно отчитываемся, не патчим.
                    stat["tmp_fonts"] += 1
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
                    elif type_name in _TMP_TYPES:
                        # TextMeshProUGUI / TextMeshPro: поле m_text
                        # (строчное; в patch обязано совпасть по регистру).
                        raw = tree.get("m_text", None)
                        text = _decode_text(raw) if raw is not None else None
                        if text is not None:
                            stripped = text.strip()
                            if len(stripped) >= 2 \
                                    and _has_letters(stripped):
                                pairs = [("m_text", stripped)]
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
    for rel in iter_streaming_text_files(game_dir):
        abs_path = os.path.join(game_dir, *rel.split("/"))
        if not os.path.isfile(abs_path):
            continue
        try:
            with open(abs_path, "rb") as f:
                raw = f.read()
        except OSError:
            continue
        basename = rel.rsplit("/", 1)[-1]
        for field, original in harvest_streaming_text(basename, raw):
            json_path = f"asset://{basename}/streaming/{field}"
            key = (rel, json_path)
            if key in seen:
                continue
            seen.add(key)
            entries.append(TranslationEntry(
                id=next_id, file=rel, json_path=json_path,
                context=f"Streaming:{basename}", original=original))
            next_id += 1
            stat["streaming"] += 1
    if stats is not None:
        stats.update(stat)
        stats["entries"] = len(entries)
    LAST_STATS.clear()
    LAST_STATS.update(stat)
    LAST_STATS["entries"] = len(entries)
    return entries


def _apply_streaming_file(
    game_dir: str,
    rel: str,
    items: list,
    stats: dict,
    backup: bool,
    backup_root: str | None,
) -> None:
    """Прямая замена всего содержимого текстового файла (без UnityPy).

    Тот же паттерн, что у ассетов: сверка с оригиналом, BackupStore,
    atomic_write_bytes, verify перечитыванием. Статистика — в stats.
    """
    abs_path = os.path.join(game_dir, *rel.split("/"))
    if not os.path.isfile(abs_path):
        _skip(stats, "streaming-missing-file", len(items))
        return
    try:
        with open(abs_path, "rb") as f:
            current = f.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        _skip(stats, "streaming-unreadable", len(items))
        return
    applied = 0
    for entry in items:
        try:
            if isinstance(entry, dict):
                trans = str(entry.get("translation", ""))
                orig = entry.get("original", "")
            else:
                trans = str(getattr(entry, "translation", ""))
                orig = getattr(entry, "original", "")
        except Exception:
            _skip(stats, "bad-entry", 1)
            continue
        if not trans.strip():
            _skip(stats, "no-translation", 1)
            continue
        orig_s = orig if isinstance(orig, str) else ""
        if current != orig_s and current.strip() != orig_s.strip():
            _skip(stats, "changed", 1)
            continue
        current = trans
        applied += 1
    if not applied:
        return
    if backup:
        try:
            from app.core.io import BackupStore

            bdir = backup_root or os.path.join(
                game_dir, "backup", "unity")
            saved = BackupStore(bdir).backup(abs_path)
            if saved:
                stats["backups"].append(saved)
        except Exception:
            pass
    try:
        from app.core.io import atomic_write_bytes

        atomic_write_bytes(abs_path, current.encode("utf-8"))
        try:
            with open(abs_path, "rb") as f:
                check = f.read().decode("utf-8")
            if check == current:
                stats["verified"] += 1
            else:
                _verify_fail(stats, rel)
        except (OSError, UnicodeDecodeError):
            _verify_fail(stats, rel)
        stats["files"] += 1
        stats["strings"] += applied
    except Exception as e:
        _skip(stats, "write-failed", applied)
        _problem(stats, f"{rel}: {type(e).__name__}")


def _verify_fail(stats: dict, rel: str) -> None:
    """Verify не сошёлся: список строк (контракт), не счётчик."""
    stats.setdefault("verify_failed", []).append(rel)
    _problem(stats, f"{rel}: не совпало после записи")


def _problem(stats: dict, text: str) -> None:
    """Причина пропуска/сбоя для показа пользователю (без текста игры)."""
    problems = stats.setdefault("problems", [])
    if len(problems) < 20 and text not in problems:
        problems.append(text)


def _skip(stats: dict, reason: str, count: int = 1) -> None:
    """Засчитать пропуск с причиной (контракт ApplyReport).

    Молчаливые пропуски — главная причина жалоб «перевод не применился»:
    UI обязан показать, ЧТО и ПОЧЕМУ пропущено.
    """
    if count <= 0:
        return
    stats["skipped"] = stats.get("skipped", 0) + count
    by = stats.setdefault("skipped_by", {})
    by[reason] = by.get(reason, 0) + count


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
    ('asset://<file>/<path_id>/<field>'; StreamingAssets — по маркеру
    '/streaming/' прямой перезаписью файла), сверка с оригиналом,
    пропуск при расхождении. target_lang записывается в stats.
    Без UnityPy -> {'files': 0, 'strings': 0, 'skipped': 'no-unitypy'}.
    Пустой вход (с UnityPy) -> {'files': 0} (совместимость заглушки).
    """
    _ = kwargs
    UnityPy = _try_import_unitypy()
    if UnityPy is None:
        return {"files": 0, "strings": 0, "skipped_total": 0,
                "skipped_by": {"no-unitypy": 1}, "verify_failed": [],
                "backups": [], "verify_restored": True,
                "target_lang": target_lang}
    _force_pure_python_reader()
    if not entries:
        return {"files": 0, "strings": 0, "skipped_total": 0,
                "skipped_by": {}, "verify_failed": [],
                "backups": [], "verify_restored": True,
                "target_lang": target_lang}
    # группировка по файлу (поддержка TranslationEntry и dict)
    by_file: dict[str, list] = {}
    no_translation = 0
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
            no_translation += 1
            continue
        by_file.setdefault(file, []).append(entry)
    # Контракт ApplyReport (app/engines/protocol.py): skipped_total +
    # skipped_by(причины) + verify_failed СПИСОК строк. UI обязан показать
    # пропуски, иначе «применил — в игре пусто» остаётся без объяснения.
    stats: dict = {"files": 0, "strings": 0, "skipped": 0,
                   "skipped_by": {}, "backups": [], "verified": 0,
                   "verify_failed": [], "verify_restored": True,
                   "problems": [], "target_lang": target_lang}
    if no_translation:
        _skip(stats, "no-translation", no_translation)
    for rel, items in by_file.items():
        stream_items: list = []
        asset_items: list = []
        for entry in items:
            try:
                jp = entry.get("json_path", "") \
                    if isinstance(entry, dict) \
                    else str(getattr(entry, "json_path", ""))
            except Exception:
                _skip(stats, "bad-json-path", 1)
                continue
            if "/streaming/" in jp:
                stream_items.append(entry)
            else:
                asset_items.append(entry)
        if stream_items:
            _apply_streaming_file(game_dir, rel, stream_items, stats,
                                  backup, backup_root)
        if not asset_items:
            continue
        items = asset_items
        abs_path = os.path.join(game_dir, *rel.split("/"))
        if not os.path.isfile(abs_path):
            _skip(stats, "missing-file", len(items))
            continue
        try:
            if os.path.getsize(abs_path) < 128:
                _skip(stats, "tiny-file", len(items))
                continue
        except OSError:
            _skip(stats, "stat-failed", len(items))
            continue
        # Путь, НЕ байты: load(bytes) ломает разбор скриптовых полей
        # MonoBehaviour. Ручки закрываем _close_env перед записью.
        try:
            env = UnityPy.load(abs_path)
        except Exception as e:
            _skip(stats, "load-failed", len(items))
            _problem(stats, f"{rel}: {type(e).__name__}")
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
            _skip(stats, "unreadable", len(items))
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
                _skip(stats, "bad-entry", 1)
                continue
            parsed = _parse_json_path(jp)
            if parsed is None:
                _skip(stats, "bad-json-path", 1)
                continue
            _fpart, pid, field = parsed
            if not trans.strip():
                _skip(stats, "no-translation", 1)
                continue
            grouped.setdefault(pid, []).append((field, trans, orig))
        file_written = 0
        for pid, lst in grouped.items():
            obj = pid_to_obj.get(pid)
            tname = pid_to_type.get(pid, "?")
            if obj is None:
                _skip(stats, "object-missing", len(lst))
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
                    _skip(stats, "typetree-failed", len(lst))
                    continue
            if tree is None:
                _skip(stats, "typetree-empty", len(lst))
                continue
            if tname == "MonoBehaviour" and not strict_ok:
                # скриптовые поля без генератора недоступны — не портим
                _skip(stats, "no-script-fields", len(lst))
                continue
            # сверка оригиналов + отбор к применению
            to_apply: list[tuple[str, str]] = []
            # 'm_Script#N' — построчные правки TextAsset: идут отдельной
            # веткой, потому что _get_path_value работает с деревом, а
            # здесь индекс строки внутри обычной строки.
            line_edits: dict[int, tuple[str, str]] = {}
            for field, trans, orig in lst:
                if field.startswith(_TA_LINE):
                    idx = _line_index(field)
                    if idx is None:
                        _skip(stats, "bad-json-path", 1)
                        continue
                    line_edits[idx] = (trans, orig)
                    continue
                cur = _get_path_value(tree, field)
                if cur is None:
                    # TextAsset m_Script может лежать как bytes/str —
                    # _get_path_value уже декодирует; None = нет поля
                    _skip(stats, "field-missing", 1)
                    continue
                orig_s = orig if isinstance(orig, str) else ""
                if cur != orig_s and cur.strip() != orig_s.strip():
                    _skip(stats, "changed", 1)
                    continue
                to_apply.append((field, trans))
            if not to_apply and not line_edits:
                continue
            if tname == "TextAsset" and line_edits:
                # строчные: сверить оригинал и заменить только свои номера
                raw = tree.get("m_Script", "")
                lines = _split_lines(raw)
                ok_lines: dict[int, str] = {}
                for idx, (trans, orig) in line_edits.items():
                    if not isinstance(orig, str) or idx < 0 \
                            or idx >= len(lines) or not trans.strip():
                        _skip(stats, "field-missing", 1)
                        continue
                    cur_line = lines[idx].strip()
                    if cur_line != orig and cur_line != orig.strip():
                        _skip(stats, "changed", 1)
                        continue
                    ok_lines[idx] = trans
                if ok_lines:
                    new_script = patch_textasset_lines(raw, ok_lines)
                    if new_script == raw:
                        _skip(stats, "patch-failed", len(ok_lines))
                        continue
                    tree["m_Script"] = new_script
                    file_written += len(ok_lines)
                    if not to_apply:
                        try:
                            obj.patch(tree)  # type: ignore[attr-defined]
                        except Exception:
                            file_written -= len(ok_lines)
                            _skip(stats, "patch-failed", len(ok_lines))
                            continue
            try:
                if tname == "TextAsset" and to_apply:
                    mapping = dict(to_apply)
                    new_script = patch_textasset(
                        tree.get("m_Script", ""), mapping)
                    if new_script == tree.get("m_Script", ""):
                        continue
                    tree["m_Script"] = new_script
                    obj.patch(tree)  # type: ignore[attr-defined]
                    file_written += len(to_apply)
                elif tname in ("TextMesh", "GUIText",
                                "TextMeshProUGUI", "TextMeshPro"):
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
                    _skip(stats, "type-unsupported", len(to_apply))
            except Exception:
                _skip(stats, "patch-failed", len(to_apply))
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

            target_norm = os.path.normcase(os.path.normpath(os.path.abspath(abs_path)))
            # target asset by normalized path: UnityPy lazily pulls dependencies into env.files, do not rewrite them
            candidates = []
            for _ck, _ca in list(getattr(env, 'files', {}).items()):
                try:
                    _cn = os.path.normcase(os.path.normpath(os.path.abspath(str(_ck))))
                except Exception:
                    continue
                if _cn == target_norm:
                    candidates.append((_ck, _ca))
            if not candidates:
                # legacy single-file fallback: single entry with non-matching key, save it, multiple mismatches stay skipped
                if len(getattr(env, 'files', {})) == 1:
                    candidates = list(getattr(env, 'files', {}).items())
            for _ak, asset in candidates:
                save = getattr(asset, 'save', None)
                if not callable(save):
                    continue
                raw = save()
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                data = bytes(raw)
                break
            if data is None:
                _skip(stats, "save-failed", file_written)
                _problem(stats, f"{rel}: не удалось сохранить асет")
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
                _verify_fail(stats, rel)
            stats["files"] += 1
            stats["strings"] += file_written
        except Exception as e:
            _skip(stats, "write-failed", file_written)
            _problem(stats, f"{rel}: {type(e).__name__}")
            continue
    # Контракт ApplyReport: UI читает skipped_total/skipped_by, а не skipped.
    stats["skipped_total"] = stats["skipped"]
    return stats


def font_patch(
    game_dir: str,
    ttf_path: str | None = None,
    backup: bool = True,
    backup_root: str | None = None,
) -> dict:
    """Замена m_FontData классических Font на TTF с кириллицей.

    По умолчанию — комплектный NotoSans-Regular.ttf из
    app/core/assets/fonts. Паттерн как у apply(): BackupStore до записи,
    atomic_write_bytes, verify переоткрытием из байтов. Один список байт
    шрифта переиспользуется между объектами (копий на объект не делаем —
    9-МБ TTF в десятках копий съел бы сотни мегабайт RAM).

    TMP SDF-генерация вне скоупа (нужен Unity Editor): объекты
    TMP_FontAsset только считаем в stats['tmp_fonts'].
    Без UnityPy -> {'patched': False, 'reason': 'no-unitypy'}.
    """
    UnityPy = _try_import_unitypy()
    if UnityPy is None:
        return {"patched": False, "fonts": 0, "files": 0,
                "reason": "no-unitypy"}
    src = ttf_path or _BUNDLED_FONT
    try:
        with open(src, "rb") as f:
            blob = f.read()
    except OSError:
        return {"patched": False, "fonts": 0, "files": 0,
                "reason": "no-ttf"}
    if len(blob) < 128 or bytes(blob[:4]) not in _TTF_MAGICS:
        return {"patched": False, "fonts": 0, "files": 0,
                "reason": "bad-ttf"}
    font_blob = list(blob)
    _force_pure_python_reader()
    stats: dict = {"patched": False, "fonts": 0, "files": 0, "strings": 0,
                   "skipped": 0, "backups": [], "verified": 0,
                   "verify_failed": 0, "tmp_fonts": 0, "names": [],
                   "dynamic_neutralized": 0, "reason": "no-fonts"}
    for rel in _candidate_files(game_dir):
        abs_path = os.path.join(game_dir, *rel.split("/"))
        if not os.path.isfile(abs_path):
            continue
        try:
            if os.path.getsize(abs_path) < 128:
                continue
        except OSError:
            continue
        try:
            env = UnityPy.load(abs_path)
        except Exception:
            continue
        try:
            pid_to_obj: dict[int, object] = {}
            for _ak, asset in list(getattr(env, "files", {}).items()):
                objects = getattr(asset, "objects", None)
                if not objects:
                    continue
                vals = objects.values() \
                    if isinstance(objects, dict) else objects
                for obj in list(vals):
                    try:
                        tname = str(getattr(obj.type, "name", "?"))
                    except Exception:
                        continue
                    if tname == "TMP_FontAsset":
                        stats["tmp_fonts"] += 1
                    elif tname == "Font":
                        try:
                            pid = int(getattr(obj, "path_id", -1))
                        except Exception:
                            continue
                        pid_to_obj[pid] = obj
            if not pid_to_obj:
                continue
            patched_here = 0
            for _pid, obj in pid_to_obj.items():
                try:
                    tree = obj.parse_as_dict()  # type: ignore[attr-defined]
                    if not isinstance(tree, dict):
                        tree = obj.parse_as_dict(  # type: ignore[attr-defined]
                            check_read=False)
                except Exception:
                    try:
                        tree = obj.parse_as_dict(  # type: ignore[attr-defined]
                            check_read=False)
                    except Exception:
                        stats["skipped"] += 1
                        continue
                if not isinstance(tree, dict) or "m_FontData" not in tree:
                    stats["skipped"] += 1
                    continue
                try:
                    tree["m_FontData"] = font_blob
                    # Динамический OS-шрифт Unity игнорирует m_FontData:
                    # он берёт системный файл по имени из m_FontNames.
                    # Пустой список делает шрифт статическим — тогда
                    # текст рисуется из внедрённых данных и кириллица
                    # видна (иначе после перевода пустые квадраты).
                    names = tree.get("m_FontNames")
                    if isinstance(names, list) and names:
                        tree["m_FontNames"] = []
                        stats["dynamic_neutralized"] += 1
                    obj.patch(tree)  # type: ignore[attr-defined]
                    patched_here += 1
                    name = tree.get("m_Name", "")
                    if isinstance(name, str) and name:
                        stats["names"].append(name)
                except Exception:
                    stats["skipped"] += 1
                    continue
            stats["fonts"] += len(pid_to_obj)
            if patched_here <= 0:
                continue
            if backup:
                try:
                    from app.core.io import BackupStore

                    bdir = backup_root or os.path.join(
                        game_dir, "backup", "unity")
                    saved = BackupStore(bdir).backup(abs_path)
                    if saved:
                        stats["backups"].append(saved)
                except Exception:
                    pass
            data: bytes | None = None
            try:
                from app.core.io import atomic_write_bytes

                target_norm = os.path.normcase(os.path.normpath(os.path.abspath(abs_path)))
                # target asset by normalized path: UnityPy lazily pulls dependencies into env.files, do not rewrite them
                candidates = []
                for _ck, _ca in list(getattr(env, 'files', {}).items()):
                    try:
                        _cn = os.path.normcase(os.path.normpath(os.path.abspath(str(_ck))))
                    except Exception:
                        continue
                    if _cn == target_norm:
                        candidates.append((_ck, _ca))
                if not candidates:
                    # legacy single-file fallback: single entry with non-matching key, save it, multiple mismatches stay skipped
                    if len(getattr(env, 'files', {})) == 1:
                        candidates = list(getattr(env, 'files', {}).items())
                for _ak, asset in candidates:
                    save = getattr(asset, 'save', None)
                    if not callable(save):
                        continue
                    raw = save()
                    if not isinstance(raw, (bytes, bytearray)):
                        continue
                    data = bytes(raw)
                    break
                if data is None:
                    stats["skipped"] += patched_here
                    continue
                _close_env(env)
                atomic_write_bytes(abs_path, data)
                try:
                    check_env = UnityPy.load(bytes(data))
                    _ = getattr(check_env, "files", {})
                    stats["verified"] += 1
                except Exception:
                    stats["verify_failed"] += 1
                stats["files"] += 1
                stats["strings"] += patched_here
            except Exception:
                stats["skipped"] += patched_here
                continue
        finally:
            try:
                _close_env(env)
            except Exception:
                pass
    if stats["files"]:
        stats["patched"] = True
        stats["reason"] = "ok"
    return stats


def is_patched(game_dir: str) -> bool:
    """Есть ли бэкапы font_patch (для показа кнопки «Восстановить»)."""
    try:
        from app.core.io import BackupStore

        store = BackupStore(os.path.join(game_dir, "backup", "unity"))
        return bool(store.manifest_files())
    except Exception:
        return False


# -*- coding: utf-8 -*-
"""Модуль RPG Maker MV/MZ — извлечение, внедрение, подключение.

Один модуль на обе формы игры:
- обычная: data/*.json, img/, js/ лежат прямо в папке игры;
- Electron: всё упаковано в resources/app.asar — файлы читаются лениво
  через AsarFileView, переводы пишутся в архив «на месте» (пересборка
  только если файл вырос), вкладки карт/ресурсов/читов работают по тем же
  относительным путям.

Весь функционал RPG Maker хранится в этой папке:
- parser: извлечение/внедрение текста в data/*.json
- asar: детект Electron-игр (resources/app.asar)
- crypto: расшифровка ресурсов
- fontpatch: замена шрифта на кириллический
- varnames: имена переменных/переключателей
- maprender: данные для карт
- tentacle: CDP-подключение к живой игре
"""
from __future__ import annotations

import os
import re
from collections import Counter

from app.core.io import atomic_write_bytes
from app.core.rpgmaker.fileview import AsarFileView, DiskFileView, FileView
from app.engines.base import EngineModule

_FEATURES = {"files", "cheats", "resources", "maps"}
_FEATURES_FONT = {"files", "cheats", "resources", "font", "maps"}

# Причины пропусков parser.apply -> короткие метки для отчёта.
# Порядок важен: конкретные префиксы раньше общих.
_SKIP_BUCKETS = (
    ("path not found", "path"),
    ("cannot write", "write"),
    ("param value not found", "param-missing"),
    ("not in plugin", "param-missing"),
    ("not in list", "plugin-missing"),
    ("plugins list", "plugins-list"),
    ("slot changed or key protected", "changed"),
    ("title tag", "title"),
    ("current value is not a string", "type"),
)


def _bucket_skip(reason: object) -> str:
    text = str(reason or "")
    for needle, label in _SKIP_BUCKETS:
        if needle in text:
            return label
    return "other"


class RpgMakerModule(EngineModule):
    key = "rpgmaker"
    title = "RPG Maker"
    maturity = "stable"

    @property
    def features(self) -> set[str]:
        # замена шрифта (js/rmmz_core + fonts внутри архива) — только для
        # обычных игр; у Electron-версии кнопка скрыта
        return _FEATURES if self._asar else _FEATURES_FONT

    @classmethod
    def detect(cls, game_dir: str) -> int:
        from . import asar
        from . import parser
        variant = asar.detect_variant(game_dir)
        if variant:
            return {"mz": 110, "mv": 100}.get(variant, 0)
        engine = parser.detect_engine(game_dir)
        if engine == "mz":
            return 100
        if engine == "mv":
            return 90
        return 0

    def __init__(self, game_dir: str):
        from . import asar
        from . import parser
        self._asar = bool(asar.detect_variant(game_dir))
        self.variant = (asar.detect_variant(game_dir)
                        if self._asar else parser.detect_engine(game_dir))
        self._views: dict[str, FileView] = {}

    @property
    def display(self) -> str:
        suffix = " (Electron)" if self._asar else ""
        return f"RPG Maker {self.variant.upper()}{suffix}"

    def file_view(self, game_dir: str) -> FileView:
        """Файловый доступ для вкладок: диск или ленивый asar.

        View кэшируется на время сессии: AsarFileView перечитывает заголовок
        архива при каждом создании, а это может быть несколько мегабайт JSON.
        """
        view = self._views.get(game_dir)
        if view is None:
            if self._asar:
                from . import asar as asarlib
                view = AsarFileView(
                    asarlib.asar_path(game_dir),
                    backup_dir=os.path.join(game_dir, "backup", "maps"))
            else:
                view = DiskFileView(game_dir)
            self._views[game_dir] = view
        return view

    def extract(self, game_dir: str) -> list:
        from . import parser
        if self._asar:
            return self._extract_asar(game_dir)
        return parser.extract(game_dir, variant=self.variant)

    def _extract_asar(self, game_dir: str) -> list:
        from .asar import _temp_project
        from . import parser
        with _temp_project(game_dir) as proj:
            return parser.extract(proj, variant=self.variant)

    def apply(self, game_dir: str, entries: list, **kwargs) -> dict:
        try:
            return self._apply_impl(game_dir, entries, **kwargs)
        except Exception:
            try:
                self.restore_original(game_dir)
            except Exception:  # noqa: BLE001
                pass
            raise

    def _apply_impl(self, game_dir: str, entries: list, **kwargs) -> dict:
        """Гибридный механизм: runtime-overlay для данных + live + точечный file-patch.

        - `data/*.json`, `Map*.json` (включая .rpgmvm) — только runtime-overlay
          (`ob_translation/<lang>.json` + `js/plugins/ob_runtime.js`), файлы
          игры не трогаем → не ломается на любых играх/плагинах.
        - `js/plugins/*.js` (исходники плагинов) — по умолчанию НЕ патчим
          файлом: замена литералов по содержимому ломает синтаксис
          (кавычки/переносы) и логику (один литерал — и текст, и ключ),
          игра после такого патча не стартует. Эти строки идут в тот же
          runtime-словарь и переводятся live через catch-all хуки
          (drawText/drawTextEx/convertEscapeCharacters) без touching файлов.
          Рискованный file-patch доступен только явно:
          ``patch_plugin_js=True`` (не для asar).
        - VALUES параметров `plugins.js` (`#plugparam:`) — file-patch
          (JSON-данные, не код): плагины кэшируют
          PluginManager.parameters() при загрузке, поздний runtime-обход
          их не догонит (меню/титулы MOG и т.п.). Патч валидируется перед
          записью, с бэкапом. Для asar — без репака: только live.
        - `www`-деплой, Electron/asar, шифрованные карты — overlay + live
          (CDP/мост) без модификации архива.
        - Читы (PAYLOAD, ES5) — отдельно через CDP (MZ) или `octopus_ob.js` (MV).
        - После всех записей — verify_boot_files строгим парсером (глазами
          V8): при провале всё наше откатывается и в stats кладётся
          verify_failed/verify_restored вместо молчаливого «готово».

        Максимальное извлечение (generic + DB + events + plugins) сохранено,
        но с защитой: пути к файлам, `true/false/null`, note/meta, команды
        `356` с кодом не извлекаются (см. parser._generic_text, mask);
        строки, совпадающие с ресурсами игры (audio/img/movies), —
        ссылки на файлы и не переводятся никогда (resrefs).
        """
        from app.core.rpgmaker import runtime as rt
        # мигрируем legacy file-патч если он был: откатываем один раз
        # чтобы не оставлять игру в поломанном состоянии
        try:
            from app.core.rpgmaker import parser as parser_mod
            bak = os.path.join(game_dir, "backup")
            if not self._asar and os.path.isdir(bak):
                # есть бэкапы data/*.json — откатываем их
                parser_mod.restore_original(game_dir)
        except Exception:  # noqa: BLE001
            pass

        target_lang = kwargs.get("target_lang", "ru")
        patch_plugin_js = bool(kwargs.get("patch_plugin_js", False))

        # Индекс ресурсов: строки, совпадающие с файлами audio/img/movies,
        # — это ссылки, а не текст. Их перевод даёт "Failed to load",
        # поэтому такие записи не идут ни в file-patch, ни в словарь.
        try:
            from app.core.rpgmaker import resrefs
            resrefs.clear_index(game_dir)
            res = resrefs.build_index(game_dir)
        except Exception:  # noqa: BLE001
            res = None

        def _is_res_entry(e) -> bool:
            if not res:
                return False
            # заголовок окна — всегда текст для показа (файлом-ресурсом
            # быть не может, подмена безопасна везде)
            f = getattr(e, "file", "") if not isinstance(e, dict) else e.get("file", "")
            if f == "package.json" or f.lower().endswith((".html", ".htm")):
                return False
            o = getattr(e, "original", "") if not isinstance(e, dict) else e.get("original", "")
            return resrefs.is_resource_name(res, o or "")

        # ——— разделение: runtime (безопасно) vs file-patch (точечно) ———
        # file-путь в entry.file — относительный ("data/Actors.json" или
        # "js/plugins/YEP_Core.js"). Важно: "js/plugins.js" (список) —
        # НЕ путать с "js/plugins/" (каталог исходников).
        def _is_plugin_js(e) -> bool:
            f = getattr(e, "file", "") if not isinstance(e, dict) else e.get("file", "")
            return "js/plugins/" in f

        def _is_plugin_param(e) -> bool:
            p = getattr(e, "json_path", "") if not isinstance(e, dict) else e.get("json_path", "")
            return "#plugparam:" in p

        def _is_translatable(e) -> bool:
            t = getattr(e, "translation", "") if not isinstance(e, dict) else e.get("translation", "")
            s = getattr(e, "status", "") if not isinstance(e, dict) else e.get("status", "")
            o = getattr(e, "original", "") if not isinstance(e, dict) else e.get("original", "")
            return bool(o and t and t.strip() and s != "skip")

        plugin_entries = [e for e in entries if _is_plugin_js(e) and _is_translatable(e)]
        param_entries = [e for e in entries if _is_plugin_param(e) and _is_translatable(e)]
        json_entries = [e for e in entries
                        if not _is_plugin_js(e) and not _is_plugin_param(e)]

        # ссылки на ресурсы — вон из всех путей подмены (и старые проекты,
        # где они уже извлечены, тоже чистятся здесь)
        res_skipped = 0
        if res:
            def _keep(lst):
                nonlocal res_skipped
                out = []
                for e in lst:
                    if _is_res_entry(e):
                        res_skipped += 1
                    else:
                        out.append(e)
                return out
            plugin_entries, param_entries, json_entries = (
                _keep(plugin_entries), _keep(param_entries), _keep(json_entries))

        # js/plugins-литералы — в runtime-словарь (live catch-all),
        # а не в file-patch: безопасно и покрывает asar/шифрованные сборки.
        runtime_entries = list(json_entries) + list(plugin_entries)
        # params для asar тоже только в live (репак архива ради меню —
        # риск сломать запуск; live-хук PluginManager.parameters покрывает
        # ленивые чтения).
        if self._asar:
            runtime_entries = runtime_entries + list(param_entries)
            param_entries = []

        stats: dict = {"files": 0, "strings": 0, "runtime": False, "backups": [],
                       "res_skipped": res_skipped}
        # учёт пропусков file-patch для отчёта («пропущено N: ...»)
        skip_counter: Counter = Counter()
        if res_skipped:
            skip_counter["resources"] = res_skipped

        def _on_skip(entry, reason) -> None:
            skip_counter[_bucket_skip(reason)] += 1

        # 1) file-patch ТОЛЬКО для VALUES параметров plugins.js (диск)
        # и опционально для js/plugins/*.js (patch_plugin_js=True).
        # Порядок важен: СНАЧАЛА file-patch (бэкап plugins.js — оригинал),
        # ПОТОМ runtime (добавляет запись ob_runtime). Иначе бэкап
        # plugins.js снимется уже с ob_runtime и restore его воскресит.
        file_entries = list(param_entries)
        if patch_plugin_js and not self._asar:
            file_entries = file_entries + list(plugin_entries)
            # при явном file-patch плагинов — не дублируем их в runtime,
            # чтобы не было двойного перевода (file + live идемпотентны,
            # но словарь меньше — чище)
            runtime_entries = list(json_entries)
        if file_entries:
            if self._asar:
                # Electron: архив не репакаем ради перевода — только live.
                # Сюда попадаем только при patch_plugin_js (params уже
                # ушли в runtime выше), на всякий случай — no-op.
                pass
            else:
                from . import parser
                p_stats = parser.apply(
                    game_dir, file_entries, target_lang=target_lang, res=res,
                    on_skip=_on_skip)
                stats["files"] = stats.get("files", 0) + p_stats.get("files", 0)
                stats["strings"] = stats.get("strings", 0) + p_stats.get("strings", 0)
                if p_stats.get("backups"):
                    stats["backups"] = stats.get("backups", []) + p_stats["backups"]
                stats["plugin_files"] = p_stats.get("files", 0)
                stats["plugin_strings"] = p_stats.get("strings", 0)

        if skip_counter:
            stats["skipped_total"] = sum(skip_counter.values())
            stats["skipped_by"] = dict(skip_counter.most_common(5))

        # 2) runtime-overlay для JSON-данных + текстов плагинов (live catch-all)
        # (включая зашифрованные Map*.rpgmvm — файлы не трогаем)
        if any(_is_translatable(e) for e in runtime_entries):
            rt_stats = rt.install_runtime(game_dir, runtime_entries, target_lang=target_lang)
            # rt(files=1) + file-patch(files=N) — суммируем, runtime-флаг важнее
            rt_files = rt_stats.get("files", 0)
            rt_strings = rt_stats.get("strings", 0)
            for k, v in rt_stats.items():
                if k not in ("files", "strings"):
                    stats[k] = v
            stats["files"] = stats.get("files", 0) + rt_files
            stats["strings"] = stats.get("strings", 0) + rt_strings
        else:
            # нет JSON-переводов — runtime не нужен (только плагины)
            if not stats.get("runtime"):
                stats["runtime"] = False

        # 3) MV: мост для читов/live (всегда, даже если нет переводов — нужен для читов)
        if self.variant == "mv":
            from app.core.rpgmaker import mv_bridge
            from app.core.rpgmaker.payloads import (
                PAYLOAD, _TRANSLATION_PAYLOAD)
            if not mv_bridge.ensure_bridge_registered(
                    game_dir, PAYLOAD, _TRANSLATION_PAYLOAD):
                raise RuntimeError("не удалось зарегистрировать MV-мост")
            live_entries = [e for e in runtime_entries
                            if _is_translatable(e)]
            if live_entries and not mv_bridge.update_tr_dict(
                    game_dir, live_entries):
                raise RuntimeError("не удалось записать словарь MV-моста")

        # 4) страховка: игра обязана стартовать. Проверяем все файлы,
        # которые движок читает через JSON.parse (data, список плагинов,
        # вшитые словари), строгим парсером глазами V8. При провале —
        # откатываем всё наше и возвращаем честную ошибку вместо «готово».
        from app.core.rpgmaker import verify as vrf
        problems = vrf.verify_boot_files(
            game_dir, check_plugin_js=patch_plugin_js)
        if problems:
            try:
                self.restore_original(game_dir)
            except Exception:  # noqa: BLE001
                pass
            try:
                still = vrf.verify_boot_files(
                    game_dir, check_plugin_js=patch_plugin_js)
            except Exception:  # noqa: BLE001
                still = list(problems)
            stats["verify_failed"] = problems
            stats["verify_restored"] = not still
            stats["verify_remaining"] = still
        return stats

    def restore_original(self, game_dir: str) -> dict:
        from app.core.rpgmaker import runtime as rt
        stats = rt.uninstall_runtime(game_dir, restore_legacy=False)
        stats["errors"] = []
        # legacy откат на случай старых file-патчей (одноразово)
        if not self._asar:
            try:
                from app.core.rpgmaker import parser as parser_mod
                legacy = parser_mod.restore_original(game_dir)
                if legacy.get("restored"):
                    stats["legacy_restored"] = legacy["restored"]
            except Exception as exc:  # noqa: BLE001
                stats["errors"].append(f"legacy restore: {exc}")
        # Electron: откат asar если был полный бэкап архива
        if self._asar:
            try:
                asar_stats = self._restore_asar(game_dir)
                if asar_stats.get("restored"):
                    stats["asar_restored"] = asar_stats["restored"]
            except Exception as exc:  # noqa: BLE001
                stats["errors"].append(f"asar restore: {exc}")
        return stats

    def _restore_asar(self, game_dir: str) -> dict:
        """Восстанавливает asar из backup/ (самая ранняя папка) либо из
        <архив>.ob.bak, если архив пересобирался целиком."""
        from . import asar as asarlib
        from app.core import asar as asarcore
        ar_path = asarlib.asar_path(game_dir)
        full_bak = ar_path + ".ob.bak"
        if os.path.isfile(full_bak):
            with open(full_bak, "rb") as f:
                atomic_write_bytes(ar_path, f.read())
            return {"restored": 1}
        root = os.path.join(game_dir, "backup")
        if not os.path.isdir(root):
            return {"restored": 0}
        ar = asarcore.AsarArchive(ar_path)

        def read_tree(base: str) -> dict[str, bytes]:
            values: dict[str, bytes] = {}
            for current, _dirs, files in os.walk(base):
                for name in files:
                    if name.endswith(".ob.bak") or name.endswith(".ob.new"):
                        continue
                    src = os.path.join(current, name)
                    try:
                        with open(src, "rb") as fh:
                            rel = os.path.relpath(src, base).replace(os.sep, "/")
                            values[rel] = fh.read()
                    except OSError:
                        pass
            return values

        def resolve_rel(rel: str, prefer_project: bool) -> str | None:
            candidates = (
                (f"{asarlib.PROJECT_PREFIX}/{rel}", rel, f"www/{rel}")
                if prefer_project else
                (rel, f"{asarlib.PROJECT_PREFIX}/{rel}", f"www/{rel}")
            )
            for candidate in dict.fromkeys(candidates):
                if ar.exists(candidate):
                    return candidate
            return None

        blobs: dict[str, bytes] = {}
        try:
            entries = sorted(os.listdir(root))
        except OSError:
            entries = []
        for name in entries:
            if not re.match(r"^\d{8}_\d{6}$", name):
                continue
            base = os.path.join(root, name)
            if not os.path.isdir(base):
                continue
            if blobs:
                break
            blobs = read_tree(base)

        patches: dict[str, bytes] = {}
        for rel, blob in blobs.items():
            archive_rel = resolve_rel(rel, prefer_project=True)
            if archive_rel is not None:
                patches[archive_rel] = blob
        if not patches and blobs:
            rel_by_base: dict[str, str] = {}
            for rel, _node in ar.iter_files():
                rel_by_base.setdefault(os.path.basename(rel), rel)
            patches = {rel_by_base[os.path.basename(rel)]: blob
                       for rel, blob in blobs.items()
                       if os.path.basename(rel) in rel_by_base}

        maps_root = os.path.join(root, "maps")
        if os.path.isdir(maps_root):
            for rel, blob in read_tree(maps_root).items():
                archive_rel = resolve_rel(rel, prefer_project=False)
                if archive_rel is not None and archive_rel not in patches:
                    patches[archive_rel] = blob
        if not patches:
            return {"restored": 0}
        astats = asarcore.apply_patches(ar_path, patches)
        return {"restored": astats["files"]}

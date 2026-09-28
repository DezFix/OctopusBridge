# -*- coding: utf-8 -*-
"""Сервис перевода: склеивает определение языка, маскирование, глоссарий,
движок и память переводов.

Принцип: перевод не имеет права упасть из-за одного провайдера. Строка,
которую не удалось перевести, не помечается «готово» — она возвращается
в очередь и повторяется позже. Иначе получается «всё зелёное, а по
факту ничего не переведено».
"""
from __future__ import annotations

import re
import time
from typing import Callable

from app.core.models import TranslationEntry
from .alphabets import is_single_letter
from .detect import detect_lang
from .engines import BaseEngine, EngineError
from .fixers import apply_fixers
from .glossary import Glossary
from .mask import (is_code_only, mask, split_edge_codes, tokens_present,
                   unmask, validate)
from .memory import TranslationMemory

# батчи для LLM ограничиваем по примерному числу токенов, а не только
# по числу строк: длинные строки обрывают ответ модели.
# Пакеты крупнее = меньше запросов: Google отдаёт до 200 строк за раз,
# LLM-движки режут батч сами.
TARGET_TOKENS = 1500
MAX_BATCH_LINES = 100

# сколько кругов повтора, прежде чем оставить строки не переведёнными.
# Круг делается только если предыдущий дал прогресс, поэтому на
# непереводимых строках цикл не крутится. Нужно, чтобы пережить череду
# лимитов: «отдохнул провайдер — поехали дальше».
MAX_GROUP_PASSES = 12
# потолок ожидания между кругами, секунды
MAX_PASS_SLEEP = 60.0
# пауза между кругами, если движок не попросил конкретную
DEFAULT_PASS_SLEEP = 5.0


def build_tr_dict(entries) -> dict:
    """Словарь original->translation для live-перевода (пустые пропущены).

    Каноническая реализация (раньше копипаста в engines/rpgmaker/tentacle,
    engines/twine/tentacle и core/rpgmaker/mv_bridge.update_tr_dict).
    Принимает TranslationEntry или dict'ы; записи со status='skip',
    пустым original или пустым translation пропускаются.
    """
    tr: dict = {}
    for e in entries:
        if isinstance(e, dict):
            orig = e.get("original", "")
            text = e.get("translation", "") or ""
            status = e.get("status", "")
        else:
            orig = getattr(e, "original", "")
            text = getattr(e, "translation", "") or ""
            status = getattr(e, "status", "")
        if orig and text.strip() and status != "skip":
            tr[orig] = text
    return tr


def _estimate_tokens(text: str) -> int:
    """Грубая оценка токенов: CJK ~1 токен на символ, латиница ~1/4."""
    if re.search(r"[\u3000-\u9fff\uf900-\ufaff\uac00-\ud7af]", text):
        return max(len(text), 1)
    return max(len(text) // 4, 1)


def _is_code_token(text: str) -> bool:
    """Строка — код/данные, а не текст для игрока: путь к файлу, URL,
    hex-цвет. Один токен без пробелов, только ASCII-символы — иначе
    зацепим японские/русские слова и настоящие фразы."""
    s = text.strip()
    if not s or re.search(r"\s", s):
        return False
    if re.match(r"^https?://", s):
        return True
    if re.match(r"^#[0-9a-fA-F]{3,8}$", s):
        return True
    if re.search(r"[\\/]", s) and re.search(r"\.[A-Za-z0-9]{1,5}$", s) \
            and re.fullmatch(r"[\w.\\/\-@!#$%^&*()\[\]{}<>:;,?+=~`|']+", s) \
            and not re.search(r"[^\x00-\x7F]", s):
        return True
    return False


def _resolve_src(text: str, declared_src: str, tgt_lang: str) -> str | None:
    """Реальный язык источника строки для движка.

    Смешанные игры (часть текста на японском, часть на английском):
    детекция по строке важнее заявленного языка проекта, иначе
    английские строки уходят движку как «японские» и остаются без
    перевода. Возвращает None — строка уже на целевом языке.
    """
    detected = detect_lang(text)
    if detected == tgt_lang:
        return None
    if declared_src == "auto":
        # как раньше: не распознано — переводить нечего
        return detected
    return detected or declared_src


def _reattach(text: str, lead: list[str], trail: list[str]) -> str:
    """Приклеивает краевые коды, если переводчик их не сохранил.

    Порядок кодов сохраняется: находим самый длинный префикс/суффикс,
    который движок уже вернул, и вставляем недостающие коды рядом,
    не дублируя сохранённые.
    """
    if lead:
        for j in range(len(lead), -1, -1):
            prefix = "".join(lead[:j])
            if text.startswith(prefix):
                if j < len(lead):
                    text = "".join(lead) + text[len(prefix):]
                break
    if trail:
        found = False
        for j in range(len(trail)):
            suffix = "".join(trail[j:])
            if text.endswith(suffix):
                text = text[:-len(suffix)] + "".join(trail)
                found = True
                break
        if not found:
            text = text + "".join(trail)
    return text


class Translator:
    def __init__(self, engine: BaseEngine, tm: TranslationMemory | None = None,
                 glossary: Glossary | None = None):
        self.engine = engine
        self.tm = tm
        self.glossary = glossary
        self.cancelled = False
        # строки, которые не удалось перевести в этом запуске: остаются
        # со статусом new и повторятся при следующем запуске
        self.failed: list[TranslationEntry] = []
        self.last_error: str = ""

    def cancel(self):
        self.cancelled = True
        # движок проверяет флаг перед каждым сетевым запросом/ожиданием —
        # иначе поток не выйдет из спячки/таймаута до конца батча
        if self.engine is not None:
            self.engine.cancel()

    # ---------- устойчивость к отказам провайдера ----------
    def _engine_call(self, texts: list[str], src_lang: str,
                     tgt_lang: str) -> list:
        """Вызов движка, который не роняет задачу. None — отказ."""
        if self.cancelled:
            raise InterruptedError("cancelled")
        try:
            return self.engine.translate(texts, src_lang, tgt_lang)
        except InterruptedError:
            raise
        except Exception as e:  # noqa: BLE001
            self.last_error = f"{type(e).__name__}: {e}"
            return None

    def _engine_wait(self) -> float:
        """Сколько движок просит подождать (его кулдауны). 0 — можно."""
        getter = getattr(self.engine, "wait_hint", None)
        if not callable(getter):
            return 0.0
        try:
            return max(0.0, float(getter()))
        except Exception:  # noqa: BLE001
            return 0.0

    def _engine_dead(self) -> bool:
        """Движок сообщает: сети нет ни у одного провайдера. Ждать нечего."""
        getter = getattr(self.engine, "all_down", None)
        if not callable(getter):
            return False
        try:
            return bool(getter())
        except Exception:  # noqa: BLE001
            return False

    def _sleep_cancellable(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while not self.cancelled:
            remain = end - time.monotonic()
            if remain <= 0:
                return
            time.sleep(min(0.5, remain))

    # ---------- одна строка ----------
    def translate_text(self, text: str, src_lang: str, tgt_lang: str,
                       overwrite: bool = False,
                       strict: bool = False) -> str:
        """Переводит одну строку: TM -> глоссарий-сегменты -> движок.

        strict=True — движок недоступен, поднимет EngineError вместо
        возврата оригинала. Нужен пакетному переводу файлов, где молча
        вернувшийся оригинал был бы помечен как готовый перевод.
        """
        src = _resolve_src(text, src_lang, tgt_lang)
        if not src:
            return text
        src_lang = src

        # одиночный знак алфавита (кана/кириллица/латиница) — не слово,
        # перевода не имеет; раньше чем TM: старый мусор «Домой» не должен
        # вылезать из кеша
        if is_single_letter(text):
            return text
        # только цифры/знаки (без букв): единицы, пунктуация, символы —
        # движок может их исказить (LLM), переводить нечего
        if not re.search(r"[^\W\d_]", text):
            return text
        # пути к файлам/URL/hex-цвета — код, не текст для игрока
        if _is_code_token(text):
            return text

        cached = None
        if self.tm and not overwrite:
            cached = self.tm.get(text, src_lang, tgt_lang)
        if cached:
            return cached

        # TextPreserve prefix/suffix: краевые коды не отправляем движку,
        # приклеиваем к результату (переводчики их теряют чаще всего)
        lead, mid, trail = split_edge_codes(text)
        masked, codes = mask(mid)
        if is_code_only(masked):
            return "".join(lead) + mid + "".join(trail)
        segments = (self.glossary.split_by_terms(masked, src_lang, tgt_lang)
                    if self.glossary else [(masked, None)])
        out_parts: list[str] = []
        for segment, fixed in segments:
            if fixed is not None:
                out_parts.append(fixed)
                continue
            if not segment.strip():
                out_parts.append(segment)
                continue
            # TextPreserve check: строка только из кодов — движку не нужна
            if is_code_only(segment.strip()):
                out_parts.append(segment)
                continue
            # одиночный знак алфавита (кнопка кана-клавиатуры, хоткей) —
            # движку не отправляем, отдаём как есть
            if is_single_letter(segment.strip()):
                out_parts.append(segment)
                continue
            # движки нормализуют пробелы по краям — сохраняем их сами
            lead_ws = segment[:len(segment) - len(segment.lstrip())]
            trail_ws = segment[len(segment.rstrip()):]
            res = self._engine_call([segment.strip()], src_lang, tgt_lang)
            translated = ""
            if res is not None:
                translated = res[0] or "" if res else ""
            if strict and not (translated or "").strip():
                raise EngineError("engine unavailable for single line")
            # движок вернул пустое (звуки/короткие возгласы) — оригинал,
            # иначе текст в игре просто исчезает. Rotate для одной строки
            # штатно возвращает [None] — это «не перевёл», а не краш.
            if not (translated or "").strip() and segment.strip():
                translated = segment.strip()
            # мягкая проверка: unmask восстановит что сможет
            restored = (unmask(translated, codes)
                        if validate(translated, codes)
                        or tokens_present(translated)
                        else translated)
            # фиксерам нужен оригинал с кодами, а не с токенами <xN/>:
            # иначе fix_codes сочтёт все коды перевода "лишними" и сотрёт
            orig_codes = unmask(segment, codes) if codes else segment
            restored = apply_fixers(restored, src_lang, tgt_lang,
                                    orig_codes.strip())
            out_parts.append(lead_ws + restored + trail_ws)
        result = "".join(out_parts)
        result = _reattach(result, lead, trail)
        # В память переводов пишем только реальные переводы: иначе при
        # сбое движка (результат == оригинал) INSERT OR REPLACE затирает
        # хороший перевод мусором.
        if self.tm and result != text and result.strip():
            self.tm.put(text, result, src_lang, tgt_lang)
        return result

    # ---------- пакет простых строк (имена и т.п.) ----------
    def translate_texts(self, texts: list[str], src_lang: str,
                        tgt_lang: str) -> list[str]:
        """Переводит список простых строк одним батчем на язык.

        Для имён переменных/предметов: сотни отдельных translate_text()
        превращаются в десятки запросов к движку. Строки, которым
        перевод не нужен (уже на целевом языке, цифры/знаки, коды),
        возвращаются как есть.
        """
        out: list[str] = [""] * len(texts)
        # (index, text, detected_src, masked, codes, lead, trail)
        jobs: list[tuple] = []
        for i, text in enumerate(texts):
            text = text or ""
            if not text.strip():
                out[i] = text
                continue
            src = _resolve_src(text, src_lang, tgt_lang)
            if not src:
                out[i] = text
                continue
            if is_single_letter(text):
                out[i] = text
                continue
            if not re.search(r"[^\W\d_]", text):
                out[i] = text
                continue
            if _is_code_token(text):
                out[i] = text
                continue
            cached = self.tm.get(text, src, tgt_lang) if self.tm else None
            if cached:
                out[i] = cached
                continue
            lead, mid, trail = split_edge_codes(text)
            masked, codes = mask(mid)
            if is_code_only(masked):
                out[i] = "".join(lead) + mid + "".join(trail)
                continue
            jobs.append((i, text, src, masked, codes, lead, trail))

        by_src: dict[str, list[tuple]] = {}
        for job in jobs:
            by_src.setdefault(job[2], []).append(job)
        for src, group in by_src.items():
            for start in range(0, len(group), MAX_BATCH_LINES):
                chunk = group[start:start + MAX_BATCH_LINES]
                batch = [j[3] for j in chunk]
                try:
                    translated = self.engine.translate(batch, src, tgt_lang)
                except InterruptedError:
                    raise
                except Exception:  # noqa: BLE001 — движок упал, вернём как есть
                    translated = [None] * len(batch)
                # движок может вернуть короче (отфильтровал None): хвост —
                # неперевёденные строки, а не чужие переводы (как в _run_jobs)
                out_list = list(translated) if translated else []
                if len(out_list) < len(chunk):
                    out_list.extend([None] * (len(chunk) - len(out_list)))
                tm_pairs: list[tuple[str, str]] = []
                for (i, text, _src, masked, codes, lead, trail), res in \
                        zip(chunk, out_list):
                    if not res or not res.strip():
                        out[i] = text
                        continue
                    restored = (unmask(res, codes)
                                if validate(res, codes)
                                or tokens_present(res)
                                else res)
                    orig_codes = unmask(masked, codes) if codes else masked
                    restored = apply_fixers(restored, src, tgt_lang,
                                            orig_codes.strip())
                    result = _reattach(restored, lead, trail)
                    out[i] = result
                    if result != text and result.strip():
                        tm_pairs.append((text, result))
                if self.tm and tm_pairs:
                    self.tm.put_many(tm_pairs, src, tgt_lang)
        return out

    # ---------- записи проекта ----------
    def prefill_from_memory(
        self,
        entries: list[TranslationEntry],
        src_lang: str,
        tgt_lang: str,
    ) -> int:
        """Подтянуть переводы из памяти (ТМ) для записей без перевода.

        Точное совпадение + совпадение по нормализованной строке
        (пробелы/переносы) — делает TranslationMemory.get().
        Записям с найденным переводом ставит status='translated'.
        Пропускает записи с уже готовым переводом и status='skip'.
        Возвращает число подтянутых строк. Движок не используется.
        """
        if not self.tm:
            return 0
        # Группируем по реальному языку строки и тянем PACKETом
        # (lookup_many: один проход, один коммит). Поштучный tm.get()
        # с commit на хит здесь запрещён — 3000 строк вешали GUI.
        groups: dict[str, list] = {}
        for e in entries:
            if (e.translation or "").strip() or e.status == "skip":
                continue
            if not (e.original or "").strip():
                continue
            lang = _resolve_src(e.original, src_lang, tgt_lang)
            if not lang:
                continue
            groups.setdefault(lang, []).append(e)
        n = 0
        for lang, group in groups.items():
            if self.cancelled:
                break
            found = self.tm.lookup_many(
                [e.original for e in group], lang, tgt_lang)
            if lang != src_lang:
                missing = [e.original for e in group if e.original not in found]
                if missing:
                    try:
                        extra = self.tm.lookup_many(missing, src_lang, tgt_lang)
                    except Exception:
                        extra = {}
                    found.update(extra)
            for e in group:
                hit = found.get(e.original)
                if hit:
                    e.translation = hit
                    e.status = "translated"
                    n += 1
        return n

    def translate_entries(
        self,
        entries: list[TranslationEntry],
        src_lang: str,
        tgt_lang: str,
        progress: Callable[[int, int], None] | None = None,
        overwrite: bool = False,
        status_cb: Callable[[str], None] | None = None,
    ) -> int:
        """Переводит записи на месте. Возвращает число переведённых строк.

        Строки, которые не удалось перевести (движок недоступен, лимит,
        потерянные токены), остаются со статусом new и попадают в
        self.failed — задача не падает и повторит их позже.
        status_cb — текстовые этапы для UI («жду N с»), чтобы окно не
        выглядело висящим во время молчаливых пауз.
        """
        self.failed = []
        targets = [
            e for e in entries
            if (overwrite or not (e.translation or "").strip())
            and (overwrite or e.status != "skip")
        ]
        total = len(targets)
        done = [0]  # общий счётчик для прогресса

        def report():
            if progress:
                progress(done[0], total)

        if src_lang == "auto":
            groups: dict[str, list[TranslationEntry]] = {}
            skipped = 0
            for e in targets:
                lang = detect_lang(e.original)
                if not lang or lang == tgt_lang:
                    # строка уже на целевом языке (или без букв) —
                    # переводить нечего; помечаем, чтобы было видно
                    skipped += 1
                    if e.status not in ("manual", "corrected", "translated"):
                        e.status = "skip"
                    continue
                groups.setdefault(lang, []).append(e)
            done[0] += skipped
            report()
            for lang, group in groups.items():
                if self.cancelled:
                    break
                self._translate_group(group, lang, tgt_lang, done, report,
                                      overwrite, status_cb)
            return done[0] - skipped

        # явный исходный язык: всё равно группируем по реальному языку
        # строки — в смешанных играх (часть текста ja, часть en) иначе
        # английские строки уходят движку как «японские» без перевода
        groups: dict[str, list[TranslationEntry]] = {}
        for e in targets:
            lang = _resolve_src(e.original, src_lang, tgt_lang)
            if not lang:
                continue
            groups.setdefault(lang, []).append(e)
        for lang, group in groups.items():
            if self.cancelled:
                break
            self._translate_group(group, lang, tgt_lang, done, report,
                                  overwrite, status_cb)
        return done[0]

    # ---------- перевод группы строк одного языка ----------
    def _finish_one(self, masked_tr, job, src_lang, tgt_lang) -> str | None:
        """Готовый перевод строки или None, если движок её не осилил.

        Здесь стоял fallback `text = holders[0].original` со
        status='translated': строка оставалась на языке оригинала, но
        помечалась готовой и больше никогда не переводилась — отсюда
        «всё зелёное, а перевода нет». Теперь такая строка возвращается
        в очередь на повтор.
        """
        holders, masked, codes, lead, trail = job
        if not masked_tr or not masked_tr.strip():
            return None
        if validate(masked_tr, codes) or tokens_present(masked_tr):
            text = unmask(masked_tr, codes)
        else:
            # токены потеряны: одиночный ретрай того же текста
            retry = self._engine_call([masked], src_lang, tgt_lang)
            got = retry[0] if retry else None
            if got and (validate(got, codes) or tokens_present(got)):
                text = unmask(got, codes)
            else:
                return None
        if not (text or "").strip():
            return None
        text = _reattach(text, lead, trail)
        orig = holders[0].original or "" if holders else ""
        return apply_fixers(text, src_lang, tgt_lang, orig)

    def _commit(self, job, text, done: list[int],
                tm_pairs: list[tuple[str, str]]) -> None:
        holders, _masked, _codes, _lead, _trail = job
        for e in holders:
            e.translation = text
            e.status = "translated"
            done[0] += 1
        if text != holders[0].original and text.strip():
            tm_pairs.append((holders[0].original, text))

    def _run_jobs(self, jobs: list[tuple], src_lang: str, tgt_lang: str,
                  done: list[int], report: Callable[[], None],
                  tm_pairs: list[tuple[str, str]]) -> list[tuple]:
        """Прогоняет список заданий через движок пакетами.

        Возвращает задания, которые не удалось перевести — их никуда не
        теряем, они уйдут в следующий круг повтора. Запись в память
        переводов делает вызывающий.
        """
        left: list[tuple] = []
        for start in range(0, len(jobs), MAX_BATCH_LINES):
            if self.cancelled:
                left.extend(jobs[start:])
                break
            chunk = jobs[start:start + MAX_BATCH_LINES]
            out = self._engine_call([j[1] for j in chunk], src_lang, tgt_lang)
            if out is None:
                # движок недоступен целиком — батч целиком в очередь
                left.extend(chunk)
                report()
                continue
            out = list(out)
            if len(out) < len(chunk):
                out.extend([None] * (len(chunk) - len(out)))
            for job, res in zip(chunk, out):
                text = self._finish_one(res, job, src_lang, tgt_lang)
                if text is None:
                    left.append(job)
                    continue
                self._commit(job, text, done, tm_pairs)
            report()
        return left

    def _translate_group(self, targets: list[TranslationEntry],
                          src_lang: str, tgt_lang: str,
                          done: list[int], report: Callable[[], None],
                          overwrite: bool = False,
                          status_cb: Callable[[str], None] | None = None):
        # дедупликация: одинаковые оригиналы переводим один раз
        unique: dict[str, list[TranslationEntry]] = {}
        for e in targets:
            unique.setdefault(e.original, []).append(e)

        # Память одним пакетом (lookup_many: один проход, один коммит),
        # а не tm.get() на каждую строку (там UPDATE+commit на хит —
        # тысячи fsync на больших проектах).
        cached_map: dict[str, str] = {}
        if self.tm and not overwrite:
            try:
                cached_map = self.tm.lookup_many(
                    list(unique), src_lang, tgt_lang)
            except Exception:  # noqa: BLE001 — память не обязательна
                cached_map = {}

        # Позиции для контекста — индексной картой за O(n), а не линейным
        # поиском на каждую строку (было O(n^2): десятки секунд на 40k).
        pos_of: dict[int, int] = {id(e): i for i, e in enumerate(targets)}

        all_originals = [e.original for e in targets]
        jobs: list[tuple] = []          # (holders, masked, codes, lead, trail)
        gloss_jobs: list[tuple] = []   # строки с терминами глоссария
        batch_src: list[str] = []
        batch_jobs: list[tuple] = []
        batch_indices: list[int] = []
        batch_tokens: list[int] = [0]
        tm_pairs: list[tuple[str, str]] = []

        def flush():
            if not batch_src:
                return
            if self.cancelled:
                batch_src.clear()
                batch_jobs.clear()
                batch_indices.clear()
                batch_tokens[0] = 0
                return
            first_idx = batch_indices[0] if batch_indices else 0
            last_idx = batch_indices[-1] if batch_indices else 0
            ctx_before = all_originals[max(0, first_idx - 3):first_idx] \
                if first_idx > 0 else None
            ctx_after = all_originals[last_idx + 1:last_idx + 4] \
                if last_idx < len(all_originals) - 1 else None
            try:
                translated = self.engine.translate(
                    batch_src, src_lang, tgt_lang,
                    context_before=ctx_before, context_after=ctx_after)
            except InterruptedError:
                raise
            except Exception:  # noqa: BLE001 — батч уходит в очередь
                translated = None
            out = list(translated) if translated else []
            if len(out) < len(batch_jobs):
                out.extend([None] * (len(batch_jobs) - len(out)))
            for job, res in zip(batch_jobs, out):
                text = self._finish_one(res, job, src_lang, tgt_lang)
                if text is None:
                    jobs.append(job)
                    continue
                self._commit(job, text, done, tm_pairs)
            if self.tm and tm_pairs:
                self.tm.put_many(tm_pairs, src_lang, tgt_lang)
                tm_pairs.clear()
            batch_src.clear()
            batch_jobs.clear()
            batch_indices.clear()
            batch_tokens[0] = 0
            report()

        for idx, (original, holders) in enumerate(unique.items()):
            if self.cancelled:
                break
            job = (holders, "", [], [], [])
            # В режиме «Перевести всё заново» память переводов не
            # консультируем: иначе записи с уже готовым переводом
            # замыкаются на старый кэш и не пересоздаются.
            cached = cached_map.get(original)
            if cached:
                for e in holders:
                    e.translation = cached
                    e.status = "translated"
                    done[0] += 1
                continue
            # строки с терминами из глоссария — поштучно, чтобы сегментировать
            if self.glossary and any(
                    t in original for t in self.glossary.terms(src_lang, tgt_lang)):
                gloss_jobs.append((holders, original, src_lang, tgt_lang))
                continue
            # TextPreserve prefix/suffix: краевые коды уводим из батча
            lead, mid, trail = split_edge_codes(original)
            masked, codes = mask(mid)
            if is_code_only(masked):
                # TextPreserve check: строка только из кодов — без движка
                for e in holders:
                    e.translation = original
                    e.status = "translated"
                    done[0] += 1
                continue
            # только цифры/знаки (без букв) и код-токены (пути/URL/hex) —
            # без движка: LLM их искажает или ломает пути к ресурсам
            if not re.search(r"[^\W\d_]", original) \
                    or _is_code_token(masked):
                for e in holders:
                    e.translation = original
                    e.status = "translated"
                    done[0] += 1
                continue
            # одиночный знак алфавита — без движка, как есть
            if is_single_letter(masked):
                for e in holders:
                    e.translation = original
                    e.status = "translated"
                    done[0] += 1
                continue
            job = (holders, masked, codes, lead, trail)
            tokens = _estimate_tokens(masked)
            # строка не влезает в лимит — завершаем текущий батч
            # (строки не режем: длинная уйдёт отдельно)
            if batch_tokens[0] > 0 and batch_tokens[0] + tokens > TARGET_TOKENS:
                flush()
            batch_src.append(masked)
            batch_jobs.append(job)
            batch_indices.append(pos_of.get(id(holders[0]), idx))
            batch_tokens[0] += tokens
            if batch_tokens[0] >= TARGET_TOKENS or len(batch_src) >= MAX_BATCH_LINES:
                flush()

        flush()

        # ---- глоссарий: поштучно, с очередью на повтор ----
        if gloss_jobs and not self.cancelled:
            left_gloss: list[tuple] = []
            for gjob in gloss_jobs:
                if self.cancelled:
                    left_gloss.append(gjob)
                    continue
                holders, original, _sl, _tl = gjob
                try:
                    text = self.translate_text(original, src_lang, tgt_lang,
                                               overwrite=overwrite, strict=True)
                except InterruptedError:
                    raise
                except EngineError:
                    left_gloss.append(gjob)
                    continue
                job = (holders, original, [], [], [])
                self._commit(job, text, done, tm_pairs)
            if self.tm and tm_pairs:
                self.tm.put_many(tm_pairs, src_lang, tgt_lang)
                tm_pairs.clear()
            report()
            jobs.extend(left_gloss)

        # ---- повторы: не сдаёмся после первой неудачи ----
        # «От лимита к лимиту»: ждём, пока отдохнёт провайдер, который ловил
        # лимит, и пробуем снова. Круг делается только если предыдущий дал
        # прогресс — иначе крутить бессмысленно (либо сети нет вовсе, либо
        # строка непереводима). Оставшиеся строки сохраняют статус new и
        # повторятся при следующем запуске / авто-возобновлении.
        for _ in range(MAX_GROUP_PASSES):
            if self.cancelled or not jobs:
                break
            before = len(jobs)
            wait = self._engine_wait()
            if wait > 0:
                # провайдеры отдыхают от лимита — спим ровно до этого.
                # Молчаливый сон до 60 с выглядел как вис: говорим в UI.
                nap = min(wait, MAX_PASS_SLEEP)
                if status_cb:
                    try:
                        from app.ui.i18n import TR as _TR
                        status_cb(_TR("tr_status_wait", sec=int(nap)))
                    except Exception:  # noqa: BLE001 — статус не обязателен
                        pass
                self._sleep_cancellable(nap)
                report()
            elif self._engine_dead():
                break   # сети нет ни у кого — ждать нечего
            jobs = self._run_jobs(jobs, src_lang, tgt_lang, done, report,
                                  tm_pairs)
            if self.tm and tm_pairs:
                self.tm.put_many(tm_pairs, src_lang, tgt_lang)
                tm_pairs.clear()
            if len(jobs) >= before:
                break   # прогресса нет — дальше крутить нечего

        # не осилили — оставляем не переведёнными (status new) и отдаём
        # наружу, чтобы UI показал «ждёт провайдера», а не «готово»
        for job in jobs:
            for e in job[0]:
                if e not in self.failed:
                    self.failed.append(e)

# -*- coding: utf-8 -*-
"""Память переводов (SQLite): повторное использование переводов между сессиями.

v2: нормализация пробелов + WAL + батчевые записи + reuse между проектами.

Схема:
  tm  — legacy-таблица (source, src_lang, tgt_lang -> target), точное
         совпадение. Оставлена для обратной совместимости, при записи
         синхронизируется с tm2.
  tm2 — новая таблица:
         norm_source TEXT, source TEXT, src_lang, tgt_lang, target,
         engine TEXT, project TEXT, updated INTEGER, hits INTEGER,
         PRIMARY KEY(norm_source, src_lang, tgt_lang).

norm = NFC + strip + схлопывание всех пробельных последовательностей
(пробелы, табы, переносы) в один пробел. Поэтому «Привет\\nмир» и
«Привет  мир» — одна запись.

Потокобезопасна: соединение создаётся с check_same_thread=False, все
операции защищены RLock — можно вызывать из потока перевода.
"""
from __future__ import annotations

import difflib
import glob
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata

_WS_RE = re.compile(r"\s+")


def normalize_source(text: str) -> str:
    """Нормализованный ключ строки: NFC + strip + collapse whitespace."""
    return _WS_RE.sub(" ", unicodedata.normalize("NFC", text)).strip()


class TranslationMemory:
    def __init__(self, db_path: str):
        self._lock = threading.RLock()
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        with self._lock:
            # WAL: читатели не блокируют писателя (UI + поток перевода).
            try:
                self.db.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                pass
            try:
                self.db.execute("PRAGMA synchronous=NORMAL")
            except sqlite3.Error:
                pass
            # legacy-таблица — не трогаем схему, только создаём если нет
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS tm ("
                " source TEXT NOT NULL,"
                " src_lang TEXT NOT NULL,"
                " tgt_lang TEXT NOT NULL,"
                " target TEXT NOT NULL,"
                " PRIMARY KEY (source, src_lang, tgt_lang))"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS tm2 ("
                " norm_source TEXT NOT NULL,"
                " source TEXT NOT NULL,"
                " src_lang TEXT NOT NULL,"
                " tgt_lang TEXT NOT NULL,"
                " target TEXT NOT NULL,"
                " engine TEXT NOT NULL DEFAULT '',"
                " project TEXT NOT NULL DEFAULT '',"
                " updated INTEGER NOT NULL DEFAULT 0,"
                " hits INTEGER NOT NULL DEFAULT 0,"
                " PRIMARY KEY (norm_source, src_lang, tgt_lang))"
            )
            self.db.commit()
            self._migrate_legacy()

    # ---------- миграция ----------
    def _migrate_legacy(self):
        """Копировать старые строки из tm в tm2, если tm2 пуста."""
        row = self.db.execute("SELECT COUNT(*) FROM tm2").fetchone()
        if row and row[0] > 0:
            return
        rows = self.db.execute(
            "SELECT source, src_lang, tgt_lang, target FROM tm"
        ).fetchall()
        if not rows:
            return
        now = int(time.time())
        data = [
            (normalize_source(s), s, sl, tl, t, "", "", now, 0)
            for s, sl, tl, t in rows
        ]
        self.db.executemany(
            "INSERT OR IGNORE INTO tm2 (norm_source, source, src_lang,"
            " tgt_lang, target, engine, project, updated, hits)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            data,
        )
        self.db.commit()

    # ---------- чтение ----------
    def get(self, source: str, src_lang: str, tgt_lang: str) -> str | None:
        """Точное совпадение, затем совпадение по нормализованной строке."""
        norm = normalize_source(source)
        with self._lock:
            row = self.db.execute(
                "SELECT target FROM tm2 WHERE source=? AND src_lang=?"
                " AND tgt_lang=?",
                (source, src_lang, tgt_lang),
            ).fetchone()
            if row:
                self.db.execute(
                    "UPDATE tm2 SET hits=hits+1 WHERE source=?"
                    " AND src_lang=? AND tgt_lang=?",
                    (source, src_lang, tgt_lang),
                )
                self.db.commit()
                return row[0]
            row = self.db.execute(
                "SELECT target FROM tm2 WHERE norm_source=? AND src_lang=?"
                " AND tgt_lang=?",
                (norm, src_lang, tgt_lang),
            ).fetchone()
            if row:
                self.db.execute(
                    "UPDATE tm2 SET hits=hits+1 WHERE norm_source=?"
                    " AND src_lang=? AND tgt_lang=?",
                    (norm, src_lang, tgt_lang),
                )
                self.db.commit()
                return row[0]
            # fallback: старая таблица (на случай если миграция не прошла)
            row = self.db.execute(
                "SELECT target FROM tm WHERE source=? AND src_lang=?"
                " AND tgt_lang=?",
                (source, src_lang, tgt_lang),
            ).fetchone()
        return row[0] if row else None

    def get_any_src(self, source: str, tgt_lang: str) -> str | None:
        """Совпадение без учёта исходного языка: та же строка, тот же таргет.

        Нужно для reuse между проектами с разным source_lang
        (старый ja->ru, новый en->ru/auto->ru): текст идентичен,
        перевод переиспользуем. Норм-совпадение приоритетнее точного
        по чужой паре? Нет — сначала точное по любому src, потом норм.
        """
        norm = normalize_source(source)
        with self._lock:
            row = self.db.execute(
                "SELECT target FROM tm2 WHERE source=? AND tgt_lang=?"
                " LIMIT 1",
                (source, tgt_lang),
            ).fetchone()
            if row:
                return row[0]
            row = self.db.execute(
                "SELECT target FROM tm2 WHERE norm_source=? AND tgt_lang=?"
                " LIMIT 1",
                (norm, tgt_lang),
            ).fetchone()
        return row[0] if row else None

    def lookup_many(self, sources: list[str], src_lang: str,
                      tgt_lang: str) -> dict[str, str]:
        """Пакетный поиск для prefill: один проход, один коммит.

        Для каждой строки: точное совпадение -> норм -> любой src
        (тот же tgt). Счётчик hits инкрементируется одним UPDATE
        в конце, а не commit на строку (иначе 3000 строк = 3000
        fsync и секунды виса). Возвращает {original: target}."""
        out: dict[str, str] = {}
        if not sources:
            return out
        norms = [normalize_source(s) for s in sources]
        hit_norms: set[tuple[str, str]] = set()
        with self._lock:
            for s, norm in zip(sources, norms):
                if not norm or s in out:
                    continue
                row = self.db.execute(
                    "SELECT target FROM tm2 WHERE source=? AND src_lang=?"
                    " AND tgt_lang=?",
                    (s, src_lang, tgt_lang),
                ).fetchone()
                if row:
                    out[s] = row[0]
                    hit_norms.add((norm, src_lang))
                    continue
                row = self.db.execute(
                    "SELECT target FROM tm2 WHERE norm_source=?"
                    " AND src_lang=? AND tgt_lang=?",
                    (norm, src_lang, tgt_lang),
                ).fetchone()
                if row:
                    out[s] = row[0]
                    hit_norms.add((norm, src_lang))
                    continue
                row = self.db.execute(
                    "SELECT target FROM tm2 WHERE norm_source=? AND tgt_lang=?"
                    " LIMIT 1",
                    (norm, tgt_lang),
                ).fetchone()
                if row:
                    out[s] = row[0]
            if hit_norms:
                self.db.executemany(
                    "UPDATE tm2 SET hits=hits+1 WHERE norm_source=?"
                    " AND src_lang=?",
                    list(hit_norms),
                )
                self.db.commit()
        return out

    @staticmethod
    def projects_fingerprint(projects_dir: str) -> tuple[int, float, int]:
        """Дешёвый отпечаток папки проектов (без чтения файлов).

        (число .ob.json, max mtime, суммарный размер). Повторное
        нажатие «Подтянуть» с тем же отпечатком пропускает
        import_projects — только быстрый bulk-поиск по TM.
        """
        count = 0
        max_mtime = 0.0
        total = 0
        try:
            names = os.listdir(projects_dir)
        except OSError:
            return (0, 0.0, 0)
        for name in names:
            if not name.endswith(".ob.json"):
                continue
            p = os.path.join(projects_dir, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            count += 1
            total += st.st_size
            if st.st_mtime > max_mtime:
                max_mtime = st.st_mtime
        return (count, max_mtime, total)

    def get_fuzzy(
        self,
        source: str,
        src_lang: str,
        tgt_lang: str,
        threshold: float = 0.85,
    ) -> tuple[str, str, float] | None:
        """Нечёткий поиск: лучший кандидат (source, target, score).

        Кандидаты — записи той же пары языков с тем же первым символом
        нормализованной строки (LIMIT 200), сходство —
        difflib.SequenceMatcher. Возвращает None если ничего не дотянуло
        до threshold.
        """
        norm = normalize_source(source)
        if not norm:
            return None
        prefix = norm[:1]
        with self._lock:
            rows = self.db.execute(
                "SELECT source, target, norm_source FROM tm2"
                " WHERE src_lang=? AND tgt_lang=?"
                " AND substr(norm_source, 1, 1)=?"
                " LIMIT 200",
                (src_lang, tgt_lang, prefix),
            ).fetchall()
        best: tuple[str, str, float] | None = None
        for cand_source, cand_target, cand_norm in rows:
            score = difflib.SequenceMatcher(None, norm, cand_norm).ratio()
            if score >= threshold and (best is None or score > best[2]):
                best = (cand_source, cand_target, score)
        return best

    def suggest_all(
        self,
        source: str,
        src_lang: str,
        tgt_lang: str,
        limit: int = 5,
        threshold: float = 0.5,
    ) -> list[dict]:
        """Несколько вариантов для UI: [{source, target, score}, ...].

        Отсортированы по убыванию score. Точное/норм-совпадение (score=1.0)
        идёт первым, если есть.
        """
        out: list[dict] = []
        exact = self.get(source, src_lang, tgt_lang)
        if exact is not None:
            out.append({"source": source, "target": exact, "score": 1.0})
        norm = normalize_source(source)
        if not norm:
            return out[:limit]
        prefix = norm[:1]
        with self._lock:
            rows = self.db.execute(
                "SELECT source, target, norm_source FROM tm2"
                " WHERE src_lang=? AND tgt_lang=?"
                " AND substr(norm_source, 1, 1)=?"
                " LIMIT 200",
                (src_lang, tgt_lang, prefix),
            ).fetchall()
        scored: list[dict] = []
        for cand_source, cand_target, cand_norm in rows:
            if exact is not None and cand_norm == norm:
                continue  # уже отдан как точное
            score = difflib.SequenceMatcher(None, norm, cand_norm).ratio()
            if score >= threshold:
                scored.append(
                    {"source": cand_source, "target": cand_target,
                     "score": score}
                )
        scored.sort(key=lambda d: d["score"], reverse=True)
        out.extend(scored)
        return out[:limit]

    # ---------- запись ----------
    def put(self, source: str, target: str, src_lang: str, tgt_lang: str,
            engine: str = "", project: str = ""):
        self.put_many([(source, target)], src_lang, tgt_lang,
                       engine=engine, project=project)

    def put_many(self, pairs: list[tuple[str, str]], src_lang: str,
                 tgt_lang: str, engine: str = "", project: str = ""):
        """Батч в одной транзакции: executemany + один commit."""
        if not pairs:
            return
        now = int(time.time())
        legacy = [(s, src_lang, tgt_lang, t) for s, t in pairs]
        modern = [
            (normalize_source(s), s, src_lang, tgt_lang, t,
             engine, project, now)
            for s, t in pairs
        ]
        with self._lock:
            self.db.executemany(
                "INSERT OR REPLACE INTO tm (source, src_lang, tgt_lang, target)"
                " VALUES (?,?,?,?)",
                legacy,
            )
            self.db.executemany(
                "INSERT INTO tm2 (norm_source, source, src_lang, tgt_lang,"
                " target, engine, project, updated, hits)"
                " VALUES (?,?,?,?,?,?,?, ?, 0)"
                " ON CONFLICT(norm_source, src_lang, tgt_lang) DO UPDATE SET"
                " source=excluded.source, target=excluded.target,"
                " engine=excluded.engine, project=excluded.project,"
                " updated=excluded.updated, hits=tm2.hits+1",
                modern,
            )
            self.db.commit()

    # ---------- статистика / импорт ----------
    def stats(self) -> dict:
        """{'total': число записей, 'hits': суммарные попадания}."""
        with self._lock:
            total = self.db.execute("SELECT COUNT(*) FROM tm2").fetchone()[0]
            hits = self.db.execute(
                "SELECT COALESCE(SUM(hits), 0) FROM tm2").fetchone()[0]
        return {"total": total, "hits": hits}

    def import_projects(self, projects_dir: str) -> int:
        """Залить переводы из всех *.ob.json в tm2 батчами по 500.

        Это и есть reuse между проектами: новый проект подхватывает уже
        переведённое из других проектов при одинаковых строках (через
        get() — точное + нормализованное совпадение — или через
        Translator.prefill_from_memory()).

        Берёт только записи с непустым translation. Языки — из полей
        проекта source_lang/target_lang (fallback 'auto'/'ru').
        Возвращает число импортированных пар.
        """
        # группируем по (src, tgt, project), чтобы батчи были однородными
        groups: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
        for path in sorted(glob.glob(os.path.join(projects_dir, "*.ob.json"))):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            src = data.get("source_lang") or "auto"
            tgt = data.get("target_lang") or "ru"
            proj = os.path.splitext(os.path.basename(path))[0]
            entries = data.get("entries") or []
            for e in entries:
                orig = (e.get("original") or "")
                trans = (e.get("translation") or "")
                if not orig or not trans.strip():
                    continue
                groups.setdefault((src, tgt, proj), []).append((orig, trans))
        total = 0
        for (src, tgt, proj), pairs in groups.items():
            # дедуп внутри проекта по норм-строке: последний перевод побеждает
            dedup: dict[str, tuple[str, str]] = {}
            for s, t in pairs:
                dedup[normalize_source(s)] = (s, t)
            merged = list(dedup.values())
            for i in range(0, len(merged), 500):
                chunk = merged[i:i + 500]
                self.put_many(chunk, src, tgt, project=proj)
                total += len(chunk)
        return total

    def close(self):
        with self._lock:
            self.db.close()

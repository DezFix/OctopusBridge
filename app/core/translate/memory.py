# -*- coding: utf-8 -*-
"""Память переводов (SQLite): повторное использование переводов между сессиями.

Потокобезопасна: соединение создаётся с check_same_thread=False, все
операции защищены блокировкой — можно вызывать из потока перевода.
"""
from __future__ import annotations

import sqlite3
import threading


class TranslationMemory:
    def __init__(self, db_path: str):
        self._lock = threading.RLock()
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        with self._lock:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS tm ("
                " source TEXT NOT NULL,"
                " src_lang TEXT NOT NULL,"
                " tgt_lang TEXT NOT NULL,"
                " target TEXT NOT NULL,"
                " PRIMARY KEY (source, src_lang, tgt_lang))"
            )
            self.db.commit()

    def get(self, source: str, src_lang: str, tgt_lang: str) -> str | None:
        with self._lock:
            row = self.db.execute(
                "SELECT target FROM tm WHERE source=? AND src_lang=? AND tgt_lang=?",
                (source, src_lang, tgt_lang),
            ).fetchone()
        return row[0] if row else None

    def put(self, source: str, target: str, src_lang: str, tgt_lang: str):
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO tm (source, src_lang, tgt_lang, target)"
                " VALUES (?,?,?,?)",
                (source, src_lang, tgt_lang, target),
            )
            self.db.commit()

    def put_many(self, pairs: list[tuple[str, str]], src_lang: str, tgt_lang: str):
        with self._lock:
            self.db.executemany(
                "INSERT OR REPLACE INTO tm (source, src_lang, tgt_lang, target)"
                " VALUES (?,?,?,?)",
                [(s, src_lang, tgt_lang, t) for s, t in pairs],
            )
            self.db.commit()

    def close(self):
        with self._lock:
            self.db.close()

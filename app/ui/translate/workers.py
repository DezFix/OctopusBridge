# -*- coding: utf-8 -*-
"""Фоновые воркеры вкладки перевода (QThread, без прямого доступа к UI).

Извлечение и перевод гоняются здесь, результат уходит сигналами
в TranslateTab. Раньше жили в app/ui/translate_tab.py.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from app.core.translate.service import Translator
from app.ui.i18n import TR


class ExtractWorker(QThread):
    """Фоновое извлечение текста из игры (не морозит GUI)."""

    done = Signal(object)       # list[TranslationEntry]
    failed = Signal(str)

    def __init__(self, module, game_dir: str, extract_lang: str | None = None):
        super().__init__()
        self.setObjectName("ExtractWorker")
        self._module = module
        self._game_dir = game_dir
        self._extract_lang = extract_lang

    def run(self):
        try:
            if self._extract_lang and hasattr(self._module, "list_languages"):
                entries = self._module.extract(self._game_dir, self._extract_lang)
            else:
                entries = self._module.extract(self._game_dir)
            if not self.isInterruptionRequested():
                self.done.emit(entries)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class TranslateWorker(QThread):
    progressed = Signal(int, int)
    done = Signal(int, int)     # (переведено, на целевом языке — пропущено)
    left = Signal(int)          # осталось не переведённым (ждали провайдера)
    status = Signal(str)        # текстовый этап (пинг/память/ожидание)
    failed = Signal(str)

    def __init__(self, translator: Translator, entries, src, tgt,
                 overwrite=False, prefill: bool = False,
                 ping_hint: str = ""):
        super().__init__()
        self.setObjectName("TranslateWorker")
        self.translator = translator
        self.entries = entries
        self.src = src
        self.tgt = tgt
        self.overwrite = overwrite
        self.prefill = prefill
        # Текст ошибки при недоступном движке (готовит GUI-поток без
        # сети; сам ping — только здесь, в фоне).
        self.ping_hint = ping_hint

    def run(self):
        try:
            # Проверка связи — в фоне: ping() ходит в сеть (Google +
            # Bing-токены) и в GUI-потоке морозил окно на десятки секунд.
            # Этапы шлём текстом: иначе «Перевожу» висит без прогресса,
            # пока ping/prefill молчат.
            self.status.emit(TR("tr_status_ping"))
            try:
                alive = self.translator.engine.ping()
            except Exception:  # noqa: BLE001 — ping не обязан отвечать
                alive = False
            if self.isInterruptionRequested():
                return
            if not alive:
                self.failed.emit(
                    self.ping_hint or "translation provider unavailable")
                return

            def progress_check(d, t):
                if self.isInterruptionRequested():
                    raise InterruptedError("cancelled")
                self.progressed.emit(d, t)
            # Сначала память переводов: повторы и уже переведённые ранее
            # строки уходят из сети нулём запросов.
            if self.prefill and not self.overwrite:
                self.status.emit(TR("tr_status_memory"))
                try:
                    self.translator.prefill_from_memory(
                        self.entries, self.src, self.tgt)
                except InterruptedError:
                    raise
                except Exception:  # noqa: BLE001 — память не обязательна
                    pass
                self.progressed.emit(0, max(len(self.entries), 1))
            n = self.translator.translate_entries(
                self.entries, self.src, self.tgt,
                progress=progress_check,
                overwrite=self.overwrite,
                status_cb=self.status.emit)
            skipped = sum(
                1 for e in self.entries
                if e.status == "skip" and not (e.translation or "").strip())
            if not self.isInterruptionRequested():
                self.left.emit(len(self.translator.failed))
                self.done.emit(n, skipped)
        except InterruptedError:
            pass
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
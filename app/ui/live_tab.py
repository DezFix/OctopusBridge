# -*- coding: utf-8 -*-
"""Вкладка «Реалтайм»: запуск игры + перевод + лог."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit,
                                QPushButton, QVBoxLayout, QWidget)

from app.core import process as proc
from app.ui.i18n import TR


class LiveTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._autowatch_failed: set[int] = set()
        self._autowatch_busy = False
        self._probe = None

        lay = QVBoxLayout(self)

        # ── кнопки запуска/остановки ──
        row = QHBoxLayout()
        self.btn_launch = QPushButton(TR("live_start"))
        self.btn_launch.setObjectName("accent")
        self.btn_launch.clicked.connect(self.start_live)
        row.addWidget(self.btn_launch)

        self.btn_stop = QPushButton(TR("live_stop"))
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_live)
        row.addWidget(self.btn_stop)
        row.addStretch(1)
        lay.addLayout(row)

        # ── статус ──
        self.lbl_status = QLabel(TR("live_stopped"))
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        lay.addWidget(QLabel(TR("live_log")))

        # ── лог ──
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        lay.addWidget(self.log_view, 1)

        # ── сигналы ──
        self.main.bridge_client.connect(self._on_client)
        self.main.bridge_translated.connect(self._on_translated)
        self.main.bridge_log.connect(self._log)
        self.main.session.game_exited.connect(self._on_game_exited)

        # автопоимка запущенной игры
        self._autowatch = QTimer(self)
        self._autowatch.timeout.connect(self._autowatch_tick)
        self._autowatch.start(2500)

    def cleanup(self):
        self._autowatch.stop()
        probe = self._probe
        if probe and probe.isRunning():
            probe.wait(4000)

    # ── запуск ──
    def start_live(self):
        game_dir = self.main.project.game_dir if self.main.project else ""
        if not game_dir:
            self._log(TR("live_no_game_dir"))
            return
        self._log(TR("live_starting"))
        self.btn_launch.setEnabled(False)
        engine = self.main.create_engine("realtime")
        fn = self.main.build_translate_fn(engine) if engine and engine.ping() \
            else (lambda text: text)
        ok = self.main.start_session(game_dir, fn)
        if not ok:
            self.btn_launch.setEnabled(True)

    def _stop_live(self):
        self.main.stop_session()
        self.btn_launch.setEnabled(True)
        self.btn_stop.setEnabled(False)

    # ── движок ──
    def _engine_key(self) -> str:
        mod = self.main.engine_module
        return mod.key if mod else ""

    # ── автопоимка ──
    def _autowatch_tick(self):
        if self._autowatch_busy:
            return
        if self.main.session.is_connecting() or not self.isVisible():
            return
        if self.main.session.is_active():
            return
        engine = self._engine_key()
        if engine not in ("rpgmaker", "renpy"):
            return
        game_dir = self.main.project.game_dir if self.main.project else ""
        for p in proc.find_game_processes(engine, game_dir):
            pid = p["pid"]
            if pid in self._autowatch_failed:
                continue
            if engine == "renpy":
                self._attach_auto(pid, 0)
                return
            if p.get("port"):
                self._attach_auto(pid, p["port"])
                return
            self._autowatch_busy = True
            from PySide6.QtCore import QThread

            class _Probe(QThread):
                def __init__(self, pid):
                    super().__init__()
                    self.setObjectName("AutowatchProbe")
                    self._pid = pid

                def run(self):
                    from app.engines.rpgmaker.tentacle import probe_game_port
                    self._result = probe_game_port(self._pid)

            self._probe = _Probe(pid)
            self._probe.finished.connect(
                lambda pid=pid: self._on_probed(pid))
            self._probe.start()
            return

    def _on_probed(self, pid: int):
        port = getattr(self._probe, "_result", 0)
        self._probe.deleteLater()
        self._probe = None
        self._autowatch_busy = False
        if not proc.pid_exists(pid):
            return
        if not port:
            self._autowatch_failed.add(pid)
            return
        self._attach_auto(pid, port)

    def _attach_auto(self, pid: int, port: int):
        self._log(TR("live_autofound", pid=pid))
        engine = self.main.create_engine("realtime")
        fn = self.main.build_translate_fn(engine) if engine and engine.ping() \
            else None
        if not self.main.start_session("", fn,
                                       attach_pid=pid, port_hint=port):
            self._autowatch_failed.add(pid)

    # ── события ──
    def _on_client(self, connected: bool):
        if connected:
            self.lbl_status.setText(TR("live_connected"))
            self.btn_launch.setEnabled(False)
            self.btn_stop.setEnabled(True)
        else:
            self.lbl_status.setText(TR("live_waiting"))
            self.btn_launch.setEnabled(True)
            self.btn_stop.setEnabled(False)

    def _on_game_exited(self):
        self._log(TR("live_game_closed"))
        self._autowatch_failed.clear()
        self.lbl_status.setText(TR("live_stopped_hint"))
        self.btn_launch.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def _on_translated(self, original: str, translation: str):
        self._log(f"{original}  =>  {translation}")

    def _log(self, text: str):
        self.log_view.appendPlainText(text)
        doc = self.log_view.document()
        while doc.blockCount() > 500:
            cursor = self.log_view.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.select(QTextCursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

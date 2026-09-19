# -*- coding: utf-8 -*-
"""Проверка новой версии OctopusBridge на GitHub.

При старте приложения асинхронно опрашиваем GitHub API (latest release)
и показываем ненавязчивое уведомление, если нашли более новую версию.
Ошибки сети молча игнорируются — приложение не обязано быть онлайн.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import (QNetworkAccessManager, QNetworkReply,
                               QNetworkRequest)
from PySide6.QtWidgets import QMessageBox

import app
from app.ui.i18n import TR

# API GitHub: последний релиз репозитория.
_RELEASES_URL = ("https://api.github.com/repos/DezFix/OctopusBridge/"
                 "releases/latest")

_TAG_RE = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?(?:[-+].*)?")


def _parse_version(tag: str) -> tuple[int, int, int] | None:
    m = _TAG_RE.match(tag.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)),
            int(m.group(3) or 0))


def _is_newer(new: tuple[int, int, int],
              cur: tuple[int, int, int]) -> bool:
    return new > cur


def _show_update_dialog(parent, version: str, url: str) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(TR("update_title"))
    box.setIcon(QMessageBox.Icon.Information)
    box.setText(TR("update_found", v=version))
    box.setInformativeText(TR("update_open_release"))
    btn_open = box.addButton(TR("update_open"),
                             QMessageBox.ButtonRole.AcceptRole)
    box.addButton(TR("update_later"),
                  QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is btn_open:
        QDesktopServices.openUrl(QUrl(url))


def check_for_updates(parent=None, delay_ms: int = 1500) -> None:
    """Проверка в фоне: GitHub → latest release → уведомление.

    Вызывается при старте приложения. Сеть недоступна или версия не
    отличается — молча выходим.
    """
    from PySide6.QtCore import QTimer

    def _run():
        try:
            _query(parent)
        except Exception:  # noqa: BLE001 — молча, иначе старт тормозит
            pass

    QTimer.singleShot(delay_ms, _run)


# P0: долгоживущие ссылки на QNetworkAccessManager — локальный net
# умирал вместе с _query() до прихода reply (GC Python-обёртки).
_ACTIVE_NETS: list = []


def _query(parent) -> None:
    from PySide6.QtCore import QTimer

    net = QNetworkAccessManager(parent)
    _ACTIVE_NETS.append(net)

    def _release():
        try:
            _ACTIVE_NETS.remove(net)
        except ValueError:
            pass
        try:
            net.deleteLater()
        except RuntimeError:
            pass

    def _on_reply(reply: QNetworkReply):
        _release()
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            return
        data = bytes(reply.readAll()).decode("utf-8", "replace")
        try:
            import json
            payload = json.loads(data)
            tag = str(payload.get("tag_name", "") or "")
            url = str(payload.get("html_url", "") or "")
        except (ValueError, TypeError):
            return
        if not tag or not url:
            return
        new = _parse_version(tag)
        cur = _parse_version(app.__version__)
        if not new or not cur or not _is_newer(new, cur):
            return
        _show_update_dialog(parent, tag.lstrip("v"), url)

    req = QNetworkRequest(QUrl(_RELEASES_URL))
    req.setRawHeader(b"User-Agent", b"OctopusBridge")
    reply = net.get(req)
    reply.finished.connect(lambda: _on_reply(reply))

    def _timeout():
        # 10с без ответа — рвём запрос; finished придёт с ошибкой
        # OperationCanceledError и _on_reply молча выйдет + освободит net.
        try:
            if reply.isRunning():
                reply.abort()
        except RuntimeError:
            _release()

    QTimer.singleShot(10000, _timeout)

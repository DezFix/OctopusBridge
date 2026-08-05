# -*- coding: utf-8 -*-
"""Точка входа OctopusBridge."""
import os
import subprocess
import sys
import traceback

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

import app as app_paths
from app.ui.main_window import MainWindow
from app.ui.theme import apply_dark_theme

CRASH_LOG = app_paths.crash_log_path()


def _excepthook(exc_type, exc_value, exc_tb):
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n=== {__import__('datetime').datetime.now()} ===\n{text}")
        try:
            subprocess.Popen(["notepad", CRASH_LOG])
        except OSError:
            os.startfile(CRASH_LOG)
    except OSError:
        pass
    QMessageBox.critical(None, "Error",
                         f"{exc_type.__name__}: {exc_value}\n"
                         f"(see crash.log)")
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def main():
    # офлайн-модели honyaku: models/ рядом с приложением (автономная работа)
    app_paths.ensure_honyaku_env()
    app = QApplication(sys.argv)
    app.setApplicationName("OctopusBridge")
    icon_path = app_paths.icon_path()
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    apply_dark_theme(app)
    window = MainWindow()
    window.show()
    sys.excepthook = _excepthook
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

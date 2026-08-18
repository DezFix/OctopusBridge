# -*- coding: utf-8 -*-
"""Точка входа OctopusBridge."""
import os
import subprocess
import sys


def main():
    import traceback

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    import app as app_paths
    from app.ui.main_window import MainWindow
    from app.ui.theme import apply_dark_theme

    crash_log = app_paths.crash_log_path()

    def _excepthook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with open(crash_log, "a", encoding="utf-8") as f:
                f.write(f"\n=== {__import__('datetime').datetime.now()} ===\n{text}")
            try:
                subprocess.Popen(["notepad", crash_log])
            except OSError:
                os.startfile(crash_log)
        except OSError:
            pass
        QMessageBox.critical(None, "Error",
                             f"{exc_type.__name__}: {exc_value}\n"
                             f"(see crash.log)")
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    app = QApplication(sys.argv)
    app.setApplicationName("OctopusBridge")
    icon_path = app_paths.icon_path()
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    apply_dark_theme(app)
    from PySide6.QtCore import QSettings
    from app.ui.setup_wizard import SetupWizard
    if not QSettings("OctopusBridge", "OctopusBridge").value(
            "setup_done", False, type=bool):
        wizard = SetupWizard()
        wizard.exec()
    window = MainWindow()
    window.show()
    sys.excepthook = _excepthook
    from app.ui.updates import check_for_updates
    check_for_updates(window)
    sys.exit(app.exec())


if __name__ == "__main__":
    # Окно Twine (WebView2) в отдельном процессе: во frozen-сборке это
    # второй экземпляр exe с флагом (pythonw.exe рядом с exe нет, а
    # обычный перезапуск открыл бы ещё одно окно приложения).
    # PySide6 при этом не грузится — окно стартует быстро.
    if "--webapp-window" in sys.argv:
        from app.engines.twine import webapp
        try:
            _i = sys.argv.index("--webapp-window")
            _url, _title, _profile, _icon = sys.argv[_i + 1:_i + 5]
        except (ValueError, IndexError):
            sys.exit(2)
        webapp._run_window(_url, _title, _profile, _icon)
        sys.exit(0)
    main()

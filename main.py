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
    # Родитель для диалога ошибки (назначается после создания MainWindow).
    _window_ref: list = [None]

    def _rotate_crash_log(path: str, limit: int = 2 * 1024 * 1024) -> None:
        """Ручная ротация: если crash.log > limit — сдвигаем в .1.bak."""
        try:
            if os.path.isfile(path) and os.path.getsize(path) > limit:
                bak = path + ".1.bak"
                try:
                    if os.path.isfile(bak):
                        os.remove(bak)
                except OSError:
                    pass
                os.replace(path, bak)
        except OSError:
            pass

    def _excepthook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            _rotate_crash_log(crash_log)
            with open(crash_log, "a", encoding="utf-8") as f:
                f.write(f"\n=== {__import__('datetime').datetime.now()} ===\n{text}")
        except OSError:
            pass
        # Безопасно для не-GUI потока: диалог только через try,
        # автооткрытие лога убрано — только кнопка «Открыть лог».
        try:
            from PySide6.QtWidgets import QApplication as _QA
            if _QA.instance() is not None:
                parent = _window_ref[0]
                box = QMessageBox(
                    parent if parent is not None else None)
                box.setWindowTitle("Error")
                box.setIcon(QMessageBox.Icon.Critical)
                box.setText(f"{exc_type.__name__}: {exc_value}\n"
                            f"(see crash.log)")
                btn_open = box.addButton(
                    "Открыть лог",
                    QMessageBox.ButtonRole.ActionRole)
                box.addButton(QMessageBox.StandardButton.Close)
                box.exec()
                if box.clickedButton() is btn_open:
                    try:
                        os.startfile(crash_log)  # noqa: S606
                    except OSError:
                        try:
                            subprocess.Popen(["notepad", crash_log])
                        except OSError:
                            pass
        except Exception:  # noqa: BLE001 — диалог не должен ронять excepthook
            pass
        try:
            sys.__excepthook__(exc_type, exc_value, exc_tb)
        except Exception:  # noqa: BLE001
            pass

    # Ставим ПЕРВЫМ — до QApplication/MainWindow, чтобы ловить
    # ошибки инициализации (тема, визард, главное окно).
    sys.excepthook = _excepthook

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
    _window_ref[0] = window
    window.show()
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

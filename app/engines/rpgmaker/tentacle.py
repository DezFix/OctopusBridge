# -*- coding: utf-8 -*-
"""Щупальце RPG Maker MV/MZ — два профиля.

MZ (и Electron/asar-сборки MV): CDP-внедрение в NW.js-процесс игры,
запуск с --remote-debugging-port, Runtime.evaluate + JS-пейлоад.

MV (официальный десктопный рантайм): non-SDK NW.js без remote
debugging — канал через мост octopus_ob.js (HTTP-сервер внутри игры,
см. app.core.rpgmaker.mv_bridge). Весь API (evaluate/request_state/
apply_translation) прозрачно роутится через мост.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time

from app.core import process as proc
from app.transport.cdp import browser
from app.core.tentacles.cdp_base import (
    CDPTentacle, DEFAULT_SCAN_PORTS, bruteforce_port,
    cdp_page_is_game,
    probe_game_port as _base_probe,
)
from app.core.translate.service import build_tr_dict  # noqa: F401 — реэкспорт
from app.core.rpgmaker import mv_bridge
from app.core.rpgmaker import variant as rpgm_variant
from app.core.rpgmaker.payloads import PAYLOAD, _TRANSLATION_PAYLOAD

# Кандидаты портов для сканирования (алиас общей константы из cdp_base;
# оставлено для совместимости импортов).
SCAN_PORTS = DEFAULT_SCAN_PORTS

# признак страницы RPG Maker / NW.js
_RPGM_PROBE = ("!!(window.$gameMessage || window.$dataSystem || "
               "(window.nw && window.nw.Window))")

# PAYLOAD и _TRANSLATION_PAYLOAD — в app.core.rpgmaker.payloads
# (ядро без Qt; здесь реэкспорт для совместимости).
# build_tr_dict — канонический из app.core.translate.service
# (здесь реэкспорт для совместимости: from ...tentacle import build_tr_dict).


def _nwjs_profile_dirs(game_dir: str) -> list[str]:
    """Возможные каталоги профиля NW.js (user-data-dir).

    По умолчанию NW.js держит профиль в папке приложения, но многие
    игры задают --user-data-dir в chromium-args, а часть движков
    (например, runtime RPG Maker MV) кладёт профиль в
    %LOCALAPPDATA%\\<name>\\User Data по имени из package.json.
    """
    dirs = [game_dir]
    local = os.environ.get("LOCALAPPDATA")
    try:
        with open(os.path.join(game_dir, "package.json"),
                  encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        manifest = None
    args = (manifest or {}).get("chromium-args")
    if isinstance(args, str):
        for m in re.finditer(r"--user-data-dir=(?:\"([^\"]+)\"|(\S+))", args):
            path = m.group(1) or m.group(2)
            if path:
                resolved = path if os.path.isabs(path) else os.path.join(
                    game_dir, path)
                if resolved not in dirs:
                    dirs.append(os.path.abspath(resolved))
    if not local:
        return dirs
    name = (manifest or {}).get("name")
    if isinstance(name, str) and name.strip():
        base = local
        for part in re.split(r"[\\/]+", name.strip()):
            if part:
                base = os.path.join(base, part)
    else:
        base = os.path.join(local, "nwjs")
    for d in (base, os.path.join(base, "User Data"),
              os.path.join(local, "User Data"),  # MV runtime (пустой name)
              os.path.join(local, "KADOKAWA", "RPGMV"),
              os.path.join(local, "KADOKAWA", "RPGMV", "User Data"),
              os.path.join(local, "KADOKAWA", "RPGMZ"),
              os.path.join(local, "KADOKAWA", "RPGMZ", "User Data")):
        if d not in dirs:
            dirs.append(d)
    return dirs


def _is_stale_version(value) -> bool:
    """user_data_version из Local State: число или числовая строка.

    Chromium пишет ключ то числом, то строкой — принимаем оба варианта,
    иначе «протухший» профиль остаётся незамеченным и ошибка вернётся.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str) and value.strip().isdigit():
        return True
    return False


def _has_stale_profile(profile_dir: str) -> bool:
    """True, если в профиле есть Local State от более новой версии NW.js."""
    ls = os.path.join(profile_dir, "Local State")
    if not os.path.isfile(ls):
        return False
    try:
        with open(ls, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    return _is_stale_version(data.get("user_data_version"))


def _rename_if_exists(path: str) -> bool:
    """Переименовывает файл в path.bak с ретраями.

    Запущенный NW.js-процесс держит файлы профиля залоченными — при
    первом OSError пробуем ещё пару раз с паузой.
    """
    if not os.path.isfile(path):
        return False
    bak = path + ".bak"
    for _ in range(3):
        try:
            if os.path.exists(bak):
                os.remove(bak)
            os.rename(path, bak)
            return True
        except OSError:
            time.sleep(0.4)
    return False


def clean_nwjs_profile(game_dir: str) -> list[str]:
    """Чинит «Ваш профиль не может использоваться, поскольку он от более
    новой версии NW.js».

    Причина: Chromium мигрирует профиль только «вперёд» — если игру
    раньше запускали более новой сборкой NW.js (или профиль общий:
    у MV-игр с пустым name в package.json это %LOCALAPPDATA%\\nwjs),
    старая NW.js не может прочитать базы нового формата и показывает
    эту ошибку. Официальная рекомендация nwjs и сообщества RPG Maker —
    очистить каталог профиля.

    Файлы, где «зашита» версия: Local State (механизм Chromium) и
    Default/Web Data*, Default/Preferences. Их не удаляем, а
    переименовываем в *.bak — NW.js создаст свежий профиль. Каталог
    Default/Local Storage не трогаем (localStorage плагинов), а сейвы
    RPG Maker лежат в www/save — профиль их не содержит.

    Возвращает список каталогов профилей, где что-то переименовано.
    """
    renamed = []
    for d in _nwjs_profile_dirs(game_dir):
        ls = os.path.join(d, "Local State")
        default_dir = os.path.join(d, "Default")
        # «протухший» профиль: маркер версии в Local State ИЛИ реально
        # использованный профиль (Web Data/Preferences) — именно там, по
        # опыту сообщества RPG Maker, зашита версия, из-за которой
        # старая NW.js показывает «профиль от более новой версии»
        dirty = (_has_stale_profile(d)
                 or os.path.isfile(os.path.join(default_dir, "Web Data"))
                 or os.path.isfile(
                     os.path.join(default_dir, "Web Data-journal"))
                 or os.path.isfile(
                     os.path.join(default_dir, "Preferences"))
                 or os.path.isfile(
                     os.path.join(default_dir, "Secure Preferences")))
        if not dirty:
            continue
        if _rename_if_exists(ls):
            renamed.append(d)
        if os.path.isdir(default_dir):
            for name in ("Web Data", "Web Data-journal",
                         "Preferences", "Secure Preferences"):
                _rename_if_exists(os.path.join(default_dir, name))
        if not renamed or renamed[-1] != d:
            renamed.append(d)
    return renamed


class RpgMakerTentacle(CDPTentacle):
    key = "rpgmaker"
    title = "RPG Maker (CDP)"
    PAYLOAD = PAYLOAD

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: subprocess.Popen | None = None
        self._bridge_port = 0
        self._variant = ""

    # ── запуск ──
    def launch(self, target: str) -> bool:
        exe = target
        if os.path.isdir(target):
            # имя exe произвольное (Aochikano.exe, tropical-chase.exe...),
            # а не только Game.exe
            found = rpgm_variant.find_game_exe(target)
            if not found:
                self.error.emit(
                    f"Не найден исполняемый файл игры в папке: {target} "
                    f"(нет *.exe кроме хелперов NW.js)")
                return False
            exe = found
        if not os.path.isfile(exe):
            self.error.emit(f"Не найден исполняемый файл игры: {exe}")
            return False
        self.log.emit(f"Запускаю: {os.path.basename(exe)}")
        game_dir = os.path.dirname(exe)
        self._game_dir = game_dir
        self._variant = rpgm_variant.detect_variant(game_dir)
        is_mv = self._variant == "mv"

        # Игра уже запущена? NW.js (single-instance) не даёт второму
        # экземпляру поднять отладочный порт — поэтому подключаемся
        # к уже запущенному процессу, а без порта перезапускаем его
        # с --remote-debugging-port (иначе читы молча не работают).
        norm_dir = os.path.normpath(game_dir).lower()
        for r in proc.find_game_processes("rpgmaker", game_dir):
            if not os.path.normpath(r["exe"]).lower().startswith(norm_dir):
                continue  # чужая игра — не трогаем
            pid = r["pid"]
            if r["port"]:
                self.log.emit(
                    f"Игра уже запущена (pid {pid}, отладка "
                    f":{r['port']}) — подключаюсь к ней.")
                self._pid = pid
                if self._connect_page(r["port"], url_hint=".html",
                                      wait=10.0):
                    return True
                self._pid = None
                self.log.emit(
                    "Не удалось подключиться к запущенной игре — "
                    "перезапускаю её с отладкой.")
            else:
                if is_mv:
                    # MV: CDP недоступен, но мост мог подняться (плагин
                    # уже в игре) — подключаемся, ничего не закрывая
                    bport = mv_bridge.find_bridge_port(wait=5.0)
                    if bport:
                        self.log.emit(
                            f"Игра уже запущена с мостом (pid {pid}) — "
                            f"подключаюсь к :{bport}.")
                        self._pid = pid
                        self._bridge_port = bport
                        self.attached.emit()
                        return True
                self.log.emit(
                    f"Игра запущена без отладки (pid {pid}) — закрываю "
                    "и запускаю заново с отладочным портом.")
            # Защита от убийства чужого процесса: PID мог переиспользоваться
            # ОС между find_game_processes и terminate, либо exe уже другой
            # (обновление/перезапись). Сверяем живой exe path с папкой нашей
            # игры; сомневаемся — только log, terminate не зовём. Второй
            # рубеж — сам proc.terminate(expected_dir=...) сверяет exe/cmdline
            # через psutil перед убийством.
            _live_exe = proc.exe_of(pid)
            if not _live_exe or not os.path.normpath(
                    _live_exe).lower().startswith(norm_dir):
                self.log.emit(
                    f"PID {pid} больше не принадлежит игре "
                    f"({_live_exe or 'нет exe'}) — не завершаю, "
                    "запускаю новый экземпляр.")
                break
            try:
                _killed = proc.terminate(
                    pid, timeout=5.0, expected_dir=game_dir)
            except TypeError:
                # мок в старых тестах без expected_dir — старый вызов
                _killed = proc.terminate(pid, timeout=5.0)
            if not _killed:
                self.error.emit(
                    "Не удалось закрыть уже запущенную игру. "
                    "Закройте её вручную и нажмите «Запустить» снова.")
                return False
            time.sleep(1.5)  # освободить порт и профиль NW.js
            break

        port = browser.free_port()
        if clean_nwjs_profile(game_dir):
            self.log.emit(
                "Профиль NW.js от другой версии: Local State переименован "
                "в Local State.bak (сейвы не тронуты).")
        if is_mv:
            # плагин-мост должен лежать в игре ДО старта: иначе игра
            # прочитает plugins.js без него и мост не поднимется
            if mv_bridge.ensure_bridge_registered(
                    game_dir, self.PAYLOAD, _TRANSLATION_PAYLOAD):
                self.log.emit(
                    "Мост MV внедрён: js/plugins/octopus_ob.js.")
        try:
            self._proc = subprocess.Popen(
                [exe, f"--remote-debugging-port={port}"],
                cwd=game_dir)
        except OSError as e:
            self.error.emit(f"Не удалось запустить игру: {e}")
            return False
        self._pid = self._proc.pid
        self.log.emit(f"Игра запущена (pid {self._pid}).")
        if is_mv:
            return self._launch_mv(port)
        self.log.emit(f"Отладка :{port}.")
        if not self._connect_page(port, url_hint=".html", wait=30.0):
            # NW.js мог поднять отладчик на другом порту (занятый
            # порт/инкремент) — ищем фактический до того, как сдаваться
            actual = probe_game_port(self._pid) if self._pid else 0
            if actual and actual != port:
                self.log.emit(
                    f"Отладка поднялась на :{actual} — подключаюсь туда.")
                if self._connect_page(actual, url_hint=".html", wait=10.0):
                    return True
            # ВАЖНО: игру НЕ убиваем — перевод через ob_runtime.js
            # работает и без CDP, а убийство выглядит как
            # «кнопка не работает» (окно вспыхнуло и закрылось).
            # Такое бывает при --disable-devtools в package.json
            # (обе лабораторные игры) — порт просто не поднимается.
            # Честно: читов нет => attached не эмитим и возвращаем False,
            # чтобы UI показал ошибку, а не «подключено». Игра остаётся
            # запущенной (перевод через файлы работает).
            self.log.emit(
                "Отладчик недоступен (в package.json есть "
                "--disable-devtools?) — игра остаётся запущенной, "
                "перевод работает через ob_runtime.js.")
            self.error.emit(
                "Запущено без читов (нет debug-порта): игра осталась "
                "запущенной, читы недоступны до перезапуска с отладкой.")
            return False
        return True

    def _launch_mv(self, port: int) -> bool:
        """MV-профиль: мост вместо CDP (non-SDK NW.js, отладка вырезана).

        Перед стартом гарантируем наличие плагина-моста в игре (если его
        ещё нет — например, игру ещё не переводили). Затем ждём HTTP-мост;
        на расширенной (SDK) сборке запасной путь — CDP. Если не вышло
        ни то, ни другое, игру НЕ закрываем: перевод работает через файлы.
        """
        self.log.emit("Жду мост MV (официальный рантайм без CDP)…")
        bport = mv_bridge.find_bridge_port(wait=35.0)
        if bport:
            self._bridge_port = bport
            self.log.emit(
                f"Мост подключён: http://127.0.0.1:{bport}")
            self._log_game_errors(bport)
            self.attached.emit()
            return True
        if self._connect_page(port, url_hint=".html", wait=10.0):
            self.log.emit("Подключено через CDP (расширенная сборка).")
            return True
        # Честно: моста и CDP нет => читы недоступны, attached не эмитим.
        self.log.emit(
            "Игра запущена без отладки: официальный рантайм MV "
            "не поддерживает remote debugging.")
        self.error.emit(
            "Запущено без читов (нет debug-порта и моста MV): игра "
            "осталась запущенной, перевод применяется к файлам игры.")
        return False

    def attach(self, pid: int) -> bool:
        # MV: мост может быть уже поднят (игра запущена с нашим плагином)
        bport = mv_bridge.find_bridge_port(wait=3.0)
        if bport:
            self._pid = pid
            self._bridge_port = bport
            self.log.emit(
                f"Мост подключён: http://127.0.0.1:{bport}")
            self._log_game_errors(bport)
            self.attached.emit()
            return True
        port = getattr(self, "_port_hint", 0) or probe_game_port(pid)
        if not port:
            self.error.emit(
                "Отладочный порт не найден: игра запущена без "
                "--remote-debugging-port. Запустите её через OctopusBridge.")
            return False
        self._pid = pid
        # Профиль NW.js чистим и при attach (best-effort): файлы может
        # держать запущенная игра — переименования с ретраями упадут
        # молча, зато следующий запуск будет без «профиль от более
        # новой версии».
        try:
            exe_path = proc.exe_of(pid)
            if exe_path:
                clean_nwjs_profile(os.path.dirname(exe_path))
        except Exception:  # noqa: BLE001
            pass
        return self._connect_page(port, url_hint=".html", wait=5.0)

    def set_port_hint(self, port: int):
        self._port_hint = port

    def detach(self):
        self._proc = None
        self._bridge_port = 0
        super().detach()

    # ── мост MV: прозрачный роутинг поверх CDP-API ──
    def _log_game_errors(self, bport: int):
        """Ошибки страницы игры из предыдущих сессий (пережили краш в
        localStorage) — молчаливые вылеты MV становятся видимыми."""
        try:
            err = mv_bridge.bridge_errlog(bport)
        except Exception:  # noqa: BLE001
            return
        if not isinstance(err, dict):
            return
        for kind in ("catch", "error", "rejection"):
            e = err.get(kind)
            if isinstance(e, dict) and e.get("msg"):
                self.log.emit(
                    f"[игра] {kind}: {e['msg']} "
                    f"({e.get('extra', '')})")

    def evaluate(self, expression: str, await_promise: bool = False,
                 timeout: float = 15.0):
        if self._bridge_port:
            return mv_bridge.bridge_eval(
                self._bridge_port, expression, timeout)
        return super().evaluate(expression, await_promise, timeout)

    def is_attached(self) -> bool:
        if self._bridge_port:
            return True
        return super().is_attached()

    def send_key(self, key: str, code: str = "", keyCode: int = 0,
                 windowsKeyCode: int = 0) -> bool:
        if self._bridge_port:
            return False  # Input.dispatchKeyEvent недоступен без CDP
        return super().send_key(key, code, keyCode, windowsKeyCode)

    def screenshot(self) -> bytes | None:
        if self._bridge_port:
            return None  # Page.captureScreenshot недоступен без CDP
        return super().screenshot()

    # ── состояние ──
    def request_state(self) -> bool:
        ok, val = self.evaluate(
            "JSON.stringify(window.__octopus_collectState "
            "? window.__octopus_collectState() : null)")
        if ok and isinstance(val, str) and val:
            try:
                self.state_received.emit(json.loads(val))
                return True
            except ValueError:
                pass
        return False

    def request_vars(self) -> bool:
        return self.request_state()

    def set_variable(self, name: str, value) -> bool:
        if name.startswith("var:"):
            return self.send_cheat("var_set", index=int(name[4:]),
                                   value=value)
        if name.startswith("switch:"):
            return self.send_cheat("switch_set", index=int(name[7:]),
                                   value=bool(value))
        return False

    def send_cheat(self, cmd: str, **kwargs) -> bool:
        expr = self._cheat_expr(cmd, **kwargs)
        if expr is None:
            self.cheat_ack.emit(cmd, False, "unknown cmd", "")
            return False
        ok, val = self.evaluate(expr)
        if not ok:
            time.sleep(0.5)
            ok, val = self.evaluate(expr)
        self.cheat_ack.emit(cmd, ok, "" if ok else str(val),
                            json.dumps(val) if ok else "")
        return ok

    def apply_translation(self, entries) -> bool:
        """Гибридный live-перевод: внедряет словарь в игру (MV и MZ).

        Работает поверх файлового патча и покрывает зашифрованные/asar
        сборки, где данные не меняются напрямую.
        """
        tr = build_tr_dict(entries)
        if not tr:
            return False
        code = _TRANSLATION_PAYLOAD.replace(
            "__TR_DICT__", mv_bridge.js_json(tr))
        ok, _val = self.evaluate(code)
        return bool(ok)

    @staticmethod
    def _cheat_expr(cmd: str, **kwargs) -> str | None:
        # Все выражения — ES5 (var/function/indexOf): стрелки/const/let
        # роняют официальный рантайм MV (Chromium 41-49) с SyntaxError,
        # и читы «молча не работают».
        js = json.dumps
        if cmd == "gold_set":
            # Через gainGold (а не прямой _gold): срабатывают хуки
            # autoSendState и обновление UI сцены.
            target = int(kwargs["value"])
            return ("(function(){var t=" + str(target) + ";"
                    "var c=$gameParty.gold();var d=t-c;"
                    "if(d!==0){$gameParty.gainGold(d);}"
                    "return $gameParty.gold();})()")
        if cmd == "gold_add":
            return f"$gameParty.gainGold({int(kwargs['value'])})"
        if cmd == "var_set":
            return ("$gameVariables.setValue("
                    f"{int(kwargs['index'])}, {js(kwargs['value'])})")
        if cmd == "switch_set":
            v = "true" if kwargs["value"] else "false"
            return f"$gameSwitches.setValue({int(kwargs['index'])}, {v})"
        if cmd == "self_switch_set":
            # Self-переключатель события: ключ [mapId, eventId, "A".."D"].
            # setValue сам дёргает refresh карты — страница пересчитается.
            ch = str(kwargs.get("ch", "A")).upper()[:1]
            if ch not in "ABCD":
                ch = "A"
            v = "true" if kwargs["value"] else "false"
            return ("$gameSelfSwitches.setValue(["
                    + str(int(kwargs["mapId"])) + ", "
                    + str(int(kwargs["eventId"])) + ', "' + ch + '"], '
                    + v + ")")
        if cmd == "heal":
            return ("(function(){var m=$gameParty.members();"
                    "for(var i=0;i<m.length;i++){"
                    "m[i].setHp(m[i].mhp);m[i].setMp(m[i].mmp);}"
                    "return 'healed';})()")
        if cmd == "heal_all":
            # MV: removeAllStates() отсутствует (MZ-only) — снимаем через
            # states()/removeState, это же лечит смерть (revive).
            # Копия массива states(): removeState во время обхода безопасен.
            return ("(function(){var m=$gameParty.members();"
                    "for(var i=0;i<m.length;i++){var a=m[i];"
                    "var st=a.states().slice();"
                    "for(var j=0;j<st.length;j++){"
                    "a.removeState(st[j].id);}"
                    "a.setHp(a.mhp);a.setMp(a.mmp);}"
                    "return 'healed_all';})()")
        if cmd == "clear_states":
            return ("(function(){var m=$gameParty.members();"
                    "for(var i=0;i<m.length;i++){var a=m[i];"
                    "var st=a.states().slice();"
                    "for(var j=0;j<st.length;j++){"
                    "a.removeState(st[j].id);}}"
                    "return 'states_cleared';})()")
        if cmd == "speed":
            return f"$gamePlayer.setMoveSpeed({int(kwargs['value'])})"
        if cmd == "game_speed":
            return f"window.__octopus_setGameSpeed({int(kwargs['value'])})"
        if cmd == "through":
            v = "true" if kwargs["value"] else "false"
            return f"$gamePlayer.setThrough({v})"
        if cmd == "click_tp":
            v = "true" if kwargs["value"] else "false"
            return f"window.__octopus.clickTp = {v}"
        if cmd == "teleport":
            return ("(function(){if(typeof $gamePlayer==='undefined'){"
                    "throw new Error('игра ещё не загружена');}"
                    "if($gameParty.inBattle()){"
                    "throw new Error('нельзя во время боя');}"
                    "$gamePlayer.reserveTransfer("
                    + str(int(kwargs['mapId'])) + ", " + str(int(kwargs['x'])) + ", "
                    + str(int(kwargs['y'])) + ", 0, 0);return 'teleported';})()")
        if cmd == "event_start":
            # Принудительный запуск события: «дёрнуть триггер» из редактора
            # или карты, не трогая условия видимости/триггер страницы.
            return ("(function(){var eid=" + str(int(kwargs["eventId"])) + ";"
                    "if(typeof $gameMap==='undefined'){"
                    "throw new Error('игра ещё не загружена');}"
                    "var ev=$gameMap.event(eid);"
                    "if(!ev){throw new Error('события нет на этой карте');}"
                    "ev.start();return 'event_started';})()")
        if cmd == "reload_map":
            # Без Decrypter/XHR-хитростей: перечитываем файл карты через
            # штатный XHR (plain JSON) с www/data-фолбэком, для шифрованных
            # .rpgmvm — мягкий fallback на setup текущей $dataMap.
            # Всё ES5, ошибки XHR не роняют чит (возвращаем результат).
            return (
                "(function(){"
                "var mapId=$gameMap.mapId();"
                "var px=$gamePlayer.x,py=$gamePlayer.y,dir=$gamePlayer.direction();"
                "function obDone(){try{$gameMap.setup(mapId);}catch(e){}"
                "try{$gamePlayer.reserveTransfer(mapId,px,py,dir,0);}catch(e2){}"
                "return 'map_reloaded';}"
                "try{"
                "var pad=('00'+mapId).slice(-3);"
                "var urls=['data/Map'+pad+'.json','www/data/Map'+pad+'.json'];"
                "var idx=0;"
                "function obTry(){"
                "if(idx>=urls.length){return obDone();}"
                "var fn=urls[idx++];"
                "var xhr=new XMLHttpRequest();"
                "try{xhr.open('GET',fn);}catch(e){return obTry();}"
                "try{xhr.overrideMimeType('application/octet-stream');}catch(e2){}"
                "xhr.onload=function(){"
                "try{if(xhr.status===0||xhr.status===200){"
                "var t=xhr.responseText;"
                "if(t&&t.charCodeAt(0)===82){return obTry();}"
                "$dataMap=JSON.parse(t);return obDone();}}catch(e){}"
                "return obTry();};"
                "xhr.onerror=function(){return obTry();};"
                "try{xhr.send();}catch(e){return obTry();}"
                "}"
                "obTry();return 'map_reloading';"
                "}catch(e){return obDone();}"
                "})()")
        if cmd == "win_battle":
            return ("(function(){if(typeof $gameParty==='undefined'||"
                    "!$gameParty.inBattle()){"
                    "throw new Error('сейчас нет боя');}"
                    "var troop=$gameTroop;"
                    "var ms=troop.members();"
                    "for(var i=0;i<ms.length;i++){"
                    "if(ms[i].isAlive()){ms[i].die();}}"
                    "if(troop.isAllDead()){BattleManager.processVictory();}"
                    "return 'won';})()")
        if cmd == "give_item":
            kind = str(kwargs.get("kind", ""))
            db = {"weapon": "$dataWeapons", "armor": "$dataArmors"}.get(
                kind, "$dataItems")
            return ("(function(){var it=" + db + f"[{int(kwargs['id'])}];"
                    "if(!it){throw new Error('нет такого предмета');}"
                    f"$gameParty.gainItem(it, {int(kwargs.get('count', 1))}, "
                    "true);return it.name;})()")
        if cmd == "open_menu":
            return ("(function(){if(typeof SceneManager==='undefined'){"
                    "throw new Error('сцена недоступна');}"
                    "if(SceneManager._scene&&SceneManager._scene.constructor===Scene_Menu){"
                    "return 'already';}"
                    "SceneManager.push(Scene_Menu);return 'menu_opened';})()")
        if cmd == "open_items":
            return ("(function(){if(typeof SceneManager==='undefined'){"
                    "throw new Error('сцена недоступна');}"
                    "if(SceneManager._scene&&SceneManager._scene.constructor===Scene_Item){"
                    "return 'already';}"
                    "SceneManager.push(Scene_Item);return 'items_opened';})()")
        if cmd == "open_skills":
            return ("(function(){if(typeof SceneManager==='undefined'){"
                    "throw new Error('сцена недоступна');}"
                    "if(SceneManager._scene&&SceneManager._scene.constructor===Scene_Skill){"
                    "return 'already';}"
                    "SceneManager.push(Scene_Skill);return 'skills_opened';})()")
        if cmd == "open_equip":
            return ("(function(){if(typeof SceneManager==='undefined'){"
                    "throw new Error('сцена недоступна');}"
                    "if(SceneManager._scene&&SceneManager._scene.constructor===Scene_Equip){"
                    "return 'already';}"
                    "SceneManager.push(Scene_Equip);return 'equip_opened';})()")
        if cmd == "open_status":
            return ("(function(){if(typeof SceneManager==='undefined'){"
                    "throw new Error('сцена недоступна');}"
                    "if(SceneManager._scene&&SceneManager._scene.constructor===Scene_Status){"
                    "return 'already';}"
                    "SceneManager.push(Scene_Status);return 'status_opened';})()")
        if cmd == "open_save":
            return ("(function(){if(typeof SceneManager==='undefined'){"
                    "throw new Error('сцена недоступна');}"
                    "SceneManager.push(Scene_Save);return 'save_opened';})()")
        if cmd == "open_load":
            return ("(function(){if(typeof SceneManager==='undefined'){"
                    "throw new Error('сцена недоступна');}"
                    "SceneManager.push(Scene_Load);return 'load_opened';})()")
        if cmd == "open_options":
            return ("(function(){if(typeof SceneManager==='undefined'){"
                    "throw new Error('сцена недоступна');}"
                    "SceneManager.push(Scene_Options);return 'options_opened';})()")
        if cmd == "open_gameend":
            return ("(function(){if(typeof SceneManager==='undefined'){"
                    "throw new Error('сцена недоступна');}"
                    "SceneManager.push(Scene_GameEnd);return 'gameend_opened';})()")
        if cmd == "actor_set":
            field = str(kwargs["field"])
            fid = int(kwargs["actorId"])
            val = kwargs["value"]
            ops = {
                "level": f"a.changeLevel({int(val)}, false)",
                "hp": f"a.setHp({int(val)})",
                "mp": f"a.setMp({int(val)})",
                "exp": f"a.changeExp({js(int(val))}, false)",
            }
            op = ops.get(field)
            if not op:
                return None
            return ("(function(){var a=$gameActors.actor(" + str(fid) +
                    ");if(!a){throw new Error('нет такого героя');}"
                    + op + ";return a.name();})()")
        return None

    def game_pid(self) -> int | None:
        if self._proc and self._proc.poll() is None:
            return self._proc.pid
        if self._pid and proc.pid_exists(self._pid):
            return self._pid
        return None


# ── Поиск порта (тонкие обёртки над cdp_base; логика одна) ──

def probe_game_port(pid: int) -> int:
    return _base_probe(pid, SCAN_PORTS, _port_is_rpgm_game)


def _bruteforce_port(pid: int) -> int:
    return bruteforce_port(pid, SCAN_PORTS, _port_is_rpgm_game)


def _port_is_rpgm_game(port: int, pid: int) -> bool:
    return cdp_page_is_game(port, pid, _RPGM_PROBE, engine_key="rpgmaker")

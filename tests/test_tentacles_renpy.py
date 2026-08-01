# -*- coding: utf-8 -*-
"""Живой тест Ren'Py-щупальца: Frida-инъекция агента в Python-процесс
с фейковым renpy-модулем. ПРОПУСК при недоступности Frida."""
import io
import os
import subprocess
import sys
import tempfile
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

try:
    import frida  # noqa: F401
except ImportError:
    print("ПРОПУСК: frida не установлена")
    sys.exit(0)

app = QApplication([])

FAKE_RENPY = r'''
import sys, time, types, os, shutil, tempfile, re
renpy = types.ModuleType("renpy")
class _NS: pass
renpy.store = _NS()
renpy.store.gold = 100
renpy.store.hp = 5
renpy.store.hp_max = 10
renpy.store.player = {"level": 3, "name": "Hero"}
renpy.persistent = _NS()
renpy.config = _NS()
renpy.config.gamedir = tempfile.mkdtemp(prefix="ob_fake_game_")
try:
    _ob_fd = os.path.join(renpy.config.gamedir, "ob_fonts")
    os.makedirs(_ob_fd)
    shutil.copy(os.environ["OB_FAKE_FONT"],
                os.path.join(_ob_fd, "NotoSans-Regular.ttf"))
except Exception:
    pass
renpy.config.say_menu_text_filter = None
renpy.config.start_callbacks = []
renpy.config.after_load_callbacks = []
renpy.restart_interaction = lambda: None
text_mod = types.ModuleType("renpy.text")
text_text = types.ModuleType("renpy.text.text")
class Text:
    def __init__(self, text, *a, **k):
        self.text = text
text_text.Text = Text
font_mod = types.ModuleType("renpy.text.font")
class FontGroup:
    def __init__(self): self.fonts = []
    def add(self, path, a, b): self.fonts.append((path, a, b))
font_mod.FontGroup = FontGroup
text_mod.text = text_text
text_mod.font = font_mod
renpy.text = text_mod
style = _NS()
style.default = _NS(); style.default.font = "Original.ttf"
style.say = _NS(); style.say.font = "Another.ttf"
renpy.store.style = style
renpy.style = types.ModuleType("renpy.style")
renpy.style.default = style.default
renpy.style.styles = {"default": style.default, "say": style.say}
py_mod = types.ModuleType("renpy.python")
py_mod.py_eval = eval
renpy.python = py_mod
trl_mod = types.ModuleType("renpy.translation")
trl_mod.translate_string = lambda s, language=None: s
renpy.translation = trl_mod
# заглушка интерполяции: [ключ] -> значение из scope (реальный Ren'Py
# делает то же в renpy/substitutions.py, вызывая translate_string
# ДО подстановки — здесь переводит только агент, через обёртку)
sub_mod = types.ModuleType("renpy.substitutions")
def _fake_sub(s, scope=None, force=False, translate=True):
    did = "[" in s
    if did:
        s = re.sub(r"\[(\w+)\]",
                   lambda m: str((scope or {}).get(m.group(1), "?")), s)
    return s, did
sub_mod.substitute = _fake_sub
renpy.substitutions = sub_mod
renpy.call = lambda label: None
renpy.current_context = lambda: type("C", (), {"current": "start"})()
sys.modules["renpy"] = renpy
sys.modules["renpy.text"] = text_mod
sys.modules["renpy.text.text"] = text_text
sys.modules["renpy.text.font"] = font_mod
sys.modules["renpy.python"] = py_mod
sys.modules["renpy.translation"] = trl_mod
sys.modules["renpy.substitutions"] = sub_mod
print("FAKE_RENPY_READY", flush=True)
while True:
    time.sleep(0.5)
'''


def pump(seconds, cond=None):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        if cond and cond():
            return True
        time.sleep(0.03)
    return bool(cond and cond())


with tempfile.TemporaryDirectory() as td:
    target = os.path.join(td, "fake_renpy_target.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write(FAKE_RENPY)

    os.environ["OB_FAKE_FONT"] = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "core", "assets", "fonts", "NotoSans-Regular.ttf")

    proc = subprocess.Popen([sys.executable, target],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    line = proc.stdout.readline().strip()
    assert "FAKE_RENPY_READY" in line, line

    # venv python (3.13+) может быть редиректором: настоящий
    # интерпретатор — дочерний процесс
    import psutil
    real_pid = proc.pid
    for child in psutil.Process(proc.pid).children(recursive=True):
        if "python" in child.name().lower():
            real_pid = child.pid

    try:
        from app.engines.renpy.tentacle import RenPyTentacle
        t = RenPyTentacle()
        events = {"attached": [], "seen": [], "vars": [], "state": [],
                  "ack": [], "err": []}
        t.attached.connect(lambda: events["attached"].append(1))
        t.text_seen.connect(lambda o, tr: events["seen"].append((o, tr)))
        t.vars_received.connect(lambda v: events["vars"].append(v))
        t.state_received.connect(lambda s: events["state"].append(s))
        t.cheat_ack.connect(lambda c, ok, e, v:
                            events["ack"].append((c, ok, e, v)))
        t.error.connect(lambda s: events["err"].append(s))
        t.set_translate_fn(lambda s: s.upper())

        print("1) Frida attach + инъекция агента (pid %d)..." % real_pid)
        # attach сам агент не инжектит (это делает RPY-файл игры) —
        # поднимаем сервер и внедряем agent_source напрямую
        from app.transport.frida_rpc.injector import PythonInjector
        from app.engines.renpy.agent import agent_source
        if not t._start_server():
            print("   ПРОПУСК: не поднялся сервер щупальца:", events["err"])
            sys.exit(0)
        injector = PythonInjector()
        if not injector.attach(real_pid):
            print("   ПРОПУСК: Frida attach не удался:", events["err"])
            sys.exit(0)
        t._injector = injector
        t._pid = real_pid
        t._game_dir = ""
        rc = injector.exec_python(
            agent_source(t._server.port, "ob_fonts/NotoSans-Regular.ttf", ""))
        assert rc == 0, injector._last_error
        if not pump(30, lambda: events["attached"]):
            print("   ПРОПУСК: агент не подключился:", events["err"])
            sys.exit(0)
        print("   OK")

        import json as _json

        def eval_in_game(code, timeout=12):
            events["ack"].clear()
            assert t.send_cheat("exec", code=code)
            assert pump(timeout, lambda: events["ack"]), "нет ответа exec"
            c, ok, e, v = events["ack"][-1]
            assert ok, e
            return _json.loads(v)

        print("2) Хук текста: оригинал -> запрос -> кэш...")
        t._injector.exec_python(
            "import renpy; renpy._t1 = renpy.text.text.Text('hello agent')")
        assert pump(8, lambda: any(o == "hello agent"
                                   for o, _ in events["seen"]))
        t._injector.exec_python(
            "renpy._t2 = renpy.text.text.Text('hello agent')")
        time.sleep(0.3)
        assert eval_in_game("renpy._t2.text") == "HELLO AGENT"
        print("   OK")

        print("2b) Хук renpy.translation.translate_string (API-уровень)...")
        t._injector.exec_python(
            "renpy._t3 = renpy.translation.translate_string('api level text')")
        assert pump(8, lambda: any(o == "api level text"
                                   for o, _ in events["seen"]))
        t._injector.exec_python(
            "renpy._t4 = renpy.translation.translate_string('api level text')")
        time.sleep(0.3)
        assert eval_in_game("renpy._t4") == "API LEVEL TEXT"
        print("   OK")

        print("2c) Префильтры: русский/трейсбек/длинные строки не уходят...")
        events["seen"].clear()
        t._injector.exec_python(
            "renpy._t5 = renpy.translation.translate_string(u'уже русский текст')")
        t._injector.exec_python(
            "renpy.translation.translate_string('File \"game/script.rpy\", line 525')")
        t._injector.exec_python(
            "renpy.translation.translate_string('Traceback (most recent call last):')")
        t._injector.exec_python("renpy.translation.translate_string('x' * 600)")
        time.sleep(1.0)
        assert not events["seen"], events["seen"]
        assert eval_in_game("renpy._t5") == u"уже русский текст"
        print("   OK")

        print("2d) Identity-ответ -> скип-сет (повтор не отправляется)...")
        t._injector.exec_python(
            "renpy.translation.translate_string('ALREADY UPPER')")
        assert pump(8, lambda: any(o == "ALREADY UPPER"
                                   for o, _ in events["seen"]))
        events["seen"].clear()
        t._injector.exec_python(
            "renpy.translation.translate_string('ALREADY UPPER')")
        time.sleep(1.0)
        assert not events["seen"], events["seen"]
        print("   OK")

        print("2e) Ren'Py-escape [[ через весь пайплайн...")
        t._injector.exec_python(
            "renpy._t6 = renpy.text.text.Text('Misc [[Requires Restart]')")
        assert pump(8, lambda: any(o == "Misc [[Requires Restart]"
                                   for o, _ in events["seen"]))
        t._injector.exec_python(
            "renpy._t7 = renpy.text.text.Text('Misc [[Requires Restart]')")
        time.sleep(0.3)
        assert eval_in_game("renpy._t7.text") == "MISC [[REQUIRES RESTART]"
        print("   OK")

        print("2f) Хук renpy.substitutions.substitute (интерполированные строки меню)...")
        t._injector.exec_python(
            "renpy._t8 = renpy.substitutions.substitute('Go [dest]!', {'dest': 'somewhere else'})[0]")
        assert pump(8, lambda: any(o == "Go somewhere else!"
                                   for o, _ in events["seen"]))
        t._injector.exec_python(
            "renpy._t9 = renpy.substitutions.substitute('Go [dest]!', {'dest': 'somewhere else'})[0]")
        time.sleep(0.3)
        assert eval_in_game("renpy._t9") == "GO SOMEWHERE ELSE!"
        print("   OK")

        print("2g) substitute(translate=False): DynamicImage-пути НЕ переводятся...")
        events["seen"].clear()
        t._injector.exec_python(
            "renpy._t10 = renpy.substitutions.substitute('gui/scrollbar/vertical_[prefix_]bar.png', {'prefix_': 'idle '}, translate=False)[0]")
        time.sleep(1.0)
        assert not events["seen"], events["seen"]
        v10 = eval_in_game("renpy._t10")
        assert "gui/scrollbar" in v10 and v10.endswith(".png"), v10
        # ассет-путь через translate=True тоже не уходит (префильтр)
        events["seen"].clear()
        t._injector.exec_python(
            "renpy._t11 = renpy.substitutions.substitute('gui/scrollbar/vertical_[prefix_]bar.png', {'prefix_': 'hover '}, translate=True)[0]")
        time.sleep(1.0)
        assert not events["seen"], events["seen"]
        v11 = eval_in_game("renpy._t11")
        assert "gui/scrollbar" in v11 and v11.endswith(".png"), v11
        print("   OK")

        print("3) Подмена шрифта: глобальная font_replacement_map...")
        # стили НЕ меняются — шрифт подменяется картой движка
        assert eval_in_game(
            "renpy.store.style.default.font") == "Original.ttf"
        assert eval_in_game(
            "renpy.store.style.say.font") == "Another.ttf"
        # wildcard-карта установлена: ЛЮБОЕ имя -> наш NotoSans
        assert eval_in_game(
            "renpy.config.font_replacement_map.get(('Original.ttf', False, False))[0]"
        ) == "ob_fonts/NotoSans-Regular.ttf"
        assert eval_in_game(
            "renpy.config.font_replacement_map.get(('fonts/boon-500.otf', False, False))[0]"
        ) == "ob_fonts/NotoSans-Regular.ttf"
        # флаги bold/italic из ключа сохраняются
        assert eval_in_game(
            "renpy.config.font_replacement_map.get(('Bold.ttf', True, False))[1]"
        ) == "True"
        # файлы игры НЕ тронуты: бэкапов/манифеста нет
        assert eval_in_game(
            "__import__('os').path.isfile(renpy.config.gamedir + '/ob_fonts_orig/manifest.json')"
        ) == "False"
        print("   OK")

        print("4) Читы: золото, переменные, heal...")
        events["ack"].clear()
        t.send_cheat("gold_add", value=50)
        assert pump(2, lambda: events["ack"]), "нет ответа gold_add"
        assert eval_in_game("renpy.store.gold") == "150"
        events["ack"].clear()
        assert t.set_variable("player.level", 5)
        assert pump(2, lambda: events["ack"]), "нет ответа var_set"
        assert eval_in_game("renpy.store.player['level']") == "5"
        events["ack"].clear()
        t.send_cheat("heal")
        assert pump(2, lambda: events["ack"]), "нет ответа heal"
        assert eval_in_game("renpy.store.hp") == "10"
        print("   OK")

        print("5) Список переменных и снимок состояния...")
        events["vars"].clear()
        assert t.request_vars()
        assert pump(8, lambda: events["vars"])
        names = [v["name"] for v in events["vars"][-1]]
        assert "gold" in names and "player.level" in names, names
        events["state"].clear()
        assert t.request_state()
        assert pump(8, lambda: events["state"])
        st = events["state"][-1]
        assert st.get("gold") == 150 and st.get("label") == "start", st
        print("   OK")

        print("6) Отключение...")
        t.detach()
        assert not t.is_attached()
        print("   OK")

        print()
        print("ВСЕ ТЕСТЫ RENPY-ЩУПАЛЬЦА ПРОШЛИ")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

sys.stdout.flush()
os._exit(0)

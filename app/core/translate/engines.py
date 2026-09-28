# -*- coding: utf-8 -*-
"""Движки машинного перевода: Google Free, Bing, MyMemory,
Rotate (бесплатные, без нейросетей).

Контракт translate(): возвращает список той же длины, что и texts.
На месте непереведённой строки стоит None — «этот провайдер не смог»,
а не EngineError. Ошибка движка не должна убивать перевод задачи:
непереведённые строки собираются в очередь и повторяются позже.
"""
from __future__ import annotations

import html
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from app import user_data_dir

# сколько секунд Google «отдыхает» после 429/капчи (страница /sorry/)
_RATE_LIMIT_COOLDOWN = 60.0
# потолок кулдауна провайдера: дальше ждать бессмысленно, он отвалился
_COOLDOWN_MAX = 900.0

# (удалено: публичных серверов LibreTranslate без ключа не осталось —
# проверены fedilab/cutie/argos/terra/.de, все мертвы. Свои ключи тоже
# убраны: один движок, ноль настроек серверов.)


# ---------- состояние провайдеров, переживает перезапуск ----------
# Раньше кулдаун жил только в памяти процесса: закрыли приложение,
# открыли — и мы снова лезем в закрытую дверь и ловим 429. Теперь
# «отдохнувший» провайдер не трогается до конца своего кулдауна.
_HEALTH_FILE = os.path.join(user_data_dir(), "engine_health.json")
# RLock, а не Lock: penalize_engine() держит лок и внутри вызывает
# _load_health(), которая тоже берёт лок — обычный Lock здесь вешает
# перевод намертво (проверено: тест вставал намертво в clear_engine_cooldown).
_HEALTH_LOCK = threading.RLock()
_health: dict | None = None


def _load_health() -> dict:
    global _health
    with _HEALTH_LOCK:
        if _health is None:
            data: dict = {}
            try:
                with open(_HEALTH_FILE, encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, ValueError):
                data = {}
            _health = data
        return _health


def _store_health(data: dict) -> None:
    try:
        tmp = f"{_HEALTH_FILE}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, _HEALTH_FILE)
    except OSError:
        pass


def engine_state(name: str) -> tuple[float, bool]:
    """(секунд до конца кулдауна, помечен ли провайдер как «упавший»).

    «Упавший» = нет сети/DNS/таймаут. Ждать его бессмысленно, в отличие
    от 429 по лимиту — там провайдер сам оживёт.
    """
    rec = _load_health().get(name)
    if not isinstance(rec, dict):
        return 0.0, False
    try:
        left = max(0.0, float(rec.get("cooldown_until", 0.0)) - time.time())
    except (TypeError, ValueError):
        left = 0.0
    return left, bool(rec.get("down"))


def engine_cooldown(name: str) -> float:
    return engine_state(name)[0]


def penalize_engine(name: str, seconds: float = 30.0,
                    down: bool = False) -> None:
    """Провайдер отказал: уводим его в кулдаун и сохраняем на диск.

    Кулдаун нарастает при повторных отказах (30с, 60с, 120с... до
    15 минут) и обнуляется при первом успешном ответе. down=True — сети
    нет вовсе, ждать бессмысленно.
    """
    with _HEALTH_LOCK:
        data = _load_health()
        rec = data.get(name) if isinstance(data.get(name), dict) else {}
        left = max(0.0, float(rec.get("cooldown_until", 0.0) or 0.0)
                   - time.time())
        delay = min(max(seconds, left * 2 if left else 0.0), _COOLDOWN_MAX)
        data[name] = {"fails": int(rec.get("fails", 0) or 0) + 1,
                      "cooldown_until": time.time() + delay,
                      "down": bool(down) or bool(rec.get("down"))}
        _store_health(data)


def clear_engine_cooldown(name: str) -> None:
    with _HEALTH_LOCK:
        data = _load_health()
        if data.get(name):
            data[name] = {"fails": 0, "cooldown_until": 0.0, "down": False}
            _store_health(data)


def is_network_dead(exc: BaseException) -> bool:
    """Сети нет (DNS/соединение/таймаут) — провайдер не «отдыхает»,
    а упал. Ждать такого бессмысленно, надо честно остановиться."""
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    cause = exc.__cause__ or exc.__context__
    if cause is not None and cause is not exc:
        return is_network_dead(cause)
    return False

LANG_NAMES = {
    "ja": "Japanese", "zh": "Chinese", "en": "English",
    "ru": "Russian", "ko": "Korean", "uk": "Ukrainian",
    "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "pl": "Polish",
    "cs": "Czech", "ar": "Arabic", "id": "Indonesian",
    "th": "Thai", "vi": "Vietnamese", "tr": "Turkish",
    "nl": "Dutch", "sv": "Swedish",
}

# языки для выбора в настройках/мастере (коды Google Translate,
# понимает и Bing через LANG_NAMES). "auto" — только для исходного.
SOURCE_LANGS = ("auto", "ja", "zh", "ko", "en", "ru", "uk", "de",
                "fr", "es", "it", "pt", "pl", "cs", "ar", "id",
                "th", "vi", "tr", "nl", "sv")
TARGET_LANGS = tuple(l for l in SOURCE_LANGS if l != "auto")


_TOKEN_RE = re.compile(r"</?x\d+\s*/?>")


def _tokens(text: str) -> list[str]:
    """Все токены <xN/> в строке по порядку (для проверки целостности)."""
    return _TOKEN_RE.findall(text)


class EngineError(Exception):
    pass


class BaseEngine:
    name = "base"

    def __init__(self) -> None:
        # флаг отмены — инстанс-атрибут (раньше был класс-атрибутом
        # и cancel() одного движка останавливал все экземпляры).
        self.cancelled = False

    def _sleep_cancellable(self, seconds: float) -> None:
        """Прерываемый sleep: проверка self.cancelled каждые 0.5с."""
        end = time.monotonic() + max(0.0, seconds)
        while True:
            if self.cancelled:
                raise InterruptedError("cancelled")
            remain = end - time.monotonic()
            if remain <= 0:
                return
            time.sleep(min(0.5, remain))

    def cancel(self):
        """Просит движок остановиться. Проверки выполняются в
        translate() и перед сетевыми запросами/ожиданиями."""
        self.cancelled = True

    def translate(self, texts: list[str], source: str, target: str,
                  context_before: list[str] | None = None,
                  context_after: list[str] | None = None) -> list[str]:
        raise NotImplementedError

    def _align(self, texts: list[str], out) -> list:
        """Приводит ответ к длине texts: None на месте непереведённых строк.

        Раньше RotateEngine возвращал отфильтрованный список (короче
        texts), и zip() в сервисе молча сдвигал переводы на чужие
        записи — строка получала чужой перевод. Теперь длина гарантирована.
        """
        if out is None:
            return [None] * len(texts)
        res = list(out)
        if len(res) > len(texts):
            del res[len(texts):]
        elif len(res) < len(texts):
            res.extend([None] * (len(texts) - len(res)))
        return res

    def cooldown_left(self) -> float:
        """Секунд до конца кулдауна (0 — провайдер доступен)."""
        return engine_state(self.name)[0]

    def is_down(self) -> bool:
        """Провайдер упал (нет сети) — ждать его бессмысленно."""
        return engine_state(self.name)[1]

    def report_failure(self, exc: BaseException,
                       seconds: float = 30.0) -> None:
        """Отказ провайдера: 429/капча — отдых, нет сети — падение."""
        penalize_engine(self.name, seconds, down=is_network_dead(exc))

    def all_down(self) -> bool:
        """Провайдер сам упал (сети нет) — ждать нечего."""
        return self.is_down()

    def _guard_tokens(self, texts: list[str],
                      out: list) -> list:
        """Страховка для любых движков: если перевод
        потерял/переставил токены <xN/> (макросы, ссылки, коды), строка
        возвращается непереведённой — иначе игра упадёт («cannot find a
        closing tag for macro», битые ссылки и т.п.). None (строку не
        перевели) пропускаем как есть."""
        # Выравниваем длины до zip: укороченный ответ движка иначе
        # сдвигает переводы на чужие строки (хвост получал чужое).
        aligned = self._align(texts, out)
        res: list = []
        for src_s, tr_s in zip(texts, aligned):
            if tr_s is None or _tokens(src_s) != _tokens(tr_s):
                res.append(src_s if tr_s is not None else None)
            else:
                res.append(tr_s)
        return res

    def ping(self) -> bool:
        return False




class GoogleFreeEngine(BaseEngine):
    """Google Translate — бесплатные неофициальные эндпоинты (без ключа).

    Каскад эндпоинтов (от быстрого к медленному):
    1. translate-pa.googleapis.com/v1/translateHtml — тот же сервис, что
       у расширения Google Translate: публичный ключ, один запрос на весь
       пакет (каждая строка — отдельный элемент, БЕЗ \\n-склейки),
       замер: ~90 мс на 50 строк, 277 мс на 200. Это основной путь.
    2. translate.googleapis.com/translate_a/single — классический gtx:
       строки пакета через \\n, ответ режется обратно (фолбэк для строк
       с переводами строк — translateHtml их теряет — и при сбое №1).
    3. translate.google.com/m — HTML-версия, щедрые лимиты (последний
       фолбэк перед построчным обходом).

    Соединение переиспользуется (requests.Session, keep-alive — раньше
    каждый запрос делал новый TLS-рукопожатие). Пакеты переводятся
    параллельно (пул потоков).

    Защита от rate-limit: при 429/капче (страница /sorry/) Google
    уходит в кулдаун — в течение кулдауна запросы не шлются вовсе
    (мгновенный отказ), rotate в это время работает на Bing.
    """

    name = "google_free"
    URL_SINGLE = "https://translate.googleapis.com/translate_a/single"
    URL_FAST = "https://translate-pa.googleapis.com/v1/translateHtml"
    URL_M = "https://translate.google.com/m"
    FAST_KEY = "AIzaSyATBXajvzQLTDHEQbcpq0Ihe0vWDHmO520"
    WORKERS = 4
    BATCH_LINES = 100
    _UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

    def __init__(self):
        super().__init__()
        self._ratelimit_until = 0.0
        self._rl_lock = threading.Lock()
        # P0: requests.Session не потокобезопасен, а translate() гоняет
        # пакеты из ThreadPoolExecutor. Сериализуем доступ локом
        # (на потом — пул сессий по одной на поток через threading.local).
        self._sess_lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": self._UA,
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        })

    def _rate_limited(self) -> bool:
        with self._rl_lock:
            return time.time() < self._ratelimit_until

    def _mark_rate_limited(self, duration: float = _RATE_LIMIT_COOLDOWN) -> None:
        with self._rl_lock:
            self._ratelimit_until = time.time() + duration

    def _is_rate_limit(self, r) -> bool:
        """429/403 или переадресация на страницу капчи /sorry/."""
        return (getattr(r, "status_code", 200) in (429, 403)
                or "sorry" in getattr(r, "url", ""))

    def _sget(self, *args, **kwargs):
        """GET через общий Session под локом (Session не потокобезопасен)."""
        with self._sess_lock:
            return self._session.get(*args, **kwargs)

    def _spost(self, *args, **kwargs):
        """POST через общий Session под локом (Session не потокобезопасен)."""
        with self._sess_lock:
            return self._session.post(*args, **kwargs)

    def ping(self) -> bool:
        try:
            self._sget(self.URL_SINGLE,
                       params={"client": "gtx", "sl": "en",
                               "tl": "ru", "dt": "t", "q": "hi"},
                       timeout=5)
            return True
        except requests.RequestException:
            return False

    # ── 1. translateHtml: быстрый батч (без \n-склейки) ──
    def _translate_fast(self, texts: list[str], src: str, target: str
                        ) -> list[str]:
        """Один запрос на весь пакет. Только для строк без переводов
        строк (translateHtml их теряет). Кидает EngineError при сбое."""
        if self.cancelled:
            raise InterruptedError("cancelled")
        if self._rate_limited():
            raise EngineError("Google: rate-limit кулдаун")
        try:
            r = self._spost(
                self.URL_FAST,
                headers={"X-Goog-API-Key": self.FAST_KEY,
                         "Content-Type": "application/json+protobuf"},
                data=json.dumps([[texts, "auto", target], "wt_lib"],
                                ensure_ascii=False),
                timeout=30)
        except requests.RequestException as e:
            raise EngineError(f"Google fast unavailable: {e}") from e
        if r.status_code == 429 or "sorry" in getattr(r, "url", ""):
            self._mark_rate_limited()
            raise EngineError(f"rate limit ({r.status_code})")
        # 403/404 = ключ отозван/недоступен — без кулдауна, уходим на
        # классический эндпоинт, он живёт без ключа
        if r.status_code in (403, 404):
            raise EngineError(f"fast endpoint {r.status_code}")
        try:
            r.raise_for_status()
            data = r.json()
            out = [html.unescape(str(t)) for t in data[0]]
        except (requests.RequestException, ValueError, TypeError,
                KeyError, IndexError) as e:
            raise EngineError(f"fast response: {e}") from e
        if len(out) != len(texts):
            raise EngineError(f"fast response length {len(out)}")
        return out

    # ── 2. классический gtx: пакет через \n ──
    def _translate_batch_join(self, texts: list[str], src: str,
                              target: str) -> list[str]:
        """Один запрос на пакет: строки через \\n, ответ режется обратно.

        Если Google склеил строки и число сегментов не совпало — пакет
        переводится построчно (замедленно, но без потери результата).
        """
        q = "\n".join(texts)
        for attempt in range(3):
            if self.cancelled:
                raise InterruptedError("cancelled")
            if self._rate_limited():
                raise EngineError("Google: rate-limit кулдаун")
            try:
                r = self._sget(self.URL_SINGLE, params={
                    "client": "gtx", "sl": src, "tl": target,
                    "dt": "t", "q": q}, timeout=30)
                if self._is_rate_limit(r):
                    self._mark_rate_limited()
                    raise requests.HTTPError(f"rate limit ({r.status_code})")
                r.raise_for_status()
                data = r.json()
                translated = "".join(seg[0] for seg in data[0] if seg[0])
                parts = translated.split("\n")
                if len(parts) == len(texts):
                    return parts
                break  # счётчик не сошёлся — построчно
            except (requests.RequestException, ValueError, TypeError,
                    KeyError, IndexError):
                if attempt < 2:
                    self._sleep_cancellable(
                        6.0 * (attempt + 1) if self._rate_limited()
                        else 1.0 * (attempt + 1))
        return [self._translate_one(t, src, target) for t in texts]

    # ── 3. translate.google.com/m: HTML-фолбэк ──
    def _translate_m(self, text: str, src: str, target: str) -> str:
        """Старая мобильная HTML-версия — щедрые лимиты, последний
        фолбэк перед построчным обходом. Только без переводов строк."""
        if self.cancelled:
            raise InterruptedError("cancelled")
        if self._rate_limited():
            raise EngineError("Google: rate-limit кулдаун")
        try:
            r = self._sget(self.URL_M, params={
                "sl": src, "tl": target, "q": text}, timeout=30)
            if self._is_rate_limit(r):
                self._mark_rate_limited()
                raise requests.HTTPError(f"rate limit ({r.status_code})")
            r.raise_for_status()
            m = re.search(r'class="(?:result-container|tlid-translation)">'
                          r'(.*?)</div>', r.text)
            if not m:
                raise ValueError("result container not found")
            return re.sub(r"<[^>]+>", "", m.group(1))
        except (requests.RequestException, ValueError) as e:
            raise EngineError(f"Google m unavailable: {e}") from e

    def _translate_one(self, text: str, src: str, target: str) -> str:
        # быстрый одиночный запрос (только без переводов строк)
        if "\n" not in text:
            try:
                return self._translate_fast([text], src, target)[0]
            except InterruptedError:
                raise
            except EngineError:
                pass
        last_err = None
        for attempt in range(3):
            if self.cancelled:
                raise InterruptedError("cancelled")
            if self._rate_limited():
                raise EngineError("Google: rate-limit кулдаун")
            try:
                r = self._sget(self.URL_SINGLE, params={
                    "client": "gtx", "sl": src, "tl": target,
                    "dt": "t", "q": text}, timeout=30)
                if self._is_rate_limit(r):
                    self._mark_rate_limited()
                    raise requests.HTTPError(f"rate limit ({r.status_code})")
                r.raise_for_status()
                data = r.json()
                return "".join(seg[0] for seg in data[0] if seg[0])
            except (requests.RequestException, ValueError, TypeError,
                    KeyError, IndexError) as e:
                last_err = e
                if attempt < 2:
                    self._sleep_cancellable(
                        6.0 * (attempt + 1) if self._rate_limited()
                        else 1.0 * (attempt + 1))
        try:
            return self._translate_m(text, src, target)
        except InterruptedError:
            raise
        except EngineError:
            pass
        raise EngineError(
            f"Google Translate unavailable: {last_err}") from last_err

    def _translate_chunk(self, texts: list[str], src: str,
                         target: str) -> list[str]:
        """Один пакет: быстрый батч → склейка → построчно."""
        if self.cancelled:
            raise InterruptedError("cancelled")
        simple = all("\n" not in t for t in texts)
        if simple:
            try:
                return self._translate_fast(texts, src, target)
            except InterruptedError:
                raise
            except EngineError:
                pass
        try:
            return self._translate_batch_join(texts, src, target)
        except InterruptedError:
            raise
        except EngineError:
            pass
        return [self._translate_one(t, src, target) for t in texts]

    def translate(self, texts: list[str], source: str, target: str,
                  context_before: list[str] | None = None,
                  context_after: list[str] | None = None) -> list[str]:
        if not texts:
            return []
        src = "auto" if source == "auto" else source
        if len(texts) == 1:
            return self._guard_tokens(
                texts, [self._translate_one(texts[0], src, target)])
        chunks = [texts[i:i + self.BATCH_LINES]
                  for i in range(0, len(texts), self.BATCH_LINES)]
        results: list[list[str] | None] = [None] * len(chunks)
        with ThreadPoolExecutor(max_workers=min(self.WORKERS, len(chunks))) as ex:
            futures = {ex.submit(self._translate_chunk, c, src, target): i
                       for i, c in enumerate(chunks)}
            for f in as_completed(futures):
                try:
                    results[futures[f]] = f.result()
                except InterruptedError:
                    raise
                except Exception:  # noqa: BLE001 — битый чанк: None-дырки
                    results[futures[f]] = None
        out: list[str | None] = [None] * len(texts)
        for i, res in enumerate(results):
            if res is None:
                continue
            for j, t in enumerate(res):
                pos = i * self.BATCH_LINES + j
                if pos < len(out):
                    out[pos] = t
        # None-дырки НЕ схлопываем: иначе хвост чанка сдвигается на чужие
        # строки. _guard_tokens оставит None как «не переведено».
        return self._guard_tokens(texts, out)


class BingEngine(BaseEngine):
    """Bing Translator — бесплатный неофициальный endpoint (без ключа).

    Делает запросы, имитируя браузер напрямую в Bing Translator:
    GET страницы переводчика для динамических токенов (IG, IID, key, token),
    затем POST на ttranslatev3 (аналог API v3 для веб-клиента).
    """

    name = "bing"
    HOST_URL = "https://www.bing.com/Translator"
    _UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

    def __init__(self):
        super().__init__()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": self._UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        # P0: токены и Session трогают несколько потоков (Rotate крутит
        # Bing-сессии из пула) — защищаем локом.
        self._lock = threading.RLock()
        self._ig: str | None = None
        self._iid: str | None = None
        self._token: str | None = None
        self._key: str | None = None

    def _sget(self, *args, **kwargs):
        with self._lock:
            sess = self._session
        # сам HTTP вне токен-лока не держим дольше нужного: Session
        # используется только здесь и в _translate_one под тем же локом
        # (сериализация запросов — цена потокобезопасности, см. Google).
        with self._lock:
            return sess.get(*args, **kwargs)

    def _spost(self, *args, **kwargs):
        with self._lock:
            return self._session.post(*args, **kwargs)

    # ── токены ──
    def _load_tokens(self):
        with self._lock:
            if self._ig and self._token:
                return
        # Короткий таймаут: получение токенов обязано быть быстрым; 15 с
        # на каждую Bing-сессию превращали ping/старт перевода в долгое
        # молчание без прогресса.
        r = self._sget(self.HOST_URL, timeout=8)
        r.raise_for_status()
        html = r.text
        with self._lock:
            if self._ig and self._token:
                return  # другой поток уже загрузил, пока шёл GET
            m = re.search(r'IG\s*[:=]\s*["\']([^"\']+)["\']', html)
            if m and "+_G.IG+" not in m.group(1):
                self._ig = m.group(1)
            m = re.search(r'id="tta_outGDCont"[^>]*data-iid="([^"]+)"', html)
            if not m:
                m = re.search(r'_iid\s*=\s*["\']([^"\']+)["\']', html)
            if m:
                self._iid = m.group(1)
            m = re.search(r"params_AbusePreventionHelper\s*=\s*\[([^\]]+)\]", html)
            if m:
                parts = [p.strip().strip('"').strip("'") for p in m.group(1).split(",")]
                if parts:
                    self._key = parts[0]
                if len(parts) > 1:
                    self._token = parts[1]
            if not self._iid:
                self._iid = "translator.5028"
            if not (self._ig and self._token):
                raise EngineError("Bing: не удалось получить токены переводчика")

    def _reset_tokens(self):
        with self._lock:
            self._ig = self._iid = self._token = self._key = None

    def ping(self) -> bool:
        try:
            self._load_tokens()
            return True
        except (requests.RequestException, EngineError):
            return False

    def translate(self, texts: list[str], source: str, target: str,
                  context_before: list[str] | None = None,
                  context_after: list[str] | None = None) -> list[str]:
        out = []
        for t in texts:
            out.append(self._translate_one(t, source, target))
        return self._guard_tokens(texts, out)

    def _translate_one(self, text: str, source: str, target: str) -> str:
        src = "auto-detect" if source == "auto" else source
        last_err = None
        for attempt in range(3):
            if self.cancelled:
                raise InterruptedError("cancelled")
            try:
                self._load_tokens()
                with self._lock:
                    ig, iid, key, token = (
                        self._ig, self._iid, self._key, self._token)
                api_url = self.HOST_URL.replace("Translator", "ttranslatev3")
                url = f"{api_url}?isVertical=1&&IG={ig}&IID={iid}"
                r = self._spost(
                    url,
                    data={"text": text, "fromLang": src, "to": target,
                          "tryFetchingGenderDebiasedTranslations": "true",
                          "key": key, "token": token},
                    headers={"Referer": self.HOST_URL,
                             "Origin": "https://www.bing.com",
                             "Accept": "application/json",
                             "X-Requested-With": "XMLHttpRequest",
                             "Content-Type": "application/x-www-form-urlencoded; "
                                             "charset=UTF-8"},
                    timeout=30)
                r.raise_for_status()
                data = r.json()
                if isinstance(data, list) and data:
                    return data[0]["translations"][0]["text"]
                if isinstance(data, dict) and data.get("statusCode") == 205:
                    raise ValueError("token expired")
                raise ValueError(f"unexpected response: {data}")
            except (requests.RequestException, ValueError, KeyError,
                    IndexError) as e:
                last_err = e
                # токены могли протухнуть или страница изменилась —
                # полный сброс и повторная загрузка
                self._reset_tokens()
                if attempt < 2:
                    self._sleep_cancellable(0.8 * (attempt + 1))
        raise EngineError(
            f"Bing Translator unavailable: {last_err}") from last_err


class MyMemoryEngine(BaseEngine):
    """MyMemory — официальный бесплатный API (api.mymemory.translated.net).

    Лимиты (официальные, mymemory.translated.net/doc/usagelimits.php):
      * анонимно      — 5 000 символов/день на IP;
      * с почтой ('de') — 50 000 символов/день.
    Раньше и в коде, и в UI стояло 50K — это лимит С ПОЧТОЙ. Без неё
    движок упирается в 5K и почти сразу получает отказ, поэтому в пул
    он идёт только с заданным email, а по умолчанию считается мелким.

    Параметр q ограничен 500 байтами — длинные строки режутся на куски.
    """

    name = "mymemory"
    API = "https://api.mymemory.translated.net/get"
    _WORKERS = 6
    _CHUNK_BYTES = 480

    def __init__(self, api_key: str = "", email: str = ""):
        super().__init__()
        self.api_key = api_key or ""
        self.email = (email or "").strip()

    def usable(self) -> bool:
        """Без почты лимит 5K/день — движок в пул не берём."""
        return bool(self.email)

    def ping(self) -> bool:
        try:
            self._check_cancel()
            r = requests.get(self.API, params={"q": "Hello", "langpair": "en|ru"},
                             timeout=8)
            data = r.json()
            return bool(data.get("responseStatus") == 200
                        and data.get("responseData"))
        except (requests.RequestException, ValueError):
            return False

    def translate(self, texts, source, target, context_before=None,
                  context_after=None) -> list[str]:
        if not texts:
            return []
        try:
            pair = ("Autodetect" if source == "auto" else source) + "|" + target
            with ThreadPoolExecutor(max_workers=self._WORKERS) as ex:
                futs = {ex.submit(self._translate_one, t, pair): i
                        for i, t in enumerate(texts)}
                # По готовности, а не по порядку: зависший запрос не
                # стопарит готовые (head-of-line блокировка).
                out: list = [None] * len(futs)
                for f in as_completed(futs):
                    out[futs[f]] = f.result()
        except InterruptedError:
            raise
        except Exception as e:  # noqa: BLE001
            raise EngineError(f"MyMemory unavailable: {e}") from e
        return self._align(texts, self._guard_tokens(texts, out))

    def _split(self, text: str) -> list[str]:
        """Режет строку на куски по 480 байт (лимит API на q)."""
        if len(text.encode("utf-8")) <= self._CHUNK_BYTES:
            return [text]
        parts: list[str] = []
        buf = ""
        for ch in text:
            if len((buf + ch).encode("utf-8")) > self._CHUNK_BYTES:
                parts.append(buf)
                buf = ch
            else:
                buf += ch
        if buf:
            parts.append(buf)
        return parts

    def _translate_one(self, text: str, pair: str) -> str | None:
        self._check_cancel()
        data = {"q": text, "langpair": pair}
        if self.email:
            # с почтой лимит выше: 50 000 символов/день вместо 5 000
            data["de"] = self.email
        if self.api_key:
            data["key"] = self.api_key
        chunks = self._split(text)
        got: list[str] = []
        for chunk in chunks:
            self._check_cancel()
            r = requests.post(self.API, data={**data, "q": chunk},
                              timeout=20)
            resp = r.json()
            self._check_cancel()
            if not isinstance(resp, dict) or resp.get("responseStatus") != 200:
                # не 200 = дневной лимит исчерпан либо сервис отказал
                raise EngineError("MyMemory: bad response")
            rd = resp.get("responseData") or {}
            out = rd.get("translatedText")
            if out is None:
                raise EngineError("MyMemory: no translatedText")
            got.append(str(out))
        return "".join(got) or None

    def _check_cancel(self):
        if self.cancelled:
            raise InterruptedError




class RotateEngine(BaseEngine):
    """ЕДИНСТВЕННЫЙ движок приложения: пул бесплатных провайдеров,
    крутится по лимитам, пока всё не переведёт. Выбора нет и не надо.

    Порядок пула: Google пакетами (до 100 строк за запрос, в разы
    быстрее построчных) → две сессии Bing (у каждой свой токен
    и своя квота) → MyMemory (только с почтой: анонимный лимит
    5K/день кончается мгновенно).
    Строка уходит тому, кто сейчас не в кулдауне; отказ — отдых
    и следующий по кругу. Круг повторяется, пока есть прогресс.

    Кулдауны и счётчики отказов лежат в engine_health.json и переживают
    перезапуск: закрыли приложение, открыли — «отдохнувший» провайдер
    не трогается до конца своего кулдауна.

    Гарантия: translate() не бросает EngineError. Строку, которую не смог
    перевести ни один провайдер, возвращает как None — сервис оставит её
    не переведённой и повторит позже, а не запишет оригинал с пометкой
    «переведено». Если весь пул в кулдауне — движок спит до конца
    ближайшего и продолжает работу.
    """

    name = "rotate"
    WORKERS = 6
    BING_SESSIONS = 2
    # пауза между кругами, когда все живые ответили пустым
    IDLE_SLEEP = 5.0

    def __init__(self, mymemory_email: str = ""):
        super().__init__()
        # Google — основной (пакетами), дальше резерв: две сессии Bing
        # (у каждой свой токен и своя квота), дальше MyMemory с почтой.
        # Мёртвый источник (эндпоинт недоступен из этой сети) помечается
        # «упал» и больше не трогается — см. BaseEngine.report_failure.
        self._engines: list[BaseEngine] = [GoogleFreeEngine()] + [
            BingEngine() for _ in range(self.BING_SESSIONS)]
        if (mymemory_email or "").strip():
            self._engines.append(
                MyMemoryEngine(email=mymemory_email.strip()))
        self._cursor = 0
        self._lock = threading.Lock()

    def cancel(self):
        super().cancel()
        for e in self._engines:
            e.cancel()

    def ping(self) -> bool:
        return any(e.ping() for e in self._engines)

    def wait_hint(self) -> float:
        """Сколько секунд сервис должен подождать перед следующим кругом.

        0 — можно пробовать сейчас (или сети нет вовсе и ждать нечего,
        тогда сервис закончит строки и повторит их при следующем запуске).
        """
        usable = [e for e in self._engines if not e.is_down()]
        if not usable:
            return 0.0
        waits = [e.cooldown_left() for e in usable]
        return min(waits) if waits else 0.0

    def _live(self) -> list[BaseEngine]:
        return [e for e in self._engines
                if e.cooldown_left() <= 0 and not e.is_down()]

    def all_down(self) -> bool:
        """Все провайдеры помечены упавшими — сети нет, ждать нечего."""
        return bool(self._engines) and all(e.is_down() for e in self._engines)

    def translate(self, texts: list[str], source: str, target: str,
                  context_before: list[str] | None = None,
                  context_after: list[str] | None = None) -> list:
        if not texts:
            return []
        if self.cancelled:
            raise InterruptedError("cancelled")
        if len(texts) == 1:
            return [self._translate_one(texts[0], source, target)]
        # быстрый путь: Google пакетами
        primary = self._engines[0]
        if primary.cooldown_left() <= 0 and not primary.is_down():
            out = None
            try:
                out = primary.translate(texts, source, target)
            except InterruptedError:
                raise
            except Exception as e:  # noqa: BLE001 — отказ не важен
                primary.report_failure(e, _RATE_LIMIT_COOLDOWN)
            if out is not None:
                aligned = self._align(texts, out)
                if all(o and o.strip() for o in aligned):
                    return self._guard_tokens(texts, aligned)
        # фолбэк: по одной строке с чередованием провайдеров.
        # Результаты забираем по готовности (as_completed): зависший
        # провайдер на одной строке не стопарит готовые остальные.
        out = [None] * len(texts)
        with ThreadPoolExecutor(max_workers=self.WORKERS) as ex:
            futures = {ex.submit(self._translate_one, t, source, target): i
                       for i, t in enumerate(texts)}
            for f in as_completed(futures):
                try:
                    out[futures[f]] = f.result()
                except InterruptedError:
                    raise
                except Exception:  # noqa: BLE001
                    out[futures[f]] = None
        return self._align(texts, out)

    def _translate_one(self, text: str, source: str, target: str) -> str | None:
        """Один проход по пулу. None — не осилил ни один живой провайдер.

        Здесь нет ожидания: ждать умеет сервис (между кругами, один раз
        на всю группу строк). Ожидание на каждую строку при мёртвой сети
        превращало 70 строк в 70×120 секунд.
        """
        for eng in self._live():
            if self.cancelled:
                raise InterruptedError("cancelled")
            with self._lock:
                self._cursor += 1
            try:
                out = eng.translate([text], source, target)
            except InterruptedError:
                raise
            except Exception as e:  # noqa: BLE001
                # отказ провайдера: уводим в кулдаун, берём следующего
                eng.report_failure(e)
                continue
            res = out[0] if out else None
            if res and res.strip():
                clear_engine_cooldown(eng.name)
                return res
            # пустой ответ: провайдер жив, строку не перевёл. Отказом не
            # считаем — просто берём следующего.
        return None


# реестр провайдеров для настроек: только бесплатные, без нейросетей.
# AI (OpenAI/Ollama) и офлайн-NLLB удалены решением владельца:
# ключи, локальные серверы и модели на 600 МБ — не наш путь.
PROVIDERS = {
    "rotate": "Бесплатный автопилот — Google пакетами + Bing "
              "в резерве (сам уходит в отдых при лимите и продолжает)",
    "google_free": "Google Translate — бесплатный (без ключа)",
    "bing": "Bing Translator — бесплатный (без ключа)",
    "mymemory": "MyMemory — официальный бесплатный API (5K символов/день "
                "без почты, 50K — с почтой)",
}


def get_engine(name: str, **kwargs) -> BaseEngine:
    engines = {
        "google_free": GoogleFreeEngine,
        "bing": BingEngine,
        "mymemory": MyMemoryEngine,
        "rotate": RotateEngine,
    }
    if name not in engines:
        if name in ("ai", "ollama", "openai_compat", "corrector",
                    "honyaku", "argos", "nllb", "libretranslate"):
            # старые настройки с удалёнными движками — молча
            # переводим на rotate (при запуске они обновляются в QSettings)
            return RotateEngine()
        raise EngineError(f"Unknown engine: {name}")
    return engines[name](**kwargs)


ENGINE_HINTS: dict[str, str] = {}


def engine_hint(name: str) -> str:
    return ENGINE_HINTS.get(name, "Check that the engine is running.")

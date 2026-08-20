# -*- coding: utf-8 -*-
"""Движки машинного перевода: AI (LLM), Google Free, Bing, Rotate."""
from __future__ import annotations

import html
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# сколько секунд Google «отдыхает» после 429/капчи (страница /sorry/)
_RATE_LIMIT_COOLDOWN = 60.0

# адрес публичного сервера LibreTranslate по умолчанию (можно заменить
# на свой в настройках; ключ необязателен)
LIBRETRANSLATE_DEFAULT_URL = "https://libretranslate.com"

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
    # флаг отмены: класс-атрибут, чтобы подклассы без __init__-вызова
    # суперкласса (GoogleFreeEngine и др.) читали его без инициализации
    cancelled = False

    def cancel(self):
        """Просит движок остановиться. Проверки выполняются в
        translate() и перед сетевыми запросами/ожиданиями."""
        self.cancelled = True

    def translate(self, texts: list[str], source: str, target: str,
                  context_before: list[str] | None = None,
                  context_after: list[str] | None = None) -> list[str]:
        raise NotImplementedError

    def _guard_tokens(self, texts: list[str],
                      out: list[str]) -> list[str]:
        """Страховка для любых движков (AI, Google, Bing): если перевод
        потерял/переставил токены <xN/> (макросы, ссылки, коды), строка
        возвращается непереведённой — иначе игра упадёт («cannot find a
        closing tag for macro», битые ссылки и т.п.)."""
        return [src_s if _tokens(src_s) != _tokens(tr_s) else tr_s
                for src_s, tr_s in zip(texts, out)]

    def ping(self) -> bool:
        return False


class AIEngine(BaseEngine):
    """OpenAI-совместимый API / локальный LLM (Ollama, OpenRouter, OpenAI, LM Studio)."""

    name = "ai"

    def __init__(self, base_url: str = "https://openrouter.ai/api/v1",
                 api_key: str = "", model: str = "", batch_size: int = 8):
        self.base_url = (base_url or "https://openrouter.ai/api/v1").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.batch_size = batch_size

    def ping(self) -> bool:
        if not self.api_key and "localhost" not in self.base_url and "11434" not in self.base_url:
            return False
        try:
            requests.get(f"{self.base_url}/models",
                         headers=self._headers(), timeout=5)
            return True
        except requests.RequestException:
            return False

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def complete(self, prompt: str) -> str:
        """Сырой запрос к LLM (для перевода и ИИ-коррекции)."""
        try:
            r = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={"model": self.model, "temperature": 0.2,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=30,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            raise EngineError(f"AI unavailable: {e}") from e
        try:
            return r.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError) as e:
            raise EngineError(f"Invalid AI response: {e}") from e

    def _parse_translate_response(self, content: str, n: int) -> list[str] | None:
        """Разбирает ответ LLM: JSON-массив, JSONL ({"i": N, "t": "..."})
        или строки по одной на строку. При ошибке — None."""
        if not content:
            return None
        # 1. JSON-массив
        try:
            start = content.index("[")
            end = content.rindex("]") + 1
            out = json.loads(content[start:end])
            if isinstance(out, list) and len(out) == n:
                return [str(x) for x in out]
        except (ValueError, json.JSONDecodeError):
            pass
        # 2. JSONL: одна строка — один объект {"i": N, "t": "..."}
        by_index: dict[int, str] = {}
        for line in content.splitlines():
            line = line.strip().strip(",")
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (isinstance(obj, dict) and isinstance(obj.get("i"), int)
                    and isinstance(obj.get("t"), str)):
                by_index[obj["i"]] = obj["t"]
        if len(by_index) == n and all(i in by_index for i in range(n)):
            return [by_index[i] for i in range(n)]
        # 3. каждая строка — строка JSON (модель забыла про JSONL)
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        if len(lines) == n:
            out = []
            for line in lines:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    break
            if len(out) == n:
                return [str(x) for x in out]
        return None

    def _translate_batch(self, batch: list[str], source: str, target: str,
                         context_before: list[str] | None = None,
                         context_after: list[str] | None = None) -> list[str]:
        src = LANG_NAMES.get(source, source)
        tgt = LANG_NAMES.get(target, target)
        payload = json.dumps(batch, ensure_ascii=False)
        ctx = ""
        if context_before:
            prev = json.dumps(context_before[-3:], ensure_ascii=False)
            ctx += f"\nPrevious lines for context: {prev}"
        if context_after:
            nxt = json.dumps(context_after[:3], ensure_ascii=False)
            ctx += f"\nNext lines for context: {nxt}"
        # TextPreserve sample: список кодов в батче, чтобы модель их не трогала
        codes = sorted(set(re.findall(r"</?x\d+\s*/?>", "".join(batch))))
        codes_hint = ""
        if codes:
            codes_hint = ("Codes in this batch, keep each of them exactly "
                          "as-is, do not translate, drop or reorder them: "
                          + " ".join(codes))
        prompt = (
            f"Translate the following JSON array of JRPG dialogue strings "
            f"from {src} to {tgt}. Rules: keep every placeholder like <x0/> "
            f"exactly as-is and in the same order; do not add, remove or "
            f"reorder any symbols — brackets, parentheses, quotes, "
            f"apostrophes, dashes, digits, percent signs, backslashes, "
            f"tags, variables and macros must stay unchanged, translate "
            f"only words; keep the tone of an RPG; do not add comments. "
            f"Answer with JSON lines — one object per "
            f"line: {{\"i\": index, \"t\": \"translation\"}}.{codes_hint}"
            f"{ctx}\n{payload}"
        )
        content = self.complete(prompt)
        out = self._parse_translate_response(content, len(batch))
        if out is None:
            raise EngineError("AI returned response of wrong length")
        # Страховка: строки, где модель потеряла/переставила токены
        # <xN/>, остаются непереведёнными — иначе игра упадёт
        return self._guard_tokens(batch, out)

    def translate(self, texts: list[str], source: str, target: str,
                  context_before: list[str] | None = None,
                  context_after: list[str] | None = None) -> list[str]:
        result: list[str] = []
        for i in range(0, len(texts), self.batch_size):
            if self.cancelled:
                raise InterruptedError("cancelled")
            chunk = texts[i:i + self.batch_size]
            cb = context_before[i:] if context_before else None
            ca = context_after[i + len(chunk):] if context_after else None
            result.extend(self._translate_batch(chunk, source, target, cb, ca))
        return result


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
        self._ratelimit_until = 0.0
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": self._UA,
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        })

    def _rate_limited(self) -> bool:
        return time.time() < self._ratelimit_until

    def _mark_rate_limited(self, duration: float = _RATE_LIMIT_COOLDOWN) -> None:
        self._ratelimit_until = time.time() + duration

    def _is_rate_limit(self, r) -> bool:
        """429/403 или переадресация на страницу капчи /sorry/."""
        return (getattr(r, "status_code", 200) in (429, 403)
                or "sorry" in getattr(r, "url", ""))

    def ping(self) -> bool:
        try:
            self._session.get(self.URL_SINGLE,
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
            r = self._session.post(
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
                r = self._session.get(self.URL_SINGLE, params={
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
                    time.sleep(6.0 * (attempt + 1) if self._rate_limited()
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
            r = self._session.get(self.URL_M, params={
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
                r = self._session.get(self.URL_SINGLE, params={
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
                    time.sleep(6.0 * (attempt + 1) if self._rate_limited()
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
                results[futures[f]] = f.result()
        out: list[str | None] = [None] * len(texts)
        for i, res in enumerate(results):
            if res is None:
                continue
            for j, t in enumerate(res):
                out[i * self.BATCH_LINES + j] = t
        out = [o for o in out if o is not None]
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
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": self._UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        self._ig: str | None = None
        self._iid: str | None = None
        self._token: str | None = None
        self._key: str | None = None

    # ── токены ──
    def _load_tokens(self):
        if self._ig and self._token:
            return
        r = self._session.get(self.HOST_URL, timeout=15)
        r.raise_for_status()
        html = r.text
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
                api_url = self.HOST_URL.replace("Translator", "ttranslatev3")
                url = f"{api_url}?isVertical=1&&IG={self._ig}&IID={self._iid}"
                r = self._session.post(
                    url,
                    data={"text": text, "fromLang": src, "to": target,
                          "tryFetchingGenderDebiasedTranslations": "true",
                          "key": self._key, "token": self._token},
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
                self._ig = self._iid = self._token = self._key = None
                if attempt < 2:
                    import time
                    time.sleep(0.8 * (attempt + 1))
        raise EngineError(
            f"Bing Translator unavailable: {last_err}") from last_err


class MyMemoryEngine(BaseEngine):
    """MyMemory — официальный бесплатный API перевода (без ключа).

    Лимит: 50 000 символов/день на IP, честный и публичный сервис
    (api.mymemory.translated.net) — в отличие от неофициальных
    эндпоинтов Google не ловит капчу/429, но качество RU ниже.
    API принимает по одному тексту за запрос — строки переводятся
    параллельно, результат склеивается в порядке исходного списка.
    """

    name = "mymemory"
    API = "https://api.mymemory.translated.net/get"
    _WORKERS = 6

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or ""

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
                futs = [ex.submit(self._translate_one, t, pair)
                        for t in texts]
                out = [f.result() for f in futs]
        except InterruptedError:
            raise
        except Exception as e:  # noqa: BLE001
            raise EngineError(f"MyMemory unavailable: {e}") from e
        return self._guard_tokens(texts, out)

    def _translate_one(self, text: str, pair: str) -> str:
        self._check_cancel()
        r = requests.post(self.API, data={"q": text, "langpair": pair},
                          timeout=20)
        data = r.json()
        self._check_cancel()
        if not isinstance(data, dict) or data.get("responseStatus") != 200:
            raise EngineError("MyMemory: bad response")
        rd = data.get("responseData") or {}
        out = rd.get("translatedText")
        if out is None:
            raise EngineError("MyMemory: no translatedText")
        return out

    def _check_cancel(self):
        if self.cancelled:
            raise InterruptedError


class LibreTranslateEngine(BaseEngine):
    """LibreTranslate — открытый бесплатный переводчик (публичный сервер
    или свой в Docker). Весь пакет уходит одним запросом (q: массив),
    ключ не обязателен; source 'auto' — автоопределение сервера."""

    name = "libretranslate"
    DEFAULT_URL = "https://libretranslate.com"

    def __init__(self, base_url: str = "", api_key: str = ""):
        self.base_url = (base_url or self.DEFAULT_URL).rstrip("/")
        self.api_key = api_key or ""

    def ping(self) -> bool:
        try:
            self._check_cancel()
            r = requests.get(f"{self.base_url}/languages", timeout=8)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def translate(self, texts, source, target, context_before=None,
                  context_after=None) -> list[str]:
        if not texts:
            return []
        payload = {"q": list(texts), "source": source, "target": target,
                   "format": "text"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            self._check_cancel()
            r = requests.post(f"{self.base_url}/translate", json=payload,
                              headers=headers, timeout=30)
            self._check_cancel()
            data = r.json()
        except InterruptedError:
            raise
        except (requests.RequestException, ValueError) as e:
            raise EngineError(f"LibreTranslate unavailable: {e}") from e
        if isinstance(data, dict) and data.get("error"):
            raise EngineError(f"LibreTranslate: {data['error']}")
        if not isinstance(data, list) or len(data) != len(texts):
            raise EngineError("LibreTranslate: wrong response length")
        return self._guard_tokens(texts, [str(t) for t in data])

    def _check_cancel(self):
        if self.cancelled:
            raise InterruptedError


class RotateEngine(BaseEngine):
    """Google пакетно + Bing в фолбэке.

    Основной путь — Google: весь список строк уходит пакетами
    (до BATCH_LINES строк на запрос, десятки раз быстрее построчных
    запросов). Если Google недоступен — построчный обход с чередованием
    Google ↔ Bing (round-robin): при ошибке одного провайдера строка
    уходит другому.

    У Bing несколько независимых сессий — у каждой свой токен и квота.
    """

    name = "rotate"
    WORKERS = 6
    BING_SESSIONS = 2

    def __init__(self):
        self._engines = [GoogleFreeEngine()] + [
            BingEngine() for _ in range(self.BING_SESSIONS)]
        self._cursor = 0
        self._lock = threading.Lock()

    def cancel(self):
        super().cancel()
        for e in self._engines:
            e.cancel()

    def ping(self) -> bool:
        return any(e.ping() for e in self._engines)

    def translate(self, texts: list[str], source: str, target: str,
                  context_before: list[str] | None = None,
                  context_after: list[str] | None = None) -> list[str]:
        if not texts:
            return []
        if self.cancelled:
            raise InterruptedError("cancelled")
        if len(texts) == 1:
            return [self._translate_one(texts[0], source, target)]
        try:
            return self._engines[0].translate(texts, source, target)
        except InterruptedError:
            raise
        except EngineError:
            pass
        # фолбэк: по одной строке с чередованием провайдеров
        out: list[str | None] = [None] * len(texts)
        with ThreadPoolExecutor(max_workers=self.WORKERS) as ex:
            futures = [ex.submit(self._translate_one, t, source, target)
                       for t in texts]
            for i, f in enumerate(futures):
                out[i] = f.result()
        out = [o for o in out if o is not None]
        return self._guard_tokens(texts, out)

    def _translate_one(self, text: str, source: str, target: str) -> str:
        # если Google в кулдауне (429/капча) — не трогаем его вообще,
        # работаем только на Bing-сессиях
        engines = self._engines
        if self._engines[0]._rate_limited():
            engines = self._engines[1:] + [self._engines[0]]
        last_err = None
        for _ in range(len(engines)):
            if self.cancelled:
                raise InterruptedError("cancelled")
            with self._lock:
                eng = engines[self._cursor % len(engines)]
                self._cursor += 1
            try:
                return eng.translate([text], source, target)[0]
            except InterruptedError:
                raise
            except Exception as e:  # noqa: BLE001
                last_err = e
        raise EngineError(f"Rotate unavailable: {last_err}") from last_err


# реестр провайдеров для настроек
PROVIDERS = {
    "google_free": "Google Translate — бесплатный (без ключа)",
    "bing": "Bing Translator — бесплатный (без ключа)",
    "mymemory": "MyMemory — бесплатный API (50K символов/день, без ключа)",
    "libretranslate": "LibreTranslate — открытый и бесплатный (публичный или свой сервер)",
    "rotate": "Google + Bing — Google пакетами, фолбэк на Bing (быстрее)",
    "ai": "AI — OpenAI/Ollama/LM Studio (требуется API или локальный сервер)",
}

# провайдеры для ИИ-коррекции (только LLM)
AI_PROVIDERS = {
    "ai": "AI — OpenAI/Ollama/LM Studio",
}


def get_engine(name: str, **kwargs) -> BaseEngine:
    engines = {
        "ai": AIEngine,
        "ollama": AIEngine,
        "openai_compat": AIEngine,
        "google_free": GoogleFreeEngine,
        "bing": BingEngine,
        "mymemory": MyMemoryEngine,
        "libretranslate": LibreTranslateEngine,
        "rotate": RotateEngine,
    }
    if name not in engines:
        if name in ("honyaku", "argos", "nllb"):
            # старые настройки с удалённым офлайн-переводчиком — молча
            # переводим на rotate (при запуске они обновляются в QSettings)
            return RotateEngine()
        raise EngineError(f"Unknown engine: {name}")
    if name in ("ollama", "openai_compat"):
        kwargs.setdefault("base_url", "http://localhost:11434")
        return AIEngine(**kwargs)
    return engines[name](**kwargs)


ENGINE_HINTS = {
    "ai": (
        "AI provider is not connected.\n\n"
        "For local LLM: install Ollama, pull a model, it runs on port 11434.\n"
        "For remote API: set base URL and API key in Settings.\n"
        "Check connection with 'Test Connection' button."
    ),
}


def engine_hint(name: str) -> str:
    return ENGINE_HINTS.get(name, "Check that the engine is running.")

# -*- coding: utf-8 -*-
"""Движки машинного перевода: AI (LLM), Argos (встроенный офлайн), Google Free."""
from __future__ import annotations

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import requests

LANG_NAMES = {
    "ja": "Japanese", "zh": "Chinese", "en": "English",
    "ru": "Russian", "ko": "Korean",
}


class EngineError(Exception):
    pass


class BaseEngine:
    name = "base"

    def translate(self, texts: list[str], source: str, target: str,
                  context_before: list[str] | None = None,
                  context_after: list[str] | None = None) -> list[str]:
        raise NotImplementedError

    def ping(self) -> bool:
        return False


class AIEngine(BaseEngine):
    """OpenAI-совместимый API / локальный LLM (Ollama, OpenRouter, OpenAI, LM Studio)."""

    name = "ai"

    def __init__(self, base_url: str = "https://openrouter.ai/api/v1",
                 api_key: str = "", model: str = "", batch_size: int = 8):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
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
            f"exactly as-is and in the same order; keep the tone of an RPG; "
            f"do not add comments. Answer with JSON lines — one object per "
            f"line: {{\"i\": index, \"t\": \"translation\"}}.{codes_hint}"
            f"{ctx}\n{payload}"
        )
        content = self.complete(prompt)
        out = self._parse_translate_response(content, len(batch))
        if out is not None:
            return out
        raise EngineError("AI returned response of wrong length")

    def translate(self, texts: list[str], source: str, target: str,
                  context_before: list[str] | None = None,
                  context_after: list[str] | None = None) -> list[str]:
        result: list[str] = []
        for i in range(0, len(texts), self.batch_size):
            chunk = texts[i:i + self.batch_size]
            cb = context_before[i:] if context_before else None
            ca = context_after[i + len(chunk):] if context_after else None
            result.extend(self._translate_batch(chunk, source, target, cb, ca))
        return result


class ArgosEngine(BaseEngine):
    """Встроенный офлайн-перевод на argostranslate (CTranslate2).

    Не требует внешних программ. Языковые пакеты (~100-300 МБ) скачиваются
    один раз из настроек приложения. Направления вроде ja→ru переводятся
    автоматически через английский (ja→en→ru).
    """

    name = "argos"

    def __init__(self):
        try:
            import argostranslate.translate as tr
            self._tr = tr
            self._translators: dict = {}
        except ImportError:
            self._tr = None
            self._translators = {}

    def _get_tr(self, source: str, target: str):
        key = (source, target)
        tr = self._translators.get(key)
        if tr is not None:
            return tr
        langs = self._tr.get_installed_languages()
        langs_dict = {l.code: l for l in langs}
        from_lang = langs_dict.get(source)
        to_lang = langs_dict.get(target)
        if from_lang is None or to_lang is None:
            return None
        tr = from_lang.get_translation(to_lang)
        self._translators[key] = tr
        return tr

    def ping(self) -> bool:
        if self._tr is None:
            return False
        return len(self._tr.get_installed_languages()) > 0

    def translate(self, texts: list[str], source: str, target: str,
                  context_before: list[str] | None = None,
                  context_after: list[str] | None = None) -> list[str]:
        if self._tr is None:
            raise EngineError(
                "argostranslate package not installed "
                "(pip install argostranslate)")
        if source == target:
            return list(texts)
        tr = self._get_tr(source, target)
        if tr is not None:
            return [tr.translate(t) for t in texts]
        tr_src_en = self._get_tr(source, "en")
        tr_en_tgt = self._get_tr("en", target)
        if tr_src_en is None or tr_en_tgt is None:
            raise EngineError(
                f"No Argos models for {source}→{target} or "
                f"{source}→en→{target}. Download in Settings.")
        result = []
        for t in texts:
            en = tr_src_en.translate(t)
            result.append(tr_en_tgt.translate(en))
        return result


class GoogleFreeEngine(BaseEngine):
    """Google Translate — бесплатный неофициальный endpoint (без ключа).

    Endpoint не поддерживает пакетную отправку (несколько q= игнорирует),
    поэтому ускорение — параллельными запросами: пул потоков, каждый
    запрос ждёт только сеть, CPU почти не тратится.
    """

    name = "google_free"
    URL = "https://translate.googleapis.com/translate_a/single"
    WORKERS = 4

    def ping(self) -> bool:
        try:
            requests.get(self.URL, params={"client": "gtx", "sl": "en",
                                           "tl": "ru", "dt": "t", "q": "hi"},
                         timeout=5)
            return True
        except requests.RequestException:
            return False

    def _translate_one(self, text: str, src: str, target: str) -> str:
        import time
        last_err = None
        for attempt in range(3):
            try:
                r = requests.get(self.URL, params={
                    "client": "gtx", "sl": src, "tl": target,
                    "dt": "t", "q": text}, timeout=30)
                r.raise_for_status()
                data = r.json()
                return "".join(seg[0] for seg in data[0] if seg[0])
            except (requests.RequestException, ValueError, TypeError,
                    KeyError, IndexError) as e:
                last_err = e
                if attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
        raise EngineError(
            f"Google Translate unavailable: {last_err}") from last_err

    def translate(self, texts: list[str], source: str, target: str,
                  context_before: list[str] | None = None,
                  context_after: list[str] | None = None) -> list[str]:
        if not texts:
            return []
        src = "auto" if source == "auto" else source
        if len(texts) == 1:
            return [self._translate_one(texts[0], src, target)]
        out: list[str | None] = [None] * len(texts)
        with ThreadPoolExecutor(max_workers=self.WORKERS) as ex:
            futures = [ex.submit(self._translate_one, t, src, target)
                       for t in texts]
            for i, f in enumerate(futures):
                out[i] = f.result()
        return [o for o in out if o is not None]


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
        m = re.search(r'\bIG:"([^"]+)"', html)
        if m:
            self._ig = m.group(1)
        m = re.search(r'id="tta_outGDCont"[^>]*data-iid="([^"]+)"', html)
        if not m:
            m = re.search(r'_iid="([^"]+)"', html)
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
        return out

    def _translate_one(self, text: str, source: str, target: str) -> str:
        src = "auto-detect" if source == "auto" else source
        last_err = None
        for attempt in range(3):
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
                             "Origin": "https://www.bing.com"},
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
                # токены могли протухнуть — сброс и повторная загрузка
                self._ig = self._iid = self._token = self._key = None
                if attempt < 2:
                    import time
                    time.sleep(0.8 * (attempt + 1))
        raise EngineError(
            f"Bing Translator unavailable: {last_err}") from last_err


class RotateEngine(BaseEngine):
    """Чередование Google ↔ Bing (round-robin) для ускорения перевода.

    Запросы распределяются между провайдерами по очереди; при ошибке
    одного из них автоматически используется другой (fallback).

    Тексты переводятся параллельно (пул потоков): каждый запрос к
    Google/Bing ждёт только сеть, CPU почти не тратится, поэтому
    несколько параллельных запросов дают почти линейный прирост.
    У Bing несколько сессий — у каждой свой токен и своя квота.
    """

    name = "rotate"
    WORKERS = 6
    BING_SESSIONS = 2

    def __init__(self):
        self._engines = ([GoogleFreeEngine(), BingEngine()]
                         * self.BING_SESSIONS)
        self._cursor = 0
        self._lock = threading.Lock()

    def ping(self) -> bool:
        return any(e.ping() for e in self._engines)

    def translate(self, texts: list[str], source: str, target: str,
                  context_before: list[str] | None = None,
                  context_after: list[str] | None = None) -> list[str]:
        if not texts:
            return []
        if len(texts) == 1:
            return [self._translate_one(texts[0], source, target)]
        out: list[str | None] = [None] * len(texts)
        with ThreadPoolExecutor(max_workers=self.WORKERS) as ex:
            futures = [ex.submit(self._translate_one, t, source, target)
                       for t in texts]
            for i, f in enumerate(futures):
                out[i] = f.result()
        return [o for o in out if o is not None]

    def _translate_one(self, text: str, source: str, target: str) -> str:
        last_err = None
        for _ in range(len(self._engines)):
            with self._lock:
                eng = self._engines[self._cursor % len(self._engines)]
                self._cursor += 1
            try:
                return eng.translate([text], source, target)[0]
            except Exception as e:  # noqa: BLE001
                last_err = e
        raise EngineError(f"Rotate unavailable: {last_err}") from last_err


class NllbEngine(BaseEngine):
    """Удалённый движок — оставлен как заглушка для старых настроек.

    NLLB-200 требует transformers+torch (~2.5 ГБ + модель 2.3 ГБ),
    поэтому исключён из состава приложения. Старые настройки,
    где провайдером выбран 'nllb', переводят на Argos.
    """

    name = "nllb"

    def __init__(self, *args, **kwargs):
        self.use_gpu = False

    def ping(self) -> bool:
        return False

    def translate(self, texts, source, target, *args, **kwargs):
        raise EngineError(
            "NLLB-200 удалён из приложения — используйте Argos "
            "(настройки → провайдер).")


# реестр провайдеров для настроек
PROVIDERS = {
    "argos": "Argos — встроенный офлайн (без ключа)",
    "google_free": "Google Translate — бесплатный (без ключа)",
    "bing": "Bing Translator — бесплатный (без ключа)",
    "rotate": "Google + Bing — чередование (быстрее)",
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
        "argos": ArgosEngine,
        "google_free": GoogleFreeEngine,
        "bing": BingEngine,
        "rotate": RotateEngine,
        "nllb": NllbEngine,
    }
    if name not in engines:
        raise EngineError(f"Unknown engine: {name}")
    if name == "argos":
        kwargs.pop("url", None)
    if name == "nllb":
        # старые настройки с удалённым NLLB — молча переводим на Argos
        return ArgosEngine()
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
    "argos": (
        "Offline engine is not ready.\n\n"
        "If this is the first launch — download language packs with "
        "'Download Language Packs' button in Settings "
        "(~100-300 MB per pair, one-time download)."
    ),
}


def engine_hint(name: str) -> str:
    return ENGINE_HINTS.get(name, "Check that the engine is running.")


# ---------- скачивание языковых пакетов Argos ----------

ARGOS_ALL_PAIRS = [("ja", "en"), ("zh", "en"), ("en", "ru"), ("ru", "en")]


def argos_missing_pairs_all() -> list[tuple[str, str]]:
    try:
        import argostranslate.translate as tr
    except ImportError:
        raise EngineError("argostranslate not installed")
    installed = {(t.from_lang.code, t.to_lang.code)
                 for l in tr.get_installed_languages()
                 for t in l.translations_from}
    return [p for p in ARGOS_ALL_PAIRS if p not in installed]


def argos_download(pairs: list[tuple[str, str]],
                   progress=None) -> list[str]:
    import argostranslate.package as pkg
    pkg.update_package_index()
    available = pkg.get_available_packages()
    done = []
    for i, (src, dst) in enumerate(pairs):
        package = next((p for p in available
                        if p.from_code == src and p.to_code == dst), None)
        if package is None:
            raise EngineError(f"Package {src}→{dst} not found in Argos catalog")
        if progress:
            progress(i + 1, len(pairs), f"{src}→{dst}")
        download_path = package.download()
        pkg.install_from_path(download_path)
        done.append(f"{src}→{dst}")
    return done

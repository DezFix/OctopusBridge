# -*- coding: utf-8 -*-
"""Движки машинного перевода: AI (LLM), Honyaku (встроенный офлайн),
Google Free, Bing."""
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


class HonyakuEngine(BaseEngine):
    """Встроенный офлайн-перевод на собственной библиотеке honyaku
    (CTranslate2 + SentencePiece, без PyTorch).

    Два тира моделей:
      * fast — OPUS-MT, отдельная маленькая модель на ядровые пары
        (ja→ru, ja→en, en→ru), максимальная скорость;
      * best — NLLB-200 distilled 600M, ОДНА модель на все пары
        (ja/zh/ko/ru/en/fr/de/es/it/pt), заметно лучше смысл.

    Модели качаются автоматически при первом переводе (обе тиры —
    fast для ядровых пар, best как запасная и для остальных пар).
    """

    name = "honyaku"
    DEFAULT_PAIRS = [
        ("ja", "ru"), ("ja", "en"), ("zh", "ru"), ("zh", "en"),
        ("en", "ru"),
    ]
    _FAST_PAIRS = ("ja-ru", "ja-en", "en-ru", "zh-en")

    def __init__(self, tier: str = "best"):
        try:
            from app.translators.honyaku import Translator
            self._Translator = Translator
        except ImportError:
            self._Translator = None
        self.tier = tier
        self._translators: dict[str, object] = {}
        self._lock = threading.Lock()

    def _tiers_for(self, pair: str) -> list[str]:
        # для ядерных пар можно "fast"; для остальных (zh, ko…) —
        # только best (NLLB)
        if pair in self._FAST_PAIRS:
            return [self.tier, "fast", "best"]
        return [self.tier, "best"]

    def _translator(self, source: str, target: str):
        pair = f"{source}-{target}"
        with self._lock:
            tr = self._translators.get(pair)
            if tr is not None:
                return tr
            last_err = None
            for tier in self._tiers_for(pair):
                try:
                    tr = self._Translator(pair=pair, tier=tier)
                    self._translators[pair] = tr
                    return tr
                except (ValueError, RuntimeError) as e:
                    last_err = e
            raise EngineError from last_err

    def ping(self) -> bool:
        # Движок готов всегда: модели качаются автоматически при первом
        # переводе. Проверка скачанных моделей здесь НЕ нужна — иначе
        # реалтайм молча подменяется identity-функцией и перевод
        # «не работает» без всякой ошибки.
        return self._Translator is not None

    def translate(self, texts: list[str], source: str, target: str,
                  context_before: list[str] | None = None,
                  context_after: list[str] | None = None) -> list[str]:
        if self._Translator is None:
            raise EngineError("honyaku module not available")
        if source == target:
            return list(texts)
        pair = f"{source}-{target}"
        # Модели качаются ТОЛЬКО фоновой задачей приложения (prefetch):
        # синхронная докачка здесь блокирует живой перевод — серверный
        # поток Ren'Py / CDP-поток Tyrano замирает на минуты (HF без
        # таймаута), игра в это время «висит» по 30с на строку диалога.
        # Если модели нет — мгновенный отказ; перевод заработает сам,
        # как только фоновая загрузка завершится.
        try:
            from app.translators.honyaku.download import is_downloaded
            if not any(is_downloaded(t, pair) for t in self._tiers_for(pair)):
                raise EngineError(
                    f"Offline models for {source}→{target} are not "
                    "downloaded yet (background download in progress — "
                    "translation resumes automatically).")
        except EngineError:
            raise
        except ImportError:
            pass
        try:
            tr = self._translator(source, target)
        except Exception as e:  # noqa: BLE001
            raise EngineError(
                f"No offline models for {source}→{target} "
                "(models download automatically on first use).") from e
        return list(tr.translate_batch(texts))


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

    NLLB-200 теперь работает через honyaku (tier=best). Старые настройки,
    где провайдером выбран 'nllb', переводят на HonyakuEngine.
    """

    name = "nllb"

    def __init__(self, *args, **kwargs):
        self.use_gpu = False

    def ping(self) -> bool:
        return False

    def translate(self, texts, source, target, *args, **kwargs):
        raise EngineError(
            "NLLB-200 перенесён в honyaku (tier=best) — выберите провайдера "
            "Honyaku в настройках.")


# реестр провайдеров для настроек
PROVIDERS = {
    "honyaku": "Honyaku — встроенный офлайн (без ключа)",
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
        "honyaku": HonyakuEngine,
        "argos": HonyakuEngine,      # старые настройки -> honyaku
        "google_free": GoogleFreeEngine,
        "bing": BingEngine,
        "rotate": RotateEngine,
    }
    if name not in engines:
        if name == "nllb":
            # старые настройки с удалённым NLLB — молча переводим на honyaku
            return HonyakuEngine()
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
    "honyaku": (
        "Offline engine is not ready.\n\n"
        "Models download automatically on first translation "
        "(~60 MB per fast pair, ~1.2 GB for NLLB best, one-time download)."
    ),
}


def engine_hint(name: str) -> str:
    return ENGINE_HINTS.get(name, "Check that the engine is running.")


# ---------- скачивание моделей honyaku ----------

HONYAKU_ALL_PAIRS = [
    ("ja", "ru"), ("ja", "en"), ("zh", "ru"), ("zh", "en"), ("en", "ru"),
]

_FAST_PAIRS = ("ja-ru", "ja-en", "en-ru", "zh-en")


def honyaku_missing_pairs_all() -> list[tuple[str, str]]:
    try:
        from app.translators.honyaku.download import is_downloaded
    except ImportError:
        raise EngineError("honyaku not installed")
    missing = []
    for src, tgt in HONYAKU_ALL_PAIRS:
        pair = f"{src}-{tgt}"
        tiers = ("fast", "best") if pair in _FAST_PAIRS else ("best",)
        if not any(is_downloaded(t, pair) for t in tiers):
            missing.append((src, tgt))
    return missing


def honyaku_download(pairs: list[tuple[str, str]],
                     progress=None, cancel=None) -> list[str]:
    from app.translators.honyaku.download import ensure_model
    done = []
    for i, (src, dst) in enumerate(pairs):
        if cancel is not None and cancel.is_set():
            break
        pair = f"{src}-{dst}"
        tier = "fast" if pair in _FAST_PAIRS else "best"
        if progress:
            progress(i + 1, len(pairs), f"{src}→{dst} ({tier})")
        ensure_model(tier, pair)
        done.append(f"{src}→{dst}")
    return done


def honyaku_warm(pairs: list[tuple[str, str]]):
    """Прогревает движки honyaku: загружает модели в память в фоне.

    Первый перевод живой сессии иначе платит полную стоимость загрузки
    модели (fast ~1-3с, NLLB best ~10-30с) прямо в серверном/CDP-потоке —
    игра бы замерла на первые строки. Best-effort: при ошибке модель
    дозагрузится при первом переводе (тентент с таймаут-страховкой).
    """
    from app.translators.honyaku import Translator
    for src, dst in pairs:
        pair = f"{src}-{dst}"
        tier = "fast" if pair in _FAST_PAIRS else "best"
        try:
            Translator(pair=pair, tier=tier)._ensure_engine()
        except Exception:  # noqa: BLE001
            continue


def honyaku_models_status() -> tuple[int, int, int]:
    """Статус офлайн-моделей: (скачано пар, всего пар, размер МБ).

    Размер считается по каталогу модели honyaku (model_root()).
    """
    from app.translators.honyaku.download import model_root, is_downloaded
    total = len(HONYAKU_ALL_PAIRS)
    done = 0
    for src, tgt in HONYAKU_ALL_PAIRS:
        pair = f"{src}-{tgt}"
        tiers = ("fast", "best") if pair in _FAST_PAIRS else ("best",)
        if any(is_downloaded(t, pair) for t in tiers):
            done += 1
    size_mb = 0
    root = model_root()
    try:
        for dirpath, _dirnames, filenames in os.walk(str(root)):
            for name in filenames:
                try:
                    size_mb += os.path.getsize(
                        os.path.join(dirpath, name)) // (1024 * 1024)
                except OSError:
                    pass
    except OSError:
        pass
    return done, total, size_mb

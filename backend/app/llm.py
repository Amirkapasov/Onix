"""Абстракция LLM: gemini (по умолчанию) | anthropic | openai. Ответ — JSON-объект.

Таймаут и 1 ретрай; любая ошибка → LLMError, пайплайн уходит в режим деградации.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass

from . import config

log = logging.getLogger("seruen.llm")


class LLMError(Exception):
    pass


@dataclass
class LLMResult:
    data: dict
    provider: str
    model: str
    latency_ms: int


def extract_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    a = text.find("{")
    if a < 0:
        raise LLMError("no JSON in LLM output")
    try:  # первый JSON-объект; хвост после него (бывает у lite-моделей) игнорируем
        val, _ = json.JSONDecoder().raw_decode(text[a:])
    except json.JSONDecodeError as e:
        raise LLMError(f"bad JSON: {e}") from e
    if not isinstance(val, dict):
        raise LLMError("JSON is not an object")
    return val


class Provider:
    name = "none"
    model = ""

    def models_for(self, purpose: str) -> list[str]:
        return [self.model]

    def complete(self, system: str, user: str, temperature: float, max_tokens: int, timeout: float,
                 model: str | None = None) -> str:
        raise NotImplementedError


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self) -> None:
        from google import genai
        self.model = config.GEMINI_MODEL
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)

    def models_for(self, purpose: str) -> list[str]:
        # у бесплатного тарифа квота на каждую модель своя (5 RPM) → разбор на lite-модели, при 429 — запасные
        if purpose == "parse":
            return [config.GEMINI_PARSE_MODEL]
        return list(dict.fromkeys([self.model] + config.GEMINI_FALLBACK_MODELS))

    def complete(self, system, user, temperature, max_tokens, timeout, model=None):
        from google.genai import types
        model = model or self.model
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            # Gemini API не принимает дедлайн < 10 с; наш бюджет времени держит пайплайн (asyncio.wait_for)
            http_options=types.HttpOptions(timeout=int(max(10.0, timeout) * 1000)),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        # «мышление» съедает время — для коротких JSON минимизируем (поле зависит от поколения модели)
        m = model.lower()
        if "2.5-flash" in m:
            cfg.thinking_config = types.ThinkingConfig(thinking_budget=0)
        elif m.startswith("gemini-3"):
            cfg.thinking_config = types.ThinkingConfig(thinking_level="low")
        resp = self.client.models.generate_content(model=model, contents=user, config=cfg)
        return resp.text or ""


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self) -> None:
        import anthropic
        self.model = config.ANTHROPIC_MODEL
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=0)

    def complete(self, system, user, temperature, max_tokens, timeout, model=None):
        resp = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, temperature=temperature, timeout=timeout,
            system=system + "\nОтвечай только JSON-объектом, без пояснений и markdown.",
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self) -> None:
        import openai
        self.model = config.OPENAI_MODEL
        self.client = openai.OpenAI(api_key=config.OPENAI_API_KEY, max_retries=0)

    def complete(self, system, user, temperature, max_tokens, timeout, model=None):
        resp = self.client.chat.completions.create(
            model=self.model, temperature=temperature, max_tokens=max_tokens, timeout=timeout,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content or ""


_PROVIDERS = {"gemini": (GeminiProvider, "GEMINI_API_KEY"),
              "anthropic": (AnthropicProvider, "ANTHROPIC_API_KEY"),
              "openai": (OpenAIProvider, "OPENAI_API_KEY")}
_instance: Provider | None = None
_init_done = False


def get_provider() -> Provider | None:
    """Провайдер из LLM_PROVIDER, если для него есть ключ; иначе None (деградация)."""
    global _instance, _init_done
    if config.DISABLE_LLM:
        return None
    if not _init_done:
        _init_done = True
        entry = _PROVIDERS.get(config.LLM_PROVIDER)
        if entry and getattr(config, entry[1]):
            try:
                _instance = entry[0]()
            except Exception as e:
                log.warning("LLM provider %s init failed: %s", config.LLM_PROVIDER, type(e).__name__)
        else:
            log.warning("LLM provider %s: no API key — degraded mode", config.LLM_PROVIDER)
    return _instance


_cooldown: dict[str, float] = {}  # модель → monotonic-время, до которого её не трогаем (429)
_cache: OrderedDict[str, tuple[float, LLMResult]] = OrderedDict()
CACHE_TTL_S = 30 * 60


def _retry_delay(err: str) -> float:
    m = re.search(r"retryDelay'?:\s*'?(\d+)", err) or re.search(r"retry in (\d+(?:\.\d+)?)s", err)
    return min(120.0, float(m.group(1)) + 1) if m else 60.0


def _is_quota(err: str) -> bool:
    return "429" in err or "RESOURCE_EXHAUSTED" in err or "rate_limit" in err.lower()


def _is_overloaded(err: str) -> bool:
    return bool(re.search(r"\b50[34]\b|UNAVAILABLE|DEADLINE_EXCEEDED|overloaded|high demand", err))


def complete_json(system: str, user: str, *, temperature: float = 0.2, max_tokens: int = 1200,
                  timeout: float | None = None, purpose: str = "gen") -> LLMResult:
    """JSON от LLM. Кэш по (system, user) на 30 мин; при 429 модель «остывает», пробуем следующую."""
    prov = get_provider()
    if prov is None:
        raise LLMError("llm_unavailable")
    key = hashlib.sha1(f"{purpose}|{temperature}|{system}|{user}".encode()).hexdigest()
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        _cache.move_to_end(key)
        return LLMResult(hit[1].data, hit[1].provider, hit[1].model, 0)
    timeout = timeout or config.LLM_TIMEOUT_S
    t0 = time.monotonic()
    last = "no model available"
    calls = 0  # не больше 2 обращений к API на запрос: попытка + 1 ретрай (на той же или запасной модели)
    for model in prov.models_for(purpose):
        if _cooldown.get(model, 0) > time.monotonic():
            last = f"{model}: quota cooldown"
            continue
        for attempt in range(2):
            if calls >= 2:
                raise LLMError(last)
            calls += 1
            try:
                text = prov.complete(system, user, temperature, max_tokens, timeout, model=model)
                res = LLMResult(extract_json(text), prov.name, model, int((time.monotonic() - t0) * 1000))
                _cache[key] = (time.monotonic(), res)
                if len(_cache) > 300:
                    _cache.popitem(last=False)
                return res
            except Exception as e:
                last = f"{type(e).__name__}: {str(e)[:300]}"
                if _is_quota(last):
                    _cooldown[model] = time.monotonic() + _retry_delay(last)
                    log.warning("LLM %s/%s quota exhausted — cooldown %.0fs", prov.name, model, _retry_delay(last))
                    break
                if _is_overloaded(last):  # 503/504 «high demand» — повтор той же модели не поможет
                    _cooldown[model] = time.monotonic() + 30
                    log.warning("LLM %s/%s overloaded — next model", prov.name, model)
                    break
                log.warning("LLM %s/%s attempt %d failed: %s", prov.name, model, attempt + 1, last[:200])
                if time.monotonic() - t0 > timeout:
                    raise LLMError(last)
    raise LLMError(last)


def quota_limited() -> bool:
    """Все модели генерации сейчас «остывают» после 429."""
    prov = get_provider()
    return bool(prov) and all(_cooldown.get(m, 0) > time.monotonic() for m in prov.models_for("gen"))

"""Абстракция LLM: gemini (по умолчанию) | anthropic | openai. Ответ — JSON-объект.

Таймаут и 1 ретрай; любая ошибка → LLMError, пайплайн уходит в режим деградации.
"""
from __future__ import annotations

import json
import logging
import re
import time
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
    try:
        val = json.loads(text)
    except json.JSONDecodeError:
        a, b = text.find("{"), text.rfind("}")
        if a < 0 or b <= a:
            raise LLMError("no JSON in LLM output")
        try:
            val = json.loads(text[a:b + 1])
        except json.JSONDecodeError as e:
            raise LLMError(f"bad JSON: {e}") from e
    if not isinstance(val, dict):
        raise LLMError("JSON is not an object")
    return val


class Provider:
    name = "none"
    model = ""

    def complete(self, system: str, user: str, temperature: float, max_tokens: int, timeout: float) -> str:
        raise NotImplementedError


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self) -> None:
        from google import genai
        self._genai = genai
        self.model = config.GEMINI_MODEL
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)

    def complete(self, system, user, temperature, max_tokens, timeout):
        from google.genai import types
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),
        )
        # «мышление» съедает время — для коротких JSON минимизируем (поле зависит от поколения модели)
        m = self.model.lower()
        if "2.5-flash" in m:
            cfg.thinking_config = types.ThinkingConfig(thinking_budget=0)
        elif m.startswith("gemini-3"):
            cfg.thinking_config = types.ThinkingConfig(thinking_level="low")
        resp = self.client.models.generate_content(model=self.model, contents=user, config=cfg)
        return resp.text or ""


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self) -> None:
        import anthropic
        self.model = config.ANTHROPIC_MODEL
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=0)

    def complete(self, system, user, temperature, max_tokens, timeout):
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

    def complete(self, system, user, temperature, max_tokens, timeout):
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


def complete_json(system: str, user: str, *, temperature: float = 0.2, max_tokens: int = 1200,
                  timeout: float | None = None) -> LLMResult:
    prov = get_provider()
    if prov is None:
        raise LLMError("llm_unavailable")
    timeout = timeout or config.LLM_TIMEOUT_S
    t0 = time.monotonic()
    last: Exception | None = None
    for attempt in range(2):  # 1 ретрай
        try:
            text = prov.complete(system, user, temperature, max_tokens, timeout)
            data = extract_json(text)
            return LLMResult(data, prov.name, prov.model, int((time.monotonic() - t0) * 1000))
        except Exception as e:
            last = e
            log.warning("LLM %s attempt %d failed: %s: %s", prov.name, attempt + 1, type(e).__name__, str(e)[:200])
            if time.monotonic() - t0 > timeout:
                break
    raise LLMError(f"{type(last).__name__}: {str(last)[:200]}")

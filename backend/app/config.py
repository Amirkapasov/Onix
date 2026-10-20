"""Настройки сервиса: переменные окружения (.env) и веса ранжирования."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


# --- Данные ---
POIS_PATH = _env("POIS_PATH", "data/pois.json")
SEED_PATH = "data/seed/pois_seed.json"
CACHE_DIR = ROOT / "data" / "cache"

# --- LLM ---
LLM_PROVIDER = _env("LLM_PROVIDER", "gemini").lower()
GEMINI_API_KEY = _env("GEMINI_API_KEY")
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-3.5-flash-lite")
# Бесплатный тариф: ~5 запросов/мин на КАЖДУЮ модель → разбор на своей lite-модели, генерация с запасными
GEMINI_PARSE_MODEL = _env("GEMINI_PARSE_MODEL", "gemini-3.1-flash-lite")
GEMINI_FALLBACK_MODELS = [m.strip() for m in _env(
    "GEMINI_FALLBACK_MODELS", "gemini-3.5-flash-lite,gemini-2.5-flash-lite,gemini-3.5-flash,gemini-2.5-flash").split(",") if m.strip()]
GEMINI_EMBED_MODEL = _env("GEMINI_EMBED_MODEL", "gemini-embedding-2")
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _env("ANTHROPIC_MODEL", "claude-haiku-5-5")
OPENAI_API_KEY = _env("OPENAI_API_KEY")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-4.1-mini")
LLM_TIMEOUT_S = float(_env("LLM_TIMEOUT_S", "6"))
LLM_PARSE_MODE = _env("LLM_PARSE_MODE", "auto").lower()  # auto (только если правила слабые) | always | off
LLM_PARSE_TIMEOUT_S = float(_env("LLM_PARSE_TIMEOUT_S", "2.5"))
# Выключить LLM целиком (для тестов и режима деградации): SERUEN_DISABLE_LLM=1
DISABLE_LLM = _env("SERUEN_DISABLE_LLM") in ("1", "true", "yes")
DISABLE_NETWORK = _env("SERUEN_DISABLE_NETWORK") in ("1", "true", "yes")

# --- Маршруты и погода ---
OSRM_FOOT_URL = _env("OSRM_FOOT_URL", "https://routing.openstreetmap.de/routed-foot").rstrip("/")
OSRM_TIMEOUT_S = 3.0
WEATHER_TTL_S = 15 * 60
CITY_CENTER = (51.128, 71.430)  # погоду запрашиваем по центру города, не по координатам пользователя
TZ_OFFSET_H = 5  # Астана, UTC+5
AIRPORT = (51.0222, 71.4669)

# --- Скорости ---
WALK_KMH = 4.5
WALK_DETOUR = 1.3
CAR_KMH = 30.0  # с учётом выезда на магистрали (аэропорт → центр ≈ 30 мин)
CAR_DETOUR = 1.2
CAR_OVERHEAD_MIN = 5  # вызов такси / парковка
TRANSIT_KMH = 15.0
TRANSIT_DETOUR = 1.3
TRANSIT_OVERHEAD_MIN = 8

# Доля бюджета на дорогу в одну сторону
ONE_WAY_SHARE = 0.33
ONE_WAY_SHARE_WALK_INTENT = 0.45  # если сама прогулка — цель
MIN_RADIUS_M = 800
MAX_RADIUS_M = 15000
DEFAULT_BUDGET_MIN = 90
NEED_MAX_RADIUS_M = 10000  # явная потребность («бассейн») рядом не нашлась → ищем до 10 км на такси
FLIGHT_BUFFER_MIN = 60  # быть в аэропорту за час до вылета

# --- Ранжирование (прозрачная формула: score = Σ w_i · f_i) ---
WEIGHTS = {
    "relevance": 0.40,     # гибрид BM25 + эмбеддинги, 0..1
    "constraints": 0.20,   # доля выполненных мягких ограничений (тихо, кофе, розетки…)
    "proximity": 0.15,     # 1 − d / radius
    "quality": 0.10,       # рейтинг/популярность
    "data_quality": 0.05,
    "hours": 0.10,         # уверенность в часах работы
    "weather": 0.10,       # ±1 в зависимости от погоды и indoor/outdoor
    "daytime": 0.10,       # ночь/вечер
}
# Явная потребность («бассейн», «аптека»): соответствие уже обеспечено фильтром → близость, потом рейтинг
WEIGHTS_NEED = {
    "relevance": 0.10, "constraints": 0.12, "proximity": 0.40, "quality": 0.18, "data_quality": 0.04,
    "hours": 0.12, "weather": 0.02, "daytime": 0.02,
}
DIVERSITY_PENALTY = 0.12  # штраф за повтор категории в выдаче
LLM_CANDIDATES = 9

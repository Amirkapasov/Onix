"""Погода: Open-Meteo (без ключа, кэш 15 мин) по центру города; для «сдвинутого» времени демо —
климатическая норма месяца; температура из запроса («на улице −20») важнее всего."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from . import config

log = logging.getLogger("seruen.weather")

# Средняя температура по месяцам, Астана (°C), ветер ~4–5 м/с
CLIMATE = [-14.2, -13.5, -6.5, 5.6, 13.7, 19.4, 20.9, 18.6, 12.0, 3.9, -5.4, -11.5]


@dataclass
class Weather:
    temp_c: float | None
    wind_ms: float | None
    precip_mm: float | None
    source: str  # open-meteo | climate | query | none

    @property
    def cold(self) -> bool:
        return (self.temp_c is not None and self.temp_c < -10) or (self.wind_ms is not None and self.wind_ms > 10)

    @property
    def bad(self) -> bool:
        return self.cold or (self.precip_mm or 0) > 0.5 or (self.temp_c is not None and self.temp_c > 32)

    @property
    def pleasant(self) -> bool:
        return self.temp_c is not None and 12 <= self.temp_c <= 30 and not self.bad

    def label(self, lang: str = "ru") -> str:
        if self.temp_c is None:
            return {"ru": "нет данных о погоде", "en": "no weather data", "kk": "ауа райы белгісіз"}.get(lang, "")
        t = f"{self.temp_c:+.0f}°C".replace("-", "−")
        parts = [t]
        if self.wind_ms is not None:
            parts.append({"ru": f"ветер {self.wind_ms:.0f} м/с", "en": f"wind {self.wind_ms:.0f} m/s",
                          "kk": f"жел {self.wind_ms:.0f} м/с"}.get(lang, ""))
        if (self.precip_mm or 0) > 0.5:
            parts.append({"ru": "осадки", "en": "precipitation", "kk": "жауын-шашын"}.get(lang, ""))
        suffix = {
            "climate": {"ru": " (климатическая норма для выбранного времени)", "en": " (climate normal)", "kk": " (климаттық норма)"},
            "query": {"ru": " (из запроса)", "en": " (from your query)", "kk": " (сұраудан)"},
        }.get(self.source, {}).get(lang, "")
        return ", ".join(parts) + suffix


_cache: tuple[float, Weather] | None = None


async def get_weather(client_dt: datetime, temperature_hint: float | None = None) -> Weather:
    if temperature_hint is not None:
        return Weather(temperature_hint, None, None, "query")
    now = datetime.now(timezone.utc)
    if abs(client_dt - now) > timedelta(hours=3):  # демо со сдвинутым временем — реальная погода не подходит
        return Weather(CLIMATE[client_dt.month - 1], 4.5, None, "climate")
    return await _current()


async def _current() -> Weather:
    global _cache
    if _cache and time.monotonic() - _cache[0] < config.WEATHER_TTL_S:
        return _cache[1]
    if config.DISABLE_NETWORK:
        return Weather(None, None, None, "none")
    lat, lon = config.CITY_CENTER
    try:
        async with httpx.AsyncClient(timeout=2.5) as c:
            r = await c.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": lat, "longitude": lon, "wind_speed_unit": "ms",
                "current": "temperature_2m,wind_speed_10m,precipitation"})
            r.raise_for_status()
            cur = r.json()["current"]
        w = Weather(cur.get("temperature_2m"), cur.get("wind_speed_10m"), cur.get("precipitation"), "open-meteo")
        _cache = (time.monotonic(), w)
        return w
    except Exception as e:
        log.warning("open-meteo failed: %s", type(e).__name__)
        m = datetime.now(timezone(timedelta(hours=config.TZ_OFFSET_H))).month
        return Weather(CLIMATE[m - 1], None, None, "climate")

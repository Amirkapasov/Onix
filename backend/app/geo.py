"""Расстояния, время в пути и радиус поиска из бюджета времени."""
from __future__ import annotations

import math

from . import config


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _speed(mode: str) -> tuple[float, float, float]:
    """(м/мин, коэффициент извилистости, накладные минуты)."""
    if mode == "car":
        return config.CAR_KMH * 1000 / 60, config.CAR_DETOUR, config.CAR_OVERHEAD_MIN
    if mode == "transit":
        return config.TRANSIT_KMH * 1000 / 60, config.TRANSIT_DETOUR, config.TRANSIT_OVERHEAD_MIN
    return config.WALK_KMH * 1000 / 60, config.WALK_DETOUR, 0


def travel_min(distance_m: float, mode: str = "walk") -> int:
    """Время в пути по прямому расстоянию с поправкой на извилистость улиц."""
    speed, detour, overhead = _speed(mode)
    if distance_m < 30:
        return 0
    return max(1, round(distance_m * detour / speed + overhead))


def path_min(path_distance_m: float, mode: str = "walk") -> int:
    """Время по уже известной длине пути (OSRM) — без коэффициента извилистости."""
    speed, _, overhead = _speed(mode)
    return max(1, round(path_distance_m / speed + overhead)) if path_distance_m >= 30 else 0


def radius_for_budget(budget_min: int, mode: str = "walk", walk_intent: bool = False) -> int:
    """Радиус (по прямой), чтобы дорога в одну сторону заняла ≤ ~1/3 бюджета."""
    share = config.ONE_WAY_SHARE_WALK_INTENT if walk_intent else config.ONE_WAY_SHARE
    one_way = max(5.0, budget_min * share)
    speed, detour, overhead = _speed(mode)
    r = max(0.0, one_way - overhead) * speed / detour
    return int(min(config.MAX_RADIUS_M, max(config.MIN_RADIUS_M, r)))


def round_coord(x: float, digits: int = 2) -> float:
    return round(float(x), digits)

"""Жёсткие фильтры (код) и прозрачное ранжирование кандидатов."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import config, geo
from .hours import PoiOpen, poi_open_status
from .weather import Weather

DEFAULT_VISIT = {
    "museum": 60, "gallery": 45, "park": 45, "mall": 60, "cafe": 40, "landmark": 20, "monument": 15,
    "viewpoint": 30, "religious": 25, "playground": 40, "kids": 60, "entertainment": 60, "theatre": 120,
    "cinema": 120, "library": 60, "coworking": 90, "restaurant": 60, "bar": 60, "nightlife": 90,
    "market": 40, "sport": 60, "other": 30,
}
INTENT_CATEGORIES = {
    "walk": {"park", "landmark", "monument", "viewpoint"},
    "coffee": {"cafe"}, "work": {"cafe", "coworking", "library"},
    "kids": {"playground", "kids", "museum", "park", "entertainment"},
    "sightseeing": {"landmark", "monument", "viewpoint", "museum", "religious"},
    "night": {"bar", "nightlife", "viewpoint", "landmark", "entertainment", "cinema"},
    "food": {"restaurant", "cafe"}, "culture": {"museum", "gallery", "theatre", "library"},
    "shopping": {"mall", "market"},
}
HERE_PENALTY_INTENTS = {"walk", "sightseeing", "other", "culture", "night"}
FACETS = {"food", "coffee", "kids", "view", "night", "sockets", "quiet"}
KID_TAGS = {"kids", "playground", "family", "interactive"}
ADULT_CATEGORIES = {"bar", "nightlife"}


def visit_range(p: dict) -> tuple[int, int]:
    t = p.get("typical_visit_min") or DEFAULT_VISIT.get(p.get("category", ""), 30)
    lo = max(10, int(round(t * 0.7 / 5) * 5))
    hi = max(lo + 5, int(round(t * 1.2 / 5) * 5))
    return lo, hi


@dataclass
class Ctx:
    start: tuple[float, float]
    when: datetime
    mode: str
    lang: str
    budget: int
    budget_explicit: bool
    radius: int
    parsed: dict
    with_kids: bool
    accessibility: bool
    indoor_only: bool
    categories: list[str]
    flight: bool
    available: int  # минут на прогулку (с учётом запаса до вылета)
    weather: Weather | None = None
    notes: list[str] = field(default_factory=list)  # что учли — для context_used.filters
    warnings: list[str] = field(default_factory=list)


@dataclass
class Cand:
    poi: dict
    dist_m: int
    travel_min: int
    visit: tuple[int, int]
    open: PoiOpen
    back_min: int = 0  # дорога до аэропорта (сценарий вылета)
    here: bool = False  # пользователь уже стоит в этом месте
    relevance: float = 0.0
    score: float = 0.0
    parts: dict = field(default_factory=dict)


def make_cand(p: dict, ctx: Ctx) -> Cand:
    d = geo.haversine_m(ctx.start[0], ctx.start[1], p["lat"], p["lon"])
    tmin = geo.travel_min(d, ctx.mode)
    visit = visit_range(p)
    back = geo.travel_min(geo.haversine_m(p["lat"], p["lon"], *config.AIRPORT), ctx.mode) if ctx.flight else 0
    if ctx.budget_explicit or ctx.flight:  # визит не длиннее того, что реально остаётся
        room = ctx.available - tmin - back
        if room >= min_visit(visit, ctx.available):
            hi = min(visit[1], room)
            visit = (min(visit[0], max(min_visit(visit, ctx.available), hi - 15)), hi)
    arrival = ctx.when + timedelta(minutes=tmin)
    st = poi_open_status(p, arrival, visit[0], ctx.lang)
    return Cand(p, int(round(d)), tmin, visit, st, back_min=back)


def min_visit(visit: tuple[int, int], available: int | None = None) -> int:
    """Минимально осмысленный визит: половина обычного, но не меньше 10 мин
    (при очень маленьком бюджете — до половины бюджета: «кофе за 15 минут»)."""
    m = max(10, visit[0] // 2)
    return min(m, max(5, available // 2)) if available else m


def _is_kid_ok(p: dict) -> bool:
    if p.get("category") in ADULT_CATEGORIES or p.get("kid_friendly") is False:
        return False
    return bool(p.get("kid_friendly")) or bool(KID_TAGS & set(p.get("tags") or [])) or p.get("category") in ("playground", "kids")


def _not_destination(p: dict) -> bool:
    name = p.get("name", "").lower()
    return "transport" in (p.get("tags") or []) or bool(re.match(r"(международный )?аэропорт\b|airport\b|(ж/д )?вокзал\b", name))


def hard_filter(pois: list[dict], ctx: Ctx) -> tuple[list[Cand], dict]:
    """Возвращает кандидатов и счётчики отсеянного. Ослабляет условия по шагам, если пусто."""
    base = [p for p in pois if not _not_destination(p)]
    stats = {"closed": 0, "far": 0, "kids": 0, "access": 0, "indoor": 0, "category": 0, "guess_closed": 0, "budget": 0}
    if ctx.categories:
        n = len(base)
        base = [p for p in base if p.get("category") in ctx.categories]
        stats["category"] = n - len(base)
    if ctx.with_kids:
        n = len(base)
        base = [p for p in base if _is_kid_ok(p)]
        stats["kids"] = n - len(base)
    elif ctx.parsed["intent"] != "kids" and "playground" not in ctx.categories:
        base = [p for p in base if p.get("category") != "playground"]  # площадки — только для запросов с детьми
    if ctx.accessibility:
        n = len(base)
        base = [p for p in base if p.get("wheelchair") in ("yes", "limited")]
        stats["access"] = n - len(base)
    if ctx.indoor_only:
        n = len(base)
        base = [p for p in base if p.get("indoor") is True]
        stats["indoor"] = n - len(base)

    def run(radius: int, allow_guess: bool) -> list[Cand]:
        out = []
        for k in stats:
            if k in ("closed", "far", "guess_closed", "budget"):
                stats[k] = 0
        for p in base:
            if geo.haversine_m(ctx.start[0], ctx.start[1], p["lat"], p["lon"]) > radius:
                stats["far"] += 1
                continue
            c = make_cand(p, ctx)
            if c.open.state == "closed" or not c.open.fits_visit:
                stats["closed"] += 1
                continue
            if c.open.guessed_closed and not allow_guess:
                stats["guess_closed"] += 1
                continue
            need = c.travel_min + min_visit(c.visit, ctx.available) + c.back_min
            if (ctx.flight or ctx.budget_explicit) and need > ctx.available:
                stats["budget"] += 1
                continue
            out.append(c)
        return out

    cands = run(ctx.radius, False)
    radius = ctx.radius
    # расширяем, только если мест меньше двух, и не дальше 2× (в мороз 1.3×) исходного радиуса
    max_r = min(config.MAX_RADIUS_M, int(ctx.radius * (1.3 if ctx.weather and ctx.weather.cold else 2.0)))
    while len(cands) < 2 and not ctx.flight and radius < max_r:
        radius = min(max_r, int(radius * 1.4))
        cands = run(radius, False)
    if radius != ctx.radius and cands:
        ctx.warnings.append(_t(ctx.lang, "radius", r=_km(radius)))
        ctx.radius = radius
    if not cands:
        cands = run(radius, True)
    return cands, stats


def _km(m: int) -> str:
    return f"{m / 1000:.1f} км" if m >= 1000 else f"{m} м"


_TXT = {
    "radius": {"ru": "Рядом мало подходящих мест — радиус поиска расширен до {r}.",
               "en": "Few suitable places nearby — search radius widened to {r}.",
               "kk": "Жақын маңда орын аз — іздеу радиусы {r} дейін кеңейтілді."},
}


def _t(lang: str, key: str, **kw) -> str:
    return _TXT[key].get(lang, _TXT[key]["ru"]).format(**kw)


# ---------------- ранжирование ----------------

def _soft(c: str, p: dict, cand: Cand) -> bool | None:
    tags = set(p.get("tags") or [])
    cat = p.get("category")
    if c == "quiet":
        return ("quiet" in tags or cat in ("library", "park", "religious", "museum", "gallery", "coworking")) and cat not in ("mall", "bar", "nightlife")
    if c == "sockets":
        return "sockets" in tags or cat == "coworking"
    if c == "wifi":
        return "wifi" in tags or cat == "coworking"
    if c == "coffee":
        return cat == "cafe" or "coffee" in tags
    if c == "indoor":
        return p.get("indoor") is True
    if c == "outdoor_ok":
        return p.get("indoor") is False or cat in ("park", "landmark", "monument", "viewpoint")
    if c == "night":
        return "night" in tags or cat in ("nightlife", "bar") or cand.open.open_late
    if c == "unusual":
        return bool({"unusual", "art", "interactive"} & tags) or cat in ("gallery", "viewpoint", "entertainment", "museum", "theatre")
    if c == "free":
        return p.get("price_level") == 0 or "free" in tags
    if c == "view":
        return bool({"view", "photo", "terrace"} & tags) or cat in ("viewpoint", "landmark")
    if c == "interactive":
        return "interactive" in tags
    if c == "food":
        return cat in ("restaurant", "cafe")
    return None


def rank(cands: list[Cand], ctx: Ctx) -> list[Cand]:
    w = config.WEIGHTS
    parsed = ctx.parsed
    soft = [c for c in parsed["constraints"] if c not in ("flight_soon", "accessibility")]
    if ctx.with_kids:
        soft.append("kids")
    intent_cats = INTENT_CATEGORIES.get(parsed["intent"], set())
    hour = ctx.when.hour
    night = hour >= 22 or hour < 6
    evening = 18 <= hour < 22
    for c in cands:
        p = c.poi
        checks = []
        for s in soft:
            v = _is_kid_ok(p) if s == "kids" else _soft(s, p, c)
            if v is not None:
                checks.append(1.0 if v else 0.0)
        if intent_cats:
            checks.append(1.0 if p.get("category") in intent_cats else 0.0)
        f_cons = sum(checks) / len(checks) if checks else 0.5
        f_prox = max(0.0, 1 - c.dist_m / max(ctx.radius, 1))
        rating = p.get("rating")
        f_q = 0.6 * ((rating / 5) if isinstance(rating, (int, float)) else 0.6) + 0.4 * (p.get("popularity") or 0.3)
        f_dq = p.get("data_quality") if isinstance(p.get("data_quality"), (int, float)) else 0.5
        f_hours = {("open", "high"): 1.0, ("open", "medium"): 0.85, ("open", "low"): 0.6}.get(
            (c.open.state, c.open.confidence), 0.7 if c.open.outdoor_area else 0.4)
        f_w = 0.0
        wx = ctx.weather
        if wx and wx.bad:
            f_w = 1.0 if p.get("indoor") is True else (-1.0 if p.get("indoor") is False else 0.0)
        elif wx and wx.pleasant:
            f_w = 0.5 if p.get("indoor") is False else 0.0
        f_day = 0.0
        tags = set(p.get("tags") or [])
        if night:
            f_day = 1.0 if (_soft("night", p, c) or "view" in tags and p.get("indoor") is False) else (-0.5 if p.get("category") == "park" else 0.0)
        elif evening:
            f_day = 0.5 if ("night" in tags or "view" in tags) else 0.0
        parts = {"relevance": c.relevance, "constraints": f_cons, "proximity": f_prox, "quality": f_q,
                 "data_quality": f_dq, "hours": f_hours, "weather": f_w, "daytime": f_day}
        c.parts = {k: round(v, 3) for k, v in parts.items()}
        c.score = sum(w[k] * v for k, v in parts.items())
    # дубли по названию (сети, две точки одного кафе) — оставляем лучшую
    pool, names = [], set()
    for c in sorted(cands, key=lambda x: -x.score):
        key = re.sub(r"[^a-zа-яё0-9әғқңөұүһі]", "", c.poi.get("name", "").lower().split(",")[0])
        if key and key in names:
            continue
        names.add(key)
        pool.append(c)
    # разнообразие: жадно, со штрафом за повтор категории
    out: list[Cand] = []
    seen: dict[str, int] = {}
    here_later: list[Cand] = []
    while pool and len(out) < config.LLM_CANDIDATES:
        best_i, best_s = 0, -1e9
        for i, c in enumerate(pool):
            cat = c.poi.get("category", "")
            pen = config.DIVERSITY_PENALTY * seen.get(cat, 0) * (0.5 if cat in intent_cats else 1.0)
            if c.score - pen > best_s:
                best_i, best_s = i, c.score - pen
        c = pool.pop(best_i)
        if c.here and pool:
            here_later.append(c)  # «вы уже здесь» — только запасной вариант
            continue
        seen[c.poi.get("category", "")] = seen.get(c.poi.get("category", ""), 0) + 1
        out.append(c)
    out += here_later
    # «прогуляться и поужинать»: каждое предметное пожелание должно быть хотя бы в top-3
    for facet in [s for s in soft if s in FACETS]:
        check = (lambda x: _is_kid_ok(x.poi)) if facet == "kids" else (lambda x, f=facet: bool(_soft(f, x.poi, x)))
        if len(out) > 3 and not any(check(x) for x in out[:3]):
            best = next((x for x in out[3:] if check(x)), None)
            if best:
                out.remove(best)
                out.insert(min(2, len(out)), best)
    return out

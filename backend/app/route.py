"""Мини-маршрут: жадный порядок (ближайший сосед), геометрия OSRM, иначе прямые линии."""
from __future__ import annotations

import logging

import httpx

from . import config, geo

log = logging.getLogger("seruen.route")


def order_stops(start: tuple[float, float], recs: list[dict]) -> list[dict]:
    left = list(recs)
    out, cur = [], start
    while left:
        nxt = min(left, key=lambda r: geo.haversine_m(cur[0], cur[1], r["lat"], r["lon"]))
        out.append(nxt)
        left.remove(nxt)
        cur = (nxt["lat"], nxt["lon"])
    return out


async def _osrm(points: list[tuple[float, float]], mode: str) -> tuple[list[list[float]], list[float]] | None:
    if config.DISABLE_NETWORK or len(points) < 2:
        return None
    base, profile = config.OSRM_FOOT_URL, "foot"
    if mode == "car":
        base, profile = base.replace("routed-foot", "routed-car"), "driving"
    coords = ";".join(f"{lon:.5f},{lat:.5f}" for lat, lon in points)
    try:
        async with httpx.AsyncClient(timeout=config.OSRM_TIMEOUT_S) as c:
            r = await c.get(f"{base}/route/v1/{profile}/{coords}", params={"overview": "full", "geometries": "geojson"})
            r.raise_for_status()
            data = r.json()
        route = data["routes"][0]
        geom = [[round(lat, 5), round(lon, 5)] for lon, lat in route["geometry"]["coordinates"]]
        return geom, [leg["distance"] for leg in route["legs"]]
    except Exception as e:
        log.warning("OSRM unavailable: %s", type(e).__name__)
        return None


async def build_route(start: tuple[float, float], recs: list[dict], mode: str, budget: int | None,
                      lang: str) -> tuple[dict | None, list[dict], list[str]]:
    """→ (route, recs в порядке маршрута (возможно урезанные), warnings)."""
    warnings: list[str] = []
    if not recs:
        return None, recs, warnings
    stops = order_stops(start, recs)

    def legs_for(seq):
        legs, cur, cur_id = [], start, "start"
        for r in seq:
            d = geo.haversine_m(cur[0], cur[1], r["lat"], r["lon"])
            legs.append({"from": cur_id, "to": r["poi_id"], "distance_m": int(round(d)), "minutes": geo.travel_min(d, mode)})
            cur, cur_id = (r["lat"], r["lon"]), r["poi_id"]
        return legs

    def total(seq, legs):
        return sum(l["minutes"] for l in legs) + sum(r["visit_min"][0] for r in seq)

    legs = legs_for(stops)
    if budget:
        dropped = []
        while len(stops) > 1 and total(stops, legs) > budget:
            dropped.append(stops.pop()["name"])
            legs = legs_for(stops)
        if dropped:
            names = ", ".join(dropped[::-1])
            warnings.append({"ru": f"В маршрут на {budget} мин не влезает: {names} — это запасные варианты.",
                             "en": f"Not in the {budget}-min route: {names} — keep them as alternatives.",
                             "kk": f"{budget} мин маршрутқа сыймайды: {names} — қосымша нұсқа."}.get(lang, ""))
    points = [start] + [(r["lat"], r["lon"]) for r in stops]
    osrm = await _osrm(points, mode)
    if osrm:
        geom, dists = osrm
        for leg, d in zip(legs, dists):
            leg["distance_m"] = int(round(d))
            leg["minutes"] = geo.path_min(d, mode)
        src = "osrm"
    else:
        geom = [[round(lat, 5), round(lon, 5)] for lat, lon in points]
        src = "straight_line"
    route = {"stops": [r["poi_id"] for r in stops], "legs": legs, "total_min": total(stops, legs),
             "geometry": geom, "geometry_source": src}
    if budget and route["total_min"] > budget:
        warnings.append({"ru": f"Маршрут (~{route['total_min']} мин) немного длиннее бюджета {budget} мин.",
                         "en": f"The route (~{route['total_min']} min) is a bit over the {budget}-min budget.",
                         "kk": f"Маршрут (~{route['total_min']} мин) {budget} мин-тан ұзағырақ."}.get(lang, ""))
    return route, stops, warnings

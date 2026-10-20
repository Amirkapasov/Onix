"""OSM: Overpass API (основной путь) или выгрузка Geofabrik (резерв, нужен pyosmium).

Какие объекты брать, описано один раз в SELECTORS; из них строятся и запросы Overpass,
и фильтр для локального разбора .osm.pbf. Сырые ответы кэшируются в data/raw/.
Данные OSM — ODbL 1.0, © участники OpenStreetMap.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from common import RAW, cached_json, file_mtime_iso, http, in_bbox, log

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
GEOFABRIK_URL = "https://download.geofabrik.de/asia/kazakhstan-latest.osm.pbf"
GEOFABRIK_FILE = RAW / "geofabrik" / "kazakhstan-latest.osm.pbf"

# bbox Астаны: minLat, minLon, maxLat, maxLon (area для Астаны построена не на всех зеркалах Overpass)
BBOX = (50.98, 71.25, 51.25, 71.65)

# (группа, ключ, регулярка значения | None = любое, требуется ли name)
SELECTORS = [
    ("food", "amenity", "cafe|restaurant|fast_food|bar|pub|nightclub|ice_cream|internet_cafe", True),
    ("culture", "amenity", "theatre|cinema|library|arts_centre|place_of_worship|coworking_space|planetarium|"
                           "marketplace|fountain|events_venue|music_venue|community_centre|karaoke_box", True),
    ("culture", "tourism", "museum|gallery|attraction|viewpoint|artwork|theme_park|zoo|aquarium", True),
    ("culture", "office", "coworking", True),
    ("leisure", "leisure", "park|garden|playground|water_park|amusement_arcade|escape_game|bowling_alley|ice_rink|"
                           "stadium|trampoline_park|nature_reserve|miniature_golf|dance", True),
    ("leisure", "landuse", "recreation_ground", True),
    ("leisure", "place", "square", True),
    ("wellness", "leisure", "swimming_pool|sports_centre|fitness_centre|sauna|spa", True),
    ("wellness", "amenity", "spa|sauna|public_bath", True),
    ("shops", "shop", "mall|department_store|supermarket|convenience|clothes|shoes|stationery|books|electronics|"
                      "mobile_phone|hardware|gift|toys|cosmetics|bakery|confectionery|chemist", True),
    ("shops", "amenity", "pharmacy", True),
    ("sights", "historic", None, True),
    ("sights", "building", "museum|theatre|cathedral|mosque|church|temple|synagogue", True),
    ("sights", "tower:type", "observation", False),
]
# Составные условия, которые не укладываются в SELECTORS (в wanted() они продублированы на Python)
EXTRA_OVERPASS = {
    "sights": ['nwr["wikidata"]["name"]["building"];', 'nwr["man_made"="tower"]["tourism"];'],
    "leisure": ['way["highway"="pedestrian"]["area"="yes"]["name"];', 'way["leisure"="playground"][!"name"];'],
}


def wanted(tags: dict) -> bool:
    """Тот же отбор, что и в Overpass-запросах, — для разбора .osm.pbf."""
    has_name = bool(tags.get("name") or tags.get("name:ru"))
    for _, k, rx, need_name in SELECTORS:
        v = tags.get(k)
        if v is None or (rx and not re.fullmatch(rx, v)):
            continue
        if need_name and not has_name:
            continue
        return True
    if tags.get("wikidata") and has_name and tags.get("building"):
        return True
    if tags.get("man_made") == "tower" and tags.get("tourism"):
        return True
    if tags.get("highway") == "pedestrian" and tags.get("area") == "yes" and has_name:
        return True
    return tags.get("leisure") == "playground"


# ---------- Overpass ----------

def _group_query(group: str) -> str:
    lines = []
    for g, k, rx, need_name in SELECTORS:
        if g != group:
            continue
        sel = f'["{k}"~"^({rx})$"]' if rx else f'["{k}"]'
        lines.append(f'nwr{sel}{chr(91) + chr(34) + "name" + chr(34) + chr(93) if need_name else ""};')
    lines += EXTRA_OVERPASS.get(group, [])
    bbox = ",".join(map(str, BBOX))
    return f"[out:json][timeout:120][bbox:{bbox}];\n(\n  " + "\n  ".join(lines) + "\n);\nout center tags;"


def _overpass_fetcher(query: str):
    def fetch() -> dict:
        last = None
        for url in ENDPOINTS:
            try:
                log(f"  Overpass: {url}")
                obj = json.loads(http(url, data={"data": query}, timeout=180, retries=2))
                if obj.get("elements") and "error" not in obj.get("remark", ""):
                    return obj
                last = RuntimeError(obj.get("remark", "пустой ответ"))
            except Exception as e:  # пробуем следующее зеркало
                last = e
                log(f"  ошибка {url}: {e}")
        raise RuntimeError(f"Overpass недоступен: {last}")
    return fetch


def _from_overpass(refresh: bool) -> tuple[list[dict], str]:
    groups = sorted({g for g, *_ in SELECTORS})
    elements, dates, seen = [], [], set()
    for g in groups:
        obj, path = cached_json(f"osm_{g}", _overpass_fetcher(_group_query(g)), refresh)
        dates.append(file_mtime_iso(path))
        for e in obj["elements"]:
            if (e["type"], e["id"]) in seen:
                continue
            seen.add((e["type"], e["id"]))
            lat = e.get("lat", e.get("center", {}).get("lat"))
            lon = e.get("lon", e.get("center", {}).get("lon"))
            if lat is not None:
                elements.append({"type": e["type"], "id": e["id"], "lat": lat, "lon": lon, "tags": e.get("tags", {})})
    return elements, min(dates)


# ---------- Geofabrik (.osm.pbf + pyosmium) ----------

def _download_geofabrik(refresh: bool) -> Path:
    if GEOFABRIK_FILE.exists() and not refresh:
        return GEOFABRIK_FILE
    import urllib.request
    from common import USER_AGENT
    GEOFABRIK_FILE.parent.mkdir(parents=True, exist_ok=True)
    log(f"  Geofabrik: скачиваю {GEOFABRIK_URL} (~225 МБ)")
    part = GEOFABRIK_FILE.with_suffix(".part")
    req = urllib.request.Request(GEOFABRIK_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    part.replace(GEOFABRIK_FILE)
    return GEOFABRIK_FILE


def _bbox_center(pts):
    lats, lons = [p[0] for p in pts], [p[1] for p in pts]
    return (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2


GEOFABRIK_CACHE = RAW / "osm_geofabrik.json"


def _from_geofabrik(refresh: bool) -> tuple[list[dict], str]:
    cache = GEOFABRIK_CACHE
    if cache.exists() and not refresh and (not GEOFABRIK_FILE.exists()
                                            or cache.stat().st_mtime >= GEOFABRIK_FILE.stat().st_mtime):
        log("  кэш: data/raw/osm_geofabrik.json")
        src = GEOFABRIK_FILE if GEOFABRIK_FILE.exists() else cache
        return json.loads(cache.read_text(encoding="utf-8")), file_mtime_iso(src)

    import osmium  # pip install osmium (pipeline/requirements.txt)
    pbf = _download_geofabrik(refresh)

    t0 = time.time()
    log("  Geofabrik: разбираю .osm.pbf (bbox Астаны)…")
    minlat, minlon, maxlat, maxlon = BBOX

    def inside(lat, lon):
        return minlat <= lat <= maxlat and minlon <= lon <= maxlon

    out = []
    for o in osmium.FileProcessor(str(pbf)).with_locations().with_filter(osmium.filter.EmptyTagFilter()):
        if o.is_relation():
            continue  # отношения — ниже, через сборку мультиполигонов
        tags = dict(o.tags)
        if not wanted(tags):
            continue
        if o.is_node():
            lat, lon = o.location.lat, o.location.lon
        else:
            pts = [(n.location.lat, n.location.lon) for n in o.nodes if n.location.valid()]
            if not pts:
                continue
            lat, lon = _bbox_center(pts)
        if inside(lat, lon):
            out.append({"type": "node" if o.is_node() else "way", "id": o.id, "lat": lat, "lon": lon, "tags": tags})

    # Отношения-мультиполигоны (крупные парки и т. п.): центр bbox внешнего контура.
    for o in osmium.FileProcessor(str(pbf)).with_areas().with_filter(osmium.filter.EmptyTagFilter()):
        if not o.is_area() or o.from_way():
            continue
        tags = dict(o.tags)
        if not wanted(tags):
            continue
        pts = [(n.location.lat, n.location.lon) for ring in o.outer_rings() for n in ring if n.location.valid()]
        if pts:
            lat, lon = _bbox_center(pts)
            if inside(lat, lon):
                out.append({"type": "relation", "id": o.orig_id(), "lat": lat, "lon": lon, "tags": tags})

    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    log(f"  Geofabrik: {len(out)} объектов за {time.time() - t0:.0f} с")
    return out, file_mtime_iso(pbf)


def _osmium_available() -> bool:
    try:
        import osmium  # noqa: F401
        return True
    except ImportError:
        return False


def fetch(refresh: bool = False, source: str = "auto") -> tuple[list[dict], str, str]:
    """→ (элементы внутри bbox Астаны, дата данных, использованный источник).

    source: 'overpass' | 'geofabrik' | 'auto' (Geofabrik, если уже скачан и есть pyosmium; иначе Overpass,
    при его недоступности — Geofabrik)."""
    geofabrik_ready = (GEOFABRIK_CACHE.exists() and not refresh) or _osmium_available()
    if source == "auto" and geofabrik_ready and (GEOFABRIK_FILE.exists() or GEOFABRIK_CACHE.exists()):
        source = "geofabrik"
    used = source
    if source == "geofabrik":
        elements, date = _from_geofabrik(refresh)
    else:
        try:
            elements, date = _from_overpass(refresh)
            used = "overpass"
        except Exception as e:
            if source == "overpass" or not geofabrik_ready:
                raise
            log(f"  Overpass недоступен ({e}); переключаюсь на выгрузку Geofabrik")
            elements, date = _from_geofabrik(refresh)
            used = "geofabrik"
    out = [e for e in elements if in_bbox(e["lat"], e["lon"])]
    log(f"  OSM ({used}): {len(out)} элементов (данные от {date})")
    return out, date, used

"""2GIS Places API (официальный, catalog.api.2gis.com) — только при TWOGIS_API_KEY в .env.

Без ключа модуль тихо пропускается. Что делает при наличии ключа:
1) для самых популярных уже найденных мест (кафе, музеи, ТЦ…) ищет карточку 2GIS рядом
   (≤150 м, похожее имя) и добавляет часы работы, рейтинг, число отзывов, телефон, сайт;
2) добирает кафе вокруг контрольных точек (Mega Silk Way, ЭКСПО, Байтерек, центр).

Лимиты демо-ключа: держим бюджет запросов TWOGIS_MAX_REQUESTS (по умолчанию 250)
и паузу между запросами. Каждый ответ кэшируется в data/raw/2gis/.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse

from common import RAW, TODAY, haversine_m, http, in_bbox, log, norm_name, short_hash

API = "https://catalog.api.2gis.com/3.0/items"
FIELDS = "items.point,items.schedule,items.reviews,items.contact_groups,items.address,items.rubrics"
ENRICH_CATEGORIES = {"cafe", "restaurant", "bar", "nightlife", "museum", "gallery", "theatre", "cinema",
                     "mall", "kids", "entertainment", "library", "coworking", "sport", "wellness"}
ENRICH_TOP = 450  # сколько самых популярных мест обогащать часами/рейтингом 2GIS
# Добор по рубрикам: (запрос, регулярка по названиям рубрик 2GIS, категория, теги).
# Объект берётся, только если его рубрика подтверждает тип (иначе на «бассейн» пришёл бы любой фитнес-клуб).
HARVEST = [
    ("бассейн", r"бассейн", "wellness", ["swimming", "pool"]),
    ("аквапарк", r"аквапарк", "kids", ["swimming", "pool", "water_park", "fun"]),
    ("фитнес-клуб", r"фитнес|тренаж", "wellness", ["fitness", "gym"]),
    ("спа", r"spa|спа", "wellness", ["spa"]),
    ("сауна", r"саун|бан[ия]", "wellness", ["sauna"]),
    ("боулинг", r"боулинг", "entertainment", ["bowling", "fun"]),
    ("квесты", r"квест", "entertainment", ["quest", "unusual", "interactive"]),
    ("караоке", r"караоке", "entertainment", ["karaoke", "fun"]),
    ("каток", r"каток|катки", "sport", ["ice", "skating", "winter"]),
    ("батутный центр", r"батут", "kids", ["kids", "trampoline", "fun"]),
    ("детский развлекательный центр", r"детск|игров", "kids", ["kids", "family", "fun"]),
    ("кинотеатр", r"кинотеатр", "cinema", []),
    ("музей", r"музе", "museum", ["culture"]),
    ("галерея", r"галере|выставоч", "gallery", ["art", "culture"]),
    ("театр", r"театр|концертн|филармон", "theatre", ["culture"]),
    ("смотровая площадка", r"смотров|достопримечат", "viewpoint", ["view", "photo"]),
    ("парк", r"\bпарки?\b|сквер|бульвар|зоны отдыха", "park", ["outdoor", "walk"]),
    ("коворкинг", r"коворкинг", "coworking", ["wifi", "work"]),
    ("кофейня", r"кофейн|кафе", "cafe", ["coffee"]),
    ("супермаркет", r"супермаркет|гипермаркет", "supermarket", ["groceries"]),
    ("продукты 24 часа", r"продукт", "convenience", ["groceries"]),
    ("одежда", r"одежд", "clothes", ["shopping"]),
    ("обувь", r"обув", "clothes", ["shoes", "shopping"]),
    ("канцтовары", r"канц", "shop", ["stationery"]),
    ("книжный магазин", r"книж|книг", "shop", ["books", "stationery"]),
    ("аптека", r"аптек", "pharmacy", ["pharmacy", "medicine"]),
]
HARVEST_POINTS = {"baiterek": (51.1283, 71.4305), "mega_silk_way": (51.0890, 71.4100),
                  "old_center": (51.1690, 71.4300)}
# Рубрики, которые не делают место тем, что ищут: «паркинги» совпадают с «парк»,
# «строительство бань и саун» — с «сауна». Такие рубрики игнорируются; если основная рубрика
# из этого списка — объект не берём вовсе.
EXCLUDE_RUBRICS = re.compile(r"паркинг|парковк|автостоян|стоянк|строительств|обслуживание бассейнов|"
                             r"гидроизоляц|кровельн|оборудование для|продажа оборудования", re.I)
HARVEST_RADIUS = 3000
# Редкие типы мест добираем по всему городу (сортировка по релевантности): запрос → число страниц по 10
CITYWIDE = {"боулинг": 1, "аквапарк": 1, "каток": 1, "батутный центр": 1, "смотровая площадка": 1,
            "музей": 3, "бассейн": 2, "театр": 1, "кинотеатр": 1}
CITY_CENTER, CITY_RADIUS = (51.13, 71.43), 20000
TYPICAL_MIN = {"wellness": 90, "kids": 90, "entertainment": 90, "sport": 90, "cinema": 140, "museum": 75,
               "gallery": 45, "theatre": 150, "viewpoint": 20, "park": 45, "coworking": 120, "cafe": 45,
               "supermarket": 20, "convenience": 10, "clothes": 40, "shop": 20, "pharmacy": 10}
LABEL = {"wellness": "Спорт и отдых", "kids": "Место для детей", "entertainment": "Развлечения", "sport": "Спорт",
         "cinema": "Кинотеатр", "museum": "Музей", "gallery": "Галерея", "theatre": "Театр", "viewpoint": "Смотровая точка",
         "park": "Парк", "coworking": "Коворкинг", "cafe": "Кафе", "supermarket": "Супермаркет",
         "convenience": "Продуктовый магазин", "clothes": "Магазин одежды", "shop": "Магазин", "pharmacy": "Аптека"}
from normalize import SNAPSHOT_FIELDS as SNAPSHOT  # noqa: E402
SEED_POINTS = {
    "mega_silk_way": (51.0890, 71.4100), "expo": (51.0898, 71.4159),
    "baiterek": (51.1283, 71.4305), "khan_shatyr": (51.1325, 71.4036),
    "old_center": (51.1690, 71.4300), "embankment": (51.1580, 71.4450),
}
DAYS = [("Mon", "Mo"), ("Tue", "Tu"), ("Wed", "We"), ("Thu", "Th"), ("Fri", "Fr"), ("Sat", "Sa"), ("Sun", "Su")]
CACHE_DIR = RAW / "2gis"


class Budget:
    def __init__(self, n: int):
        self.left = n
        self.used = 0


def _get(params: dict, key: str, budget: Budget, refresh: bool, cache_id: str | None = None) -> dict | None:
    """cache_id — стабильный ключ кэша (id POI), чтобы смена имени не порождала новый запрос."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{short_hash(cache_id or json.dumps(params, sort_keys=True))}.json"
    legacy = CACHE_DIR / f"{short_hash(json.dumps(params, sort_keys=True))}.json"
    if cache_id and not cache.exists() and legacy.exists():
        cache.write_bytes(legacy.read_bytes())
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    if budget.left <= 0:
        return None
    budget.left -= 1
    budget.used += 1
    url = API + "?" + urllib.parse.urlencode({**params, "key": key})
    try:
        obj = json.loads(http(url, timeout=30, retries=2))
    except Exception as e:
        log(f"  2GIS: ошибка запроса ({type(e).__name__})")  # url с ключом не печатаем
        return None
    time.sleep(0.35)
    cache.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return obj


def schedule_to_osm(s: dict | None) -> str | None:
    """2GIS schedule → строка OSM opening_hours, напр. 'Mo-Fr 09:00-18:00; Sa,Su 10:00-16:00'."""
    if not s:
        return None
    if s.get("is_24x7"):
        return "24/7"
    per_day = []
    for k, osm_day in DAYS:
        hrs = (s.get(k) or {}).get("working_hours") or []
        spans = ",".join(f"{h['from']}-{'24:00' if h['to'] == '00:00' else h['to']}" for h in hrs if h.get("from"))
        per_day.append((osm_day, spans))
    if not any(sp for _, sp in per_day):
        return None
    rules, i = [], 0
    while i < 7:
        j = i
        while j + 1 < 7 and per_day[j + 1][1] == per_day[i][1]:
            j += 1
        if per_day[i][1]:
            days = per_day[i][0] if i == j else f"{per_day[i][0]}-{per_day[j][0]}"
            rules.append(f"{days} {per_day[i][1]}")
        i = j + 1
    return "; ".join(rules)


def _contacts(item: dict) -> tuple[str | None, str | None]:
    phone = site = None
    for g in item.get("contact_groups") or []:
        for c in g.get("contacts") or []:
            if c.get("type") == "phone" and not phone:
                phone = c.get("text") or c.get("value")
            if c.get("type") == "website" and not site:
                site = c.get("url") or c.get("value")
    return phone, site


def _rating(item: dict) -> tuple[float | None, int | None]:
    r = item.get("reviews") or {}
    rating = r.get("general_rating")
    cnt = r.get("general_review_count")
    return (float(rating) if rating else None), (int(cnt) if cnt else None)


def _apply(p: dict, item: dict) -> None:
    # снимок полей до 2GIS — из него собирается открытая выгрузка pois_open.json
    p.setdefault("_pre2gis", {f: (list(p[f]) if f == "tags" else p.get(f)) for f in SNAPSHOT})
    hours = schedule_to_osm(item.get("schedule"))
    if hours:  # 2GIS свежее OSM по часам работы
        p["opening_hours"], p["opening_hours_source"], p["opening_hours_checked_at"] = hours, "2gis", TODAY
    p["rating"], p["rating_count"] = _rating(item)
    phone, site = _contacts(item)
    p["phone"] = p.get("phone") or phone
    p["website"] = p.get("website") or site
    if not p.get("address") and item.get("address_name"):
        p["address"] = item["address_name"]
    url = f"https://2gis.kz/astana/firm/{item.get('id', '').split('_')[0]}"
    if all(src.get("url") != url for src in p["sources"]):
        p["sources"].append({"name": "2gis", "url": url, "fetched_at": TODAY})
    if hours == "24/7":
        p["tags"] = sorted(set(p["tags"]) | {"24_7", "night"})


def clean_name(name: str) -> str:
    """«На крыше, ресторан» → «На крыше» (2GIS дописывает тип через запятую)."""
    return name.split(",")[0].strip() or name


def _new_poi(item: dict, cat: str = "cafe", tags: list[str] | None = None) -> dict | None:
    import normalize
    import opening_hours as oh
    pt = item.get("point") or {}
    lat, lon = pt.get("lat"), pt.get("lon")
    if lat is None or not in_bbox(lat, lon) or not item.get("name"):
        return None
    name = clean_name(item["name"])
    address = item.get("address_name")
    rubrics = ", ".join(r.get("name", "") for r in item.get("rubrics") or []
                        if not EXCLUDE_RUBRICS.search(r.get("name", "")))
    all_tags = set(tags or ["coffee"]) | set(normalize.CATEGORY_TAGS.get(cat, []))
    all_tags |= set(normalize.name_tags(name + " " + rubrics))
    if name.lower() in normalize.BUDGET_BRANDS:
        all_tags.add("budget")
    desc = f"{LABEL.get(cat, 'Место')} «{name}»" + (f" по адресу: {address}." if address else ".")
    if rubrics:
        desc += f" Рубрики 2GIS: {rubrics.lower()}."
    p = {
        "id": f"2gis:{item['id'].split('_')[0]}", "name": name, "name_i18n": {"ru": name},
        "lat": round(lat, 6), "lon": round(lon, 6), "category": cat, "tags": sorted(all_tags | {"indoor"} if cat != "park" else all_tags),
        "description": desc, "description_source": "template", "address": address,
        "opening_hours": None, "opening_hours_source": None, "opening_hours_checked_at": None,
        "phone": None, "website": None, "rating": None, "rating_count": None, "popularity": None,
        "indoor": cat != "park", "wheelchair": "unknown",
        "kid_friendly": True if cat == "kids" or "kids" in all_tags else None, "price_level": 0 if cat == "park" else None,
        "typical_visit_min": TYPICAL_MIN.get(cat, 45), "sources": [], "data_quality": None, "updated_at": TODAY,
        "_only2gis": True,
    }
    _apply(p, item)
    if oh.is_night(p["opening_hours"]):
        p["tags"] = sorted(set(p["tags"]) | {"night"})
    return p


def _find_existing(pois: list[dict], name: str, lat: float, lon: float) -> dict | None:
    nn = norm_name(name)
    if not nn:
        return None
    for q in pois:
        if abs(q["lat"] - lat) > 0.002 or abs(q["lon"] - lon) > 0.003:
            continue
        qn = norm_name(q["name"])
        if qn and (qn == nn or (len(nn) > 4 and (nn in qn or qn in nn))) and haversine_m(q["lat"], q["lon"], lat, lon) < 80:
            return q
    return None


def _harvest(pois: list[dict], key: str, budget: Budget, refresh: bool, limit: int) -> dict[str, int]:
    """Добор мест по рубрикам вокруг контрольных точек (сортировка по расстоянию)."""
    added: dict[str, int] = {}
    seen: set[str] = {p["id"] for p in pois}
    for q, rubric_rx, cat, tags in HARVEST:
        requests = [{"q": q, "point": f"{lon},{lat}", "radius": HARVEST_RADIUS, "sort": "distance",
                     "fields": FIELDS, "page_size": 10, "locale": "ru_KZ", "type": "branch"}
                    for lat, lon in HARVEST_POINTS.values()]
        requests += [{"q": q, "point": f"{CITY_CENTER[1]},{CITY_CENTER[0]}", "radius": CITY_RADIUS, "page": page,
                      "fields": FIELDS, "page_size": 10, "locale": "ru_KZ", "type": "branch"}
                     for page in range(1, CITYWIDE.get(q, 0) + 1)]
        for params in requests:
            if budget.used >= limit:
                break
            obj = _get(params, key, budget, refresh)
            for it in ((obj or {}).get("result") or {}).get("items") or []:
                names = [r.get("name", "").lower() for r in it.get("rubrics") or []]
                if not names or EXCLUDE_RUBRICS.search(names[0]):
                    continue  # основная рубрика — паркинг, стройка и т. п.
                rubrics = " | ".join(n for n in names if not EXCLUDE_RUBRICS.search(n))
                if not re.search(rubric_rx, rubrics):
                    continue  # рубрика не подтверждает тип
                pid = f"2gis:{str(it.get('id', '')).split('_')[0]}"
                pt = it.get("point") or {}
                if pid in seen or pt.get("lat") is None:
                    continue
                seen.add(pid)
                existing = _find_existing(pois, clean_name(it.get("name", "")), pt["lat"], pt["lon"])
                if existing:  # уже есть из OSM — дополняем данными 2GIS и тегами
                    _apply(existing, it)
                    existing["tags"] = sorted(set(existing["tags"]) | set(tags))
                    continue
                np_ = _new_poi(it, cat, tags)
                if np_:
                    pois.append(np_)
                    added[cat] = added.get(cat, 0) + 1
    return added


def enrich(pois: list[dict], env: dict, refresh: bool = False) -> str:
    key = env.get("TWOGIS_API_KEY")
    if not key:
        log("  TWOGIS_API_KEY не задан — 2GIS пропущен")
        return "пропущено (нет TWOGIS_API_KEY)"
    budget = Budget(int(env.get("TWOGIS_MAX_REQUESTS", "250")))
    enrich_share = budget.left  # обогащение тратит то, что осталось после добора по рубрикам

    # 0) добор по рубрикам (бассейны, музеи, супермаркеты, аптеки…) — приоритет
    harvested = _harvest(pois, key, budget, refresh, limit=int(budget.left * 0.6))

    # 1) обогащение популярных мест
    targets = sorted((p for p in pois if p["category"] in ENRICH_CATEGORIES and not p.get("_unnamed")
                      and not p.get("_only2gis")),
                     key=lambda p: -(p.get("_sitelinks") or 0) - (0.5 if p.get("_wikidata") else 0))
    cache_only = Budget(0)  # за пределами топ-ENRICH_TOP — только из кэша, без новых запросов
    matched = 0
    for i, p in enumerate(targets):
        if budget.used >= enrich_share:
            break
        obj = _get({"q": p["name"], "point": f"{p['lon']},{p['lat']}", "radius": 200,
                    "fields": FIELDS, "page_size": 3, "locale": "ru_KZ"}, key,
                   budget if i < ENRICH_TOP else cache_only, refresh, cache_id=f"enrich:{p['id']}")
        items = ((obj or {}).get("result") or {}).get("items") or []
        nn = norm_name(p["name"])
        for it in items:
            pt = it.get("point") or {}
            if pt.get("lat") is None:
                continue
            close = haversine_m(p["lat"], p["lon"], pt["lat"], pt["lon"]) < 150
            same = nn and (nn in norm_name(it.get("name", "")) or norm_name(it.get("name", "")) in nn)
            if close and same:
                _apply(p, it)
                matched += 1
                break

    # 2) добор кафе у контрольных точек
    added = 0
    for _, (lat, lon) in SEED_POINTS.items():
        for page in (1, 2):
            obj = _get({"q": "кафе", "point": f"{lon},{lat}", "radius": 1000, "fields": FIELDS,
                        "page_size": 10, "page": page, "locale": "ru_KZ", "type": "branch"}, key, budget, refresh)
            for it in ((obj or {}).get("result") or {}).get("items") or []:
                np_ = _new_poi(it)
                if not np_ or any(q["id"] == np_["id"] for q in pois):
                    continue
                if not _find_existing(pois, np_["name"], np_["lat"], np_["lon"]):
                    pois.append(np_)
                    added += 1
    h = ", ".join(f"{k} {v}" for k, v in sorted(harvested.items(), key=lambda x: -x[1])) or "0"
    msg = (f"ok: добор по рубрикам — {sum(harvested.values())} ({h}); обогащено {matched}; "
           f"добавлено кафе {added}; новых запросов к API {budget.used}")
    log("  2GIS " + msg)
    return msg

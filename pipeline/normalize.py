"""OSM-элемент → POI по contracts/poi.schema.json + эвристики, качество, дедупликация."""
from __future__ import annotations

import re

from common import TODAY, haversine_m, norm_name
import opening_hours as oh

# (ключ, значение | None = любое) → категория. Первое совпадение выигрывает.
CATEGORY_RULES = [
    ("tourism", "museum", "museum"),
    ("amenity", "planetarium", "museum"),
    ("tourism", "gallery", "gallery"),
    ("tourism", "zoo", "kids"),
    ("tourism", "aquarium", "kids"),
    ("tourism", "theme_park", "kids"),
    ("leisure", "water_park", "kids"),
    ("leisure", "trampoline_park", "kids"),
    ("tourism", "viewpoint", "viewpoint"),
    ("man_made", "tower", "viewpoint"),
    ("amenity", "theatre", "theatre"),
    ("amenity", "cinema", "cinema"),
    ("amenity", "library", "library"),
    ("amenity", "coworking_space", "coworking"),
    ("office", "coworking", "coworking"),
    ("amenity", "nightclub", "nightlife"),
    ("amenity", "bar", "bar"),
    ("amenity", "pub", "bar"),
    ("amenity", "cafe", "cafe"),
    ("amenity", "ice_cream", "cafe"),
    ("amenity", "internet_cafe", "cafe"),
    ("amenity", "restaurant", "restaurant"),
    ("amenity", "fast_food", "restaurant"),
    ("shop", "mall", "mall"),
    ("leisure", "swimming_pool", "wellness"),
    ("leisure", "fitness_centre", "wellness"),
    ("leisure", "sauna", "wellness"),
    ("leisure", "spa", "wellness"),
    ("amenity", "spa", "wellness"),
    ("amenity", "sauna", "wellness"),
    ("amenity", "public_bath", "wellness"),
    ("amenity", "pharmacy", "pharmacy"),
    ("shop", "supermarket", "supermarket"),
    ("shop", "convenience", "convenience"),
    ("shop", "clothes", "clothes"),
    ("shop", "shoes", "clothes"),
    ("shop", "department_store", "shop"),
    ("shop", None, "shop"),
    ("amenity", "marketplace", "market"),
    ("amenity", "place_of_worship", "religious"),
    ("amenity", "arts_centre", "gallery"),
    ("amenity", "events_venue", "entertainment"),
    ("amenity", "music_venue", "entertainment"),
    ("amenity", "karaoke_box", "entertainment"),
    ("amenity", "community_centre", "entertainment"),
    ("leisure", "miniature_golf", "entertainment"),
    ("leisure", "dance", "entertainment"),
    ("leisure", "amusement_arcade", "entertainment"),
    ("leisure", "escape_game", "entertainment"),
    ("leisure", "bowling_alley", "entertainment"),
    ("leisure", "playground", "playground"),
    ("landuse", "recreation_ground", "park"),
    ("place", "square", "landmark"),
    ("highway", "pedestrian", "park"),
    ("leisure", "park", "park"),
    ("leisure", "garden", "park"),
    ("leisure", "nature_reserve", "park"),
    ("leisure", "ice_rink", "sport"),
    ("leisure", "stadium", "sport"),
    ("leisure", "sports_centre", "sport"),
    ("historic", "memorial", "monument"),
    ("historic", "monument", "monument"),
    ("tourism", "artwork", "monument"),
    ("amenity", "fountain", "landmark"),
    ("tourism", "attraction", "landmark"),
    ("building", "museum", "museum"),
    ("building", "theatre", "theatre"),
    ("building", "cathedral", "religious"),
    ("building", "mosque", "religious"),
    ("building", "church", "religious"),
    ("building", "temple", "religious"),
    ("building", "synagogue", "religious"),
    ("tower:type", "observation", "viewpoint"),
    ("historic", None, "landmark"),
    ("wikidata", None, "landmark"),
]

LABEL_RU = {
    "cafe": "Кафе", "restaurant": "Ресторан", "bar": "Бар", "nightlife": "Ночной клуб",
    "museum": "Музей", "gallery": "Галерея / арт-пространство", "theatre": "Театр",
    "cinema": "Кинотеатр", "park": "Парк", "viewpoint": "Смотровая точка",
    "monument": "Памятник", "landmark": "Достопримечательность", "religious": "Религиозный объект",
    "mall": "Торговый центр", "playground": "Детская площадка", "kids": "Место для детей",
    "entertainment": "Развлекательное место", "sport": "Спортивный объект",
    "library": "Библиотека", "coworking": "Коворкинг", "market": "Рынок", "other": "Место",
    "supermarket": "Супермаркет", "convenience": "Магазин у дома", "clothes": "Магазин одежды",
    "shop": "Магазин", "pharmacy": "Аптека", "wellness": "Спорт и отдых: бассейн, спа, фитнес",
}
SUBLABEL_RU = {
    ("amenity", "fast_food"): "Фастфуд", ("amenity", "ice_cream"): "Кафе-мороженое",
    ("amenity", "pub"): "Паб", ("amenity", "planetarium"): "Планетарий",
    ("tourism", "zoo"): "Зоопарк", ("tourism", "aquarium"): "Океанариум",
    ("tourism", "theme_park"): "Парк развлечений", ("leisure", "water_park"): "Аквапарк",
    ("leisure", "trampoline_park"): "Батутный центр", ("leisure", "garden"): "Сад / сквер",
    ("leisure", "escape_game"): "Квест-комната", ("leisure", "bowling_alley"): "Боулинг",
    ("leisure", "ice_rink"): "Каток", ("leisure", "stadium"): "Стадион",
    ("amenity", "fountain"): "Фонтан", ("tourism", "artwork"): "Арт-объект",
    ("amenity", "arts_centre"): "Арт-центр", ("leisure", "amusement_arcade"): "Игровой зал",
    ("leisure", "swimming_pool"): "Бассейн", ("leisure", "fitness_centre"): "Фитнес-клуб",
    ("leisure", "sauna"): "Сауна", ("amenity", "sauna"): "Сауна", ("leisure", "spa"): "Спа-центр",
    ("amenity", "spa"): "Спа-центр", ("amenity", "public_bath"): "Баня",
    ("amenity", "karaoke_box"): "Караоке", ("amenity", "community_centre"): "Центр досуга",
    ("leisure", "miniature_golf"): "Мини-гольф", ("leisure", "dance"): "Танцевальная студия",
    ("shop", "shoes"): "Магазин обуви", ("shop", "stationery"): "Канцтовары",
    ("shop", "books"): "Книжный магазин", ("shop", "electronics"): "Магазин электроники",
    ("shop", "mobile_phone"): "Салон связи", ("shop", "hardware"): "Хозяйственный магазин",
    ("shop", "gift"): "Магазин подарков", ("shop", "toys"): "Магазин игрушек",
    ("shop", "cosmetics"): "Магазин косметики", ("shop", "bakery"): "Пекарня",
    ("shop", "confectionery"): "Кондитерская", ("shop", "chemist"): "Бытовая химия и косметика",
    ("shop", "department_store"): "Универмаг",
}
CUISINE_RU = {
    "coffee_shop": "кофейня", "kazakh": "казахская", "russian": "русская", "italian": "итальянская",
    "japanese": "японская", "sushi": "суши", "pizza": "пицца", "burger": "бургеры",
    "georgian": "грузинская", "uzbek": "узбекская", "turkish": "турецкая", "chinese": "китайская",
    "korean": "корейская", "asian": "азиатская", "european": "европейская", "american": "американская",
    "regional": "местная", "international": "интернациональная", "steak_house": "стейки",
    "chicken": "курица", "kebab": "кебаб", "shawarma": "шаурма", "dessert": "десерты",
    "cake": "выпечка", "tea": "чай", "ice_cream": "мороженое", "donut": "пончики",
    "pancake": "блины", "french": "французская", "indian": "индийская", "thai": "тайская",
    "vietnamese": "вьетнамская", "middle_eastern": "ближневосточная", "seafood": "морепродукты",
    "bubble_tea": "бабл-ти", "breakfast": "завтраки", "barbecue": "барбекю",
}

TYPICAL_MIN = {
    "cafe": 45, "restaurant": 75, "bar": 90, "nightlife": 120, "museum": 75, "gallery": 45,
    "theatre": 150, "cinema": 140, "park": 45, "viewpoint": 20, "monument": 10, "landmark": 20,
    "religious": 20, "mall": 90, "playground": 40, "kids": 90, "entertainment": 90, "sport": 90,
    "library": 60, "coworking": 120, "market": 45, "other": 30, "supermarket": 20,
    "convenience": 10, "clothes": 40, "shop": 20, "pharmacy": 10, "wellness": 90,
}
INDOOR = {
    "cafe": True, "restaurant": True, "bar": True, "nightlife": True, "museum": True, "gallery": True,
    "theatre": True, "cinema": True, "park": False, "viewpoint": False, "monument": False,
    "religious": True, "mall": True, "playground": False, "entertainment": True, "library": True,
    "coworking": True, "supermarket": True, "convenience": True, "clothes": True, "shop": True,
    "pharmacy": True, "wellness": True,
}
KID_FRIENDLY = {
    "playground": True, "kids": True, "park": True, "mall": True, "cinema": True, "museum": True,
    "bar": False, "nightlife": False,
}
FREE_CATEGORIES = {"park", "playground", "monument", "viewpoint", "landmark"}
CATEGORY_TAGS = {
    "cafe": ["coffee"], "museum": ["indoor", "culture"], "gallery": ["indoor", "culture", "art"],
    "theatre": ["indoor", "culture"], "cinema": ["indoor"], "park": ["outdoor", "quiet", "walk"],
    "viewpoint": ["view", "photo", "outdoor"], "monument": ["photo", "outdoor"],
    "landmark": ["photo"], "religious": ["quiet", "culture"], "mall": ["indoor", "shopping", "family"],
    "playground": ["kids", "family", "outdoor"], "kids": ["kids", "family"],
    "entertainment": ["indoor", "fun"], "library": ["quiet", "indoor"],
    "supermarket": ["groceries", "shopping"], "convenience": ["groceries", "shopping"],
    "clothes": ["shopping"], "shop": ["shopping"], "pharmacy": ["pharmacy", "medicine"],
    "coworking": ["wifi", "sockets", "indoor", "work"], "nightlife": ["night"], "bar": ["evening"],
}
SUBTYPE_TAGS = {
    ("tourism", "zoo"): ["kids", "outdoor"], ("tourism", "aquarium"): ["kids", "indoor", "unusual"],
    ("tourism", "theme_park"): ["kids", "fun"], ("leisure", "water_park"): ["kids", "indoor", "fun"],
    ("amenity", "planetarium"): ["kids", "unusual", "interactive"],
    ("leisure", "escape_game"): ["unusual", "interactive"], ("leisure", "garden"): ["quiet", "outdoor"],
    ("tourism", "artwork"): ["art", "photo"], ("amenity", "ice_cream"): ["dessert", "kids"],
    ("man_made", "tower"): ["view", "indoor", "photo"], ("leisure", "ice_rink"): ["winter", "fun", "ice", "skating"],
    ("leisure", "swimming_pool"): ["swimming", "pool"], ("leisure", "water_park"): ["swimming", "pool", "water_park"],
    ("leisure", "fitness_centre"): ["fitness", "gym"], ("leisure", "sauna"): ["sauna"], ("amenity", "sauna"): ["sauna"],
    ("leisure", "spa"): ["spa"], ("amenity", "spa"): ["spa"], ("amenity", "public_bath"): ["bath", "banya", "sauna"],
    ("leisure", "bowling_alley"): ["bowling", "fun"], ("amenity", "karaoke_box"): ["karaoke", "night", "fun"],
    ("shop", "stationery"): ["stationery"], ("shop", "books"): ["books", "stationery"],
    ("shop", "electronics"): ["electronics"], ("shop", "mobile_phone"): ["electronics"],
    ("shop", "shoes"): ["shoes"], ("shop", "toys"): ["kids", "toys"], ("shop", "bakery"): ["bakery"],
    ("shop", "confectionery"): ["dessert"], ("shop", "cosmetics"): ["cosmetics"], ("shop", "gift"): ["gifts"],
    ("shop", "department_store"): ["clothes"],
}
# Слова в названии → теги (ищем «бассейн» и в названии спорткомплекса без тега sport)
NAME_TAGS = [
    (r"бассейн|аквапарк|\bpool\b|swim", ["swimming", "pool"]),
    (r"фитнес|fitness|\bgym\b|тренаж", ["fitness", "gym"]),
    (r"сауна|sauna|баня|банн|хаммам|hammam", ["sauna"]),
    (r"\bспа\b|\bspa\b|spa-|спа-", ["spa"]),
    (r"боулинг|bowling", ["bowling"]),
    (r"каток|ice rink|ледов", ["ice", "skating"]),
    (r"канц", ["stationery"]),
    (r"караоке|karaoke", ["karaoke"]),
    (r"батут|trampoline", ["kids", "trampoline"]),
    (r"квест|quest|escape", ["quest", "unusual"]),
]
WELLNESS_TAGS = {"swimming", "pool", "fitness", "gym", "sauna", "spa"}


def name_tags(name: str) -> list[str]:
    n = (name or "").lower()
    return [t for rx, tags in NAME_TAGS if re.search(rx, n) for t in tags]


# sport=* (OSM) → теги, по которым ищет бэкенд
SPORT_TAGS = {
    "swimming": ["swimming", "pool"], "fitness": ["fitness", "gym"], "ice_skating": ["ice", "skating"],
    "ice_hockey": ["ice"], "bowling": ["bowling"], "10pin": ["bowling"], "climbing": ["climbing"],
    "yoga": ["yoga", "fitness"], "billiards": ["billiards"], "tennis": ["tennis"], "multi": ["fitness"],
    "equestrian": ["horse_riding"], "boxing": ["fitness"], "martial_arts": ["fitness"],
}
# Тег budget — только для сетей, которые позиционируют себя как магазины низких цен.
# Список короткий и проверяемый; если не уверены — сеть сюда не добавляем.
BUDGET_BRANDS = {"fix price", "фикс прайс", "sinsay", "magnum cash & carry", "magnum cash&carry"}


def _match(tags: dict) -> tuple[str, tuple[str, str] | None]:
    sport = tags.get("sport") or ""
    if tags.get("leisure") == "sports_centre" and re.search(r"swimming|fitness|yoga|aerobics", sport):
        return "wellness", ("leisure", "sports_centre")
    for k, v, cat in CATEGORY_RULES:
        if k in tags and (v is None or tags[k] == v):
            return cat, (k, tags[k])
    return "other", None


def _address(t: dict) -> str | None:
    if t.get("addr:full"):
        return t["addr:full"]
    street, num = t.get("addr:street"), t.get("addr:housenumber")
    if street and num:
        return f"{street}, {num}"
    return street or None


def _osm_tags(t: dict, hours: str | None) -> list[str]:
    out = []
    if t.get("internet_access") in ("wlan", "yes", "wifi") or t.get("internet_access:fee") == "no":
        out.append("wifi")
    if any(k.startswith("socket") for k in t) or t.get("power_supply") in ("yes",):
        out.append("sockets")
    if t.get("outdoor_seating") == "yes":
        out += ["outdoor_seating", "terrace"]
    if t.get("wheelchair") == "yes":
        out.append("wheelchair")
    for diet in ("vegan", "vegetarian", "halal"):
        if t.get(f"diet:{diet}") in ("yes", "only"):
            out.append(diet)
    if oh.is_night(hours):
        out.append("night")
    if hours == "24/7":
        out.append("24_7")
    if t.get("fee") == "no":
        out.append("free")
    if t.get("takeaway") in ("yes", "only"):
        out.append("takeaway")
    if "coffee" in (t.get("cuisine") or "") or t.get("cuisine") == "coffee_shop":
        out.append("coffee")
    if t.get("indoor") == "yes":
        out.append("indoor")
    for sp in re.split(r"[;,]", t.get("sport") or ""):
        out += SPORT_TAGS.get(sp.strip(), [])
    brand = (t.get("brand") or "").strip()
    if brand:
        out.append("brand:" + re.sub(r"\s+", "_", brand.lower()))
    if t.get("clothes") and re.search(r"children|babies|kids", t["clothes"]):
        out.append("kids_clothes")
    names = {(t.get(k) or "").lower() for k in ("brand", "name", "name:ru", "name:en")}
    if names & BUDGET_BRANDS:
        out.append("budget")
    return out


def _template_description(name: str, label: str, t: dict, address: str | None, tags: list[str]) -> str:
    s = f"{label} «{name}»"
    if address:
        s += f" по адресу: {address}"
    s += "."
    cuisines = [CUISINE_RU.get(c.strip()) for c in (t.get("cuisine") or "").split(";")]
    cuisines = [c for c in cuisines if c]
    feats = []
    if cuisines:
        feats.append("кухня: " + ", ".join(cuisines[:3]))
    if "wifi" in tags:
        feats.append("есть Wi-Fi")
    if "sockets" in tags:
        feats.append("есть розетки")
    if "outdoor_seating" in tags:
        feats.append("есть летняя веранда")
    if "wheelchair" in tags:
        feats.append("доступно для колясок")
    if any(d in tags for d in ("vegan", "vegetarian")):
        feats.append("есть вегетарианские блюда")
    if feats:
        s += " " + "; ".join(feats).capitalize() + "."
    return s


def _wheelchair(v: str | None) -> str:
    return v if v in ("yes", "limited", "no") else "unknown"


def from_osm(e: dict, fetched_at: str, bad_hours: list) -> dict | None:
    t = e["tags"]
    if t.get("access") in ("private", "no") or t.get("amenity") in ("kindergarten", "childcare", "school"):
        return None  # дворы детсадов/школ и частные объекты не рекомендуем
    cat, key = _match(t)
    sub = SUBLABEL_RU.get(key) if key else None
    name = t.get("name:ru") or t.get("name")
    if not name:
        if cat != "playground":
            return None
        name = "Детская площадка"  # безымянные площадки во дворах полезны для сценария «с ребёнком»
    hours, bad = oh.clean(t.get("opening_hours"))
    oid = f"{e['type']}/{e['id']}"
    if bad:
        bad_hours.append((f"osm:{oid}", name, bad))
    address = _address(t)
    tags = list(CATEGORY_TAGS.get(cat, [])) + SUBTYPE_TAGS.get(key, []) + _osm_tags(t, hours) + name_tags(name)
    if cat == "sport" and WELLNESS_TAGS & set(tags):
        cat = "wellness"  # спорткомплекс с бассейном/фитнесом — это то, что ищут по слову «бассейн»
    if cat in FREE_CATEGORIES:
        tags.append("free")
    if t.get("tourism") in ("attraction", "viewpoint") or t.get("wikidata"):
        tags.append("sight")
    if (t.get("railway") in ("station", "halt") or t.get("public_transport") or t.get("aeroway")
            or t.get("building") in ("train_station", "transportation")
            or re.search(r"вокзал|аэропорт|станци|бекет|әуежай", name.lower())):
        tags.append("transport")  # бэкенд не рекомендует как цель прогулки
    tags = sorted(set(tags))

    i18n = {lang: t[f"name:{lang}"] for lang in ("ru", "kk", "en") if t.get(f"name:{lang}")}
    if "ru" not in i18n and t.get("name"):
        i18n.setdefault("ru", t["name"])

    osm_desc = (t.get("description:ru") or t.get("description") or "").strip()
    if len(osm_desc) >= 20 and re.search(r"[А-Яа-яЁё]", osm_desc):  # мусор вида «62 x 62 m» не берём
        description, dsrc = osm_desc, "osm"
    else:
        description = _template_description(name, sub or LABEL_RU[cat], t, address, tags)
        dsrc = "template"

    indoor = INDOOR.get(cat)
    if key in (("man_made", "tower"),) or "indoor" in tags:
        indoor = True
    if key in (("tourism", "zoo"), ("tourism", "theme_park")):
        indoor = False

    price = 0 if cat in FREE_CATEGORIES or t.get("fee") == "no" else None

    return {
        "id": f"osm:{oid}",
        "name": name,
        "name_i18n": i18n,
        "lat": round(e["lat"], 6),
        "lon": round(e["lon"], 6),
        "category": cat,
        "tags": tags,
        "description": description,
        "description_source": dsrc,
        "address": address,
        "opening_hours": hours,
        "opening_hours_source": "osm" if hours else None,
        "opening_hours_checked_at": fetched_at if hours else None,
        "phone": t.get("contact:phone") or t.get("phone"),
        "website": t.get("contact:website") or t.get("website"),
        "rating": None,
        "rating_count": None,
        "popularity": None,
        "indoor": indoor,
        "wheelchair": _wheelchair(t.get("wheelchair")),
        "kid_friendly": True if "kids" in tags else KID_FRIENDLY.get(cat),
        "price_level": price,
        "typical_visit_min": TYPICAL_MIN[cat],
        "sources": [{"name": "osm", "url": f"https://www.openstreetmap.org/{oid}", "fetched_at": fetched_at}],
        "data_quality": None,
        "updated_at": TODAY,
        # служебные поля (удаляются перед записью)
        "_wikidata": t.get("wikidata"),
        "_wikipedia": t.get("wikipedia"),
        "_commons": t.get("wikimedia_commons"),
        "_image": t.get("image"),
        "_unnamed": not (t.get("name:ru") or t.get("name")),
        "_has_name_ru": bool(t.get("name:ru")),
    }


# ---------- дедупликация ----------

FILL_FIELDS = ["address", "opening_hours", "opening_hours_source", "opening_hours_checked_at",
               "phone", "website", "rating", "rating_count", "_wikidata", "_wikipedia", "_commons", "_image"]


SNAPSHOT_FIELDS = ["opening_hours", "opening_hours_source", "opening_hours_checked_at", "rating", "rating_count",
                   "phone", "website", "address", "tags"]


def _merge(a: dict, b: dict) -> dict:
    """Слить b в a (a — основной: объект OSM/Wikidata, с более полными данными)."""
    if any(src["name"] == "2gis" for src in b["sources"]):
        # значения a до 2GIS — для открытой выгрузки без данных 2GIS
        a.setdefault("_pre2gis", {f: (list(a[f]) if f == "tags" else a.get(f)) for f in SNAPSHOT_FIELDS})
    for f in FILL_FIELDS:
        if not a.get(f) and b.get(f):
            a[f] = b[f]
    for lang, v in (b.get("name_i18n") or {}).items():
        a["name_i18n"].setdefault(lang, v)
    if a["description_source"] == "template" and b["description_source"] != "template":
        a["description"], a["description_source"] = b["description"], b["description_source"]
    a["tags"] = sorted(set(a["tags"]) | set(b["tags"]))
    urls = {s.get("url") for s in a["sources"]}
    a["sources"] += [s for s in b["sources"] if s.get("url") not in urls]
    a.setdefault("_merged_ids", []).append(b["id"])
    return a


def _richness(p: dict) -> tuple[bool, int]:
    # основной записью дубля всегда становится объект из открытых источников, а не из 2GIS
    return not p.get("_only2gis"), sum(1 for f in FILL_FIELDS if p.get(f)) + (p["description_source"] != "template")


def dedupe(pois: list[dict], radius_m: float = 80.0) -> tuple[list[dict], int]:
    """Одинаковое нормализованное имя и < radius_m → один объект. Безымянные площадки — по 30 м."""
    buckets: dict[str, list[dict]] = {}
    for p in sorted(pois, key=_richness, reverse=True):
        key = "__playground__" if p.get("_unnamed") else (norm_name(p["name"]) or p["name"].lower())
        r = 30.0 if p.get("_unnamed") else radius_m
        lst = buckets.setdefault(key, [])
        for q in lst:
            if haversine_m(p["lat"], p["lon"], q["lat"], q["lon"]) < r:
                _merge(q, p)
                break
        else:
            lst.append(p)
    out = [p for lst in buckets.values() for p in lst]
    out = _merge_close_same_word(out)
    return out, len(pois) - len(out)


def _first_word(p: dict) -> str:
    w = norm_name(p["name"]).split()
    return w[0] if w and len(w[0]) >= 4 else ""


def _merge_close_same_word(pois: list[dict], radius_m: float = 30.0) -> list[dict]:
    """< 30 м и одинаковое первое слово названия («PINGWIN Friends» и «PingWin (Bowling…)»,
    два филиала сети в одном здании) → один объект. Сетка ~100 м, чтобы не сравнивать всё со всем."""
    grid: dict[tuple[int, int], list[dict]] = {}
    out = []
    for p in sorted(pois, key=_richness, reverse=True):
        w = _first_word(p)
        if not w or p.get("_unnamed"):
            out.append(p)
            continue
        cell = (int(p["lat"] * 1000), int(p["lon"] * 600))
        target = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for q in grid.get((cell[0] + dx, cell[1] + dy), []):
                    if _first_word(q) == w and q["category"] == p["category"] or (
                            _first_word(q) == w and {q["category"], p["category"]} <= {"entertainment", "sport", "wellness", "kids"}):
                        if haversine_m(p["lat"], p["lon"], q["lat"], q["lon"]) < radius_m:
                            target = q
                            break
                if target:
                    break
            if target:
                break
        if target:
            _merge(target, p)
        else:
            grid.setdefault(cell, []).append(p)
            out.append(p)
    return out


# ---------- популярность и качество ----------

def score(p: dict) -> None:
    sitelinks = p.get("_sitelinks") or 0
    pop = 0.1
    if p.get("_wikidata"):
        pop += 0.25
    if p.get("_wikipedia") or sitelinks:
        pop += 0.1
    pop += min(sitelinks, 40) / 40 * 0.35
    if p.get("rating_count"):
        pop += min(p["rating_count"], 500) / 500 * 0.3
    if p["name_i18n"].get("en"):
        pop += 0.05
    if p.get("_unnamed"):
        pop = 0.02
    if p.get("_seed_popularity") is not None:
        pop = max(pop, p["_seed_popularity"])
    p["popularity"] = round(min(pop, 1.0), 3)

    q = 0.0
    q += 0.25 if p.get("opening_hours") else 0
    q += 0.25 if p["description_source"] not in ("template",) else 0.05
    q += 0.15 if p.get("rating") is not None else 0
    q += 0.1 if (p.get("phone") or p.get("website")) else 0
    q += 0.1 if p.get("address") else 0
    q += 0.05 if p["wheelchair"] != "unknown" else 0
    q += 0.1  # свежесть: все поля получены из источников в этот прогон
    p["data_quality"] = round(min(q, 1.0), 3)


def open_version(p: dict) -> dict | None:
    """Копия POI только с данными OSM/Wikidata/Википедии (без 2GIS) или None, если место есть только в 2GIS."""
    if p.get("_only2gis"):
        return None
    q = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v) for k, v in p.items()}
    for f, v in (p.get("_pre2gis") or {}).items():
        q[f] = list(v) if isinstance(v, list) else v
    q["sources"] = [dict(src) for src in p["sources"] if src["name"] != "2gis"]
    if q.get("description_source") == "2gis":
        q["description"], q["description_source"] = f"«{q['name']}».", "template"
    if not q.get("opening_hours"):
        q["opening_hours"] = q["opening_hours_source"] = q["opening_hours_checked_at"] = None
    q.pop("_pre2gis", None)
    return q


def strip_private(p: dict) -> dict:
    return {k: v for k, v in p.items() if not k.startswith("_")}

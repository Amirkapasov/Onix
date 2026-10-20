"""Wikidata SPARQL (CC0) + краткие описания из Википедии (REST API, CC BY-SA).

1) Все объекты с координатами, расположенные в Астане (P131* = Q1520).
2) Сопоставление с OSM: сначала по тегу `wikidata`, иначе нормализованное имя + < 150 м.
   Совпавшим даём русское имя, описание, sitelinks (→ popularity), уточняем категорию по P31.
3) Несовпавшие, но «туристические» по P31 (музей, памятник, театр, парк, мечеть…) — новые POI.
4) Для объектов со статьёй в ruwiki — первые 1–2 предложения из summary (кэш data/raw/wikipedia/).
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse

from common import (ASTANA_WIKIDATA, RAW, TODAY, cached_json, file_mtime_iso, haversine_m, http,
                    in_bbox, log, norm_name, short_hash)

SPARQL = "https://query.wikidata.org/sparql"
LABELS = """
  OPTIONAL { ?item wdt:P31 ?cls . ?cls rdfs:label ?clsLabel FILTER(LANG(?clsLabel) = "en") }
  OPTIONAL { ?item rdfs:label ?ru FILTER(LANG(?ru) = "ru") }
  OPTIONAL { ?item rdfs:label ?kk FILTER(LANG(?kk) = "kk") }
  OPTIONAL { ?item rdfs:label ?en FILTER(LANG(?en) = "en") }
  OPTIONAL { ?item schema:description ?ruDesc FILTER(LANG(?ruDesc) = "ru") }
  OPTIONAL { ?item schema:description ?enDesc FILTER(LANG(?enDesc) = "en") }
  OPTIONAL { ?ruwiki schema:about ?item ; schema:isPartOf <https://ru.wikipedia.org/> }
"""
SELECT = "SELECT ?item ?coord ?sitelinks ?cls ?clsLabel ?ru ?kk ?en ?ruDesc ?enDesc ?ruwiki WHERE {"
# Два лёгких запроса вместо одного тяжёлого (UNION упирался в таймаут 60 с):
QUERIES = {
    # 1) всё, что административно в Астане (P131* = Q1520)
    "wikidata_astana": SELECT + """
  { SELECT ?item ?coord ?sitelinks WHERE {
      ?item wdt:P131* wd:%(qid)s ; wdt:P625 ?coord ; wikibase:sitelinks ?sitelinks . } }
""" % {"qid": ASTANA_WIKIDATA} + LABELS + "}",
    # 2) объекты без P131 в радиусе 18 км от центра, хотя бы с одной статьёй в Википедии
    "wikidata_around": SELECT + """
  { SELECT ?item ?coord ?sitelinks WHERE {
      SERVICE wikibase:around { ?item wdt:P625 ?coord .
        bd:serviceParam wikibase:center "Point(71.43 51.13)"^^geo:wktLiteral ; wikibase:radius "18" . }
      ?item wikibase:sitelinks ?sitelinks . FILTER(?sitelinks > 0) } }
""" + LABELS + "}",
}

# Ключевые слова в английском названии класса P31 → категория. Порядок важен.
CLASS_RULES = [
    (r"observation tower|observation deck|viewpoint", "viewpoint"),
    (r"zoo|aquarium|oceanarium|amusement park|theme park|water park", "kids"),
    (r"museum|planetarium", "museum"),
    (r"gallery|exhibition", "gallery"),
    (r"theat|opera|concert hall|philharmonic|music venue|circus", "theatre"),
    (r"cinema|movie theater", "cinema"),
    (r"mosque|church|cathedral|synagogue|temple|chapel|religious|monastery", "religious"),
    (r"library", "library"),
    (r"shopping|mall", "mall"),
    (r"stadium|arena|sports|velodrome|ice rink", "sport"),
    (r"park|garden|boulevard|arboretum|promenade|embankment", "park"),
    (r"monument|memorial|statue|sculpture|obelisk|stele|bust", "monument"),
    (r"square|plaza|fountain|tower|skyscraper|palace|pyramid|landmark|bridge|arch|pavilion|"
     r"concert|cultural|tourist attraction|building|structure|architectural", "landmark"),
]
# Эти классы не рекомендуем как места прогулки, даже если совпали ключевые слова.
EXCLUDE = re.compile(r"street|avenue|district|neighbo|settlement|village|city|school|universit|college|"
                     r"hospital|clinic|ministry|government|embassy|agency|company|enterprise|station|"
                     r"airport|hotel|residential|office|bank|court|prison|cemetery|bus|railway|road|"
                     r"apartment|power plant|factory|organization|institute|academy|consulate", re.I)
OVERRIDABLE = {"landmark", "monument", "other"}
TYPICAL_MIN = {"museum": 75, "gallery": 45, "theatre": 150, "cinema": 140, "park": 45, "viewpoint": 30,
               "monument": 15, "landmark": 20, "religious": 25, "mall": 90, "kids": 90, "sport": 90,
               "library": 60}
INDOOR = {"museum": True, "gallery": True, "theatre": True, "cinema": True, "religious": True,
          "mall": True, "library": True, "park": False, "monument": False, "viewpoint": None}
CAT_TAGS = {"museum": ["culture", "indoor"], "gallery": ["art", "culture", "indoor"],
            "theatre": ["culture", "indoor"], "park": ["outdoor", "walk", "quiet", "free"],
            "viewpoint": ["view", "photo"], "monument": ["photo", "outdoor", "free"],
            "landmark": ["photo"], "religious": ["quiet", "culture"], "kids": ["kids", "family"],
            "mall": ["indoor", "shopping", "family"], "library": ["quiet", "indoor"]}
LABEL_RU = {"museum": "Музей", "gallery": "Галерея", "theatre": "Театр / концертный зал", "cinema": "Кинотеатр",
            "park": "Парк", "viewpoint": "Смотровая точка", "monument": "Памятник", "landmark": "Достопримечательность",
            "religious": "Религиозный объект", "mall": "Торговый центр", "kids": "Место для детей",
            "sport": "Спортивный объект", "library": "Библиотека"}
WIKI_API = "https://ru.wikipedia.org/w/api.php"
WIKI_BATCH = 20  # максимум для prop=extracts&exintro


def _fetcher(query: str):
    def fetch() -> dict:
        log("  Wikidata SPARQL…")
        raw = http(SPARQL, data={"query": query, "format": "json"},
                   headers={"Accept": "application/sparql-results+json"}, timeout=90, retries=2)
        return json.loads(raw)
    return fetch


def _items(bindings: list[dict]) -> list[dict]:
    """Строки SPARQL → по одному словарю на QID (классы собираем в список)."""
    by: dict[str, dict] = {}
    for b in bindings:
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", b["coord"]["value"])
        if not m:
            continue
        lon, lat = float(m.group(1)), float(m.group(2))
        it = by.setdefault(qid, {"qid": qid, "lat": lat, "lon": lon, "sitelinks": int(b["sitelinks"]["value"]),
                                 "classes": set()})
        for k in ("ru", "kk", "en", "ruDesc", "enDesc", "ruwiki"):
            if k in b and k not in it:
                it[k] = b[k]["value"]
        if "clsLabel" in b:
            it["classes"].add(b["clsLabel"]["value"].lower())
    return [i for i in by.values() if in_bbox(i["lat"], i["lon"])]


def classify(classes: set[str]) -> str | None:
    """Категория по классам P31: нерелевантные классы (улица, школа, отель…) игнорируются,
    из оставшихся берётся самое приоритетное правило."""
    best = None
    for c in classes:
        if EXCLUDE.search(c):
            continue
        for rank, (pat, cat) in enumerate(CLASS_RULES):
            if re.search(pat, c):
                if best is None or rank < best[0]:
                    best = (rank, cat)
                break
    if not best:
        return None
    # «здание» + «школа/больница/офис…» — не достопримечательность, если нет более точного класса
    if best[1] == "landmark" and any(EXCLUDE.search(c) for c in classes):
        return None
    return best[1]


def _wiki_cache_path(title: str):
    d = RAW / "wikipedia"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{short_hash(title)}.json"


def _title(url: str) -> str:
    return urllib.parse.unquote(url.rsplit("/wiki/", 1)[-1]).replace("_", " ")


def prefetch_wiki(urls: list[str], refresh: bool) -> int:
    """Вводные абзацы статей ruwiki пакетами по 20 (MediaWiki Action API, prop=extracts)."""
    titles = [t for t in dict.fromkeys(_title(u) for u in urls)
              if refresh or not _wiki_cache_path(t).exists()]
    n = 0
    for i in range(0, len(titles), WIKI_BATCH):
        chunk = titles[i:i + WIKI_BATCH]
        try:
            obj = json.loads(http(WIKI_API, data={
                "action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1, "redirects": 1,
                "exlimit": WIKI_BATCH, "format": "json", "formatversion": 2, "titles": "|".join(chunk)},
                timeout=60, retries=3))
        except Exception as e:
            log(f"  Wikipedia: пакет пропущен ({e})")
            continue
        n += 1
        q = obj.get("query", {})
        alias = {r["to"]: r["from"] for r in q.get("redirects", []) + q.get("normalized", [])}
        for page in q.get("pages", []):
            src = page.get("title", "")
            while src in alias:
                src = alias[src]
            _wiki_cache_path(src).write_text(json.dumps({"extract": page.get("extract", "")}, ensure_ascii=False),
                                             encoding="utf-8")
        time.sleep(1.0)
    return n


def _wiki_summary(url: str) -> str | None:
    path = _wiki_cache_path(_title(url))
    if not path.exists():
        path = _wiki_cache_path(urllib.parse.unquote(url.rsplit("/wiki/", 1)[-1]))  # старый формат кэша
        if not path.exists():
            return None
    obj = json.loads(path.read_text(encoding="utf-8"))
    text = clean_text(obj.get("extract") or "")
    if not text or obj.get("type") == "disambiguation" or "может означать" in text[:200]:
        return None
    sents = re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z«])", text)
    out = ""
    for s in sents[:3]:
        if out and len(out) + len(s) > 320:
            break
        out = (out + " " + s).strip()
    return out[:400] or None


def clean_text(text: str) -> str:
    text = text.replace("\u0301", "").split("\n")[0].strip()  # ударения, только первый абзац
    text = re.sub(r"\s*\([^()]*\)", "", text)  # скобки с транскрипциями/датами
    return re.sub(r"\s+([,.;:])", r"\1", re.sub(r"\s{2,}", " ", text)).strip()


def clean_name(name: str) -> str:
    return re.sub(r"\s*\([^()]*\)\s*$", "", name.replace("\u0301", "")).strip()


def _description(it: dict) -> tuple[str, str] | None:
    if it.get("ruDesc"):
        name = it.get("ru") or it.get("en")
        d = it["ruDesc"].strip().rstrip(".")
        return f"{name} — {d}.", "wikidata"
    return None


def _apply(p: dict, it: dict, fetched_at: str) -> None:
    p["_wikidata"] = it["qid"]
    p["_sitelinks"] = it["sitelinks"]
    i18n = p["name_i18n"]
    for lang in ("ru", "kk", "en"):
        if it.get(lang) and lang not in i18n:
            i18n[lang] = it[lang]
    # Название по-русски: если в OSM только казахское `name`, берём ru-метку Wikidata.
    if it.get("ru") and not p.get("_has_name_ru"):
        p["name"] = it["ru"]
        i18n["ru"] = it["ru"]
    cat = classify(it["classes"])
    if cat and p["category"] in OVERRIDABLE and cat not in OVERRIDABLE | {"mall", "sport"}:
        p["category"] = cat
        p["typical_visit_min"] = TYPICAL_MIN.get(cat, p["typical_visit_min"])
        if INDOOR.get(cat) is not None:
            p["indoor"] = INDOOR[cat]
    if cat == "viewpoint":
        p["tags"] = sorted(set(p["tags"]) | {"view", "photo"})
    p["tags"] = sorted(set(p["tags"]) | {"sight"})
    if p["description_source"] == "template":
        desc = None
        if it.get("ruwiki"):
            s = _wiki_summary(it["ruwiki"])
            if s:
                desc = (s, "wikipedia")
        desc = desc or _description(it)
        if desc:
            p["description"], p["description_source"] = desc
    p["sources"].append({"name": "wikidata", "url": f"https://www.wikidata.org/wiki/{it['qid']}", "fetched_at": fetched_at})
    if it.get("ruwiki") and p["description_source"] == "wikipedia":
        p["sources"].append({"name": "wikipedia", "url": it["ruwiki"], "fetched_at": fetched_at})


def _new_poi(it: dict, cat: str, fetched_at: str) -> dict | None:
    name = it.get("ru") or it.get("en") or it.get("kk")
    if not name or re.fullmatch(r"Q\d+", name):
        return None
    p = {
        "id": f"wikidata:{it['qid']}", "name": name, "name_i18n": {},
        "lat": round(it["lat"], 6), "lon": round(it["lon"], 6), "category": cat,
        "tags": sorted(set(CAT_TAGS.get(cat, [])) | {"sight"}),
        "description": f"{LABEL_RU.get(cat, 'Место')} «{name}».", "description_source": "template",
        "address": None, "opening_hours": None, "opening_hours_source": None, "opening_hours_checked_at": None,
        "phone": None, "website": None, "rating": None, "rating_count": None, "popularity": None,
        "indoor": INDOOR.get(cat), "wheelchair": "unknown",
        "kid_friendly": True if cat in ("kids", "park") else None,
        "price_level": 0 if cat in ("park", "monument") else None,
        "typical_visit_min": TYPICAL_MIN.get(cat, 30), "sources": [], "data_quality": None,
        "updated_at": TODAY, "_has_name_ru": bool(it.get("ru")),
    }
    _apply(p, it, fetched_at)
    return p


def enrich(pois: list[dict], refresh: bool = False) -> str:
    bindings, fetched_at, failed = [], TODAY, []
    for name, query in QUERIES.items():
        try:
            obj, path = cached_json(name, _fetcher(query), refresh)
            bindings += obj["results"]["bindings"]
            fetched_at = file_mtime_iso(path)
        except Exception as e:  # один из запросов упал — работаем с тем, что есть
            failed.append(name)
            log(f"  {name}: {e}")
    if not bindings:
        raise RuntimeError("Wikidata недоступна")
    items = _items(bindings)
    log(f"  Wikidata: {len(items)} объектов с координатами в Астане")
    by_qid = {p["_wikidata"]: p for p in pois if p.get("_wikidata")}
    by_name: dict[str, list[dict]] = {}
    for p in pois:
        for n in {p["name"], *p["name_i18n"].values()}:
            if norm_name(n):
                by_name.setdefault(norm_name(n), []).append(p)

    for it in items:
        for k in ("ru", "kk", "en"):
            if it.get(k):
                it[k] = clean_name(it[k])
    wiki_req = prefetch_wiki([i["ruwiki"] for i in items if i.get("ruwiki") and
                              (i["qid"] in by_qid or classify(i["classes"]))], refresh)
    matched_tag = matched_name = added = 0
    for it in sorted(items, key=lambda i: -i["sitelinks"]):
        p = by_qid.get(it["qid"])
        if p:
            matched_tag += 1
        else:
            for lang in ("ru", "kk", "en"):
                cands = by_name.get(norm_name(it.get(lang, "")), []) if it.get(lang) else []
                close = [c for c in cands if not c.get("_wikidata") and
                         haversine_m(c["lat"], c["lon"], it["lat"], it["lon"]) < 150]
                if close:
                    p = close[0]
                    matched_name += 1
                    break
        if p:
            _apply(p, it, fetched_at)
            continue
        cat = classify(it["classes"])
        if cat:
            np_ = _new_poi(it, cat, fetched_at)
            if np_:
                pois.append(np_)
                added += 1
    msg = (f"ok: {len(items)} объектов; совпало по тегу {matched_tag}, по имени+150 м {matched_name}; "
           f"добавлено новых {added}; запросов к Wikipedia {wiki_req}"
           + (f"; не получено: {', '.join(failed)}" if failed else ""))
    log("  " + msg)
    return msg

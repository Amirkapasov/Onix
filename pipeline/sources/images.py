"""Фото мест только с Wikimedia Commons (свободные лицензии), без скачивания файлов — только ссылки.

Откуда берём имя файла:
  1) Wikidata P18 (для мест с wikidata);
  2) OSM wikimedia_commons=File:… (или Category:… — тогда первый файл категории);
  3) OSM image=, если ссылка ведёт на Commons/upload.wikimedia.org.
Метаданные — Commons API (prop=imageinfo, extmetadata), пакетами по 50 файлов, кэш data/raw/commons/.
Берём только CC0, Public domain, CC BY и CC BY-SA; всё остальное → image = null.

Отдельно собирается data/category_photos.json: 1–2 фото на категорию (фолбэк «иллюстрация»)
и 3–5 фото панорамы Астаны под ключом "hero".
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse

from common import DATA, RAW, http, log, short_hash

WD_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
BATCH = 50
THUMB_WIDTH = 640
CACHE = RAW / "commons"

ALLOWED_LICENSE = re.compile(r"^(cc0|cc-zero|public domain|pd\b.*|cc[ -]by(-sa)?( \d(\.\d)?)?( [a-z]{2,})?)$", re.I)
IMAGE_EXT = re.compile(r"\.(jpe?g|png|webp|tiff?)$", re.I)

# Фолбэк-фото по категориям. Сначала — фото самих мест Астаны этой категории (POI_FIRST),
# затем отобранные вручную файлы Commons (просмотрены глазами: поиск по Commons выдаёт много мусора).
# Лицензия и наличие каждого файла всё равно проверяются через API при каждой сборке.
POI_FIRST = {"park", "museum", "monument", "theatre", "religious", "sport", "viewpoint", "mall"}
CURATED = {
    "park": ["File:Fountain in Lovers Park.jpg"],
    "landmark": ["File:Astana-2021-10 - 25.jpg", "File:Central Downtown Astana pamorama.jpg"],
    "mall": ["File:Keruen mall, interior, Astana, 2026.jpg"],
    "viewpoint": ["File:View from Bayterek tower.jpg"],
    "cafe": ["File:Starbucks coffee shop interior design.jpg", "File:Bauirsaq with candy.jpg"],
    "restaurant": ["File:Darijani, Astana (LRM 20240819 173519).jpg",
                   "File:Daredzhani, Astana (20240819-2024-08-19 14.35.19).jpg"],
    "wellness": ["File:Indoor pool of spa with open door at Amantaka luxury Resort & Hotel in Luang Prabang Laos.jpg"],
    "playground": ["File:Ma Wan Children's Playground 01.jpg"],
    "kids": ["File:Tung Tao Court Indoor playground 201407.jpg", "File:Siu Sai Wan Complex Children Play Room 2015.jpg"],
    "cinema": ["File:Cinema Roma interiör.jpg", "File:Interior of hall at CInema Museum, Kennington Lambeth.jpg"],
    "gallery": ["File:Interior of Christchurch Art Gallery, New Zealand 04.jpg"],
    "library": ["File:Liverpool Central Library Picton Reading Room - panoramio.jpg",
                "File:Graz University-Library reading-room.jpg"],
    "entertainment": ["File:Splitz bowling alley, Jacksonville.jpg", "File:Escape Room by Midgaard Event.jpg"],
    "supermarket": ["File:Molmart, Astana, 2026.jpg", "File:Cheeses, Galmart, Keruen mall, Astana, 2026.jpg"],
    "convenience": ["File:Convenience store. Tetrikhevi.jpg"],
    "clothes": ["File:Jacadi shop, Keruen mall, Astana, 2026.jpg"],
    "shop": ["File:Keruen mall, interior, Astana, 2026.jpg"],
    "pharmacy": ["File:Конаев, Абая 18а.jpg"],
    "market": ["File:Зелёный базар в Алматы (Казахстан).jpg"],
    "coworking": ["File:Coworking Space in Columbus Ohio.jpg", "File:Coworking space 2026-09-27.jpg"],
    "bar": ["File:Bar in Bristol.jpg"],
    "nightlife": ["File:Night at Esil District, Astana (P1190721).jpg"],
}
HERO = [
    ("Байтерек ночью", "File:Night at Esil District, Astana (P1190721).jpg"),
    ("Хан Шатыр", "File:Khan Shatyr.jpg"),
    ("Панорама центра и набережная Есиля", "File:Central Downtown Astana pamorama.jpg"),
    ("ЭКСПО-2017 сверху", "File:Астана, EXPO-2017 сверху.jpg"),
    ("Есиль зимой", "File:Sunny January Day on Astana's Ishim River (6658586715).jpg"),
]


# ---------- HTTP с кэшем ----------

def _cached(key: str, fetch):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{short_hash(key)}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    obj = fetch()
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    time.sleep(1.0)  # вежливо к API Wikimedia (иначе 429)
    return obj


def _api(url: str, params: dict) -> dict:
    return json.loads(http(url, data={**params, "format": "json", "formatversion": 2}, timeout=60, retries=3))


# ---------- имена файлов ----------

def _file_title(value: str | None) -> str | None:
    """'File:X.jpg' | URL Commons/upload → 'File:X.jpg'."""
    if not value:
        return None
    v = value.strip()
    if v.startswith("File:"):
        return v.split(";")[0]
    m = re.search(r"commons\.wikimedia\.org/wiki/(File:[^?#]+)", v)
    if m:
        return urllib.parse.unquote(m.group(1)).replace("_", " ")
    m = re.search(r"upload\.wikimedia\.org/wikipedia/commons/(?:thumb/)?[0-9a-f]/[0-9a-f]{2}/([^/?#]+)", v)
    if m:
        return "File:" + urllib.parse.unquote(m.group(1)).replace("_", " ")
    return None


def _p18(qids: list[str]) -> dict[str, str]:
    """qid → 'File:…' из P18, иначе 'Category:…' из P373 (Commons-категория объекта)."""
    out = {}
    qids = sorted(set(qids))
    for i in range(0, len(qids), BATCH):
        chunk = qids[i:i + BATCH]
        obj = _cached("p18:" + "|".join(chunk), lambda c=chunk: _api(WD_API, {
            "action": "wbgetentities", "ids": "|".join(c), "props": "claims"}))
        for qid, ent in (obj.get("entities") or {}).items():
            for claim in (ent.get("claims") or {}).get("P18", []):
                val = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                if val:
                    out[qid] = "File:" + val
                    break
            if qid not in out:
                for claim in (ent.get("claims") or {}).get("P373", []):
                    val = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                    if val:
                        out[qid] = "Category:" + val
                        break
    return out


def _category_first_file(category: str) -> str | None:
    obj = _cached("cat:" + category, lambda: _api(COMMONS_API, {
        "action": "query", "list": "categorymembers", "cmtitle": category, "cmtype": "file", "cmlimit": 10}))
    for m in (obj.get("query") or {}).get("categorymembers", []):
        if IMAGE_EXT.search(m.get("title", "")):
            return m["title"]
    return None


# ---------- метаданные ----------

def _clean_artist(raw: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:120] or "неизвестен"


def imageinfo(titles: list[str]) -> dict[str, dict | None]:
    """title → объект image по контракту (или None, если лицензия не подходит / файла нет)."""
    out: dict[str, dict | None] = {}
    titles = sorted(set(t for t in titles if t))
    for i in range(0, len(titles), BATCH):
        chunk = titles[i:i + BATCH]
        obj = _cached("ii:" + "|".join(chunk), lambda c=chunk: _api(COMMONS_API, {
            "action": "query", "titles": "|".join(c), "prop": "imageinfo",
            "iiprop": "url|extmetadata|size", "iiurlwidth": THUMB_WIDTH}))
        q = obj.get("query") or {}
        alias = {n["to"]: n["from"] for n in q.get("normalized", []) + q.get("redirects", [])}
        for page in q.get("pages", []):
            src = alias.get(page.get("title"), page.get("title"))
            info = (page.get("imageinfo") or [None])[0]
            out[src] = out[page.get("title")] = _to_image(info) if info else None
    return out


def _to_image(info: dict) -> dict | None:
    meta = info.get("extmetadata") or {}
    lic = (meta.get("LicenseShortName") or {}).get("value", "").strip()
    lic_plain = html.unescape(re.sub(r"<[^>]+>", "", lic)).strip()
    if not ALLOWED_LICENSE.match(lic_plain) or re.search(r"\b(nc|nd)\b", lic_plain, re.I):
        return None
    url = info.get("url", "").split("?")[0]  # Commons дописывает ?utm_source=…
    if not IMAGE_EXT.search(url):
        return None
    lic_url = (meta.get("LicenseUrl") or {}).get("value") or None
    return {
        "url": url,
        "thumb_url": (info.get("thumburl") or "").split("?")[0] or None,
        "page_url": (info.get("descriptionurl") or url).split("?")[0],
        "author": _clean_artist((meta.get("Artist") or {}).get("value", "")),
        "license": lic_plain,
        "license_url": lic_url,
        "source": "wikimedia_commons",
        "_w": info.get("width") or 0, "_h": info.get("height") or 0,
    }


def public(img: dict | None) -> dict | None:
    return {k: v for k, v in img.items() if not k.startswith("_")} if img else None


# ---------- POI ----------

def attach(pois: list[dict]) -> str:
    qids = [p["_wikidata"] for p in pois if p.get("_wikidata")]
    p18 = _p18(qids)
    title_of: dict[str, str] = {}
    for p in pois:
        t = p18.get(p.get("_wikidata") or "")
        if t and t.startswith("Category:"):
            t = _category_first_file(t)
        if not t:
            c = p.get("_commons") or ""
            t = _file_title(c) or (_category_first_file(c.split(";")[0]) if c.startswith("Category:") else None)
        if not t:
            t = _file_title(p.get("_image"))
        if t:
            title_of[p["id"]] = t
    infos = imageinfo(list(title_of.values()))
    with_img = rejected = 0
    for p in pois:
        img = infos.get(title_of.get(p["id"], ""))
        if p["id"] in title_of and not img:
            rejected += 1
        p["_image_full"] = img
        p["image"] = public(img)
        with_img += bool(img)
    msg = f"ok: файлов найдено {len(title_of)}, с подходящей лицензией {with_img}, отклонено {rejected}"
    log("  Commons: " + msg)
    return msg


# ---------- фолбэк по категориям и обложка ----------

def _good(img: dict | None, min_w: int = 1000) -> bool:
    return bool(img) and img["_w"] >= min_w and img["_w"] >= img["_h"]  # горизонтальные и не мелкие


def build_category_photos(pois: list[dict]) -> str:
    out: dict = {"_comment": "Фолбэк-фото по категориям для мест без своего фото (помечать «иллюстрация») "
                             "и обложка (hero). Все — Wikimedia Commons, свободные лицензии; атрибуция обязательна. "
                             "astana=true — снято в Астане.",
                 "categories": {}, "hero": []}
    by_cat: dict[str, list[dict]] = {}
    for p in sorted(pois, key=lambda p: -(p.get("popularity") or 0)):
        img = p.get("_image_full")
        if p["category"] in POI_FIRST and _good(img):
            by_cat.setdefault(p["category"], []).append(
                {**public(img), "depicts": p["name"], "poi_id": p["id"], "astana": True})
    infos = imageinfo([t for ts in CURATED.values() for t in ts] + [t for _, t in HERO])
    missing = []
    for cat in sorted(set(by_cat) | set(CURATED)):
        picked = by_cat.get(cat, [])[:1]
        for t in CURATED.get(cat, []):
            img = infos.get(t)
            if not img:
                missing.append(t)
            elif len(picked) < 2 and all(x["url"] != img["url"] for x in picked):
                name = t[5:].rsplit(".", 1)[0]
                picked.append({**public(img), "depicts": name, "astana": bool(re.search(r"astana|астан|nur-sultan", name, re.I))})
        picked += by_cat.get(cat, [])[1:2 - len(picked) + 1] if len(picked) < 2 else []
        if picked:
            out["categories"][cat] = picked[:2]
    for label, t in HERO:
        img = infos.get(t)
        if img:
            out["hero"].append({**public(img), "depicts": label, "astana": True})
        else:
            missing.append(t)
    (DATA / "category_photos.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    msg = f"категорий с фото {len(out['categories'])}, обложек {len(out['hero'])}"
    if missing:
        msg += f"; недоступно/не та лицензия: {len(missing)}"
        log("  нет фото: " + "; ".join(missing))
    log("  category_photos.json: " + msg)
    return msg

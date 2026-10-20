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

# Нейтральные иллюстрации категорий (generic): не изображают конкретное узнаваемое заведение с вывеской.
# Отобраны вручную по контактным листам из поиска Commons (в основном «Quality images»); (файл, подтег).
GENERIC = {
    'cafe': [
        ('File:A cup of coffee in Mohk.jpg', None),
        ('File:Cup of coffee (Serbian cuisine, Grand kava).jpg', None),
        ('File:Espresso Coffee 01.jpg', None),
    ],
    'restaurant': [
        ('File:Baghala polo.jpg', None),
        ('File:Loobia Polo.jpg', None),
        ('File:Bangladeshi Polao 1.jpg', None),
        ('File:Hamburg, Jungfernstieg -- 2016 -- 4182.jpg', None),
    ],
    'bar': [
        ('File:Cocktail-Bar (Kleines Phi) in Hamburg.jpg', None),
        ('File:Casa Classic Cocktail Bar & Jazz Club by Roland Barrera.jpg', None),
        ('File:Interior view of Golden Era Cocktail Lounge in Nevada City.jpg', None),
        ('File:Cure cocktail bar New Orleans 2011.jpg', None),
    ],
    'nightlife': [
        ('File:Long Island City New York May 2015 panorama 3.jpg', None),
        ('File:Melbourne (AU), Melbourne City Centre -- 2019 -- 1493-7.jpg', None),
        ('File:Sydney (AU), Darling Harbour -- 2019 -- 3193-5.jpg', None),
    ],
    'museum': [
        ('File:Hall of Minerals – National Museum in Prague 03.jpg', None),
        ('File:Hall of Minerals – National Museum in Prague 02.jpg', None),
        ('File:Animated lion and African buffalo taxidermy Powell-Cotton Museum, Birchington Kent England.jpg', None),
    ],
    'gallery': [
        ('File:Exhibition views with visitors – ART FUSION BASEL 2022 05.jpg', None),
        ('File:Exhibition views with visitors – ART FUSION BASEL 2022 06.jpg', None),
        ('File:Exhibition views with visitors – ART FUSION BASEL 2022 08.jpg', None),
    ],
    'theatre': [
        ('File:Grand Théâtre Tours - Scène et parterre.jpg', None),
        ('File:War Memorial Opera House auditorium chandelier.jpg', None),
        ('File:War Memorial Opera House auditorium upper levels.jpg', None),
    ],
    'cinema': [
        ('File:Lichtburg-Essen-Kinosaal-2025.jpg', None),
        ('File:Columbia City Cinema main hall.jpg', None),
        ('File:Luxury Movie Theater Seats.jpg', None),
        ('File:4DX seats in cinema (motion and environmental effects synced with the on-screen action) bench rows in a movie theater hall Kinostoler kinosal Kilden kino Tønsberg, Norway 2023 IMG 7849.jpg', None),
    ],
    'park': [
        ('File:A garden path and lawn Gibberd Garden Essex England.JPG', None),
        ('File:Tübingen - Neckarinsel - Blick entlang Neckar im Herbst.jpg', None),
        ('File:Park Środula, Sosnowiec, Jesień 2021.jpg', None),
        ('File:Dülmen, Merfeld, Von-Galen-Park -- 2013 -- 2367.jpg', None),
        ('File:Viru Bog at winter.jpg', None),
    ],
    'viewpoint': [
        ('File:View of Fukuoka City from West Observation Deck of Minami Park (northeast).jpg', None),
        ('File:View of Fukuoka City from West Observation Deck of Minami Park (north).jpg', None),
        ('File:View of Fukuoka City from West Observation Deck of Minami Park (southwest).jpg', None),
        ('File:View from Bayterek tower.jpg', None),
    ],
    'monument': [
        ('File:Dresden, Schloss, Ruhender Hirsch (Dezember 2023).jpg', None),
        ('File:Luxembourg City monument Guillaume II statue 2011.jpg', None),
    ],
    'religious': [
        ('File:Sheikh-Lotf-Allah mosque wall and ceiling 2.jpg', None),
        ('File:Jame mosque of Yazd.jpg', None),
        ('File:Ribbed vault of Jameh Mosque of Isfahan.jpg', None),
        ('File:Ајдар кади џамија, Битола (enterance domes of Hajdar Kadi Mosque, Bitola).jpg', None),
    ],
    'mall': [
        ('File:Bamberg Atrium Rolltreppen-20180417-RM-171311.jpg', None),
        ('File:Villach Warmbad Einkaufszentrum ATRIO 19032015 0900.jpg', None),
        ('File:Villach Warmbad Einkaufszentrum ATRIO 19032015 0904.jpg', None),
        ('File:The Bay Centre, Victoria, British Columbia, Canada 004.jpg', None),
    ],
    'playground': [
        ('File:Spielplatz Volkshain-Stünz – Rutsche.jpg', None),
        ('File:Klettergerüst mit Rutsche vom Spielplatz beim General Kalb Weg München Bild 2 2025-04-13.jpg', None),
        ('File:2025. Torre con tobogán. Parque infantil da Alameda de Compostela. Galiza.jpg', None),
        ('File:2026. Parque infantil de Belvís. Santiago de Compostela. Galiza. 04.jpg', None),
        ('File:Playground swing 03.jpg', None),
    ],
    'kids': [
        ('File:Happy Duck Round The World ball pit at BHG Shangdi (20210813160534).jpg', None),
        ('File:Asobono ball pool.jpg', None),
        ('File:Hometrampoline.jpg', None),
        ('File:Poland 2025 350 Czarna Góra - Colourful Play Area.jpg', None),
    ],
    'entertainment': [
        ('File:Bowling Alley Pelixir Oulu 20150110.JPG', None),
        ('File:The New HUB Bowling Alley (7975562172).jpg', None),
        ('File:Bowling Corner & Billiard interior 01.jpg', None),
        ('File:Château de Malmaison - Salle de billard 001.jpg', None),
        ('File:Le château de Rundal (Rundal Pils) (3).JPG', None),
    ],
    'sport': [
        ('File:Rijksmuseum winter 7441.jpg', None),
        ('File:Outdoor ice rink - Aerial view (1).jpg', None),
        ('File:2026-01-10 Dresdner Eislöwen gegen Eisbären Berlin (DEL Winter Game 2026, Deutsche Eishockey-Liga 2025-26) by Sandro Halank–047.jpg', None),
    ],
    'wellness': [
        ('File:Swimming Pool lanes and starting blocks.jpg', 'pool'),
        ('File:Swimming Pool lanes and starting blocks at AIS.jpg', 'pool'),
        ('File:Gym Dumbbells For Working Out (193383405).jpeg', 'fitness'),
        ('File:Colorful pile of dumbbells at the gym.jpg', 'fitness'),
        ('File:Smoke sauna stove Utsjoki.JPG', 'sauna'),
        ('File:Wood stove of smoke sauna of Kuusijärvi, Kuninkaanmäki, Vantaa, Finland, 2023 April - 2.jpg', 'sauna'),
    ],
    'library': [
        ('File:Bookshelf Prunksaal OeNB Vienna AT matl00786ch.jpg', None),
        ('File:13-11-02-olb-by-RalfR-03.jpg', None),
        ('File:Providence Athenaeum interior 2013.jpg', None),
        ('File:Westmount Public Library by Rodrigo Tetsuo Argenton (03).jpg', None),
    ],
    'coworking': [
        ('File:The Venture Studios Best coworking space in HSR Layout.jpg', None),
        ('File:Cowork Videmonte.jpg', None),
        ('File:Desks in an open office space (Unsplash).jpg', None),
        ('File:Working in open office space (Unsplash).jpg', None),
    ],
    'market': [
        ('File:Fruit Stall in Barcelona Market.jpg', None),
        ('File:Burrabazar Market in Kolkata 09.jpg', None),
        ('File:Gesundes Leben 002 2014 03 19.jpg', None),
    ],
    'supermarket': [
        ('File:Metro (supermarket) 02.jpg', None),
        ('File:Metro (supermarket) 04.jpg', None),
        ('File:IGA store in Quebec, Limoilou 12.jpg', None),
        ('File:IGA store in Quebec, Limoilou 13.jpg', None),
    ],
    'convenience': [
        ('File:Shelves in a Ralphs grocery store.jpg', None),
        ('File:Familymart sunc^n.eko 02.JPG', None),
        ('File:Bento Boxes in Japanese Convenience Store (13539630195).jpg', None),
    ],
    'clothes': [
        ('File:2008 Taipei In Style Outdoor Fashion Show Clothes Racks.jpg', None),
        ('File:Interior sports clothing store Cala Millor.jpg', None),
        ('File:Bespoke Coat Rack.jpg', None),
        ('File:Swastika coat rack.jpg', None),
    ],
    'shop': [
        ('File:Colored pencils chevre.jpg', None),
        ('File:Colouring pencils.jpg', None),
        ('File:Buntstifte -- 2021 -- 9151.jpg', None),
    ],
    'pharmacy': [
        ('File:Brest Greenberg Pharmacy Interior 2024-09-20 3798.jpg', None),
        ('File:Hospital Pharmacy.JPG', None),
        ('File:Sekkisei at a drugstore in Japan.jpg', None),
        ('File:Castellon Pharmacy New Orleans Empty Shelves where TP and Wipes were.jpg', None),
        ('File:Empty shelves in one pharmacy in Suzhou-20220214.jpg', None),
    ],
    'landmark': [
        ('File:Central Downtown Astana pamorama.jpg', None),
        ("File:Sunny January Day on Astana's Ishim River (6658586715).jpg", None),
        ('File:Astana-kazakhstan.JPG', None),
        ('File:Astana-2021-10 - 12.jpg', None),
    ],
}

HERO = [
    ("Байтерек ночью", "File:Night at Esil District, Astana (P1190721).jpg"),
    ("Хан Шатыр", "File:Khan Shatyr.jpg"),
    ("Панорама центра и набережная Есиля", "File:Central Downtown Astana pamorama.jpg"),
    ("ЭКСПО-2017 сверху", "File:Астана, EXPO-2017 сверху.jpg"),
    ("Есиль зимой", "File:Sunny January Day on Astana's Ishim River (6658586715).jpg"),
]


# Главные места без P18 в Wikidata: файл Commons подобран вручную (просмотрен), лицензия проверяется API.
MANUAL_POI_IMAGES = [
    (r"mega silk way", "File:Aĉetcentro SilkWay (Astano) 01.jpg"),
    (r"нур алем|nur alem", 'File:Expo 2017 "Nur Alem" Pavilion Space Exhibition.jpg'),
    (r"shabyt|шабыт", "File:Shabyt Palace.jpg"),
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


SITELINK_WIKIS = {"ruwiki": "ru", "kkwiki": "kk", "enwiki": "en"}


def _p18(qids: list[str], sitelinks: dict | None = None) -> dict[str, str]:
    """qid → 'File:…' из P18, иначе 'Category:…' из P373 (Commons-категория объекта).
    В sitelinks (если передан) складывает qid → [(язык, статья)] для поиска главного фото статьи."""
    out = {}
    qids = sorted(set(qids))
    for i in range(0, len(qids), BATCH):
        chunk = qids[i:i + BATCH]
        obj = _cached("p18sl:" + "|".join(chunk), lambda c=chunk: _api(WD_API, {
            "action": "wbgetentities", "ids": "|".join(c), "props": "claims|sitelinks",
            "sitefilter": "|".join(SITELINK_WIKIS)}))
        for qid, ent in (obj.get("entities") or {}).items():
            if sitelinks is not None:
                sitelinks[qid] = [(SITELINK_WIKIS[k], v["title"]) for k, v in (ent.get("sitelinks") or {}).items()
                                  if k in SITELINK_WIKIS]
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


def _page_images(refs: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """(язык, статья) → 'File:…' — главное изображение статьи Википедии (prop=pageimages)."""
    out: dict[tuple[str, str], str] = {}
    by_lang: dict[str, list[str]] = {}
    for lang, title in set(refs):
        by_lang.setdefault(lang, []).append(title)
    for lang, titles in by_lang.items():
        titles = sorted(set(titles))
        api = f"https://{lang}.wikipedia.org/w/api.php"
        for i in range(0, len(titles), BATCH):
            chunk = titles[i:i + BATCH]
            obj = _cached(f"pi:{lang}:" + "|".join(chunk), lambda c=chunk, a=api: _api(a, {
                "action": "query", "prop": "pageimages", "piprop": "name", "redirects": 1, "titles": "|".join(c)}))
            q = obj.get("query") or {}
            alias = {n["to"]: n["from"] for n in q.get("normalized", []) + q.get("redirects", [])}
            for page in q.get("pages", []):
                if page.get("pageimage"):
                    src = page["title"]
                    while src in alias:
                        src = alias[src]
                    out[(lang, src)] = "File:" + page["pageimage"].replace("_", " ")
    return out


def _wiki_ref(tag: str | None) -> tuple[str, str] | None:
    """OSM wikipedia='ru:Байтерек (монумент)' → ('ru', 'Байтерек (монумент)')."""
    m = re.match(r"^([a-z]{2,3}):(.+)$", (tag or "").strip())
    return (m.group(1), m.group(2).replace("_", " ")) if m else None


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
    sitelinks: dict[str, list] = {}
    p18 = _p18(qids, sitelinks)
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
        if not t and "must_see" in p["tags"]:
            t = next((f for rx, f in MANUAL_POI_IMAGES if re.search(rx, p["name"], re.I)), None)
        if t:
            title_of[p["id"]] = t

    # Главное изображение статьи Википедии — для мест со статьёй, но без P18/тегов Commons
    want: dict[str, list[tuple[str, str]]] = {}
    for p in pois:
        if p["id"] in title_of:
            continue
        refs = list(sitelinks.get(p.get("_wikidata") or "", []))
        if (r := _wiki_ref(p.get("_wikipedia"))):
            refs.append(r)
        if refs:
            want[p["id"]] = sorted(refs, key=lambda r: ["ru", "kk", "en"].index(r[0]) if r[0] in ("ru", "kk", "en") else 9)
    pi = _page_images([r for refs in want.values() for r in refs])
    from_wiki = 0
    for pid, refs in want.items():
        t = next((pi[r] for r in refs if r in pi), None)
        if t:
            title_of[pid] = t
            from_wiki += 1
    infos = imageinfo(list(title_of.values()))
    with_img = rejected = 0
    for p in pois:
        img = infos.get(title_of.get(p["id"], ""))
        if p["id"] in title_of and not img:
            rejected += 1
        p["_image_full"] = img
        p["image"] = public(img)
        with_img += bool(img)
    msg = (f"ok: файлов найдено {len(title_of)} (из них по статьям Википедии {from_wiki}), "
           f"с подходящей лицензией {with_img}, отклонено {rejected}")
    log("  Commons: " + msg)
    return msg


# ---------- фолбэк по категориям и обложка ----------

def _good(img: dict | None, min_w: int = 1000) -> bool:
    return bool(img) and img["_w"] >= min_w and img["_w"] >= img["_h"]  # горизонтальные и не мелкие


def build_category_photos(pois: list[dict]) -> str:
    """data/category_photos.json: нейтральные иллюстрации по категориям (generic) и обложка (hero)."""
    out: dict = {"_comment": "Иллюстрации категорий для мест без своего фото (помечать «иллюстрация»): "
                             "generic=true — не конкретное заведение; astana=true — снято в Астане/Казахстане; "
                             "tag — подтип внутри категории (wellness: pool/fitness/sauna). hero — обложка. "
                             "Все фото — Wikimedia Commons, свободные лицензии; атрибуция обязательна.",
                 "categories": {}, "hero": []}
    infos = imageinfo([t for items in GENERIC.values() for t, _ in items] + [t for _, t in HERO])
    missing = []
    for cat, items in GENERIC.items():
        picked = []
        for t, tag in items:
            img = infos.get(t)
            if not img:
                missing.append(t)
                continue
            name = t[5:].rsplit(".", 1)[0]
            entry = {**public(img), "depicts": name, "generic": True,
                     "astana": bool(re.search(r"astana|астан|nur-sultan|kazakhstan|казахстан", name, re.I))}
            if tag:
                entry["tag"] = tag
            picked.append(entry)
        if picked:
            out["categories"][cat] = picked
    for label, t in HERO:
        img = infos.get(t)
        if img:
            out["hero"].append({**public(img), "depicts": label, "astana": True})
        else:
            missing.append(t)
    (DATA / "category_photos.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    n = sum(len(v) for v in out["categories"].values())
    msg = f"generic-фото {n} в {len(out['categories'])} категориях, обложек {len(out['hero'])}"
    if missing:
        msg += f"; недоступно/не та лицензия: {len(missing)}"
        log("  нет фото: " + "; ".join(missing))
    log("  category_photos.json: " + msg)
    return msg

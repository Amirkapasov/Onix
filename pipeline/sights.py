"""Что считать достопримечательностью, а что — учреждением.

Объекты с тегом wikidata в OSM и объекты Wikidata раньше становились landmark автоматически,
из-за чего в «главные места» попадали министерства, суды, архивы и жилые комплексы.
Теперь:
  - учреждения (по тегам OSM office/government/diplomatic/amenity, классам P31 Wikidata и названию)
    → category "other" + тег "institution" (в досуговые запросы не попадают);
  - вокзалы и аэропорт → "other" + "transport";
  - главные туристические места (белый список ниже) остаются достопримечательностями и
    получают тег "must_see" — буст popularity, чтобы на «главное в городе» шли первыми.
"""
from __future__ import annotations

import re

SIGHT_CATEGORIES = {"landmark", "monument", "other", "viewpoint"}

# Главные места Астаны, которые реально осматривают туристы (сверено с сид-базой тимлида).
MUST_SEE = re.compile(
    r"байтерек|бәйтерек|bayterek|baiterek|хан шатыр|khan shatyr|ак ?орда|акорда|ақорда|"
    r"дворец мира и согласия|пирамид|хазрет султан|нур[- ]астана|нур[- ]?алем|nur alem|"
    r"казак ели\b|қазақ елі\b|мангилик ел|мәңгілік ел|триумфальн|дворец независимости|"
    r"астана опера|astana opera|национальный музей|атамекен|водно-зел|нуржол|"
    r"ботанический сад|центральный парк|площадь независимости|шабыт|абу насыра|"
    r"дворец школьников|мечеть нурсултан|центральная мечеть|"
    r"музей первого президента|президентский центр|казахстанская игла|"
    r"концертный зал «казахстан»|центральный концертный зал|shabyt|mega silk way",
    re.I)

# OSM-теги, которые означают учреждение/служебное здание
_OSM_INSTITUTION = {
    "office": None, "government": None, "diplomatic": None,
    "amenity": {"courthouse", "townhall", "embassy", "police", "university", "college", "school",
                "hospital", "clinic", "bank", "post_office", "prison", "kindergarten"},
    "building": {"government", "office", "public", "university", "college", "school", "hospital",
                 "residential", "apartments", "commercial", "train_station", "transportation", "dormitory"},
    "landuse": {"residential", "military"},
    "military": None,
}
# Классы P31 Wikidata (англ. метки)
_WD_INSTITUTION = re.compile(
    r"ministry|government|parliament|legislat|court|archive|embassy|consulate|agency|"
    r"headquarters|office building|bank|universit|college|school|academy|hospital|clinic|"
    r"residential|apartment|housing|condominium|business cent|company|organization|"
    r"railway station|airport|police|prison|military unit", re.I)
# Названия-маркеры учреждений (на случай, когда теги/классы молчат)
_NAME_INSTITUTION = re.compile(
    r"министерств|ministry|архив|суд\b|верховный суд|конституционный суд|сенат|мажилис|парламент|"
    r"правительств|акимат|посольств|консульств|embassy|прокуратур|комитет|агентств|департамент|"
    r"главный корпус|университет|академи|колледж|школа\b|больниц|поликлиник|банк\b|"
    r"\bжк\b|жилой комплекс|квартал\b|grand alatau|офис|бизнес-центр|business center|"
    r"tower$|тауэр", re.I)
_NAME_TRANSPORT = re.compile(r"вокзал|аэропорт|airport|\bстанция|\bбекеті?\b|әуежай", re.I)


def osm_institution(tags: dict) -> bool:
    for k, vals in _OSM_INSTITUTION.items():
        v = tags.get(k)
        if v and (vals is None or v in vals):
            return True
    return False


def wd_institution(classes) -> bool:
    return any(_WD_INSTITUTION.search(c) for c in classes or ())


def _names(p: dict) -> str:
    return " | ".join({p["name"], *p.get("name_i18n", {}).values()})


def apply(pois: list[dict]) -> dict[str, int]:
    stats = {"institution": 0, "transport": 0, "must_see": 0}
    for p in pois:
        names = _names(p)
        tags = set(p["tags"])
        if p["category"] in SIGHT_CATEGORIES and ("transport" in tags or _NAME_TRANSPORT.search(names)):
            p["category"] = "other"
            p["tags"] = sorted((tags - {"sight", "photo", "free", "must_see"}) | {"transport"})
            stats["transport"] += 1
            continue
        if MUST_SEE.search(names) and p["category"] not in ("cafe", "restaurant", "bar", "shop", "convenience",
                                                            "supermarket", "pharmacy", "clothes"):
            tags |= {"must_see", "sight"}
            stats["must_see"] += 1
            if p["category"] in ("other", "entertainment"):
                p["category"] = "landmark"  # Дворец мира и согласия, Дворец Независимости — это осматривают
            p["tags"] = sorted(tags)
            continue
        if p["category"] not in SIGHT_CATEGORIES:
            continue
        if "transport" in tags or _NAME_TRANSPORT.search(names):
            p["category"] = "other"
            p["tags"] = sorted((tags - {"sight", "photo", "free"}) | {"transport"})
            stats["transport"] += 1
        elif p.get("_osm_institution") or wd_institution(p.get("_wd_classes")) or _NAME_INSTITUTION.search(names):
            p["category"] = "other"
            p["tags"] = sorted((tags - {"sight", "photo", "free"}) | {"institution"})
            p["kid_friendly"] = None
            p["price_level"] = None
            stats["institution"] += 1
    return stats

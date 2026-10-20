"""Резерв из data/seed/pois_seed.json (ручная база координатора, только чтение).

Сид-точка добавляется, только если автоматические источники её не нашли:
нет объекта с общим значимым словом в названии ближе 400 м. Так ключевые места
(например, «Нур Алем», которого нет ни в OSM-выборке, ни с координатами в Wikidata)
не теряются, а дублей с OSM не возникает.
"""
from __future__ import annotations

import json
import re

from common import DATA, haversine_m, log, norm_name

SEED = DATA / "seed" / "pois_seed.json"
STOP = {"монумент", "трц", "тц", "музей", "мечеть", "вид", "площади", "республики", "казахстан",
        "астаны", "астана", "экспо", "имени"}


def _tokens(name: str) -> set[str]:
    return {t for t in norm_name(name).split() if len(t) >= 3 and t not in STOP}


def _covered(seed: dict, pois: list[dict]) -> dict | None:
    st = _tokens(seed["name"])
    for p in pois:
        if haversine_m(seed["lat"], seed["lon"], p["lat"], p["lon"]) > 400:
            continue
        names = {p["name"], *p.get("name_i18n", {}).values()}
        if any(st & _tokens(n) for n in names):
            return p
    return None


def merge(pois: list[dict]) -> str:
    if not SEED.exists():
        return "нет data/seed/pois_seed.json"
    seeds = json.loads(SEED.read_text(encoding="utf-8"))
    added = []
    renamed = 0
    for s in seeds:
        hit = _covered(s, pois)
        if hit:
            # сид — выверенные русские названия ключевых мест: «Монумент «Байтерек»» вместо «Бәйтерек»
            if hit["name"] != s["name"]:
                if re.search("[әөүұқғңһі]", hit["name"].lower()):
                    hit["name_i18n"].setdefault("kk", hit["name"])
                hit["name"] = s["name"]
                hit["name_i18n"]["ru"] = s["name"]
                renamed += 1
            continue
        p = dict(s)
        p["tags"] = list(p.get("tags", []))
        if p["category"] == "other" and re.search(r"аэропорт|вокзал", p["name"].lower()):
            p["tags"].append("transport")
        p.setdefault("name_i18n", {"ru": p["name"]})
        p["_sitelinks"] = 0
        p["_seed_popularity"] = s.get("popularity")
        pois.append(p)
        added.append(s["id"])
    log(f"  сид: добавлено {len(added)} из {len(seeds)} ({', '.join(added) or '—'})")
    return (f"ok: добавлено {len(added)} из {len(seeds)} (остальные уже найдены автоматически), "
            f"русское название из сида у {renamed}")

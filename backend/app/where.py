"""«Где я»: ближайший ориентир и адрес по НАШЕЙ базе мест — координаты никуда не отправляются."""
from __future__ import annotations

import re

from . import geo
from .data import store
from .guards import core_name, is_generic_name
from .needs import SHOP_CATEGORIES
from .rank import is_institution

LANDMARK_CATS = {"landmark", "monument", "viewpoint", "mall", "park", "museum", "theatre", "religious", "entertainment"}
LANDMARK_RADIUS_M = 400
ADDRESS_RADIUS_M = 150
_KK = re.compile(r"[әғқңөұүһі]", re.I)


def _is_landmark(p: dict) -> bool:
    if is_generic_name(p.get("name", "")) or is_institution(p) or p.get("category") in SHOP_CATEGORIES:
        return False
    return p.get("category") in LANDMARK_CATS or (p.get("popularity") or 0) >= 0.5


def where(lat: float, lon: float, lang: str = "ru") -> dict:
    lat, lon = round(lat, 3), round(lon, 3)  # огрубление ~100 м и здесь
    landmark, best = None, -1e9
    addr_cands: list[tuple[float, str]] = []
    for p in store.get():
        d = geo.haversine_m(lat, lon, p["lat"], p["lon"])
        if d <= LANDMARK_RADIUS_M and _is_landmark(p):
            score = (p.get("popularity") or 0) - d / 1000  # известное и близкое
            if score > best:
                landmark, best = p, score
        if d <= ADDRESS_RADIUS_M and p.get("address"):
            addr_cands.append((d, p["address"].strip()))
    address = None
    if addr_cands:
        addr_cands.sort()
        nearest = addr_cands[0][0]
        same_script = [a for d, a in addr_cands if d <= nearest + 40 and bool(_KK.search(a)) == (lang == "kk")]
        address = same_script[0] if same_script else addr_cands[0][1]
    name = None
    if landmark:
        i18n = (landmark.get("name_i18n") or {}).get(lang)
        name = core_name(i18n or landmark["name"])
    if name and address:
        label = {"ru": f"у «{name}», {address}", "en": f"near {name}, {address}", "kk": f"«{name}» маңы, {address}"}[lang]
    elif name:
        label = {"ru": f"у «{name}»", "en": f"near {name}", "kk": f"«{name}» маңы"}[lang]
    elif address:
        label = address
    else:
        label = f"≈ {lat:.2f}, {lon:.2f}"
    return {"label": label, "landmark": name, "address": address, "precision_m": 100}

"""Отчёт data/stats.md (идёт в слайды): полная база (с 2GIS) и открытая выгрузка (OSM + Wikidata)."""
from __future__ import annotations

import re
from collections import Counter

from common import DATA, NOW, haversine_m

BAITEREK = (51.1283, 71.4305)
MEGA = (51.0890, 71.4100)
EXPO = (51.0898, 71.4159)
KNOWN = ["Байтерек", "Хан Шатыр", "Mega Silk Way", "Нур Алем", "Национальный музей"]


def _text(p):
    return (p["name"] + " " + p["description"]).lower()


def _has(p, tags=(), rx=None, cats=()):
    if p["category"] in cats or set(tags) & set(p["tags"]):
        return True
    return bool(rx and re.search(rx, _text(p)))


# Те же правила, что в проверке релевантности Агента 4 (eval): категория wellness без подтега не засчитывается.
CHECKS_3KM = {
    "бассейн": lambda p: _has(p, ("pool", "swimming", "swimming_pool", "sport:swimming", "water_park"),
                              r"бассейн|аквапарк|\bpool\b|swim"),
    "фитнес": lambda p: _has(p, ("fitness", "gym", "sport:fitness"), r"фитнес|\bgym\b|тренаж"),
    "спа/сауна": lambda p: _has(p, ("sauna", "spa", "bath", "banya", "hammam"), r"сауна|\bспа\b|баня"),
    "боулинг": lambda p: _has(p, ("bowling",), r"боулинг|bowling"),
    "каток": lambda p: _has(p, ("ice", "skating"), r"каток"),
    "музей": lambda p: p["category"] == "museum",
    "кино": lambda p: p["category"] == "cinema",
}
CHECKS_1500 = {
    "супермаркет": lambda p: p["category"] == "supermarket",
    "Magnum": lambda p: "brand:magnum" in p["tags"] or bool(re.search(r"magnum|магнум", p["name"].lower())),
    "магазин 24/7": lambda p: "24_7" in p["tags"] or p.get("opening_hours") == "24/7",
    "одежда": lambda p: p["category"] == "clothes",
    "канцтовары": lambda p: _has(p, ("stationery",), r"канц"),
    "аптека": lambda p: p["category"] == "pharmacy",
}


def _pct(n, total):
    return f"{(100 * n / total):.0f}% ({n})" if total else "—"


def _near(pois, pt, r):
    return [p for p in pois if haversine_m(pt[0], pt[1], p["lat"], p["lon"]) <= r]


def _fields(pois):
    t = len(pois)
    return {
        "Всего POI": str(t),
        "Часы работы": _pct(sum(1 for p in pois if p.get("opening_hours")), t),
        "Рейтинг": _pct(sum(1 for p in pois if p.get("rating") is not None), t),
        "Реальное описание (не шаблон)": _pct(sum(1 for p in pois if p["description_source"] != "template"), t),
        "Контакты (телефон/сайт)": _pct(sum(1 for p in pois if p.get("phone") or p.get("website")), t),
        "Доступность для колясок известна": _pct(sum(1 for p in pois if p["wheelchair"] != "unknown"), t),
        "Можно в помещении": _pct(sum(1 for p in pois if p.get("indoor")), t),
        "Средний data_quality": f"{sum(p.get('data_quality') or 0 for p in pois) / max(t, 1):.2f}",
    }


def find_known(pois, needle):
    n = needle.lower()
    hits = [p for p in pois if n in p["name"].lower() or any(n in v.lower() for v in p.get("name_i18n", {}).values())]
    return sorted(hits, key=lambda p: -(p.get("popularity") or 0))[:1]


def check_rows(full, open_, checks, radius):
    rows = []
    for label, fn in checks.items():
        cells = []
        for pt in (BAITEREK, MEGA):
            nf = sum(1 for p in _near(full, pt, radius) if fn(p))
            no = sum(1 for p in _near(open_, pt, radius) if fn(p))
            cells.append(f"{'✅' if nf else '❌'} {nf} / {no}")
        rows.append(f"| {label} | {cells[0]} | {cells[1]} |")
    return rows


def write(full: list[dict], open_: list[dict], meta: dict) -> str:
    ff, fo = _fields(full), _fields(open_)
    cf, co = Counter(p["category"] for p in full), Counter(p["category"] for p in open_)
    L = [
        "# Статистика датасета POI Астаны",
        "",
        f"- Дата сборки: **{NOW.strftime('%Y-%m-%d %H:%M UTC')}** · время работы пайплайна: **{meta['elapsed_s']:.0f} с**",
        "- Команда: `python pipeline/run_all.py`",
        f"- Отброшено невалидных: {meta['invalid']} · слито дублей: {meta['duplicates']} · "
        f"невалидных строк часов работы: {len(meta['bad_hours'])} · валидация: `{meta['validator']}` "
        "по `contracts/poi.schema.json`",
        "- **Полная база** (`data/pois.json`, OSM + Wikidata + 2GIS) — только для локального запуска и деплоя, "
        "в репозиторий не входит (условия 2GIS). **Открытая выгрузка** (`data/pois_open.json`) — OSM + Wikidata/Википедия.",
        "",
        "## Полнота полей",
        "",
        "| Поле | Полная база | Открытая выгрузка |",
        "|---|---|---|",
    ]
    L += [f"| {k} | {ff[k]} | {fo[k]} |" for k in ff]
    L += ["", "## По категориям", "", "| Категория | Полная база | Открытая выгрузка |", "|---|---|---|"]
    L += [f"| {c} | {n} | {co.get(c, 0)} |" for c, n in cf.most_common()]

    src_f = Counter(s["name"] for p in full for s in p["sources"])
    src_o = Counter(s["name"] for p in open_ for s in p["sources"])
    L += ["", "## Источники (объектов с данными источника)", "", "| Источник | Полная база | Открытая выгрузка |",
          "|---|---|---|"]
    L += [f"| {s} | {n} | {src_o.get(s, 0)} |" for s, n in src_f.most_common()]
    desc = Counter(p["description_source"] for p in full)
    L += ["", "Источник описаний (полная база): " + ", ".join(f"{k} — {v}" for k, v in desc.most_common())]
    L += ["", "Статус источников в этом прогоне:", ""]
    L += [f"- **{k}**: {v}" for k, v in meta["source_status"].items()]

    L += ["", "## Проверки покрытия", "",
          "Ячейка: найдено мест в полной базе / в открытой выгрузке. Правила совпадают с eval (Агент 4).", "",
          "**Радиус 3 км**", "", "| Запрос | От Байтерека | От Mega Silk Way |", "|---|---|---|"]
    L += check_rows(full, open_, CHECKS_3KM, 3000)
    L += ["", "**Радиус 1,5 км (повседневные магазины)**", "", "| Запрос | От Байтерека | От Mega Silk Way |",
          "|---|---|---|"]
    L += check_rows(full, open_, CHECKS_1500, 1500)

    L += ["", "**Радиус 1 км (сценарии прогулки)**", "",
          "| Точка | Всего | Кафе/рестораны | Парки/прогулки | Для детей |", "|---|---|---|---|---|"]
    for name, pt in (("Mega Silk Way", MEGA), ("ЭКСПО / Нур Алем", EXPO), ("Байтерек", BAITEREK)):
        near = _near(full, pt, 1000)
        L.append(f"| {name} | {len(near)} | {sum(p['category'] in ('cafe', 'restaurant') for p in near)} | "
                 f"{sum(p['category'] in ('park', 'viewpoint', 'monument', 'landmark') for p in near)} | "
                 f"{sum(bool(p.get('kid_friendly')) and p['category'] in ('playground', 'kids', 'park', 'museum', 'mall', 'cinema') for p in near)} |")

    L += ["", "## Известные места", ""]
    for k in KNOWN:
        hits = find_known(full, k)
        if hits:
            h = hits[0]
            L.append(f"- {k}: ✅ `{h['id']}` «{h['name']}» ({h['lat']:.4f}, {h['lon']:.4f}), {h['category']}")
        else:
            L.append(f"- {k}: ❌ не найдено")

    if meta["bad_hours"]:
        L += ["", f"## Невалидные строки часов работы ({len(meta['bad_hours'])}, заменены на null)", ""]
        L += [f"- `{i}` {n}: `{h}`" for i, n, h in meta["bad_hours"][:30]]
        if len(meta["bad_hours"]) > 30:
            L.append(f"- … и ещё {len(meta['bad_hours']) - 30}")
    if meta["invalid_list"]:
        L += ["", "## Невалидные объекты (не попали в базу)", ""]
        L += [f"- `{i}`: {e}" for i, e in meta["invalid_list"][:30]]

    L += ["", "## Лицензии", "", "См. `data/LICENSE_DATA.md`: OpenStreetMap — ODbL 1.0, Wikidata — CC0, "
          "Википедия — CC BY-SA 4.0; данные 2GIS в репозиторий не входят.", ""]
    text = "\n".join(L)
    (DATA / "stats.md").write_text(text, encoding="utf-8")
    return text

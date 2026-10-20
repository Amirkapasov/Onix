"""Сборка датасета POI Астаны с нуля: `python pipeline/run_all.py`.

Шаги: OSM Overpass → Wikidata (обогащение) → резерв из data/seed/ → 2GIS (если есть TWOGIS_API_KEY)
→ дедупликация → popularity/data_quality → валидация по схеме → data/pois.json + data/stats.md.

Флаги:
  --refresh        перекачать OSM, Wikidata, Википедию (иначе берутся из data/raw/)
  --refresh-2gis   перекачать и ответы 2GIS (тратит лимит ключа)
  --skip-wikidata  без Wikidata
  --skip-2gis      без 2GIS даже при наличии ключа
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA, ensure_utf8_stdout, load_env, log  # noqa: E402
import normalize  # noqa: E402
import stats  # noqa: E402
import validate  # noqa: E402
from sources import osm  # noqa: E402

ORDER = ["id", "name", "name_i18n", "lat", "lon", "category", "tags", "description",
         "description_source", "address", "opening_hours", "opening_hours_source",
         "opening_hours_checked_at", "phone", "website", "rating", "rating_count", "popularity",
         "indoor", "wheelchair", "kid_friendly", "price_level", "typical_visit_min", "sources",
         "data_quality", "updated_at"]


def main() -> int:
    ensure_utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--refresh-2gis", action="store_true")
    ap.add_argument("--osm", choices=["auto", "overpass", "geofabrik"], default="auto",
                    help="источник OSM: auto — Geofabrik, если уже скачан и есть pyosmium, иначе Overpass с откатом")
    ap.add_argument("--skip-wikidata", action="store_true")
    ap.add_argument("--skip-2gis", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    env = load_env()
    status: dict[str, str] = {}

    log("1/5 OSM Overpass")
    elements, osm_date, osm_used = osm.fetch(args.refresh, args.osm)
    bad_hours: list = []
    pois = [p for e in elements if (p := normalize.from_osm(e, osm_date, bad_hours))]
    status["osm"] = f"ok ({osm_used}), {len(elements)} элементов, данные от {osm_date}"
    log(f"  нормализовано: {len(pois)}")

    log("2/5 Дедупликация")
    pois, dups = normalize.dedupe(pois)
    log(f"  слито дублей: {dups}, осталось {len(pois)}")

    log("3/5 Wikidata")
    if args.skip_wikidata:
        status["wikidata"] = "пропущено (--skip-wikidata)"
    else:
        try:
            from sources import wikidata
            status["wikidata"] = wikidata.enrich(pois, args.refresh)
        except Exception as e:  # обогащение не должно ронять сборку
            status["wikidata"] = f"ошибка: {e}"
            log(f"  Wikidata пропущена: {e}")

    log("    Резерв из data/seed/")
    try:
        from sources import seed
        status["seed"] = seed.merge(pois)
    except Exception as e:
        status["seed"] = f"ошибка: {e}"

    log("4/5 2GIS")
    if args.skip_2gis:
        status["2gis"] = "пропущено (--skip-2gis)"
    else:
        try:
            from sources import twogis
            status["2gis"] = twogis.enrich(pois, env, args.refresh_2gis)
        except Exception as e:
            status["2gis"] = f"ошибка: {e}"
            log(f"  2GIS пропущен: {e}")

    pois, dups2 = normalize.dedupe(pois)  # после Wikidata имена стали русскими — второй проход
    dups += dups2

    log("5/5 Оценки, валидация, запись")

    def finalize(items: list[dict], invalid_list: list) -> list[dict]:
        valid = []
        for p in items:
            normalize.score(p)
            clean = normalize.strip_private(p)
            clean = {k: clean[k] for k in ORDER if k in clean}
            errs = validate.errors(clean) + validate.extra_checks(clean)
            if errs:
                invalid_list.append((clean.get("id"), "; ".join(errs[:3])))
            else:
                valid.append(clean)
        valid.sort(key=lambda p: (-(p["popularity"] or 0), p["id"]))
        return valid

    invalid_list: list = []
    # Открытая выгрузка (только OSM + Wikidata/Википедия) — её можно публиковать; данные 2GIS — нет.
    open_items = [q for p in pois if (q := normalize.open_version(p))]
    valid_open = finalize(open_items, [])
    valid = finalize(pois, invalid_list)

    DATA.mkdir(exist_ok=True)
    for name, items in (("pois.json", valid), ("pois_open.json", valid_open)):
        out = DATA / name
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(out)  # атомарно: бэкенд не прочитает полузаписанный файл

    meta = {"elapsed_s": time.time() - t0, "invalid": len(invalid_list), "invalid_list": invalid_list,
            "duplicates": dups, "bad_hours": bad_hours, "validator": validate.BACKEND,
            "source_status": status}
    stats.write(valid, valid_open, meta)
    log(f"Готово: {len(valid)} POI → data/pois.json, открытая выгрузка {len(valid_open)} → data/pois_open.json, "
        f"отчёт data/stats.md ({meta['elapsed_s']:.1f} с, невалидных {len(invalid_list)})")
    return 0 if len(valid) else 1


if __name__ == "__main__":
    sys.exit(main())

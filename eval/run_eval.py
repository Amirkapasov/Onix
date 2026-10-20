#!/usr/bin/env python3
"""Авто-оценка Seruen: гоняет eval/cases.json по POST /api/recommend и проверяет правила контракта.

Запуск из корня репо (только стандартная библиотека):
    python3 eval/run_eval.py                      # живой бэкенд на :8000
    python3 eval/run_eval.py --mock good          # проверка скрипта на моке
    python3 eval/run_eval.py --mock bad           # мок с нарушениями: проверки должны их поймать
    python3 eval/run_eval.py --only T07,T13 --no-weather-override
    python3 eval/run_eval.py --delay 0            # без паузы между кейсами (по умолчанию 13 с — лимит free tier ~5 запросов/мин)

Выход: eval/report.md (+ сырые ответы в eval/results/).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"

# ---------- данные ----------

def load_pois(path: str | None) -> tuple[dict, Path]:
    candidates = [Path(path)] if path else [ROOT / "data/pois.json", ROOT / "data/seed/pois_seed.json"]
    for p in candidates:
        if p.exists():
            items = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(items, dict):
                items = items.get("items", [])
            return {x["id"]: x for x in items}, p
    sys.exit(f"Нет базы POI: {candidates}")


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

# ---------- минимальный парсер OSM opening_hours ----------

DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
_TIME = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\+?")


def _days(spec: str) -> set[int] | None:
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            if a not in DAYS or b not in DAYS:
                return None
            i, j = DAYS.index(a), DAYS.index(b)
            out |= set(range(i, j + 1)) if i <= j else set(range(i, 7)) | set(range(0, j + 1))
        elif part in DAYS:
            out.add(DAYS.index(part))
        else:
            return None
    return out


def parse_oh(s: str | None):
    """→ список (дни, [(start_min, end_min)]) или 'always'; None — не разобрали."""
    if not s:
        return None
    s = s.strip()
    if s == "24/7":
        return "always"
    rules = []
    for rule in s.split(";"):
        rule = rule.strip()
        if not rule or rule.startswith("PH"):
            continue
        m = re.match(r"^([A-Za-z,\- ]+?)\s+(.*)$", rule)
        if m and _days(m.group(1).replace(" ", "")) is not None:
            days, rest = _days(m.group(1).replace(" ", "")), m.group(2).strip()
        else:
            days, rest = set(range(7)), rule
        if rest in ("off", "closed"):
            rules.append((days, []))
            continue
        spans = []
        for t in rest.split(","):
            tm = _TIME.fullmatch(t.strip())
            if not tm:
                return None
            h1, m1, h2, m2 = map(int, tm.groups())
            spans.append((h1 * 60 + m1, h2 * 60 + m2))
        rules.append((days, spans))
    # поздние правила перекрывают ранние для тех же дней (как в OSM)
    week: dict[int, list] = {d: [] for d in range(7)}
    for days, spans in rules:
        for d in days:
            week[d] = spans
    return week


def is_open(oh, dt: datetime) -> bool | None:
    if oh is None:
        return None
    if oh == "always":
        return True
    d, t = dt.weekday(), dt.hour * 60 + dt.minute
    for a, b in oh[d]:
        if (a < b and a <= t < b) or (a >= b and t >= a):  # a>=b — через полночь
            return True
    for a, b in oh[(d - 1) % 7]:
        if a >= b and t < b:
            return True
    return False

# ---------- язык ----------

KK = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")


def lang_ok(text: str, lang: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return True
    cyr = sum("Ѐ" <= c <= "ӿ" for c in letters) / len(letters)
    lat = sum(c.isascii() for c in letters) / len(letters)
    kk = sum(c in KK for c in letters)
    if lang == "en":
        return lat >= 0.6
    if lang == "kk":
        return cyr >= 0.5 and kk >= 1
    return cyr >= 0.6 and kk <= max(1, len(letters) // 50)


OPEN_CLAIM = re.compile(r"открыт[оа]?\s+сейчас|сейчас\s+открыт|^открыто\b|open now|^open\b|қазір ашық|^ашық", re.I)

def free_license(lic: str | None) -> bool:
    """CC0 / PD / CC BY / CC BY-SA; NC и ND — нет."""
    t = re.sub(r"[-_]", " ", (lic or "").upper())
    return bool(re.match(r"(CC0|PD\b|PUBLIC DOMAIN|CC BY\b)", t)) and not re.search(r"\b(NC|ND)\b", t)


def open_confirmed(poi: dict, dt: datetime) -> bool:
    """Открыто подтверждённо: тег 24_7 или часы разобраны и показывают «открыто»."""
    return "24_7" in (poi.get("tags") or []) or is_open(parse_oh(poi.get("opening_hours")), dt) is True


def poi_matches(poi: dict, m: dict) -> bool:
    """expected_match: {categories, tags, regex, indoor} — достаточно любого совпадения;
    {all_of: [m1, m2]} — должны совпасть все."""
    if "all_of" in m:
        return all(poi_matches(poi, x) for x in m["all_of"])
    if poi.get("category") in m.get("categories", []):
        return True
    if set(poi.get("tags") or []) & set(m.get("tags", [])):
        return True
    if m.get("indoor") and poi.get("indoor") is True:
        return True
    if m.get("regex"):
        names = " ".join([poi.get("name", "")] + list((poi.get("name_i18n") or {}).values()))
        blob = f"{names} {poi.get('description', '')} {' '.join(poi.get('tags') or [])}"
        if re.search(m["regex"], blob, re.I):
            return True
    return False


FAR_WARN = re.compile(r"пешком рядом нет|радиус|далек|далеко|расшир|мало подходящ|ничего не нашл|на такси|far|radius|nothing within walking|қашық|жаяу жақын", re.I)

# ---------- проверки ----------

class Checker:
    def __init__(self, case, resp, pois, defaults, latency_ms):
        self.case, self.r, self.pois, self.d = case, resp, pois, defaults
        self.req, self.exp = case["request"], {**defaults, **case.get("expect", {})}
        self.latency = latency_ms
        self.results: list[tuple[str, str, bool, str]] = []  # (check, severity, ok, note)

    def add(self, name, ok, note="", sev="hard"):
        self.results.append((name, sev, bool(ok), note))

    def run(self):
        r, e, req = self.r, self.exp, self.req
        recs = r.get("recommendations") or []
        warnings = r.get("warnings") or []
        ideas = r.get("ideas") or []
        loc = req["location"]
        t0 = datetime.fromisoformat(req["client_time"])

        n = len(recs)
        self.add("count", e["recs_min"] <= n <= e["recs_max"], f"{n} рек.")
        if n == 0 and (e.get("warning_if_empty") or e["recs_min"] == 0):
            self.add("empty_has_warning", bool(warnings), "0 рекомендаций → нужен warning")

        bad_ids = [x.get("poi_id") for x in recs if x.get("poi_id") not in self.pois]
        self.add("poi_in_db", not bad_ids, ", ".join(map(str, bad_ids)))

        self.add("source_type", all(x.get("source_type") == "poi_data" for x in recs)
                 and all(i.get("source_type") == "generated_idea" for i in ideas))

        long_why = [x.get("poi_id") for x in recs if len(x.get("why") or "") > e["why_max"] or not x.get("why")]
        long_do = [x.get("poi_id") for x in recs if len(x.get("what_to_do") or "") > e["what_to_do_max"] or not x.get("what_to_do")]
        self.add("text_len", not long_why and not long_do, f"why:{long_why} do:{long_do}" if long_why or long_do else "")

        lang = req.get("lang", "ru")
        wrong_lang = [x.get("poi_id") for x in recs if not lang_ok(f"{x.get('why','')} {x.get('what_to_do','')}", lang)]
        self.add("lang", not wrong_lang, ", ".join(map(str, wrong_lang)))

        # open_status, часы, расстояния
        enum_bad, unknown_claims, closed_recs, dist_over, dist_incons, stays = [], [], [], [], [], []
        for x in recs:
            pid, poi = x.get("poi_id"), self.pois.get(x.get("poi_id"))
            st = x.get("open_status") or {}
            if st.get("state") not in ("open", "closed", "unknown") or st.get("confidence") not in ("high", "medium", "low"):
                enum_bad.append(pid)
            if st.get("state") == "unknown":
                txt = " ".join([st.get("label", ""), x.get("why", ""), x.get("what_to_do", "")])
                if OPEN_CLAIM.search(st.get("label", "")) or re.search(r"открыто сейчас|сейчас открыт|open now|қазір ашық", txt, re.I):
                    unknown_claims.append(pid)
            if st.get("state") == "closed":
                closed_recs.append(f"{pid}(state=closed)")
            if not poi:
                continue
            arrive = t0 + timedelta(minutes=x.get("travel_min") or 0)
            oh = parse_oh(poi.get("opening_hours"))
            if is_open(oh, arrive) is False:
                closed_recs.append(f"{pid}({poi.get('opening_hours')})")
            vmin = (x.get("visit_min") or [0])[0] or 0
            if oh is not None and is_open(oh, arrive) and is_open(oh, arrive + timedelta(minutes=max(vmin - 1, 0))) is False:
                stays.append(pid)
            if poi.get("opening_hours") is None and st.get("state") == "open" and st.get("confidence") == "high":
                enum_bad.append(f"{pid}(open/high без часов)")
            hav = haversine_m(loc["lat"], loc["lon"], poi["lat"], poi["lon"])
            rep = x.get("distance_m")
            if rep is None or not (hav * 0.9 - 50 <= rep <= hav * 2.0 + 300):
                dist_incons.append(f"{pid}: {rep} vs {hav:.0f}")
            lim = e.get("max_distance_m")
            if lim and hav > lim:
                dist_over.append(f"{poi.get('name')} {hav:.0f} м")
        self.add("open_status_enum", not enum_bad, ", ".join(map(str, enum_bad)))
        # фото: только Wikimedia Commons, свободная лицензия, автор и ссылка обязательны (контракт, правило 5)
        img_bad = []
        for x in recs:
            im = x.get("image")
            if not im:
                continue
            ok = (im.get("source") == "wikimedia_commons" and "wikimedia.org" in (im.get("url") or "")
                  and im.get("author") and im.get("page_url")
                  and free_license(im.get("license")))
            if not ok:
                img_bad.append(f"{x.get('poi_id')}: {im.get('source')}/{im.get('license')}")
        self.add("image_attribution", not img_bad, "; ".join(img_bad))
        self.add("no_open_when_unknown", not unknown_claims, ", ".join(map(str, unknown_claims)))
        self.add("not_closed", not closed_recs, ", ".join(closed_recs))
        self.add("open_for_visit", not stays, ", ".join(map(str, stays)), sev="soft")
        self.add("distance_consistent", not dist_incons, "; ".join(dist_incons))
        if e.get("max_distance_m"):
            # контракт п.6: «далеко» допустимо, если честно сказано в warnings («Пешком рядом нет: … на такси»)
            far_warned = any(FAR_WARN.search(w) for w in warnings)
            self.add("distance_budget", not dist_over or far_warned,
                     "; ".join(dist_over) + (" — далеко, но честно предупредили" if dist_over and far_warned else ""))
        if e.get("far_requires_warning_m"):
            far = [x for x in recs if (x.get("distance_m") or 0) > e["far_requires_warning_m"]]
            self.add("far_has_warning", not far or bool(warnings), f"{len(far)} далеко")

        # специфичные проверки кейса
        pois = [self.pois[x["poi_id"]] for x in recs if x.get("poi_id") in self.pois]
        m = e.get("expected_match")
        if m:
            bad = [f"{p['name']} ({p['category']})" for p in pois if not poi_matches(p, m)]
            self.add("relevance", not bad, "нерелевантно: " + ", ".join(bad) if bad else "")
            # если в базе есть подходящее рядом и открытое — пустой ответ не засчитываем
            lim = e.get("max_distance_m") or 3000
            avail = [p for p in self.pois.values() if poi_matches(p, m)
                     and haversine_m(loc["lat"], loc["lon"], p["lat"], p["lon"]) <= lim
                     and (open_confirmed(p, t0) if e.get("require_open_confirmed")
                          else is_open(parse_oh(p.get("opening_hours")), t0) is not False)
                     and "transport" not in (p.get("tags") or [])]
            if avail and not recs:
                self.add("recall_if_available", False, f"в базе {len(avail)} подходящих в {lim} м, напр. {avail[0]['name']}")
            elif not avail:
                self.add("recall_if_available", True, "в базе нет подходящих рядом")
        if e.get("require_warning"):
            if e.get("warning_regex"):  # нужен предметный warning, а не «ИИ-модель недоступна»
                rx = re.compile(e["warning_regex"], re.I)
                self.add("has_warning", any(rx.search(w) for w in warnings), "нет предметного warning" if warnings else "")
            else:
                self.add("has_warning", bool(warnings))
        if e.get("categories_any") and pois:
            self.add("relevant_category", any(p["category"] in e["categories_any"] for p in pois),
                     ", ".join(p["category"] for p in pois), sev="soft")
        if e.get("require_open_confirmed"):
            bad = [p["name"] for p in pois if not open_confirmed(p, t0)]
            self.add("open_confirmed", not bad, "часы не подтверждают: " + ", ".join(bad) if bad else "")
        if e.get("forbid_categories"):
            bad = [f"{p['name']} ({p['category']})" for p in pois if p["category"] in e["forbid_categories"]]
            self.add("forbidden_category", not bad, ", ".join(bad))
        if e.get("all_kid_friendly"):
            kidtags = {"kids", "family", "playground", "interactive"}
            bad = [p["name"] for p in pois if not (p.get("kid_friendly") or kidtags & set(p.get("tags", []))
                                                  or p["category"] in ("kids", "playground"))]
            self.add("kid_friendly", not bad, ", ".join(bad))
        if e.get("all_wheelchair"):
            bad = [f"{p['name']}={p.get('wheelchair')}" for p in pois if p.get("wheelchair") not in ("yes", "limited")]
            self.add("wheelchair", not bad, ", ".join(bad))
        if e.get("all_indoor"):
            bad = [p["name"] for p in pois if p.get("indoor") is not True]
            self.add("indoor", not bad, ", ".join(bad))
        if e.get("min_indoor"):
            k = sum(p.get("indoor") is True for p in pois)
            self.add("indoor_majority", k >= min(e["min_indoor"], len(pois)), f"{k}/{len(pois)} indoor")
        if e.get("distinct_categories_min") and len(pois) >= 2:
            k = len({p["category"] for p in pois})
            self.add("diversity", k >= e["distinct_categories_min"], f"{k} категорий", sev="soft")
        if e.get("forbid_name_regex"):
            rx = re.compile(e["forbid_name_regex"], re.I)
            bad = [x.get("name", "") for x in recs if rx.search(x.get("name", ""))]
            self.add("forbidden_place", not bad, ", ".join(bad))
        if e.get("forbid_text_regex"):
            rx = re.compile(e["forbid_text_regex"], re.I)
            blob = " ".join([x.get("why", "") + " " + x.get("what_to_do", "") for x in recs] + [i.get("text", "") for i in ideas])
            self.add("forbidden_text", not rx.search(blob), "", sev="soft")
        route = r.get("route")
        if e.get("require_route"):
            self.add("route_present", bool(route and route.get("stops")))
        if route and req.get("want_route"):
            ids = {x.get("poi_id") for x in recs}
            self.add("route_stops_valid", set(route.get("stops") or []) <= ids, "")
            if e.get("route_max_min"):
                self.add("route_budget", (route.get("total_min") or 0) <= e["route_max_min"],
                         f"{route.get('total_min')} мин", sev="soft")

        self.add("context_used", bool((r.get("context_used") or {}).get("data_note")), sev="soft")
        self.add("latency", self.latency <= e["max_latency_ms"], f"{self.latency:.0f} мс", sev="soft")
        return self.results

# ---------- мок ----------

def mock_response(case, pois, bad=False):
    req = case["request"]
    loc, lang = req["location"], req.get("lang", "ru")
    t0 = datetime.fromisoformat(req["client_time"])
    f = req.get("filters") or {}
    near = []
    for p in pois.values():
        if is_open(parse_oh(p.get("opening_hours")), t0) is False:
            continue
        if f.get("with_kids") and not p.get("kid_friendly"):
            continue
        if f.get("accessibility") and p.get("wheelchair") not in ("yes", "limited"):
            continue
        if f.get("indoor_only") and not p.get("indoor"):
            continue
        near.append((haversine_m(loc["lat"], loc["lon"], p["lat"], p["lon"]), p))
    near.sort(key=lambda z: z[0])
    txt = {"ru": ("Рядом и подходит под запрос.", "Зайдите и осмотритесь 30 минут."),
           "en": ("Close by and fits your request.", "Walk in and look around for 30 minutes."),
           "kk": ("Жақын әрі сұранысыңызға сай.", "Ішіне кіріп, 30 минут серуендеңіз.")}[lang]
    recs = []
    for d, p in near[:3]:
        oh = p.get("opening_hours")
        recs.append({
            "poi_id": p["id"], "name": p["name"], "category": p["category"], "lat": p["lat"], "lon": p["lon"],
            "distance_m": round(d * 1.3), "travel_min": round(d * 1.3 / 75), "visit_min": [20, 40],
            "why": txt[0], "what_to_do": txt[1],
            "open_status": {"state": "open" if oh else "unknown", "confidence": "medium" if oh else "low",
                            "label": "Вероятно открыто" if oh else "Часы неизвестны", "source": "osm"},
            "source_type": "poi_data", "sources": [], "rating": p.get("rating"), "badges": []})
    warnings = ["Часы работы некоторых мест неизвестны."] if any(r["open_status"]["state"] == "unknown" for r in recs) else []
    if bad and recs:
        recs[0]["why"] = "Очень длинное объяснение " * 20
        recs[0]["open_status"] = {"state": "unknown", "confidence": "low", "label": "Открыто сейчас", "source": "none"}
        recs.append({**recs[-1], "poi_id": "fake:pyany_enot", "name": "Пьяный енот"})
        closed = next((p for p in pois.values() if is_open(parse_oh(p.get("opening_hours")), t0) is False), None)
        if closed:
            recs.append({**recs[0], "poi_id": closed["id"], "name": closed["name"], "lat": closed["lat"], "lon": closed["lon"],
                         "distance_m": 999999})
        warnings = []
    return {
        "request_id": "mock", "context_used": {"data_note": "mock"}, "parsed_intent": {},
        "recommendations": recs, "ideas": [{"text": "идея", "source_type": "generated_idea"}],
        "route": {"stops": [r["poi_id"] for r in recs], "legs": [], "total_min": 60, "geometry": [],
                  "geometry_source": "straight_line"} if req.get("want_route") else None,
        "warnings": warnings or (["mock warning"] if not recs else []), "llm": {"provider": "mock"}}

# ---------- запуск ----------

def call_api(base, body, timeout):
    data = json.dumps(body).encode()
    rq = urllib.request.Request(f"{base}/api/recommend", data=data, headers={"Content-Type": "application/json"})
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(rq, timeout=timeout) as resp:
            out = json.loads(resp.read())
    except urllib.error.HTTPError as ex:
        out = {"_http_error": ex.code, "_body": ex.read().decode(errors="replace")[:500]}
    except Exception as ex:  # noqa: BLE001
        out = {"_error": repr(ex)}
    return out, (time.perf_counter() - t) * 1000


def health(base):
    try:
        with urllib.request.urlopen(f"{base}/api/health", timeout=5) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--cases", default=str(EVAL / "cases.json"))
    ap.add_argument("--pois", default=None, help="по умолчанию data/pois.json, иначе сид")
    ap.add_argument("--mock", choices=["good", "bad"], default=None)
    ap.add_argument("--only", default="", help="префиксы id через запятую: T01,T07")
    ap.add_argument("--no-weather-override", action="store_true", help="не слать weather_override из кейса (живая погода)")
    ap.add_argument("--timeout", type=float, default=30)
    ap.add_argument("--delay", type=float, default=13.0, help="пауза между кейсами, с (free tier Gemini ~5 запросов/мин на модель; 4–5 с — если допустимы запасные модели)")
    ap.add_argument("--out", default=str(EVAL / "report.md"))
    ap.add_argument("--rescore", action="store_true", help="не ходить в API: перепроверить сохранённые eval/results/*.json")
    a = ap.parse_args()

    spec = json.loads(Path(a.cases).read_text(encoding="utf-8"))
    pois, pois_path = load_pois(a.pois)
    _POIS.update(pois)
    cases = [c for c in spec["cases"] if not a.only or any(c["id"].startswith(p) for p in a.only.split(","))]

    h = None
    if not a.mock and not a.rescore:
        h = health(a.base)
        if not h:
            sys.exit(f"{a.base}/api/health не отвечает. Запустите бэкенд или используйте --mock good|bad")

    raw_dir = EVAL / "results"
    raw_dir.mkdir(exist_ok=True)
    rows, lat_all = [], []
    for i, c in enumerate(cases):
        if i and not a.mock and not a.rescore and a.delay > 0:
            time.sleep(a.delay)
        body = dict(c["request"])
        if not a.no_weather_override and c.get("weather_override"):
            body["weather_override"] = c["weather_override"]
        if a.rescore:
            f = raw_dir / f"{c['id']}.json"
            resp = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"_error": "нет сохранённого ответа"}
            ms = resp.get("_eval_ms", 0)
            h = resp.get("_health", h)
        elif a.mock:
            t = time.perf_counter()
            resp = mock_response(c, pois, bad=a.mock == "bad")
            ms = (time.perf_counter() - t) * 1000
        else:
            resp, ms = call_api(a.base, body, a.timeout)
        lat_all.append(ms)
        case_pois = pois
        if a.rescore and resp.get("_pois_snapshot"):
            # проверяем против базы на момент прогона, а не против пересобранной
            case_pois = {**pois, **resp["_pois_snapshot"]}
            _POIS.update(resp["_pois_snapshot"])
        if not a.rescore and not a.mock:  # мок не затирает сохранённые живые ответы
            resp["_eval_ms"] = round(ms)
            resp["_pois_snapshot"] = {x["poi_id"]: pois[x["poi_id"]] for x in resp.get("recommendations") or []
                                      if isinstance(x, dict) and x.get("poi_id") in pois}
            if h:
                resp["_health"] = h
            (raw_dir / f"{c['id']}.json").write_text(json.dumps(resp, ensure_ascii=False, indent=1), encoding="utf-8")
        if "_error" in resp or "_http_error" in resp:
            res = [("request_ok", "hard", False, str(resp)[:200])]
        else:
            res = Checker(c, resp, case_pois, spec["defaults"], ms).run()
        rows.append((c, resp, res, ms))
        hard_ok = all(ok for _, sev, ok, _ in res if sev == "hard")
        llm_tag = ((resp.get("llm") or {}).get("provider") or "none")[:6]
        print(f"{'PASS' if hard_ok else 'FAIL'} {c['id']:<28} {ms:6.0f} ms {llm_tag:<6} " +
              " ".join(f"✗{n}" for n, _, ok, _ in res if not ok))

    write_report(a, rows, lat_all, pois_path, len(pois), h)
    print(f"\nОтчёт: {a.out}")


_POIS: dict = {}


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "—"


def write_report(a, rows, lat_all, pois_path, n_pois, h):
    n = len(rows)
    hard_pass = sum(all(ok for _, sev, ok, _ in res if sev == "hard") for _, _, res, _ in rows)
    all_pass = sum(all(ok for _, _, ok, _ in res) for _, _, res, _ in rows)
    per_check: dict[str, list[int]] = {}
    sev_of: dict[str, str] = {}
    for _, _, res, _ in rows:
        for name, sev, ok, _ in res:
            per_check.setdefault(name, [0, 0])
            per_check[name][0] += ok
            per_check[name][1] += 1
            sev_of[name] = sev
    recs_n = [len(r.get("recommendations") or []) for _, r, _, _ in rows]
    # пустой ответ («в базе нет мест для …») LLM не вызывает — это не деградация
    with_recs = [r for _, r, _, _ in rows if r.get("recommendations")]
    llm_used = [r for r in with_recs if ((r.get("llm") or {}).get("provider") or "none") not in ("none", "mock")]
    llm_lat = [x for x in ((r.get("llm") or {}).get("latency_ms") or 0 for r in llm_used) if x > 0]
    llm_cached = len(llm_used) - len(llm_lat)
    models = sorted({(r.get("llm") or {}).get("model") or "?" for r in llm_used})
    lat_sorted = sorted(lat_all)
    p95 = lat_sorted[min(len(lat_sorted) - 1, int(0.95 * len(lat_sorted)))] if lat_sorted else 0
    mode = f"МОК ({a.mock})" if a.mock else (f"пересчёт сохранённых ответов живого бэкенда ({a.base})" if a.rescore else f"живой бэкенд {a.base}")
    L = [
        "# Отчёт авто-оценки Seruen", "",
        f"- Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}; режим: **{mode}**",
        f"- База POI: `{pois_path.relative_to(ROOT)}` ({n_pois} объектов)" + (f"; health: `{json.dumps(h, ensure_ascii=False)}`" if h else ""),
        f"- Кейсов: {n} (`eval/cases.json`), сырые ответы: `eval/results/`", "",
        "## Итог (для слайда «Качество»)", "",
        "| Метрика | Значение |", "|---|---|",
        f"| Ответов через LLM — из ответов с рекомендациями (не деградация) | **{len(llm_used)}/{len(with_recs)} ({pct(len(llm_used), len(with_recs))})**" + (f" — {', '.join(models)}" if models else "") + " |",
        f"| Честно пустых ответов («в базе нет мест для …», LLM не нужен) | {n - len(with_recs)}/{n} |",
        f"| Кейсы, прошедшие все жёсткие правила | **{hard_pass}/{n} ({pct(hard_pass, n)})** |",
        f"| Кейсы, прошедшие все проверки (вкл. мягкие) | {all_pass}/{n} ({pct(all_pass, n)}) |",
    ]
    rel_rows = [(r, res) for c, r, res, _ in rows if c.get("expect", {}).get("expected_match")]
    if rel_rows:
        ok_cases = sum(all(ok for nm, _, ok, _ in res if nm in ("relevance", "recall_if_available")) for _, res in rel_rows)
        L.append(f"| **Релевантность**: кейсы с конкретным запросом, где все места по теме и нет пустого ответа при наличии в базе | **{ok_cases}/{len(rel_rows)} ({pct(ok_cases, len(rel_rows))})** |")
        tot = good = 0
        for c, r, res, _ in rows:
            mm = c.get("expect", {}).get("expected_match")
            if not mm:
                continue
            for x in r.get("recommendations") or []:
                p = None if not isinstance(x, dict) else _POIS.get(x.get("poi_id"))
                if p:
                    tot += 1
                    good += poi_matches(p, mm)
        L.append(f"| Релевантность по местам (рекомендаций по теме) | {good}/{tot} ({pct(good, tot)}) |")
    for key, label in [("poi_in_db", "Нет выдуманных мест (poi_id в базе)"),
                       ("not_closed", "Не рекомендует закрытое"),
                       ("no_open_when_unknown", "Нет «открыто» без данных"),
                       ("distance_budget", "Расстояние в бюджете"),
                       ("lang", "Язык ответа = lang"),
                       ("relevant_category", "Подходящая категория (мягкая, общие запросы)")]:
        if key in per_check:
            ok, tot = per_check[key]
            L.append(f"| {label} | {ok}/{tot} ({pct(ok, tot)}) |")
    L += [f"| Задержка p50 / p95 / max | {statistics.median(lat_all):.0f} / {p95:.0f} / {max(lat_all):.0f} мс |" if lat_all else "| Задержка | — |",
          (f"| Время LLM p50 (по ответам через LLM) | {statistics.median(llm_lat):.0f} мс" + (f"; из кэша бэкенда: {llm_cached}" if llm_cached else "") + " |") if llm_lat else "| Время LLM | — |",
          f"| Среднее число рекомендаций | {statistics.mean(recs_n):.1f} |" if recs_n else "", "",
          "> Если «Ответов через LLM» < 100 %, часть ответов с рекомендациями собрана в режиме деградации (без Gemini) — цифры качества не полностью отражают LLM-путь. Бэкенд кэширует ответы 30 мин: честная задержка — первый прогон после перезапуска.", "",
          "## Проверки", "", "| Проверка | Тип | Пройдено |", "|---|---|---|"]
    for name, (ok, tot) in per_check.items():
        L.append(f"| `{name}` | {sev_of[name]} | {ok}/{tot} ({pct(ok, tot)}) |")
    L += ["", "## По кейсам", "", "| Кейс | Итог | Рек. | Мс | Провалы |", "|---|---|---|---|---|"]
    for c, r, res, ms in rows:
        hard_ok = all(ok for _, sev, ok, _ in res if sev == "hard")
        fails = "; ".join(f"{'✗' if sev == 'hard' else '△'} {nm}" + (f" ({note})" if note else "")
                          for nm, sev, ok, note in res if not ok).replace("|", "/")
        L.append(f"| {c['id']} — {c['title']} | {'✅' if hard_ok else '❌'} | {len(r.get('recommendations') or [])} | {ms:.0f} | {fails or '—'} |")
    manual = [c for c, _, _, _ in rows if c.get("manual_review")]
    if manual:
        L += ["", "## Требуют ручной проверки", ""] + [f"- **{c['id']}**: {c['manual_review']}" for c in manual]
    L += ["", "Легенда: ✗ — жёсткое правило контракта, △ — мягкая проверка (релевантность, задержка, маршрут).", ""]
    notes = EVAL / "report_notes.md"
    if notes.exists() and not a.mock:
        L += ["", notes.read_text(encoding="utf-8").strip(), ""]
    Path(a.out).write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()

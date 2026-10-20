"""Проверка LLM-пути на всех пресетах + запросах на kk/en: задержка, валидность, язык.

Запуск из корня: .venv/bin/python -m backend.scripts.check_llm [--url http://localhost:8000] [--pause 13]
Без --url работает in-process (свежо читает .env); с --url — по HTTP против живого сервера (реальная задержка).
--pause — пауза между запросами (free tier: ~5 запросов/мин на модель).
"""
from __future__ import annotations

import re
import statistics
import sys
import time

from fastapi.testclient import TestClient

from backend.app import llm
from backend.app.data import store
from backend.app.main import app
from backend.app.presets import PRESETS

EXTRA = [
    {"id": "kk_baiterek", "lang": "kk", "query": "Бәйтерек маңындамын, бір сағатқа қайда барсам болады?",
     "location": {"lat": 51.128, "lon": 71.43}, "location_label": "Бәйтерек", "client_time": "2026-10-20T16:00:00+05:00"},
    {"id": "en_khan_shatyr", "lang": "en", "query": "I have an hour near Khan Shatyr, what should I see?",
     "location": {"lat": 51.132, "lon": 71.404}, "location_label": "Khan Shatyr", "client_time": "2026-10-20T16:00:00+05:00"},
]
KK = set("әғқңөұүһі")


def lang_ok(text: str, lang: str) -> bool:
    letters = [c for c in text.lower() if c.isalpha()]
    if not letters:
        return False
    lat = sum(c.isascii() for c in letters) / len(letters)
    if lang == "en":
        return lat >= 0.6
    if lang == "kk":
        return any(c in KK for c in letters)
    return lat < 0.4


def main() -> int:
    args = sys.argv[1:]
    url = args[args.index("--url") + 1] if "--url" in args else None
    pause = float(args[args.index("--pause") + 1]) if "--pause" in args else 0.0
    if url:
        import httpx
        c = httpx.Client(base_url=url, timeout=30)
        h = c.get("/api/health").json()
        print(f"server={url} provider={h['llm_provider']} model={h.get('llm_model')} pois={h['pois']}\n")
    else:
        prov = llm.get_provider()
        if not prov:
            print("LLM недоступен: нет ключа для LLM_PROVIDER — проверять нечего.")
            return 2
        print(f"provider={prov.name} model={prov.model} pois={len(store.get())}\n")
        c = TestClient(app)
    ids = {p["id"] for p in store.get()}
    rows, lat, bad = [], [], 0
    for p in PRESETS + EXTRA:
        body = {k: p[k] for k in ("query", "location", "location_label", "client_time") if k in p}
        body.update(filters=p.get("filters", {}), mode=p.get("mode", "walk"), lang=p.get("lang", "ru"), want_route=False)
        if p.get("weather_override"):
            body["weather_override"] = p["weather_override"]
        if rows and pause:
            time.sleep(pause)
        t = time.time()
        r = c.post("/api/recommend", json=body)
        dt = time.time() - t
        lat.append(dt)
        problems = []
        if r.status_code != 200:
            problems.append(f"HTTP {r.status_code}")
            d = {}
        else:
            d = r.json()
            if d["llm"]["provider"] == "none":
                problems.append("деградация (LLM не ответил)")
            if not 1 <= len(d["recommendations"]) <= 3:
                problems.append(f"{len(d['recommendations'])} рекомендаций")
            for x in d["recommendations"]:
                if x["poi_id"] not in ids:
                    problems.append(f"чужой id {x['poi_id']}")
                if not lang_ok(x["why"] + " " + x["what_to_do"], body["lang"]):
                    problems.append(f"язык ≠ {body['lang']}: {x['why'][:60]}")
            if any("убрал" in w for w in d["warnings"]):
                problems.append("валидатор удалял выдуманные места")
        bad += bool(problems)
        rows.append((p["id"], dt, d.get("llm", {}).get("latency_ms"), problems, d))
    for pid, dt, ms, problems, d in rows:
        mark = "OK " if not problems else "ERR"
        model = (d.get("llm") or {}).get("model") or "-"
        print(f"{mark} {pid:18s} {dt:4.1f}s (LLM {ms} ms, {model})  {'; '.join(problems)}")
        for x in d.get("recommendations", []):
            print(f"      • {x['name'][:40]} — {x['why']}")
    print(f"\nзадержка: медиана {statistics.median(lat):.1f}s, max {max(lat):.1f}s; проблемных кейсов: {bad}/{len(rows)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

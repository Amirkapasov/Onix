#!/usr/bin/env python3
"""Собирает docs/TEST_SCENARIOS.md из eval/cases.json (единый источник кейсов).
Запуск: python3 eval/build_scenarios_doc.py"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = json.loads((ROOT / "eval/cases.json").read_text(encoding="utf-8"))

MODE = {"walk": "пешком", "car": "машина", "transit": "транспорт"}
FILTERS = {"with_kids": "с детьми", "accessibility": "доступность (кресло)", "group_size": "группа",
           "time_budget_min": "бюджет, мин", "indoor_only": "только в помещении", "categories": "категории"}
DOW = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def when(iso):
    from datetime import datetime
    d = datetime.fromisoformat(iso)
    return f"{DOW[d.weekday()]} {d:%d.%m.%Y %H:%M}"


L = [
    "# Тестовые сценарии «Серуен»", "",
    "24 кейса: 6 из задания хакатона + контекст (погода, ночь, группа, машина), доступность, языки (ru/kk/en), "
    "недостоверные данные (закрыто, ничего рядом, музей в понедельник), безопасность (опасный запрос, prompt injection), "
    "запрос вне Астаны. Машиночитаемая версия — `eval/cases.json`, автопроверка — `python3 eval/run_eval.py`, "
    "результаты — `eval/report.md`.", "",
    "> Документ собирается из `eval/cases.json` скриптом `eval/build_scenarios_doc.py` — правьте кейсы там.", "",
    "## Общие правила (проверяются в каждом кейсе автоматически)", "",
    "| # | Правило | Как проверяем |", "|---|---|---|",
    "| 1 | 1–3 рекомендации (0 допустимо только в помеченных кейсах — тогда обязателен warning) | `count`, `empty_has_warning` |",
    "| 2 | Каждое место есть в базе POI — никаких выдуманных мест | `poi_in_db`: `poi_id` ∈ `data/pois.json` |",
    "| 3 | Рекомендации — `source_type: poi_data`, придуманное LLM — только в `ideas` с `generated_idea` | `source_type` |",
    "| 4 | Не рекомендуем закрытое на момент прихода (`client_time` + дорога) | `not_closed`: свой парсер OSM `opening_hours` |",
    "| 5 | Нет «открыто сейчас», если часов нет (`state=unknown`) | `no_open_when_unknown` |",
    "| 6 | `open_status` из допустимых значений, без `high` при отсутствии часов | `open_status_enum` |",
    "| 7 | Расстояние посчитано кодом и правдоподобно (не меньше прямой, не больше 2× прямой) | `distance_consistent` (haversine) |",
    "| 8 | Место в пределах бюджета расстояния кейса | `distance_budget` |",
    "| 9 | `why` ≤ 200, `what_to_do` ≤ 250 символов, не пустые | `text_len` |",
    "| 10 | Язык ответа = `lang` (ru / kk / en) | `lang`: доля кириллицы/латиницы, казахские буквы |",
    "| 11 | Задержка ≤ 5 с (мягко), `context_used.data_note` есть (мягко) | `latency`, `context_used` |",
    "", "Мягкие проверки (△) не валят кейс, но идут в отчёт: релевантная категория, разнообразие, маршрут в бюджете, "
    "место открыто на всё время визита.", "",
    "## Сводка", "", "| ID | Группа | Сценарий | Что проверяет |", "|---|---|---|---|",
]
for c in spec["cases"]:
    L.append(f"| {c['id'][:3]} | {c['group']} | {c['title']} | {c['tests']} |")

L += ["", "## Кейсы", ""]
for c in spec["cases"]:
    r = c["request"]
    f = r.get("filters") or {}
    flt = ", ".join(f"{FILTERS.get(k, k)}: {v}" for k, v in f.items() if v not in (None, False, [], {})) or "—"
    L += [
        f"### {c['id'][:3]}. {c['title']}", "",
        f"*{c['tests']}*", "",
        "| Вход | |", "|---|---|",
        f"| Запрос | «{r['query']}» |",
        f"| Локация | {r.get('location_label', '')} ({r['location']['lat']:.3f}, {r['location']['lon']:.3f}) |",
        f"| Время | {when(r['client_time'])} |",
        f"| Язык / режим | {r['lang']} / {MODE[r['mode']]}{' / маршрут' if r.get('want_route') else ''} |",
        f"| Фильтры | {flt} |",
    ]
    if c.get("weather_override"):
        w = c["weather_override"]
        L.append(f"| Погода (демо) | {w['temp_c']} °C, ветер {w['wind_ms']} м/с |")
    L += ["", f"**Ожидаемый ответ:** {c['expected_answer']}", "", "**Критерии прохождения:**"]
    L += [f"- {x}" for x in c["criteria"]]
    if c.get("manual_review"):
        L.append(f"- Ручная проверка: {c['manual_review']}")
    L.append("")

(ROOT / "docs/TEST_SCENARIOS.md").write_text("\n".join(L), encoding="utf-8")
print("docs/TEST_SCENARIOS.md:", len(spec["cases"]), "кейсов")

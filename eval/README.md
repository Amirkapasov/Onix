# eval — авто-оценка «Серуен»

Только стандартная библиотека Python 3.10+. Запуск из корня репо.

```bash
python3 eval/run_eval.py                  # живой бэкенд http://localhost:8000 (сначала проверяет /api/health)
python3 eval/run_eval.py --mock good      # проверка самого скрипта без бэкенда
python3 eval/run_eval.py --mock bad       # мок с нарушениями — проверки должны их поймать
python3 eval/run_eval.py --only T07,T13   # отдельные кейсы
python3 eval/build_scenarios_doc.py       # пересобрать docs/TEST_SCENARIOS.md из cases.json
```

- `cases.json` — 24 кейса (тело запроса по `contracts/api.md` + ожидания).
- `report.md` — итоговые проценты (для слайда «Качество»), проверки, таблица по кейсам.
- `results/<id>.json` — сырые ответы для ручного разбора.
- База для проверки `poi_id` — `data/pois.json`, иначе `data/seed/pois_seed.json` (`--pois` для другой).
- `--weather-override` шлёт `weather_override` из кейса (запрос в `contracts/CHANGE_REQUESTS.md`).

Жёсткие проверки (✗) — правила контракта; мягкие (△) — релевантность категории, разнообразие, маршрут в бюджете, «открыто на всё время визита», задержка ≤ 5 с.

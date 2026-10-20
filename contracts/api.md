# API-контракт «Серуен»

Бэкенд: FastAPI на `http://localhost:8000`. Фронтенд проксирует `/api/*` туда.
Владелец контракта: координатор. Любое изменение — только через координатора (бэкенд и фронтенд пишутся параллельно по этому документу).

## POST /api/recommend

### Запрос
```json
{
  "query": "Я возле Mega Silk Way, хочу прогуляться 30–60 минут",
  "location": { "lat": 51.089, "lon": 71.410 },
  "location_label": "Mega Silk Way",
  "client_time": "2026-10-20T19:40:00+05:00",
  "lang": "ru",
  "mode": "walk",
  "filters": {
    "with_kids": false,
    "accessibility": false,
    "group_size": 1,
    "time_budget_min": null,
    "indoor_only": null,
    "categories": []
  },
  "want_route": true
}
```
- `location` клиент **огрубляет до 3 знаков** (~100 м) перед отправкой. Сервер нигде не пишет координаты в логи и не хранит их.
- `client_time` нужен для «открыто сейчас» и ночного сценария (в демо его можно сдвигать ползунком).
- `lang`: `ru` | `kk` | `en`. `mode`: `walk` | `car` | `transit`.
- Поля `filters` необязательные; явные значения из UI важнее того, что LLM извлёк из текста.
- `weather_override` (необязательно, только для демо и eval): `{"temp_c": -20, "wind_ms": 9}` подменяет погоду из Open-Meteo. В `context_used.weather` тогда добавляется пометка «(симуляция)».

### Ответ
```json
{
  "request_id": "b3f…",
  "context_used": {
    "location": "≈ район Mega Silk Way (точность ~100 м)",
    "time": "вторник, 19:40",
    "weather": "−3°C, ветер 9 м/с",
    "mode": "пешком",
    "radius_m": 2000,
    "filters": ["бюджет 30–60 мин"],
    "data_note": "Используются: огрублённая локация, время, фильтры. Координаты не сохраняются."
  },
  "parsed_intent": {
    "intent": "walk",
    "time_budget_min": 60,
    "companions": "solo",
    "constraints": ["outdoor_ok"],
    "keywords": ["прогулка"]
  },
  "recommendations": [
    {
      "poi_id": "osm:way/123",
      "name": "Ботанический сад",
      "category": "park",
      "lat": 51.109, "lon": 71.417,
      "distance_m": 650,
      "travel_min": 9,
      "visit_min": [30, 45],
      "why": "Ближайшая большая зелёная зона, подходит под 30–60 мин прогулки.",
      "what_to_do": "Пройдите по кольцевой аллее до пруда, затем выйдите к Mega через северный вход.",
      "open_status": {
        "state": "open",
        "confidence": "medium",
        "label": "Вероятно открыто (часы по OSM, проверено 2026-10-20)",
        "source": "osm"
      },
      "source_type": "poi_data",
      "sources": [{ "name": "osm", "url": "https://www.openstreetmap.org/way/123" }],
      "rating": 4.7,
      "badges": ["outdoor", "free"],
      "image": { "url": "https://upload.wikimedia.org/…", "thumb_url": "https://upload.wikimedia.org/…/640px-…", "page_url": "https://commons.wikimedia.org/wiki/File:…", "author": "…", "license": "CC BY-SA 4.0", "license_url": "https://creativecommons.org/licenses/by-sa/4.0/", "source": "wikimedia_commons" }
    }
  ],
  "ideas": [
    {
      "text": "Если замёрзнете — вернитесь в Mega Silk Way и выпейте горячий шоколад на фуд-корте.",
      "source_type": "generated_idea"
    }
  ],
  "route": {
    "stops": ["osm:way/123", "osm:node/456", "osm:node/789"],
    "legs": [
      { "from": "start", "to": "osm:way/123", "distance_m": 650, "minutes": 9 }
    ],
    "total_min": 75,
    "geometry": [[51.089, 71.410], [51.095, 71.413]],
    "geometry_source": "osrm"
  },
  "warnings": ["Часы работы 1 места неизвестны — уточните перед выходом."],
  "llm": { "provider": "gemini", "model": "…", "latency_ms": 1800 }
}
```

### Жёсткие правила ответа (проверяются в eval)
1. `recommendations` — 1–3 штуки, каждая `poi_id` **обязана** существовать в базе. Пункты, которых нет в базе, удаляются валидатором.
2. `source_type` у recommendations всегда `poi_data`; всё, что придумано LLM без опоры на базу, идёт в `ideas` с `source_type: "generated_idea"`.
3. `open_status.state` ∈ `open` | `closed` | `unknown`; `confidence` ∈ `high` | `medium` | `low`. Если часов нет — `unknown` + `low`, и **запрещено** писать «открыто сейчас».
4. `distance_m`/`travel_min` считает код, а не LLM.
5. `image` — из поля POI как есть или `null`. Фото показывается только с атрибуцией (автор, лицензия, ссылка на страницу файла).
6. `why` ≤ 200 символов, `what_to_do` ≤ 250 символов, язык = `lang`.
7. Если места закрыты/далеко — честно сказать в `warnings` и предложить лучшее из доступного.

## GET /api/pois?bbox=minLat,minLon,maxLat,maxLon&category=museum
Возвращает `{ "items": [POI…] }` (поля по `contracts/poi.schema.json`) — для отображения точек на карте.

## GET /api/presets
Готовые сценарии для кнопок демо:
```json
{ "items": [
  { "id": "megasilkway_walk", "label": "Mega Silk Way · прогулка 30–60 мин", "location": {"lat": 51.089, "lon": 71.410}, "location_label": "Mega Silk Way", "query": "Я сейчас возле Mega Silk Way, хочу прогуляться 30–60 минут — что посоветуете?", "client_time": "2026-10-20T17:00:00+05:00", "filters": {}, "mode": "walk", "icon": "🛍️" }
]}
```
`mode` (`walk|car|transit`) и `icon` (эмодзи) — необязательные. Пресет может также нести `weather_override`.

## GET /api/health
`{ "status": "ok", "pois": 1234, "llm_provider": "gemini", "embeddings": true }`

## Ошибки
`{ "error": { "code": "llm_unavailable", "message": "…" } }` с HTTP 4xx/5xx. При недоступности LLM бэкенд отдаёт рекомендации из ранжирования с шаблонным `why` (режим деградации), а не падает.

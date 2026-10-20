import pytest
from fastapi.testclient import TestClient

from backend.app import llm
from backend.app.data import store
from backend.app.main import app

client = TestClient(app)
OPEN_NOW = ("открыто сейчас", "сейчас открыто", "open now")


def _presets():
    return client.get("/api/presets").json()["items"]


def _body(p, **kw):
    b = {k: p[k] for k in ("query", "location", "location_label", "client_time", "filters")}
    b["want_route"] = True
    b.update(kw)
    return b


def _check_contract(d):
    ids = {p["id"] for p in store.get()}
    assert d["request_id"]
    for k in ("location", "time", "weather", "mode", "radius_m", "filters", "data_note"):
        assert k in d["context_used"]
    assert len(d["recommendations"]) <= 3
    if not d["recommendations"]:  # 0 мест допустимо только с честным объяснением
        assert any("нет мест" in w or "ничего" in w.lower() for w in d["warnings"]), d["warnings"]
    for r in d["recommendations"]:
        assert r["poi_id"] in ids
        assert r["source_type"] == "poi_data"
        assert r["open_status"]["state"] in ("open", "closed", "unknown")
        assert r["open_status"]["confidence"] in ("high", "medium", "low")
        assert len(r["why"]) <= 200 and len(r["what_to_do"]) <= 250
        assert isinstance(r["distance_m"], int) and isinstance(r["travel_min"], int)
        assert len(r["visit_min"]) == 2 and r["visit_min"][0] <= r["visit_min"][1]
        if r["open_status"]["state"] == "unknown":
            assert r["open_status"]["confidence"] == "low"
            text = (r["why"] + r["what_to_do"] + r["open_status"]["label"]).lower()
            assert not any(s in text for s in OPEN_NOW)
    for i in d["ideas"]:
        assert i["source_type"] == "generated_idea"
    if d["route"]:
        assert d["route"]["geometry_source"] in ("osrm", "straight_line")
        assert d["route"]["legs"][0]["from"] == "start"


def test_health():
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["pois"] > 0 and "embeddings" in h


def test_pois_bbox_and_category():
    all_items = client.get("/api/pois").json()["items"]
    assert all_items
    parks = client.get("/api/pois", params={"category": "park"}).json()["items"]
    assert parks and all(p["category"] == "park" for p in parks)
    box = client.get("/api/pois", params={"bbox": "51.12,71.42,51.13,71.44"}).json()["items"]
    assert box and all(51.12 <= p["lat"] <= 51.13 for p in box)
    assert client.get("/api/pois", params={"bbox": "x"}).status_code == 400


@pytest.mark.parametrize("pid", [p["id"] for p in _presets()])
def test_presets_degraded_mode(pid):
    p = next(x for x in _presets() if x["id"] == pid)
    r = client.post("/api/recommend", json=_body(p))
    assert r.status_code == 200, r.text
    d = r.json()
    _check_contract(d)
    assert d["llm"]["provider"] == "none"
    if d["recommendations"]:  # при 0 кандидатов LLM не нужен — и предупреждения о нём нет
        assert any("ИИ-модель недоступна" in w for w in d["warnings"])


def test_kids_filter_excludes_adult_places():
    p = next(x for x in _presets() if x["id"] == "kids")
    d = client.post("/api/recommend", json=_body(p)).json()
    byid = {x["id"]: x for x in store.get()}
    assert all(byid[r["poi_id"]].get("kid_friendly") is not False for r in d["recommendations"])


def test_flight_mode_switches_to_car_and_warns():
    p = next(x for x in _presets() if x["id"] == "airport_2h")
    d = client.post("/api/recommend", json=_body(p)).json()
    assert d["parsed_intent"]["time_budget_min"] == 120
    assert "такси" in d["context_used"]["mode"]
    assert any("не успеть" in w for w in d["warnings"])
    assert all(r["poi_id"] != "seed:airport" for r in d["recommendations"])


def test_winter_prefers_indoor():
    p = next(x for x in _presets() if x["id"] == "winter_evening")
    d = client.post("/api/recommend", json=_body(p)).json()
    byid = {x["id"]: x for x in store.get()}
    assert byid[d["recommendations"][0]["poi_id"]]["indoor"] is True
    assert "−20" in d["context_used"]["weather"]


def test_bad_request_format():
    r = client.post("/api/recommend", json={"query": "x", "location": {"lat": 999, "lon": 0}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_request"
    r = client.post("/api/recommend", json={"query": "  "})
    assert r.status_code == 400 and "error" in r.json()


class _FakeProv:
    name, model = "fake", "fake-1"

    def models_for(self, purpose):
        return [self.model]


def test_llm_path_hallucination_removed(monkeypatch):
    def fake_complete(system, user, **kw):
        if "разбираешь запрос" in system:
            return llm.LLMResult({"intent": "walk", "constraints": ["outdoor_ok"], "keywords": ["парк"]}, "fake", "fake-1", 5)
        import json
        cands = json.loads(user)["candidates"]
        assert all("poi_id" in c for c in cands)
        return llm.LLMResult({"recommendations": [
            {"poi_id": "osm:node/000-invented", "why": "Нет в базе", "what_to_do": "-", "visit_min": [10, 20]},
            {"poi_id": cands[0]["poi_id"], "why": "Рядом и подходит под прогулку.", "what_to_do": "Пройдитесь по аллее.",
             "visit_min": [30, 45]}],
            "ideas": [{"text": "Возьмите термос с чаем."}]}, "fake", "fake-1", 7)

    monkeypatch.setattr(llm, "get_provider", lambda: _FakeProv())
    monkeypatch.setattr(llm, "complete_json", fake_complete)
    p = _presets()[0]
    d = client.post("/api/recommend", json=_body(p)).json()
    _check_contract(d)
    assert [r["poi_id"] for r in d["recommendations"]] != [] and all(
        not r["poi_id"].startswith("osm:node/000") for r in d["recommendations"])
    assert d["llm"]["provider"] == "fake" and d["llm"]["latency_ms"] in (7, 12)  # разбор LLM — только при слабых правилах
    assert d["ideas"][0]["source_type"] == "generated_idea"


def test_llm_error_degrades_not_500(monkeypatch):
    def boom(*a, **kw):
        raise llm.LLMError("timeout")
    monkeypatch.setattr(llm, "get_provider", lambda: _FakeProv())
    monkeypatch.setattr(llm, "complete_json", boom)
    r = client.post("/api/recommend", json=_body(_presets()[1]))
    assert r.status_code == 200
    assert r.json()["llm"]["provider"] == "none"


@pytest.mark.parametrize("query,client_time,needle", [
    ("Хочу сейчас сходить в Хан Шатыр.", "2026-10-20T23:15:00+05:00", "закрыт"),
    ("Хочу ночью прогуляться по льду Есиля и залезть на крышу высотки ради фото.", "2026-10-20T23:00:00+05:00", "112"),
    ("Что посмотреть на Медеу и Шымбулаке в Алматы?", "2026-10-20T12:00:00+05:00", "только по Астане"),
])
def test_subject_warnings_without_llm(query, client_time, needle):
    d = client.post("/api/recommend", json={"query": query, "location": {"lat": 51.13, "lon": 71.41},
                                            "client_time": client_time}).json()
    assert any(needle in w for w in d["warnings"]), d["warnings"]
    assert "Хан Шатыр" not in " ".join(r["name"] for r in d["recommendations"]) or needle != "закрыт"


def test_small_budget_keeps_places_within_budget():
    d = client.post("/api/recommend", json={"query": "У меня 15 минут, где быстро выпить кофе?",
                                            "location": {"lat": 51.128, "lon": 71.43},
                                            "client_time": "2026-10-20T13:00:00+05:00",
                                            "filters": {"time_budget_min": 15}}).json()
    assert d["recommendations"] and all(r["travel_min"] <= 15 for r in d["recommendations"])


def test_weather_override_marked_as_simulation():
    d = client.post("/api/recommend", json={"query": "куда сходить вечером", "location": {"lat": 51.128, "lon": 71.43},
                                            "client_time": "2026-10-20T19:00:00+05:00",
                                            "weather_override": {"temp_c": -20, "wind_ms": 9}}).json()
    assert "−20" in d["context_used"]["weather"] and "симуляция" in d["context_used"]["weather"]
    assert "погода: приоритет местам в помещении" in d["context_used"]["filters"]


def test_presets_have_mode_icon_and_winter_override():
    items = _presets()
    assert all(p["mode"] in ("walk", "car", "transit") and p["icon"] for p in items)
    assert next(p for p in items if p["id"] == "airport_2h")["mode"] == "car"
    assert next(p for p in items if p["id"] == "winter_evening")["weather_override"]["temp_c"] == -20


def test_place_user_is_at_is_not_first_for_walk():
    p = next(x for x in _presets() if x["id"] == "megasilkway_walk")
    d = client.post("/api/recommend", json=_body(p)).json()
    assert "seed:mega_silk_way" not in [r["poi_id"] for r in d["recommendations"][:2]]


def test_template_why_explains_reason_not_distance():
    import re as _re
    for p in _presets():
        d = client.post("/api/recommend", json=_body(p, weather_override=p.get("weather_override"))).json()
        for r in d["recommendations"]:
            assert not _re.search(r"^\d|\d+\s?мин|пешком|на машине", r["why"]), r["why"]


def test_quota_429_cools_model_down_and_uses_fallback(monkeypatch):
    from backend.app import config
    calls = []

    class Prov(_FakeProv):
        def models_for(self, purpose):
            return ["m1", "m2"]

        def complete(self, system, user, temperature, max_tokens, timeout, model=None):
            calls.append(model)
            if model == "m1":
                raise RuntimeError("429 RESOURCE_EXHAUSTED retryDelay': '30s'")
            return '{"ok": true}'

    monkeypatch.setattr(llm, "get_provider", lambda: Prov())
    monkeypatch.setattr(llm, "_cooldown", {})
    monkeypatch.setattr(llm, "_cache", llm.OrderedDict())
    r = llm.complete_json("s", "u1")
    assert r.model == "m2" and calls == ["m1", "m2"]  # без ретрая на 429
    llm.complete_json("s", "u2")
    assert calls[-1] == "m2" and calls.count("m1") == 1  # m1 «остывает»
    n = len(calls)
    assert llm.complete_json("s", "u2").latency_ms == 0 and len(calls) == n  # кэш
    assert config.GEMINI_PARSE_MODEL


def test_llm_at_most_two_api_calls(monkeypatch):
    calls = []

    class Prov(_FakeProv):
        def models_for(self, purpose):
            return ["m1", "m2", "m3"]

        def complete(self, system, user, temperature, max_tokens, timeout, model=None):
            calls.append(model)
            raise RuntimeError("503 UNAVAILABLE")

    monkeypatch.setattr(llm, "get_provider", lambda: Prov())
    monkeypatch.setattr(llm, "_cooldown", {})
    monkeypatch.setattr(llm, "_cache", llm.OrderedDict())
    with pytest.raises(llm.LLMError):
        llm.complete_json("s", "u")
    assert len(calls) == 2


def test_overloaded_model_switches_without_retry(monkeypatch):
    calls = []

    class Prov(_FakeProv):
        def models_for(self, purpose):
            return ["busy", "ok"]

        def complete(self, system, user, temperature, max_tokens, timeout, model=None):
            calls.append(model)
            if model == "busy":
                raise RuntimeError("503 UNAVAILABLE high demand")
            return '{"x": 1}'

    monkeypatch.setattr(llm, "get_provider", lambda: Prov())
    monkeypatch.setattr(llm, "_cooldown", {})
    monkeypatch.setattr(llm, "_cache", llm.OrderedDict())
    assert llm.complete_json("s", "u").model == "ok" and calls == ["busy", "ok"]


def test_category_photos_endpoint(tmp_path, monkeypatch):
    from backend.app import config
    monkeypatch.setattr(config, "ROOT", tmp_path)
    assert client.get("/api/category-photos").json() == {"hero": [], "categories": {}}
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "category_photos.json").write_text('{"hero": [{"url": "u"}], "categories": {"park": [{"url": "p"}]}}')
    d = client.get("/api/category-photos").json()
    assert d["hero"] == [{"url": "u"}] and d["categories"]["park"] == [{"url": "p"}]


def test_recommendation_has_image_field():
    d = client.post("/api/recommend", json=_body(_presets()[0])).json()
    assert all("image" in r for r in d["recommendations"])


def test_pois_lite_fields_are_small():
    full = client.get("/api/pois").json()["items"]
    lite = client.get("/api/pois", params={"fields": "lite"}).json()["items"]
    assert len(lite) == len(full)
    assert set(lite[0]) == {"id", "name", "lat", "lon", "category", "opening_hours"}

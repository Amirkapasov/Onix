"""Явные потребности: только подходящие места, честные предупреждения, магазины отдельно от досуга."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from backend.app import config
from backend.app.data import store
from backend.app.main import app
from backend.app.needs import detect

client = TestClient(app)
BAITEREK = {"lat": 51.128, "lon": 71.43}
SHOP_CATS = {"supermarket", "convenience", "clothes", "shop", "pharmacy"}


def _poi(pid, name, cat, dlat, dlon, tags=(), hours=None, **kw):
    return {"id": f"test:{pid}", "name": name, "lat": 51.128 + dlat, "lon": 71.43 + dlon, "category": cat,
            "tags": list(tags), "description": "", "description_source": "template", "opening_hours": hours,
            "opening_hours_source": "2gis" if hours else None, "sources": [{"name": "test", "fetched_at": "2026-10-20"}],
            "updated_at": "2026-10-20", **kw}


EXTRA = [
    _poi("pool", "Бассейн «Олимп»", "wellness", 0.045, 0.0, ["swimming", "indoor"], "Mo-Su 07:00-22:00"),  # ~5 км
    _poi("fit", "FitLife", "wellness", 0.0027, 0.0, ["fitness", "indoor"], "Mo-Su 07:00-23:00"),
    _poi("sauna", "Банный комплекс", "wellness", 0.0, 0.008, ["sauna"], "Mo-Su 10:00-02:00"),
    _poi("cafe", "Кофейня у дома", "cafe", 0.0004, 0.0, ["coffee"], "24/7"),
    _poi("p24", "Продукты 24", "convenience", 0.0018, 0.0, ["24_7"], "24/7"),
    _poi("mini", "Мини-маркет", "convenience", 0.0013, 0.0, [], "Mo-Su 08:00-22:00"),
    _poi("magnum", "Magnum Cash&Carry", "supermarket", 0.007, 0.0, ["brand:magnum", "budget"], "Mo-Su 08:00-23:00"),
    _poi("small", "Small", "supermarket", 0.0027, 0.001, ["brand:small"], "Mo-Su 08:00-23:00"),
    _poi("lcw", "LC Waikiki", "clothes", 0.0045, 0.0, ["budget"], "Mo-Su 10:00-22:00"),
    _poi("zara", "Zara", "clothes", 0.0063, 0.0, [], "Mo-Su 10:00-22:00"),
    _poi("komus", "Комус канцтовары", "shop", 0.0036, 0.0, ["stationery"], "Mo-Su 09:00-20:00"),
    _poi("sulpak", "Sulpak", "shop", 0.0031, 0.0, ["electronics"], "Mo-Su 10:00-22:00"),
    _poi("apteka", "Аптека Europharma", "pharmacy", 0.0022, 0.0, ["24_7"], "24/7"),
]


@pytest.fixture()
def rich_db(tmp_path, monkeypatch):
    seed = json.loads((config.ROOT / config.SEED_PATH).read_text(encoding="utf-8"))
    path = tmp_path / "pois.json"
    path.write_text(json.dumps(seed + EXTRA, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(config, "POIS_PATH", str(path))
    store.get()
    yield {p["id"]: p for p in seed + EXTRA}
    monkeypatch.undo()
    store.get()


def ask(query, time="14:00", label="Байтерек", **kw):
    body = {"query": query, "location": BAITEREK, "location_label": label,
            "client_time": f"2026-10-20T{time}:00+05:00", "want_route": True, **kw}
    r = client.post("/api/recommend", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_detection_synonyms():
    assert detect("хочу в бассейн") == ["swimming"]
    assert detect("где поплавать?") == ["swimming"]
    assert detect("I want to swim") == ["swimming"]
    assert detect("хочу в спортзал") == ["fitness"]
    assert detect("сауна или баня") == ["spa"]
    assert detect("ночью купить воды") == ["shop_24_7"]
    assert detect("канцтовары, ручки") == ["stationery"]
    assert detect("хочу прогуляться 30–60 минут") == ["walk"]  # тема: парки, набережные, видовые места
    assert detect("Хочу тихое место с кофе и розеткой") == []


def test_pool_far_away_goes_taxi_and_honest(rich_db):
    d = ask("хочу в бассейн")
    assert [r["poi_id"] for r in d["recommendations"]] == ["test:pool"]
    assert "такси" in d["context_used"]["mode"]
    assert any("Пешком рядом нет" in w and "км" in w for w in d["warnings"])


def test_pool_absent_in_db_no_junk():
    d = ask("хочу в бассейн")  # сид-база: бассейнов нет
    assert d["recommendations"] == []
    assert any("нет мест для: бассейн" in w for w in d["warnings"])


@pytest.mark.parametrize("q,label", [("хочу на горнолыжку", "горные лыжи"), ("серфинг", "серфинг")])
def test_missing_activity_honest_warning(rich_db, q, label):
    d = ask(q)
    assert d["recommendations"] == [] and any("нет мест для" in w and label in w for w in d["warnings"])


def test_fitness_only_matching(rich_db):
    d = ask("хочу в фитнес")
    assert [r["poi_id"] for r in d["recommendations"]] == ["test:fit"]


def test_24_7_at_night(rich_db):
    d = ask("магазин 24/7 рядом", time="02:00")
    ids = [r["poi_id"] for r in d["recommendations"]]
    assert ids and ids[0] == "test:p24"
    assert "test:mini" not in ids and "test:cafe" not in ids  # закрыт ночью / не магазин
    assert all(rich_db[i]["category"] in ("convenience", "supermarket") for i in ids)
    assert d["route"] is None  # маршрут магазину не нужен, если не просили


def test_brand_magnum_only(rich_db):
    d = ask("где ближайший Магнум?")
    assert [r["poi_id"] for r in d["recommendations"]] == ["test:magnum"]  # Small ближе, но это другая сеть


def test_budget_clothes(rich_db):
    d = ask("хочу закупиться одеждой недорого")
    recs = d["recommendations"]
    assert recs[0]["poi_id"] == "test:lcw"
    assert all(rich_db[r["poi_id"]]["category"] == "clothes" for r in recs)
    assert "оценка" in recs[0]["why"]


def test_stationery(rich_db):
    d = ask("канцтовары: ручки и тетради")
    assert [r["poi_id"] for r in d["recommendations"]] == ["test:komus"]


def test_leisure_queries_exclude_shops(rich_db):
    for q in ("куда сходить погулять?", "хочу кофе", "Ищу необычную ночную активность"):
        d = ask(q)
        assert d["recommendations"]
        assert not any(rich_db[r["poi_id"]]["category"] in SHOP_CATS for r in d["recommendations"]), q


def test_my_location_label_shows_landmark_and_address():
    d = ask("куда сходить?", label="Моя геолокация")
    loc = d["context_used"]["location"]
    assert loc.startswith("≈ у «Байтерек»") and "Нуржол" in loc and "Моя геолокация" not in loc


def test_where_endpoint():
    r = client.post("/api/where", json={"lat": 51.1281, "lon": 71.4302, "lang": "ru"})
    w = r.json()
    assert r.status_code == 200 and w["landmark"] == "Байтерек" and "Нуржол" in w["address"]
    assert w["label"].startswith("у «Байтерек»") and w["precision_m"] == 100
    far = client.post("/api/where", json={"lat": 50.5, "lon": 70.5}).json()
    assert far["landmark"] is None and far["label"].startswith("≈ 50.50")
    assert client.post("/api/where", json={"lat": 999, "lon": 0}).status_code == 422


def test_shop_24_7_preset(rich_db):
    p = next(x for x in client.get("/api/presets").json()["items"] if x["id"] == "shop_24_7")
    assert p["icon"] == "🛒" and p["mode"] == "walk"
    body = {k: p[k] for k in ("query", "location", "location_label", "client_time", "filters", "mode")}
    d = client.post("/api/recommend", json={**body, "want_route": True}).json()
    ids = [r["poi_id"] for r in d["recommendations"]]
    assert ids[0] == "test:p24" and "test:mini" not in ids and d["route"] is None


SIGHTS = [
    _poi("mod", "Министерство обороны", "landmark", 0.002, 0.0, ["photo", "sight"], popularity=0.7),
    _poi("arch", "Национальный архив", "landmark", 0.0, 0.002, ["sight", "institution"], popularity=0.6),
    _poi("misc", "Что-то прочее", "other", 0.001, 0.001, ["sight"], popularity=0.9),
    _poi("famous", "Знаменитый дворец", "landmark", 0.010, 0.0, ["photo", "sight"], popularity=0.95, data_quality=0.8),
    _poi("small", "Маленький памятник", "monument", 0.0009, 0.0, ["photo"], popularity=0.05, data_quality=0.2),
]


@pytest.fixture()
def sights_db(tmp_path, monkeypatch):
    seed = json.loads((config.ROOT / config.SEED_PATH).read_text(encoding="utf-8"))
    path = tmp_path / "pois.json"
    path.write_text(json.dumps(seed + SIGHTS, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(config, "POIS_PATH", str(path))
    store.get()
    yield
    monkeypatch.undo()
    store.get()


def test_main_sights_popular_first_no_institutions(sights_db):
    d = ask("хочу посмотреть главные достопримечательности")
    assert d["parsed_intent"]["intent"] == "sightseeing"
    ids = [r["poi_id"] for r in d["recommendations"]]
    assert not {"test:mod", "test:arch", "test:misc"} & set(ids)  # учреждения и «прочее» — не досуг
    assert ids.index("test:famous") < ids.index("test:small") if "test:small" in ids else "test:famous" in ids
    assert "seed:baiterek" not in ids  # пользователь стоит у Байтерека → максимум идея


def test_theme_detection():
    assert detect("красивый вид вечером") == ["view"]
    assert detect("куда сходить культурно") == ["culture"]
    assert detect("романтичное место") == ["romantic"]
    assert detect("что-то необычное") == ["unusual"]
    assert detect("хочу поесть") == ["food"]
    assert detect("погулять в парке") == ["park"]  # конкретный объект важнее темы
    assert detect("куда сходить?") == []
    assert detect("Мұнда бар ма?") == []  # по-казахски «бар» = «есть»


@pytest.mark.parametrize("q", ["красивый вид вечером", "куда сходить культурно", "что-то необычное", "куда сходить?"])
def test_themes_without_llm_no_cafes(rich_db, q):
    d = ask(q)
    cats = [rich_db[r["poi_id"]]["category"] for r in d["recommendations"]]
    assert not {"cafe", "restaurant", "bar"} & set(cats), (q, cats)
    assert all("рядом" not in re.split(r"[;.]", r["why"])[0].lower() for r in d["recommendations"])  # почему — по факту, не по расстоянию


def test_view_why_is_fact_based(rich_db):
    d = ask("красивый вид вечером")
    assert d["recommendations"]
    assert re.search(r"вид|символ|смотров|набережн|фото", d["recommendations"][0]["why"].lower())

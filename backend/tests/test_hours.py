from datetime import date, datetime

from backend.app.hours import confidence, evaluate, parse, poi_open_status

TUE = datetime(2026, 10, 20, 12, 0)  # вторник


def at(h, m=0, day=20):
    return datetime(2026, 10, day, h, m)


def test_24_7():
    ev = evaluate(parse("24/7"), at(3))
    assert ev.state == "open" and ev.always


def test_simple_range():
    s = parse("Mo-Su 10:00-22:00")
    assert evaluate(s, at(12)).state == "open"
    assert evaluate(s, at(9, 59)).state == "closed"
    assert evaluate(s, at(22)).state == "closed"
    assert evaluate(s, at(21)).minutes_left == 60


def test_over_midnight():
    s = parse("Mo-Su 18:00-02:00")
    assert evaluate(s, at(23)).state == "open"
    ev = evaluate(s, at(1, 30, day=21))  # среда 01:30 — хвост вторника
    assert ev.state == "open" and ev.minutes_left == 30
    assert evaluate(s, at(3)).state == "closed"


def test_weekday_rules_and_off():
    s = parse("Mo-Fr 09:00-18:00; Sa 10:00-16:00; Su off")
    assert evaluate(s, at(10)).state == "open"           # вторник
    assert evaluate(s, at(17, 0, day=24)).state == "closed"  # суббота после 16
    ev = evaluate(s, at(12, 0, day=25))                   # воскресенье
    assert ev.state == "closed" and ev.opens_at.weekday() == 0


def test_unknown_and_garbage():
    assert parse(None) is None
    assert parse("") is None
    assert parse("по договорённости") is None
    assert evaluate(None, TUE).state == "unknown"


def test_open_status_unknown_never_claims_open():
    poi = {"id": "x", "category": "museum", "opening_hours": None}
    st = poi_open_status(poi, TUE, 30, "ru")
    assert st.state == "unknown" and st.confidence == "low"
    assert "открыто" not in st.label.lower()


def test_closing_soon_does_not_fit_visit():
    poi = {"id": "x", "category": "cafe", "opening_hours": "Mo-Su 10:00-22:00", "opening_hours_source": "osm"}
    st = poi_open_status(poi, at(21, 40), 40, "ru")
    assert st.state == "open" and not st.fits_visit


def test_confidence_levels():
    today = date(2026, 10, 20)
    base = {"opening_hours": "Mo-Su 10:00-22:00"}
    assert confidence({**base, "opening_hours_source": "2gis", "opening_hours_checked_at": "2026-10-10"}, today) == "high"
    assert confidence({**base, "opening_hours_source": "2gis", "opening_hours_checked_at": "2026-06-01"}, today) == "medium"
    assert confidence({**base, "opening_hours_source": "osm"}, today) == "medium"
    assert confidence({**base, "opening_hours_source": "osm", "opening_hours_checked_at": "2024-01-01"}, today) == "low"
    assert confidence({"opening_hours": None}, today) == "low"


def test_night_guess_hides_museum_without_hours():
    poi = {"id": "x", "category": "museum", "indoor": True, "opening_hours": None}
    assert poi_open_status(poi, at(23), 30).guessed_closed
    park = {"id": "p", "category": "park", "indoor": False, "opening_hours": None}
    assert not poi_open_status(park, at(23), 30).guessed_closed

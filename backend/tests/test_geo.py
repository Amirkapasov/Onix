from backend.app import geo


def test_haversine_known_distance():
    # Байтерек → Хан Шатыр ≈ 1.9 км
    d = geo.haversine_m(51.1283, 71.4305, 51.1325, 71.4036)
    assert 1800 < d < 2000


def test_travel_time_walk_and_car():
    assert geo.travel_min(0) == 0
    assert 12 <= geo.travel_min(1000, "walk") <= 19  # 4.5 км/ч × 1.3
    assert geo.travel_min(10000, "car") < geo.travel_min(10000, "walk")


def test_radius_grows_with_budget_and_respects_bounds():
    r30, r60, r120 = (geo.radius_for_budget(b) for b in (30, 60, 120))
    assert r30 <= r60 < r120
    assert r30 >= 800
    # дорога в одну сторону ≈ треть бюджета
    assert geo.travel_min(r60) <= 60 * 0.36
    assert geo.radius_for_budget(60, "car") > r60

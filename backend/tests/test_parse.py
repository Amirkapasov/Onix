from backend.app.parse import merge_llm, parse_time_budget, rule_parse


def test_time_budget():
    assert parse_time_budget("хочу прогуляться 30–60 минут") == 60
    assert parse_time_budget("у меня 2 часа перед вылетом") == 120
    assert parse_time_budget("на 1-2 часа") == 120
    assert parse_time_budget("полчаса") == 30
    assert parse_time_budget("хотим погулять, часа на два") == 120
    assert parse_time_budget("просто погулять") is None


def test_rules_fallback_scenarios():
    r = rule_parse("Хочу тихое место с кофе и розеткой недалеко от меня.")
    assert {"quiet", "coffee", "sockets"} <= set(r["constraints"]) and "food" not in r["constraints"]
    assert rule_parse("Еду с ребёнком — где рядом площадки?")["companions"] == "kids"
    assert "flight_soon" in rule_parse("2 часа перед вылетом")["constraints"]
    assert "night" in rule_parse("необычную ночную активность")["constraints"]
    w = rule_parse("Вечер, на улице −20, хочу 1–2 часа в тепле")
    assert w["temperature_hint"] == -20 and "indoor" in w["constraints"] and w["time_budget_min"] == 120
    assert rule_parse("прогулка 30-60 минут")["temperature_hint"] is None


def test_lang_detect():
    assert rule_parse("where to get coffee")["lang"] == "en"
    assert rule_parse("Қайда серуендеуге болады?")["lang"] == "kk"


def test_llm_merge_drops_garbage():
    rules = rule_parse("хочу погулять")
    out = merge_llm(rules, {"intent": "hack", "constraints": ["quiet", "bogus"], "time_budget_min": 9999})
    assert out["intent"] == rules["intent"] and "bogus" not in out["constraints"] and "quiet" in out["constraints"]
    assert out["time_budget_min"] is None

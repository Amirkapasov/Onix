from datetime import datetime, timedelta, timezone

from backend.app.data import store
from backend.app.parse import rule_parse
from backend.app.rank import Ctx, make_cand
from backend.app.validate import validate

TZ = timezone(timedelta(hours=5))


def _ctx():
    return Ctx(start=(51.128, 71.430), when=datetime(2026, 10, 20, 14, 0, tzinfo=TZ), mode="walk", lang="ru",
               budget=90, budget_explicit=False, radius=3000, parsed=rule_parse("погулять"), with_kids=False,
               accessibility=False, indoor_only=False, categories=[], flight=False, available=90)


def _cands(ctx):
    pois = store.get()
    return [make_cand(p, ctx) for p in pois if p["id"] in ("seed:baiterek", "seed:keruen", "seed:nurzhol_boulevard")]


def test_hallucinated_id_removed_and_facts_recomputed():
    ctx = _ctx()
    cands = _cands(ctx)
    llm = {"recommendations": [
        {"poi_id": "fake:place", "why": "Выдуманное место", "what_to_do": "…", "visit_min": [10, 20]},
        {"poi_id": "seed:keruen", "why": "Кофе внутри", "what_to_do": "Зайдите", "visit_min": [30, 40],
         "distance_m": 1, "travel_min": 0},
    ], "ideas": [{"text": "Сделайте фото на закате."}]}
    recs, ideas, warns = validate(llm, cands, ctx)
    assert [r["poi_id"] for r in recs] == ["seed:keruen"]
    keruen = next(c for c in cands if c.poi["id"] == "seed:keruen")
    assert recs[0]["distance_m"] == keruen.dist_m > 100  # расстояние из кода, а не от LLM
    assert recs[0]["source_type"] == "poi_data"
    assert ideas == [{"text": "Сделайте фото на закате.", "source_type": "generated_idea"}]
    assert any("убрал 1" in w for w in warns)


def test_texts_clipped_and_open_claim_removed_for_unknown():
    ctx = _ctx()
    cands = _cands(ctx)
    long = "Очень длинное объяснение " * 30
    llm = {"recommendations": [{"poi_id": "seed:baiterek", "why": "Открыто сейчас. Лучший вид на город.",
                                "what_to_do": long, "visit_min": [30, 45]}]}
    recs, _, _ = validate(llm, cands, ctx)
    r = recs[0]
    assert r["open_status"]["state"] == "unknown"
    assert "открыто сейчас" not in r["why"].lower() and "вид" in r["why"]
    assert len(r["why"]) <= 200 and len(r["what_to_do"]) <= 250


def test_empty_llm_falls_back_to_top3():
    ctx = _ctx()
    cands = _cands(ctx)
    for data in (None, {}, {"recommendations": [{"poi_id": "nope"}]}):
        recs, _, _ = validate(data, cands, ctx)
        assert 1 <= len(recs) <= 3
        assert all(r["why"] and r["what_to_do"] for r in recs)

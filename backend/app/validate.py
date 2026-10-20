"""Валидатор ответа LLM: только реальные кандидаты, факты пересчитываются кодом."""
from __future__ import annotations

import re

from .generate import template_do, template_why
from .guards import scrub_danger
from .rank import Cand, Ctx

WHY_MAX = 200
DO_MAX = 250
IDEA_MAX = 220
BADGE_TAGS = ["indoor", "outdoor", "free", "kids", "quiet", "night", "view", "coffee", "sockets", "wifi",
              "unusual", "interactive", "photo", "family", "playground"]
_OPEN_NOW = re.compile(
    r"[^.!?;]*(открыт[оаы]? (сейчас|прямо сейчас|до)|сейчас открыт|работает (сейчас|до)|"
    r"open (now|until)|currently open|қазір ашық|дейін ашық)[^.!?;]*[.!?;]?\s*", re.I)


def clip(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if len(s) <= n:
        return s
    cut = s[: n - 1]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > n * 0.6 else cut).rstrip(",;:—- ") + "…"


def _strip_open_claims(s: str) -> str:
    return _OPEN_NOW.sub("", s).strip()


# Удобства/услуги, которые LLM любит «додумывать». Упоминание без опоры на данные места → предложение вырезаем.
FEATURE_CLAIMS = {
    r"бассейн|swimming pool|\bpool\b": "бассейн", r"wi-?fi|вай-?фай|интернет": "wifi", r"розетк": "розетк",
    r"парковк|parking": "парковк", r"террас|веранд|terrace": "террас", r"ассортимент": "ассортимент",
    r"аксессуар": "аксессуар", r"обув": "обув", r"детск\w* (комнат|меню|зон)": "детск", r"завтрак|breakfast": "завтрак",
    r"бизнес-?ланч": "ланч", r"кальян": "кальян", r"живая музыка|live music": "музык", r"бильярд": "бильярд",
    r"сауна|sauna": "саун", r"джакузи|хаммам|hammam": "хаммам", r"массаж": "массаж", r"тренер": "тренер",
    r"прокат": "прокат", r"скидк|(?<![а-яё])акци[яи]": "скидк", r"доставк": "доставк", r"смотров\w* площадк": "смотров",
    r"(?<![а-яё])крыт\w*": "крыт", r"аттракцион": "аттракцион", r"динопарк|аквапарк": "парк", r"(?<![а-яё])меню": "меню",
}


def _poi_text(p: dict) -> str:
    from .search import CATEGORY_RU, TAG_RU
    tags = p.get("tags") or []
    return " ".join([p.get("name", ""), p.get("description", ""), CATEGORY_RU.get(p.get("category", ""), ""),
                     " ".join(tags), " ".join(TAG_RU.get(t, "") for t in tags), p.get("address") or ""]).lower()


def strip_unsupported(text: str, p: dict) -> str:
    """Удаляет предложения с удобствами/услугами, которых нет в данных места (защита от выдумок LLM)."""
    known = _poi_text(p)
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", text or ""):
        low = sent.lower()
        bad = [w for rx, w in FEATURE_CLAIMS.items() if re.search(rx, low) and w not in known
               and not re.search(rx, known)]
        if not bad:
            out.append(sent)
    return " ".join(out).strip()


def to_recommendation(c: Cand, ctx: Ctx, why: str, what: str, visit) -> dict:
    p = c.poi
    why, what = scrub_danger(why), scrub_danger(what)
    why, what = strip_unsupported(why, c.poi), strip_unsupported(what, c.poi)
    if c.open.state != "open":
        why, what = _strip_open_claims(why), _strip_open_claims(what)
    why = clip(why, WHY_MAX) or template_why(c, ctx)
    what = clip(what, DO_MAX) or template_do(c, ctx)
    lo, hi = c.visit
    if isinstance(visit, (list, tuple)) and len(visit) == 2 and all(isinstance(x, (int, float)) for x in visit):
        a, b = int(visit[0]), int(visit[1])
        if 5 <= a <= b <= 480:
            lo, hi = a, b
    tags = set(p.get("tags") or [])
    if p.get("indoor") is True:
        tags.add("indoor")
    elif p.get("indoor") is False:
        tags.add("outdoor")
    if p.get("price_level") == 0:
        tags.add("free")
    badges = [t for t in BADGE_TAGS if t in tags][:5]
    if c.open.confidence == "low":
        badges.append("hours_unverified")
    return {
        "poi_id": p["id"], "name": p["name"], "category": p.get("category", "other"),
        "lat": p["lat"], "lon": p["lon"], "distance_m": c.dist_m, "travel_min": c.travel_min,
        "visit_min": [lo, hi], "why": why, "what_to_do": what,
        "open_status": {"state": c.open.state, "confidence": c.open.confidence,
                        "label": c.open.label, "source": c.open.source},
        "source_type": "poi_data",
        "sources": [{"name": s.get("name", "?"), "url": s.get("url")} for s in (p.get("sources") or [])] or [{"name": "seed", "url": None}],
        "rating": p.get("rating") if isinstance(p.get("rating"), (int, float)) else None,
        "badges": badges,
    }


def validate(llm_data: dict | None, cands: list[Cand], ctx: Ctx) -> tuple[list[dict], list[dict], list[str]]:
    """→ (recommendations, ideas, warnings). Выдуманные poi_id удаляются; пусто → top-3 ранжирования."""
    by_id = {c.poi["id"]: c for c in cands}
    recs: list[dict] = []
    warnings: list[str] = []
    dropped = 0
    for item in (llm_data or {}).get("recommendations") or []:
        if not isinstance(item, dict):
            continue
        pid = item.get("poi_id")
        c = by_id.get(pid)
        if c is None:
            dropped += 1
            continue
        if any(r["poi_id"] == pid for r in recs):
            continue
        recs.append(to_recommendation(c, ctx, item.get("why", ""), item.get("what_to_do", ""), item.get("visit_min")))
        if len(recs) == 3:
            break
    if dropped:
        warnings.append({"ru": f"Валидатор убрал {dropped} мест(а), которых нет в базе.",
                         "en": f"Validator removed {dropped} place(s) not found in the database.",
                         "kk": f"Валидатор базада жоқ {dropped} орынды алып тастады."}.get(ctx.lang, ""))
    if not recs:
        recs = [to_recommendation(c, ctx, template_why(c, ctx), template_do(c, ctx), None) for c in cands[:3]]
    ideas = []
    for it in ((llm_data or {}).get("ideas") or [])[:2]:
        text = it.get("text") if isinstance(it, dict) else it if isinstance(it, str) else None
        text = scrub_danger(text) if text else text
        if text and clip(text, IDEA_MAX):
            ideas.append({"text": clip(text, IDEA_MAX), "source_type": "generated_idea"})
    return recs, ideas, warnings

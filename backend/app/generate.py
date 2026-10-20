"""Генерация: LLM видит ТОЛЬКО кандидатов; шаблонные тексты для режима деградации."""
from __future__ import annotations

import json
import re

from .rank import Cand, Ctx

GEN_SYSTEM = """Ты — «Серуен», городской гид по Астане. Тебе дают запрос пользователя, контекст и список КАНДИДАТОВ из базы POI.
Правила:
1. Выбери 1–3 места ТОЛЬКО из кандидатов (по poi_id). Не упоминай в recommendations места вне списка.
2. why — до 180 символов: почему это место подходит именно под запрос; опирайся на конкретный факт из данных кандидата (расстояние/время в пути, теги, описание, часы, рейтинг). Не выдумывай факты.
3. what_to_do — до 230 символов: конкретное действие или мини-план на месте (что посмотреть/сделать, в каком порядке).
4. visit_min — [от, до] минут, реалистично и в рамках бюджета времени пользователя.
5. Если у кандидата open_state = "unknown", НЕ пиши, что место открыто; можно посоветовать уточнить часы.
6. Учитывай погоду, время суток, спутников (дети), ограничения. Разнообразь выбор, если запрос это допускает.
7. ideas — 0–2 короткие творческие идеи (до 160 символов) без опоры на базу; новых названий заведений не придумывай.
8. Никогда не советуй опасное или незаконное (выход на лёд, крыши, стройки, заброшки) — предложи безопасную альтернативу. Если место из запроса закрыто или запрос не про Астану — честно скажи это в why и предложи лучшее из кандидатов.
9. Пиши на языке lang (ru — русский, kk — казахский, en — английский). Кратко и по делу.
Верни строго JSON: {"recommendations":[{"poi_id":"...","why":"...","what_to_do":"...","visit_min":[30,45]}],"ideas":[{"text":"..."}]}"""

MODE_RU = {"walk": "пешком", "car": "на машине/такси", "transit": "на транспорте"}


def candidate_payload(c: Cand, ctx: Ctx) -> dict:
    p = c.poi
    d = {
        "poi_id": p["id"], "name": p["name"], "category": p.get("category"), "tags": p.get("tags") or [],
        "description": (p.get("description") or "")[:300], "distance_m": c.dist_m,
        "travel_min": c.travel_min, "open_state": c.open.state, "hours_confidence": c.open.confidence,
        "hours_label": c.open.label, "typical_visit_min": list(c.visit),
        "rating": p.get("rating"), "indoor": p.get("indoor"), "price_level": p.get("price_level"),
        "kid_friendly": p.get("kid_friendly"), "wheelchair": p.get("wheelchair"), "address": p.get("address"),
    }
    if ctx.flight:
        d["minutes_to_airport_after"] = c.back_min
    return {k: v for k, v in d.items() if v not in (None, [], "")}


def build_user_prompt(query: str, ctx: Ctx, cands: list[Cand]) -> str:
    context = {
        "lang": ctx.lang,
        "local_time": ctx.when.strftime("%A %H:%M"),
        "weather": ctx.weather.label("ru") if ctx.weather else None,
        "mode": MODE_RU.get(ctx.mode, ctx.mode),
        "time_budget_min": ctx.budget,
        "available_min_for_visit_and_travel": ctx.available,
        "companions": "kids" if ctx.with_kids else ctx.parsed["companions"],
        "constraints": ctx.parsed["constraints"],
        "flight_soon": ctx.flight,
    }
    return json.dumps({"query": query, "context": context,
                       "candidates": [candidate_payload(c, ctx) for c in cands]}, ensure_ascii=False)


# ---------------- шаблоны (деградация / fallback валидатора) ----------------

_DO = {
    "ru": {
        "park": "Пройдитесь по главной аллее, загляните к воде или на видовые точки и вернитесь кольцом.",
        "museum": "Начните с главной экспозиции, отметьте 2–3 зала по интересам; проверьте, есть ли интерактив.",
        "gallery": "Посмотрите текущую выставку, начните с центрального зала.",
        "mall": "Зайдите погреться, выпейте кофе; при желании — кино или фуд-корт.",
        "cafe": "Возьмите напиток, займите столик у окна; уточните про розетки и Wi-Fi у бариста.",
        "landmark": "Осмотрите снаружи, сделайте фото с лучшего ракурса и пройдитесь по округе.",
        "monument": "Подойдите ближе, прочитайте табличку и сделайте фото.",
        "viewpoint": "Поднимитесь на смотровую, посмотрите на город, сделайте панорамные фото.",
        "religious": "Осмотрите здание снаружи и внутри в часы посещения; одежда — скромная.",
        "playground": "Дайте детям поиграть, присмотрите скамейку рядом.",
        "kids": "Выберите 1–2 активности по возрасту ребёнка.",
        "_": "Загляните, осмотритесь и решите, задержаться ли подольше.",
    },
    "en": {
        "park": "Walk the main alley, stop by the water or viewpoints, and loop back.",
        "museum": "Start with the main exhibition and pick 2–3 halls; look for interactive sections.",
        "mall": "Warm up inside, grab a coffee; cinema or food court if you like.",
        "cafe": "Get a drink and a table by the window; ask about sockets and Wi-Fi.",
        "landmark": "See it from outside, take photos from the best angle and stroll around.",
        "viewpoint": "Go up to the observation deck and take panoramic photos.",
        "_": "Drop in, look around and decide whether to stay longer.",
    },
    "kk": {
        "park": "Басты аллеямен серуендеп, су жағасына барып, айналып қайтыңыз.",
        "museum": "Негізгі экспозициядан бастап, 2–3 залды таңдаңыз.",
        "mall": "Ішке кіріп жылынып, кофе ішіңіз; қаласаңыз — кино немесе фуд-корт.",
        "cafe": "Сусын алып, терезе жанына отырыңыз; розетка мен Wi-Fi туралы сұраңыз.",
        "landmark": "Сырттан қарап, суретке түсіп, айналасын аралаңыз.",
        "viewpoint": "Шолу алаңына көтеріліп, панорамалық сурет түсіріңіз.",
        "_": "Кіріп, айналаны қарап шығыңыз.",
    },
}
_TAG_WORD = {
    "ru": {"quiet": "тихое место", "coffee": "есть кофе", "sockets": "есть розетки", "wifi": "есть Wi-Fi",
           "kids": "подходит детям", "interactive": "интерактив", "indoor": "в помещении", "night": "работает допоздна",
           "view": "хороший вид", "free": "бесплатно", "unusual": "необычное", "walk": "для прогулки", "playground": "детская площадка"},
    "en": {"quiet": "quiet", "coffee": "coffee", "sockets": "sockets", "wifi": "Wi-Fi", "kids": "kid-friendly",
           "interactive": "interactive", "indoor": "indoors", "night": "lively at night", "view": "great view",
           "free": "free", "unusual": "unusual", "walk": "good for a walk", "playground": "playground"},
    "kk": {"quiet": "тыныш орын", "coffee": "кофе бар", "sockets": "розетка бар", "kids": "балаларға қолайлы",
           "interactive": "интерактив", "indoor": "ғимарат ішінде", "view": "әдемі көрініс", "free": "тегін",
           "unusual": "ерекше", "walk": "серуенге"},
}


def template_why(c: Cand, ctx: Ctx) -> str:
    lang = ctx.lang if ctx.lang in _DO else "ru"
    p = c.poi
    mode_word = {"ru": {"walk": "пешком", "car": "на машине", "transit": "на транспорте"},
                 "en": {"walk": "on foot", "car": "by car", "transit": "by transit"},
                 "kk": {"walk": "жаяу", "car": "көлікпен", "transit": "көлікпен"}}[lang][ctx.mode]
    dist = f"{c.dist_m / 1000:.1f} км" if c.dist_m >= 1000 else f"{c.dist_m} м"
    if lang == "en":
        dist = dist.replace("км", "km").replace(" м", " m")
    head = {"ru": f"{dist}, ~{c.travel_min} мин {mode_word}",
            "en": f"{dist}, ~{c.travel_min} min {mode_word}",
            "kk": f"{dist}, ~{c.travel_min} мин {mode_word}"}[lang]
    if c.dist_m < 150:
        head = {"ru": "Вы уже рядом", "en": "You are right here", "kk": "Сіз жақын тұрсыз"}[lang]
    wanted = set(ctx.parsed["constraints"]) | ({"kids"} if ctx.with_kids else set())
    tags = [t for t in (p.get("tags") or []) if t in _TAG_WORD[lang]]
    tags.sort(key=lambda t: t not in wanted)
    bits = [head] + [_TAG_WORD[lang][t] for t in tags[:2]]
    if isinstance(p.get("rating"), (int, float)):
        bits.append({"ru": "рейтинг", "en": "rating", "kk": "рейтинг"}[lang] + f" {p['rating']:.1f}")
    s = "; ".join(bits) + "."
    desc = re.sub(r"\s*по адресу:[^.]*\.?", ".", (p.get("description") or "").strip()).replace("..", ".")
    if re.search(r"[әғқңөұүһі]", desc.lower()) or desc.strip(". ") == "":
        desc = ""  # адреса/названия на казахском ломают язык ответа
    if desc and lang == "ru" and len(s) + len(desc) + 1 <= 200:
        s = f"{s} {desc}"
    return s[:200]


def template_do(c: Cand, ctx: Ctx) -> str:
    lang = ctx.lang if ctx.lang in _DO else "ru"
    table = _DO[lang]
    return table.get(c.poi.get("category", ""), table["_"])

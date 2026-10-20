"""Генерация: LLM видит ТОЛЬКО кандидатов; шаблонные тексты для режима деградации."""
from __future__ import annotations

import json
import re

from .rank import Cand, Ctx

GEN_SYSTEM = """Ты — «Серуен», городской гид по Астане. Тебе дают запрос пользователя, контекст и список КАНДИДАТОВ из базы POI.
Правила:
1. Выбери 1–3 места ТОЛЬКО из кандидатов (по poi_id). Не упоминай в recommendations места вне списка.
2. ФАКТЫ О МЕСТЕ — ТОЛЬКО из полей кандидата (facts, tags, description, hours_label, rating). Нельзя добавлять удобства, услуги и ассортимент, которых там нет (бассейн, Wi-Fi, парковка, терраса, меню, «ассортимент обуви», аттракционы…). Если данных мало — пиши проще («кафе рядом с хорошим рейтингом»), но не выдумывай.
3. why — до 180 символов: почему это место подходит именно под запрос; опирайся на конкретный факт из данных кандидата (теги, описание, часы, рейтинг, погода/время суток). Метры и минуты пути уже показаны в карточке — не начинай с них и не повторяй их без нужды. Не выдумывай факты.
4. what_to_do — до 230 символов: конкретное действие или мини-план на месте (что посмотреть/сделать, в каком порядке).
5. visit_min — [от, до] минут, реалистично и в рамках бюджета времени пользователя.
6. Если у кандидата open_state = "unknown", НЕ пиши, что место открыто; можно посоветовать уточнить часы.
7. Кандидат с user_is_already_here — место, где пользователь уже стоит: не выбирай его для прогулки (можно упомянуть в ideas).
8. Если в контексте есть required — пользователь назвал конкретный объект/занятие; все кандидаты ему соответствуют, ничего другого не предлагай. Если shopping = true — это утилитарный запрос: why коротко и практично (ближайший, открыт ли, расстояние уместно), what_to_do — практичный совет; тег budget означает «сеть с невысокими ценами (оценка)», не пиши уверенно «дёшево».
9. Учитывай погоду, время суток, спутников (дети), ограничения. Разнообразь выбор, если запрос это допускает.
10. ideas — 0–2 короткие творческие идеи (до 160 символов) без опоры на базу; новых названий заведений не придумывай.
11. Никогда не советуй опасное или незаконное (выход на лёд, крыши, стройки, заброшки) — предложи безопасную альтернативу. Если место из запроса закрыто или запрос не про Астану — честно скажи это в why и предложи лучшее из кандидатов.
12. Пиши на языке lang (ru — русский, kk — казахский, en — английский). Кратко и по делу.
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
    from .search import CATEGORY_RU, TAG_RU
    d["facts"] = [f for f in [CATEGORY_RU.get(p.get("category", ""), "").split(" ")[0]]
                  + [TAG_RU.get(t, "").split(" ")[0] for t in (p.get("tags") or []) if TAG_RU.get(t)] if f]
    if ctx.flight:
        d["minutes_to_airport_after"] = c.back_min
    if c.here:
        d["user_is_already_here"] = True
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
    if ctx.needs:
        from . import needs as needs_mod
        context["required"] = needs_mod.labels(ctx.needs, "ru")
        context["shopping"] = needs_mod.is_shopping(ctx.needs)
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
        "wellness": "Возьмите купальные принадлежности/форму и сменную обувь; уточните расписание сеансов и цены по телефону.",
        "sport": "Уточните расписание и прокат инвентаря перед выходом.",
        "cinema": "Посмотрите расписание сеансов и возьмите билеты онлайн, чтобы не стоять в очереди.",
        "theatre": "Проверьте афишу на сегодня и приходите за 15–20 минут до начала.",
        "supermarket": "Продукты и товары на каждый день; на кассах самообслуживания обычно быстрее.",
        "convenience": "Магазин у дома: вода, перекус и самое нужное — зайдёте и выйдете за пару минут.",
        "pharmacy": "Лекарства и товары для здоровья; рецептурные препараты — уточните у фармацевта.",
        "clothes": "Посмотрите текущие коллекции и акции; перед покупкой сравните цены в соседних магазинах.",
        "shop": "Если нужен конкретный товар — уточните наличие по телефону, если он указан.",
        "bar": "Посмотрите меню и спокойно проведите вечер; закажите такси заранее, если возвращаться поздно.",
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
_REASON = {
    "ru": {"quiet": "тихое место, как вы просили", "coffee": "есть кофе", "sockets": "есть розетки для ноутбука",
           "wifi": "есть Wi-Fi", "kids": "подходит для детей", "interactive": "есть интерактив",
           "night": "работает допоздна", "unusual": "необычный формат", "view": "красивые виды и фото",
           "indoor": "можно провести время в тепле", "outdoor_ok": "можно погулять на свежем воздухе",
           "food": "можно поесть", "free": "бесплатно",
           "intent_walk": "зелёная зона для прогулки", "intent_culture": "культурная программа",
           "intent_sightseeing": "одна из достопримечательностей города", "intent_kids": "место для детей",
           "intent_shopping": "магазины и развлечения под одной крышей",
           "cold": "в мороз и ветер — под крышей", "pleasant": "хорошая погода для улицы",
           "late": "открыто и поздно вечером", "near": "совсем рядом", "rating": "высокий рейтинг",
           "fallback": "подходит под ваш запрос по данным базы"},
    "en": {"quiet": "a quiet place, as you asked", "coffee": "serves coffee", "sockets": "has sockets for a laptop",
           "wifi": "has Wi-Fi", "kids": "good for kids", "interactive": "interactive exhibits",
           "night": "open late", "unusual": "an unusual format", "view": "great views and photos",
           "indoor": "you can stay warm indoors", "outdoor_ok": "a fresh-air walk", "food": "you can eat here",
           "free": "free", "intent_walk": "a green area for a walk", "intent_culture": "a cultural stop",
           "intent_sightseeing": "one of the city sights", "intent_kids": "a place for kids",
           "intent_shopping": "shops and fun under one roof", "cold": "indoors — out of the frost and wind",
           "pleasant": "nice weather to be outside", "late": "open late in the evening", "near": "very close",
           "rating": "highly rated", "fallback": "matches your request in our data"},
    "kk": {"quiet": "тыныш орын", "coffee": "кофе бар", "sockets": "ноутбукқа розетка бар", "wifi": "Wi-Fi бар",
           "kids": "балаларға қолайлы", "interactive": "интерактив бар", "night": "кешке дейін ашық",
           "unusual": "ерекше формат", "view": "әдемі көрініс", "indoor": "жылы жерде уақыт өткізуге болады",
           "outdoor_ok": "таза ауада серуендеуге болады", "food": "тамақтануға болады", "free": "тегін",
           "intent_walk": "серуенге арналған жасыл аймақ", "intent_culture": "мәдени бағдарлама",
           "intent_sightseeing": "қаланың көрікті жерлерінің бірі", "intent_kids": "балаларға арналған орын",
           "intent_shopping": "дүкендер мен ойын-сауық бір жерде", "cold": "аязда — жылы жерде",
           "pleasant": "серуенге жақсы ауа райы", "late": "кешке дейін ашық", "near": "өте жақын",
           "rating": "жоғары рейтинг", "fallback": "сұранысыңызға сай келеді"},
}


_CAT_REASON = {  # если явных совпадений нет — чем место полезно по своей категории
    "ru": {"park": "зелёная зона, где можно пройтись", "monument": "заметное место города, хорошо для фото",
           "landmark": "заметное место города, стоит увидеть", "cafe": "можно передохнуть за кофе",
           "restaurant": "можно спокойно поесть", "mall": "тепло, магазины и кафе под одной крышей",
           "museum": "культурная программа", "gallery": "выставки и искусство", "theatre": "вечерняя программа",
           "cinema": "кино в тепле", "religious": "архитектура и спокойная атмосфера", "bar": "вечерняя атмосфера",
           "entertainment": "развлечения", "library": "тихо и можно посидеть", "market": "местная еда и колорит",
           "sport": "активный отдых", "viewpoint": "вид на город", "wellness": "спорт и отдых для тела",
           "supermarket": "продукты", "convenience": "магазин у дома", "clothes": "одежда и обувь",
           "pharmacy": "аптека", "shop": "магазин"},
    "en": {"park": "a green area for a stroll", "monument": "a city landmark, good for photos",
           "landmark": "a notable city sight", "cafe": "a coffee break", "restaurant": "a relaxed meal",
           "mall": "warm, with shops and cafes", "museum": "a cultural stop", "gallery": "exhibitions and art",
           "theatre": "an evening show", "cinema": "a movie indoors", "religious": "architecture and calm",
           "bar": "evening atmosphere", "library": "quiet place to sit", "viewpoint": "city views"},
    "kk": {"park": "серуендеуге жасыл аймақ", "monument": "қаланың белгілі орны, суретке қолайлы",
           "landmark": "қаланың көрікті орны", "cafe": "кофе ішіп демалуға болады", "restaurant": "тамақтануға болады",
           "mall": "жылы, дүкендер мен кафелер бар", "museum": "мәдени бағдарлама", "theatre": "кешкі бағдарлама"},
}


def why_reasons(c: Cand, ctx: Ctx) -> list[str]:
    """Причины выбора (совпадение с запросом, погода, время) — ключи _REASON, по убыванию важности."""
    from .rank import INTENT_CATEGORIES, _is_kid_ok, _soft
    p = c.poi
    keys: list[str] = []
    if ctx.with_kids and _is_kid_ok(p):
        keys.append("kids")
    for con in ctx.parsed["constraints"]:
        if con in ("flight_soon", "accessibility") or con in keys:
            continue
        if _soft(con, p, c):
            keys.append(con)
    intent = ctx.parsed["intent"]
    if (p.get("category") in INTENT_CATEGORIES.get(intent, set()) and f"intent_{intent}" in _REASON["ru"]
            and not (intent == "kids" and "kids" in keys)):
        keys.append(f"intent_{intent}")
        if intent == "walk" and "outdoor_ok" in keys:
            keys.remove("outdoor_ok")
    wx = ctx.weather
    if wx and wx.bad and p.get("indoor") is True and "indoor" not in keys:
        keys.append("cold")
    elif wx and wx.pleasant and p.get("indoor") is False and "outdoor_ok" not in keys:
        keys.append("pleasant")
    if (ctx.when.hour >= 21 or ctx.when.hour < 5) and c.open.open_late and "night" not in keys:
        keys.append("late")
    if c.travel_min <= 5 and c.dist_m >= 150:
        keys.append("near")
    return keys


def _need_label(c: Cand, ctx: Ctx, lang: str) -> str | None:
    from . import needs as needs_mod
    k = next((k for k in ctx.needs if needs_mod.BY_KEY[k].matches(c.poi)), ctx.needs[0] if ctx.needs else None)
    return needs_mod.BY_KEY[k].label.get(lang, needs_mod.BY_KEY[k].label["ru"]) if k else None


def shopping_why(c: Cand, ctx: Ctx) -> str:
    """Утилитарный запрос (магазин, аптека): коротко и практично, расстояние уместно."""
    lang = ctx.lang if ctx.lang in ("ru", "en", "kk") else "ru"
    label = _need_label(c, ctx, lang) or ""
    tags0 = set(c.poi.get("tags") or [])
    if "shop_24_7" in ctx.needs and "24_7" not in tags0 and not c.open.open_late:
        label = {"ru": "магазин, открытый сейчас", "en": "shop open now", "kk": "қазір ашық дүкен"}[lang]
    dist = f"{c.dist_m / 1000:.1f} км" if c.dist_m >= 1000 else f"{c.dist_m} м"
    if lang == "en":
        dist = dist.replace("км", "km").replace(" м", " m")
    parts = [{"ru": f"{label[:1].upper()}{label[1:]} рядом — {dist}", "en": f"{label.capitalize()} nearby — {dist}",
              "kk": f"{label.capitalize()} жақын — {dist}"}[lang]]
    tags = set(c.poi.get("tags") or [])
    if "24_7" in tags or c.open.open_late:
        parts.append({"ru": "работает допоздна или круглосуточно (по данным базы)", "en": "open late or 24/7 (per our data)",
                      "kk": "кешке дейін немесе тәулік бойы ашық"}[lang])
    if "budget" in tags:
        parts.append({"ru": "сеть с невысокими ценами (оценка)", "en": "a lower-priced chain (estimate)",
                      "kk": "бағасы қолжетімді желі (бағалау)"}[lang])
    return ("; ".join(parts) + ".")[:200]


def template_why(c: Cand, ctx: Ctx) -> str:
    from . import needs as needs_mod
    lang = ctx.lang if ctx.lang in _REASON else "ru"
    if needs_mod.is_shopping(ctx.needs):
        return shopping_why(c, ctx)
    r = _REASON[lang]
    keys = why_reasons(c, ctx)[:3]
    phrases = [r[k] for k in keys] or [_CAT_REASON[lang].get(c.poi.get("category", ""), r["fallback"])]
    if ctx.needs:
        label = _need_label(c, ctx, lang)
        phrases = [{"ru": f"{label} — то, что вы искали", "en": f"{label} — what you asked for",
                    "kk": f"{label} — сіз іздеген орын"}[lang]] + phrases[:1]
    rating = c.poi.get("rating")
    if isinstance(rating, (int, float)) and rating >= 4.6 and len(phrases) < 3:
        phrases.append(f"{r['rating']} {rating:.1f}")
    s = "; ".join(phrases)
    s = s[0].upper() + s[1:] + "."
    p = c.poi
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

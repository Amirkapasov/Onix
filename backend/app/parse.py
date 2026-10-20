"""Разбор запроса: правила на регулярках (всегда) + опционально LLM, явные фильтры UI главнее."""
from __future__ import annotations

import re

from . import needs as needs_mod

INTENTS = ["walk", "coffee", "kids", "sightseeing", "night", "food", "culture", "shopping", "work", "wellness",
           "sport", "entertainment", "other"]
COMPANIONS = ["solo", "kids", "group", "couple"]
CONSTRAINTS = ["quiet", "sockets", "wifi", "coffee", "indoor", "outdoor_ok", "night", "unusual",
               "accessibility", "flight_soon", "free", "view", "interactive", "food"]

# (регулярка, ограничение) — по корням, чтобы ловить падежи
_CONSTRAINT_RULES: list[tuple[str, str]] = [
    (r"тих|спокойн|без шума|quiet|calm|тыныш", "quiet"),
    (r"розетк|заряд|ноутбук|ноут\b|поработ|socket|charg|laptop|розетка", "sockets"),
    (r"wi-?fi|вайфай|вай-фай|интернет", "wifi"),
    (r"коф|капучино|латте|\bчай|coffee|кафе|cafe", "coffee"),
    (r"в помещени|в тепл|внутри|indoor|под крыш|жылы жер|ішінде|холодно|мороз|(?<!\d)[−-]\s?\d\d\b", "indoor"),
    (r"прогул|погулять|пройтись|на воздух|walk|серуен|қыдыр", "outdoor_ok"),
    (r"ночн|ночью|ноч[ьи]|поздн|после полуноч|night|late|түнгі|түнде", "night"),
    (r"необычн|нестандарт|уникальн|странн|интересн|unusual|unique|weird|ерекше|қызық", "unusual"),
    (r"коляск|инвалид|доступн(ая|ое|ый) среда|пандус|маломобильн|wheelchair|accessib|мүмкіндігі шектеулі", "accessibility"),
    (r"вылет|рейс|самол[её]т|аэропорт|пересадк|flight|airport|layover|ұшақ|әуежай", "flight_soon"),
    (r"бесплатн|без денег|free|тегін", "free"),
    (r"вид на|панорам|смотров|view|панорама", "view"),
    (r"интерактив|interactive|потрогать", "interactive"),
    (r"поесть|покушать|обед|ужин|ресторан|\bеда\b|\beat\b|food|dinner|lunch|тамақ", "food"),
]
_KIDS_RE = r"ребён|ребен|дет(ьми|ей|и|ск)|сын|доч|малыш|kid|child|бала|балалар"
_GROUP_RE = r"компани|друзь|группой|нас \d|нас (трое|четверо|пятеро)|group|friends|достар"
_COUPLE_RE = r"с девушк|с парн|с женой|с мужем|вдвоём|вдвоем|свидан|date|couple"


def _num(s: str) -> float:
    s = s.replace(",", ".")
    words = {"пол": 0.5, "полтора": 1.5, "полчаса": 0.5, "один": 1, "одного": 1, "два": 2, "пару": 2,
             "пара": 2, "три": 3, "четыре": 4, "пять": 5, "час": 1, "бір": 1, "екі": 2, "үш": 3}
    return words[s] if s in words else float(s)


_NUM = r"(\d+(?:[.,]\d+)?|полтора|один|одного|два|пару|пара|три|четыре|пять|бір|екі|үш)"
_RANGE = rf"{_NUM}\s*(?:[-–—]|до)\s*{_NUM}"


def parse_time_budget(q: str) -> int | None:
    """«30–60 минут» → 60, «1–2 часа» → 120, «2 часа» → 120, «полчаса» → 30, «час» → 60."""
    t = q.lower()
    m = re.search(rf"{_RANGE}\s*(мин|час|ч\b|h\b|hour|min|сағ)", t)
    if m:
        hi = _num(m.group(2))
        return int(hi * (1 if m.group(3).startswith(("мин", "min")) else 60))
    m = re.search(rf"{_NUM}\s*(минут|мин|min|час|ч\b|h\b|hour|сағат|сағ)", t)
    if m:
        v = _num(m.group(1))
        return int(v * (1 if m.group(2).startswith(("мин", "min")) else 60))
    m = re.search(rf"\b(час[а-я]*|минут[а-я]*) на {_NUM}\b", t)  # «часа на два», «минут на сорок» не ловим
    if m and m.group(1).startswith("час"):
        return int(_num(m.group(2)) * 60)
    if re.search(r"полчаса|half an hour|жарты сағат", t):
        return 30
    if re.search(r"полтора часа", t):
        return 90
    if re.search(r"\bчас\b|an hour|бір сағат|на час", t):
        return 60
    return None


def parse_temperature(q: str) -> float | None:
    """Температура, упомянутая в запросе («на улице −20»)."""
    m = re.search(r"(?<![\d–-])([−–-]\s?\d{1,2}|\+\s?\d{1,2})(?!\d)\s*(°|градус|c\b|с\b)?", q.lower())
    if not m:
        return None
    raw = m.group(1).replace(" ", "")
    if raw[0] in "−–-" and (m.group(2) or re.search(r"мороз|на улице|холод|outside|degrees|аяз", q.lower())):
        return -float(raw[1:])
    if raw[0] == "+" and m.group(2):
        return float(raw[1:])
    return None


def detect_lang(q: str) -> str:
    if re.search(r"[әғқңөұүһі]", q.lower()):
        return "kk"
    if re.search(r"[а-яё]", q.lower()):
        return "ru"
    return "en"


_STOP = set("я мы вы ты он она хочу хотим хотел бы что где как куда можно сейчас возле рядом около недалеко "
            "от меня мне нас на в во с со и или у к по за до из для это есть посоветуете посоветуйте "
            "подскажите какое какой какая какие место места минут минуты час часа часов перед "
            "i want to the a an near me some for with is are what where and or".split())


def keywords(q: str) -> list[str]:
    words = re.findall(r"[a-zа-яёәғқңөұүһі]+", q.lower())
    return [w for w in words if len(w) > 2 and w not in _STOP][:8]


def rule_parse(query: str, lang: str | None = None) -> dict:
    q = query.lower()
    cons = [c for rx, c in _CONSTRAINT_RULES if re.search(rx, q)]
    companions = "solo"
    if re.search(_KIDS_RE, q):
        companions = "kids"
    elif re.search(_GROUP_RE, q):
        companions = "group"
    elif re.search(_COUPLE_RE, q):
        companions = "couple"
    if "coffee" in cons and "sockets" in cons:
        intent = "work"
    elif "flight_soon" in cons:
        intent = "sightseeing"
    elif companions == "kids":
        intent = "kids"
    elif "night" in cons:
        intent = "night"
    elif "coffee" in cons:
        intent = "coffee"
    elif "food" in cons:
        intent = "food"
    elif re.search(r"музе|выставк|галере|театр|museum|gallery|мұражай", q):
        intent = "culture"
    elif re.search(r"достопримеч|посмотреть|увидеть|турист|sight|see|көрікті", q) or "view" in cons:
        intent = "sightseeing"
    elif re.search(r"магазин|шопинг|купить|shopping|сауда", q):
        intent = "shopping"
    elif "outdoor_ok" in cons:
        intent = "walk"
    else:
        intent = "other"
    found = needs_mod.detect(query)
    if found and intent in ("other", "walk", "sightseeing", "coffee", "food", "shopping", "culture"):
        intent = needs_mod.intent_for(found) or intent
    return {
        "intent": intent,
        "needs": found,
        "time_budget_min": parse_time_budget(q),
        "companions": companions,
        "constraints": cons,
        "keywords": keywords(query),
        "lang": lang or detect_lang(query),
        "temperature_hint": parse_temperature(query),
    }


def merge_llm(rules: dict, llm: dict | None) -> dict:
    """LLM дополняет правила; правила не теряются (fallback), мусор от LLM отбрасывается."""
    if not llm:
        return rules
    out = dict(rules)
    if llm.get("intent") in INTENTS and (rules["intent"] == "other" or llm["intent"] != "other"):
        out["intent"] = llm["intent"]
    tb = llm.get("time_budget_min")
    if rules["time_budget_min"] is None and isinstance(tb, (int, float)) and 5 <= tb <= 600:
        out["time_budget_min"] = int(tb)
    if llm.get("companions") in COMPANIONS and rules["companions"] == "solo":
        out["companions"] = llm["companions"]
    cons = list(rules["constraints"])
    for c in llm.get("constraints") or []:
        if c in CONSTRAINTS and c not in cons:
            cons.append(c)
    out["constraints"] = cons
    extra = [k for k in (llm.get("needs") or []) if k in needs_mod.BY_KEY and k not in out.get("needs", [])]
    if extra:
        out["needs"] = list(out.get("needs", [])) + extra
        if out["intent"] == "other":
            out["intent"] = needs_mod.intent_for(out["needs"]) or "other"
    kws = [str(k).lower()[:30] for k in (llm.get("keywords") or []) if isinstance(k, str)]
    if kws:
        out["keywords"] = list(dict.fromkeys(kws + rules["keywords"]))[:10]
    return out


PARSE_SYSTEM = (
    "Ты разбираешь запрос пользователя городского гида по Астане. Верни ТОЛЬКО JSON:\n"
    '{"intent": one of ' + str(INTENTS) + ', "time_budget_min": int|null (верхняя граница, '
    '"30–60 минут" → 60, "2 часа" → 120), "companions": one of ' + str(COMPANIONS) + ', '
    '"constraints": subset of ' + str(CONSTRAINTS) + ', "keywords": [до 6 коротких ключевых слов по-русски '
    'для поиска мест, включая синонимы], "lang": "ru"|"kk"|"en", "needs": subset of '
    + str(list(needs_mod.BY_KEY)) + ' — ТОЛЬКО если человек явно назвал объект, занятие или покупку}.\n'
    "flight_soon — если человек скоро улетает. Не придумывай то, чего нет в запросе."
)

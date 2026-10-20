"""Предметные предупреждения по правилам (работают и без LLM): опасные затеи, другой город,
место из запроса закрыто."""
from __future__ import annotations

import re

from . import config, geo
from .search import tokenize

_DANGER_RE = re.compile(
    r"\bл[её]д\b|\bльду\b|(?<!под )\bкрыш[аеиуы]?\b|\bзалез|\bстройк|\bзаброш|руфинг|\brooftop(?! bar)|"
    r"\bon the ice\b|frozen river|\babandoned\b|\bмұз|\bтөбесіне", re.I)
# Фразы в текстах ответа, которые нельзя оставлять (на случай, если LLM их напишет)
DANGER_ADVICE_RE = re.compile(
    r"[^.!?]*(?<!не )(залез\w*|выйд\w* на л[её]д|пройд\w* по льду|по льду|на крыш\w*|climb \w* roof|on the ice)[^.!?]*[.!?]?\s*",
    re.I)

_OTHER_PLACES = {
    "алмат": "Алматы", "almaty": "Алматы", "медеу": "Медеу (Алматы)", "medeu": "Медеу (Алматы)",
    "шымбулак": "Шымбулак (Алматы)", "shymbulak": "Шымбулак (Алматы)", "шымкент": "Шымкент",
    "караганд": "Караганда", "бурабай": "Бурабай", "боровое": "Бурабай", "актау": "Актау", "атырау": "Атырау",
    "тараз": "Тараз", "павлодар": "Павлодар", "кокшетау": "Кокшетау", "туркестан": "Туркестан",
    "ташкент": "Ташкент", "бишкек": "Бишкек", "москв": "Москва", "чарын": "Чарын",
}
ASTANA_RADIUS_M = 35000


def danger_warning(query: str, lang: str) -> str | None:
    if not _DANGER_RE.search(query or ""):
        return None
    return {"ru": "Безопасность: выходить на лёд Есиля, залезать на крыши и стройки опасно и запрещено. "
                  "Ниже — легальные видовые и освещённые места. Экстренная помощь — 112.",
            "en": "Safety: walking on the river ice or climbing roofs and construction sites is dangerous and illegal. "
                  "Below are legal viewpoints and well-lit places. Emergency: 112.",
            "kk": "Қауіпсіздік: Есіл мұзына шығу, төбелерге өрмелеу қауіпті және тыйым салынған. "
                  "Төменде — заңды көру алаңдары. Төтенше жағдай — 112."}.get(lang)


def scrub_danger(text: str) -> str:
    return DANGER_ADVICE_RE.sub("", text or "").strip()


def out_of_area_warning(query: str, start: tuple[float, float], lang: str) -> str | None:
    q = (query or "").lower()
    found = list(dict.fromkeys(v for k, v in _OTHER_PLACES.items() if k in q))
    if found:
        names = ", ".join(found)
        return {"ru": f"Я работаю только по Астане: {names} — вне зоны покрытия. Вот похожие места в Астане.",
                "en": f"I only cover Astana: {names} is out of coverage. Here are similar places in Astana.",
                "kk": f"Мен тек Астана бойынша жұмыс істеймін: {names} — қамтудан тыс. Астанадағы ұқсас орындар:"}.get(lang)
    if geo.haversine_m(*start, *config.CITY_CENTER) > ASTANA_RADIUS_M:
        return {"ru": "Похоже, вы вне Астаны — база мест покрывает только Астану.",
                "en": "You seem to be outside Astana — the places database covers Astana only.",
                "kk": "Сіз Астанадан тыс сияқтысыз — база тек Астананы қамтиды."}.get(lang)
    return None


def core_name(name: str) -> str:
    m = re.search(r"«([^»]+)»", name)
    return m.group(1) if m else name


GENERIC_WORDS = set(tokenize(
    "магазин магазины аптека продукты продуктовый сквер парк кафе кофейня ресторан столовая бар паб маркет "
    "минимаркет супермаркет детская площадка спортивная центр торговый дом фонтан памятник остановка стоянка "
    "парковка киоск павильон мини мечеть церковь библиотека музей кинотеатр театр бассейн сауна баня фитнес "
    "спортзал салон красоты магазинчик гастроном универсам аптечный пункт монумент трц тц жк "
    "shop store cafe park market pharmacy"))


def is_generic_name(name: str) -> bool:
    """«Магазин», «Аптека», «Продукты 24», «Сквер» — не имя конкретного места."""
    toks = [t for t in tokenize(core_name(name)) if not t.isdigit()]
    return not toks or all(t in GENERIC_WORDS for t in toks)


def mentioned_pois(query: str, pois: list[dict]) -> list[dict]:
    """POI, которые пользователь назвал в запросе (все значимые слова «ядра» названия есть в запросе).
    Общие слова («магазин», «аптека», «парк») именем конкретного места не считаются."""
    q = set(tokenize(query))
    if not q:
        return []
    out = []
    for p in pois:
        names = [core_name(p["name"])] + list((p.get("name_i18n") or {}).values())
        if is_generic_name(p["name"]):
            continue
        for n in names:
            toks = [t for t in tokenize(core_name(n)) if len(t) >= 3]
            toks = [t for t in toks if t not in GENERIC_WORDS] or toks  # «Монумент-Бәйтерек» ≈ «Байтерек»
            if toks and len(" ".join(toks)) >= 5 and all(t in q for t in toks):
                out.append(p)
                break
    return out[:3]


def closed_mention_warning(p: dict, label: str, lang: str) -> str:
    name = core_name(p["name"])
    return {"ru": f"«{name}» к вашему приходу закрыт: {label}. Предлагаю открытые места рядом.",
            "en": f"“{name}” will be closed when you arrive: {label}. Here are open places nearby.",
            "kk": f"«{name}» жабық: {label}. Жақын ашық орындар ұсынылады."}.get(lang, "")

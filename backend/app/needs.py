"""Явные потребности в запросе («бассейн», «аптека», «Магнум», «кино»…) — ЖЁСТКИЙ фильтр кандидатов.

Если пользователь назвал объект или занятие, в рекомендации идут только места, которые ему соответствуют
по категории, тегам или названию. Ближайшие кафе как «заглушка» не подставляются никогда.
Работает без LLM (словарь ru/kk/en); LLM-разбор может только добавить ключи из этого же словаря.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SHOP_CATEGORIES = {"supermarket", "convenience", "clothes", "shop", "pharmacy"}


@dataclass(frozen=True)
class Need:
    key: str
    query_rx: str                     # что ищем в запросе
    label: dict                       # ru/en/kk — для предупреждений и context_used
    cats: frozenset = frozenset()     # подходящие категории
    tags: frozenset = frozenset()     # подходящие теги
    name_rx: str | None = None        # подходящее название
    strict: bool = False              # категории мало — нужен тег или название (wellness = и бассейн, и фитнес)
    shopping: bool = False
    intent: str = "other"
    soft_tags: frozenset = field(default_factory=frozenset)  # предпочтительные (не обязательные) теги
    theme: bool = False               # тема («вид», «культурно», «романтично») — популярность важнее близости
    extra: object = field(default=None, compare=False)  # доп. правило p -> bool (напр. ресторан с рейтингом ≥ 4.6)

    def matches(self, p: dict) -> bool:
        if self.theme and p.get("category") in THEME_NOT_CATS - self.cats:  # кафе с тегом view — не «смотровая»
            return bool(self.extra and self.extra(p))
        tags = set(p.get("tags") or [])
        if self.tags & tags:
            return True
        if self.name_rx and re.search(self.name_rx, (p.get("name") or "").lower()):
            return True
        if self.extra and self.extra(p):
            return True
        return not self.strict and p.get("category") in self.cats


THEME_NOT_CATS = frozenset({"cafe", "restaurant", "bar", "nightlife", "mall", "playground"})


def _n(key, rx, ru, en, kk, cats=(), tags=(), name_rx=None, strict=False, shopping=False, intent="other", soft=(),
       theme=False, extra=None):
    return Need(key, rx, {"ru": ru, "en": en, "kk": kk}, frozenset(cats), frozenset(tags), name_rx, strict,
                shopping, intent, frozenset(soft), theme, extra)


def _tags(p: dict) -> set:
    return set(p.get("tags") or [])


NEEDS: list[Need] = [
    # --- досуг / спорт / здоровье ---
    _n("swimming", r"бассейн|поплава|плава(ть|ние|ем)|аквапарк|\bpool\b|swim|жүзу|бассейн",
       "бассейн", "swimming pool", "бассейн", cats=("wellness", "sport", "entertainment"),
       tags=("swimming", "pool", "aquapark"), name_rx=r"бассейн|аквапарк|плават|\bpool|swim|aqua", strict=True,
       intent="wellness"),
    _n("fitness", r"спортзал|фитнес|качалк|тренаж[её]р|\bgym\b|fitness|кроссфит|crossfit|workout",
       "фитнес / спортзал", "gym / fitness", "фитнес", cats=("wellness", "sport"), tags=("fitness", "gym"),
       name_rx=r"фитнес|fitness|\bgym|тренаж|спортзал|кроссфит|crossfit", strict=True, intent="wellness"),
    _n("spa", r"(?<![а-яa-z])спа(?![а-я])|\bspa\b|саун|(?<![а-я])бан[яюиь](?![а-я])|хаммам|hammam|sauna|массаж|монша",
       "спа / сауна", "spa / sauna", "спа / сауна", cats=("wellness",), tags=("spa", "sauna", "bath", "massage"),
       name_rx=r"(?<![а-я])спа(?![а-я])|\bspa\b|саун|(?<![а-я])бан[яи](?![а-я])|хаммам|sauna|массаж", strict=True,
       intent="wellness"),
    _n("skating", r"\bкат(ок|ке|ка)\b|коньк|skating|ice rink|сырғанау",
       "каток", "ice rink", "сырғанақ", cats=("sport", "entertainment"), tags=("ice_rink", "skating"),
       name_rx=r"каток|ледов|\bice\b", strict=True, intent="sport"),
    _n("bowling", r"боулинг|bowling", "боулинг", "bowling", "боулинг", tags=("bowling",),
       name_rx=r"боулинг|bowling", strict=True, intent="entertainment"),
    _n("quest", r"квест|\bquest|escape ?room|эскейп", "квест", "escape room", "квест", tags=("quest",),
       name_rx=r"квест|quest|escape", strict=True, intent="entertainment"),
    _n("karaoke", r"караоке|karaoke", "караоке", "karaoke", "караоке", tags=("karaoke",),
       name_rx=r"караоке|karaoke", strict=True, intent="entertainment"),
    _n("cinema", r"(?<![а-я])кино(?![а-я])|кинотеатр|фильм|сеанс|cinema|movie|кинотеатр",
       "кино", "cinema", "кино", cats=("cinema",), name_rx=r"кино|cinema|imax", intent="culture"),
    _n("museum", r"музе|выставк|экспозиц|галере|museum|exhibit|gallery|мұражай|көрме",
       "музей / выставка", "museum / exhibition", "мұражай", cats=("museum", "gallery"),
       name_rx=r"музей|галере|museum|gallery", intent="culture"),
    _n("theatre", r"театр|спектакл|опер[аыуе]\b|балет|концерт|theat|ballet|opera|театр",
       "театр / концерт", "theatre / concert", "театр", cats=("theatre",), name_rx=r"театр|опера|балет|филармон",
       intent="culture"),
    _n("park", r"(?<![а-я])парк(е|и|а|ом|ов|ах|ам)?(?![а-я])|сквер|\bpark\b|саябақ", "парк", "park", "саябақ",
       cats=("park",), intent="walk"),
    _n("library", r"библиотек|library|кітапхана", "библиотека", "library", "кітапхана", cats=("library",),
       intent="culture"),
    _n("coworking", r"коворкинг|coworking", "коворкинг", "coworking", "коворкинг", cats=("coworking",),
       intent="work"),
    _n("religious", r"мечет|храм|церк|собор|синагог|mosque|church|cathedral|мешіт",
       "мечеть / храм", "mosque / church", "мешіт", cats=("religious",), intent="sightseeing"),
    _n("bar", r"(?<![а-я])бар(?![а-яь])|(?<![а-я])бары\b|(?<![а-я])паб|пив[оа]|коктейл|\bpub\b|\bbar\b|beer",
       "бар", "bar", "бар", cats=("bar", "nightlife"), intent="night"),
    _n("nightclub", r"ночн\w* клуб|дискотек|night ?club|тусовк", "ночной клуб", "nightclub", "түнгі клуб",
       cats=("nightlife",), name_rx=r"клуб|club", intent="night"),
    _n("playground", r"детск\w* площадк|площадк\w* для дет|playground|ойын алаң", "детская площадка",
       "playground", "балалар алаңы", cats=("playground", "kids"), intent="kids"),
    # занятия, которых в городе может не быть — только по названию/тегу; нет в базе → честное «нет мест для: …»
    _n("skiing", r"горнолыж|лыж|сноуборд|ski\b|skiing|snowboard|шаңғы", "горные лыжи / сноуборд", "skiing",
       "шаңғы", tags=("skiing", "ski"), name_rx=r"лыж|\bski|сноуборд|snowboard", strict=True, intent="sport"),
    _n("surfing", r"серф|surf|вейк|wake|кайт|kite", "серфинг / вейк", "surfing", "серфинг", tags=("surfing",),
       name_rx=r"серф|surf|вейк|wake|кайт|kite", strict=True, intent="sport"),
    _n("diving", r"дайв|diving|scuba", "дайвинг", "diving", "дайвинг", tags=("diving",), name_rx=r"дайв|div",
       strict=True, intent="sport"),
    _n("climbing", r"скалодром|скалолаз|climb|боулдеринг|bouldering", "скалодром", "climbing gym", "скалодром",
       tags=("climbing",), name_rx=r"скалодром|climb|боулдер", strict=True, intent="sport"),
    _n("golf", r"гольф|golf", "гольф", "golf", "гольф", tags=("golf",), name_rx=r"гольф|golf", strict=True,
       intent="sport"),
    _n("zoo", r"зоопарк|\bzoo\b|океанариум|oceanarium|аквариум|контактн\w* зоо|хайуанат", "зоопарк / океанариум",
       "zoo / oceanarium", "хайуанаттар бағы", tags=("zoo", "aquarium"), name_rx=r"зоопарк|\bzoo|океанариум|oceanarium|аквариум",
       strict=True, intent="entertainment"),
    _n("trampoline", r"батут|trampoline|джампинг", "батутный центр", "trampoline park", "батут",
       tags=("trampoline",), name_rx=r"батут|trampoline|jump", strict=True, intent="entertainment"),
    _n("paintball", r"пейнтбол|лазертаг|страйкбол|paintball|laser ?tag|airsoft", "пейнтбол / лазертаг",
       "paintball / laser tag", "пейнтбол", tags=("paintball", "lasertag"), name_rx=r"пейнтбол|лазертаг|paintball|laser",
       strict=True, intent="entertainment"),
    _n("horse", r"конн\w* (прогул|клуб|спорт)|верхов|лошад|ипподром|horse|riding|атқа міну", "верховая езда",
       "horse riding", "атқа міну", tags=("horse_riding",), name_rx=r"конн|ипподром|horse|equestr", strict=True,
       intent="sport"),
    # --- еда: конкретная потребность, сочетается с темами («прогуляться и поужинать») ---
    _n("food", r"поесть|покушать|пообедать|поужинать|(?<![а-я])обед|(?<![а-я])ужин|голод|ресторан|перекус|"
       r"(?<![а-я])еда(?![а-я])|\beat\b|\bfood\b|hungry|lunch|dinner|restaurant|тамақ|ас ішу|кешкі ас",
       "где поесть", "food", "тамақ", cats=("restaurant", "cafe"), intent="food"),
    # --- темы: жёсткий фильтр по теме, ранжирование «популярность → близость» ---
    _n("view", r"(?<![а-я])вид(?![а-яё]*(еть|ит|ел|ишь|им|ят))|видом|видами|панорам|смотров|красив|фотограф|сфоткать|"
       r"(?<![а-я])фото(?![а-я])|закат|\bview|panoram|scenic|sunset|көрініс|көркем|сурет", "красивый вид",
       "scenic view", "әдемі көрініс", cats=("viewpoint",), tags=("view",),
       name_rx=r"смотров|набережн|байтерек|бәйтерек|панорам",
       extra=lambda p: p.get("category") in ("landmark", "monument") and bool({"photo", "sight"} & _tags(p)),
       intent="sightseeing", theme=True),
    _n("walk", r"погулять|прогул|пройтись|подышать|воздух|\bwalk|stroll|серуендеу|қыдыр", "прогулка", "walk",
       "серуен", cats=("park", "viewpoint", "landmark", "monument"), tags=("walk", "view"),
       name_rx=r"бульвар|набережн|аллея|сквер|променад|саябақ", intent="walk", theme=True),
    _n("culture", r"культур|искусств|(?<![а-я])арт(?![а-я])|\bart\b|culture|cultural|мәдени|өнер",
       "культурная программа", "culture", "мәдени бағдарлама", cats=("museum", "gallery", "theatre"),
       tags=("culture", "art"), intent="culture", theme=True),
    _n("romantic", r"романти|свидани|вдво[её]м|с девушк|с парн|с женой|с мужем|\bdate\b|romantic|ғашық|махаббат",
       "романтичное место", "romantic place", "романтикалық орын", cats=("viewpoint", "park"), tags=("view",),
       name_rx=r"набережн|аллея|бульвар",
       extra=lambda p: p.get("category") == "restaurant" and (p.get("rating") or 0) >= 4.6,
       intent="sightseeing", theme=True),
    _n("unusual", r"необычн|интересн|нестандартн|уникальн|удиви|\bunusual|unique|weird|ерекше|қызық",
       "что-то необычное", "something unusual", "ерекше нәрсе", cats=("entertainment", "gallery", "museum"),
       tags=("unusual", "interactive", "art"), intent="culture", theme=True),
    _n("night", r"ночн|ночью|после 2[2-4]|после полуноч|(?<![а-я])поздно|\bnight|\blate\b|түнде|түнгі",
       "ночной досуг", "night out", "түнгі демалыс", cats=("nightlife", "bar"), tags=("night", "24_7"),
       intent="night", theme=True),
    _n("kids_fun", r"ребён|ребен|(?<![а-я])дет(ьми|ей|и|ск)|малыш|\bkids?\b|child|бала", "для детей", "for kids",
       "балаларға", cats=("kids", "playground"), tags=("kids", "interactive"), intent="kids", theme=True),
    # --- покупки (утилитарные запросы) ---
    _n("shop_24_7", r"круглосуточн|24/7|24 час|ночью купить|купить ночью|магазин\w* ночью|тәулік бойы",
       "круглосуточный магазин", "24/7 shop", "тәулік бойы дүкен", cats=("convenience", "supermarket"),
       shopping=True, intent="shopping", soft=("24_7",)),
    _n("supermarket", r"магнум|magnum|(?<![а-я])смолл|\bsmall\b|галмарт|galmart|супермаркет|продукт|гастроном|"
       r"supermarket|grocer|азық-түлік", "супермаркет / продукты", "supermarket", "супермаркет",
       cats=("supermarket", "convenience"), shopping=True, intent="shopping"),
    _n("clothes", r"одежд|шмот|закупит|обув|кроссовк|куртк|джинс|clothes|clothing|shoes|киім|аяқ киім",
       "одежда / обувь", "clothes / shoes", "киім", cats=("clothes",), tags=("shoes", "kids_clothes"),
       shopping=True, intent="shopping"),
    _n("stationery", r"канц|ручк[иу]|тетрад|карандаш|stationery|кеңсе", "канцтовары", "stationery",
       "кеңсе тауарлары", cats=("shop",), tags=("stationery",), name_rx=r"канц|stationery|комус", strict=True,
       shopping=True, intent="shopping"),
    _n("books", r"книжн|книг[иу] (купить|магазин)|купить книг|bookstore|book ?shop|кітап дүкен", "книжный",
       "bookstore", "кітап дүкені", cats=("shop",), tags=("books",), name_rx=r"книг|book|меломан|meloman",
       strict=True, shopping=True, intent="shopping"),
    _n("electronics", r"электроник|бытов\w* техник|наушник|ноутбук купить|телефон купить|electronics|"
       r"sulpak|сулпак|технодом|technodom|mechta|мечта\b", "электроника", "electronics", "электроника",
       cats=("shop",), tags=("electronics",), name_rx=r"sulpak|сулпак|технодом|technodom|mechta|мечта|электрон|alser",
       strict=True, shopping=True, intent="shopping"),
    _n("pharmacy", r"аптек|лекарств|таблетк|pharmacy|drugstore|дәріхана", "аптека", "pharmacy", "дәріхана",
       cats=("pharmacy",), name_rx=r"аптек|pharm|дәріхана", shopping=True, intent="shopping"),
    _n("mall", r"торгов\w* центр|(?<![а-я])т(р)?ц(?![а-я])|\bmall\b|сауда орталығы", "торговый центр", "mall",
       "сауда орталығы", cats=("mall",), shopping=True, intent="shopping"),
]
BY_KEY = {n.key: n for n in NEEDS}
_GENERIC_SHOP = _n("shop", r"магазин|\bshop\b|\bstore\b|дүкен", "магазин", "shop", "дүкен",
                   cats=tuple(SHOP_CATEGORIES | {"mall"}), shopping=True, intent="shopping")
BY_KEY["shop"] = _GENERIC_SHOP
BRANDS = {"magnum": r"магнум|magnum", "small": r"(?<![а-я])смолл|\bsmall\b", "galmart": r"галмарт|galmart"}
BUDGET_RX = r"бюджетн|недорог|дёшев|дешев|подешевле|cheap|budget|арзан"


def detect(query: str) -> list[str]:
    q = (query or "").lower()
    keys = [n.key for n in NEEDS if re.search(n.query_rx, q)]
    if "bar" in keys and re.search(r"[әғқңөұүһі]", q) and not re.search(r"сыра|паб|коктейл|\bbar\b|\bpub\b", q):
        keys.remove("bar")  # по-казахски «бар» = «есть» («орын бар ма?»), а не бар
    themes = [k for k in keys if BY_KEY[k].theme]
    objects = [k for k in keys if not BY_KEY[k].theme and k != "food"]
    if objects:  # назван конкретный объект («кино», «бассейн», «аптека») — он важнее общей темы
        keys = [k for k in keys if k not in themes]
    elif "kids_fun" in themes and {"view", "walk", "romantic"} & set(themes):
        keys.remove("kids_fun")  # «красивый вид с ребёнком» — тема вид, а «с детьми» сделает фильтр детей
    if "shop_24_7" in keys and "supermarket" in keys and not re.search(BRANDS["magnum"] + "|" + BRANDS["small"]
                                                                          + "|" + BRANDS["galmart"], q):
        keys.remove("supermarket")  # «круглосуточный магазин продуктов» — достаточно 24/7
    if not any(BY_KEY[k].shopping for k in keys) and re.search(_GENERIC_SHOP.query_rx, q):
        keys.append("shop")
    return keys


def brand(query: str) -> str | None:
    q = (query or "").lower()
    return next((b for b, rx in BRANDS.items() if re.search(rx, q)), None)


def wants_budget(query: str) -> bool:
    return bool(re.search(BUDGET_RX, (query or "").lower()))


def matches_any(p: dict, keys: list[str], brand_name: str | None = None) -> bool:
    if brand_name and any(k in ("supermarket", "shop_24_7", "shop") for k in keys):
        name = (p.get("name") or "").lower()
        if f"brand:{brand_name}" in (p.get("tags") or []) or re.search(BRANDS[brand_name], name):
            return True
        return False  # назвали бренд — другие сети не подставляем
    return any(BY_KEY[k].matches(p) for k in keys)


def labels(keys: list[str], lang: str) -> str:
    return ", ".join(BY_KEY[k].label.get(lang, BY_KEY[k].label["ru"]) for k in keys)


def is_theme(keys: list[str]) -> bool:
    """Только темы (вид, прогулка, культура…) — популярность важнее близости, маршрут уместен."""
    return bool(keys) and all(BY_KEY[k].theme for k in keys)


def is_shopping(keys: list[str]) -> bool:
    return bool(keys) and all(BY_KEY[k].shopping for k in keys)


def intent_for(keys: list[str]) -> str | None:
    return BY_KEY[keys[0]].intent if keys else None

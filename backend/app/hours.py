"""Парсер OSM opening_hours (частые шаблоны) и статус «открыто» с уверенностью.

Поддерживается: `24/7`, `Mo-Su 10:00-22:00`, `Mo-Fr 09:00-18:00; Sa-Su 10:00-16:00`,
списки дней `Mo,We,Fr`, несколько интервалов `10:00-14:00,15:00-19:00`, интервалы через
полночь `18:00-02:00`, `off`/`closed`, правила без дней. Нераспознанная строка → None
(статус `unknown`), чтобы не выдумывать «открыто».
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

DAYS = ["mo", "tu", "we", "th", "fr", "sa", "su"]
Schedule = dict[int, list[tuple[int, int]]]  # день недели → [(начало, конец)] в минутах, конец может быть > 1440

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})(\+)?$")
_DAYSEL_RE = re.compile(r"^(mo|tu|we|th|fr|sa|su)(\s*-\s*(mo|tu|we|th|fr|sa|su))?$")


def _parse_days(sel: str) -> set[int] | None:
    days: set[int] = set()
    for part in sel.split(","):
        part = part.strip()
        if part == "ph":  # праздники не моделируем — правило пропускаем целиком
            return set()
        m = _DAYSEL_RE.match(part)
        if not m:
            return None
        a = DAYS.index(m.group(1))
        b = DAYS.index(m.group(3)) if m.group(3) else a
        i = a
        while True:
            days.add(i)
            if i == b:
                break
            i = (i + 1) % 7
    return days


def _parse_times(s: str) -> list[tuple[int, int]] | None:
    out = []
    for part in s.split(","):
        part = part.strip()
        if part in ("sunrise-sunset",):
            out.append((7 * 60, 20 * 60))
            continue
        m = _TIME_RE.match(part)
        if not m:
            return None
        h1, m1, h2, m2 = (int(x) for x in m.groups()[:4])
        start, end = h1 * 60 + m1, h2 * 60 + m2
        if m.group(5):  # «10:00+» — открытый конец: считаем +4 ч
            end = start + 240
        if end <= start:
            end += 1440  # через полночь
        out.append((start, end))
    return out


def parse(spec: str | None) -> Schedule | None:
    if not spec or not isinstance(spec, str):
        return None
    s = spec.strip().lower().replace("–", "-").replace("—", "-").replace("||", ";")
    if s in ("24/7", "mo-su 00:00-24:00", "00:00-24:00"):
        return {d: [(0, 1440)] for d in range(7)}
    sched: Schedule = {}
    any_rule = False
    for rule in [r.strip() for r in s.split(";") if r.strip()]:
        rule = re.sub(r'"[^"]*"', "", rule).strip()  # комментарии в кавычках
        tokens = rule.split(None, 1)
        days = _parse_days(tokens[0])
        if days is not None:
            rest = tokens[1].strip() if len(tokens) > 1 else "00:00-24:00"
        else:
            days, rest = set(range(7)), rule
        if not days:
            continue  # PH и т.п.
        if rest in ("off", "closed"):
            for d in days:
                sched[d] = []
            any_rule = True
            continue
        if rest == "24/7":
            rest = "00:00-24:00"
        times = _parse_times(rest)
        if times is None:
            return None
        for d in days:
            sched[d] = list(times)  # более позднее правило переопределяет день (семантика OSM)
        any_rule = True
    if not any_rule:
        return None
    for d in range(7):
        sched.setdefault(d, [])
    return sched


@dataclass
class OpenEval:
    state: str  # open | closed | unknown
    closes_at: datetime | None = None
    opens_at: datetime | None = None
    minutes_left: int | None = None
    always: bool = False


def evaluate(sched: Schedule | None, dt: datetime) -> OpenEval:
    """Открыто ли в момент dt (локальное время)."""
    if sched is None:
        return OpenEval("unknown")
    if all(sched[d] == [(0, 1440)] for d in range(7)):
        return OpenEval("open", always=True, minutes_left=10**6)
    day0 = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    wd = dt.weekday()
    # интервалы вчера/сегодня, приведённые к абсолютному времени
    spans: list[tuple[datetime, datetime]] = []
    for offset in (-1, 0):
        d = (wd + offset) % 7
        for a, b in sched[d]:
            base = day0 + timedelta(days=offset)
            spans.append((base + timedelta(minutes=a), base + timedelta(minutes=b)))
    # склеиваем смежные (Mo-Su 00:00-24:00 по дням, 18:00-24:00 + 00:00-02:00)
    for start, end in spans:
        if start <= dt < end:
            end = _extend(sched, end)
            return OpenEval("open", closes_at=end, minutes_left=int((end - dt).total_seconds() // 60))
    for k in range(0, 8):
        base = day0 + timedelta(days=k)
        for a, _b in sorted(sched[(wd + k) % 7]):
            start = base + timedelta(minutes=a)
            if start > dt:
                return OpenEval("closed", opens_at=start)
    return OpenEval("closed")


def _extend(sched: Schedule, end: datetime) -> datetime:
    """Если следующий интервал начинается ровно в момент закрытия — продлеваем."""
    for _ in range(7):
        day0 = end.replace(hour=0, minute=0, second=0, microsecond=0)
        t = int((end - day0).total_seconds() // 60)
        nxt = [b for a, b in sched[end.weekday()] if a == t and b > t]
        if not nxt:
            break
        end = day0 + timedelta(minutes=max(nxt))
    return end


# ---------------- статус для ответа API ----------------

OUTDOOR_CATEGORIES = {"park", "monument", "landmark", "viewpoint"}
SRC_LABEL = {
    "ru": {"osm": "часы по OSM", "2gis": "часы по 2GIS", "official_site": "часы с офиц. сайта", "manual": "часы внесены вручную"},
    "en": {"osm": "OSM hours", "2gis": "2GIS hours", "official_site": "official website hours", "manual": "manually entered hours"},
    "kk": {"osm": "OSM бойынша", "2gis": "2GIS бойынша", "official_site": "ресми сайт бойынша", "manual": "қолмен енгізілген"},
}

# Типичные часы по категории — ТОЛЬКО для внутренней эвристики (ранжирование/фильтр ночью),
# в ответ как факт не попадают.
TYPICAL_HOURS = {
    "museum": "Tu-Su 10:00-18:00", "gallery": "Tu-Su 10:00-19:00", "library": "Mo-Sa 09:00-19:00",
    "mall": "Mo-Su 10:00-22:00", "cafe": "Mo-Su 08:00-23:00", "restaurant": "Mo-Su 11:00-23:00",
    "bar": "Mo-Su 18:00-02:00", "nightlife": "Mo-Su 21:00-04:00", "theatre": "Mo-Su 11:00-21:00",
    "cinema": "Mo-Su 10:00-01:00", "kids": "Mo-Su 10:00-20:00", "entertainment": "Mo-Su 10:00-22:00",
    "coworking": "Mo-Su 09:00-21:00", "market": "Mo-Su 09:00-19:00", "religious": "Mo-Su 06:00-21:00",
    "supermarket": "Mo-Su 08:00-23:00", "clothes": "Mo-Su 10:00-22:00", "shop": "Mo-Su 10:00-20:00",
    "pharmacy": "Mo-Su 08:00-22:00", "wellness": "Mo-Su 07:00-23:00",
    "sport": "Mo-Su 08:00-22:00", "viewpoint": "Mo-Su 10:00-21:00", "landmark": "Mo-Su 10:00-18:00",
}


def confidence(poi: dict, today: date | None = None) -> str:
    if not parse(poi.get("opening_hours")):
        return "low"
    src = (poi.get("opening_hours_source") or "").lower()
    age = _age_days(poi.get("opening_hours_checked_at"), today)
    if age is not None and age > 365:
        return "low"
    if src in ("2gis", "official_site") and age is not None and age <= 30:
        return "high"
    return "medium"


def _age_days(checked: str | None, today: date | None) -> int | None:
    if not checked:
        return None
    try:
        d = datetime.fromisoformat(str(checked).replace("Z", "+00:00")).date()
    except ValueError:
        return None
    return ((today or date.today()) - d).days


@dataclass
class PoiOpen:
    state: str
    confidence: str
    label: str
    source: str | None
    fits_visit: bool  # успевает ли посещение до закрытия
    guessed_closed: bool  # часов нет, но по типичным часам категории скорее закрыто
    open_late: bool = False  # круглосуточно или работает после полуночи
    outdoor_area: bool = False  # открытая территория без часов


def poi_open_status(poi: dict, arrival: datetime, visit_min: int, lang: str = "ru",
                    today: date | None = None) -> PoiOpen:
    sched = parse(poi.get("opening_hours"))
    src = poi.get("opening_hours_source") or ("osm" if sched else None)
    conf = confidence(poi, today)
    lang = lang if lang in SRC_LABEL else "ru"
    src_txt = SRC_LABEL[lang].get(src or "", src or "")
    checked = poi.get("opening_hours_checked_at")
    note = f"{src_txt}, {_checked_word(lang)} {str(checked)[:10]}" if checked else src_txt

    if sched is None:
        guess = evaluate(parse(TYPICAL_HOURS.get(poi.get("category", ""))), arrival)
        guessed_closed = guess.state == "closed" or (guess.state == "open" and (guess.minutes_left or 0) < min(visit_min, 30))
        outdoor = poi.get("category") in OUTDOOR_CATEGORIES and not poi.get("indoor")
        return PoiOpen("unknown", "low", _unknown_label(lang, outdoor), None, True, guessed_closed and not outdoor,
                       outdoor_area=outdoor)

    ev = evaluate(sched, arrival)
    if ev.state == "open":
        hhmm = ev.closes_at.strftime("%H:%M") if ev.closes_at else ""
        fits = ev.always or (ev.minutes_left or 0) >= visit_min
        if ev.always:
            label = {"ru": "Круглосуточно", "en": "Open 24/7", "kk": "Тәулік бойы"}[lang]
        elif not fits:
            label = {"ru": f"Закрывается в {hhmm} — времени мало",
                     "en": f"Closes at {hhmm} — little time left",
                     "kk": f"{hhmm}-да жабылады — уақыт аз"}[lang]
        elif conf == "high":
            label = {"ru": f"Открыто до {hhmm}", "en": f"Open until {hhmm}", "kk": f"{hhmm} дейін ашық"}[lang]
        elif conf == "medium":
            label = {"ru": f"Вероятно открыто до {hhmm}", "en": f"Likely open until {hhmm}",
                     "kk": f"{hhmm} дейін ашық болуы мүмкін"}[lang]
        else:
            label = {"ru": f"Возможно открыто до {hhmm} (данные устарели — уточните)",
                     "en": f"Possibly open until {hhmm} (data may be outdated)",
                     "kk": f"{hhmm} дейін ашық болуы мүмкін (дерек ескірген)"}[lang]
        late = ev.always or (ev.closes_at is not None and (ev.closes_at.date() > arrival.date() or ev.closes_at.hour >= 23))
        return PoiOpen("open", conf, f"{label} ({note})" if note else label, src, fits, False, open_late=late)

    opens = ev.opens_at
    if opens:
        when = opens.strftime("%H:%M") if opens.date() == arrival.date() else opens.strftime("%d.%m %H:%M")
        label = {"ru": f"Закрыто, откроется {when}", "en": f"Closed, opens {when}", "kk": f"Жабық, {when} ашылады"}[lang]
    else:
        label = {"ru": "Закрыто", "en": "Closed", "kk": "Жабық"}[lang]
    return PoiOpen("closed", conf, f"{label} ({note})" if note else label, src, False, False)


def _checked_word(lang: str) -> str:
    return {"ru": "проверено", "en": "checked", "kk": "тексерілді"}.get(lang, "проверено")


def _unknown_label(lang: str, outdoor: bool) -> str:
    if outdoor:
        return {"ru": "Часы не указаны; открытая территория — обычно доступна",
                "en": "Hours not listed; open-air area, usually accessible",
                "kk": "Жұмыс уақыты көрсетілмеген; ашық аумақ, әдетте қолжетімді"}[lang]
    return {"ru": "Часы работы неизвестны — уточните перед выходом",
            "en": "Opening hours unknown — check before going",
            "kk": "Жұмыс уақыты белгісіз — алдын ала нақтылаңыз"}[lang]

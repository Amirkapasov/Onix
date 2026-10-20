"""Минимальная проверка строк OSM opening_hours (без внешних зависимостей).

Задача — отсеять мусор («пн-пт 9-18», «круглосуточно», телефоны), а не реализовать
полную спецификацию. Строка проходит, если целиком разбирается на допустимые
токены и все интервалы времени корректны. Мелкие огрехи (9:00 → 09:00, тире «–»)
исправляются перед проверкой.
"""
from __future__ import annotations

import re

WD = r"(?:Mo|Tu|We|Th|Fr|Sa|Su)"
MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
TIME = r"(?:[0-4]?\d:[0-5]\d|sunrise|sunset|dawn|dusk)"

TOKEN = re.compile(
    r"""\s*(?:
      (?P<always>24/7)
    | (?P<span>%(t)s(?:\s*-\s*%(t)s\+?|\+))
    | (?P<wd>%(wd)s(?:\s*-\s*%(wd)s)?(?:\[[-\d,]+\])?)
    | (?P<hol>(?:PH|SH)(?:\s*[+-]\d+\s*days?)?)
    | (?P<mon>%(mon)s(?:\s*\d{1,2})?(?:\s*-\s*(?:%(mon)s(?:\s*\d{1,2})?|\d{1,2}))?)
    | (?P<year>\d{4}(?:\s*-\s*\d{4})?)
    | (?P<week>week\s*\d{1,2}(?:\s*-\s*\d{1,2})?(?:/\d+)?)
    | (?P<state>off|closed|open|unknown)
    | (?P<comment>"[^"]*")
    | (?P<sep>\|\||[;,:])
    )""" % {"t": TIME, "wd": WD, "mon": MON},
    re.VERBOSE,
)

_HHMM = re.compile(r"(\d{1,2}):(\d{2})")


def normalize(raw: str) -> str:
    s = raw.strip().replace("–", "-").replace("—", "-").replace("‒", "-")
    s = re.sub(r"\s+", " ", s)
    s = _HHMM.sub(lambda m: f"{int(m.group(1)):02d}:{m.group(2)}", s)
    s = re.sub(r"\s*-\s*", "-", s)
    s = s.rstrip(";").strip()
    return s


def is_valid(s: str) -> bool:
    if not s:
        return False
    pos, kinds = 0, []
    while pos < len(s):
        m = TOKEN.match(s, pos)
        if not m or m.end() == pos:
            return False
        kinds.append(m.lastgroup)
        if m.lastgroup == "span":
            for hh, mm in _HHMM.findall(m.group(0)):
                if int(hh) > 48 or int(mm) > 59:
                    return False
        pos = m.end()
    # Должно быть хоть какое-то содержательное правило.
    return any(k in ("always", "span", "state") for k in kinds)


def clean(raw: str | None) -> tuple[str | None, str | None]:
    """→ (валидная строка | None, исходная невалидная строка | None)."""
    if not raw:
        return None, None
    s = normalize(raw)
    if is_valid(s):
        return s, None
    return None, raw


def is_night(s: str | None) -> bool:
    """Открыто поздно: 24/7 или интервал, заканчивающийся после 23:00 / за полночь."""
    if not s:
        return False
    if "24/7" in s:
        return True
    for a, b in re.findall(r"(\d{2}):\d{2}-(\d{2}):\d{2}", s):
        start, end = int(a), int(b)
        if end >= 23 or end <= 5 and end < start or end > 24:
            return True
    return False


if __name__ == "__main__":
    for t in ["Mo-Su 10:00-22:00", "24/7", "Mo-Fr 9:00-18:00; Sa 10:00-16:00", "пн-пт 9-18",
              "Mo-Th 12:00-02:00; Fr,Sa 12:00-04:00", "May-Sep: Mo-Su 10:00-23:00", "PH off", "10:00-22:00"]:
        print(repr(t), clean(t), is_night(clean(t)[0]))

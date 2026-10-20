"""Валидация POI по contracts/poi.schema.json.

Если установлен `jsonschema` — используется он; иначе встроенная проверка
подмножества JSON Schema, которого достаточно для нашей схемы (type, required, enum, items).
"""
from __future__ import annotations

import json

from common import SCHEMA_PATH

SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

_TYPES = {
    "string": str, "number": (int, float), "integer": int, "boolean": bool,
    "object": dict, "array": list, "null": type(None),
}


def _type_ok(v, t) -> bool:
    ts = t if isinstance(t, list) else [t]
    for name in ts:
        py = _TYPES[name]
        if name in ("number", "integer") and isinstance(v, bool):
            continue
        if isinstance(v, py):
            return True
    return False


def _check(v, s, path, errs):
    if "type" in s and not _type_ok(v, s["type"]):
        errs.append(f"{path}: тип {type(v).__name__}, ожидался {s['type']}")
        return
    if "enum" in s and v not in s["enum"]:
        errs.append(f"{path}: {v!r} не из enum")
    if isinstance(v, dict):
        for r in s.get("required", []):
            if r not in v:
                errs.append(f"{path}.{r}: обязательное поле отсутствует")
        for k, sub in s.get("properties", {}).items():
            if k in v:
                _check(v[k], sub, f"{path}.{k}", errs)
    if isinstance(v, list) and "items" in s:
        for i, x in enumerate(v):
            _check(x, s["items"], f"{path}[{i}]", errs)


try:
    import jsonschema  # type: ignore

    _validator = jsonschema.Draft202012Validator(SCHEMA)
    BACKEND = "jsonschema"

    def errors(poi: dict) -> list[str]:
        return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in _validator.iter_errors(poi)]
except Exception:  # пакет не установлен — встроенная проверка
    BACKEND = "builtin"

    def errors(poi: dict) -> list[str]:
        errs: list[str] = []
        _check(poi, SCHEMA, "poi", errs)
        return errs


def extra_checks(poi: dict) -> list[str]:
    """Проверки смысла, которых нет в схеме."""
    errs = []
    if not (-90 <= poi["lat"] <= 90 and -180 <= poi["lon"] <= 180):
        errs.append("координаты вне диапазона")
    if not poi["name"].strip():
        errs.append("пустое имя")
    if not poi["description"].strip():
        errs.append("пустое описание")
    r = poi.get("rating")
    if r is not None and not 0 <= r <= 5:
        errs.append("rating вне 0–5")
    return errs

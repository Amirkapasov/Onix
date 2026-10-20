"""Общие утилиты пайплайна: пути, .env, HTTP с кэшем, гео-функции.

Только стандартная библиотека — пайплайн запускается без установки пакетов.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
CACHE = DATA / "cache"
SCHEMA_PATH = ROOT / "contracts" / "poi.schema.json"

USER_AGENT = "seruen-hackathon/0.1 (NIC Smart City hackathon; Astana walking assistant)"

# Граница Астаны: relation 3087155, wikidata Q1520. bbox — запасной фильтр.
ASTANA_WIKIDATA = "Q1520"
ASTANA_BBOX = (50.98, 71.20, 51.30, 71.70)  # minLat, minLon, maxLat, maxLon

NOW = datetime.now(timezone.utc)
TODAY = NOW.date().isoformat()


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_env() -> dict:
    """Читает ROOT/.env (KEY=VALUE) поверх os.environ. Значения не логируются."""
    env = dict(os.environ)
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v and not env.get(k.strip()):
                env[k.strip()] = v
    return env


def http(url: str, data: dict | None = None, headers: dict | None = None,
         timeout: int = 200, retries: int = 3) -> bytes:
    """GET (или POST form, если data) с User-Agent и повторами при 429/5xx."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    hdrs.update(headers or {})
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
        wait = 10 * (attempt + 1)
        log(f"  сетевой сбой ({last}); повтор через {wait} с")
        time.sleep(wait)
    raise RuntimeError(f"запрос не удался: {last}")


def cached_json(name: str, fetch, refresh: bool = False):
    """Кэш сырого ответа в data/raw/<name>.json; повторный запуск не бьёт API."""
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / f"{name}.json"
    if path.exists() and not refresh:
        log(f"  кэш: {path.relative_to(ROOT)}")
        return json.loads(path.read_text(encoding="utf-8")), path
    try:
        obj = fetch()
    except Exception as e:
        if path.exists():  # источник недоступен — работаем на прошлой выгрузке
            log(f"  источник недоступен ({e}); беру прошлый кэш {path.relative_to(ROOT)}")
            return json.loads(path.read_text(encoding="utf-8")), path
        raise
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return obj, path


def file_mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).date().isoformat()


def short_hash(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def in_bbox(lat, lon, bbox=ASTANA_BBOX) -> bool:
    return bbox[0] <= lat <= bbox[2] and bbox[1] <= lon <= bbox[3]


_QUOTES = "«»\"'“”„`’"
_GENERIC = r"\b(тц|трц|трк|тд|кафе|cafe|coffee|кофейня|ресторан|restaurant|бар|bar|парк|park|сквер|музей|museum)\b"


def norm_name(name: str) -> str:
    """Имя для дедупликации/сопоставления: нижний регистр, без кавычек и родовых слов."""
    s = unicodedata.normalize("NFKC", name or "").lower().replace("ё", "е")
    s = "".join(ch for ch in s if ch not in _QUOTES)
    s = re.sub(_GENERIC, " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def ensure_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

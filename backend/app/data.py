"""Загрузка базы POI. Перечитывает файл, если он появился или изменился."""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from . import config

log = logging.getLogger("seruen.data")


class PoiStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path: Path | None = None
        self._mtime: float = -1
        self.pois: list[dict] = []
        self.by_id: dict[str, dict] = {}
        self.version = 0  # растёт при каждой перезагрузке (сбрасывает индексы поиска)

    def _resolve_path(self) -> Path:
        main = Path(config.POIS_PATH)
        if not main.is_absolute():
            main = config.ROOT / main
        if main.exists() and main.stat().st_size > 2:
            return main
        return config.ROOT / config.SEED_PATH

    def get(self) -> list[dict]:
        path = self._resolve_path()
        mtime = path.stat().st_mtime
        if path != self._path or mtime != self._mtime:
            with self._lock:
                if path != self._path or mtime != self._mtime:
                    self._load(path, mtime)
        return self.pois

    def _load(self, path: Path, mtime: float) -> None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # битый файл во время записи Агентом 1 — оставляем старую версию
            log.warning("cannot read %s: %s", path, e)
            if self.pois:
                return
            raise
        items = raw if isinstance(raw, list) else raw.get("items", [])
        pois = [p for p in items if _valid(p)]
        self.pois = pois
        self.by_id = {p["id"]: p for p in pois}
        self._path, self._mtime = path, mtime
        self.version += 1
        log.info("loaded %d POIs from %s", len(pois), path.relative_to(config.ROOT))

    @property
    def source_name(self) -> str:
        return self._path.name if self._path else ""


def _valid(p: dict) -> bool:
    try:
        return bool(p.get("id")) and bool(p.get("name")) and float(p["lat"]) and float(p["lon"])
    except (KeyError, TypeError, ValueError):
        return False


store = PoiStore()

"""Гибридный поиск: BM25 (всегда) + эмбеддинги Gemini (если есть ключ), кэш в data/cache/."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from . import config
from .data import store

log = logging.getLogger("seruen.search")

CATEGORY_RU = {
    "cafe": "кафе кофейня", "restaurant": "ресторан еда", "bar": "бар", "nightlife": "ночной клуб ночная жизнь",
    "museum": "музей", "gallery": "галерея выставка искусство", "theatre": "театр", "cinema": "кино кинотеатр",
    "park": "парк сквер прогулка", "viewpoint": "смотровая площадка вид", "monument": "памятник монумент",
    "landmark": "достопримечательность", "religious": "мечеть храм собор", "mall": "торговый центр тц",
    "playground": "детская площадка", "kids": "детский дети", "entertainment": "развлечения",
    "sport": "спорт", "library": "библиотека", "coworking": "коворкинг работа", "market": "рынок базар",
    "supermarket": "супермаркет продукты магазин", "convenience": "магазин у дома продукты",
    "clothes": "одежда обувь магазин", "shop": "магазин", "pharmacy": "аптека лекарства",
    "wellness": "оздоровление спорт отдых",
    "other": "",
}
TAG_RU = {
    "wifi": "вайфай интернет", "sockets": "розетки зарядка ноутбук", "quiet": "тихо тихое спокойное",
    "interactive": "интерактив", "kids": "дети ребенок детский", "night": "ночью ночное поздно",
    "view": "вид панорама", "indoor": "в помещении тепло", "outdoor": "на улице воздух",
    "free": "бесплатно", "photo": "фото", "coffee": "кофе", "family": "семья дети", "unusual": "необычное",
    "walk": "прогулка погулять", "playground": "детская площадка", "architecture": "архитектура",
    "history": "история", "science": "наука", "shopping": "магазины шопинг", "cinema": "кино",
    "swimming": "бассейн плавание", "pool": "бассейн", "fitness": "фитнес спортзал тренажёры", "gym": "спортзал",
    "spa": "спа", "sauna": "сауна баня", "massage": "массаж", "24_7": "круглосуточно", "budget": "недорого",
    "stationery": "канцтовары", "books": "книги", "electronics": "электроника", "shoes": "обувь",
    "groceries": "продукты", "terrace": "терраса веранда", "outdoor_seating": "летняя веранда",
    "wheelchair": "доступно для колясок пандус", "takeaway": "навынос",
}
EXPAND = {  # ограничение/интент → слова для BM25-запроса
    "quiet": "quiet тихо", "coffee": "coffee cafe кофе", "sockets": "sockets wifi coworking розетки",
    "wifi": "wifi", "night": "night ночное", "unusual": "unusual необычное", "outdoor_ok": "outdoor walk park прогулка",
    "view": "view viewpoint вид", "indoor": "indoor", "food": "restaurant cafe еда", "interactive": "interactive",
    "free": "free", "kids": "kids playground family interactive дети", "culture": "museum gallery theatre музей",
    "sightseeing": "landmark monument viewpoint photo достопримечательность", "walk": "walk park outdoor прогулка",
    "work": "coworking sockets wifi coffee", "shopping": "mall shopping",
}
_ENDINGS = sorted("ами ями ого его ому ему ыми ими ой ей ий ый ая яя ое ее ые ие ам ям ах ях ом ем ов ев ую юю "
                  "а я о е ы и у ю ь й".split(), key=len, reverse=True)


def stem(w: str) -> str:
    w = w.replace("ё", "е")
    if re.match(r"[а-я]", w):
        for e in _ENDINGS:
            if w.endswith(e) and len(w) - len(e) >= 3:
                w = w[: -len(e)]
                break
        return w[:5]
    return w[:8]


def tokenize(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-zа-яёәғқңөұүһі0-9]+", (text or "").lower()) if len(w) > 1]


def doc_text(p: dict) -> str:
    tags = p.get("tags") or []
    parts = [p.get("name", ""), p.get("category", ""), CATEGORY_RU.get(p.get("category", ""), ""),
             " ".join(tags), " ".join(TAG_RU.get(t, "") for t in tags), p.get("description", "")]
    return " ".join(x for x in parts if x)


class Index:
    def __init__(self) -> None:
        self.version = -1
        self.bm25: BM25Okapi | None = None
        self.emb: np.ndarray | None = None  # нормированные эмбеддинги документов
        self.idx: dict[str, int] = {}
        self._lock = threading.Lock()
        self._emb_thread: threading.Thread | None = None
        self._qcache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._q_cooldown = 0.0
        self.emb_mask: np.ndarray | None = None
        self.progress = (0, 0)

    def ensure(self) -> None:
        pois = store.get()
        if self.version == store.version:
            return
        with self._lock:
            if self.version == store.version:
                return
            texts = [doc_text(p) for p in pois]
            self.bm25 = BM25Okapi([tokenize(t) or ["_"] for t in texts])
            self.idx = {p["id"]: i for i, p in enumerate(pois)}
            self.emb = None
            self.version = store.version
            if _embed_enabled():
                self._emb_thread = threading.Thread(target=self._build_emb, args=(texts, store.version, pois),
                                                    daemon=True)
                self._emb_thread.start()

    def _build_emb(self, texts: list[str], version: int, pois: list[dict] | None = None) -> None:
        """Фоновое построение индекса (сервис тем временем работает на BM25).

        Кэш инкрементальный: вектор хранится по sha1(модель + текст документа), поэтому при новой версии
        data/pois.json пересчитываются только изменённые/новые места, одинаковые тексты встраиваются один раз,
        а прогресс переживает перезапуск. Встраиваются только «досуговые» места (магазины, площадки и места
        с общими названиями обслуживает фильтр потребностей + BM25), сначала популярные. Несколько процессов
        не строят одновременно (lock-файл). Суточная квота кончилась → частичный индекс (≥ 30 %), поток
        ждёт сброса квоты и продолжает сам."""
        want = [i for i in range(len(texts)) if pois is None or _embeddable(pois[i])]
        hashes = [_text_hash(t) for t in texts]
        uniq = list(dict.fromkeys(hashes[i] for i in want))
        first = {}
        for i in want:
            first.setdefault(hashes[i], i)
        prio = {h: -(_poi_weight(pois[first[h]]) if pois else 0) for h in uniq}
        self.progress = (0, len(uniq))
        while version == self.version:
            try:
                cache = _load_store()
                missing = sorted((h for h in uniq if h not in cache), key=lambda h: prio[h])
                self.progress = (len(uniq) - len(missing), len(uniq))
                if not missing:
                    self._set_emb(hashes, cache, version, set(uniq))
                    return
                if not _take_lock():
                    time.sleep(30)  # строит другой процесс — ждём его результат
                    continue
                try:
                    for start in range(0, len(missing), EMBED_BATCH):
                        if version != self.version:
                            return
                        chunk = missing[start:start + EMBED_BATCH]
                        vecs = _embed([texts[first[h]] for h in chunk], "RETRIEVAL_DOCUMENT", patient=True)
                        cache.update(zip(chunk, vecs))
                        _save_store(cache)
                        _touch_lock()
                        self.progress = (len(uniq) - len(missing) + start + len(chunk), len(uniq))
                finally:
                    _release_lock()
            except DailyQuotaExceeded as e:
                cache = _load_store()
                done = sum(h in cache for h in uniq)
                partial = done >= len(uniq) * 0.3
                log.warning("embeddings: daily quota exhausted (%d/%d) — %s; resume after quota reset",
                            done, len(uniq), "partial index" if partial else "BM25 only")
                if partial:
                    self._set_emb(hashes, cache, version, set(uniq))
                m = re.search(r"retryDelay'?:\s*'?(\d+)", str(e))
                time.sleep(min(int(m.group(1)) + 60 if m else 3600, 6 * 3600))
            except Exception as e:
                log.warning("embeddings disabled (BM25 only): %s: %s", type(e).__name__, str(e)[:200])
                return

    def _set_emb(self, hashes: list[str], cache: dict, version: int, wanted: set | None = None) -> None:
        dim = len(next(iter(cache.values())))
        mask = np.array([h in cache and (wanted is None or h in wanted) for h in hashes])
        mat = np.stack([cache[h] if h in cache else np.zeros(dim, np.float32) for h in hashes]).astype(np.float32)
        if version == self.version:
            self.emb, self.emb_mask = mat, mask
            log.info("embeddings ready: %s (coverage %d/%d)", mat.shape, int(mask.sum()), len(mask))

    def query_emb(self, q: str) -> np.ndarray | None:
        """Эмбеддинг запроса (кэш в памяти). Квота/таймаут → None, поиск тихо остаётся на BM25."""
        if self.emb is None:
            return None
        if q in self._qcache:
            self._qcache.move_to_end(q)
            return self._qcache[q]
        if time.monotonic() < self._q_cooldown:
            return None
        fut = _QPOOL.submit(_embed, [q], "RETRIEVAL_QUERY")
        try:
            v = fut.result(timeout=QUERY_EMBED_BUDGET_S)[0]
        except Exception as e:  # 429, таймаут, сеть
            from .llm import _is_quota, _retry_delay
            err = str(e)
            self._q_cooldown = time.monotonic() + (_retry_delay(err) if _is_quota(err) else 30)
            log.info("query embedding skipped (%s) — BM25 only", type(e).__name__)
            return None
        self._qcache[q] = v
        if len(self._qcache) > 500:
            self._qcache.popitem(last=False)
        return v

    def scores(self, query: str, expand_terms: list[str], ids: list[str]) -> dict[str, float]:
        """Релевантность 0..1 для списка id."""
        self.ensure()
        if not ids:
            return {}
        q_tokens = tokenize(query) + tokenize(" ".join(EXPAND.get(t, t) for t in expand_terms))
        rows = [self.idx[i] for i in ids]
        bm = np.array(self.bm25.get_batch_scores(q_tokens, rows), dtype=float) if q_tokens else np.zeros(len(rows))
        bm = bm / bm.max() if bm.max() > 0 else bm
        qv = self.query_emb(query) if self.emb is not None else None
        if qv is None:
            return dict(zip(ids, bm.tolist()))
        cos = self.emb[rows] @ qv
        has = self.emb_mask[rows] if self.emb_mask is not None else np.ones(len(rows), bool)
        if not has.any():
            return dict(zip(ids, bm.tolist()))
        lo, hi = float(cos[has].min()), float(cos[has].max())
        cn = (cos - lo) / (hi - lo) if hi - lo > 1e-6 else np.zeros_like(cos)
        cn = np.where(has, cn, 0.5)  # у места нет вектора (частичный индекс) — нейтральная оценка
        return dict(zip(ids, (0.5 * bm + 0.5 * cn).tolist()))

    @property
    def embeddings_ready(self) -> bool:
        return self.emb is not None


class DailyQuotaExceeded(Exception):
    pass


def _embeddable(p: dict) -> bool:
    from .guards import is_generic_name
    from .needs import SHOP_CATEGORIES
    return p.get("category") not in SHOP_CATEGORIES | {"playground"} and not is_generic_name(p.get("name", ""))


def _poi_weight(p: dict) -> float:
    return (p.get("popularity") or 0) + (p.get("data_quality") or 0) + (0.5 if len(p.get("description") or "") > 60 else 0)


EMBED_BATCH = 100          # одним batchEmbedContents (квота free tier считает каждый текст)
QUERY_EMBED_BUDGET_S = 2.0
_QPOOL = ThreadPoolExecutor(max_workers=2)
LOCK_STALE_S = 180


def _store_path() -> Path:
    return config.CACHE_DIR / f"emb_store_{config.GEMINI_EMBED_MODEL}.npz"


def _text_hash(text: str) -> str:
    return hashlib.sha1(f"{config.GEMINI_EMBED_MODEL}|768|{text}".encode()).hexdigest()


def _load_store() -> dict[str, np.ndarray]:
    path = _store_path()
    if not path.exists():
        return {}
    try:
        with np.load(path) as z:
            return dict(zip(z["keys"].tolist(), z["vecs"]))
    except Exception as e:
        log.warning("embedding cache unreadable, rebuilding: %s", type(e).__name__)
        return {}


def _save_store(cache: dict[str, np.ndarray]) -> None:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _store_path().with_suffix(".tmp.npz")
    keys = list(cache)
    np.savez(tmp, keys=np.array(keys), vecs=np.stack([cache[k] for k in keys]).astype(np.float32))
    os.replace(tmp, _store_path())  # атомарно: читатели не увидят полузаписанный файл


def _lock_path() -> Path:
    return config.CACHE_DIR / f"emb_build_{config.GEMINI_EMBED_MODEL}.lock"


def _take_lock() -> bool:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    lp = _lock_path()
    if lp.exists() and time.time() - lp.stat().st_mtime > LOCK_STALE_S:
        lp.unlink(missing_ok=True)  # строитель умер (перезапуск) — забираем
    try:
        fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _touch_lock() -> None:
    try:
        os.utime(_lock_path())
    except OSError:
        pass


def _release_lock() -> None:
    _lock_path().unlink(missing_ok=True)


def _embed_enabled() -> bool:
    return bool(config.GEMINI_API_KEY) and not config.DISABLE_LLM and not config.DISABLE_NETWORK


def _embed(texts: list[str], task: str, timeout: float = 30.0, patient: bool = False) -> np.ndarray:
    """patient=True (фоновое построение индекса): на 429 ждём и продолжаем, до ~15 мин."""
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    model = config.GEMINI_EMBED_MODEL
    kw = {"output_dimensionality": 768, "http_options": types.HttpOptions(timeout=int(max(10.0, timeout) * 1000))}
    if "embedding-001" in model:
        kw["task_type"] = task
    else:  # gemini-embedding-2 и новее: task_type не поддерживается — префикс в тексте
        pre = "task: search result | query: " if task == "RETRIEVAL_QUERY" else "text: "
        texts = [pre + t for t in texts]
    out: list = []
    step, waited = EMBED_BATCH, 0.0
    i = 0
    while i < len(texts):
        try:
            resp = client.models.embed_content(model=model, contents=texts[i:i + step],
                                               config=types.EmbedContentConfig(**kw))
        except Exception as e:
            from .llm import _is_quota, _retry_delay
            if not (patient and _is_quota(str(e))) or waited > 1800:
                raise
            m = re.search(r"retryDelay'?:\s*'?(\d+)", str(e))
            if "PerDay" in str(e) or (m and int(m.group(1)) > 600):
                raise DailyQuotaExceeded(str(e)[:200]) from e
            delay = _retry_delay(str(e))
            log.info("embeddings: quota, waiting %.0fs (%d/%d done)", delay, i, len(texts))
            time.sleep(delay)
            _touch_lock()
            waited += delay
            continue
        out.extend(e.values for e in resp.embeddings)
        i += step
    mat = np.array(out, dtype=np.float32)
    mat /= np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
    return mat


index = Index()

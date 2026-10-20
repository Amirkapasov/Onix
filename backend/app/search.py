"""Гибридный поиск: BM25 (всегда) + эмбеддинги Gemini (если есть ключ), кэш в data/cache/."""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from collections import OrderedDict

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
    "other": "",
}
TAG_RU = {
    "wifi": "вайфай интернет", "sockets": "розетки зарядка ноутбук", "quiet": "тихо тихое спокойное",
    "interactive": "интерактив", "kids": "дети ребенок детский", "night": "ночью ночное поздно",
    "view": "вид панорама", "indoor": "в помещении тепло", "outdoor": "на улице воздух",
    "free": "бесплатно", "photo": "фото", "coffee": "кофе", "family": "семья дети", "unusual": "необычное",
    "walk": "прогулка погулять", "playground": "детская площадка", "architecture": "архитектура",
    "history": "история", "science": "наука", "shopping": "магазины шопинг", "cinema": "кино",
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
                self._emb_thread = threading.Thread(target=self._build_emb, args=(texts, store.version), daemon=True)
                self._emb_thread.start()

    def _build_emb(self, texts: list[str], version: int) -> None:
        try:
            h = hashlib.sha1(("\n".join(texts) + config.GEMINI_EMBED_MODEL).encode()).hexdigest()[:16]
            path = config.CACHE_DIR / f"emb_{h}.npy"
            if path.exists():
                mat = np.load(path)
            else:
                mat = _embed(texts, "RETRIEVAL_DOCUMENT")
                config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
                np.save(path, mat)
            if version == self.version:
                self.emb = mat
                log.info("embeddings ready: %s", mat.shape)
        except Exception as e:
            log.warning("embeddings disabled (BM25 only): %s: %s", type(e).__name__, str(e)[:200])

    def query_emb(self, q: str) -> np.ndarray | None:
        if self.emb is None:
            return None
        if q in self._qcache:
            self._qcache.move_to_end(q)
            return self._qcache[q]
        try:
            v = _embed([q], "RETRIEVAL_QUERY", timeout=3.0)[0]
        except Exception as e:
            log.warning("query embedding failed: %s", type(e).__name__)
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
        lo, hi = float(cos.min()), float(cos.max())
        cn = (cos - lo) / (hi - lo) if hi - lo > 1e-6 else np.zeros_like(cos)
        return dict(zip(ids, (0.5 * bm + 0.5 * cn).tolist()))

    @property
    def embeddings_ready(self) -> bool:
        return self.emb is not None


def _embed_enabled() -> bool:
    return bool(config.GEMINI_API_KEY) and not config.DISABLE_LLM and not config.DISABLE_NETWORK


def _embed(texts: list[str], task: str, timeout: float = 30.0) -> np.ndarray:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    model = config.GEMINI_EMBED_MODEL
    kw = {"output_dimensionality": 768, "http_options": types.HttpOptions(timeout=int(timeout * 1000))}
    if "embedding-001" in model:
        kw["task_type"] = task
    else:  # gemini-embedding-2 и новее: task_type не поддерживается — префикс в тексте
        pre = "task: search result | query: " if task == "RETRIEVAL_QUERY" else "text: "
        texts = [pre + t for t in texts]
    out = []
    for i in range(0, len(texts), 100):
        resp = client.models.embed_content(model=model, contents=texts[i:i + 100],
                                           config=types.EmbedContentConfig(**kw))
        out.extend(e.values for e in resp.embeddings)
    mat = np.array(out, dtype=np.float32)
    mat /= np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
    return mat


index = Index()

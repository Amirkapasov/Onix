import numpy as np

from backend.app import config, search


def test_incremental_store_resumes_and_skips_known(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    calls = []

    def fake_embed(texts, task, timeout=30.0, patient=False):
        calls.append(len(texts))
        return np.ones((len(texts), 4), dtype=np.float32) / 2

    monkeypatch.setattr(search, "_embed", fake_embed)
    monkeypatch.setattr(search, "EMBED_BATCH", 2)
    idx = search.Index()
    idx.version = 1
    texts = ["a", "b", "c"]
    idx._build_emb(texts, 1)
    assert idx.emb.shape == (3, 4) and calls == [2, 1] and idx.progress == (3, 3)
    assert not list(tmp_path.glob("*.lock"))
    # второй запуск (например, после рестарта): всё из кэша, API не трогаем; новый POI — только он
    idx2 = search.Index()
    idx2.version = 1
    idx2._build_emb(texts + ["d"], 1)
    assert calls == [2, 1, 1] and idx2.emb.shape == (4, 4)


def test_query_embedding_quota_falls_back_silently(monkeypatch):
    idx = search.Index()
    idx.emb = np.ones((1, 4), dtype=np.float32)

    def boom(*a, **k):
        raise RuntimeError("429 RESOURCE_EXHAUSTED retryDelay': '30s'")

    monkeypatch.setattr(search, "_embed", boom)
    assert idx.query_emb("кофе") is None
    assert idx._q_cooldown > 0  # дальше не дёргаем API, пока квота не восстановится


def test_daily_quota_gives_partial_index(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(search, "EMBED_BATCH", 2)
    n = {"calls": 0}

    def fake_embed(texts, task, timeout=30.0, patient=False):
        n["calls"] += 1
        if n["calls"] > 1:
            raise search.DailyQuotaExceeded("PerDay")
        return np.ones((len(texts), 4), dtype=np.float32) / 2

    monkeypatch.setattr(search, "_embed", fake_embed)
    monkeypatch.setattr(search.time, "sleep", lambda s: setattr(idx, "version", 2))  # «ждём сброса» → выходим
    idx = search.Index()
    idx.version = 1
    idx._build_emb(["a", "b", "a", "c"], 1)  # «a» дважды → встраивается один раз
    assert idx.progress == (2, 3) and idx.emb is not None
    assert idx.emb_mask.tolist() == [True, True, True, False]


def test_shops_and_generic_names_not_embedded(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    seen = []
    monkeypatch.setattr(search, "_embed", lambda texts, task, timeout=30.0, patient=False:
                        seen.extend(texts) or np.ones((len(texts), 4), dtype=np.float32))
    pois = [{"name": "Хан Шатыр", "category": "mall"}, {"name": "Аптека", "category": "pharmacy"},
            {"name": "Детская площадка", "category": "playground"}, {"name": "Сквер", "category": "park"}]
    idx = search.Index()
    idx.version = 1
    idx._build_emb(["t1", "t2", "t3", "t4"], 1, pois)
    assert seen == ["t1"] and idx.emb_mask.tolist() == [True, False, False, False]

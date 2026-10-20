"""FastAPI-приложение Seruen. Запуск из корня: uvicorn backend.app.main:app --reload --port 8000"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config, llm, weather
from .data import store
from .models import RecommendRequest, RecommendResponse, WhereRequest
from .where import where
from .pipeline import recommend
from .presets import PRESETS
from .search import index

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("seruen")


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.get()
    index.ensure()  # эмбеддинги строятся в фоне
    llm.get_provider()
    task = asyncio.create_task(weather.prefetch())
    yield
    task.cancel()


app = FastAPI(title="Seruen API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(RequestValidationError)
async def _bad_request(_: Request, exc: RequestValidationError):
    msg = "; ".join(f"{'.'.join(str(x) for x in e['loc'][1:])}: {e['msg']}" for e in exc.errors()[:5])
    return error(422, "bad_request", msg)


@app.exception_handler(Exception)
async def _internal(_: Request, exc: Exception):
    log.exception("unhandled error")
    return error(500, "internal_error", type(exc).__name__)


@app.post("/api/recommend", response_model=RecommendResponse, response_model_by_alias=True)
async def api_recommend(req: RecommendRequest):
    if not req.query.strip() and not req.filters.categories:
        return error(400, "empty_query", "Опишите, что хотите, или выберите категорию.")
    return await recommend(req)


@app.get("/api/pois")
def api_pois(bbox: str | None = Query(None, description="minLat,minLon,maxLat,maxLon"),
             category: str | None = None, limit: int = Query(5000, ge=1, le=20000),
             fields: str | None = Query(None, description="lite — только поля для точек на карте (в ~8 раз легче)")):
    items = store.get()
    if bbox:
        try:
            a, b, c, d = (float(x) for x in bbox.split(","))
        except ValueError:
            return error(400, "bad_bbox", "bbox = minLat,minLon,maxLat,maxLon")
        items = [p for p in items if a <= p["lat"] <= c and b <= p["lon"] <= d]
    if category:
        cats = set(category.split(","))
        items = [p for p in items if p.get("category") in cats]
    items = items[:limit]
    if fields == "lite":  # точки на карте: без описаний, источников и фото — ответ в разы меньше
        items = [{k: p.get(k) for k in LITE_FIELDS} for p in items]
    return JSONResponse({"items": items}, headers={"Cache-Control": "public, max-age=300"})


LITE_FIELDS = ("id", "name", "lat", "lon", "category", "opening_hours")


@app.get("/api/presets")
def api_presets():
    return {"items": PRESETS}


@app.post("/api/where")
def api_where(loc: WhereRequest):
    """«Где я»: ориентир и адрес по базе мест (POST — координаты не попадают в журнал запросов)."""
    return where(loc.lat, loc.lon, loc.lang or "ru")


@app.get("/api/category-photos")
def api_category_photos():
    """Фото категорий и обложки (data/category_photos.json от Агента 1); нет файла — пустой ответ."""
    path = config.ROOT / "data" / "category_photos.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {"hero": data.get("hero") or [], "categories": data.get("categories") or {},
                    **{k: v for k, v in data.items() if k not in ("hero", "categories")}}
    except FileNotFoundError:
        pass
    except Exception as e:  # битый/пишущийся файл — не 500
        log.warning("category_photos.json unreadable: %s", type(e).__name__)
    return {"hero": [], "categories": {}}


@app.get("/api/health")
def api_health():
    prov = llm.get_provider()
    return {"status": "ok", "pois": len(store.get()), "llm_provider": prov.name if prov else "none",
            "llm_model": prov.model if prov else None, "embeddings": index.embeddings_ready,
            "embeddings_progress": "{}/{}".format(*index.progress),
            "data_file": store.source_name, "configured_provider": config.LLM_PROVIDER}

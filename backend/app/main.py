"""FastAPI-приложение «Серуен». Запуск из корня: uvicorn backend.app.main:app --reload --port 8000"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config, llm
from .data import store
from .models import RecommendRequest, RecommendResponse
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
    yield


app = FastAPI(title="Серуен API", version="0.1.0", lifespan=lifespan)
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
             category: str | None = None, limit: int = Query(5000, ge=1, le=20000)):
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
    return {"items": items[:limit]}


@app.get("/api/presets")
def api_presets():
    return {"items": PRESETS}


@app.get("/api/health")
def api_health():
    prov = llm.get_provider()
    return {"status": "ok", "pois": len(store.get()), "llm_provider": prov.name if prov else "none",
            "llm_model": prov.model if prov else None, "embeddings": index.embeddings_ready,
            "data_file": store.source_name, "configured_provider": config.LLM_PROVIDER}

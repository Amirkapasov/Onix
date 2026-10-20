"""Один сервис для Cloud Run: API «Seruen» на /api/* + собранный фронтенд (frontend/dist) на "/".

Запуск из корня репо:  uvicorn deploy.server:app --port 8080
В контейнере порт берётся из $PORT (Cloud Run), по умолчанию 8080 — см. Dockerfile.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.main import app  # lifespan, обработчики ошибок и /api/* приходят вместе с приложением

ROOT = Path(__file__).resolve().parents[1]
DIST = Path(os.getenv("SERUEN_STATIC_DIR", ROOT / "frontend" / "dist")).resolve()
INDEX = DIST / "index.html"

if not INDEX.exists():
    raise RuntimeError(f"Нет собранного фронтенда: {INDEX}. Выполните `cd frontend && npm run build`.")

# Хэшированные бандлы Vite — отдаём напрямую и кэшируем надолго.
app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    # Неизвестный /api/* — JSON-ошибка по контракту, а не index.html.
    if path == "api" or path.startswith("api/"):
        return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": f"/{path}"}})
    file = (DIST / path).resolve()
    if path and file.is_file() and file.is_relative_to(DIST):
        return FileResponse(file)  # favicon.svg и прочее из public/
    # SPA fallback: любой другой путь (в т.ч. /?preset=…) — index.html без кэша, чтобы новый деплой подхватывался сразу.
    return FileResponse(INDEX, headers={"Cache-Control": "no-cache"})

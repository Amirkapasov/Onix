# «Серуен» — один сервис для Cloud Run: FastAPI (/api/*) + собранный фронтенд (/).
# Сборка: gcloud run deploy seruen --source .   (подробно: deploy/README.md)

# ---------- 1. Фронтенд ----------
FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Переменные окружения важнее .env-файлов Vite: в проде всегда живой API, не моки.
ENV VITE_USE_MOCK=0
RUN npm run build

# ---------- 2. Рантайм ----------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/ backend/
COPY deploy/ deploy/
COPY contracts/ contracts/
# data/pois.json, data/seed/ и, если есть, data/cache/ (кэш эмбеддингов — чтобы не пересчитывать при старте).
# data/raw и прочее отсекает .dockerignore.
COPY data/ data/
COPY --from=frontend /src/frontend/dist frontend/dist

# Не root
RUN useradd --create-home --uid 10001 seruen && chown -R seruen /app/data
USER seruen

EXPOSE 8080
# Cloud Run задаёт $PORT; секреты (GEMINI_API_KEY и т.п.) — только через переменные окружения сервиса.
CMD ["sh", "-c", "exec uvicorn deploy.server:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]

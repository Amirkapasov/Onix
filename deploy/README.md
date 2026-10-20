# Деплой «Seruen» на Google Cloud Run

Один сервис: FastAPI отдаёт API на `/api/*` и собранный фронтенд на `/`.
Образ собирает Cloud Build по `Dockerfile` из корня репозитория, Docker локально не нужен.

| Файл | Зачем |
|---|---|
| `Dockerfile` (корень) | node собирает `frontend/dist` → python:3.12-slim + backend + data → `uvicorn deploy.server:app` на `$PORT` |
| `.dockerignore`, `.gcloudignore` (корень) | `.env`, `.venv`, `node_modules`, `data/raw`, docs/eval не попадают ни в загрузку, ни в образ. `data/cache` (кэш эмбеддингов) — попадает |
| `deploy/server.py` | обёртка над `backend.app.main:app`: статика + SPA fallback; неизвестный `/api/*` → JSON 404 |

Секреты — **только** переменные окружения Cloud Run (`GEMINI_API_KEY`, `LLM_PROVIDER=gemini`). Ключ 2GIS в рантайме не нужен.

---

## 0. Проверка локально (без Docker)

```bash
cd frontend && npm ci && npm run build && cd ..
.venv/bin/uvicorn deploy.server:app --port 8080
```
Откройте http://localhost:8080 (UI) и http://localhost:8080/api/health (API).

## 1. Установить gcloud и войти

```bash
brew install --cask google-cloud-sdk
```
```bash
gcloud auth login
```
```bash
gcloud config set project <PROJECT_ID>
```
```bash
gcloud config set run/region europe-west1
```

## 2. Включить API (один раз)

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

## 3. Деплой

Команды запускаются **из корня репозитория** (`seruen/`). Первый деплой ~5–8 минут: gcloud предложит создать репозиторий Artifact Registry `cloud-run-source-deploy` — ответьте `Y`.

### Вариант A (рекомендуется): ключ в Secret Manager

```bash
gcloud services enable secretmanager.googleapis.com
```
Создать секрет (ключ вводится из буфера, не остаётся в истории shell):
```bash
pbpaste | gcloud secrets create gemini-api-key --data-file=-
```
Дать сервису право читать секрет (сервис работает от сервисного аккаунта Compute по умолчанию):
```bash
PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format='value(projectNumber)')
gcloud secrets add-iam-policy-binding gemini-api-key \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```
Деплой:
```bash
gcloud run deploy seruen --source . --region europe-west1 --allow-unauthenticated --set-env-vars LLM_PROVIDER=gemini --set-secrets GEMINI_API_KEY=gemini-api-key:latest --memory 1Gi --cpu 1 --min-instances 0 --max-instances 2 --concurrency 20 --timeout 60
```

### Вариант B (быстрее, для одноразового демо): ключ в переменной окружения

```bash
gcloud run deploy seruen --source . --region europe-west1 --allow-unauthenticated --set-env-vars LLM_PROVIDER=gemini,GEMINI_API_KEY=<ВАШ_КЛЮЧ> --memory 1Gi --cpu 1 --min-instances 0 --max-instances 2 --concurrency 20 --timeout 60
```
Минус: ключ виден в консоли Cloud Run всем, у кого есть доступ к проекту, и остаётся в истории shell.

В конце команда печатает `Service URL: https://seruen-…run.app`. Проверка:
```bash
curl -s "$(gcloud run services describe seruen --region europe-west1 --format='value(status.url)')/api/health"
```
Ожидается `"llm_provider": "gemini"`. Если там `"none"` — ключ не дошёл (см. «Проблемы»).

Необязательные переменные: `GEMINI_MODEL`, `GEMINI_EMBED_MODEL`, `LLM_TIMEOUT_S` — через `--update-env-vars ИМЯ=значение`.

### Обновление
Та же команда `gcloud run deploy …` — новая ревизия, трафик переключается после успешного старта.

## 4. Защита бюджета

- `--max-instances 2` — больше двух контейнеров не поднимется ни при какой нагрузке.
- `--min-instances 0` — без трафика сервис стоит ~0 ₽ (первый запрос после простоя — «холодный старт» 5–15 с; **перед выступлением откройте сайт заранее**).
- Бюджет с оповещениями. Через консоль: *Billing → Budgets & alerts → Create budget* → сумма, например 10 USD, пороги 50 / 90 / 100 %, письма админам биллинга. Или CLI:
  ```bash
  gcloud services enable billingbudgets.googleapis.com
  ```
  ```bash
  gcloud billing accounts list
  ```
  ```bash
  gcloud billing budgets create --billing-account=<BILLING_ACCOUNT_ID> --display-name="seruen-demo" --budget-amount=10USD --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
  ```
  Бюджет только **оповещает**, расходы он не останавливает — реальный ограничитель здесь `--max-instances`.
- Расходы Gemini API считаются отдельно (Google AI Studio / квоты ключа) — там тоже стоит выставить лимит.

## 5. После хакатона

```bash
gcloud run services delete seruen --region europe-west1
```
Также можно удалить образы в Artifact Registry (`cloud-run-source-deploy`) и секрет `gemini-api-key`.

## Проблемы

| Симптом | Что сделать |
|---|---|
| `PERMISSION_DENIED` при сборке в новом проекте | Выдать сервисному аккаунту сборки роль сборщика: `gcloud projects add-iam-policy-binding <PROJECT_ID> --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" --role="roles/run.builder"` |
| `/api/health` → `"llm_provider": "none"` | Проверить переменные: `gcloud run services describe seruen --region europe-west1 --format=yaml(spec.template.spec.containers[0].env)`; для варианта A — роль `secretAccessor` |
| Ошибка при старте | Логи: `gcloud run services logs read seruen --region europe-west1 --limit 50` |
| Старые данные POI | `data/pois.json` вшит в образ — после обновления данных нужен повторный `gcloud run deploy` |

## Приватность в проде
- Координаты огрубляются до ~100 м в браузере до отправки; бэкенд не пишет их в логи (в логах Cloud Run — только округлённые значения и id запроса).
- В образе нет `.env` и ключей; ключ приходит из Secret Manager / переменной окружения.
- Тайлы карты грузятся напрямую с `tile.openstreetmap.org` (с атрибуцией). Для демо-нагрузки этого достаточно; для реального трафика — свой тайл-провайдер.

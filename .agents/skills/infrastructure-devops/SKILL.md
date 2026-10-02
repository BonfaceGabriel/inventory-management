---
name: infrastructure-devops
description: Docker infrastructure, Celery task processing, and deployment configuration for this project. Use when working with docker-compose, Dockerfiles, nginx config, Celery worker/beat, Daphne ASGI server, environment configuration, supervisor process management, database migrations, and deployment to Render or Railway.
metadata:
  domain: infrastructure
  type: operations
---

## Architecture

```
nginx (80/443) ──→ web (Daphne ASGI :8000) ──→ PostgreSQL 14 (:5432)
                                        ──→ Redis 6.2 (:6379) ←── celery (worker + beat)
```

All services on `inventory-network` bridge network.

## Docker Services

| Service | Image | Purpose | Depends On |
|---------|-------|---------|------------|
| nginx | nginx:alpine | Reverse proxy, SSL termination | web (healthy) |
| web | Custom (Python 3.11) | Django/Daphne ASGI (HTTP + WebSocket) | db, redis |
| db | postgres:14 | PostgreSQL database | — |
| redis | redis:6.2-alpine | Cache, Celery broker, Channels layer | — |
| celery | Same as web | Background worker + Beat scheduler | db, redis |

## Key Commands

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f web        # Backend
docker-compose logs -f celery     # Celery

# Run tests
docker-compose exec web python manage.py test payments.tests

# Migrations
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py makemigrations

# Django shell
docker-compose exec web python manage.py shell
```

## Environment Configuration

- **File**: `.env` at project root, loaded by docker-compose.
- **Key vars**: `DATABASE_URL` / `DATABASE_*`, `SECRET_KEY`, `DEBUG`, `CELERY_BROKER_URL` (redis), `CORS_ALLOWED_ORIGINS`.
- **Production detection**: Via `RENDER` or `RAILWAY_ENVIRONMENT` env vars.
- **Frontend env**: Prefixed with `VITE_` — `VITE_API_URL`, `VITE_API_KEY`.

## Celery Configuration

- **App**: `management/celery.py` — creates Celery instance with Redis broker.
- **Tasks**: Two tasks in `payments/tasks.py`:
  1. `process_raw_message(message_id)` — Parses SMS and creates Transaction (triggered by message ingest)
  2. `generate_daily_report()` — Scheduled nightly at 23:59 EAT (20:59 UTC) via Celery Beat.
- **Beat schedule**: Defined in `management/celery.py` using `CELERY_BEAT_SCHEDULE`.
- **Runner**: `celery -A management worker --beat -l info` — both worker and beat in same process.
- **Timezone**: Celery Beat uses UTC internally but targets `Africa/Nairobi` via `CELERY_TIMEZONE`.

## ASGI / Daphne

- **Entrypoint**: `entrypoint.sh` runs migrations, then starts Daphne.
- **Daphne command**: `daphne -b 0.0.0.0 -p 8000 management.asgi:application`
- **ASGI config**: `management/asgi.py` applies the Channels protocol type router.
- **WebSocket path**: `ws://host/ws/transactions/` — routed via `payments/routing.py` → `payments/consumers.py`.

## Nginx Configuration

- **Location**: `backend/nginx.conf`.
- **Routes**: `/api/` → Django (proxy_pass to Daphne), `/ws/` → WebSocket upgrade, `/static/` → whitenoise.
- **Health check**: Nginx depends on web being healthy before starting.

## Deployment

- **Render**: `render.yaml` — defines services, environment, and build commands.
- **Production Dockerfile**: `backend/Dockerfile.prod` — multi-stage build.
- **Supervisor**: `supervisord.conf` manages Django process in production.
- **Static files**: Served via whitenoise middleware in production.

## Key Gotchas

- **`entrypoint.sh` runs migrations on every start**: That's by design for development. In production, migrations should be run separately.
- **Celery Beat timezone**: The schedule is defined in UTC (20:59:59) but targets Nairobi midnight (23:59:59 EAT). Don't change to Nairobi time in the schedule — it's intentionally UTC.
- **Redis for everything**: Cache + Celery broker + Channels layer all use the same Redis instance. No separate config needed.
- **Frontend runs natively**: Not in docker-compose for development. Run with `cd frontend && npm run dev` separately.
- **CORS**: Configured via `CORS_ALLOWED_ORIGINS` env var for the frontend URL(s).
- **Data persistence**: PostgreSQL data in Docker volume. Redis is in-memory (no persistence needed — it's a cache/broker).

## Anti-patterns

- Don't run Daphne with `--reload` in production — use proper process management (supervisor).
- Don't hardcode timezone offsets in Celery schedules — use `CELERY_TIMEZONE` and schedule in UTC with comments explaining the EAT equivalent.
- Don't forget to set `DEBUG=False` in production (detected via `RENDER`/`RAILWAY_ENVIRONMENT` env vars).
- Don't expose the `.env` file — it's in `.gitignore` and contains secrets.
- Don't run Celery without Redis running — tasks will silently fail.
- Don't skip the healthcheck on DB — the web service depends on it being ready.

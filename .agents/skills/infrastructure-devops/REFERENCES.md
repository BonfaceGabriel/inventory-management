# Infrastructure & DevOps Reference

## Service Map
| Service | Image | Port | Depends On |
|---|---|---|---|
| nginx | nginx:alpine | 80/443 | web (healthy) |
| web | Dockerfile (python:3.11-slim) | 8000 | db (healthy), redis |
| db | postgres:14 | 5432 | — |
| redis | redis:6.2-alpine | 6379 | — |
| celery | same as web | — | redis, db, web |

## Environment Variables
### Backend (`.env`)
| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | (required) | Django secret |
| `DEBUG` | True | Debug mode |
| `ALLOWED_HOSTS` | localhost,... | Allowed hostnames |
| `DATABASE_HOST` | db | PostgreSQL host |
| `DATABASE_NAME` | inventory | DB name |
| `DATABASE_USER` | gabriel | DB user |
| `DATABASE_PASSWORD` | (required) | DB password |
| `DATABASE_PORT` | 5432 | DB port |
| `CELERY_BROKER_URL` | redis://redis:6379/0 | Redis for Celery |
| `CELERY_RESULT_BACKEND` | redis://redis:6379/0 | Redis for results |
| `CORS_ALLOWED_ORIGINS` | (varies) | CORS allowed hosts |
| `DJANGO_LOG_LEVEL` | INFO | Django logging level |
| `APP_LOG_LEVEL` | INFO | App logging level |

### Frontend (`.env`)
| Variable | Example | Purpose |
|---|---|---|
| `VITE_API_URL` | http://localhost:8000/api/v1 | Backend API URL |
| `VITE_WS_URL` | ws://localhost:8000 | WebSocket URL |
| `VITE_API_KEY` | (from device reg) | API key for auth |

## Deployment Targets
| Target | Config | Notes |
|---|---|---|
| Docker Compose (dev) | `docker-compose.yml` | Full stack, hot reload |
| Render | `render.yaml` | Single container via supervisord (Daphne + Celery) |
| Dokploy | `frontend/docker-compose.yml` | Traefik reverse proxy, Let's Encrypt |
| Railway | Env detection `RAILWAY_ENVIRONMENT` | Auto-detected in settings |

## Production Entrypoint Flow (`entrypoint.prod.sh`)
1. Wait for PostgreSQL (30 retries, 2s interval)
2. Run `migrate --noinput`
3. Run `create_default_gateways`
4. Run `collectstatic --noinput`
5. Create admin superuser if not exists
6. Start supervisord (Daphne + Celery worker)

## Celery Config
- Broker + Backend: Redis
- Concurrency: 2 (supervisord config)
- Beat schedule defined in `management/settings.py` (CELERY_BEAT_SCHEDULE)
- Tasks: `process_raw_message` (async SMS), `generate_daily_report` (nightly)

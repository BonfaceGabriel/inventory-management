# Inventory Management System

A complete payment management and inventory system with real-time updates, built with Django REST Framework (backend) and React (frontend).

## Project Structure

```
inventory-management/
├── backend/                    # Django REST API
│   ├── payments/              # Main app
│   ├── management/            # Django project settings
│   ├── utils/                 # Shared utilities
│   ├── manage.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── [documentation files]
│
├── frontend/                  # React application (to be created)
│   ├── src/
│   ├── public/
│   └── package.json
│
├── docker-compose.yml         # Combined Docker setup
├── .env                       # Environment variables
└── README.md                  # This file
```

---

## Features

### Backend (Django REST API)
- ✅ **Real-time Transaction Updates** via WebSocket
- ✅ **Payment Gateway Management** (M-PESA, PDQ, Bank, Cash)
- ✅ **Transaction Lifecycle Management** with locking and status tracking
- ✅ **Manual Payment Entry** for non-SMS payments
- ✅ **Daily Reconciliation Reports** (JSON + PDF)
- ✅ **Settlement Calculations** by gateway
- ✅ **Discrepancy Detection** for quality control
- ✅ **Admin Interface** for management
- ✅ **SMS Message Parsing** with Celery async processing

### Frontend (React) - Coming Soon
- Real-time transaction dashboard
- Order management interface
- Report generation and download
- Payment gateway configuration
- Analytics and insights

---

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Git

### 1. Clone & Setup

```bash
# Already cloned, just ensure you're in the right directory
cd /home/gabriel/inventory-management

# Environment variables are already configured in .env
```

### 2. Start Backend Services

```bash
# Start all services (Django, PostgreSQL, Redis, Celery)
docker-compose up -d

# Check logs
docker-compose logs -f web

# Backend will be available at:
# - API: http://localhost:8000/api/v1/
# - Admin: http://localhost:8000/admin/
# - WebSocket: ws://localhost:8000/ws/transactions/
```

### 3. Access the System

**Admin Interface:**
```
http://localhost:8000/admin/
```

**API Documentation:**
- See `backend/RECONCILIATION_REPORTS.md` for API endpoints
- See `backend/WEBSOCKET_SETUP.md` for WebSocket integration

---

## Development

### Backend Development

```bash
# Run migrations
docker exec inventory-management-web-1 python manage.py migrate

# Create superuser
docker exec -it inventory-management-web-1 python manage.py createsuperuser

# Run tests
docker exec inventory-management-web-1 python manage.py test

# Django shell
docker exec -it inventory-management-web-1 python manage.py shell
```

### Frontend Development (Coming Soon)

```bash
# Create React app
cd frontend
npm install
npm start

# Frontend will run on http://localhost:3000
```

---

## API Endpoints

Base URL: `http://localhost:8000/api/v1/`

### Transactions
- `GET /transactions/` - List all transactions (with filtering)
- `GET /transactions/<id>/` - Get specific transaction
- `GET /transactions/by-tx-id/<tx_id>/` - Get by transaction ID

### Manual Payments
- `POST /payments/manual/` - Create manual payment
- `GET /payments/manual/list/` - List manual payments
- `GET /payments/manual/summary/` - Get summary

### Reports
- `GET /reports/daily-reconciliation/` - Daily report (JSON)
- `GET /reports/daily-reconciliation/pdf/` - Daily report (PDF download)
- `GET /reports/date-range-reconciliation/` - Date range report (JSON)
- `GET /reports/date-range-reconciliation/pdf/` - Date range report (PDF)
- `GET /reports/discrepancies/` - Discrepancy detection

### WebSocket
- `ws://localhost:8000/ws/transactions/` - Real-time transaction updates

**Authentication:** All endpoints require `X-API-KEY` header with device API key.

---

## Documentation

Detailed documentation in `backend/` directory:

- **[IMPLEMENTATION_SUMMARY.md](backend/IMPLEMENTATION_SUMMARY.md)** - Complete implementation overview
- **[WEBSOCKET_SETUP.md](backend/WEBSOCKET_SETUP.md)** - WebSocket integration guide
- **[RECONCILIATION_REPORTS.md](backend/RECONCILIATION_REPORTS.md)** - API documentation for reports
- **[PAYMENT_GATEWAY_SETUP.md](backend/PAYMENT_GATEWAY_SETUP.md)** - Gateway configuration guide

---

## Architecture

### Backend Stack
- **Framework:** Django 5.2.7 + Django REST Framework
- **Database:** PostgreSQL 14
- **Cache & Channels:** Redis 6.2
- **Task Queue:** Celery
- **WebSocket:** Django Channels + Daphne
- **PDF Generation:** ReportLab

### Frontend Stack (Planned)
- **Framework:** React 18
- **State Management:** React Context / Redux
- **Styling:** Tailwind CSS / Material-UI
- **WebSocket Client:** Native WebSocket API
- **HTTP Client:** Axios / Fetch

---

## Environment Variables

Key environment variables (in `.env`):

```bash
# Database
DATABASE_NAME=payment_mvp
DATABASE_USER=postgres
DATABASE_PASSWORD=postgres
DATABASE_HOST=db
DATABASE_PORT=5432

# Django
SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# CORS (for frontend)
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

---

## Deployment

### Backend Deployment

1. **Set production environment variables:**
   ```bash
   DEBUG=False
   ALLOWED_HOSTS=your-domain.com
   SECRET_KEY=strong-random-key
   ```

2. **Run migrations:**
   ```bash
   docker exec inventory-management-web-1 python manage.py migrate
   ```

3. **Collect static files:**
   ```bash
   docker exec inventory-management-web-1 python manage.py collectstatic --noinput
   ```

4. **Set up SSL/TLS for secure WebSocket (WSS)**

### Frontend Deployment (Coming Soon)

Options:
- Vercel (recommended for React)
- Netlify
- AWS S3 + CloudFront
- Same server as backend (Nginx)

---

## Common Tasks

### Configure Payment Gateways

```bash
# Via Django shell
docker exec -it inventory-management-web-1 python manage.py shell

# Follow instructions in backend/PAYMENT_GATEWAY_SETUP.md
```

### Generate Daily Report

```bash
# JSON
curl -H "X-API-KEY: your_key" \
  http://localhost:8000/api/v1/reports/daily-reconciliation/

# PDF download
curl -H "X-API-KEY: your_key" \
  http://localhost:8000/api/v1/reports/daily-reconciliation/pdf/ \
  --output report.pdf
```

### Test WebSocket Connection

```bash
# Using websocat
websocat ws://localhost:8000/ws/transactions/

# Using Python
python3 -c "
import asyncio
import websockets
import json

async def test():
    async with websockets.connect('ws://localhost:8000/ws/transactions/') as ws:
        print('Connected!')
        async for msg in ws:
            print(json.loads(msg))

asyncio.run(test())
"
```

---

## Troubleshooting

### Backend Issues

**Container won't start:**
```bash
# Check logs
docker-compose logs web

# Restart services
docker-compose restart

# Rebuild
docker-compose up -d --build
```

**Database connection error:**
```bash
# Check if DB is healthy
docker-compose ps

# Reset database (WARNING: deletes data)
docker-compose down -v
docker-compose up -d
```

**Import errors:**
```bash
# Clear Python cache
docker exec inventory-management-web-1 find /app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
docker-compose restart web
```

---

## Contributing

1. Create a feature branch
2. Make your changes
3. Write/update tests
4. Submit a pull request

---

## License

See [LICENSE](LICENSE) file for details.

---

## Support

For questions or issues:
1. Check the documentation in `backend/` directory
2. Review the code comments
3. Check Docker logs: `docker-compose logs`

---

## Status

- ✅ **Backend:** Production-ready
- 🔄 **Frontend:** In development
- 📝 **Documentation:** Complete

---

**Last Updated:** 2025-10-13

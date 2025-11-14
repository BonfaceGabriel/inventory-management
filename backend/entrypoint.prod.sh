#!/bin/bash
set -e

echo "Production Deployment - Starting..."

# Wait for database (using DATABASE_URL if available, otherwise use individual vars)
if [ -n "$DATABASE_URL" ]; then
  echo "Using DATABASE_URL for connection..."
  # Extract host from DATABASE_URL for pg_isready check
  DB_HOST=$(echo $DATABASE_URL | sed -n 's/.*@\([^:]*\):.*/\1/p')
  echo "Checking database connectivity to $DB_HOST..."

  # Simple retry loop for database (max 30 attempts = 60 seconds)
  MAX_ATTEMPTS=30
  ATTEMPT=0
  until python -c "import psycopg2; psycopg2.connect('$DATABASE_URL').close()" 2>/dev/null || [ $ATTEMPT -eq $MAX_ATTEMPTS ]; do
    echo "Database is unavailable - sleeping (attempt $ATTEMPT/$MAX_ATTEMPTS)"
    sleep 2
    ATTEMPT=$((ATTEMPT+1))
  done

  if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    echo "❌ Failed to connect to database after $MAX_ATTEMPTS attempts"
    exit 1
  fi
else
  echo "Using DATABASE_HOST for connection..."
  while ! pg_isready -h $DATABASE_HOST -p ${DATABASE_PORT:-5432} -U $DATABASE_USER 2>/dev/null; do
    echo "Database is unavailable - sleeping"
    sleep 2
  done
fi

echo "✓ PostgreSQL is ready!"
echo ""
echo "Running database migrations..."
python manage.py migrate --noinput

echo ""
echo "Creating default payment gateways..."
python manage.py create_default_gateways

echo ""
echo "Collecting static files..."
python manage.py collectstatic --noinput || echo "No static files to collect"

echo ""
echo "Creating superuser if not exists..."
python manage.py shell << EOF
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', '${ADMIN_PASSWORD:-changeme123}')
    print('✓ Superuser created')
    print('  Username: admin')
    print('  Password: ${ADMIN_PASSWORD:-changeme123}')
    print('  ⚠ CHANGE PASSWORD IMMEDIATELY AFTER FIRST LOGIN!')
else:
    print('○ Superuser already exists')
EOF

echo ""
echo "=========================================="
echo "Deployment completed successfully!"
echo "=========================================="
echo "Starting application..."
exec "$@"

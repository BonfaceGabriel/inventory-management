#!/bin/bash
set -e

echo "Production Deployment - Waiting for PostgreSQL..."
while ! pg_isready -h $DATABASE_HOST -p ${DATABASE_PORT:-5432} -U $DATABASE_USER 2>/dev/null; do
  echo "Database is unavailable - sleeping"
  sleep 2
done

echo "PostgreSQL is ready!"
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

#!/bin/bash
set -e

# Use DATABASE_HOST environment variable, fallback to 'db' if not set
DB_HOST=${DATABASE_HOST:-db}
DB_PORT=${DATABASE_PORT:-5432}

echo "Waiting for database to be ready at ${DB_HOST}:${DB_PORT}..."
until pg_isready -h "${DB_HOST}" -p "${DB_PORT}" -U "${DATABASE_USER}"; do
  echo "Database is unavailable - sleeping"
  sleep 2
done

echo "Database is up!"

# Always run migrations in production
echo "Running database migrations..."
python manage.py migrate

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Creating default payment gateways..."
python manage.py create_default_gateways || echo "Gateways already exist or creation failed"

if [ -n "$TELEGRAM_WEBHOOK_URL" ] && [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    echo "Setting Telegram webhook to $TELEGRAM_WEBHOOK_URL..."
    python manage.py run_bot --webhook "$TELEGRAM_WEBHOOK_URL" || echo "Webhook setup failed"
fi

echo "Executing command: $@"
exec "$@"
#!/bin/bash
set -e

echo "Waiting for database to be ready..."
until pg_isready -h db -U ${DATABASE_USER}; do
  echo "Database is unavailable - sleeping"
  sleep 1
done

# Run migrations only if the environment variable is set to true
if [ "$RUN_MIGRATIONS" = "true" ]; then
  echo "Database is up - applying migrations"
  python manage.py migrate
fi

echo "Executing command"
exec "$@"

#!/bin/bash
unset DOCKER_HOST
set -e

echo "Building and starting containers..."
docker compose up --build -d

echo "Application is running. Migrations will be applied automatically by the container."

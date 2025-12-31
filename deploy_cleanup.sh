#!/bin/bash
# Deployment script to clear active stock take sessions
# Run this during deployment to ensure no orphaned sessions

set -e

echo "========================================="
echo "Deployment Cleanup - Stock Take Sessions"
echo "========================================="

# Check if running in Docker
if [ -f /.dockerenv ]; then
    echo "Running inside Docker container..."
    python manage.py clear_active_stock_takes
else
    echo "Running via Docker exec..."
    docker exec inventory-management-web-1 python manage.py clear_active_stock_takes
fi

echo ""
echo "Cleanup complete!"

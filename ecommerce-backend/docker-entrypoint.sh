#!/bin/sh
set -e

# If starting the main FastAPI web server, run migrations first
if [ "$1" = "uvicorn" ]; then
    echo "Applying database migrations..."
    alembic upgrade head || {
        echo "Migration failed or database not ready, retrying in 3 seconds..."
        sleep 3
        alembic upgrade head
    }
    echo "Database migrations applied successfully."
fi

exec "$@"

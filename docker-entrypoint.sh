#!/bin/sh
set -e

echo "Running migrations..."
python manage.py migrate --noinput

if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_EMAIL" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    echo "Creating superuser (if it doesn't exist)..."
    python manage.py createsuperuser --noinput || true
fi

exec "$@"

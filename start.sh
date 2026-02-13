#!/bin/bash
echo "Running migrations..."
python manage.py migrate --noinput
echo "Collecting static files..."
python manage.py collectstatic --noinput
echo "Starting gunicorn..."
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3

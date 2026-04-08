#!/bin/bash
set -e
python manage.py migrate --noinput
python manage.py seed_templates
python manage.py seed_demo_data
python manage.py ensure_superuser
exec gunicorn config.wsgi:application -c gunicorn.conf.py --bind "0.0.0.0:${PORT:-8080}"

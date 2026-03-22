#!/bin/bash
set -e
python manage.py migrate --noinput
python manage.py seed_templates
exec gunicorn config.wsgi:application -c gunicorn.conf.py --bind "0.0.0.0:${PORT:-8080}"

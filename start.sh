#!/bin/bash
set -e
python manage.py migrate --noinput
python manage.py seed_templates
exec gunicorn config.wsgi:application

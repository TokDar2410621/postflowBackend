release: python manage.py migrate && python manage.py seed_templates
web: gunicorn config.wsgi:application

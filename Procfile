web: python manage.py migrate --noinput && python manage.py createcachetable 2>/dev/null || true && gunicorn config.wsgi:application

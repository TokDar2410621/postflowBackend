web: python manage.py migrate --noinput && python manage.py createcachetable --database default 2>/dev/null; gunicorn config.wsgi:application

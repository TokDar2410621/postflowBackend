import os

port = os.environ.get("PORT", "8080")
bind = f"0.0.0.0:{port}"
workers = 3
timeout = 120


def post_fork(server, worker):
    """Start the scheduler only in the FIRST worker to avoid duplicates."""
    # worker.age is the sequential worker number (1, 2, 3...)
    if worker.age == 1:
        server.log.info(f"Starting scheduler in worker {worker.pid}...")
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        import django
        django.setup()
        from api import scheduler
        scheduler.start()

import os
import subprocess
import sys


def on_starting(server):
    """Run Django management commands before workers start."""
    server.log.info("Running database migrations...")
    result = subprocess.run(
        [sys.executable, "manage.py", "migrate", "--noinput"],
        capture_output=False,
    )
    if result.returncode != 0:
        server.log.error("Migrations failed!")
        sys.exit(1)

    server.log.info("Collecting static files...")
    subprocess.run(
        [sys.executable, "manage.py", "collectstatic", "--noinput"],
        capture_output=False,
    )
    server.log.info("Ready to start workers.")


def post_fork(server, worker):
    """Start the scheduler only in the FIRST worker to avoid duplicates."""
    if worker.age == 1:
        server.log.info(f"Starting scheduler in worker {worker.pid}...")
        import django
        django.setup()
        from api import scheduler
        scheduler.start()


port = os.environ.get("PORT", "8080")
bind = f"0.0.0.0:{port}"
workers = 3

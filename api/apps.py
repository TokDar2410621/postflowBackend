from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        import os
        import sys

        # Only start scheduler for local dev (runserver).
        # In production (gunicorn), scheduler is started via post_fork hook.
        if 'runserver' not in sys.argv:
            return

        # Avoid double-start from runserver's reloader
        if os.environ.get('RUN_MAIN') != 'true':
            return

        try:
            from api import scheduler
            scheduler.start()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f'Scheduler not started: {e}')

from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        import os
        import sys

        # En dev (runserver), ne démarrer que dans le process enfant (reloader)
        is_runserver = 'runserver' in sys.argv
        if is_runserver and os.environ.get('RUN_MAIN') != 'true':
            return

        try:
            from api import scheduler
            scheduler.start()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f'Scheduler non démarré: {e}')

from django.core.management.base import BaseCommand
from api.schedule import publish_scheduled_posts


class Command(BaseCommand):
    help = 'Publie les posts programmés dont l\'heure est arrivée'

    def handle(self, *args, **options):
        count = publish_scheduled_posts()
        if count > 0:
            self.stdout.write(
                self.style.SUCCESS(f'{count} post(s) traité(s)')
            )
        else:
            self.stdout.write('Aucun post à traiter')

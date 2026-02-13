from django.core.management.base import BaseCommand
from api.linkedin import update_all_post_stats


class Command(BaseCommand):
    help = 'Met à jour les statistiques LinkedIn de tous les posts publiés récents'

    def handle(self, *args, **options):
        count = update_all_post_stats()
        if count > 0:
            self.stdout.write(
                self.style.SUCCESS(f'{count} post(s) mis à jour')
            )
        else:
            self.stdout.write('Aucun post à mettre à jour')

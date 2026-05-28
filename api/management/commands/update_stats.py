import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from api.linkedin import update_all_post_stats
from api.linkedin_rag import sync_user_posts_to_rag

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = (
        'Met à jour les statistiques LinkedIn des posts publiés récents '
        'puis re-synchronise les feedback_scores RAG en conséquence.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--skip-rag',
            action='store_true',
            help='Update stats only, skip the RAG feedback_score resync.',
        )

    def handle(self, *args, **options):
        count = update_all_post_stats()
        if count > 0:
            self.stdout.write(self.style.SUCCESS(f'{count} post(s) mis à jour'))
        else:
            self.stdout.write('Aucun post à mettre à jour')

        if options['skip_rag']:
            return

        users = User.objects.filter(published_posts__isnull=False).distinct()
        synced = 0
        for user in users:
            try:
                sync_user_posts_to_rag(user)
                synced += 1
            except Exception as e:
                logger.warning('rag sync failed for user=%s err=%s', user.pk, e)

        self.stdout.write(self.style.SUCCESS(
            f'RAG feedback_scores resyncés pour {synced} user(s)'
        ))

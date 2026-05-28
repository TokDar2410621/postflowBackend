"""Sync PublishedPost rows into the rag_memory_pgvector store.

Idempotent — safe to run repeatedly. Re-running refreshes feedback_scores
from current engagement stats without re-embedding unchanged content.

Usage:
    python manage.py import_linkedin_to_rag --user-id 42
    python manage.py import_linkedin_to_rag --all
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from api.linkedin_rag import sync_user_posts_to_rag

User = get_user_model()


class Command(BaseCommand):
    help = "Sync PublishedPost rows into rag_memory_pgvector (idempotent)."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--user-id",
            type=int,
            help="Sync a single user by PK.",
        )
        group.add_argument(
            "--all",
            action="store_true",
            help="Sync every user that has at least one PublishedPost.",
        )

    def handle(self, *args, **opts):
        if opts["user_id"]:
            try:
                user = User.objects.get(pk=opts["user_id"])
            except User.DoesNotExist:
                raise CommandError(f"User #{opts['user_id']} not found.")
            users = [user]
        else:
            users = list(
                User.objects.filter(published_posts__isnull=False).distinct()
            )

        self.stdout.write(f"Syncing {len(users)} user(s) to RAG…")
        grand = {"created": 0, "reused": 0, "errors": 0, "scored": 0}

        for user in users:
            totals = sync_user_posts_to_rag(user)
            self.stdout.write(
                f"  user={user.username} "
                f"posts={totals['total_posts']} "
                f"created={totals['created']} "
                f"reused={totals['reused']} "
                f"scored={totals['scored']} "
                f"baseline_views={totals['baseline_views']} "
                f"errors={totals['errors']}"
            )
            for k in grand:
                grand[k] += totals[k]

        style = self.style.SUCCESS if grand["errors"] == 0 else self.style.WARNING
        self.stdout.write(style(f"\nDone: {grand}"))

"""Run the L2 pattern extractor for one user or every eligible user.

Designed to be wired into a weekly scheduler job. Eligible users (>= 10
scored past posts) get their winning_patterns + anti_patterns refreshed;
others are skipped silently.

Usage:
    python manage.py extract_learned_patterns --user-id 42
    python manage.py extract_learned_patterns --all
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from api.pattern_extractor import extract_patterns_for_user

User = get_user_model()


class Command(BaseCommand):
    help = "Extract winning patterns + anti-patterns from each user's post history."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--user-id", type=int)
        group.add_argument("--all", action="store_true")

    def handle(self, *args, **opts):
        if opts["user_id"]:
            try:
                users = [User.objects.get(pk=opts["user_id"])]
            except User.DoesNotExist:
                raise CommandError(f"User #{opts['user_id']} not found.")
        else:
            users = list(
                User.objects.filter(published_posts__isnull=False).distinct()
            )

        self.stdout.write(f"Extracting patterns for {len(users)} user(s)…")
        ran = 0
        skipped = 0
        for user in users:
            result = extract_patterns_for_user(user)
            if result.get("skipped"):
                self.stdout.write(
                    f"  skip user={user.username} reason={result.get('reason')}"
                )
                skipped += 1
                continue
            self.stdout.write(self.style.SUCCESS(
                f"  user={user.username} "
                f"winning={result['winning_patterns_indexed']} "
                f"anti={result['anti_patterns_indexed']} "
                f"(top={result['top_posts_analyzed']}, "
                f"bottom={result['bottom_posts_analyzed']})"
            ))
            ran += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nDone: ran={ran} skipped={skipped}"
        ))

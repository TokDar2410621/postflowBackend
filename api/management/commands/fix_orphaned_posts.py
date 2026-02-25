"""One-shot command to reassign orphaned posts (user=NULL) to a specific user."""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from api.models import GeneratedPost, PublishedPost, ScheduledPost


class Command(BaseCommand):
    help = 'Reassign orphaned posts (user=NULL) to a specific user'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, help='Target username')
        parser.add_argument('--user-id', type=int, help='Target user ID')
        parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')

    def handle(self, *args, **options):
        # Find the target user
        if options['user_id']:
            user = User.objects.filter(id=options['user_id']).first()
        elif options['username']:
            user = User.objects.filter(username=options['username']).first()
        else:
            # If no user specified, list all users and orphan counts
            self.stdout.write("\n=== Users ===")
            for u in User.objects.all():
                self.stdout.write(f"  id={u.id}  username={u.username}  email={u.email}")

            orphan_gen = GeneratedPost.objects.filter(user__isnull=True).count()
            orphan_pub = PublishedPost.objects.filter(user__isnull=True).count()
            orphan_sch = ScheduledPost.objects.filter(user__isnull=True).count()

            self.stdout.write(f"\n=== Orphaned Posts ===")
            self.stdout.write(f"  GeneratedPost:  {orphan_gen}")
            self.stdout.write(f"  PublishedPost:  {orphan_pub}")
            self.stdout.write(f"  ScheduledPost:  {orphan_sch}")
            self.stdout.write(f"\nUsage: fix_orphaned_posts --username <name> [--dry-run]")
            return

        if not user:
            self.stderr.write("User not found!")
            return

        dry = options['dry_run']
        prefix = "[DRY RUN] " if dry else ""

        gen_count = GeneratedPost.objects.filter(user__isnull=True).count()
        pub_count = PublishedPost.objects.filter(user__isnull=True).count()
        sch_count = ScheduledPost.objects.filter(user__isnull=True).count()

        self.stdout.write(f"\n{prefix}Reassigning to user: {user.username} (id={user.id})")
        self.stdout.write(f"  GeneratedPost orphans: {gen_count}")
        self.stdout.write(f"  PublishedPost orphans: {pub_count}")
        self.stdout.write(f"  ScheduledPost orphans: {sch_count}")

        if not dry:
            GeneratedPost.objects.filter(user__isnull=True).update(user=user)
            PublishedPost.objects.filter(user__isnull=True).update(user=user)
            ScheduledPost.objects.filter(user__isnull=True).update(user=user)
            self.stdout.write(self.style.SUCCESS(f"\nDone! {gen_count + pub_count + sch_count} posts reassigned."))
        else:
            self.stdout.write(f"\n{prefix}No changes made. Remove --dry-run to apply.")

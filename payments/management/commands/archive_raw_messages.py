from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone
from datetime import timedelta
from payments.models import RawMessage

class Command(BaseCommand):
    help = 'Deletes raw messages older than a specified number of days.'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            '--days',
            type=int,
            default=180,
            help='The number of days to retain messages.'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='If set, the command will only count the messages to be deleted without actually deleting them.'
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']

        cutoff_date = timezone.now() - timedelta(days=days)

        old_messages = RawMessage.objects.filter(created_at__lt=cutoff_date)
        count = old_messages.count()

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f'[Dry Run] Found {count} messages older than {days} days to be deleted.'))
        else:
            if count > 0:
                old_messages.delete()
                self.stdout.write(self.style.SUCCESS(f'Successfully deleted {count} messages older than {days} days.'))
            else:
                self.stdout.write(self.style.SUCCESS('No old messages to delete.'))

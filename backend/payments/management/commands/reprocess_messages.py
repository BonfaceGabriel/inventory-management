"""
Management command to reprocess unprocessed raw messages.

This command finds all RawMessage records that have processed=False
and attempts to parse and create transactions for them.

Usage:
    python manage.py reprocess_messages [--all] [--limit N] [--dry-run]

Options:
    --all        Reprocess ALL unprocessed messages (default: only recent ones)
    --limit N    Limit processing to N messages (default: no limit)
    --dry-run    Show what would be processed without actually processing
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from payments.models import RawMessage
from payments.tasks import process_raw_message


class Command(BaseCommand):
    help = 'Reprocess unprocessed raw messages'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Reprocess all unprocessed messages (default: only last 30 days)',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limit number of messages to process',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be processed without actually processing',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of days to look back (default: 30)',
        )

    def handle(self, *args, **options):
        all_messages = options['all']
        limit = options['limit']
        dry_run = options['dry_run']
        days_back = options['days']

        self.stdout.write(self.style.SUCCESS('\n' + '='*70))
        self.stdout.write(self.style.SUCCESS('Reprocessing Unprocessed Messages'))
        self.stdout.write(self.style.SUCCESS('='*70 + '\n'))

        # Build query
        query = RawMessage.objects.filter(processed=False)

        # Filter by date if not processing all
        if not all_messages:
            cutoff_date = timezone.now() - timedelta(days=days_back)
            query = query.filter(created_at__gte=cutoff_date)
            self.stdout.write(f"Filtering to messages from last {days_back} days\n")
        else:
            self.stdout.write("Processing ALL unprocessed messages\n")

        # Order by creation date (must be before slice)
        query = query.order_by('created_at')

        # Apply limit if specified
        if limit:
            query = query[:limit]
            self.stdout.write(f"Limiting to {limit} messages\n")

        # Get messages
        messages = query
        total_count = messages.count()

        if total_count == 0:
            self.stdout.write(self.style.WARNING('No unprocessed messages found.'))
            return

        self.stdout.write(f"Found {total_count} unprocessed messages\n")
        self.stdout.write('='*70 + '\n')

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN MODE - No messages will be processed\n'))
            for msg in messages:
                self.stdout.write(f"\nMessage ID: {msg.id}")
                self.stdout.write(f"  Created: {msg.created_at}")
                self.stdout.write(f"  Device: {msg.device.name}")
                self.stdout.write(f"  Text: {msg.raw_text[:100]}...")
            return

        # Process messages
        success_count = 0
        duplicate_count = 0
        failed_count = 0

        for idx, msg in enumerate(messages, 1):
            self.stdout.write(f"\n[{idx}/{total_count}] Processing message ID: {msg.id}")
            self.stdout.write(f"  Created: {msg.created_at}")
            self.stdout.write(f"  Device: {msg.device.name}")
            self.stdout.write(f"  Text: {msg.raw_text[:80]}...")

            try:
                # Call the Celery task synchronously
                process_raw_message(msg.id)

                # Refresh from database
                msg.refresh_from_db()

                if msg.transaction:
                    self.stdout.write(self.style.SUCCESS(
                        f"  ✓ Created transaction: {msg.transaction.tx_id} "
                        f"(Ksh {msg.transaction.amount:,.2f})"
                    ))
                    success_count += 1
                elif msg.processed:
                    # Message was processed but no transaction (likely duplicate)
                    self.stdout.write(self.style.WARNING(
                        "  ⚠ Processed but no transaction created (likely duplicate)"
                    ))
                    duplicate_count += 1
                else:
                    self.stdout.write(self.style.WARNING(
                        "  ⚠ Failed to parse message with sufficient confidence"
                    ))
                    failed_count += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ✗ Error: {str(e)}"))
                failed_count += 1

        # Summary
        self.stdout.write('\n' + '='*70)
        self.stdout.write(self.style.SUCCESS('PROCESSING COMPLETE'))
        self.stdout.write('='*70)
        self.stdout.write(f"\nTotal messages processed: {total_count}")
        self.stdout.write(self.style.SUCCESS(f"  ✓ Successfully created: {success_count}"))
        self.stdout.write(self.style.WARNING(f"  ⚠ Duplicates/Skipped: {duplicate_count}"))
        self.stdout.write(self.style.ERROR(f"  ✗ Failed: {failed_count}"))
        self.stdout.write('\n' + '='*70 + '\n')

"""
Management command to reprocess unprocessed raw messages.

This command finds all RawMessage records that have processed=False
and attempts to parse and create transactions for them.

Usage:
    python manage.py reprocess_messages [--all] [--limit N] [--dry-run] [--analyze-failed]

Options:
    --all             Reprocess ALL unprocessed messages (default: only recent ones)
    --limit N         Limit processing to N messages (default: no limit)
    --dry-run         Show what would be processed without actually processing
    --analyze-failed  Analyze failed messages to identify parsing patterns
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from payments.models import RawMessage
from payments.tasks import process_raw_message
from payments.parsers import parse_mpesa_sms
import re
from collections import defaultdict


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
        parser.add_argument(
            '--analyze-failed',
            action='store_true',
            help='Analyze failed messages to identify parsing patterns',
        )

    def analyze_failed_messages(self, messages):
        """Analyze failed messages to identify patterns for parser updates."""
        self.stdout.write(self.style.SUCCESS('\n' + '='*70))
        self.stdout.write(self.style.SUCCESS('ANALYZING FAILED MESSAGES'))
        self.stdout.write(self.style.SUCCESS('='*70 + '\n'))

        failed_received = []
        failed_other = []

        for msg in messages:
            # Test if message can be parsed
            result = parse_mpesa_sms(msg.raw_text)

            # If confidence is 0, it failed to parse
            if result.get('confidence', 0) == 0:
                # Check if it's a "received" transaction
                if 'received from' in msg.raw_text.lower():
                    failed_received.append(msg)
                else:
                    failed_other.append(msg)

        self.stdout.write(f"\nTotal unparsed messages: {len(failed_received) + len(failed_other)}")
        self.stdout.write(f"  - Received transactions: {len(failed_received)}")
        self.stdout.write(f"  - Other messages: {len(failed_other)}\n")

        if failed_received:
            self.stdout.write(self.style.WARNING('\n' + '='*70))
            self.stdout.write(self.style.WARNING('UNPARSED RECEIVED TRANSACTIONS'))
            self.stdout.write(self.style.WARNING('='*70 + '\n'))

            # Group by pattern
            pattern_groups = defaultdict(list)

            for msg in failed_received[:50]:  # Limit to first 50
                # Extract key pattern features
                text = msg.raw_text

                # Identify format type
                if 'Confirmed. on' in text and 'received from' in text:
                    if re.search(r'\d{10}', text):  # Has 10-digit number
                        pattern_groups['new_format_with_10digit'].append(msg)
                    elif re.search(r'254\d{9}', text):  # Has 254... number
                        pattern_groups['new_format_with_254'].append(msg)
                    else:
                        pattern_groups['new_format_no_phone'].append(msg)
                elif 'You have received' in text:
                    pattern_groups['old_format'].append(msg)
                else:
                    pattern_groups['unknown_format'].append(msg)

            # Display examples from each group
            for pattern_name, msgs in pattern_groups.items():
                self.stdout.write(f"\n{self.style.WARNING(f'Pattern: {pattern_name}')} ({len(msgs)} messages)")
                self.stdout.write('-'*70)

                # Show first 3 examples
                for i, msg in enumerate(msgs[:3], 1):
                    self.stdout.write(f"\nExample {i} (ID: {msg.id}):")
                    self.stdout.write(f"Device: {msg.device.name}")
                    self.stdout.write(f"Created: {msg.created_at}")

                    # Show full text with line breaks visible
                    text_display = msg.raw_text.replace('\n', '\\n')[:300]
                    self.stdout.write(f"Text: {text_display}...")

                    # Try to extract key components
                    self.stdout.write("\nExtracted components:")

                    # TX ID
                    tx_match = re.search(r'^(\w+)\s+Confirmed', msg.raw_text)
                    if tx_match:
                        self.stdout.write(f"  TX ID: {tx_match.group(1)}")

                    # Amount
                    amount_match = re.search(r'Ksh\s*([\d,]+\.\d{2})', msg.raw_text)
                    if amount_match:
                        self.stdout.write(f"  Amount: {amount_match.group(1)}")

                    # Date/Time
                    date_match = re.search(r'on (\d{1,2}/\d{1,2}/\d{2,4}) at (\d{1,2}:\d{2}\s*[AP]M)', msg.raw_text)
                    if date_match:
                        self.stdout.write(f"  Date: {date_match.group(1)}, Time: {date_match.group(2)}")

                    # Sender info
                    received_match = re.search(r'received from (.+?)(?:\.|$|\sAccount|\sNew)', msg.raw_text, re.IGNORECASE)
                    if received_match:
                        self.stdout.write(f"  Sender: {received_match.group(1)[:100]}")

                    self.stdout.write('')

            # Provide parser update suggestions
            self.stdout.write('\n' + '='*70)
            self.stdout.write(self.style.SUCCESS('PARSER UPDATE SUGGESTIONS'))
            self.stdout.write('='*70 + '\n')

            for pattern_name, msgs in pattern_groups.items():
                if msgs:
                    self.stdout.write(f"\n{pattern_name}: {len(msgs)} messages")
                    self.stdout.write(f"  Action needed: Add parser pattern to handle this format")

        return len(failed_received)

    def handle(self, *args, **options):
        all_messages = options['all']
        limit = options['limit']
        dry_run = options['dry_run']
        days_back = options['days']
        analyze_failed = options['analyze_failed']

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

        # If analyze_failed flag is set, analyze and exit
        if analyze_failed:
            self.analyze_failed_messages(messages)
            return

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

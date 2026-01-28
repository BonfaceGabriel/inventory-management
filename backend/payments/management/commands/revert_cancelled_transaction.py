"""
Management command to revert a cancelled transaction to its initial state.

Usage:
    python manage.py revert_cancelled_transaction UAS6G4XTEO

This will:
1. Find the transaction by tx_id
2. Reset status to NOT_PROCESSED
3. Clear cancellation audit fields
4. Clear fulfillment amounts
5. Clear issuance-related fields
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from payments.models import Transaction
from decimal import Decimal


class Command(BaseCommand):
    help = 'Revert a cancelled transaction to its initial NOT_PROCESSED state'

    def add_arguments(self, parser):
        parser.add_argument(
            'tx_id',
            type=str,
            help='Transaction ID to revert (e.g., UAS6G4XTEO)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without making changes'
        )

    def handle(self, *args, **options):
        tx_id = options['tx_id']
        dry_run = options['dry_run']

        try:
            transaction = Transaction.objects.get(tx_id=tx_id)
        except Transaction.DoesNotExist:
            raise CommandError(f'Transaction with tx_id "{tx_id}" does not exist')

        # Show current state
        self.stdout.write(self.style.WARNING(f'\nCurrent state of transaction {tx_id}:'))
        self.stdout.write(f'  Status: {transaction.status}')
        self.stdout.write(f'  Amount: {transaction.amount}')
        self.stdout.write(f'  Amount Fulfilled: {transaction.amount_fulfilled}')
        self.stdout.write(f'  Amount Paid: {transaction.amount_paid}')
        self.stdout.write(f'  Is In Issuance: {transaction.is_in_issuance}')
        self.stdout.write(f'  Is Time Locked: {transaction.is_time_locked}')
        self.stdout.write(f'  Cancelled By: {transaction.cancelled_by}')
        self.stdout.write(f'  Cancelled At: {transaction.cancelled_at}')
        self.stdout.write(f'  Activated By: {transaction.activated_by}')
        self.stdout.write(f'  Activated At: {transaction.activated_at}')
        self.stdout.write(f'  Completed By: {transaction.completed_by}')
        self.stdout.write(f'  Completed At: {transaction.completed_at}')

        if transaction.status != Transaction.OrderStatus.CANCELLED:
            raise CommandError(
                f'Transaction is not CANCELLED (current status: {transaction.status}). '
                'This command only reverts CANCELLED transactions.'
            )

        if dry_run:
            self.stdout.write(self.style.NOTICE('\n[DRY RUN] Would make the following changes:'))
        else:
            self.stdout.write(self.style.WARNING('\nReverting transaction...'))

        # Reset fields to initial state
        changes = {
            'status': Transaction.OrderStatus.NOT_PROCESSED,
            'amount_fulfilled': Decimal('0.00'),
            'amount_paid': Decimal('0.00'),
            'total_cost': None,
            'total_pv': None,
            'is_in_issuance': False,
            'is_time_locked': False,
            'locked_at': None,
            'locked_by': '',
            'activated_by': None,
            'activated_at': None,
            'completed_by': None,
            'completed_at': None,
            'cancelled_by': None,
            'cancelled_at': None,
            'processed_by': None,
            'processed_at': None,
            'amount_fulfilled_before_activation': None,
            'status_before_activation': None,
        }

        for field, value in changes.items():
            current = getattr(transaction, field)
            if current != value:
                self.stdout.write(f'  {field}: {current} -> {value}')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\n[DRY RUN] No changes made.'))
            return

        # Apply changes
        for field, value in changes.items():
            setattr(transaction, field, value)

        # Save with skip_validation to bypass locked status check
        transaction.save(skip_validation=True)

        self.stdout.write(self.style.SUCCESS(
            f'\nTransaction {tx_id} has been reverted to NOT_PROCESSED state.'
        ))

        # Verify the change
        transaction.refresh_from_db()
        self.stdout.write(self.style.SUCCESS(f'Verified: Status is now {transaction.status}'))

"""
Management command to unmark a transaction as a registration and revert it to NOT_PROCESSED.

Use when a transaction was incorrectly flagged as a registration but no kit has been issued yet.

Usage:
    docker exec inventory-management-web-1 python manage.py unmark_registration <TX_ID>
    docker exec inventory-management-web-1 python manage.py unmark_registration <TX_ID> --dry-run
"""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from payments.models import Transaction


class Command(BaseCommand):
    help = 'Unmark a transaction as registration and revert it to NOT_PROCESSED'

    def add_arguments(self, parser):
        parser.add_argument('tx_id', type=str, help='Transaction ID to unmark')
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would change without saving',
        )

    def handle(self, *args, **options):
        tx_id = options['tx_id']
        dry_run = options['dry_run']

        try:
            txn = Transaction.objects.get(tx_id=tx_id)
        except Transaction.DoesNotExist:
            raise CommandError(f'Transaction "{tx_id}" does not exist')

        # --- safety checks ---
        if not txn.is_registration:
            raise CommandError(f'{tx_id} is not marked as a registration')

        if txn.registration_kit_issued:
            raise CommandError(
                f'{tx_id} already has a kit issued. '
                'This command only handles transactions where no kit has been issued yet.'
            )

        if txn.combined_orders.exists():
            raise CommandError(f'{tx_id} is part of a combined order. Handle manually.')

        if txn.line_items.filter(is_inventory_deducted=True).exists():
            raise CommandError(
                f'{tx_id} has deducted line items. '
                'This command only handles transactions with no fulfillment.'
            )

        # --- show current state ---
        self.stdout.write(self.style.WARNING(f'\nCurrent state of {tx_id}:'))
        self.stdout.write(f'  status:              {txn.status}')
        self.stdout.write(f'  is_registration:     {txn.is_registration}')
        self.stdout.write(f'  amount:              {txn.amount}')
        self.stdout.write(f'  amount_fulfilled:    {txn.amount_fulfilled}')
        self.stdout.write(f'  is_in_issuance:      {txn.is_in_issuance}')
        self.stdout.write(f'  activated_by:        {txn.activated_by}')
        self.stdout.write(f'  activated_at:        {txn.activated_at}')

        # --- compute changes ---
        changes = {
            'is_registration': False,
            'status': Transaction.OrderStatus.NOT_PROCESSED,
            'amount_fulfilled': Decimal('0.00'),
            'amount_paid': Decimal('0.00'),
            'is_in_issuance': False,
            'activated_by': None,
            'activated_at': None,
            'completed_by': None,
            'completed_at': None,
            'processed_by': None,
            'processed_at': None,
            'status_before_activation': None,
            'amount_fulfilled_before_activation': None,
        }

        self.stdout.write(self.style.WARNING('\nProposed changes:'))
        for field, new_val in changes.items():
            current = getattr(txn, field)
            if current != new_val:
                self.stdout.write(f'  {field}: {current} -> {new_val}')

        if dry_run:
            self.stdout.write(self.style.NOTICE('\n[DRY RUN] No changes made.'))
            return

        # --- apply ---
        for field, new_val in changes.items():
            setattr(txn, field, new_val)

        timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        txn.notes = (txn.notes or '') + (
            f'\n[{timestamp}] Registration flag removed and reverted to NOT_PROCESSED '
            f'via unmark_registration management command.'
        )

        txn.save(skip_validation=True)

        txn.refresh_from_db()
        self.stdout.write(self.style.SUCCESS(
            f'\n{tx_id} unmarked as registration. Status: {txn.status}'
        ))

"""
Reset transactions to baseline state.

Usage:
    python manage.py reset_transactions TX_ID1 TX_ID2 TX_ID3 ...

Example:
    python manage.py reset_transactions MAN-PDQ-20260114-9645 UAEFU3MWGY UAE713O3RC
"""

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone

from payments.models import Transaction, TransactionLineItem, InventoryMovement, Product


class Command(BaseCommand):
    help = 'Reset transactions to baseline state (NOT_PROCESSED, amount_fulfilled=0, return inventory)'

    def add_arguments(self, parser):
        parser.add_argument(
            'tx_ids',
            nargs='+',
            type=str,
            help='Transaction IDs to reset (space-separated)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes'
        )

    def handle(self, *args, **options):
        tx_ids = options['tx_ids']
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No changes will be made\n'))

        self.stdout.write('=' * 50)
        self.stdout.write('RESETTING TRANSACTIONS TO BASELINE')
        self.stdout.write('=' * 50)

        success_count = 0
        fail_count = 0

        try:
            with db_transaction.atomic():
                for tx_id in tx_ids:
                    if self.reset_transaction(tx_id, dry_run):
                        success_count += 1
                    else:
                        fail_count += 1

                if dry_run:
                    # Rollback by raising exception
                    self.stdout.write(self.style.WARNING('\nDRY RUN - Rolling back all changes'))
                    raise Exception('Dry run rollback')
        except Exception as e:
            if dry_run and 'Dry run rollback' in str(e):
                pass  # Expected for dry run
            else:
                raise

        self.stdout.write('\n' + '=' * 50)
        self.stdout.write(self.style.SUCCESS(f'Successfully reset: {success_count}'))
        if fail_count > 0:
            self.stdout.write(self.style.ERROR(f'Not found: {fail_count}'))
        self.stdout.write('Done!')

    def reset_transaction(self, tx_id, dry_run=False):
        """Reset a single transaction to baseline state."""
        try:
            txn = Transaction.objects.get(tx_id=tx_id)
        except Transaction.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'\n[NOT FOUND] {tx_id}'))
            return False

        self.stdout.write(f'\nTransaction: {tx_id}')
        self.stdout.write(f'  Status: {txn.status}')
        self.stdout.write(f'  Amount: {txn.amount}')
        self.stdout.write(f'  Amount Fulfilled: {txn.amount_fulfilled}')
        self.stdout.write(f'  Is Registration: {txn.is_registration}')
        self.stdout.write(f'  Kit Issued: {txn.registration_kit_issued}')

        # Get line items
        line_items = TransactionLineItem.objects.filter(transaction=txn)
        self.stdout.write(f'  Line Items: {line_items.count()}')

        # Return inventory for each line item
        for item in line_items.select_related('product'):
            product = Product.objects.select_for_update().get(id=item.product.id)
            qty_before = product.quantity
            product.quantity += item.quantity
            product.save()

            # Create inventory movement for audit trail
            InventoryMovement.objects.create(
                movement_type=InventoryMovement.MovementType.RETURN,
                product=product,
                quantity_before=qty_before,
                quantity_after=product.quantity,
                quantity_change=item.quantity,
                reference=f'Reset {tx_id}',
                performed_by='manage.py reset_transactions'
            )

            self.stdout.write(
                self.style.SUCCESS(f'    Returned {item.quantity}x {product.prod_name} (stock: {qty_before} -> {product.quantity})')
            )

        # Delete line items
        line_items.delete()

        # Return registration kit if issued
        if txn.is_registration and txn.registration_kit_issued and txn.registration_kit_quantity > 0:
            try:
                reg_kit = Product.objects.select_for_update().get(prod_code='REG_KIT_001')
                kit_qty = txn.registration_kit_quantity
                qty_before = reg_kit.quantity
                reg_kit.quantity += kit_qty
                reg_kit.save()

                InventoryMovement.objects.create(
                    movement_type=InventoryMovement.MovementType.RETURN,
                    product=reg_kit,
                    quantity_before=qty_before,
                    quantity_after=reg_kit.quantity,
                    quantity_change=kit_qty,
                    reference=f'Reset {tx_id} Kit',
                    performed_by='manage.py reset_transactions'
                )

                self.stdout.write(
                    self.style.SUCCESS(f'    Returned {kit_qty}x Registration Kit (stock: {qty_before} -> {reg_kit.quantity})')
                )
            except Product.DoesNotExist:
                self.stdout.write(self.style.WARNING('    [WARNING] REG_KIT_001 not found - kit not returned'))

        # Reset transaction fields
        txn.status = Transaction.OrderStatus.NOT_PROCESSED
        txn.amount_fulfilled = Decimal('0.00')
        txn.amount_paid = Decimal('0.00')  # Must reset both due to sync logic in save()
        txn.total_cost = Decimal('0.00')
        txn.total_pv = Decimal('0.00')
        txn.is_in_issuance = False

        # Clear tracking fields
        txn.amount_fulfilled_before_activation = None
        txn.status_before_activation = None
        txn.activated_by = None
        txn.activated_at = None
        txn.completed_by = None
        txn.completed_at = None
        txn.cancelled_by = None
        txn.cancelled_at = None

        # Clear registration kit fields
        if txn.is_registration:
            txn.registration_kit_issued = False
            txn.registration_kit_quantity = 0
            txn.registration_kit_amount_deducted = Decimal('0.00')

        # Add note
        reset_note = f"\n[{timezone.now().strftime('%Y-%m-%d %H:%M')}] RESET to baseline via manage.py"
        txn.notes = f"{txn.notes}{reset_note}" if txn.notes else reset_note

        # Save with skip_validation
        txn.save(skip_validation=True)

        self.stdout.write(self.style.SUCCESS(f'  [RESET] Status: NOT_PROCESSED, Amount Fulfilled: 0'))
        return True

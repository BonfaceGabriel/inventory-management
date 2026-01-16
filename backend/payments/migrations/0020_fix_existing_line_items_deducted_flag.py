# Generated migration to fix existing line items
# Sets is_inventory_deducted=True for all line items in completed/partially fulfilled transactions

from django.db import migrations


def fix_existing_line_items(apps, schema_editor):
    """
    Fix existing line items that should have is_inventory_deducted=True.

    Any transaction that is PARTIALLY_FULFILLED or FULFILLED has already had its
    inventory deducted, so all its line items should be marked accordingly.
    """
    TransactionLineItem = apps.get_model('payments', 'TransactionLineItem')
    CombinedOrderLineItem = apps.get_model('payments', 'CombinedOrderLineItem')

    # Fix transaction line items
    # For PARTIALLY_FULFILLED and FULFILLED transactions, mark all line items as deducted
    updated = TransactionLineItem.objects.filter(
        transaction__status__in=['PARTIALLY_FULFILLED', 'FULFILLED', 'COMBINED_FULFILLED'],
        is_inventory_deducted=False
    ).update(is_inventory_deducted=True)
    print(f"Updated {updated} transaction line items to is_inventory_deducted=True")

    # For combined orders that are PARTIALLY_FULFILLED or FULFILLED, mark their items
    updated_combined = CombinedOrderLineItem.objects.filter(
        combined_order__status__in=['PARTIALLY_FULFILLED', 'FULFILLED'],
        is_inventory_deducted=False,
        copied_from_transaction__isnull=True  # Only items scanned directly in combined order
    ).update(is_inventory_deducted=True)
    print(f"Updated {updated_combined} combined order line items to is_inventory_deducted=True")

    # Copied items from child transactions should always be marked as deducted
    # (they were already deducted in the source transaction)
    updated_copied = CombinedOrderLineItem.objects.filter(
        copied_from_transaction__isnull=False,
        is_inventory_deducted=False
    ).update(is_inventory_deducted=True)
    print(f"Updated {updated_copied} copied line items to is_inventory_deducted=True")


def reverse_fix(apps, schema_editor):
    """
    Reverse migration - set all back to False (data loss, use with caution)
    """
    # Note: This is destructive and loses information about which items were deducted
    # Only use in development/testing
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0019_add_inventory_tracking_fields'),
    ]

    operations = [
        migrations.RunPython(fix_existing_line_items, reverse_fix),
    ]

"""
Data migration: Create the "Main Shop" Location and assign all existing
Transaction, CombinedOrder, and User records to it.
"""
from django.db import migrations
import uuid


def create_main_shop(apps, schema_editor):
    Location = apps.get_model('payments', 'Location')
    Transaction = apps.get_model('payments', 'Transaction')
    CombinedOrder = apps.get_model('payments', 'CombinedOrder')
    User = apps.get_model('payments', 'User')

    main_shop, _ = Location.objects.get_or_create(
        location_type='MAIN',
        defaults={
            'id': uuid.uuid4(),
            'name': 'Main Shop',
            'status': 'ACTIVE',
            'notes': 'Primary shop location (auto-created by migration)',
        }
    )

    # Assign existing transactions to Main Shop
    Transaction.objects.filter(location__isnull=True).update(location=main_shop)

    # Assign existing combined orders to Main Shop
    CombinedOrder.objects.filter(location__isnull=True).update(location=main_shop)

    # Assign all users to Main Shop as their current_location
    User.objects.filter(current_location__isnull=True).update(current_location=main_shop)


def reverse_migration(apps, schema_editor):
    """Reversing just clears the assignments — the Location row is left."""
    Transaction = apps.get_model('payments', 'Transaction')
    CombinedOrder = apps.get_model('payments', 'CombinedOrder')
    User = apps.get_model('payments', 'User')
    Transaction.objects.all().update(location=None)
    CombinedOrder.objects.all().update(location=None)
    User.objects.all().update(current_location=None)


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0025_location_model'),
    ]

    operations = [
        migrations.RunPython(create_main_shop, reverse_migration),
    ]

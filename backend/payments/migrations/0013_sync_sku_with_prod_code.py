# Migration to sync SKU field with prod_code (they should be the same)

from django.db import migrations


def sync_sku_with_prod_code(apps, schema_editor):
    """
    Make SKU the same as prod_code for all products.

    User requirement: Product Code and SKU should be the same field.
    We keep both fields for backward compatibility but ensure they have the same value.
    """
    Product = apps.get_model('payments', 'Product')

    updated_count = 0
    for product in Product.objects.all():
        if product.sku != product.prod_code:
            product.sku = product.prod_code
            product.save(update_fields=['sku'])
            updated_count += 1
            print(f"Synced SKU for {product.prod_code}: {product.prod_name}")

    print(f"\nSKU sync complete: {updated_count} products updated")


def reverse_sync(apps, schema_editor):
    """Cannot reverse - no way to know original SKU values"""
    print("WARNING: SKU sync reversal not supported")


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0012_alter_product_cost_price_alter_product_current_price_and_more'),
    ]

    operations = [
        migrations.RunPython(sync_sku_with_prod_code, reverse_sync),
    ]

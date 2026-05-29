# Migration to update products to use Buying Price instead of Selling Price

from django.db import migrations
import openpyxl
from decimal import Decimal
import os
import sys


def update_product_prices_from_excel(apps, schema_editor):
    """
    Update all existing products to use Buying Price from Excel.

    Excel structure:
    - Column 4: Buying (KSH) → current_price (what resellers buy from us)
    - Column 5: Selling (KSH) → NOT USED (what resellers sell to customers)
    - Column 3: PV → current_pv

    Database mapping:
    - current_price = Buying Price from Excel
    - cost_price = Buying Price from Excel (same value, represents our cost structure)
    - current_pv = PV from Excel
    """
    # Avoid file-driven data changes during automated tests.
    if 'test' in sys.argv or os.environ.get('PYTEST_CURRENT_TEST'):
        print("Skipping Excel price update during tests.")
        return

    Product = apps.get_model('payments', 'Product')

    # Load Excel file
    try:
        wb = openpyxl.load_workbook('/app/products.xlsx')
        ws = wb['add sku field separte from barc']
    except Exception as e:
        print(f"Warning: Could not load products.xlsx: {e}")
        print("Skipping price update. Products will use existing prices.")
        return

    updated_count = 0
    skipped_count = 0

    # Build a mapping of product_name → (buying_price, pv, barcode)
    # Use product name as key since barcodes may be None in database
    price_map = {}

    for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        # Unpack row values (handle variable length rows)
        row_values = list(row)
        if len(row_values) < 7:
            continue  # Skip rows with insufficient data

        # Excel columns: Product Line, Product Name, PV, Selling (KSH), Buying (KSH), SKU, Barcode
        # Column indices: 0, 1, 2, 3, 4, 5, 6
        product_line = row_values[0]
        product_name = row_values[1]
        pv = row_values[2]
        selling_price = row_values[3]  # Column D: Selling (KSH) - what resellers sell to customers
        buying_price = row_values[4] if len(row_values) > 4 else None  # Column E: Buying (KSH) - what resellers pay us
        sku = row_values[5] if len(row_values) > 5 else None
        barcode = row_values[6] if len(row_values) > 6 else None

        if not product_name or not buying_price:
            continue

        # Normalize product name for matching (strip and lowercase)
        product_name_normalized = product_name.strip().lower()
        price_map[product_name_normalized] = {
            'buying_price': Decimal(str(buying_price)),
            'pv': Decimal(str(pv or 0)),
            'barcode': str(barcode).strip() if barcode else None,
            'name': product_name
        }

    print(f"Loaded {len(price_map)} products from Excel")

    # Update existing products
    for product in Product.objects.all():
        # Match by product name (normalized)
        product_name_normalized = product.prod_name.strip().lower()

        if product_name_normalized not in price_map:
            print(f"Skipped (not in Excel): {product.prod_code} - {product.prod_name}")
            skipped_count += 1
            continue

        price_data = price_map[product_name_normalized]
        buying_price = price_data['buying_price']
        pv = price_data['pv']

        # Update prices and barcode
        old_price = product.current_price
        old_pv = product.current_pv

        product.current_price = buying_price
        product.cost_price = buying_price  # Same as buying price
        product.current_pv = pv

        # Also update barcode if it was None
        if not product.barcode and price_data['barcode']:
            product.barcode = price_data['barcode']

        product.save()

        updated_count += 1
        if old_price != buying_price or old_pv != pv:
            print(f"Updated: {product.prod_code} - {product.prod_name}")
            print(f"  Price: {old_price} → {buying_price} | PV: {old_pv} → {pv}")

    print(f"\nPrice update complete:")
    print(f"  - Updated: {updated_count} products")
    print(f"  - Skipped: {skipped_count} products")


def reverse_update(apps, schema_editor):
    """
    Reverse is not possible without backup data.
    This would require re-importing from the old logic.
    """
    print("WARNING: Price update reversal not supported.")
    print("To revert, you would need to restore from backup or re-run original import.")


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0009_transaction_registration_kit_amount_deducted_and_more'),
    ]

    operations = [
        migrations.RunPython(update_product_prices_from_excel, reverse_update),
    ]

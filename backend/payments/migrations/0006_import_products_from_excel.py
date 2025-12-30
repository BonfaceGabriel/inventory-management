# Generated migration for importing products from Excel file

from django.db import migrations
import openpyxl
from decimal import Decimal


def import_products_from_excel(apps, schema_editor):
    """
    Import products from products.xlsx file.

    Creates:
    - ProductCategory entries
    - Product entries with barcode, pricing, and initial stock
    """
    Product = apps.get_model('payments', 'Product')
    ProductCategory = apps.get_model('payments', 'ProductCategory')

    # Load Excel file
    try:
        wb = openpyxl.load_workbook('/app/products.xlsx')
        ws = wb['add sku field separte from barc']
    except Exception as e:
        print(f"Warning: Could not load products.xlsx: {e}")
        print("Skipping product import. You can import manually later.")
        return

    # Track categories
    category_cache = {}
    current_category = None
    imported_count = 0
    skipped_count = 0

    for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        product_line, product_name, pv, selling_price, sku, barcode, _ = row

        # Skip empty rows
        if not product_name:
            continue

        # Update current category
        if product_line:
            current_category = product_line

            # Create category if not exists
            if current_category not in category_cache:
                category, created = ProductCategory.objects.get_or_create(
                    name=current_category,
                    defaults={'description': f'{current_category} products'}
                )
                category_cache[current_category] = category
                if created:
                    print(f"Created category: {current_category}")

        # Validate required fields
        if not barcode or not selling_price:
            print(f"Skipping row {row_num}: Missing barcode or price")
            skipped_count += 1
            continue

        # Generate SKU if not provided (use barcode as SKU)
        if not sku:
            sku = str(barcode).strip()

        # Generate unique product code
        # Format: First 2 letters of category + barcode last 4 digits
        category_prefix = ''.join(c for c in (current_category or 'GEN')[:2] if c.isalnum()).upper()
        barcode_suffix = str(barcode)[-4:] if len(str(barcode)) >= 4 else str(barcode)
        prod_code = f"{category_prefix}{barcode_suffix}"

        # Skip if product with this SKU already exists
        if Product.objects.filter(sku=sku).exists():
            print(f"Skipped (SKU exists): {sku} - {product_name}")
            skipped_count += 1
            continue

        # Make prod_code unique by adding counter if needed
        counter = 1
        original_prod_code = prod_code
        while Product.objects.filter(prod_code=prod_code).exists():
            prod_code = f"{original_prod_code}_{counter}"
            counter += 1

        # Calculate cost price (assume 60% of selling price as default)
        cost_price = Decimal(str(selling_price)) * Decimal('0.6')

        # Create product
        try:
            product = Product.objects.create(
                prod_code=prod_code,
                prod_name=product_name.strip(),
                sku=sku,
                sku_name=product_name.strip(),  # Use product name as SKU name
                barcode=str(barcode).strip(),
                current_price=Decimal(str(selling_price)),
                cost_price=cost_price,
                current_pv=Decimal(str(pv or 0)),
                quantity=0,  # Start with 0 stock (will be updated via stock-take)
                reorder_level=10,
                category=category_cache.get(current_category),
                is_active=True
            )
            imported_count += 1
            print(f"Imported: {prod_code} - {product_name}")
        except Exception as e:
            print(f"Error importing row {row_num} ({product_name}): {e}")
            skipped_count += 1

    print(f"\nImport complete:")
    print(f"  - Imported: {imported_count} products")
    print(f"  - Skipped: {skipped_count} products")
    print(f"  - Categories: {len(category_cache)}")


def reverse_import(apps, schema_editor):
    """
    Reverse the import by deleting imported products and categories.

    Note: This will delete ALL products and categories.
    Only use if you need to re-import from scratch.
    """
    Product = apps.get_model('payments', 'Product')
    ProductCategory = apps.get_model('payments', 'ProductCategory')

    # Delete products (except Registration Kit which was seeded earlier)
    deleted_products = Product.objects.exclude(prod_code='REG_KIT_001').delete()
    print(f"Deleted {deleted_products[0]} products")

    # Delete categories (except those with remaining products)
    deleted_categories = ProductCategory.objects.filter(products__isnull=True).delete()
    print(f"Deleted {deleted_categories[0]} categories")


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0005_product_barcode'),
    ]

    operations = [
        migrations.RunPython(import_products_from_excel, reverse_import),
    ]

"""
Django management command to import products from products.xlsx.

Usage:
    python manage.py import_products_excel
    python manage.py import_products_excel --clear  # Clear existing products first
    python manage.py import_products_excel --file /path/to/products.xlsx
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
from payments.models import Product, ProductCategory
import openpyxl
import os


class Command(BaseCommand):
    help = 'Import products from products.xlsx file'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear all existing products before importing',
        )
        parser.add_argument(
            '--file',
            type=str,
            default='/app/products.xlsx',
            help='Path to Excel file (default: /app/products.xlsx)',
        )

    def handle(self, *args, **options):
        excel_file = options['file']

        # Check if file exists
        if not os.path.exists(excel_file):
            self.stdout.write(
                self.style.ERROR(f'Error: File not found: {excel_file}')
            )
            return

        # Read Excel file
        self.stdout.write(f'Reading Excel file: {excel_file}')
        wb = openpyxl.load_workbook(excel_file)
        ws = wb.active  # Get first sheet

        # If --clear flag is set, delete all existing products
        if options['clear']:
            deleted_count = Product.objects.all().count()
            Product.objects.all().delete()
            self.stdout.write(
                self.style.WARNING(f'Deleted {deleted_count} existing products')
            )

        # Create/Get product categories from Product Line column
        categories = {}

        created_count = 0
        updated_count = 0
        skipped_count = 0

        # Process Excel rows
        # Skip header row (row 1)
        products_data = []
        current_product_line = None

        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            # Unpack row data
            product_line, product_name, pv, buying_price, selling_price, sku, barcode, notes = row

            # Track current product line (category)
            if product_line:
                current_product_line = product_line

            # Skip rows without product name
            if not product_name:
                continue

            # Skip notes like "print white", "out of stock", etc.
            if notes and isinstance(notes, str) and notes.lower() in ['print white', 'print', 'out of stock']:
                self.stdout.write(
                    self.style.WARNING(f'⚠ Row {row_idx}: Skipping "{product_name}" - {notes}')
                )
                skipped_count += 1
                continue

            products_data.append({
                'row': row_idx,
                'product_line': current_product_line,
                'product_name': product_name,
                'pv': pv,
                'buying_price': buying_price,
                'selling_price': selling_price,
                'sku': sku,
                'barcode': barcode,
                'notes': notes
            })

        self.stdout.write(f'Found {len(products_data)} products to import')
        self.stdout.write('='*80)

        # Import products
        with transaction.atomic():
            for data in products_data:
                product_line = data['product_line']
                product_name = data['product_name']
                pv = data['pv'] or Decimal('0.00')
                buying_price = data['buying_price'] or Decimal('0.00')
                selling_price = data['selling_price'] or Decimal('0.00')
                sku_value = data['sku']
                barcode = data['barcode']
                row_idx = data['row']

                # Get or create category
                if product_line and product_line not in categories:
                    category, created = ProductCategory.objects.get_or_create(
                        name=product_line,
                        defaults={'description': f'Products in {product_line} category'}
                    )
                    categories[product_line] = category
                    if created:
                        self.stdout.write(
                            self.style.SUCCESS(f'  ✓ Created category: {product_line}')
                        )

                category = categories.get(product_line)

                # Generate prod_code from product name (first 10 chars, uppercase, no spaces)
                prod_code_base = product_name.upper().replace(' ', '')[:10]
                prod_code = prod_code_base

                # Add suffix if duplicate
                suffix = 1
                while Product.objects.filter(prod_code=prod_code).exists():
                    prod_code = f"{prod_code_base}{suffix}"
                    suffix += 1

                # Use barcode as SKU if available, otherwise use product code
                if barcode and barcode != 'None':
                    # Convert barcode to string without decimal point
                    sku = str(int(barcode)) if isinstance(barcode, (int, float)) else str(barcode)
                elif sku_value:
                    sku = str(sku_value)
                else:
                    sku = prod_code

                # Ensure SKU is unique
                original_sku = sku
                suffix = 1
                while Product.objects.filter(sku=sku).exists():
                    sku = f"{original_sku}_{suffix}"
                    suffix += 1

                # SKU name - use product name as package description
                sku_name = product_name

                # Convert prices to Decimal
                try:
                    current_price = Decimal(str(selling_price))
                    cost_price = Decimal(str(buying_price))
                    current_pv = Decimal(str(pv))
                except (ValueError, TypeError) as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f'✗ Row {row_idx}: Error converting prices for {product_name}: {e}'
                        )
                    )
                    skipped_count += 1
                    continue

                # Create or update product
                try:
                    product, created = Product.objects.update_or_create(
                        prod_code=prod_code,
                        defaults={
                            'prod_name': product_name,
                            'sku': sku,
                            'sku_name': sku_name,
                            'current_price': current_price,
                            'cost_price': cost_price,
                            'current_pv': current_pv,
                            'quantity': 0,  # Start with zero inventory
                            'reorder_level': 10,  # Default reorder level
                            'category': category,
                            'is_active': True,
                        }
                    )

                    if created:
                        created_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'✓ Row {row_idx}: Created {prod_code} - {product_name} '
                                f'(Price: {current_price}, PV: {current_pv}, SKU: {sku})'
                            )
                        )
                    else:
                        updated_count += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f'↻ Row {row_idx}: Updated {prod_code} - {product_name} '
                                f'(Price: {current_price}, PV: {current_pv}, SKU: {sku})'
                            )
                        )
                except Exception as e:
                    skipped_count += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f'✗ Row {row_idx}: Error creating {product_name}: {e}'
                        )
                    )

        # Summary
        self.stdout.write(self.style.SUCCESS('\n' + '='*80))
        self.stdout.write(self.style.SUCCESS('IMPORT SUMMARY'))
        self.stdout.write(self.style.SUCCESS('='*80))
        self.stdout.write(self.style.SUCCESS(f'Created: {created_count}'))
        self.stdout.write(self.style.WARNING(f'Updated: {updated_count}'))
        self.stdout.write(self.style.ERROR(f'Skipped: {skipped_count}'))
        self.stdout.write(self.style.SUCCESS(f'Categories: {len(categories)}'))
        self.stdout.write(self.style.SUCCESS(f'Total Products: {Product.objects.count()}'))
        self.stdout.write(self.style.SUCCESS('='*80))
        self.stdout.write(
            self.style.SUCCESS(
                '\n✓ Product import completed successfully!'
            )
        )

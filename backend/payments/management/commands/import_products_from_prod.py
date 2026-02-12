"""
Management command to import products from production to development environment.

Supports two modes:
1. Import from JSON file exported from production
2. Export products from current environment to JSON

Usage:
    # Step 1: Export products from production (run this on PRODUCTION)
    docker compose exec web python manage.py import_products_from_prod --export products.json

    # Step 2: Copy products.json to development environment, then import
    docker compose exec web python manage.py import_products_from_prod --file products.json

    # Preview changes without saving
    docker compose exec web python manage.py import_products_from_prod --file products.json --dry-run

    # Update existing products instead of skipping
    docker compose exec web python manage.py import_products_from_prod --file products.json --update-existing

    # Reset quantity to 0 (recommended for dev)
    docker compose exec web python manage.py import_products_from_prod --file products.json --reset-quantity
"""

import json
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from payments.models import Product, ProductLine


class Command(BaseCommand):
    help = 'Import products from production environment via JSON export/import'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            help='JSON file to import from',
        )
        parser.add_argument(
            '--export',
            type=str,
            help='Export current products to JSON file (use this on production)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be imported without saving',
        )
        parser.add_argument(
            '--update-existing',
            action='store_true',
            help='Update existing products instead of skipping them',
        )
        parser.add_argument(
            '--reset-quantity',
            action='store_true',
            help='Reset quantity to 0 for imported products (recommended for dev)',
        )

    def handle(self, *args, **options):
        export_file = options.get('export')
        import_file = options.get('file')
        dry_run = options['dry_run']
        update_existing = options['update_existing']
        reset_quantity = options['reset_quantity']

        if export_file:
            self.export_products(export_file)
            return

        if not import_file:
            raise CommandError('Either --file or --export must be specified')

        self.import_products(import_file, dry_run, update_existing, reset_quantity)

    def export_products(self, filename):
        """Export products and product lines to JSON file"""
        self.stdout.write(self.style.NOTICE('Exporting products from current environment...'))

        # Export product lines first (to preserve relationships)
        product_lines = []
        for pl in ProductLine.objects.all().order_by('id'):
            product_lines.append({
                'name': pl.name,
                'description': pl.description,
                'parent_line': pl.parent_line.name if pl.parent_line else None,
            })

        # Export products
        products = []
        for prod in Product.objects.all().order_by('prod_code'):
            products.append({
                'prod_code': prod.prod_code,
                'prod_name': prod.prod_name,
                'sku': prod.sku,
                'sku_name': prod.sku_name,
                'barcode': prod.barcode,
                'current_price': str(prod.current_price),
                'cost_price': str(prod.cost_price),
                'current_pv': str(prod.current_pv),
                'quantity': prod.quantity,
                'reorder_level': prod.reorder_level,
                'product_line': prod.product_line.name if prod.product_line else None,
                'is_active': prod.is_active,
            })

        data = {
            'product_lines': product_lines,
            'products': products,
            'export_metadata': {
                'total_lines': len(product_lines),
                'total_products': len(products),
            }
        }

        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)

        self.stdout.write(self.style.SUCCESS('\n' + '='*70))
        self.stdout.write(self.style.SUCCESS(
            f'✓ Exported {len(product_lines)} product lines and {len(products)} products to {filename}'
        ))
        self.stdout.write(self.style.SUCCESS('='*70))
        self.stdout.write(f'\nNext steps:')
        self.stdout.write(f'1. Copy {filename} to your development environment')
        self.stdout.write(f'2. Run: docker compose exec web python manage.py import_products_from_prod --file {filename}')

    def import_products(self, filename, dry_run, update_existing, reset_quantity):
        """Import products from JSON file"""
        self.stdout.write(self.style.NOTICE(f'Reading products from {filename}...'))

        try:
            with open(filename, 'r') as f:
                data = json.load(f)
        except FileNotFoundError:
            raise CommandError(f'File not found: {filename}')
        except json.JSONDecodeError as e:
            raise CommandError(f'Invalid JSON: {e}')

        product_lines_data = data.get('product_lines', [])
        products_data = data.get('products', [])

        self.stdout.write(f'Found {len(product_lines_data)} product lines and {len(products_data)} products\n')

        if dry_run:
            self.stdout.write(self.style.WARNING('[DRY RUN MODE] - No changes will be saved\n'))

        if reset_quantity:
            self.stdout.write(self.style.NOTICE('[RESET QUANTITY] - All product quantities will be set to 0\n'))

        # Track statistics
        stats = {
            'lines_created': 0,
            'lines_skipped': 0,
            'products_created': 0,
            'products_updated': 0,
            'products_skipped': 0,
        }

        # Import product lines first (handle parent relationships)
        if not dry_run:
            with transaction.atomic():
                stats = self._import_product_lines(product_lines_data, stats)
                stats = self._import_products(
                    products_data,
                    stats,
                    update_existing,
                    reset_quantity
                )
        else:
            # Dry run - don't use transaction
            stats = self._import_product_lines(product_lines_data, stats, dry_run=True)
            stats = self._import_products(
                products_data,
                stats,
                update_existing,
                reset_quantity,
                dry_run=True
            )

        # Print summary
        self.stdout.write(self.style.SUCCESS('\n' + '='*70))
        self.stdout.write(self.style.SUCCESS('IMPORT SUMMARY'))
        self.stdout.write(self.style.SUCCESS('='*70))
        self.stdout.write(f"Product Lines:")
        self.stdout.write(f"  Created: {stats['lines_created']}")
        self.stdout.write(f"  Skipped: {stats['lines_skipped']}")
        self.stdout.write(f"\nProducts:")
        self.stdout.write(f"  Created: {stats['products_created']}")
        if update_existing:
            self.stdout.write(f"  Updated: {stats['products_updated']}")
        self.stdout.write(f"  Skipped: {stats['products_skipped']}")
        self.stdout.write(self.style.SUCCESS('='*70))

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[DRY RUN] No changes were saved'))
        else:
            self.stdout.write(self.style.SUCCESS('\n✓ Import completed successfully'))
            self.stdout.write(f'\nTotal products in database: {Product.objects.count()}')

    def _import_product_lines(self, product_lines_data, stats, dry_run=False):
        """Import product lines, handling parent relationships"""
        if not product_lines_data:
            return stats

        self.stdout.write(self.style.NOTICE('Importing product lines...'))

        # First pass: create product lines without parents
        created_lines = {}
        for pl_data in product_lines_data:
            name = pl_data['name']

            if not dry_run:
                existing = ProductLine.objects.filter(name=name).first()
                if existing:
                    created_lines[name] = existing
                    stats['lines_skipped'] += 1
                    self.stdout.write(f"  ↷ Skipped: {name} (already exists)")
                    continue

                pl = ProductLine(
                    name=name,
                    description=pl_data.get('description', ''),
                )
                pl.save()
                created_lines[name] = pl
                stats['lines_created'] += 1
                self.stdout.write(self.style.SUCCESS(f"  ✓ Created: {name}"))
            else:
                existing = ProductLine.objects.filter(name=name).exists()
                if existing:
                    self.stdout.write(f"  → Would skip: {name} (already exists)")
                    stats['lines_skipped'] += 1
                else:
                    self.stdout.write(f"  → Would create: {name}")
                    stats['lines_created'] += 1

        # Second pass: update parent relationships
        if not dry_run:
            for pl_data in product_lines_data:
                parent_name = pl_data.get('parent_line')
                if parent_name:
                    name = pl_data['name']
                    if name in created_lines and parent_name in created_lines:
                        pl = created_lines[name]
                        pl.parent_line = created_lines[parent_name]
                        pl.save()
                        self.stdout.write(f"    ↳ Set parent: {name} → {parent_name}")

        return stats

    def _import_products(self, products_data, stats, update_existing, reset_quantity, dry_run=False):
        """Import products"""
        self.stdout.write(self.style.NOTICE('\nImporting products...'))

        for idx, prod_data in enumerate(products_data, start=1):
            prod_code = prod_data['prod_code']
            prod_name = prod_data['prod_name']

            if not dry_run:
                existing = Product.objects.filter(prod_code=prod_code).first()

                if existing:
                    if update_existing:
                        self._update_product(existing, prod_data, reset_quantity)
                        stats['products_updated'] += 1
                        qty_info = " (qty reset to 0)" if reset_quantity else f" (qty: {prod_data['quantity']})"
                        self.stdout.write(self.style.WARNING(
                            f"  [{idx}/{len(products_data)}] ⟳ Updated: {prod_code} - {prod_name}{qty_info}"
                        ))
                    else:
                        stats['products_skipped'] += 1
                        self.stdout.write(
                            f"  [{idx}/{len(products_data)}] ↷ Skipped: {prod_code} (already exists)"
                        )
                    continue

                self._create_product(prod_data, reset_quantity)
                stats['products_created'] += 1
                qty_info = " (qty: 0)" if reset_quantity else f" (qty: {prod_data['quantity']})"
                self.stdout.write(self.style.SUCCESS(
                    f"  [{idx}/{len(products_data)}] ✓ Created: {prod_code} - {prod_name}{qty_info}"
                ))
            else:
                # Dry run
                existing = Product.objects.filter(prod_code=prod_code).first()
                if existing:
                    if update_existing:
                        self.stdout.write(
                            f"  [{idx}/{len(products_data)}] → Would update: {prod_code} - {prod_name}"
                        )
                        stats['products_updated'] += 1
                    else:
                        self.stdout.write(
                            f"  [{idx}/{len(products_data)}] → Would skip: {prod_code} (already exists)"
                        )
                        stats['products_skipped'] += 1
                else:
                    self.stdout.write(
                        f"  [{idx}/{len(products_data)}] → Would create: {prod_code} - {prod_name}"
                    )
                    stats['products_created'] += 1

        return stats

    def _create_product(self, prod_data, reset_quantity):
        """Create a new product"""
        product_line = None
        if prod_data.get('product_line'):
            product_line = ProductLine.objects.filter(name=prod_data['product_line']).first()

        quantity = 0 if reset_quantity else prod_data['quantity']

        Product.objects.create(
            prod_code=prod_data['prod_code'],
            prod_name=prod_data['prod_name'],
            sku=prod_data['sku'],
            sku_name=prod_data['sku_name'],
            barcode=prod_data.get('barcode'),
            current_price=Decimal(prod_data['current_price']),
            cost_price=Decimal(prod_data['cost_price']),
            current_pv=Decimal(prod_data['current_pv']),
            quantity=quantity,
            reorder_level=prod_data['reorder_level'],
            product_line=product_line,
            is_active=prod_data['is_active'],
        )

    def _update_product(self, product, prod_data, reset_quantity):
        """Update an existing product"""
        product_line = None
        if prod_data.get('product_line'):
            product_line = ProductLine.objects.filter(name=prod_data['product_line']).first()

        product.prod_name = prod_data['prod_name']
        product.sku = prod_data['sku']
        product.sku_name = prod_data['sku_name']
        product.barcode = prod_data.get('barcode')
        product.current_price = Decimal(prod_data['current_price'])
        product.cost_price = Decimal(prod_data['cost_price'])
        product.current_pv = Decimal(prod_data['current_pv'])
        product.quantity = 0 if reset_quantity else prod_data['quantity']
        product.reorder_level = prod_data['reorder_level']
        product.product_line = product_line
        product.is_active = prod_data['is_active']
        product.save()

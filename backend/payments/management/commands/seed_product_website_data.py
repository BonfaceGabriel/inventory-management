"""
Management command to seed product descriptions and image URLs for the
inventory API (BF SUMA Eagleshop website).

Usage:
    python manage.py seed_product_website_data
    python manage.py seed_product_website_data --file /app/seed_data/product_website_data.json
    python manage.py seed_product_website_data --dry-run  # Preview without saving
"""

import json
from django.core.management.base import BaseCommand
from payments.models import Product


class Command(BaseCommand):
    help = 'Seed description and image_url on products for the website catalog'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default='/app/seed_data/product_website_data.json',
            help='Path to JSON file with product website data',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without saving to database',
        )

    def handle(self, *args, **options):
        file_path = options['file']
        dry_run = options['dry_run']

        try:
            with open(file_path) as f:
                data = json.load(f)
        except FileNotFoundError:
            self.stderr.write(self.style.ERROR(f'File not found: {file_path}'))
            return
        except json.JSONDecodeError as e:
            self.stderr.write(self.style.ERROR(f'Invalid JSON: {e}'))
            return

        updates = 0
        skipped = 0
        errors = 0

        for entry in data:
            code = entry.get('code', '').strip()
            if not code:
                skipped += 1
                continue

            description = entry.get('description', '')
            image_url = entry.get('image_url', '')

            try:
                product = Product.objects.get(prod_code=code)
            except Product.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f'  Product not found: {code}')
                )
                errors += 1
                continue

            changed = False
            if description and product.description != description:
                product.description = description
                changed = True
            if image_url and product.image_url != image_url:
                product.image_url = image_url
                changed = True

            if changed:
                if not dry_run:
                    product.save(update_fields=['description', 'image_url'])
                updates += 1
                self.stdout.write(
                    f'  {code}: {"would update" if dry_run else "updated"}'
                )

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {updates} updated, {skipped} skipped, {errors} errors'
            f'{" (dry run)" if dry_run else ""}'
        ))

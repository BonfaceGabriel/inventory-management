"""
Management command to batch-update product prod_code using
a JSON mapping file.

Useful for fixing auto-generated codes on deployed instances.
Only updates prod_code (leaves sku and barcode unchanged).

Usage:
    python manage.py update_product_codes --file /app/seed_data/code_mapping.json
    python manage.py update_product_codes --file /path/to/mapping.json --dry-run
    python manage.py update_product_codes --file /path/to/mapping.json --commit

Mapping file format:
    [
        {"old_code": "4IN1CORDYC", "new_code": "IM2937"},
        {"old_code": "PURE&BROKE", "new_code": "IM2128"},
        ...
    ]
"""
import json
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F
from payments.models import Product


class Command(BaseCommand):
    help = 'Batch-update product codes (prod_code & sku) from a JSON mapping'

    def add_arguments(self, parser):
        parser.add_argument('--file', required=True, help='Path to JSON mapping file')
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Validate mapping without saving changes',
        )
        parser.add_argument(
            '--commit',
            action='store_true',
            help='Actually apply changes (required for safety)',
        )

    def handle(self, *args, **options):
        file_path = options['file']
        dry_run = options['dry_run']
        commit = options['commit']

        if not dry_run and not commit:
            self.stderr.write(
                self.style.WARNING(
                    'Dry run mode. Use --commit to apply changes, or --dry-run to preview.'
                )
            )
            dry_run = True

        try:
            with open(file_path) as f:
                mapping = json.load(f)
        except FileNotFoundError:
            raise CommandError(f'File not found: {file_path}')
        except json.JSONDecodeError as e:
            raise CommandError(f'Invalid JSON: {e}')

        if not isinstance(mapping, list):
            raise CommandError('Mapping file must contain a JSON array')

        updated = 0
        skipped = 0
        errors = []

        # Pre-validate: check for duplicate new_codes
        new_codes = [entry.get('new_code', '').strip() for entry in mapping if entry.get('new_code')]
        seen = set()
        duplicates = set()
        for code in new_codes:
            if code in seen:
                duplicates.add(code)
            seen.add(code)
        if duplicates:
            raise CommandError(f'Duplicate new_codes in mapping: {", ".join(duplicates)}')

        for entry in mapping:
            old_code = entry.get('old_code', '').strip()
            new_code = entry.get('new_code', '').strip()

            if not old_code or not new_code:
                skipped += 1
                continue

            if old_code == new_code:
                skipped += 1
                continue

            try:
                product = Product.objects.get(prod_code=old_code)
            except Product.DoesNotExist:
                errors.append(f'Product with prod_code "{old_code}" not found')
                continue

            # Check new_code doesn't already exist on a different product
            existing = Product.objects.filter(prod_code=new_code).exclude(pk=product.pk).first()
            if existing:
                errors.append(
                    f'Cannot rename "{old_code}" to "{new_code}": '
                    f'product "{existing.prod_name}" already has that code'
                )
                continue

            if not dry_run:
                with transaction.atomic():
                    product.prod_code = new_code
                    product.save(update_fields=['prod_code'])

            updated += 1
            self.stdout.write(
                f'  {old_code:20s} → {new_code:20s}  '
                f'({product.prod_name[:40]})'
                f'{" [DRY RUN]" if dry_run else ""}'
            )

        self.stdout.write()
        if errors:
            self.stdout.write(self.style.WARNING(f'Errors ({len(errors)}):'))
            for error in errors:
                self.stdout.write(f'  ⚠ {error}')

        self.stdout.write(self.style.SUCCESS(
            f'\nDone: {updated} updated, {skipped} skipped, {len(errors)} errors'
            f'{" (dry run)" if dry_run else ""}'
        ))

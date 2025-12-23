"""
Django management command to fix device-gateway assignments.

This corrects devices that were assigned to wrong gateways before
alphabetical ordering was implemented.

Usage:
    python manage.py fix_device_gateways
    python manage.py fix_device_gateways --dry-run  # Preview changes without applying
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from payments.models import Device, PaymentGateway


class Command(BaseCommand):
    help = 'Fix device-gateway assignments based on device naming conventions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without applying them',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('\n=== DRY RUN MODE - No changes will be saved ===\n'))

        # Get gateways
        try:
            paybill_gateway = PaymentGateway.objects.get(name='Paybill Parent Company')
            till_products_gateway = PaymentGateway.objects.get(name='Till Products')
            till_merchandise_gateway = PaymentGateway.objects.get(name='Till Merchandise')
        except PaymentGateway.DoesNotExist as e:
            self.stdout.write(self.style.ERROR(f'Error: Required gateway not found: {e}'))
            return

        # Define mapping rules based on device names
        mapping_rules = [
            {
                'name_contains': 'paybill',
                'correct_gateway': paybill_gateway,
                'gateway_name': 'Paybill Parent Company'
            },
            {
                'name_contains': 'product',
                'correct_gateway': till_products_gateway,
                'gateway_name': 'Till Products'
            },
            {
                'name_contains': 'supplement',
                'correct_gateway': till_products_gateway,
                'gateway_name': 'Till Products'
            },
            {
                'name_contains': 'merchandise',
                'correct_gateway': till_merchandise_gateway,
                'gateway_name': 'Till Merchandise'
            },
        ]

        devices = Device.objects.all()
        fixed_count = 0
        unchanged_count = 0

        self.stdout.write('\n' + '='*80)
        self.stdout.write('CHECKING DEVICE-GATEWAY ASSIGNMENTS')
        self.stdout.write('='*80 + '\n')

        with transaction.atomic():
            for device in devices:
                device_name_lower = device.name.lower()
                current_gateway = device.gateway
                correct_gateway = None
                matched_rule = None

                # Find matching rule
                for rule in mapping_rules:
                    if rule['name_contains'] in device_name_lower:
                        correct_gateway = rule['correct_gateway']
                        matched_rule = rule
                        break

                if correct_gateway is None:
                    self.stdout.write(
                        self.style.WARNING(
                            f'⚠ Device "{device.name}" - No matching rule found, keeping current gateway: '
                            f'{current_gateway.name if current_gateway else "None"}'
                        )
                    )
                    unchanged_count += 1
                    continue

                # Check if gateway needs updating
                if current_gateway != correct_gateway:
                    self.stdout.write(
                        self.style.ERROR(
                            f'✗ Device "{device.name}":\n'
                            f'    Current:  {current_gateway.name if current_gateway else "None"} (ID: {current_gateway.id if current_gateway else "N/A"})\n'
                            f'    Expected: {matched_rule["gateway_name"]} (ID: {correct_gateway.id})'
                        )
                    )

                    if not dry_run:
                        device.gateway = correct_gateway
                        device.save()
                        self.stdout.write(
                            self.style.SUCCESS(f'    ✓ Updated to {matched_rule["gateway_name"]}')
                        )

                    fixed_count += 1
                else:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✓ Device "{device.name}" - Correct gateway: {current_gateway.name}'
                        )
                    )
                    unchanged_count += 1

            if dry_run:
                # Rollback transaction in dry-run mode
                transaction.set_rollback(True)

        # Summary
        self.stdout.write(self.style.SUCCESS('\n' + '='*80))
        self.stdout.write(self.style.SUCCESS('SUMMARY'))
        self.stdout.write(self.style.SUCCESS('='*80))
        self.stdout.write(self.style.ERROR(f'Incorrect assignments: {fixed_count}'))
        self.stdout.write(self.style.SUCCESS(f'Correct assignments: {unchanged_count}'))
        self.stdout.write(self.style.SUCCESS(f'Total devices: {devices.count()}'))
        self.stdout.write(self.style.SUCCESS('='*80))

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    '\n⚠ DRY RUN MODE - No changes were saved. Run without --dry-run to apply fixes.\n'
                )
            )
        elif fixed_count > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✓ Fixed {fixed_count} device-gateway assignment(s)!\n'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    '\n✓ All device-gateway assignments are correct!\n'
                )
            )

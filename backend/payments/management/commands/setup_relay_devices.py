"""
Management command to create "Relay" devices on each target branch.

For each shared gateway type (MPESA_TILL, MERCHANDISE), this command finds
an active PaymentGateway of that type and creates a Device named
"Relay - {gateway_type}" linked to it. These devices are used internally by
the relay endpoint to create RawMessage records.

Usage:
    python manage.py setup_relay_devices
"""

import uuid
from django.core.management.base import BaseCommand
from django.conf import settings
from payments.models import PaymentGateway, Device


class Command(BaseCommand):
    help = 'Creates Relay devices for shared gateway types on this branch'

    def add_arguments(self, parser):
        parser.add_argument(
            '--gateway-types',
            nargs='+',
            type=str,
            help='Override gateway types (default: from PAYMENT_RELAY_GATEWAY_TYPES)',
        )

    def handle(self, *args, **options):
        relay_types = options.get('gateway_types') or getattr(
            settings, 'PAYMENT_RELAY_GATEWAY_TYPES', ['MPESA_TILL', 'MERCHANDISE']
        )

        self.stdout.write(self.style.WARNING('\n' + '=' * 70))
        self.stdout.write(self.style.WARNING('Setting Up Relay Devices'))
        self.stdout.write(self.style.WARNING('=' * 70 + '\n'))

        created_count = 0
        found_count = 0
        skipped_count = 0

        for gateway_type_str in relay_types:
            gateway_type_str = gateway_type_str.strip()
            self.stdout.write(f"Processing gateway type: {gateway_type_str}\n")

            # Validate that the gateway type exists
            valid_types = [t.value for t in PaymentGateway.GatewayType]
            if gateway_type_str not in valid_types:
                self.stdout.write(
                    self.style.ERROR(
                        f"  ✗ Invalid gateway type '{gateway_type_str}'. "
                        f"Valid types: {', '.join(valid_types)}\n"
                    )
                )
                skipped_count += 1
                continue

            try:
                gateway = PaymentGateway.objects.get(
                    gateway_type=gateway_type_str,
                    is_active=True,
                )
            except PaymentGateway.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(
                        f"  ⚠ No active {gateway_type_str} gateway found. "
                        f"Create one first with create_default_gateways.\n"
                    )
                )
                skipped_count += 1
                continue

            device_name = f"Relay - {gateway_type_str}"
            device, created = Device.objects.get_or_create(
                name=device_name,
                defaults={
                    'gateway': gateway,
                    'api_key': f'relay-internal-{uuid.uuid4()}',
                },
            )

            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  ✓ Created relay device '{device_name}' "
                        f"for gateway '{gateway.name}' ({gateway.gateway_number})\n"
                    )
                )
            else:
                # Update gateway in case it changed
                old_gateway = device.gateway
                if device.gateway_id != gateway.id:
                    device.gateway = gateway
                    device.save(update_fields=['gateway'])
                    self.stdout.write(
                        self.style.WARNING(
                            f"  ~ Updated device '{device_name}' gateway "
                            f"from '{old_gateway}' to '{gateway}'\n"
                        )
                    )
                else:
                    self.stdout.write(
                        f"  ✓ Device '{device_name}' already exists "
                        f"for gateway '{gateway.name}' ({gateway.gateway_number})\n"
                    )
                found_count += 1

        self.stdout.write(self.style.WARNING('\n' + '-' * 70))
        self.stdout.write(self.style.WARNING('Summary:'))
        self.stdout.write(f"  Created: {created_count}")
        self.stdout.write(f"  Found existing: {found_count}")
        self.stdout.write(f"  Skipped: {skipped_count}")
        self.stdout.write('-' * 70 + '\n')

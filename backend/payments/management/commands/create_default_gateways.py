"""
Management command to create default payment gateways.

This command creates standard payment gateways if they don't already exist.
It's safe to run multiple times (idempotent).

Usage:
    python manage.py create_default_gateways
"""

from django.core.management.base import BaseCommand
from payments.models import PaymentGateway


class Command(BaseCommand):
    help = 'Creates default payment gateways (Paybill, Tills, PDQ, Bank, Cash, Cheque)'

    def handle(self, *args, **options):
        """Create default gateways if they don't exist."""

        default_gateways = [
            {
                'name': 'Paybill Parent Company',
                'gateway_type': PaymentGateway.GatewayType.MPESA_PAYBILL,
                'gateway_number': 'PAYBILL_NUMBER',
                'settlement_type': PaymentGateway.SettlementType.PARENT_TAKES_ALL,
                'requires_parent_settlement': True,
                'description': 'M-Pesa Paybill - All payments go to parent company'
            },
            {
                'name': 'Till Products',
                'gateway_type': PaymentGateway.GatewayType.MPESA_TILL,
                'gateway_number': 'TILL_PRODUCTS',
                'settlement_type': PaymentGateway.SettlementType.NONE,
                'requires_parent_settlement': False,
                'description': 'M-Pesa Till for product sales'
            },
            {
                'name': 'Till Merchandise',
                'gateway_type': PaymentGateway.GatewayType.MPESA_TILL,
                'gateway_number': 'TILL_MERCHANDISE',
                'settlement_type': PaymentGateway.SettlementType.NONE,
                'requires_parent_settlement': False,
                'description': 'M-Pesa Till for merchandise sales'
            },
            {
                'name': 'PDQ/Card Payment',
                'gateway_type': PaymentGateway.GatewayType.PDQ,
                'gateway_number': 'PDQ_TERMINAL',
                'settlement_type': PaymentGateway.SettlementType.NONE,
                'requires_parent_settlement': False,
                'description': 'Card payment terminal (PDQ machine)'
            },
            {
                'name': 'Bank Transfer',
                'gateway_type': PaymentGateway.GatewayType.BANK_TRANSFER,
                'gateway_number': 'BANK_ACCOUNT',
                'settlement_type': PaymentGateway.SettlementType.NONE,
                'requires_parent_settlement': False,
                'description': 'Direct bank transfer payments'
            },
            {
                'name': 'Cash Payment',
                'gateway_type': PaymentGateway.GatewayType.CASH,
                'gateway_number': 'CASH_COUNTER',
                'settlement_type': PaymentGateway.SettlementType.NONE,
                'requires_parent_settlement': False,
                'description': 'Cash payments at counter'
            },
            {
                'name': 'Cheque Payment',
                'gateway_type': PaymentGateway.GatewayType.OTHER,
                'gateway_number': 'CHEQUE_COUNTER',
                'settlement_type': PaymentGateway.SettlementType.NONE,
                'requires_parent_settlement': False,
                'description': 'Cheque payments'
            },
        ]

        created_count = 0
        existing_count = 0

        self.stdout.write(self.style.WARNING('\n' + '='*80))
        self.stdout.write(self.style.WARNING('Creating Default Payment Gateways'))
        self.stdout.write(self.style.WARNING('='*80 + '\n'))

        for gateway_data in default_gateways:
            gateway, created = PaymentGateway.objects.get_or_create(
                name=gateway_data['name'],
                defaults=gateway_data
            )

            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✓ Created: {gateway.name} ({gateway.gateway_type})'
                    )
                )
            else:
                existing_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f'○ Already exists: {gateway.name} ({gateway.gateway_type})'
                    )
                )

        self.stdout.write(self.style.WARNING('\n' + '='*80))
        self.stdout.write(
            self.style.SUCCESS(
                f'\n✓ Created {created_count} new gateway(s)'
            )
        )
        self.stdout.write(
            self.style.WARNING(
                f'○ Found {existing_count} existing gateway(s)'
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f'\nTotal gateways in database: {PaymentGateway.objects.count()}'
            )
        )
        self.stdout.write(self.style.WARNING('='*80 + '\n'))

        # Display reminder to update gateway numbers
        if created_count > 0:
            self.stdout.write(
                self.style.WARNING(
                    '\n⚠ REMINDER: Update placeholder gateway numbers with real values:'
                )
            )
            self.stdout.write(
                '  - Visit: /admin/payments/paymentgateway/'
            )
            self.stdout.write(
                '  - Or use API: PATCH /api/v1/gateways/<id>/'
            )
            self.stdout.write(
                self.style.WARNING(
                    f"  - Replace 'PAYBILL_NUMBER', 'TILL_PRODUCTS', etc. with actual numbers\n"
                )
            )

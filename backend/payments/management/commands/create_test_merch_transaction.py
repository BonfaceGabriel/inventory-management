"""
Create a test merchandise transaction to verify the MERCH gateway type display.

Usage:
    python manage.py create_test_merch_transaction
    python manage.py create_test_merch_transaction --amount 5000
    python manage.py create_test_merch_transaction --status pending
"""

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from payments.models import PaymentGateway, Transaction
from payments.services.merchandise_service import MerchandiseService


class Command(BaseCommand):
    help = "Create a test merchandise transaction"

    def add_arguments(self, parser):
        parser.add_argument(
            "--amount",
            type=int,
            default=3500,
            help="Transaction amount (default: 3500)",
        )
        parser.add_argument(
            "--status",
            type=str,
            default="NOT_PROCESSED",
            choices=["NOT_PROCESSED", "PROCESSING", "FULFILLED"],
            help="Transaction status (default: NOT_PROCESSED)",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing test merchandise transactions first",
        )

    def handle(self, *args, **options):
        amount = options["amount"]
        status_str = options["status"]
        clear = options["clear"]

        # Clear existing test transactions if requested
        if clear:
            from payments.models import MerchandiseOrder

            # First delete merchandise orders that reference the transactions
            merch_orders = MerchandiseOrder.objects.filter(
                transaction__tx_id__startswith="TEST-MERCH-"
            )
            order_count = merch_orders.count()
            merch_orders.delete()
            # Then delete the transactions
            transactions = Transaction.objects.filter(tx_id__startswith="TEST-MERCH-")
            tx_count = transactions.count()
            transactions.delete()
            self.stdout.write(
                self.style.WARNING(
                    f"Cleared {order_count} merchandise orders and {tx_count} transactions"
                )
            )

        # Find the merchandise gateway
        merch_gateway = None
        for gw in PaymentGateway.objects.filter(is_active=True):
            if MerchandiseService.is_merchandise_gateway(gw):
                merch_gateway = gw
                break

        if not merch_gateway:
            self.stdout.write(
                self.style.ERROR(
                    'No merchandise gateway found. Please create a gateway named "Till Merchandise" or similar.'
                )
            )
            return

        self.stdout.write(
            f"Found merchandise gateway: {merch_gateway.name} (ID: {merch_gateway.id})"
        )
        self.stdout.write(f"  Gateway type: {merch_gateway.gateway_type}")

        # Generate unique transaction ID
        import hashlib
        import uuid

        tx_id = f"TEST-MERCH-{uuid.uuid4().hex[:8].upper()}"
        unique_hash = hashlib.sha256(tx_id.encode()).hexdigest()[:64]

        # Create the transaction
        now = timezone.now()
        tx = Transaction(
            tx_id=tx_id,
            amount=Decimal(str(amount)),
            sender_name="Test Merchandise Customer",
            sender_phone="0712345678",
            timestamp=now,
            gateway=merch_gateway,
            gateway_type=merch_gateway.gateway_type,  # This stores the actual type
            destination_number=merch_gateway.gateway_number,
            status=getattr(Transaction.OrderStatus, status_str),
            confidence=0.99,
            unique_hash=unique_hash,
            notes="Test transaction for merchandise gateway type display",
        )
        tx.save(skip_validation=True)

        # Create the merchandise order
        from payments.models import MerchandiseOrder

        order = MerchandiseOrder.objects.create(
            transaction=tx,
            gateway=merch_gateway,
            status=MerchandiseOrder.Status.PENDING,
        )

        self.stdout.write(
            self.style.SUCCESS("\n✓ Test merchandise transaction created:")
        )
        self.stdout.write(f"  Transaction ID: {tx.tx_id}")
        self.stdout.write(f"  Amount: {tx.amount}")
        self.stdout.write(f"  Status: {tx.status}")
        self.stdout.write(f"  Gateway Name: {tx.gateway.name}")
        self.stdout.write(f"  Gateway Type (raw): {tx.gateway.gateway_type}")
        self.stdout.write(f"  Merchandise Order ID: {order.id}")
        self.stdout.write("")
        self.stdout.write(
            '  The API will return "MERCH" for gateway_type when this transaction is serialized.'
        )
        self.stdout.write("  Check the transaction list to verify the display.")

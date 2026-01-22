#!/usr/bin/env python
"""
Django management command to cancel issuance for a combined order.

Usage:
    python manage.py cancel_combined_issuance CMB-20260122-100126 --cancelled-by "admin" --reason "Mistake during scanning"
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'management.settings')
django.setup()

from payments.services.combined_order_service import CombinedOrderService
from django.core.exceptions import ValidationError

def main():
    order_id = 'CMB-20260122-100126'
    cancelled_by = 'admin'
    reason = 'Cancel issuance via script'

    print(f"Attempting to cancel issuance for combined order: {order_id}")
    print(f"Cancelled by: {cancelled_by}")
    print(f"Reason: {reason}")
    print("-" * 60)

    try:
        result = CombinedOrderService.cancel_combined_order_issuance(
            combined_order_id=order_id,
            cancelled_by=cancelled_by,
            reason=reason
        )

        print("✅ SUCCESS")
        print("-" * 60)
        print(f"Combined Order ID: {result['combined_order_id']}")
        print(f"Pending items removed: {result['pending_items_removed']}")
        print(f"New status: {result['status']}")
        print(f"Amount fulfilled: KES {result['amount_fulfilled']:.2f}")
        print(f"Previous status: {result['previous_status']}")
        print(f"Message: {result['message']}")

    except ValidationError as e:
        print("❌ VALIDATION ERROR")
        print("-" * 60)
        print(f"Error: {e}")
        sys.exit(1)

    except Exception as e:
        print("❌ ERROR")
        print("-" * 60)
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()

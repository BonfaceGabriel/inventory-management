#!/usr/bin/env python
"""
Django management command to cancel issuance for a combined order.

Usage:
    python manage.py cancel_combined_issuance CMB-20260122-100126 --cancelled-by "admin" --reason "Mistake during scanning"
"""

import os
import sys
import django
import logging

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'management.settings')
django.setup()

from payments.services.combined_order_service import CombinedOrderService
from django.core.exceptions import ValidationError

def main():
    order_id = 'CMB-20260122-101120'  # Updated to the failing order ID from logs
    cancelled_by = 'admin'
    reason = 'Cancel issuance via script'

    logger.info("=" * 80)
    logger.info(f"Starting cancellation script for combined order: {order_id}")
    logger.info(f"Cancelled by: {cancelled_by}")
    logger.info(f"Reason: {reason}")
    logger.info("=" * 80)

    try:
        logger.info("Calling CombinedOrderService.cancel_combined_order_issuance...")
        result = CombinedOrderService.cancel_combined_order_issuance(
            combined_order_id=order_id,
            cancelled_by=cancelled_by,
            reason=reason
        )

        logger.info("=" * 80)
        logger.info("✅ CANCELLATION SUCCESSFUL")
        logger.info("=" * 80)
        logger.info(f"Combined Order ID: {result['combined_order_id']}")
        logger.info(f"Pending items removed: {result['pending_items_removed']}")
        logger.info(f"New status: {result['status']}")
        logger.info(f"Amount fulfilled: KES {result['amount_fulfilled']:.2f}")
        logger.info(f"Previous status: {result['previous_status']}")
        logger.info(f"Message: {result['message']}")
        logger.info("=" * 80)

        # Also print to console
        print("\n" + "=" * 60)
        print("✅ SUCCESS")
        print("=" * 60)
        print(f"Combined Order ID: {result['combined_order_id']}")
        print(f"Pending items removed: {result['pending_items_removed']}")
        print(f"New status: {result['status']}")
        print(f"Amount fulfilled: KES {result['amount_fulfilled']:.2f}")
        print(f"Previous status: {result['previous_status']}")
        print(f"Message: {result['message']}")
        print("=" * 60)

    except ValidationError as e:
        logger.error("=" * 80)
        logger.error("❌ VALIDATION ERROR")
        logger.error("=" * 80)
        logger.error(f"ValidationError: {e}")
        if hasattr(e, 'message_dict'):
            logger.error(f"Message dict: {e.message_dict}")
        logger.error("=" * 80)

        print("\n" + "=" * 60)
        print("❌ VALIDATION ERROR")
        print("=" * 60)
        print(f"Error: {e}")
        print("=" * 60)
        sys.exit(1)

    except Exception as e:
        logger.error("=" * 80)
        logger.error("❌ UNEXPECTED ERROR")
        logger.error("=" * 80)
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.error("=" * 80)
        import traceback
        logger.error("Full traceback:")
        logger.error(traceback.format_exc())
        logger.error("=" * 80)

        print("\n" + "=" * 60)
        print("❌ ERROR")
        print("=" * 60)
        print(f"Error: {str(e)}")
        print("\nCheck the logs above for detailed error information")
        print("=" * 60)
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()

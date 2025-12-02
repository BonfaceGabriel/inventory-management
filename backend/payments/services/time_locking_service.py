"""
Time-Locking Service

Handles end-of-day locking of partially fulfilled transactions.
Triggered by report generation to freeze accounting state.
"""

from decimal import Decimal
from django.db import transaction as db_transaction
from django.utils import timezone
from django.db.models import Q
from typing import List, Dict
import logging

from payments.models import Transaction

logger = logging.getLogger(__name__)


class TimeLockingService:
    """Service for time-based transaction locking."""

    @staticmethod
    def lock_partially_fulfilled_transactions(
        target_date=None,
        locked_by: str = "System: End-of-Day Report"
    ) -> Dict:
        """
        Lock all PARTIALLY_FULFILLED transactions for a specific date.

        Called when end-of-day report is generated to freeze the accounting state.
        Locked transactions preserve their PARTIALLY_FULFILLED status but become read-only.

        Once locked, transactions cannot be unlocked (permanent lock per business rules).

        Args:
            target_date: Date to lock transactions for (defaults to today)
            locked_by: Identifier of who/what initiated the lock

        Returns:
            Dict with lock statistics and transaction IDs
        """
        if target_date is None:
            target_date = timezone.now().date()

        # Define date range for the target date
        start_datetime = timezone.make_aware(
            timezone.datetime.combine(target_date, timezone.datetime.min.time())
        )
        end_datetime = timezone.make_aware(
            timezone.datetime.combine(target_date, timezone.datetime.max.time())
        )

        with db_transaction.atomic():
            # Find all partially fulfilled transactions for the date
            # that are NOT already time-locked or status-locked
            partially_fulfilled = Transaction.objects.filter(
                timestamp__gte=start_datetime,
                timestamp__lte=end_datetime,
                status=Transaction.OrderStatus.PARTIALLY_FULFILLED,
                is_time_locked=False
            ).select_for_update()

            locked_count = 0
            locked_tx_ids = []
            locked_amounts = Decimal('0.00')

            lock_timestamp = timezone.now()

            for txn in partially_fulfilled:
                # Add locking note to transaction
                lock_note = (
                    f"[{lock_timestamp.strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"Time-locked at end-of-day by {locked_by}. "
                    f"This transaction is now permanently locked and cannot be modified."
                )

                txn.is_time_locked = True
                txn.locked_at = lock_timestamp
                txn.locked_by = locked_by
                txn.notes = (
                    f"{txn.notes}\n{lock_note}" if txn.notes else lock_note
                )
                txn.save()

                locked_count += 1
                locked_tx_ids.append(txn.tx_id)
                locked_amounts += txn.remaining_amount

            logger.info(
                f"Time-locked {locked_count} partially fulfilled transactions "
                f"for date {target_date}. Total remaining amount: {locked_amounts}"
            )

            return {
                'success': True,
                'locked_count': locked_count,
                'locked_tx_ids': locked_tx_ids,
                'total_remaining_amount': float(locked_amounts),
                'target_date': target_date.isoformat(),
                'locked_at': lock_timestamp.isoformat(),
                'locked_by': locked_by,
            }

    @staticmethod
    def get_lockable_transactions(target_date=None) -> List[Transaction]:
        """
        Get transactions eligible for time-locking on target date.

        Returns PARTIALLY_FULFILLED transactions that are not yet locked.

        Args:
            target_date: Date to check (defaults to today)

        Returns:
            QuerySet of Transaction instances eligible for locking
        """
        if target_date is None:
            target_date = timezone.now().date()

        start_datetime = timezone.make_aware(
            timezone.datetime.combine(target_date, timezone.datetime.min.time())
        )
        end_datetime = timezone.make_aware(
            timezone.datetime.combine(target_date, timezone.datetime.max.time())
        )

        return Transaction.objects.filter(
            timestamp__gte=start_datetime,
            timestamp__lte=end_datetime,
            status=Transaction.OrderStatus.PARTIALLY_FULFILLED,
            is_time_locked=False
        ).order_by('timestamp')

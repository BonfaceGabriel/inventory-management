#!/usr/bin/env python
"""
Script to revert stock-taking sessions from today and undo their inventory changes.

Usage:
    # Dry run (preview what would be reverted)
    docker exec inventory-management-web-1 python revert_stock_takes.py --dry-run

    # Actually revert today's sessions
    docker exec inventory-management-web-1 python revert_stock_takes.py

    # Revert specific date
    docker exec inventory-management-web-1 python revert_stock_takes.py --date 2026-01-22

    # Revert specific session
    docker exec inventory-management-web-1 python revert_stock_takes.py --session STK-20260123-154937

Safety Features:
- Dry-run mode by default shows what would be reverted
- Requires explicit confirmation before making changes
- Creates backup of data before reverting
- Logs all actions taken
- Only reverts COMPLETED sessions (not DRAFT or CANCELLED)
"""

import os
import sys
import django
from datetime import datetime, timedelta
from decimal import Decimal
import json

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'management.settings')
django.setup()

from django.db import transaction
from django.utils import timezone
from payments.models import (
    StockTakeSession,
    StockTakeItem,
    InventoryMovement,
    Product
)


class StockTakeReverter:
    """Handles reverting stock-taking sessions and inventory changes."""

    def __init__(self, dry_run=True, date=None, session_id=None):
        self.dry_run = dry_run
        self.target_date = date or timezone.now().date()
        self.session_id = session_id
        self.reverted_sessions = []
        self.reverted_movements = []
        self.product_changes = {}

    def get_sessions_to_revert(self):
        """Get stock-taking sessions to revert."""
        if self.session_id:
            # Revert specific session
            sessions = StockTakeSession.objects.filter(
                session_id=self.session_id,
                status=StockTakeSession.Status.COMPLETED
            )
        else:
            # Revert all completed sessions from target date
            start_of_day = timezone.make_aware(
                datetime.combine(self.target_date, datetime.min.time())
            )
            end_of_day = timezone.make_aware(
                datetime.combine(self.target_date, datetime.max.time())
            )

            sessions = StockTakeSession.objects.filter(
                status=StockTakeSession.Status.COMPLETED,
                completed_at__gte=start_of_day,
                completed_at__lte=end_of_day
            ).order_by('completed_at')

        return sessions

    def preview_revert(self, sessions):
        """Preview what would be reverted."""
        print("\n" + "=" * 80)
        print("STOCK-TAKING REVERT PREVIEW")
        print("=" * 80)
        print(f"Target Date: {self.target_date}")
        print(f"Sessions to Revert: {sessions.count()}")
        print()

        if sessions.count() == 0:
            print("❌ No completed stock-taking sessions found for the specified criteria.")
            return False

        total_items = 0
        total_quantity_change = 0

        for session in sessions:
            items = session.items.all()
            session_quantity = sum(item.quantity_scanned for item in items)
            total_items += items.count()
            total_quantity_change += session_quantity

            print(f"\n📦 Session: {session.session_id}")
            print(f"   Status: {session.status}")
            print(f"   Completed: {session.completed_at}")
            print(f"   Completed By: {session.completed_by or session.created_by}")
            print(f"   Items: {items.count()}")
            print(f"   Total Quantity Added: {session_quantity}")

            print(f"\n   Items in this session:")
            for item in items:
                print(f"   - {item.product.prod_name} ({item.product.prod_code})")
                print(f"     Before: {item.quantity_before} → After: {item.quantity_after}")
                print(f"     Scanned: +{item.quantity_scanned}")

        print("\n" + "-" * 80)
        print(f"📊 SUMMARY:")
        print(f"   Total Sessions: {sessions.count()}")
        print(f"   Total Items: {total_items}")
        print(f"   Total Quantity to Revert: -{total_quantity_change}")
        print("-" * 80)

        return True

    def revert_sessions(self, sessions):
        """Actually revert the sessions and inventory changes."""
        if self.dry_run:
            print("\n⚠️  DRY RUN MODE - No changes will be made")
            return self.preview_revert(sessions)

        print("\n" + "=" * 80)
        print("⚠️  WARNING: ABOUT TO REVERT STOCK-TAKING SESSIONS")
        print("=" * 80)
        self.preview_revert(sessions)

        # Confirmation prompt
        print("\n" + "!" * 80)
        print("This will:")
        print("1. Revert all inventory changes made by these sessions")
        print("2. Update product stock quantities")
        print("3. Cancel the stock-taking sessions")
        print("4. Create reversal inventory movement records")
        print("!" * 80)

        confirmation = input("\nType 'REVERT' to confirm (or anything else to cancel): ")
        if confirmation != 'REVERT':
            print("\n❌ Revert cancelled by user")
            return False

        print("\n🔄 Starting revert process...")

        try:
            with transaction.atomic():
                for session in sessions:
                    self._revert_session(session)

                print("\n✅ All sessions reverted successfully!")
                print(f"\n📋 Reverted {len(self.reverted_sessions)} session(s)")
                print(f"📋 Created {len(self.reverted_movements)} reversal movement(s)")
                print(f"📋 Updated {len(self.product_changes)} product(s)")

                return True

        except Exception as e:
            print(f"\n❌ Error during revert: {e}")
            print("⚠️  Transaction rolled back - no changes made")
            raise

    def _revert_session(self, session):
        """Revert a single session."""
        print(f"\n🔄 Reverting session: {session.session_id}")

        # Get all items in this session
        items = session.items.all().select_related('product')

        for item in items:
            self._revert_item(session, item)

        # Mark session as cancelled
        session.status = StockTakeSession.Status.CANCELLED
        session.notes = f"[REVERTED] {session.notes or ''} - Reverted due to bugs"
        session.save()

        self.reverted_sessions.append(session.session_id)
        print(f"   ✓ Session {session.session_id} marked as CANCELLED")

    def _revert_item(self, session, item):
        """Revert inventory changes for a single item."""
        product = item.product

        # Calculate the reversal
        quantity_to_subtract = item.quantity_scanned
        current_quantity = product.quantity_in_stock
        new_quantity = current_quantity - quantity_to_subtract

        if new_quantity < 0:
            print(f"   ⚠️  WARNING: Product {product.prod_code} would go negative!")
            print(f"      Current: {current_quantity}, Reverting: -{quantity_to_subtract}")
            print(f"      Setting to 0 instead of {new_quantity}")
            new_quantity = 0

        # Update product stock
        product.quantity_in_stock = new_quantity
        product.save()

        # Track changes
        if product.prod_code not in self.product_changes:
            self.product_changes[product.prod_code] = {
                'name': product.prod_name,
                'old_quantity': current_quantity,
                'new_quantity': new_quantity,
                'change': -quantity_to_subtract
            }

        # Create reversal inventory movement
        movement = InventoryMovement.objects.create(
            movement_type=InventoryMovement.MovementType.ADJUSTMENT,
            product=product,
            quantity_before=current_quantity,
            quantity_after=new_quantity,
            quantity_change=-quantity_to_subtract,
            reference=f"REVERT: {session.session_id}",
            performed_by=f"System (Reverting {session.completed_by or session.created_by})",
            notes=f"Reverted stock-take session {session.session_id} due to bugs"
        )

        self.reverted_movements.append(movement.id)
        print(f"   ✓ {product.prod_code}: {current_quantity} → {new_quantity} (-{quantity_to_subtract})")

    def save_backup(self, sessions):
        """Save backup of sessions before reverting."""
        backup_data = {
            'timestamp': timezone.now().isoformat(),
            'target_date': self.target_date.isoformat(),
            'sessions': []
        }

        for session in sessions:
            session_data = {
                'session_id': session.session_id,
                'status': session.status,
                'created_by': session.created_by,
                'completed_by': session.completed_by,
                'completed_at': session.completed_at.isoformat() if session.completed_at else None,
                'notes': session.notes,
                'items': []
            }

            for item in session.items.all():
                item_data = {
                    'product_code': item.product.prod_code,
                    'product_name': item.product.prod_name,
                    'quantity_before': item.quantity_before,
                    'quantity_scanned': item.quantity_scanned,
                    'quantity_after': item.quantity_after,
                    'scanned_at': item.scanned_at.isoformat(),
                    'scanned_by': item.scanned_by
                }
                session_data['items'].append(item_data)

            backup_data['sessions'].append(session_data)

        # Save to file
        backup_filename = f"stock_take_backup_{timezone.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(backup_filename, 'w') as f:
            json.dump(backup_data, f, indent=2)

        print(f"\n💾 Backup saved to: {backup_filename}")
        return backup_filename


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Revert stock-taking sessions and inventory changes',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=True,
        help='Preview changes without actually reverting (default: True)'
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually execute the revert (required to make changes)'
    )
    parser.add_argument(
        '--date',
        type=str,
        help='Date to revert sessions from (YYYY-MM-DD, default: today)'
    )
    parser.add_argument(
        '--session',
        type=str,
        help='Specific session ID to revert (e.g., STK-20260123-154937)'
    )

    args = parser.parse_args()

    # Parse date if provided
    target_date = None
    if args.date:
        try:
            target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        except ValueError:
            print(f"❌ Invalid date format: {args.date}")
            print("   Use YYYY-MM-DD format (e.g., 2026-01-23)")
            sys.exit(1)

    # Determine if this is a dry run
    dry_run = not args.execute

    # Create reverter
    reverter = StockTakeReverter(
        dry_run=dry_run,
        date=target_date,
        session_id=args.session
    )

    # Get sessions to revert
    sessions = reverter.get_sessions_to_revert()

    if sessions.count() == 0:
        print(f"\n❌ No completed stock-taking sessions found")
        if args.session:
            print(f"   Session: {args.session}")
        else:
            print(f"   Date: {reverter.target_date}")
        sys.exit(0)

    # Save backup before reverting (even in dry-run)
    if not dry_run:
        reverter.save_backup(sessions)

    # Revert sessions
    success = reverter.revert_sessions(sessions)

    if not success:
        sys.exit(1)

    if dry_run:
        print("\n" + "=" * 80)
        print("ℹ️  This was a DRY RUN - no changes were made")
        print("   To actually revert, run with --execute flag:")
        print(f"   docker exec inventory-management-web-1 python revert_stock_takes.py --execute")
        print("=" * 80)


if __name__ == '__main__':
    main()

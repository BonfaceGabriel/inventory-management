"""
Django management command to clear all active stock take sessions.
This is intended to run on deployment to clean up any orphaned sessions.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from payments.models import StockTakeSession


class Command(BaseCommand):
    help = 'Clear all active (DRAFT) stock take sessions - useful for deployment cleanup'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be cancelled without actually doing it',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Find all DRAFT stock take sessions
        active_sessions = StockTakeSession.objects.filter(
            status=StockTakeSession.Status.DRAFT
        )
        
        count = active_sessions.count()
        
        if count == 0:
            self.stdout.write(
                self.style.SUCCESS('No active stock take sessions found.')
            )
            return
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'DRY RUN: Would cancel {count} active session(s):')
            )
            for session in active_sessions:
                self.stdout.write(f'  - {session.session_id} (created by {session.created_by} at {session.created_at})')
        else:
            # Cancel all active sessions
            for session in active_sessions:
                session.status = StockTakeSession.Status.CANCELLED
                session.completed_at = timezone.now()
                session.completed_by = 'system_deployment'
                session.save()
                
                self.stdout.write(
                    self.style.SUCCESS(f'Cancelled session: {session.session_id}')
                )
            
            self.stdout.write(
                self.style.SUCCESS(f'\nSuccessfully cancelled {count} active stock take session(s).')
            )

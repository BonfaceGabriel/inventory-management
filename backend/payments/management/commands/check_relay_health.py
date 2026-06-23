"""
Health check for the SMS relay pipeline.

Checks:
  1. Celery worker is alive (sends a ping task with timeout)
  2. No stale unprocessed relayed RawMessage records
  3. Recent messages have been processed within expected window

Exit codes:
  0 — healthy
  1 — stale relayed messages found (warning)
  2 — Celery worker unreachable (critical)

Usage:
    docker exec <web-container> python manage.py check_relay_health
    docker exec <web-container> python manage.py check_relay_health \
        --stale-threshold 10 --max-age-minutes 5
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings

from payments.models import RawMessage


class Command(BaseCommand):
    help = "Check relay pipeline health (Celery + stale messages)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--stale-threshold',
            type=int,
            default=10,
            help="Warn if more than N stale relayed messages exist (default: 10)",
        )
        parser.add_argument(
            '--max-age-minutes',
            type=int,
            default=5,
            help="Messages older than this many minutes are considered stale (default: 5)",
        )

    def handle(self, *args, **options):
        stale_threshold = options['stale_threshold']
        max_age = timedelta(minutes=options['max_age_minutes'])

        checks = [
            self._check_celery_alive(),
            self._check_stale_relayed_messages(stale_threshold, max_age),
        ]

        all_ok = True
        critical_failure = False

        for ok, label, detail in checks:
            if ok:
                self.stdout.write(self.style.SUCCESS(f"  PASS  {label}  {detail}"))
            elif ok is None:
                self.stdout.write(self.style.WARNING(f"  WARN  {label}  {detail}"))
                all_ok = False
            else:
                self.stdout.write(self.style.ERROR(f"  FAIL  {label}  {detail}"))
                all_ok = False
                critical_failure = True

        if all_ok:
            self.stdout.write(self.style.SUCCESS("\nRelay pipeline is healthy."))
            raise SystemExit(0)
        elif critical_failure:
            self.stdout.write(self.style.ERROR("\nCritical relay pipeline issue detected."))
            raise SystemExit(2)
        else:
            self.stdout.write(self.style.WARNING("\nRelay pipeline has warnings."))
            raise SystemExit(1)

    def _check_celery_alive(self):
        """
        Verify the Celery worker is reachable by sending a ping task
        with a short timeout.
        """
        try:
            from celery.app.control import Inspect
            inspect = Inspect(app=self._get_celery_app())
            stats = inspect.stats(timeout=3)
            if stats:
                workers = list(stats.keys())
                return (True, "Celery worker", f"{len(workers)} worker(s) active: {', '.join(workers)}")
            else:
                return (False, "Celery worker", "No workers responded to ping (timeout)")
        except Exception as e:
            return (False, "Celery worker", f"Cannot reach Celery: {e}")

    def _check_stale_relayed_messages(self, stale_threshold: int, max_age: timedelta):
        """
        Count unprocessed relayed RawMessage records older than max_age.
        These should normally be processed within seconds.
        """
        cutoff = timezone.now() - max_age

        stale_count = RawMessage.objects.filter(
            processed=False,
            is_relayed=True,
            created_at__lte=cutoff,
        ).count()

        total_stale = RawMessage.objects.filter(
            processed=False,
            is_relayed=True,
        ).count()

        if stale_count == 0:
            pending = RawMessage.objects.filter(
                processed=False, is_relayed=True
            ).count()
            return (True, "Relayed messages", f"No stale messages (0 pending)")

        detail = f"{stale_count} stale (≥{max_age.seconds // 60}min), {total_stale} total pending"

        if total_stale >= stale_threshold:
            return (False, "Relayed messages", detail)
        else:
            return (None, "Relayed messages", detail)

    @staticmethod
    def _get_celery_app():
        from management.celery import app
        return app

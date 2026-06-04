"""
End-to-end diagnostic for SMS ingest → Celery → Transaction → WebSocket.

Runs every check in order and stops reporting the first hard failure,
while still collecting downstream hints.

Usage:
    docker exec <web-container> python manage.py diagnose_payment_pipeline
    docker exec <web-container> python manage.py diagnose_payment_pipeline --hours 48
    docker exec <web-container> python manage.py diagnose_payment_pipeline --verbose
    docker exec <web-container> python manage.py diagnose_payment_pipeline --reprocess 5
"""

from __future__ import annotations

import hashlib
import os
import socket
import ssl
import time
from collections import Counter
from datetime import timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from payments.models import Device, RawMessage, Transaction
from payments.parsers import parse_mpesa_sms
from payments.tasks import process_raw_message


def _mask_url(url: str) -> str:
    if not url:
        return "(not set)"
    parsed = urlparse(url)
    host = parsed.hostname or "?"
    port = f":{parsed.port}" if parsed.port else ""
    scheme = parsed.scheme or "?"
    user = parsed.username
    auth = f"{user}:***@" if user else ""
    path = parsed.path or ""
    return f"{scheme}://{auth}{host}{port}{path}"


def _status_line(ok: bool | None, label: str, detail: str = "") -> str:
    if ok is True:
        icon = "PASS"
    elif ok is False:
        icon = "FAIL"
    else:
        icon = "WARN"
    line = f"  [{icon}] {label}"
    if detail:
        line += f" — {detail}"
    return line


class Command(BaseCommand):
    help = "Diagnose where the payment ingest pipeline breaks (DB → Redis → Celery → parse → transaction)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=24,
            help="Look back this many hours for message/transaction stats (default: 24).",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print sample raw SMS snippets and per-device breakdown.",
        )
        parser.add_argument(
            "--reprocess",
            type=int,
            default=0,
            metavar="N",
            help="Synchronously reprocess up to N oldest unprocessed messages (live fix test).",
        )
        parser.add_argument(
            "--check-relay",
            action="store_true",
            help="Specifically debug the relay configuration and outgoing/incoming relay messages.",
        )

    def handle(self, *args, **options):
        hours = options["hours"]
        verbose = options["verbose"]
        reprocess_n = options["reprocess"]
        check_relay = options["check_relay"]
        since = timezone.now() - timedelta(hours=hours)

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("=" * 72))
        self.stdout.write(self.style.HTTP_INFO(" PAYMENT PIPELINE DIAGNOSTIC"))
        self.stdout.write(self.style.HTTP_INFO("=" * 72))
        self.stdout.write(f"  Time window : last {hours}h (since {timezone.localtime(since)})")
        self.stdout.write(f"  Hostname    : {socket.gethostname()}")
        self.stdout.write(f"  Django TZ   : {settings.TIME_ZONE}")
        self.stdout.write("")

        failures: list[str] = []
        warnings: list[str] = []

        # --- 1. Environment ---
        self.stdout.write(self.style.MIGRATE_HEADING("1. Environment"))
        broker = os.getenv("CELERY_BROKER_URL", getattr(settings, "CELERY_BROKER_URL", ""))
        backend = os.getenv("CELERY_RESULT_BACKEND", getattr(settings, "CELERY_RESULT_BACKEND", ""))
        redis_url = os.getenv("REDIS_URL", getattr(settings, "REDIS_URL", ""))
        eager = getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)
        
        self.stdout.write(_status_line(True, "CELERY_BROKER_URL", _mask_url(broker)))
        self.stdout.write(_status_line(True, "CELERY_RESULT_BACKEND", _mask_url(backend)))
        self.stdout.write(_status_line(True, "REDIS_URL (Channels)", _mask_url(redis_url)))
        
        # Check for shared broker issues
        if broker and "localhost" not in broker and "127.0.0.1" not in broker:
            self.stdout.write(self.style.WARNING("  [INFO] External broker detected. Ensure different DB indices for multi-instance setups."))
            if not any(broker.endswith(f"/{i}") for i in range(16)):
                 warnings.append("Broker URL doesn't specify a DB index (e.g., /0). Risk of task collision if multiple instances share Redis.")

        if broker != backend:
            warnings.append("CELERY_BROKER_URL and CELERY_RESULT_BACKEND differ")
            self.stdout.write(_status_line(None, "Broker vs result backend", "URLs differ (usually OK)"))
        if eager:
            failures.append("CELERY_TASK_ALWAYS_EAGER=True — tasks run in web process, not a worker")
            self.stdout.write(_status_line(False, "CELERY_TASK_ALWAYS_EAGER", "enabled (unexpected in prod)"))
        else:
            self.stdout.write(_status_line(True, "CELERY_TASK_ALWAYS_EAGER", "disabled"))
        self.stdout.write("")

        # --- 1b. Relay Configuration ---
        self.stdout.write(self.style.MIGRATE_HEADING("1b. Relay Configuration"))
        relay_targets = getattr(settings, "PAYMENT_RELAY_TARGETS", [])
        relay_secret = getattr(settings, "PAYMENT_RELAY_SECRET", "")
        branch_name = getattr(settings, "BRANCH_NAME", "Main Shop")
        relay_types = getattr(settings, "PAYMENT_RELAY_GATEWAY_TYPES", [])
        
        self.stdout.write(f"  Branch Name        : {branch_name}")
        self.stdout.write(f"  Relay Secret Set   : {'Yes' if relay_secret else 'No'}")
        self.stdout.write(f"  Relay Targets      : {len(relay_targets)}")
        for target in relay_targets:
            self.stdout.write(f"    - {target.get('name', 'Unknown')}: {target.get('url', 'No URL')}")
        self.stdout.write(f"  Relay Types        : {', '.join(relay_types)}")

        if relay_targets and not relay_secret:
            failures.append("Relay targets configured but PAYMENT_RELAY_SECRET is missing")
        if not relay_targets and not check_relay:
            self.stdout.write(_status_line(None, "Relay", "No targets configured (this instance is a leaf/primary only)"))
        self.stdout.write("")

        # --- 2. Database ---
        self.stdout.write(self.style.MIGRATE_HEADING("2. Database"))
        db_ok = self._check_database()
        self.stdout.write(_status_line(db_ok, "PostgreSQL connection", connection.settings_dict.get("HOST", "?")))
        
        # Check for missing migrations
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            failures.append(f"Missing {len(plan)} database migrations!")
            self.stdout.write(_status_line(False, "Migrations", f"{len(plan)} pending"))
        else:
            self.stdout.write(_status_line(True, "Migrations", "Up to date"))

        if not db_ok:
            failures.append("Database unreachable")
            self._print_verdict(failures, warnings)
            return
        self.stdout.write("")

        # --- 3. Redis (broker + channels) ---
        self.stdout.write(self.style.MIGRATE_HEADING("3. Redis connectivity"))
        broker_ok, broker_detail, queue_depth = self._check_redis(broker, label="Celery broker")
        self.stdout.write(_status_line(broker_ok, "Celery broker ping", broker_detail))
        if not broker_ok:
            failures.append(f"Celery broker unreachable: {broker_detail}")

        channels_ok, channels_detail, _ = self._check_redis(redis_url, label="Channels")
        self.stdout.write(_status_line(channels_ok, "Channels Redis ping", channels_detail))
        if not channels_ok:
            warnings.append(f"Channels Redis issue: {channels_detail}")

        if broker_ok and queue_depth is not None:
            self.stdout.write(_status_line(
                queue_depth < 500,
                f"Celery queue depth (key 'celery')",
                f"{queue_depth} pending task(s)" + (" — backlog!" if queue_depth > 50 else ""),
            ))
            if queue_depth > 50:
                warnings.append(f"{queue_depth} tasks queued — worker may be down or slow")
        self.stdout.write("")

        # --- 4. Celery workers ---
        self.stdout.write(self.style.MIGRATE_HEADING("4. Celery workers"))
        worker_ok, worker_detail, worker_names = self._check_celery_workers()
        self.stdout.write(_status_line(worker_ok, "Worker ping", worker_detail))
        
        # ALWAYS run deep dive to check Redis state even if ping fails
        self._celery_deep_dive(worker_names if worker_ok else [])
        
        if not worker_ok:
            failures.append("No Celery worker responded — tasks may be stuck or worker is a 'Zombie'")
        
        registered_ok, reg_detail = self._check_registered_task()
        self.stdout.write(_status_line(registered_ok, "Task registration", reg_detail))
        if not registered_ok:
            warnings.append("process_raw_message not visible on workers — restart celery after deploy")
        self.stdout.write("")

    def _celery_deep_dive(self, worker_names):
        """Inspect the internals of the running workers."""
        from celery import current_app
        i = current_app.control.inspect(timeout=5.0) # Increased timeout
        
        self.stdout.write(self.style.HTTP_INFO("  Celery Health Deep Dive:"))
        
        # 1. Redis Client Health (Run this first!)
        try:
            import redis
            broker_url = getattr(settings, 'CELERY_BROKER_URL', '')
            r_client = redis.from_url(broker_url)
            info = r_client.info('clients')
            connected = info.get('connected_clients', '?')
            self.stdout.write(f"    • Redis Clients  : {connected} connected")
            
            # Key indicator: If we have many clients but no worker ping, we have zombies.
            if int(connected) > 10 and not worker_names:
                self.stdout.write(self.style.ERROR("      [CRITICAL] Many Redis clients but no workers responding. ZOMBIES detected!"))
            
            # Check for "Ghost" workers on the same DB
            keys = r_client.keys("celery-ev*")
            self.stdout.write(f"    • Event Keys     : {len(keys)}")
            if len(keys) > 20:
                 self.stdout.write(self.style.WARNING(f"      [WARN] Old worker traces found. Running cleanup script recommended."))
        except Exception as e:
            self.stdout.write(f"    • Redis Info Err : {e}")

        if not worker_names:
            self.stdout.write(self.style.WARNING("    • No active workers to inspect further."))
            return

        # 2. Stats (Uptime, Concurrency)
        stats = i.stats() or {}
        for name in worker_names:
            w_stats = stats.get(name, {})
            uptime = w_stats.get('uptime', 0)
            pool = w_stats.get('pool', {})
            concurrency = pool.get('max-concurrency', '?')
            self.stdout.write(f"    • {name}: Uptime={uptime}s, Concurrency={concurrency}")
            if uptime < 60:
                self.stdout.write(self.style.WARNING(f"      [WARN] Worker recently restarted. Check for crash loops!"))

        # 3. Active Tasks (Currently running)
        active = i.active() or {}
        active_count = sum(len(tasks) for tasks in active.values())
        self.stdout.write(f"    • Active tasks   : {active_count}")
        for w_name, tasks in active.items():
            for t in tasks:
                self.stdout.write(f"      - {t['name']}[{t['id']}] (running for {time.time() - t['time_start']:.1f}s)")

        # 4. Reserved/Scheduled (Queued but not started)
        reserved = i.reserved() or {}
        reserved_count = sum(len(tasks) for tasks in reserved.values())
        self.stdout.write(f"    • Reserved tasks : {reserved_count}")

        # --- 4b. Live enqueue test ---
        self.stdout.write(self.style.MIGRATE_HEADING("4b. Live Celery enqueue test"))
        self._test_enqueue(since)
        self.stdout.write("")

        # --- 5. Devices / gateways ---
        self.stdout.write(self.style.MIGRATE_HEADING("5. Registered devices"))
        device_issues = self._check_devices(verbose)
        if device_issues:
            for issue in device_issues:
                warnings.append(issue)
                self.stdout.write(_status_line(None, issue))
        else:
            self.stdout.write(_status_line(True, "All devices have gateways assigned"))
        self.stdout.write("")

        # --- 6. Pipeline stats ---
        self.stdout.write(self.style.MIGRATE_HEADING(f"6. Message vs transaction flow (last {hours}h)"))
        stats = self._pipeline_stats(since)
        self.stdout.write(f"  Raw messages received     : {stats['raw_total']}")
        self.stdout.write(f"    - Relayed (incoming)    : {stats['raw_relayed']}")
        self.stdout.write(f"    - Local (from devices)  : {stats['raw_local']}")
        self.stdout.write(f"  Marked processed          : {stats['raw_processed']}")
        self.stdout.write(f"  Still unprocessed         : {stats['raw_unprocessed']}")
        self.stdout.write(f"  Linked to transaction     : {stats['raw_with_txn']}")
        self.stdout.write(f"  Transactions created      : {stats['txn_created']}")
        self.stdout.write("")

        if check_relay:
            self.stdout.write(self.style.MIGRATE_HEADING("6b. Relay and Ingest Analysis"))
            if stats['raw_relayed'] == 0:
                warnings.append("No relayed messages received in window. Check if primary instance is sending.")
            else:
                self.stdout.write(f"  [INFO] Received {stats['raw_relayed']} relayed messages successfully.")
            
            # Check for active gateways for relay
            from payments.models import PaymentGateway
            for gtype in relay_types:
                active_gw = PaymentGateway.objects.filter(gateway_type=gtype, is_active=True).exists()
                self.stdout.write(_status_line(active_gw, f"Active {gtype} Gateway", "required for relay ingest" if not active_gw else "OK"))
                if not active_gw:
                    failures.append(f"No active gateway of type {gtype} — relay ingest will fail for this type")
            self.stdout.write("")

        if stats["raw_total"] > 0 and stats["raw_unprocessed"] == stats["raw_total"]:
            failures.append(
                "Every recent message is unprocessed — Celery worker not consuming tasks"
            )
        elif stats["raw_unprocessed"] > 10 and queue_depth == 0:
            failures.append(
                f"{stats['raw_unprocessed']} messages stuck unprocessed with empty queue — "
                "tasks are failing on the worker (check celery container logs) or never registered"
            )
        elif stats["raw_unprocessed"] > 10:
            warnings.append(f"{stats['raw_unprocessed']} unprocessed messages in window")

        if stats["raw_total"] > 5 and stats["txn_created"] == 0:
            failures.append("Messages arriving but zero transactions created in window")

        # --- 7. Classify unprocessed failures ---
        self.stdout.write(self.style.MIGRATE_HEADING("7. Why unprocessed messages fail"))
        breakdown = self._classify_unprocessed(since, verbose=verbose)
        if not breakdown["samples"]:
            self.stdout.write(_status_line(True, "No unprocessed messages in window"))
        else:
            for reason, count in breakdown["counts"].most_common():
                self.stdout.write(f"  • {count:4d}  {reason}")
            if verbose:
                self.stdout.write("")
                self.stdout.write("  Sample messages:")
                for sample in breakdown["samples"][:5]:
                    self.stdout.write(f"    id={sample['id']} device={sample['device']} reason={sample['reason']}")
                    snippet = sample["text"][:120].replace("\n", " ")
                    self.stdout.write(f"      \"{snippet}...\"")
        self.stdout.write("")

        # --- 8. Live reprocess test ---
        if reprocess_n > 0:
            self.stdout.write(self.style.MIGRATE_HEADING(f"8. Live reprocess (up to {reprocess_n})"))
            self._reprocess_batch(reprocess_n)
            self.stdout.write("")

        # --- Verdict ---
        self._print_verdict(failures, warnings, stats, worker_ok, broker_ok, queue_depth, check_relay)

    def _check_database(self) -> bool:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return True
        except Exception as exc:
            self.stdout.write(f"    Error: {exc}")
            return False

    def _check_redis(self, url: str, label: str) -> tuple[bool, str, int | None]:
        if not url:
            return False, f"{label} URL not configured", None
        try:
            import redis
        except ImportError:
            return False, "redis package not installed", None

        try:
            kwargs = {}
            if url.startswith("rediss://"):
                kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED
            client = redis.from_url(url, **kwargs)
            client.ping()
            depth = None
            if label == "Celery broker":
                try:
                    depth = client.llen("celery")
                except Exception:
                    depth = None
            return True, "PONG", depth
        except Exception as exc:
            return False, str(exc), None

    def _check_celery_workers(self) -> tuple[bool, str, list[str]]:
        try:
            from celery import current_app

            inspect = current_app.control.inspect(timeout=3.0)
            ping = inspect.ping()
            if not ping:
                return False, "no workers replied (inspect.ping() empty)", []
            names = sorted(ping.keys())
            return True, f"{len(names)} worker(s): {', '.join(names)}", names
        except Exception as exc:
            return False, str(exc), []

    def _check_registered_task(self) -> tuple[bool, str]:
        try:
            from celery import current_app

            inspect = current_app.control.inspect(timeout=3.0)
            registered = inspect.registered() or {}
            if not registered:
                return False, "no registered tasks returned (no workers?)"

            all_tasks: list[str] = []
            for tasks in registered.values():
                all_tasks.extend(tasks)

            matches = [t for t in all_tasks if "process_raw_message" in t]
            if matches:
                return True, f"found: {', '.join(matches)}"

            preview = ", ".join(sorted(all_tasks)[:8])
            if len(all_tasks) > 8:
                preview += f", … (+{len(all_tasks) - 8} more)"
            return False, f"not listed; worker has: {preview or '(empty)'}"
        except Exception as exc:
            return False, str(exc)

    def _test_enqueue(self, since) -> None:
        """Fire process_raw_message.delay() for one pending message and poll result."""
        sample = (
            RawMessage.objects.filter(processed=False, created_at__gte=since)
            .order_by("created_at")
            .first()
        )
        if not sample:
            self.stdout.write("  No unprocessed message available for enqueue test.")
            return

        self.stdout.write(f"  Testing Celery enqueue on RawMessage id={sample.id} ...")
        try:
            async_result = process_raw_message.delay(sample.id)
            self.stdout.write(f"    Task id: {async_result.id}")
            self.stdout.write(f"    Task name: {async_result.name}")

            # Poll up to ~6 seconds
            for _ in range(12):
                if async_result.ready():
                    break
                time.sleep(0.5)

            sample.refresh_from_db()
            if async_result.failed():
                self.stdout.write(self.style.ERROR(f"    [FAIL] Task failed: {async_result.result}"))
                tb = async_result.traceback
                if tb:
                    for line in str(tb).strip().splitlines()[-6:]:
                        self.stdout.write(f"      {line}")
            elif async_result.successful() and sample.processed:
                self.stdout.write(self.style.SUCCESS(
                    f"    [PASS] Task succeeded; processed=True txn_id={sample.transaction_id}"
                ))
            elif async_result.successful() and not sample.processed:
                self.stdout.write(self.style.WARNING(
                    "    [WARN] Task returned OK but message still unprocessed — check celery logs"
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f"    [WARN] Task still pending after 6s (worker not consuming '{async_result.name}'?)"
                ))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"    [FAIL] Could not enqueue: {exc}"))

    def _check_devices(self, verbose: bool) -> list[str]:
        issues = []
        devices = Device.objects.select_related("gateway").all()
        if not devices.exists():
            issues.append("No devices registered")
            return issues

        no_gateway = [d for d in devices if d.gateway_id is None]
        if no_gateway:
            issues.append(f"{len(no_gateway)} device(s) without gateway: {', '.join(d.name for d in no_gateway[:5])}")

        if verbose:
            self.stdout.write(f"  Devices ({devices.count()}):")
            for d in devices:
                gw = d.gateway.name if d.gateway_id else "MISSING"
                recent = d.messages.filter(
                    created_at__gte=timezone.now() - timedelta(hours=24)
                ).count()
                self.stdout.write(f"    • {d.name} → {gw}  ({recent} msgs / 24h)")
        return issues

    def _pipeline_stats(self, since) -> dict:
        raw_qs = RawMessage.objects.filter(created_at__gte=since)
        return {
            "raw_total": raw_qs.count(),
            "raw_relayed": raw_qs.filter(is_relayed=True).count(),
            "raw_local": raw_qs.filter(is_relayed=False).count(),
            "raw_processed": raw_qs.filter(processed=True).count(),
            "raw_unprocessed": raw_qs.filter(processed=False).count(),
            "raw_with_txn": raw_qs.exclude(transaction_id=None).count(),
            "txn_created": Transaction.objects.filter(created_at__gte=since).count(),
        }

    def _classify_unprocessed(self, since, verbose: bool) -> dict:
        qs = (
            RawMessage.objects.filter(processed=False, created_at__gte=since)
            .select_related("device", "device__gateway")
            .order_by("-created_at")[:200]
        )
        counts: Counter = Counter()
        samples = []

        for msg in qs:
            reason = self._failure_reason(msg)
            counts[reason] += 1
            if len(samples) < 10:
                samples.append({
                    "id": msg.id,
                    "device": msg.device.name if msg.device_id else "?",
                    "reason": reason,
                    "text": msg.raw_text,
                })

        return {"counts": counts, "samples": samples}

    def _failure_reason(self, msg: RawMessage) -> str:
        # Not yet processed by worker → queue/worker issue
        if not msg.processed:
            device = msg.device
            if device is None:
                return "NO_DEVICE (orphan message)"
            if device.gateway_id is None:
                return "NO_GATEWAY on device (worker would skip)"
            parsed = parse_mpesa_sms(msg.raw_text)
            confidence = parsed.get("confidence", 0) if parsed else 0
            if confidence <= 0.6:
                return f"PARSE_LOW_CONFIDENCE ({confidence:.2f})"
            # Would parse OK — if still unprocessed, worker never ran
            tx_id = parsed.get("tx_id")
            amount = parsed.get("amount")
            timestamp = parsed.get("timestamp")
            if tx_id and amount is not None and timestamp:
                hash_string = f"{tx_id}|{amount}|{timestamp}"
                unique_hash = hashlib.sha256(hash_string.encode()).hexdigest()
                if Transaction.objects.filter(unique_hash=unique_hash).exists():
                    return "DUPLICATE (transaction already exists)"
            sender_name = parsed.get("sender_name", "")
            sender_phone = parsed.get("sender_phone", "")
            if "7974481" in (sender_phone or "") or "7974481" in (sender_name or ""):
                return "INTERNAL_SENDER filtered (7974481)"
            return "READY — should process (worker/queue likely stuck)"

        return "UNKNOWN"

    def _reprocess_batch(self, n: int) -> None:
        pending = (
            RawMessage.objects.filter(processed=False)
            .order_by("created_at")[:n]
        )
        if not pending:
            self.stdout.write("  No unprocessed messages to reprocess.")
            return

        self.stdout.write(f"  Reprocessing {pending.count()} message(s) synchronously...")
        ok = 0
        for msg in pending:
            before_txn = msg.transaction_id
            try:
                process_raw_message(msg.id)
                msg.refresh_from_db()
                if msg.processed and (msg.transaction_id or before_txn):
                    ok += 1
                    self.stdout.write(_status_line(True, f"message {msg.id}", f"txn_id={msg.transaction_id}"))
                elif msg.processed:
                    self.stdout.write(_status_line(None, f"message {msg.id}", "processed but no transaction"))
                else:
                    self.stdout.write(_status_line(False, f"message {msg.id}", "still unprocessed"))
            except Exception as exc:
                self.stdout.write(_status_line(False, f"message {msg.id}", str(exc)))

        self.stdout.write(f"  Result: {ok}/{pending.count()} produced transactions")

    def _print_verdict(
        self,
        failures: list[str],
        warnings: list[str],
        stats: dict | None = None,
        worker_ok: bool | None = None,
        broker_ok: bool | None = None,
        queue_depth: int | None = None,
        check_relay: bool = False,
    ) -> None:
        self.stdout.write(self.style.HTTP_INFO("=" * 72))
        self.stdout.write(self.style.HTTP_INFO(" VERDICT"))
        self.stdout.write(self.style.HTTP_INFO("=" * 72))

        if failures:
            self.stdout.write(self.style.ERROR("  Pipeline BROKEN at:"))
            for i, f in enumerate(failures, 1):
                self.stdout.write(self.style.ERROR(f"    {i}. {f}"))
        else:
            self.stdout.write(self.style.SUCCESS("  No hard failures detected."))

        if warnings:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("  Warnings:"))
            for w in warnings:
                self.stdout.write(self.style.WARNING(f"    • {w}"))

        self.stdout.write("")
        self.stdout.write("  Likely break point (check in order):")
        steps = [
            ("Android → API", (stats["raw_local"] > 0) if stats else None),
            ("API saves RawMessage", (stats["raw_total"] > 0) if stats else None),
            ("Redis broker reachable", broker_ok),
            ("Celery worker running", worker_ok),
            ("Tasks consumed (queue depth)", queue_depth is not None and queue_depth < 50 if queue_depth is not None else worker_ok),
            ("Parse + create Transaction", (stats["txn_created"] > 0) if stats else None),
        ]
        
        if check_relay:
            steps.insert(0, ("Relay Ingest (Instance A → B)", (stats["raw_relayed"] > 0) if stats else None))

        for label, ok in steps:
            if ok is True:
                self.stdout.write(_status_line(True, label))
            elif ok is False:
                self.stdout.write(_status_line(False, label, "← investigate here"))
            else:
                self.stdout.write(_status_line(None, label, "unknown"))

        self.stdout.write("")
        self.stdout.write("  Recommended actions:")
        if failures and any("migrations" in f.lower() for f in failures):
             self.stdout.write("    → RUN MIGRATIONS: python manage.py migrate")
        
        if worker_ok is False:
            self.stdout.write("    → Start celery service: celery -A management worker -l info")
            self.stdout.write("    → Ensure CELERY_BROKER_URL matches on web + celery containers")
        
        if check_relay and stats and stats['raw_relayed'] == 0:
            self.stdout.write("    → Check PAYMENT_RELAY_TARGETS on the primary instance.")
            self.stdout.write("    → Verify PAYMENT_RELAY_SECRET matches on both instances.")
            
        if stats and stats.get("raw_unprocessed", 0) > 0:
            self.stdout.write("    → Clear backlog: python manage.py reprocess_messages --days 1")
            self.stdout.write("    → Or test one: python manage.py diagnose_payment_pipeline --reprocess 3")
        self.stdout.write("")

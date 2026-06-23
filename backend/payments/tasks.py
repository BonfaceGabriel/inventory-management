
import os
import logging
import hashlib
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from celery import shared_task
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from .models import RawMessage, Transaction
from .parsers import parse_mpesa_sms
from .serializers import TransactionSerializer
from .services.merchandise_service import MerchandiseService

logger = logging.getLogger(__name__)

@shared_task(
    name='payments.tasks.process_raw_message',
    autoretry_for=(RawMessage.DoesNotExist,),
    max_retries=5,
    default_retry_delay=2,
    soft_time_limit=30,
    time_limit=45,
)
def process_raw_message(message_id):
    """Parse a RawMessage and create a Transaction. Returns a status dict when called directly."""
    try:
        message = RawMessage.objects.get(id=message_id)
        if message.processed:
            logger.info(f"Message {message_id} has already been processed.")
            return {'success': True, 'reason': 'already_processed'}

        parsed_data = parse_mpesa_sms(message.raw_text)

        if parsed_data and parsed_data.get('confidence', 0) > 0.6:
            tx_id = parsed_data['tx_id']
            amount = parsed_data['amount']
            timestamp = parsed_data['timestamp']

            # Compute unique_hash
            hash_string = f"{tx_id}|{amount}|{timestamp}"
            unique_hash = hashlib.sha256(hash_string.encode()).hexdigest()

            try:
                with transaction.atomic():
                    # Get the device's gateway (REQUIRED - all messages must come from registered devices with gateways)
                    device_gateway = message.device.gateway if message.device else None

                    if not device_gateway:
                        logger.warning(
                            f"Message {message_id} from device {message.device} has no gateway assigned. "
                            f"Skipping transaction creation."
                        )
                        message.processed = True
                        message.save(update_fields=['processed'])
                        return {'success': True, 'reason': 'no_gateway'}

                    # Exclude internal transactions from BF SUMA EAGLE SHOP LTD (7974481)
                    sender_name = parsed_data.get('sender_name', '')
                    sender_phone = parsed_data.get('sender_phone', '')
                    
                    if "7974481" in sender_phone or "7974481" in sender_name:
                        message.processed = True
                        message.save(update_fields=['processed'])
                        logger.info(f"Skipping transaction creation for internal sender: {sender_name} ({sender_phone})")
                        return {'success': True, 'reason': 'internal_sender_filtered'}

                    # Create a Transaction record using device's gateway
                    new_transaction = Transaction.objects.create(
                        tx_id=tx_id,
                        amount=amount,
                        sender_name=sender_name,
                        sender_phone=sender_phone,
                        timestamp=timestamp,
                        gateway=device_gateway,  # Gateway resolved from device, not message
                        gateway_type=device_gateway.gateway_type,  # Use gateway's type for legacy compatibility
                        destination_number=parsed_data.get('destination_number', ''),
                        confidence=parsed_data['confidence'],
                        unique_hash=unique_hash,
                        amount_expected=amount
                    )
                    message.transaction = new_transaction
                    message.processed = True
                    message.save()
                    logger.info(f"Successfully processed message {message_id} and created transaction with gateway: {device_gateway.name}")

                    # For Till Merchandise transactions, create a dedicated pending
                    # manual-fulfillment order in the separate merchandise pipeline.
                    MerchandiseService.create_pending_order_for_transaction(
                        new_transaction,
                        device=message.device
                    )

                    # Broadcast new transaction to WebSocket clients
                    _broadcast_transaction_created(new_transaction)

                return {'success': True, 'transaction_id': new_transaction.id}

            except Exception as e:
                logger.warning(
                    f"Could not create transaction for message {message_id}. "
                    f"It might be a duplicate. Error: {e}"
                )
                try:
                    existing_transaction = Transaction.objects.get(unique_hash=unique_hash)
                except Transaction.DoesNotExist:
                    logger.error(
                        f"Message {message_id} failed with non-duplicate error; leaving unprocessed for retry. "
                        f"Error: {e}"
                    )
                    raise
                message.transaction = existing_transaction
                message.processed = True
                message.save(update_fields=['transaction', 'processed'])
                return {'success': True, 'transaction_id': existing_transaction.id, 'reason': 'duplicate'}

        else:
            logger.warning(
                f"Failed to parse message {message_id} with sufficient confidence. "
                f"Marking as processed to avoid infinite retry loop."
            )
            message.processed = True
            message.save(update_fields=['processed'])
            return {'success': True, 'reason': 'parse_failed_ignored'}

    except RawMessage.DoesNotExist:
        logger.error(f"RawMessage with id {message_id} does not exist.")
        return {'success': False, 'reason': 'not_found'}
    except Exception as e:
        logger.error(f"An error occurred while processing message {message_id}: {e}")
        return {'success': False, 'reason': 'error', 'error': str(e)}


@shared_task(
    name='payments.tasks.relay_message_to_branches',
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    soft_time_limit=45,
    time_limit=60,
)
def relay_message_to_branches(self, message_id):
    """
    Fan out a raw SMS message to all configured branch backends.
    Called after local processing on the primary instance.

    Only relays messages from shared gateway types (MPESA_TILL, MERCHANDISE).
    Each target is independent — one failure doesn't block others.
    Retries up to 3 times with 10s delay on failure.
    """
    try:
        message = RawMessage.objects.select_related('device__gateway').get(id=message_id)
    except RawMessage.DoesNotExist:
        logger.error(f"relay_message_to_branches: RawMessage {message_id} not found")
        return {'relayed': False, 'reason': 'message_not_found'}

    gateway = message.device.gateway
    if not gateway:
        logger.warning(f"relay_message_to_branches: no gateway on device {message.device} for message {message_id}")
        return {'relayed': False, 'reason': 'no_gateway'}

    relay_types = getattr(settings, 'PAYMENT_RELAY_GATEWAY_TYPES', ['MPESA_TILL', 'MERCHANDISE'])

    if gateway.gateway_type not in relay_types:
        return {'relayed': False, 'reason': 'gateway_type_not_shared'}

    targets = getattr(settings, 'PAYMENT_RELAY_TARGETS', [])
    relay_secret = getattr(settings, 'PAYMENT_RELAY_SECRET', '')
    branch_name = getattr(settings, 'BRANCH_NAME', 'Main Shop')

    if not targets:
        logger.warning(f"relay_message_to_branches: no targets configured for message {message_id}")
        return {'relayed': False, 'reason': 'no_targets_configured'}

    if not relay_secret:
        logger.warning(f"relay_message_to_branches: PAYMENT_RELAY_SECRET not set — skipping relay for message {message_id}")
        return {'relayed': False, 'reason': 'no_secret'}

    results = []
    all_succeeded = True

    session = requests.Session()
    retries = Retry(
        total=2,
        backoff_factor=1,
        status_forcelist=[502, 503, 504],
        allowed_methods=["POST"]
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))

    for target in targets:
        url = target.get('url', '').rstrip('/') + '/api/v1/messages/relay/'
        target_name = target.get('name', url)
        try:
            payload = {
                'raw_text': message.raw_text,
                'received_at': message.received_at.isoformat(),
                'gateway_type': gateway.gateway_type,
                'source_branch': branch_name,
            }
            resp = session.post(
                url,
                json=payload,
                headers={'X-Relay-Secret': relay_secret},
                timeout=10,
            )
            ok = resp.status_code in (200, 201, 202)
            if not ok:
                all_succeeded = False
            results.append({
                'target': target_name,
                'status': resp.status_code,
                'success': ok,
            })
        except requests.exceptions.RequestException as e:
            all_succeeded = False
            results.append({
                'target': target_name,
                'success': False,
                'error': str(e),
            })

    if not all_succeeded:
        logger.warning(
            f"relay_message_to_branches: {len(results) - sum(r['success'] for r in results)}/"
            f"{len(results)} relay targets failed for message {message_id}. "
            f"Individual per-target HTTP retries have been exhausted. "
            f"The reprocess_stale_raw_messages beat task will catch this."
        )
        # Do NOT retry the entire batch — that would flood the queue with
        # duplicate requests to targets that already succeeded.
        # The beat-driven reprocess_stale_raw_messages task will pick up
        # any unprocessed RawMessages later.

    return {'relayed': all_succeeded, 'results': results}


@shared_task(
    name='payments.tasks.reprocess_stale_raw_messages',
    soft_time_limit=120,
    time_limit=180,
)
def reprocess_stale_raw_messages(max_batch=100, min_age_seconds=120):
    """
    Safety net: re-run processing for messages left unprocessed (e.g. worker was down).
    Scheduled via Celery Beat every 10 minutes.
    """
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(seconds=min_age_seconds)
    stale_ids = list(
        RawMessage.objects.filter(processed=False, created_at__lte=cutoff)
        .order_by('created_at')
        .values_list('id', flat=True)[:max_batch]
    )
    if not stale_ids:
        return {'reprocessed': 0}

    logger.info(f"Reprocessing {len(stale_ids)} stale raw message(s)")
    success = 0
    for message_id in stale_ids:
        result = process_raw_message(message_id)
        if result and result.get('success'):
            success += 1
    return {'reprocessed': success, 'attempted': len(stale_ids)}


def _broadcast_transaction_created(transaction):
    """
    Broadcast a newly created transaction to WebSocket clients.

    Uses async_to_sync from asgiref which properly reuses any existing
    event loop instead of creating a new one each time. This prevents
    Redis connection leaks and RuntimeError crashes in Celery workers.
    """
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.warning("No channel layer configured — skipping broadcast")
            return

        serializer = TransactionSerializer(transaction)
        transaction_data = json.loads(json.dumps(serializer.data, default=str))

        async_to_sync(channel_layer.group_send)(
            'transactions',
            {
                'type': 'transaction.created',
                'transaction': transaction_data,
            }
        )
        logger.info(f"Broadcasted transaction {transaction.tx_id} to WebSocket clients")
    except Exception as e:
        logger.error(f"Failed to broadcast transaction {transaction.tx_id}: {e}")


@shared_task
def generate_daily_report():
    """
    Generate and persist the unified daily report.

    Scheduled via Celery Beat at 20:59:59 UTC (23:59:59 Nairobi).
    Targets the current date in Africa/Nairobi at execution time.
    Uses update_or_create so it is safe to re-run manually.
    """
    from .services.export_service import TransactionExportService
    from .models import GeneratedReport

    report_date = timezone.localtime(timezone.now()).date()
    logger.info(f"Starting daily report generation for {report_date}")

    try:
        # Only persist if no report exists yet for this date.
        # The end-of-day snapshot (23:59) is the authoritative copy and must not be overwritten.
        # On-demand generation via the API endpoint works without touching this record.
        _, created = GeneratedReport.objects.get_or_create(
            report_date=report_date,
            defaults={'report_file': b''},  # placeholder – replaced immediately below
        )
        if created:
            xlsx_buffer = TransactionExportService.generate_unified_report(report_date)
            GeneratedReport.objects.filter(report_date=report_date).update(
                report_file=xlsx_buffer.getvalue()
            )
            logger.info(f"Daily report for {report_date} generated and persisted successfully")
        else:
            logger.info(f"Daily report for {report_date} already exists – skipping overwrite")
    except Exception as e:
        logger.error(f"Failed to generate daily report for {report_date}: {e}")


@shared_task(name='payments.tasks.send_daily_briefing')
def send_daily_briefing():
    from .services.bi_briefing_service import BiBriefingService
    from .bi_telegram_bot import format_briefing, send_telegram_message
    from django.conf import settings

    chat_id = getattr(settings, 'TELEGRAM_CHAT_ID', '')
    if not chat_id:
        logger.warning("TELEGRAM_CHAT_ID not set — skipping EOD briefing")
        return {'sent': False, 'reason': 'no_chat_id'}

    try:
        report_date = timezone.localtime(timezone.now()).date()
        briefing = BiBriefingService.generate_daily_briefing(report_date)
        message = format_briefing(briefing)

        import asyncio
        success = asyncio.run(send_telegram_message(chat_id, message))
        if success:
            logger.info(f"EOD briefing for {report_date} sent successfully")
        else:
            logger.warning(f"Failed to send EOD briefing for {report_date}")
        return {'sent': success, 'date': str(report_date)}
    except Exception as e:
        logger.error(f"Failed to send EOD briefing: {e}")
        return {'sent': False, 'error': str(e)}


@shared_task(name='payments.tasks.send_stock_alerts')
def send_stock_alerts():
    from .services.bi_core_service import BiCoreService
    from .bi_telegram_bot import format_stock_alerts, send_telegram_message
    from django.conf import settings

    chat_id = getattr(settings, 'TELEGRAM_CHAT_ID', '')
    if not chat_id:
        return {'sent': False, 'reason': 'no_chat_id'}

    try:
        alerts = BiCoreService.get_stock_alerts()
        total_critical = alerts['out_of_stock_count'] + alerts['low_stock_count']
        if total_critical == 0:
            logger.info("No stock alerts to send")
            return {'sent': True, 'alerts': 0}

        message = format_stock_alerts(alerts)
        import asyncio
        success = asyncio.run(send_telegram_message(chat_id, message))
        return {'sent': success, 'alerts': total_critical}
    except Exception as e:
        logger.error(f"Failed to send stock alerts: {e}")
        return {'sent': False, 'error': str(e)}


@shared_task(name='payments.tasks.send_branch_summary')
def send_branch_summary():
    from .services.bi_branch_aggregator import BiBranchAggregator
    from .bi_telegram_bot import format_branch_summary, send_telegram_message
    from django.conf import settings

    chat_id = getattr(settings, 'TELEGRAM_CHAT_ID', '')
    if not chat_id:
        return {'sent': False, 'reason': 'no_chat_id'}

    try:
        report_date = timezone.localtime(timezone.now()).date()
        data = BiBranchAggregator.aggregate_branch_revenue(report_date)
        message = format_branch_summary(data)
        import asyncio
        success = asyncio.run(send_telegram_message(chat_id, message))
        return {'sent': success, 'date': str(report_date)}
    except Exception as e:
        logger.error(f"Failed to send branch summary: {e}")
        return {'sent': False, 'error': str(e)}


@shared_task(
    name='payments.tasks.auto_relay_health_check',
    soft_time_limit=30,
    time_limit=45,
)
def auto_relay_health_check():
    """
    Automated relay pipeline health check run by Celery Beat every 5 minutes.

    Counts stale unprocessed relayed RawMessage records and logs warnings
    if the count exceeds a threshold. This serves as an early-warning system
    when the relay pipeline stops processing messages.

    Thresholds:
    - 1-9 stale: logged as WARNING
    - 10+ stale: logged as ERROR (critical degradation)
    """
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(minutes=5)
    stale_count = RawMessage.objects.filter(
        processed=False,
        is_relayed=True,
        created_at__lte=cutoff,
    ).count()

    total_pending = RawMessage.objects.filter(
        processed=False,
        is_relayed=True,
    ).count()

    if stale_count == 0:
        logger.info(f"relay_health_check: OK — 0 stale relayed messages ({total_pending} pending)")
        return {'healthy': True, 'stale': 0, 'pending': total_pending}

    if stale_count >= 10:
        logger.error(
            f"relay_health_check: CRITICAL — {stale_count} stale relayed messages "
            f"({total_pending} pending). Relay pipeline may be stuck."
        )
    else:
        logger.warning(
            f"relay_health_check: DEGRADED — {stale_count} stale relayed messages "
            f"({total_pending} pending)."
        )

    return {'healthy': stale_count < 10, 'stale': stale_count, 'pending': total_pending}

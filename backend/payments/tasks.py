
import os
import logging
import hashlib
import json

# import requests
from celery import shared_task
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import RawMessage, Transaction
from .parsers import parse_mpesa_sms
from .serializers import TransactionSerializer
from .services.merchandise_service import MerchandiseService

logger = logging.getLogger(__name__)

@shared_task(name='payments.tasks.process_raw_message')
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
)
def relay_message_to_branches(self, message_id):
    """
    Fan out a raw SMS message to all configured branch backends.
    Called after local processing on the primary instance.

    Only relays messages from shared gateway types (MPESA_TILL, MERCHANDISE).
    Each target is independent — one failure doesn't block others.
    Retries up to 3 times with 10s delay on failure.
    """
    import requests
    try:
        message = RawMessage.objects.select_related('device__gateway').get(id=message_id)
    except RawMessage.DoesNotExist:
        logger.error(f"relay_message_to_branches: RawMessage {message_id} not found")
        return {'relayed': False, 'reason': 'message_not_found'}

    gateway = message.device.gateway
    if not gateway:
        return {'relayed': False, 'reason': 'no_gateway'}

    relay_types = getattr(settings, 'PAYMENT_RELAY_GATEWAY_TYPES', ['MPESA_TILL', 'MERCHANDISE'])
    if gateway.gateway_type not in relay_types:
        logger.info(
            f"relay_message_to_branches: skipping relay for {gateway.gateway_type} "
            f"(not in {relay_types})"
        )
        return {'relayed': False, 'reason': 'gateway_type_not_shared'}

    targets = getattr(settings, 'PAYMENT_RELAY_TARGETS', [])
    relay_secret = getattr(settings, 'PAYMENT_RELAY_SECRET', '')
    branch_name = getattr(settings, 'BRANCH_NAME', 'Main Shop')

    if not targets:
        return {'relayed': False, 'reason': 'no_targets_configured'}

    if not relay_secret:
        logger.warning("relay_message_to_branches: PAYMENT_RELAY_SECRET not set — skipping relay")
        return {'relayed': False, 'reason': 'no_secret'}

    results = []
    all_succeeded = True

    for target in targets:
        url = target.get('url', '').rstrip('/') + '/api/v1/messages/relay/'
        target_name = target.get('name', url)
        try:
            resp = requests.post(
                url,
                json={
                    'raw_text': message.raw_text,
                    'received_at': message.received_at.isoformat(),
                    'gateway_type': gateway.gateway_type,
                    'source_branch': branch_name,
                },
                headers={'X-Relay-Secret': relay_secret},
                timeout=15,
            )
            ok = resp.status_code in (200, 201, 202)
            if not ok:
                all_succeeded = False
            results.append({
                'target': target_name,
                'status': resp.status_code,
                'success': ok,
            })
            logger.info(
                f"relay to {target_name}: {'ok' if ok else 'failed'} "
                f"(HTTP {resp.status_code})"
            )
        except Exception as e:
            all_succeeded = False
            results.append({
                'target': target_name,
                'success': False,
                'error': str(e),
            })
            logger.warning(f"relay to {target_name} failed: {e}")

    if not all_succeeded:
        raise self.retry(exc=Exception('One or more relay targets failed'))

    return {'relayed': True, 'results': results}


@shared_task(name='payments.tasks.reprocess_stale_raw_messages')
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

    Args:
        transaction: Transaction instance
    """
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            serializer = TransactionSerializer(transaction)
            # Convert to JSON and back to ensure all UUIDs are serialized as strings
            transaction_data = json.loads(json.dumps(serializer.data, default=str))

            async_to_sync(channel_layer.group_send)(
                'transactions',
                {
                    'type': 'transaction.created',
                    'transaction': transaction_data
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
